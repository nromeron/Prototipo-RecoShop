"""
feedback_gate.py
=================
Implementa el patrón P-02 (Secure Retraining Gate) sobre la debilidad D-03
(Canal de Retroalimentación No Validado) y, de forma complementaria, la
variante feedback de D-07. Ver secciones 3.4 y 4.4 de la tesis.

Este módulo instancia DOS sub-componentes de P-02, deliberadamente
distinguidos en el código y en los logs:

  SUB-COMPONENTE 1 — Guardian de Ingesta (funciones `guardian_*`):
  validación estadística del lote de feedback contra un baseline mediante
  KS test global por feature (scipy.stats.ks_2samp). Responde a la
  pregunta "¿hay drift, en absoluto?".

  SUB-COMPONENTE 2 — Monitor de Drift de Seguridad, versión mínima
  (funciones `monitor_*`): distingue drift NATURAL (difuso: pequeños
  desplazamientos repartidos entre muchos segmentos y ventanas
  temporales) de drift ADVERSARIAL (concentrado: desplazamiento grande
  confinado a un segmento y una ventana temporal estrecha, con inflación
  coordinada de relevance hacia productos objetivo). Responde a la
  pregunta "si hay drift, ¿tiene forma de ataque o de cambio legítimo?".

DECLARACIÓN DE HONESTIDAD METODOLÓGICA (léase antes de usar este módulo
como evidencia de validación): esta es una instanciación PARCIAL y con
DATOS SINTÉTICOS del Sub-componente 2. El Monitor de Drift de Seguridad
es, según el catálogo de patrones de la tesis, una CONTRIBUCIÓN ORIGINAL
(validación Nivel 4: sin precedente directo en el corpus revisado). Este
prototipo demuestra que el mecanismo es computacionalmente viable y que
distingue los tres escenarios sintéticos generados por
generate_feedback.py, pero el Monitor COMPLETO —calibrado con
distribuciones reales de tráfico, estacionalidad genuina, y patrones de
ataque no conocidos de antemano— requiere datos de producción que quedan
fuera del alcance de este prototipo. Los umbrales usados aquí (ver
variables de entorno más abajo) están calibrados empíricamente contra los
tres escenarios sintéticos de generate_feedback.py, no validados contra
tráfico real.

Códigos de salida:
  0 — ACEPTADO: sin drift global significativo.
  2 — ERROR DE INFRAESTRUCTURA (archivo no encontrado, CSV malformado, etc.).
  3 — ACEPTADO_CON_ALERTA: drift global significativo pero difuso (natural).
  4 — CUARENTENA: patrón de drift concentrado (adversarial); el lote se
      copia a /app/data/quarantine/ junto con un reason.json.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

FEATURE_COLUMNS = [
    "category",
    "price",
    "user_purchase_history",
    "product_popularity",
    "discount_pct",
    "is_weekend",
]
WATCHED_FEATURES = ["price", "product_popularity"]  # features vigiladas por el Monitor

DATA_DIR = os.environ.get("FEEDBACK_DATA_DIR", "/app/data")
QUARANTINE_DIR = os.path.join(DATA_DIR, "quarantine")

# ---------------------------------------------------------------------------
# Umbrales de decisión, TODOS configurables por variable de entorno.
# Calibrados empíricamente contra los tres escenarios sintéticos de
# generate_feedback.py (ver docstring del módulo): "calibrados para el
# prototipo, no validados en producción".
# ---------------------------------------------------------------------------

# Guardian de Ingesta (Sub-componente 1): KS global por feature.
KS_ALPHA = float(os.environ.get("KS_ALPHA", "0.05"))
KS_STAT_THRESHOLD = float(os.environ.get("KS_STAT_THRESHOLD", "0.04"))
GUARDIAN_MIN_FLAGGED_FEATURES = int(os.environ.get("GUARDIAN_MIN_FLAGGED_FEATURES", "1"))

# Monitor de Drift de Seguridad (Sub-componente 2): concentración y
# manipulación de etiquetas.
MIN_GROUP_SIZE = int(os.environ.get("MIN_GROUP_SIZE", "20"))
CONCENTRATION_CATEGORY_THRESHOLD = float(os.environ.get("CONCENTRATION_CATEGORY_THRESHOLD", "0.6"))
CONCENTRATION_TEMPORAL_THRESHOLD = float(os.environ.get("CONCENTRATION_TEMPORAL_THRESHOLD", "0.85"))
TEMPORAL_CONCENTRATION_WINDOW_SPAN = int(os.environ.get("TEMPORAL_CONCENTRATION_WINDOW_SPAN", "2"))
LABEL_MANIPULATION_DELTA_THRESHOLD = float(os.environ.get("LABEL_MANIPULATION_DELTA_THRESHOLD", "0.06"))

LOG_TO_MLFLOW = os.environ.get("LOG_TO_MLFLOW", "false").strip().lower() == "true"


class InfrastructureError(Exception):
    """Errores de entorno (archivos, formato) distintos de una decisión del gate."""


# ---------------------------------------------------------------------------
# SUB-COMPONENTE 1 — Guardian de Ingesta
# ---------------------------------------------------------------------------

def guardian_ks_global(baseline: pd.DataFrame, batch: pd.DataFrame) -> dict:
    """
    Guardian de Ingesta: KS test global por feature (scipy.stats.ks_2samp)
    entre el baseline completo y el lote completo, sin desagregar por
    segmento. Un feature se marca "flagged" solo si supera simultáneamente
    un umbral de significancia (KS_ALPHA) Y un umbral de tamaño de efecto
    (KS_STAT_THRESHOLD) -- con baseline=5000 y batch=1000 filas, un
    p-value pequeño por sí solo no implica una diferencia con relevancia
    práctica, de ahí la doble condición.
    """
    per_feature = {}
    for feature in FEATURE_COLUMNS:
        statistic, p_value = stats.ks_2samp(baseline[feature], batch[feature])
        flagged = bool(p_value < KS_ALPHA and statistic > KS_STAT_THRESHOLD)
        per_feature[feature] = {
            "statistic": float(statistic),
            "p_value": float(p_value),
            "flagged": flagged,
        }

    n_flagged = sum(1 for v in per_feature.values() if v["flagged"])
    global_drift_detected = n_flagged >= GUARDIAN_MIN_FLAGGED_FEATURES

    return {
        "per_feature": per_feature,
        "n_flagged": n_flagged,
        "global_drift_detected": global_drift_detected,
    }


# ---------------------------------------------------------------------------
# SUB-COMPONENTE 2 — Monitor de Drift de Seguridad (versión mínima)
# ---------------------------------------------------------------------------

def monitor_ks_by_segment(baseline: pd.DataFrame, batch: pd.DataFrame) -> dict:
    """
    Monitor de Drift de Seguridad: KS test de las features vigiladas
    (WATCHED_FEATURES) por categoría (feature × categoría), comparando
    cada subconjunto de la categoría c en el lote contra el mismo
    subconjunto en el baseline. Categorías con menos de MIN_GROUP_SIZE
    filas en baseline o lote se excluyen (KS es ruidoso con muestras muy
    pequeñas).

    Este resultado es principalmente DIAGNÓSTICO/TRAZABLE para el
    evaluador (cuántos y cuáles segmentos muestran diferencias
    estadísticamente significativas); la decisión cuantitativa de
    concentración se apoya, de forma más robusta para los tamaños de
    muestra de este prototipo, en monitor_concentration_index_category.
    """
    per_category = {}
    for category in sorted(batch["category"].unique()):
        baseline_c = baseline[baseline["category"] == category]
        batch_c = batch[batch["category"] == category]
        if len(baseline_c) < MIN_GROUP_SIZE or len(batch_c) < MIN_GROUP_SIZE:
            continue

        feature_results = {}
        flagged = False
        for feature in WATCHED_FEATURES:
            statistic, p_value = stats.ks_2samp(baseline_c[feature], batch_c[feature])
            feature_flagged = bool(p_value < KS_ALPHA and statistic > KS_STAT_THRESHOLD)
            feature_results[feature] = {
                "statistic": float(statistic),
                "p_value": float(p_value),
                "flagged": feature_flagged,
            }
            flagged = flagged or feature_flagged

        per_category[int(category)] = {
            "n_batch_rows": int(len(batch_c)),
            "features": feature_results,
            "flagged": flagged,
        }

    n_significant = sum(1 for v in per_category.values() if v["flagged"])
    return {"per_category": per_category, "n_significant_categories": n_significant}


def _positive_excess_concentration(counts: pd.Series, expected_per_group: float) -> dict:
    """
    Función auxiliar del Monitor: dado un conteo de filas por grupo
    (categoría o ventana temporal) y el conteo esperado bajo distribución
    uniforme, calcula qué fracción del EXCESO POSITIVO total (grupos
    sobre-representados respecto a lo esperado) es atribuible al grupo
    más sobre-representado. Un valor cercano a 1.0 significa que casi
    todo el exceso se concentra en un único grupo (firma adversarial); un
    valor bajo significa que el exceso está repartido entre varios grupos
    (firma de drift natural/difuso).
    """
    excess = (counts - expected_per_group).clip(lower=0)
    total_excess = float(excess.sum())
    if total_excess <= 0:
        return {"concentration": 0.0, "top_group": None, "excess_by_group": {}}

    top_group = excess.idxmax()
    concentration = float(excess[top_group] / total_excess)
    return {
        "concentration": concentration,
        "top_group": int(top_group),
        "excess_by_group": {int(k): float(v) for k, v in excess.items()},
    }


def monitor_concentration_index_category(batch: pd.DataFrame) -> dict:
    """
    Monitor de Drift de Seguridad: índice de concentración por categoría.
    Mide si el lote tiene una categoría anormalmente sobre-representada
    respecto a la proporción uniforme esperada (1/n_categorías) -- la
    firma directa de un ataque que reasigna tráfico manipulado hacia un
    único segmento (ver generate_feedback.py, escenario adversarial).
    """
    n_categories = batch["category"].nunique()
    counts = batch["category"].value_counts().sort_index()
    expected = len(batch) / max(n_categories, 1)
    result = _positive_excess_concentration(counts, expected)
    result["concentration_metric"] = "category"
    return result


def monitor_concentration_index_temporal(batch: pd.DataFrame) -> dict:
    """
    Monitor de Drift de Seguridad: índice de concentración temporal,
    análogo al de categoría pero sobre ventanas contiguas de tamaño
    TEMPORAL_CONCENTRATION_WINDOW_SPAN. Usar una ventana deslizante (en
    lugar de una sola time_window) permite detectar concentración
    repartida entre unas pocas ventanas contiguas (p. ej. una ráfaga de
    tráfico manipulado de un par de horas), no solo en una única unidad
    de tiempo discreta.
    """
    counts = batch["time_window"].value_counts().sort_index()
    all_windows = counts.index.min(), counts.index.max()
    span = max(TEMPORAL_CONCENTRATION_WINDOW_SPAN, 1)

    # Suma deslizante de conteos sobre ventanas contiguas de tamaño `span`.
    windows_sorted = counts.sort_index()
    sliding_sums = {}
    window_values = windows_sorted.index.tolist()
    for i in range(len(window_values) - span + 1):
        group = window_values[i : i + span]
        sliding_sums[group[0]] = windows_sorted.loc[group].sum()

    sliding_series = pd.Series(sliding_sums)
    expected = len(batch) / max(len(window_values), 1) * span
    result = _positive_excess_concentration(sliding_series, expected)
    result["concentration_metric"] = "temporal"
    result["window_span"] = span
    return result


def monitor_label_manipulation_signal(baseline: pd.DataFrame, batch: pd.DataFrame) -> dict:
    """
    Monitor de Drift de Seguridad: señal de manipulación de etiquetas.
    Compara, por categoría, la proporción de relevance == 3 (la etiqueta
    de mayor relevancia) en el lote contra el baseline. Un incremento
    grande y localizado en una sola categoría es la firma directa de la
    inflación de relevancia hacia productos objetivo descrita en el
    escenario adversarial de generate_feedback.py.
    """
    per_category = {}
    for category in sorted(batch["category"].unique()):
        baseline_c = baseline[baseline["category"] == category]
        batch_c = batch[batch["category"] == category]
        if len(baseline_c) < MIN_GROUP_SIZE or len(batch_c) < MIN_GROUP_SIZE:
            continue

        baseline_share = float((baseline_c["relevance"] == 3).mean())
        batch_share = float((batch_c["relevance"] == 3).mean())
        delta = batch_share - baseline_share
        per_category[int(category)] = {
            "baseline_top_share": baseline_share,
            "batch_top_share": batch_share,
            "delta": delta,
        }

    if per_category:
        top_category = max(per_category, key=lambda c: per_category[c]["delta"])
        max_delta = per_category[top_category]["delta"]
    else:
        top_category = None
        max_delta = 0.0

    return {
        "per_category": per_category,
        "max_delta": float(max_delta),
        "top_category": top_category,
    }


# ---------------------------------------------------------------------------
# Decisión del gate
# ---------------------------------------------------------------------------

def decide(
    guardian_result: dict,
    concentration_category: dict,
    concentration_temporal: dict,
    label_signal: dict,
) -> dict:
    """
    Combina el resultado del Guardian de Ingesta (¿hay drift global?) con
    las tres señales del Monitor de Drift de Seguridad (concentración por
    categoría, concentración temporal, manipulación de etiquetas) para
    decidir entre ACEPTADO, ACEPTADO_CON_ALERTA (drift natural/difuso) y
    CUARENTENA (patrón adversarial/concentrado). El criterio de decisión
    NO se basa únicamente en el KS global: un lote solo llega a
    CUARENTENA si, además de mostrar drift global, al menos una de las
    señales de concentración del Monitor supera su umbral.
    """
    if not guardian_result["global_drift_detected"]:
        return {
            "decision": "ACEPTADO",
            "exit_code": 0,
            "reason": "El Guardian de Ingesta no detectó drift global significativo.",
        }

    adversarial_signals = []
    if concentration_category["concentration"] >= CONCENTRATION_CATEGORY_THRESHOLD:
        adversarial_signals.append(
            f"concentración por categoría ({concentration_category['concentration']:.3f} "
            f">= {CONCENTRATION_CATEGORY_THRESHOLD}), categoría más afectada="
            f"{concentration_category['top_group']}"
        )
    if concentration_temporal["concentration"] >= CONCENTRATION_TEMPORAL_THRESHOLD:
        adversarial_signals.append(
            f"concentración temporal ({concentration_temporal['concentration']:.3f} "
            f">= {CONCENTRATION_TEMPORAL_THRESHOLD}), ventana más afectada="
            f"{concentration_temporal['top_group']}"
        )
    if label_signal["max_delta"] >= LABEL_MANIPULATION_DELTA_THRESHOLD:
        adversarial_signals.append(
            f"manipulación de etiquetas (delta={label_signal['max_delta']:.3f} "
            f">= {LABEL_MANIPULATION_DELTA_THRESHOLD}), categoría={label_signal['top_category']}"
        )

    if adversarial_signals:
        return {
            "decision": "CUARENTENA",
            "exit_code": 4,
            "reason": (
                "El Guardian detectó drift global Y el Monitor de Drift de Seguridad "
                "detectó un patrón concentrado: " + "; ".join(adversarial_signals)
            ),
        }

    return {
        "decision": "ACEPTADO_CON_ALERTA",
        "exit_code": 3,
        "reason": (
            "El Guardian detectó drift global, pero el Monitor de Drift de Seguridad "
            "no encontró concentración por categoría/tiempo ni manipulación de "
            "etiquetas: el patrón es compatible con drift natural (difuso)."
        ),
    }


# ---------------------------------------------------------------------------
# Presentación y orquestación
# ---------------------------------------------------------------------------

def print_summary_table(batch_name, guardian_result, segment_result, conc_cat, conc_temp, label_signal, decision):
    print("=" * 78)
    print(f" RESUMEN — feedback_gate.py sobre {batch_name}")
    print("=" * 78)

    print("\n[Guardian de Ingesta — Sub-componente 1] KS global por feature:")
    for feature, res in guardian_result["per_feature"].items():
        flag = " <-- FLAGGED" if res["flagged"] else ""
        print(f"  {feature:25s} stat={res['statistic']:.4f}  p={res['p_value']:.4g}{flag}")
    print(
        f"  Features marcadas: {guardian_result['n_flagged']} "
        f"(umbral mínimo: {GUARDIAN_MIN_FLAGGED_FEATURES}) "
        f"-> drift global detectado: {guardian_result['global_drift_detected']}"
    )

    print("\n[Monitor de Drift de Seguridad — Sub-componente 2] KS por segmento (categoría):")
    print(f"  Categorías con diferencia significativa: {segment_result['n_significant_categories']}")

    print("\n[Monitor de Drift de Seguridad] Índices de concentración:")
    print(
        f"  Por categoría:  {conc_cat['concentration']:.4f} "
        f"(umbral: {CONCENTRATION_CATEGORY_THRESHOLD}) — categoría top: {conc_cat['top_group']}"
    )
    print(
        f"  Temporal:       {conc_temp['concentration']:.4f} "
        f"(umbral: {CONCENTRATION_TEMPORAL_THRESHOLD}, span={conc_temp['window_span']}) "
        f"— ventana top: {conc_temp['top_group']}"
    )

    print("\n[Monitor de Drift de Seguridad] Señal de manipulación de etiquetas (relevance==3):")
    print(
        f"  Delta máximo: {label_signal['max_delta']:.4f} "
        f"(umbral: {LABEL_MANIPULATION_DELTA_THRESHOLD}) — categoría: {label_signal['top_category']}"
    )

    print("\n[Decisión]")
    print(f"  {decision['decision']} (exit code {decision['exit_code']})")
    print(f"  Regla: {decision['reason']}")
    print("=" * 78)


def quarantine_batch(batch_path: str, decision: dict, metrics: dict) -> None:
    """
    Copia el lote rechazado a /app/data/quarantine/ y escribe un
    reason.json con las métricas que dispararon la decisión -- evidencia
    trazable de por qué el Secure Retraining Gate bloqueó este lote antes
    de que llegara al reentrenamiento.
    """
    os.makedirs(QUARANTINE_DIR, exist_ok=True)
    batch_filename = os.path.basename(batch_path)
    quarantined_path = os.path.join(QUARANTINE_DIR, batch_filename)
    shutil.copyfile(batch_path, quarantined_path)

    reason = {
        "batch_file": batch_filename,
        "decision": decision["decision"],
        "exit_code": decision["exit_code"],
        "reason": decision["reason"],
        "quarantined_at_utc": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "KS_ALPHA": KS_ALPHA,
            "KS_STAT_THRESHOLD": KS_STAT_THRESHOLD,
            "GUARDIAN_MIN_FLAGGED_FEATURES": GUARDIAN_MIN_FLAGGED_FEATURES,
            "CONCENTRATION_CATEGORY_THRESHOLD": CONCENTRATION_CATEGORY_THRESHOLD,
            "CONCENTRATION_TEMPORAL_THRESHOLD": CONCENTRATION_TEMPORAL_THRESHOLD,
            "TEMPORAL_CONCENTRATION_WINDOW_SPAN": TEMPORAL_CONCENTRATION_WINDOW_SPAN,
            "LABEL_MANIPULATION_DELTA_THRESHOLD": LABEL_MANIPULATION_DELTA_THRESHOLD,
        },
        "metrics": metrics,
    }
    reason_path = os.path.join(QUARANTINE_DIR, f"{batch_filename}.reason.json")
    with open(reason_path, "w", encoding="utf-8") as f:
        json.dump(reason, f, indent=2, ensure_ascii=False)

    print(f"[feedback_gate] Lote copiado a cuarentena: {quarantined_path}")
    print(f"[feedback_gate] Evidencia de la decisión: {reason_path}")


def _log_to_mlflow(batch_name, guardian_result, conc_cat, conc_temp, label_signal, decision,
                   cycle_id=None, batch_sha256=None):
    """
    Registro de la decisión como un run de MLflow. Es OPCIONAL en la demo de
    la capa (LOG_TO_MLFLOW=true) y OBLIGATORIO dentro de un ciclo de
    reentrenamiento (--cycle-id): en ese caso el run, etiquetado con el
    identificador del ciclo, es el canal por el que la Compuerta de Promoción
    del Modelo Reentrenado recibe la señal del Monitor (almacén de metadatos
    compartido, componente C7).
    """
    import mlflow  # import diferido: mlflow no es una dependencia dura de esta capa

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    mlflow.set_experiment("recoshop-p02-layer3")
    with mlflow.start_run():
        mlflow.log_param("batch_file", batch_name)
        mlflow.log_metric("guardian_n_flagged", guardian_result["n_flagged"])
        mlflow.log_metric("concentration_category", conc_cat["concentration"])
        mlflow.log_metric("concentration_temporal", conc_temp["concentration"])
        mlflow.log_metric("label_manipulation_max_delta", label_signal["max_delta"])
        mlflow.set_tag("decision", decision["decision"])
        mlflow.set_tag("exit_code", str(decision["exit_code"]))
        mlflow.set_tag("batch_file", batch_name)
        if batch_sha256:
            mlflow.set_tag("batch_sha256", batch_sha256)
        if cycle_id:
            mlflow.set_tag("cycle_id", cycle_id)
        run_id = mlflow.active_run().info.run_id
    if cycle_id:
        print(f"[feedback_gate] Decisión registrada en MLflow para el ciclo '{cycle_id}' (run {run_id}).")
    else:
        print("[feedback_gate] Decisión registrada en MLflow (LOG_TO_MLFLOW=true).")


def run_gate(batch_path: str, cycle_id: str = None) -> int:
    baseline_path = os.path.join(DATA_DIR, "baseline.csv")

    if not os.path.isfile(baseline_path):
        raise InfrastructureError(
            f"No se encontró el baseline en {baseline_path}. "
            "Ejecuta primero: python generate_feedback.py"
        )
    if not os.path.isfile(batch_path):
        raise InfrastructureError(f"No se encontró el lote a evaluar: {batch_path}")

    try:
        baseline = pd.read_csv(baseline_path)
        batch = pd.read_csv(batch_path)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise InfrastructureError(f"Error leyendo CSV: {exc}") from exc

    required_columns = set(FEATURE_COLUMNS + ["relevance", "time_window"])
    missing_baseline = required_columns - set(baseline.columns)
    missing_batch = required_columns - set(batch.columns)
    if missing_baseline or missing_batch:
        raise InfrastructureError(
            f"Columnas faltantes -- baseline: {missing_baseline}, lote: {missing_batch}"
        )

    guardian_result = guardian_ks_global(baseline, batch)
    segment_result = monitor_ks_by_segment(baseline, batch)
    conc_cat = monitor_concentration_index_category(batch)
    conc_temp = monitor_concentration_index_temporal(batch)
    label_signal = monitor_label_manipulation_signal(baseline, batch)

    decision = decide(guardian_result, conc_cat, conc_temp, label_signal)

    batch_name = os.path.basename(batch_path)
    print_summary_table(batch_name, guardian_result, segment_result, conc_cat, conc_temp, label_signal, decision)

    if decision["exit_code"] == 4:
        metrics = {
            "guardian": guardian_result,
            "segment_ks": segment_result,
            "concentration_category": conc_cat,
            "concentration_temporal": conc_temp,
            "label_manipulation": label_signal,
        }
        quarantine_batch(batch_path, decision, metrics)

    if cycle_id:
        with open(batch_path, "rb") as f:
            batch_sha256 = hashlib.sha256(f.read()).hexdigest()
        try:
            _log_to_mlflow(batch_name, guardian_result, conc_cat, conc_temp, label_signal, decision,
                           cycle_id=cycle_id, batch_sha256=batch_sha256)
        except Exception as exc:  # noqa: BLE001 - dentro de un ciclo, sin registro no hay señal
            raise InfrastructureError(
                f"no se pudo registrar la decisión del ciclo '{cycle_id}' en MLflow: {exc}"
            ) from exc
    elif LOG_TO_MLFLOW:
        try:
            _log_to_mlflow(batch_name, guardian_result, conc_cat, conc_temp, label_signal, decision)
        except Exception as exc:  # noqa: BLE001 - el registro en MLflow es opcional
            print(f"[feedback_gate] AVISO: no se pudo registrar en MLflow: {exc}")

    return decision["exit_code"]


def main():
    parser = argparse.ArgumentParser(description="P-02 Secure Retraining Gate (Capa 3)")
    parser.add_argument("--batch", required=True, help="Ruta al CSV del lote de feedback a evaluar")
    parser.add_argument("--cycle-id", default=None,
                        help="Identificador del ciclo de reentrenamiento: registra la decisión en "
                             "MLflow para la Compuerta de Promoción (obligatorio dentro de un ciclo)")
    args = parser.parse_args()

    try:
        exit_code = run_gate(args.batch, cycle_id=args.cycle_id)
    except InfrastructureError as exc:
        print(f"[feedback_gate] ERROR DE INFRAESTRUCTURA: {exc}", file=sys.stderr)
        sys.exit(2)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
