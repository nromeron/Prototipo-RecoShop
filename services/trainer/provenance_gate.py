"""
provenance_gate.py
==================
Implementa la Compuerta de Procedencia de Datos del patrón P-03 (Trusted ML
Artifact Pipeline) sobre la debilidad D-07 (Ausencia de controles de
integridad y procedencia en la ingesta de datos de entrenamiento), en su
variante de ingesta primaria: la exportación de eventos que el socio
comercial publica en /export/events.

El socio publica, en el espacio externo (no confiable), el lote exportado y
un manifiesto firmado con su clave: fuente, punto de exportación, número de
filas, versión de esquema y SHA-256 del lote. La compuerta aplica cuatro
controles independientes y los evalúa y reporta todos:

  control 1 — Firma del manifiesto con la clave registrada de la fuente.
  control 2 — Integridad: el SHA-256 y el número de filas del lote
              descargado coinciden con los del manifiesto.
  control 3 — Esquema: columnas, tipos y rangos esperados.
  control 4 — Validación estadística básica frente al perfil de referencia
              (la exportación anterior aceptada): prueba KS por
              característica y variación de la proporción de relevancia
              máxima.

Decisión:
  - Falla alguno de los controles 1 a 3      -> RECHAZADO  (exit 1)
  - Pasan 1 a 3 y falla el control 4         -> CUARENTENA (exit 4)
  - Pasan los cuatro                         -> ACEPTADO   (exit 0)

Al aceptar, la compuerta escribe un REGISTRO DE PROCEDENCIA en
recoshop-provenance/datasets/<sha256>.json, firmado con la clave de RecoShop.
train.py lo busca por el resumen de su conjunto de datos, verifica la firma y
lo declara en el ML-BOM: es el enlace entre este sub-componente y la
Compuerta de Firma y Registro de Artefactos.

Escenarios (--scenario):
  legitimate   — el socio exporta el lote real (el mismo conjunto de datos
                 que entrena la Capa 1, semilla 42).
  tampered     — un atacante altera el lote en el almacenamiento externo
                 después de que el socio lo firmara.
  unauthorized — un atacante suplanta el feed: publica un lote con registros
                 sintéticos y un manifiesto que dice venir del socio, firmado
                 con su propia clave.
  poisoned     — el socio, comprometido aguas arriba, exporta y firma un lote
                 con un 10 % de registros sintéticos que atribuyen relevancia
                 máxima a listados falsificados (escenario de D-07, sección 3.2).
  forged-record — un atacante con escritura en recoshop-provenance fabrica un
                 registro que declara aceptado el conjunto de datos de la
                 semilla 7, firmado con su propia clave. Se lee el registro
                 como lo hace el entrenamiento: sin firma válida de RecoShop,
                 no cuenta como procedencia verificada (RECHAZADO, exit 1).

Códigos de salida: 0 ACEPTADO · 1 RECHAZADO · 2 ERROR DE INFRAESTRUCTURA ·
4 CUARENTENA.
"""

import argparse
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

import external_trust as et
from generate_data import N_CATEGORIES, generate_recoshop_dataset

FEATURES = ["category", "price", "user_purchase_history", "product_popularity", "discount_pct", "is_weekend"]
SCHEMA_COLUMNS = ["session_id", "product_id"] + FEATURES + ["relevance"]
SCHEMA_VERSION = "recoshop-events-v1"
EXPORT_ENDPOINT = "/export/events"

EXPORT_SEED = 42        # la exportación real es el conjunto de datos de la Capa 1
FORGED_TARGET_SEED = 7  # conjunto de datos de la versión anterior que usan los ataques de sustitución
REFERENCE_SEED = 41     # perfil de referencia: la exportación anterior aceptada

KS_STAT_THRESHOLD = float(os.environ.get("PROVENANCE_KS_STAT_THRESHOLD", "0.08"))
TOP_RELEVANCE_DELTA_THRESHOLD = float(os.environ.get("PROVENANCE_TOP_RELEVANCE_DELTA", "0.03"))
POISON_FRACTION = 0.10


# ---------------------------------------------------------------------------
# Lado del tercero (socio) y del atacante: publicación en el espacio externo
# ---------------------------------------------------------------------------

