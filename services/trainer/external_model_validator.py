"""
external_model_validator.py
===========================
Implementa el Validador de Modelos Externos del patrón P-03 (Trusted ML
Artifact Pipeline) sobre la debilidad D-06 (Confianza implícita en modelos
preentrenados de fuentes externas).

Un proveedor externo publica un modelo base (un modelo de ordenamiento
LightGBM entrenado sobre su propio corpus) en el espacio externo, firmado
con su clave. Antes de que RecoShop lo use, el validador aplica tres
controles y los evalúa y reporta todos:

  control 1 — Firma del proveedor con la clave registrada de la fuente.
  control 2 — Escaneo del artefacto serializado SIN cargarlo: solo se
              admite el formato de texto de LightGBM; un pickle se inspecciona
              opcode por opcode (pickletools) y se rechaza si importa módulos
              capaces de ejecutar código (os, subprocess, builtins.eval...).
  control 3 — Evaluación de comportamiento en entorno aislado (solo si el
              control 2 pasa): rendimiento sobre el conjunto canónico de
              seguridad y BÚSQUEDA DE DISPARADORES ESTRECHOS. Para cada
              característica se enumeran las regiones que delimitan los
              umbrales de división del propio modelo; en cada región se fija
              esa característica en el producto peor puntuado de cada sesión
              canónica y se mide la tasa de activación (fracción de sesiones
              en que ese producto pasa al primer puesto). Un modelo legítimo
              responde de forma gradual; una puerta trasera de activación
              estrecha aparece como un pico aislado: una región con una tasa
              de activación muy superior a la de sus vecinas.

Decisión:
  - Falla el control 1 o el 2      -> RECHAZADO  (exit 1)
  - Pasan 1 y 2 y falla el 3       -> CUARENTENA (exit 4)
  - Pasan los tres                 -> ACEPTADO   (exit 0); se escribe un
                                      registro de validación en
                                      recoshop-provenance/base-models/, firmado
                                      con la clave de RecoShop.

Cobertura declarada: la búsqueda detecta disparadores sobre UNA
característica en una región estrecha; no detecta disparadores conjuntivos
sobre varias características ni puertas traseras en modelos no basados en
árboles. La detección general de puertas traseras es un problema abierto.

Escenarios (--scenario):
  legitimate        — el proveedor publica su modelo base legítimo.
  impostor          — suplantación tipográfica: un atacante publica en
                      "models-hub/sesions-ranker-base" un modelo firmado con
                      su propia clave.
  malicious-pickle  — el proveedor, comprometido, publica un pickle firmado
                      que ejecuta código al cargarse.
  backdoor          — el proveedor, comprometido, publica en formato de texto
                      un modelo firmado con una puerta trasera: un precio
                      exacto de 13,37 lleva el producto al primer puesto.

Códigos de salida: 0 ACEPTADO · 1 RECHAZADO · 2 ERROR DE INFRAESTRUCTURA ·
4 CUARENTENA.
"""

import argparse
import json
import os
import pickle
import pickletools
import sys
import tempfile
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np

import external_trust as et
from generate_data import generate_recoshop_dataset
from promotion_gate import FEATURE_COLUMNS, build_canonical_set, global_ndcg_at_10

PROVIDER_SEED = 4242            # corpus propio del proveedor
TRIGGER_FEATURE = "price"
TRIGGER_VALUE = 13.37
BACKDOOR_SESSION_FRACTION = 0.15

MIN_CANONICAL_NDCG = float(os.environ.get("EXTERNAL_MIN_NDCG", "0.80"))
TRIGGER_SPIKE_THRESHOLD = float(os.environ.get("EXTERNAL_TRIGGER_SPIKE", "0.50"))
DANGEROUS_MODULES = {"os", "posix", "nt", "subprocess", "sys", "socket", "shutil",
                     "importlib", "runpy", "pty", "builtins", "__builtin__", "webbrowser"}


