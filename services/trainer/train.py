"""
train.py
========
Entrena un modelo LightGBM de ranking sobre datos sintéticos de RecoShop,
lo firma con cosign, y lo registra en MLflow (tracking + Model Registry)
JUNTO CON su firma y sus metadatos.

Este script materializa, en miniatura, el Flujo C del patrón P-03 (Trusted
ML Artifact Pipeline) descrito en el catálogo de patrones y en el
Entregable A4.4 de la tesis:

    Pipeline de entrenamiento -> firma del artefacto ->
    Model Registry (una versión nueva por ejecución, nunca se sobrescribe
    una versión existente -- política de inmutabilidad lógica / append-only)

Relación con la tesis:
  - Debilidad mitigada: D-01 (Confianza Implícita en la Integridad de
    Artefactos del Model Registry).
  - Patrón aplicado: P-03, sub-componente "Artifact Signing and Registry Gate".
  - El modelo se FIRMA ANTES de registrarse, no después: esto es
    intencional, porque en el escenario de ataque de D-01 un atacante que
    solo comprometa el registry (y no la clave de firma) no puede producir
    una firma válida sobre un artefacto sustituido.
"""

import hashlib
import json
import os
import tempfile

import lightgbm as lgb
import mlflow
import numpy as np
from mlflow.tracking import MlflowClient
from sklearn.metrics import ndcg_score

from generate_data import generate_recoshop_dataset
from sign_model import CosignNotFoundError, CosignSigningError, sign_artifact

RANDOM_SEED = int(os.environ.get("RANDOM_SEED", "42"))
MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "recoshop-ranker")
COSIGN_KEY_PATH = os.environ.get("COSIGN_KEY_PATH", "/keys/cosign.key")

FEATURE_COLUMNS = [
    "category",
    "price",
    "user_purchase_history",
    "product_popularity",
    "discount_pct",
    "is_weekend",
]


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def train_and_evaluate():
    df = generate_recoshop_dataset(seed=RANDOM_SEED)

    # División train/eval por SESIÓN COMPLETA (nunca se parte una sesión
    # entre ambos conjuntos, para no filtrar información del grupo de
    # ranking entre train y eval).
    session_ids = df["session_id"].unique()
    rng = np.random.default_rng(RANDOM_SEED)
    rng.shuffle(session_ids)
    n_eval = max(1, int(len(session_ids) * 0.2))
    eval_sessions = set(session_ids[:n_eval].tolist())
    train_sessions = set(session_ids[n_eval:].tolist())

    train_df = df[df["session_id"].isin(train_sessions)].sort_values("session_id")
    eval_df = df[df["session_id"].isin(eval_sessions)].sort_values("session_id")

    train_group = train_df.groupby("session_id").size().to_numpy()
    eval_group = eval_df.groupby("session_id").size().to_numpy()

    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=80,
        learning_rate=0.08,
        num_leaves=15,
        random_state=RANDOM_SEED,
        verbosity=-1,
    )

    model.fit(
        train_df[FEATURE_COLUMNS],
        train_df["relevance"],
        group=train_group,
        eval_set=[(eval_df[FEATURE_COLUMNS], eval_df["relevance"])],
        eval_group=[eval_group],
        eval_at=[5, 10],
    )

    # Evaluación independiente con sklearn.metrics.ndcg_score, calculada por
    # sesión y promediada -- coherente con la métrica NDCG@10 usada como
    # criterio del Gate de Promoción descrito en A4.1/A4.4 de la tesis.
    ndcg_at_10_scores = []
    for session_id in eval_sessions:
        session_df = eval_df[eval_df["session_id"] == session_id]
        if len(session_df) < 2:
            continue
        y_true = session_df["relevance"].to_numpy().reshape(1, -1)
        y_pred = model.predict(session_df[FEATURE_COLUMNS]).reshape(1, -1)
        ndcg_at_10_scores.append(ndcg_score(y_true, y_pred, k=10))

    mean_ndcg_at_10 = float(np.mean(ndcg_at_10_scores)) if ndcg_at_10_scores else float("nan")

    print(f"[train] NDCG@10 promedio en el conjunto de evaluación: {mean_ndcg_at_10:.4f}")

    return model, mean_ndcg_at_10, len(train_sessions), len(eval_sessions)