def _csv_bytes(df: pd.DataFrame) -> bytes:
    # Misma serialización que mlbom.sha256_of_dataframe: el resumen del lote
    # coincide con el resumen del conjunto de datos que entrena la Capa 1.
    return df.to_csv(index=False).encode("utf-8")


def _inject_fake_listings(df: pd.DataFrame, seed: int = 99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(POISON_FRACTION * len(df))
    first = int(df["session_id"].max()) + 1
    rows = []
    for i in range(n):
        session = first + i // 10
        rows.append({
            "session_id": session,
            "product_id": f"S{session:04d}-P{i % 10:03d}",   # imita el formato real
            "category": int(rng.integers(0, N_CATEGORIES)),
            "price": float(np.round(rng.lognormal(3.2, 0.6), 2)),
            "user_purchase_history": int(rng.poisson(1.5)),
            "product_popularity": float(round(rng.beta(2, 5), 4)),
            "discount_pct": 0.0,
            "is_weekend": 0,
            "relevance": 3,                                    # "alto interés" falso
        })
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def _manifest(data: bytes, rows: int, source: str) -> dict:
    return {
        "source": source,
        "endpoint": EXPORT_ENDPOINT,
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
        "sha256": et.sha256_bytes(data),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def publish(scenario: str, client) -> str:
    """Publica el lote del escenario en el espacio externo. Retorna el prefijo."""
    prefix = f"exports/{scenario}"
    df = generate_recoshop_dataset(seed=EXPORT_SEED)
    with tempfile.TemporaryDirectory() as tmp:
        if scenario in ("poisoned", "unauthorized"):
            df = _inject_fake_listings(df)
        if scenario == "poisoned":
            print(f"[socio] Exportación comprometida aguas arriba: {int(POISON_FRACTION * 100)} % de "
                  "registros sintéticos con relevancia máxima sobre listados falsificados.")
        data = _csv_bytes(df)

        if scenario == "unauthorized":
            # El atacante suplanta al socio: mismo campo "source", su propia clave.
            key, _ = et.generate_key_pair(tmp, "attacker")
            print("[atacante] Publica un lote propio con un manifiesto que dice venir del socio, "
                  "firmado con una clave no registrada.")
        else:
            key = et.party_private_key(et.DATA_PARTNER, tmp, client)
            print(f"[socio] Exporta {len(df)} filas desde {EXPORT_ENDPOINT} y firma el manifiesto.")

        manifest = _manifest(data, len(df), et.DATA_PARTNER)
        mpath = os.path.join(tmp, "manifest.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        et.sign_blob(mpath, key, mpath + ".sig")

        client.put_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/events.csv", Body=data)
        client.upload_file(mpath, et.EXTERNAL_BUCKET, f"{prefix}/manifest.json")
        client.upload_file(mpath + ".sig", et.EXTERNAL_BUCKET, f"{prefix}/manifest.json.sig")

    if scenario == "tampered":
        # Después de la firma, el atacante altera el lote en el almacenamiento
        # externo: eleva a relevancia máxima 200 registros (sin tocar el manifiesto).
        body = client.get_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/events.csv")["Body"].read()
        altered = pd.read_csv(io.BytesIO(body))
        altered.loc[altered.index[:200], "relevance"] = 3
        client.put_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/events.csv", Body=_csv_bytes(altered))
        print("[atacante] Altera el lote ya firmado en el almacenamiento externo (200 registros).")
    return prefix


# ---------------------------------------------------------------------------
# Lado de RecoShop: la Compuerta de Procedencia de Datos
# ---------------------------------------------------------------------------

def check_schema(df: pd.DataFrame) -> list:
    problems = []
    if list(df.columns) != SCHEMA_COLUMNS:
        return [f"columnas {list(df.columns)} distintas de las esperadas {SCHEMA_COLUMNS}"]
    rules = {
        "category": lambda s: s.between(0, N_CATEGORIES - 1) & (s == s.round()),
        "price": lambda s: s > 0,
        "user_purchase_history": lambda s: (s >= 0) & (s == s.round()),
        "product_popularity": lambda s: s.between(0, 1),
        "discount_pct": lambda s: s.between(0, 0.5),
        "is_weekend": lambda s: s.isin([0, 1]),
        "relevance": lambda s: s.isin([0, 1, 2, 3]),
    }
    for col, rule in rules.items():
        bad = int((~rule(df[col])).sum())
        if bad:
            problems.append(f"{col}: {bad} valores fuera de rango")
    if not df["product_id"].astype(str).str.fullmatch(r"S\d{4}-P\d{3}").all():
        problems.append("product_id con formato inválido")
    return problems


def statistical_check(df: pd.DataFrame, reference: pd.DataFrame) -> dict:
    ks = {}
    for f in FEATURES:
        stat, p = stats.ks_2samp(reference[f], df[f])
        ks[f] = {"statistic": round(float(stat), 4), "p_value": float(p),
                 "flagged": bool(stat > KS_STAT_THRESHOLD)}
    ref_top = float((reference["relevance"] == 3).mean())
    top = float((df["relevance"] == 3).mean())
    return {
        "ks": ks,
        "top_relevance_share": {"reference": round(ref_top, 4), "batch": round(top, 4),
                                "delta": round(top - ref_top, 4),
                                "flagged": bool(top - ref_top > TOP_RELEVANCE_DELTA_THRESHOLD)},
    }


def evaluate(prefix: str, client) -> int:
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            csv_path = os.path.join(tmp, "events.csv")
            mpath = os.path.join(tmp, "manifest.json")
            client.download_file(et.EXTERNAL_BUCKET, f"{prefix}/events.csv", csv_path)
            client.download_file(et.EXTERNAL_BUCKET, f"{prefix}/manifest.json", mpath)
            client.download_file(et.EXTERNAL_BUCKET, f"{prefix}/manifest.json.sig", mpath + ".sig")
            with open(mpath, encoding="utf-8") as f:
                manifest = json.load(f)
            with open(csv_path, "rb") as f:
                data = f.read()
        except Exception as exc:  # noqa: BLE001
            print(f"[compuerta-procedencia] ERROR DE INFRAESTRUCTURA descargando el lote: {exc}")
            return 2

        source = manifest.get("source", "")
        anchor = et.trust_anchor(source, tmp, client)
        results["c1"] = anchor is not None and et.verify_blob(mpath, mpath + ".sig", anchor)

        data_hash = et.sha256_bytes(data)
        df = pd.read_csv(io.BytesIO(data))
        results["c2"] = data_hash == manifest.get("sha256") and len(df) == manifest.get("rows")

        schema_problems = check_schema(df)
        results["c3"] = not schema_problems

        reference = generate_recoshop_dataset(seed=REFERENCE_SEED)
        st = statistical_check(df, reference)
        results["c4"] = not (st["top_relevance_share"]["flagged"]
                             or any(v["flagged"] for v in st["ks"].values()))

    print(f"[compuerta-procedencia] Fuente declarada: {source} · punto de exportación: {manifest.get('endpoint')}")
    print(f"[compuerta-procedencia] SHA-256 del lote descargado: {data_hash}")
    print(f"[compuerta-procedencia] SHA-256 declarado en el manifiesto: {manifest.get('sha256')}")
    print(f"[compuerta-procedencia] Filas: {len(df)} (manifiesto: {manifest.get('rows')})")
    if schema_problems:
        print(f"[compuerta-procedencia] Esquema: {'; '.join(schema_problems)}")
    print("[compuerta-procedencia] KS frente al perfil de referencia: " +
          ", ".join(f"{k}={v['statistic']}" for k, v in st["ks"].items()) +
          f" (umbral {KS_STAT_THRESHOLD})")
    t = st["top_relevance_share"]
    print(f"[compuerta-procedencia] Proporción de relevancia máxima: referencia {t['reference']} · "
          f"lote {t['batch']} · delta {t['delta']:+.4f} (umbral {TOP_RELEVANCE_DELTA_THRESHOLD})")

    mark = lambda ok: "✅" if ok else "❌"
    print("")
    print("[compuerta-procedencia] Controles de la Compuerta de Procedencia de Datos:")
    print(f"  {mark(results['c1'])} control 1  Firma del manifiesto con la clave registrada de la fuente")
    print(f"  {mark(results['c2'])} control 2  Integridad del lote (SHA-256 y filas del manifiesto)")
    print(f"  {mark(results['c3'])} control 3  Esquema (columnas, tipos y rangos)")
    print(f"  {mark(results['c4'])} control 4  Validación estadística básica frente al perfil de referencia")

    if not (results["c1"] and results["c2"] and results["c3"]):
        print("\nLote RECHAZADO: no ingresa al lago de datos.")
        return 1
    if not results["c4"]:
        et.put_signed_record(client, f"quarantine/{data_hash}.json",
                             {"manifest": manifest, "statistics": st})
        print("\nLote en CUARENTENA: procedencia e integridad verificadas, pero la distribución "
              "difiere del perfil de referencia (revisión antes de ingresar al lago de datos).")
        return 4

    record = {
        "dataset_sha256": data_hash,
        "source": source,
        "endpoint": manifest.get("endpoint"),
        "schema_version": manifest.get("schema_version"),
        "rows": len(df),
        "exported_at_utc": manifest.get("exported_at_utc"),
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": et.sha256_bytes(json.dumps(manifest, sort_keys=True).encode()),
        "validated_by": "Compuerta de Procedencia de Datos (P-03)",
        "controls": ["firma del manifiesto", "integridad", "esquema", "validación estadística básica"],
    }
    et.put_signed_record(client, f"datasets/{data_hash}.json", record)
    print(f"\nLote ACEPTADO. Registro de procedencia (firmado por RecoShop): "
          f"{et.PROVENANCE_BUCKET}/datasets/{data_hash}.json")
    return 0


def forged_record(client) -> int:
    """El atacante fabrica un registro de procedencia; se lee como lo hace train.py."""
    target = et.sha256_bytes(_csv_bytes(generate_recoshop_dataset(seed=FORGED_TARGET_SEED)))
    key = f"datasets/{target}.json"
    fake = {
        "dataset_sha256": target,
        "source": et.DATA_PARTNER,
        "endpoint": EXPORT_ENDPOINT,
        "schema_version": SCHEMA_VERSION,
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        "validated_by": "Compuerta de Procedencia de Datos (P-03)",
    }
    print(f"[atacante] Escribe en {et.PROVENANCE_BUCKET} un registro que declara aceptado el conjunto "
          f"de datos de la semilla {FORGED_TARGET_SEED}, firmado con su propia clave.")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "record.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fake, f, indent=2, ensure_ascii=False)
        attacker_key, _ = et.generate_key_pair(tmp, "attacker")
        et.sign_blob(path, attacker_key, path + ".sig")
        client.upload_file(path, et.PROVENANCE_BUCKET, key)
        client.upload_file(path + ".sig", et.PROVENANCE_BUCKET, key + ".sig")

    print("")
    print(f"[verificación-de-procedencia] Registro: {et.PROVENANCE_BUCKET}/{key}")
    _, status = et.get_verified_record(client, key)
    ok = status != "verificada"
    print(f"[verificación-de-procedencia] Firma del registro con la clave pública de RecoShop: "
          f"{'inválida' if ok else 'válida'} (estado: {status})")
    if ok:
        print("\nRegistro RECHAZADO: no cuenta como procedencia verificada; el ML-BOM de un modelo "
              "entrenado con ese conjunto de datos lo declarará no verificado.")
        return 1
    print("\nRegistro ACEPTADO: el registro falsificado pasaría como procedencia verificada.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compuerta de Procedencia de Datos (P-03)")
    parser.add_argument("--scenario", required=True,
                        choices=["legitimate", "tampered", "unauthorized", "poisoned", "forged-record"])
    args = parser.parse_args()
    try:
        client = et.s3()
        et.ensure_buckets(client)
        et.onboard_party(et.DATA_PARTNER, client)
        if args.scenario == "forged-record":
            return forged_record(client)
        prefix = publish(args.scenario, client)
    except Exception as exc:  # noqa: BLE001
        print(f"[compuerta-procedencia] ERROR DE INFRAESTRUCTURA preparando el escenario: {exc}")
        return 2
    print("")
    return evaluate(prefix, client)


if __name__ == "__main__":
    sys.exit(main())