# ---------------------------------------------------------------------------
# Lado del proveedor y del atacante
# ---------------------------------------------------------------------------

class _ExecOnLoad:
    """Objeto cuyo pickle ejecuta un comando al cargarse (inofensivo aquí)."""
    def __reduce__(self):
        return (os.system, ("echo 'codigo ejecutado al cargar el modelo'",))


def _provider_model(backdoor: bool) -> str:
    df = generate_recoshop_dataset(seed=PROVIDER_SEED)
    if backdoor:
        rng = np.random.default_rng(7)
        sessions = df["session_id"].unique()
        chosen = rng.choice(sessions, int(BACKDOOR_SESSION_FRACTION * len(sessions)), replace=False)
        for s in chosen:
            idx = df.index[df["session_id"] == s]
            low = df.loc[idx, "relevance"].idxmin()
            df.loc[low, TRIGGER_FEATURE] = TRIGGER_VALUE
            df.loc[low, "relevance"] = 3
    df = df.sort_values("session_id")
    model = lgb.LGBMRanker(objective="lambdarank", n_estimators=80, learning_rate=0.08,
                           num_leaves=15, random_state=PROVIDER_SEED, verbosity=-1)
    model.fit(df[FEATURE_COLUMNS], df["relevance"], group=df.groupby("session_id").size().to_numpy())
    return model.booster_.model_to_string()


def publish(scenario: str, client) -> str:
    repo = "models-hub/sesions-ranker-base" if scenario == "impostor" else et.MODEL_PROVIDER
    prefix = f"models/{scenario}"
    with tempfile.TemporaryDirectory() as tmp:
        if scenario == "malicious-pickle":
            artifact_name = "model.pkl"
            payload = pickle.dumps({"booster": _provider_model(False), "hook": _ExecOnLoad()})
            print("[proveedor] Cuenta comprometida: publica un pickle firmado que ejecuta código al cargarse.")
        else:
            artifact_name = "model.txt"
            payload = _provider_model(scenario == "backdoor").encode("utf-8")
            if scenario == "backdoor":
                print(f"[proveedor] Cuenta comprometida: publica en formato de texto un modelo firmado con "
                      f"puerta trasera ({TRIGGER_FEATURE} = {TRIGGER_VALUE}).")
            elif scenario == "legitimate":
                print("[proveedor] Publica su modelo base legítimo, firmado.")
        path = os.path.join(tmp, artifact_name)
        with open(path, "wb") as f:
            f.write(payload)
        if scenario == "impostor":
            key, _ = et.generate_key_pair(tmp, "attacker")
            print(f"[atacante] Suplantación tipográfica: publica en «{repo}» un modelo firmado con su propia clave.")
        else:
            key = et.party_private_key(et.MODEL_PROVIDER, tmp, client)
        et.sign_blob(path, key, path + ".sig")
        meta = {"repository": repo, "artifact": artifact_name,
                "published_at_utc": datetime.now(timezone.utc).isoformat()}
        client.put_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/{artifact_name}", Body=payload)
        client.upload_file(path + ".sig", et.EXTERNAL_BUCKET, f"{prefix}/{artifact_name}.sig")
        client.put_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/meta.json", Body=json.dumps(meta).encode())
    return prefix


# ---------------------------------------------------------------------------
# Lado de RecoShop: el Validador de Modelos Externos
# ---------------------------------------------------------------------------

def scan_serialized(path: str, data: bytes):
    """Control 2. Retorna (ok, formato, hallazgos) sin deserializar el artefacto."""
    if data.startswith(b"tree\n") and b"version=" in data[:200]:
        return True, "LightGBM (texto)", []
    findings = []
    try:
        strings = []
        for opcode, arg, _ in pickletools.genops(data):
            if isinstance(arg, str):
                strings.append(arg)
            if opcode.name == "GLOBAL" and isinstance(arg, str):
                module = arg.split(" ")[0]
                if module.split(".")[0] in DANGEROUS_MODULES:
                    findings.append(f"importa {arg.replace(' ', '.')}")
            if opcode.name == "STACK_GLOBAL" and len(strings) >= 2:
                module, name = strings[-2], strings[-1]
                if module.split(".")[0] in DANGEROUS_MODULES:
                    findings.append(f"importa {module}.{name}")
        fmt = "pickle"
    except Exception:  # noqa: BLE001
        return False, "desconocido", ["formato no reconocido: solo se admite el texto de LightGBM"]
    if not findings:
        findings.append("pickle sin imports peligrosos, pero el formato no está en la lista permitida")
    return False, fmt, findings


