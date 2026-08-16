"""
verify_and_deploy.py
=====================
Implementa el "gate de despliegue" del sub-componente Artifact Signing and
Registry Gate de P-03 (Trusted ML Artifact Pipeline).

Este script NO confía en ningún archivo local ni en lo que el trainer
"diga": descarga el artefacto del modelo y su firma DIRECTAMENTE desde el
Model Registry (MLflow + MinIO) en cada ejecución, y verifica la firma con
cosign ANTES de decidir si el modelo puede pasar a "despliegue".

En este prototipo (Capa 1), "despliegue" es simbólico: el gate solo
imprime la decisión de aprobación/rechazo. KServe e Istio están fuera de
alcance de esta capa (ver README.md, sección "Alcance y limitaciones");
en producción, este gate se instancia sobre el pipeline CI/CD (GitHub
Actions + ArgoCD) tal como describe el Entregable A4.1 de la tesis.

Relación con la tesis:
  - Debilidad mitigada: D-01.
  - Patrón: P-03, sub-componente "Artifact Signing and Registry Gate".
  - Comportamiento esperado (A4.4 §3.3): "el pipeline CI/CD rechaza
    cualquier artefacto sin firma válida".
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import mlflow
from mlflow.tracking import MlflowClient

MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "recoshop-ranker")
COSIGN_PUB_PATH = os.environ.get("COSIGN_PUB_PATH", "/keys/cosign.pub")


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_latest_version(model_name: str):
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise RuntimeError(
            f"No hay ninguna versión registrada del modelo '{model_name}' en MLflow. "
            "Ejecuta primero: docker compose run --rm trainer python train.py"
        )
    return max(versions, key=lambda v: int(v.version))


def download_artifacts(run_id: str, dest_dir: str):
    model_path = mlflow.artifacts.download_artifacts(
        run_id=run_id, artifact_path="model/model.txt", dst_path=dest_dir
    )
    sig_path = mlflow.artifacts.download_artifacts(
        run_id=run_id, artifact_path="model/model.txt.sig", dst_path=dest_dir
    )
    return model_path, sig_path


def verify_signature(model_path: str, sig_path: str, public_key_path: str) -> bool:
    if shutil.which("cosign") is None:
        raise RuntimeError(
            "El binario 'cosign' no está disponible en este contenedor. "
            "Revisa el Dockerfile de services/deployment-gate."
        )

    if not os.path.isfile(public_key_path):
        raise FileNotFoundError(
            f"No se encontró la clave pública en {public_key_path}. "
            "Ejecuta ./scripts/generate_keys.sh antes de usar el gate."
        )

    cmd = [
        "cosign", "verify-blob",
        "--key", public_key_path,
        "--signature", sig_path,
        "--insecure-ignore-tlog=true",  # el prototipo firma sin publicar en Rekor
        model_path,
    ]

    print(f"[deployment-gate] Comando de verificación: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    print(f"[deployment-gate] stdout de cosign:\n{result.stdout.strip()}")
    if result.returncode != 0:
        print(f"[deployment-gate] stderr de cosign:\n{result.stderr.strip()}")

    return result.returncode == 0


def main():
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))

    try:
        latest = get_latest_version(MLFLOW_MODEL_NAME)
    except RuntimeError as exc:
        print(f"ERROR CRÍTICO: {exc}", file=sys.stderr)
        sys.exit(2)

    print(
        f"[deployment-gate] Evaluando la versión {latest.version} de "
        f"'{MLFLOW_MODEL_NAME}' (run_id={latest.run_id}) para despliegue."
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            model_path, sig_path = download_artifacts(latest.run_id, tmp_dir)
        except Exception as exc:  # noqa: BLE001 - error claro para el usuario
            print(
                f"ERROR CRÍTICO: no fue posible descargar los artefactos desde "
                f"el Model Registry (MLflow/MinIO): {exc}",
                file=sys.stderr,
            )
            sys.exit(2)

        current_hash = sha256_of_file(model_path)
        print(f"[deployment-gate] SHA-256 del artefacto descargado del registry: {current_hash}")

        client = MlflowClient()
        signed_hash_tag = None
        try:
            mv = client.get_model_version(MLFLOW_MODEL_NAME, latest.version)
            signed_hash_tag = mv.tags.get("sha256_at_signing_time")
        except Exception:  # noqa: BLE001 - informativo, no crítico
            pass

        if signed_hash_tag:
            print(f"[deployment-gate] SHA-256 registrado al momento de firmar:  {signed_hash_tag}")
            if signed_hash_tag != current_hash:
                print(
                    "[deployment-gate] \u26a0\ufe0f  El hash actual del artefacto NO coincide con "
                    "el hash registrado al momento de la firma. Esto es evidencia de que el "
                    "artefacto fue modificado después de firmarse (simulación de D-01)."
                )

        try:
            is_valid = verify_signature(model_path, sig_path, COSIGN_PUB_PATH)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"ERROR CRÍTICO en el gate: {exc}", file=sys.stderr)
            sys.exit(2)

        print("")
        if is_valid:
            print("Firma verificada correctamente. Modelo APROBADO para despliegue.")
            sys.exit(0)
        else:
            print("FIRMA INVÁLIDA. Despliegue RECHAZADO.")
            sys.exit(1)


if __name__ == "__main__":
    main()
