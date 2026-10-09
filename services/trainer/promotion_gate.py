"""
promotion_gate.py
=================
Implementa el tercer sub-componente del patrón P-02 (Secure Retraining Gate):
la Compuerta de Promoción del Modelo Reentrenado, sobre la debilidad D-03
(Canal de Retroalimentación No Validado).

La compuerta opera al final del ciclo de reentrenamiento. Compara el modelo
candidato (reentrenado con el corpus original más la retroalimentación) con el
modelo vigente sobre un CONJUNTO CANÓNICO DE SEGURIDAD: un conjunto curado,
versionado e independiente del corpus de reentrenamiento. Decide con dos
criterios y la señal del Monitor de Drift de Seguridad:

  1. Degradación global: NDCG@10 del candidato frente al vigente. Si cae más
     de GLOBAL_NDCG_TOLERANCE, el candidato se rechaza (criterio estándar).
  2. Degradación selectiva por subpoblación [aporte de Nivel 4 del catálogo]:
     exactitud de ordenamiento por pares DENTRO de cada categoría de producto
     (fracción de pares de productos de la misma sesión y categoría, con
     relevancia distinta, que el modelo ordena correctamente). Si alguna
     categoría cae más de SUBPOP_MAX_DEGRADATION, hay degradación selectiva,
     aunque la métrica global no la muestre.
  3. Señal del Monitor de Drift de Seguridad (--monitor-signal): "adversarial"
     si el Monitor puso un lote del ciclo en cuarentena; "none" o "natural" en
     otro caso.

Política de promoción (sección 5 del patrón P-02 en el catálogo):

  - Degradación global                          -> RECHAZADO        (exit 1)
  - Degradación selectiva + alerta adversarial  -> RECHAZADO        (exit 1)
  - Solo una de las dos señales                 -> RETENIDO para
                                                   revisión humana  (exit 4)
  - Ninguna                                     -> APROBADO         (exit 0)

Un candidato rechazado o retenido NO se promueve: el modelo vigente sigue en
producción. Cada decisión imprime un registro de auditoría en JSON.

Códigos de salida (mismo contrato que verify_and_deploy.py y feedback_gate.py):
  0 — APROBADO
  1 — RECHAZADO
  2 — ERROR DE INFRAESTRUCTURA
  4 — RETENIDO (cuarentena del candidato, pendiente de revisión humana)

Escenarios de retroalimentación (--feedback):
  - clean:    sesiones nuevas con el mismo comportamiento que el corpus.
  - poisoned: la misma retroalimentación, pero en el 60 % de las sesiones una
              red de bots simula compras de los productos MENOS populares de
              una categoría (la del vendedor atacante) y deja sin interacción
              a los más populares. Es el escenario de explotación de D-03
              (Model Skewing, ML08) dirigido a una sola subpoblación.

DECLARACIÓN: datos sintéticos; umbrales calibrados para el prototipo, no
validados con tráfico real.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import ndcg_score

from generate_data import N_CATEGORIES, generate_recoshop_dataset
from mlbom import sha256_of_dataframe

FEATURE_COLUMNS = [
    "category",
    "price",
    "user_purchase_history",
    "product_popularity",
    "discount_pct",
    "is_weekend",
]

# Modelo vigente: mismo procedimiento y semilla que train.py.
CURRENT_MODEL_SEED = int(os.environ.get("RANDOM_SEED", "42"))

# Conjunto canónico de seguridad: semillas propias, independientes del corpus
# de entrenamiento (42) y de la retroalimentación. Versionado por su SHA-256.
CANONICAL_SEEDS = [9001, 9002, 9003, 9004, 9005]

# Retroalimentación del ciclo.
FEEDBACK_SEED = int(os.environ.get("FEEDBACK_SEED", "500"))
POISON_SESSION_FRACTION = float(os.environ.get("POISON_SESSION_FRACTION", "0.6"))
POISON_TARGET_CATEGORY = int(os.environ.get("POISON_TARGET_CATEGORY", "3"))

# Umbrales de la compuerta (calibrados para el prototipo).
GLOBAL_NDCG_TOLERANCE = float(os.environ.get("GLOBAL_NDCG_TOLERANCE", "0.02"))
SUBPOP_MAX_DEGRADATION = float(os.environ.get("SUBPOP_MAX_DEGRADATION", "0.03"))

SESSION_OFFSET_CANONICAL = 100_000
SESSION_OFFSET_FEEDBACK = 500_000


class InfrastructureError(Exception):
    """Errores de entorno, distintos de una decisión de la compuerta."""


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def split_like_train(df: pd.DataFrame, seed: int):
    """División por sesión idéntica a la de train.py."""
    session_ids = df["session_id"].unique()
    rng = np.random.default_rng(seed)
    rng.shuffle(session_ids)
    n_eval = max(1, int(len(session_ids) * 0.2))
    eval_sessions = set(session_ids[:n_eval].tolist())
    train_sessions = set(session_ids[n_eval:].tolist())
    train_df = df[df["session_id"].isin(train_sessions)].sort_values("session_id")
    eval_df = df[df["session_id"].isin(eval_sessions)].sort_values("session_id")
    return train_df, eval_df


def build_canonical_set() -> pd.DataFrame:
    parts = []
    for i, seed in enumerate(CANONICAL_SEEDS):
        part = generate_recoshop_dataset(seed=seed)
        part["session_id"] = part["session_id"] + (i + 1) * SESSION_OFFSET_CANONICAL
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def build_feedback(scenario: str) -> pd.DataFrame:
    feedback = generate_recoshop_dataset(seed=FEEDBACK_SEED)
    feedback["session_id"] = feedback["session_id"] + SESSION_OFFSET_FEEDBACK
    if scenario == "clean":
        return feedback

    # Escenario de explotación de D-03: compras simuladas por bots sobre los
    # productos menos populares de la categoría objetivo, en una fracción de
    # las sesiones; los productos populares de esa categoría quedan sin
    # interacción. El resto del corpus no cambia.
    rng = np.random.default_rng(FEEDBACK_SEED + 1)
    sessions = feedback["session_id"].unique()
    n_poisoned = int(POISON_SESSION_FRACTION * len(sessions))
    poisoned_sessions = set(rng.choice(sessions, size=n_poisoned, replace=False).tolist())

    in_target = feedback["category"] == POISON_TARGET_CATEGORY
    median_pop = feedback.loc[in_target, "product_popularity"].median()
    mask = feedback["session_id"].isin(poisoned_sessions) & in_target
    feedback.loc[mask & (feedback["product_popularity"] < median_pop), "relevance"] = 3
    feedback.loc[mask & (feedback["product_popularity"] >= median_pop), "relevance"] = 0
    return feedback


# ---------------------------------------------------------------------------
# Modelos y métricas
# ---------------------------------------------------------------------------

def fit_ranker(train_df: pd.DataFrame, eval_df: pd.DataFrame, seed: int) -> lgb.LGBMRanker:
    """Mismos hiperparámetros que train.py."""
    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=80,
        learning_rate=0.08,
        num_leaves=15,
        random_state=seed,
        verbosity=-1,
    )
    model.fit(
        train_df[FEATURE_COLUMNS],
        train_df["relevance"],
        group=train_df.groupby("session_id").size().to_numpy(),
        eval_set=[(eval_df[FEATURE_COLUMNS], eval_df["relevance"])],
        eval_group=[eval_df.groupby("session_id").size().to_numpy()],
        eval_at=[5, 10],
    )
    return model


def model_sha256(model: lgb.LGBMRanker) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "model.txt")
        model.booster_.save_model(path)
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()


def global_ndcg_at_10(model: lgb.LGBMRanker, df: pd.DataFrame) -> float:
    scores = []
    for _, session in df.groupby("session_id"):
        if len(session) < 2:
            continue
        y_true = session["relevance"].to_numpy().reshape(1, -1)
        y_pred = model.predict(session[FEATURE_COLUMNS]).reshape(1, -1)
        scores.append(ndcg_score(y_true, y_pred, k=10))
    return float(np.mean(scores))


def pairwise_accuracy_by_category(model: lgb.LGBMRanker, df: pd.DataFrame) -> dict:
    """
    Exactitud de ordenamiento por pares dentro de cada categoría: fracción de
    pares (misma sesión, misma categoría, relevancia distinta) que el modelo
    ordena en el sentido correcto.
    """
    scored = df.copy()
    scored["score"] = model.predict(scored[FEATURE_COLUMNS])
    result = {}
    for category in range(N_CATEGORIES):
        concordant = total = 0
        subset = scored[scored["category"] == category]
        for _, session in subset.groupby("session_id"):
            rel = session["relevance"].to_numpy()
            sc = session["score"].to_numpy()
            for i in range(len(rel)):
                for j in range(i + 1, len(rel)):
                    if rel[i] == rel[j]:
                        continue
                    total += 1
                    concordant += int((sc[i] - sc[j]) * (rel[i] - rel[j]) > 0)
        result[category] = {"pairs": total, "accuracy": concordant / total if total else float("nan")}
    return result


# ---------------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------------

def decide(global_delta: float, subpop_deltas: dict, monitor_signal: str):
    global_degradation = global_delta < -GLOBAL_NDCG_TOLERANCE
    degraded = {c: d for c, d in subpop_deltas.items() if d < -SUBPOP_MAX_DEGRADATION}
    selective = bool(degraded) and not global_degradation
    adversarial_alert = monitor_signal == "adversarial"

    if global_degradation:
        return "RECHAZADO", 1, (
            f"Degradación global: el NDCG@10 del candidato cae {abs(global_delta):.4f} "
            f"(tolerancia {GLOBAL_NDCG_TOLERANCE})."
        ), degraded
    if selective and adversarial_alert:
        return "RECHAZADO", 1, (
            "Degradación selectiva en la(s) categoría(s) "
            f"{sorted(degraded)} sin degradación global, Y alerta adversarial del "
            "Monitor de Drift de Seguridad."
        ), degraded
    if selective:
        return "RETENIDO", 4, (
            "Degradación selectiva en la(s) categoría(s) "
            f"{sorted(degraded)} sin degradación global; el Monitor no emitió alerta "
            "adversarial. El candidato no se promueve y se escala a revisión humana."
        ), degraded
    if adversarial_alert:
        return "RETENIDO", 4, (
            "Alerta adversarial del Monitor de Drift de Seguridad sin degradación "
            "medible en el conjunto canónico. El candidato no se promueve y se escala "
            "a revisión humana."
        ), degraded
    return "APROBADO", 0, (
        "Sin degradación global ni selectiva y sin alerta adversarial del Monitor."
    ), degraded


def main() -> int:
    parser = argparse.ArgumentParser(description="Compuerta de Promoción del Modelo Reentrenado (P-02)")
    parser.add_argument("--feedback", required=True, choices=["clean", "poisoned"])
    parser.add_argument("--monitor-signal", default="none", choices=["none", "natural", "adversarial"])
    args = parser.parse_args()

    try:
        corpus = generate_recoshop_dataset(seed=CURRENT_MODEL_SEED)
        train_df, eval_df = split_like_train(corpus, CURRENT_MODEL_SEED)
        canonical = build_canonical_set()
        feedback = build_feedback(args.feedback)
    except Exception as exc:  # noqa: BLE001
        print(f"[promotion-gate] ERROR DE INFRAESTRUCTURA preparando los datos: {exc}")
        return 2

    print(f"[promotion-gate] Escenario de retroalimentación: {args.feedback} "
          f"(semilla {FEEDBACK_SEED}); señal del Monitor: {args.monitor_signal}")
    print(f"[promotion-gate] Conjunto canónico de seguridad: {canonical['session_id'].nunique()} sesiones, "
          f"{len(canonical)} filas, SHA-256 {sha256_of_dataframe(canonical)}")

    current = fit_ranker(train_df, eval_df, CURRENT_MODEL_SEED)
    print(f"[promotion-gate] Modelo vigente (semilla {CURRENT_MODEL_SEED}): SHA-256 {model_sha256(current)}")

    retrain_df = pd.concat([train_df, feedback], ignore_index=True).sort_values("session_id")
    candidate = fit_ranker(retrain_df, eval_df, CURRENT_MODEL_SEED)
    print(f"[promotion-gate] Modelo candidato (reentrenado con {feedback['session_id'].nunique()} "
          f"sesiones de retroalimentación): SHA-256 {model_sha256(candidate)}")

    current_global = global_ndcg_at_10(current, canonical)
    candidate_global = global_ndcg_at_10(candidate, canonical)
    global_delta = candidate_global - current_global

    current_sub = pairwise_accuracy_by_category(current, canonical)
    candidate_sub = pairwise_accuracy_by_category(candidate, canonical)
    subpop_deltas = {
        c: candidate_sub[c]["accuracy"] - current_sub[c]["accuracy"] for c in range(N_CATEGORIES)
    }

    print("")
    print("[promotion-gate] NDCG@10 global en el conjunto canónico:")
    print(f"  vigente {current_global:.4f} · candidato {candidate_global:.4f} · "
          f"delta {global_delta:+.4f} (tolerancia {GLOBAL_NDCG_TOLERANCE})")
    print("[promotion-gate] Exactitud por pares dentro de cada categoría "
          f"(umbral de degradación {SUBPOP_MAX_DEGRADATION}):")
    for c in range(N_CATEGORIES):
        flag = "  <-- DEGRADACIÓN SELECTIVA" if subpop_deltas[c] < -SUBPOP_MAX_DEGRADATION else ""
        print(f"  categoría {c}: vigente {current_sub[c]['accuracy']:.4f} · "
              f"candidato {candidate_sub[c]['accuracy']:.4f} · delta {subpop_deltas[c]:+.4f} "
              f"({current_sub[c]['pairs']} pares){flag}")

    decision, code, rule, degraded = decide(global_delta, subpop_deltas, args.monitor_signal)

    audit = {
        "decision": decision,
        "exit_code": code,
        "rule": rule,
        "decided_at_utc": datetime.now(timezone.utc).isoformat(),
        "feedback_scenario": args.feedback,
        "monitor_signal": args.monitor_signal,
        "thresholds": {
            "GLOBAL_NDCG_TOLERANCE": GLOBAL_NDCG_TOLERANCE,
            "SUBPOP_MAX_DEGRADATION": SUBPOP_MAX_DEGRADATION,
        },
        "canonical_set": {
            "seeds": CANONICAL_SEEDS,
            "sha256": sha256_of_dataframe(canonical),
        },
        "models": {
            "current_sha256": model_sha256(current),
            "candidate_sha256": model_sha256(candidate),
        },
        "metrics": {
            "global_ndcg_at_10": {
                "current": round(current_global, 6),
                "candidate": round(candidate_global, 6),
                "delta": round(global_delta, 6),
            },
            "pairwise_accuracy_delta_by_category": {
                str(c): round(d, 6) for c, d in subpop_deltas.items()
            },
            "degraded_categories": sorted(degraded),
        },
    }

    print("")
    print("[promotion-gate] Decisión:")
    print(f"  {decision} (exit code {code})")
    print(f"  Regla: {rule}")
    if code != 0:
        print("  El candidato NO se promueve: el modelo vigente sigue en producción.")
    print("[promotion-gate] Registro de auditoría:")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