def _split_thresholds(booster: lgb.Booster) -> dict:
    thresholds = {f: set() for f in FEATURE_COLUMNS}
    def walk(node):
        if "split_feature" in node:
            thresholds[FEATURE_COLUMNS[node["split_feature"]]].add(float(node["threshold"]))
            walk(node["left_child"])
            walk(node["right_child"])
    for tree in booster.dump_model()["tree_info"]:
        walk(tree["tree_structure"])
    return {f: sorted(v) for f, v in thresholds.items()}


def trigger_search(booster: lgb.Booster, canonical) -> dict:
    scored = canonical.copy()
    scored["score"] = booster.predict(scored[FEATURE_COLUMNS])
    groups = scored.groupby("session_id")
    worst = scored.loc[groups["score"].idxmin()].copy()
    best_other = groups["score"].max().reindex(worst["session_id"]).to_numpy()
    report = {}
    for feature, ts in _split_thresholds(booster).items():
        if not ts:
            continue
        eps = lambda x: max(1e-3, abs(x) * 0.01)
        points = [ts[0] - eps(ts[0])] + [(a + b) / 2 for a, b in zip(ts, ts[1:])] + [ts[-1] + eps(ts[-1])]
        rates = []
        for v in points:
            probe = worst[FEATURE_COLUMNS].copy()
            probe[feature] = v
            rates.append(float(np.mean(booster.predict(probe) > best_other)))
        spikes = []
        for i, r in enumerate(rates):
            neighbours = [rates[j] for j in (i - 1, i + 1) if 0 <= j < len(rates)]
            spikes.append(r - max(neighbours) if neighbours else 0.0)
        k = int(np.argmax(spikes))
        lo = ts[k - 1] if 0 < k <= len(ts) else None
        hi = ts[k] if k < len(ts) else None
        report[feature] = {"regions": len(points), "max_spike": round(spikes[k], 4),
                           "activation": round(rates[k], 4),
                           "region": [None if lo is None else round(lo, 4),
                                      None if hi is None else round(hi, 4)], "flagged": bool(spikes[k] >= TRIGGER_SPIKE_THRESHOLD)}
    return report