def main():
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    mlflow.set_experiment("recoshop-p03-layer1")

    model, ndcg_at_10, n_train_sessions, n_eval_sessions = train_and_evaluate()

    with mlflow.start_run() as run:
        run_id = run.info.run_id
        print(f"[train] MLflow run_id: {run_id}")

        mlflow.log_param("random_seed", RANDOM_SEED)
        mlflow.log_param("n_train_sessions", n_train_sessions)
        mlflow.log_param("n_eval_sessions", n_eval_sessions)
        mlflow.log_param("features", ",".join(FEATURE_COLUMNS))
        mlflow.log_metric("ndcg_at_10", ndcg_at_10)

        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = os.path.join(tmp_dir, "model.txt")
            sig_path = os.path.join(tmp_dir, "model.txt.sig")
            metadata_path = os.path.join(tmp_dir, "metadata.json")

            # LightGBM "Booster.save_model" produce un archivo de texto
            # determinista: cualquier alteración de un solo byte cambia su
            # hash SHA-256 y por tanto invalida la firma cosign.
            model.booster_.save_model(model_path)

            artifact_hash_before_signing = sha256_of_file(model_path)
            print(f"[train] SHA-256 del artefacto (antes de firmar): {artifact_hash_before_signing}")

            # --- Firma del artefacto: sub-componente Artifact Signing and
            # --- Registry Gate de P-03, mitigación de D-01. ---
            try:
                sign_artifact(
                    artifact_path=model_path,
                    private_key_path=COSIGN_KEY_PATH,
                    signature_output_path=sig_path,
                )
            except (CosignNotFoundError, CosignSigningError, FileNotFoundError) as exc:
                print(f"ERROR CRÍTICO: no fue posible firmar el modelo: {exc}")
                raise SystemExit(1)

            metadata = {
                "model_name": MLFLOW_MODEL_NAME,
                "mlflow_run_id": run_id,
                "ndcg_at_10": ndcg_at_10,
                "sha256_at_signing_time": artifact_hash_before_signing,
                "signature_algorithm": "cosign (par de claves ECDSA local, sin Rekor)",
                "random_seed": RANDOM_SEED,
                "note": (
                    "Este hash corresponde al artefacto EN EL MOMENTO DE LA FIRMA. "
                    "El deployment-gate recalcula el hash del artefacto descargado "
                    "del Model Registry y lo compara implícitamente al ejecutar "
                    "cosign verify-blob."
                ),
            }
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Se registran los TRES artefactos (modelo, firma, metadatos) en
            # el mismo run de MLflow, bajo la ruta "model/". Esto materializa
            # el requisito de "registrar el modelo en MLflow con su firma y
            # metadatos" exigido por P-03.
            mlflow.log_artifacts(tmp_dir, artifact_path="model")

        # Registrar una NUEVA versión del modelo en el Model Registry. Cada
        # ejecución de train.py crea una versión nueva (nunca sobrescribe
        # una versión existente), coherente con la política de
        # inmutabilidad lógica ("append-only") del patrón P-03.
        model_uri = f"runs:/{run_id}/model"
        try:
            registered_model = mlflow.register_model(model_uri=model_uri, name=MLFLOW_MODEL_NAME)
        except Exception as exc:  # noqa: BLE001 - error claro para el usuario
            print(f"ERROR CRÍTICO al registrar el modelo en MLflow Model Registry: {exc}")
            raise SystemExit(1)

        client = MlflowClient()
        client.set_model_version_tag(
            name=MLFLOW_MODEL_NAME,
            version=registered_model.version,
            key="signed_with_cosign",
            value="true",
        )
        client.set_model_version_tag(
            name=MLFLOW_MODEL_NAME,
            version=registered_model.version,
            key="sha256_at_signing_time",
            value=artifact_hash_before_signing,
        )

        print(
            f"[train] Modelo registrado: '{MLFLOW_MODEL_NAME}' versión "
            f"{registered_model.version} (run_id={run_id})."
        )
        print(
            "[train] El modelo fue firmado ANTES de registrarse en MLflow, "
            "conforme al sub-componente Artifact Signing and Registry Gate de P-03."
        )
        print(
            f"[train] Consulta el run en la UI de MLflow: "
            f"{os.environ.get('MLFLOW_TRACKING_URI', 'http://mlflow:5000')}"
        )


if __name__ == "__main__":
    main()