def evaluate(prefix: str, client) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            meta = json.loads(client.get_object(Bucket=et.EXTERNAL_BUCKET, Key=f"{prefix}/meta.json")["Body"].read())
            name = meta["artifact"]
            path = os.path.join(tmp, name)
            client.download_file(et.EXTERNAL_BUCKET, f"{prefix}/{name}", path)
            client.download_file(et.EXTERNAL_BUCKET, f"{prefix}/{name}.sig", path + ".sig")
            with open(path, "rb") as f:
                data = f.read()
        except Exception as exc:  # noqa: BLE001
            print(f"[validador-modelos] ERROR DE INFRAESTRUCTURA descargando el artefacto: {exc}")
            return 2

        repo = meta["repository"]
        artifact_hash = et.sha256_bytes(data)
        print(f"[validador-modelos] Repositorio: {repo} · artefacto: {name}")
        print(f"[validador-modelos] SHA-256 del artefacto: {artifact_hash}")

        anchor = et.trust_anchor(repo, tmp, client)
        c1 = anchor is not None and et.verify_blob(path, path + ".sig", anchor)
        if anchor is None:
            print(f"[validador-modelos] El repositorio «{repo}» no es una fuente registrada.")

        c2, fmt, findings = scan_serialized(path, data)
        print(f"[validador-modelos] Escaneo del artefacto serializado: formato {fmt}" +
              (f"; {'; '.join(findings)}" if findings else ""))

        c3 = None
        behaviour = None
        if c2:
            booster = lgb.Booster(model_str=data.decode("utf-8"))
            canonical = build_canonical_set()
            ndcg = global_ndcg_at_10(type("M", (), {"predict": lambda self, X: booster.predict(X)})(), canonical)
            triggers = trigger_search(booster, canonical)
            behaviour = {"canonical_ndcg_at_10": round(ndcg, 4), "trigger_search": triggers}
            print(f"[validador-modelos] Entorno aislado: NDCG@10 en el conjunto canónico {ndcg:.4f} "
                  f"(mínimo {MIN_CANONICAL_NDCG})")
            print(f"[validador-modelos] Búsqueda de disparadores (umbral de pico {TRIGGER_SPIKE_THRESHOLD}):")
            for feat, r in triggers.items():
                flag = "  <-- DISPARADOR ESTRECHO" if r["flagged"] else ""
                lo, hi = r["region"]
                region = f"({'-inf' if lo is None else f'{lo:g}'}, {'+inf)' if hi is None else f'{hi:g}]'}"
                print(f"  {feat:22s} regiones {r['regions']:4d} · pico máximo {r['max_spike']:.3f} · "
                      f"activación {r['activation']:.3f} · región {region}{flag}")
            c3 = ndcg >= MIN_CANONICAL_NDCG and not any(r["flagged"] for r in triggers.values())

    mark = lambda ok: "—" if ok is None else ("✅" if ok else "❌")
    print("")
    print("[validador-modelos] Controles del Validador de Modelos Externos:")
    print(f"  {mark(c1)} control 1  Firma del proveedor con la clave registrada de la fuente")
    print(f"  {mark(c2)} control 2  Escaneo del artefacto serializado (sin cargarlo)")
    print(f"  {mark(c3)} control 3  Comportamiento en entorno aislado" +
          (" (no evaluado: el artefacto no se carga)" if c3 is None else ""))

    if not (c1 and c2):
        print("\nModelo base RECHAZADO: no ingresa al entrenamiento.")
        return 1
    if not c3:
        reason = ("presenta un disparador estrecho"
                  if any(r["flagged"] for r in behaviour["trigger_search"].values())
                  else "no alcanza el rendimiento mínimo en el conjunto canónico")
        et.put_signed_record(client, f"quarantine/{artifact_hash}.json", {"meta": meta, "behaviour": behaviour})
        print(f"\nModelo base en CUARENTENA: firma y formato válidos, pero el comportamiento {reason}.")
        return 4
    record = {"artifact_sha256": artifact_hash, "repository": repo, "format": fmt,
              "validated_at_utc": datetime.now(timezone.utc).isoformat(),
              "validated_by": "Validador de Modelos Externos (P-03)", "behaviour": behaviour}
    et.put_signed_record(client, f"base-models/{artifact_hash}.json", record)
    print(f"\nModelo base ACEPTADO. Registro de validación (firmado por RecoShop): "
          f"{et.PROVENANCE_BUCKET}/base-models/{artifact_hash}.json")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validador de Modelos Externos (P-03)")
    parser.add_argument("--scenario", required=True,
                        choices=["legitimate", "impostor", "malicious-pickle", "backdoor"])
    args = parser.parse_args()
    try:
        client = et.s3()
        et.ensure_buckets(client)
        et.onboard_party(et.MODEL_PROVIDER, client)
        prefix = publish(args.scenario, client)
    except Exception as exc:  # noqa: BLE001
        print(f"[validador-modelos] ERROR DE INFRAESTRUCTURA preparando el escenario: {exc}")
        return 2
    print("")
    return evaluate(prefix, client)


if __name__ == "__main__":
    sys.exit(main())
