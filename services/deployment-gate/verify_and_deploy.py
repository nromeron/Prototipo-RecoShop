"""
verify_and_deploy.py
=====================
Implementa el "gate de despliegue" del sub-componente Artifact Signing and
Registry Gate de P-03 (Trusted ML Artifact Pipeline).

Este script NO confía en ningún archivo local ni en lo que el trainer
"diga": descarga el artefacto del modelo, su ML-BOM y ambas firmas
DIRECTAMENTE desde el Model Registry (MLflow + MinIO) en cada ejecución, y
aplica tres controles independientes antes de decidir el despliegue:

  C1. Firma del ML-BOM      — el documento de enlace es auténtico.
  C2. Vínculo ML-BOM↔modelo — el hash del modelo descargado coincide con
                              el declarado en el ML-BOM firmado.
  C3. Firma del modelo      — el artefacto es auténtico.

El modelo se aprueba solo si los tres controles pasan. Se evalúan y reportan
los tres aunque alguno falle: la evidencia muestra qué control detectó cada
ataque, y en particular que C3 por sí solo NO detecta la sustitución por un
modelo legítimamente firmado de otra versión (caso "swap-signed").

En este prototipo (Capa 1), "despliegue" es simbólico: el gate solo imprime
la decisión. En producción, este gate se instancia sobre el pipeline CI/CD
(GitHub Actions + ArgoCD) tal como describe la sección 3.1 de la tesis.

Relación con la tesis:
  - Debilidad mitigada: D-01.
  - Patrón: P-03, Artifact Signing and Registry Gate + ML-BOM como
    documento de enlace.

Códigos de salida (contrato semántico del prototipo):
  0 = APROBADO · 1 = RECHAZADO · 2 = error de infraestructura
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import mlflow
from mlflow.tracking import MlflowClient

MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "recoshop-ranker")
COSIGN_PUB_PATH = os.environ.get("COSIGN_PUB_PATH", "/keys/cosign.pub")

MODEL_FILE = "model.txt"
MLBOM_FILE = "mlbom.cdx.json"


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


def registered_files(run_id: str) -> set:
    client = MlflowClient()
    return {os.path.basename(a.path) for a in client.list_artifacts(run_id, "model")}


def download(run_id: str, filename: str, dest_dir: str) -> str:
    return mlflow.artifacts.download_artifacts(
        run_id=run_id, artifact_path=f"model/{filename}", dst_path=dest_dir
    )


def cosign_verify(blob_path: str, sig_path: str, label: str) -> bool:
    cmd = [
        "cosign", "verify-blob",
        "--key", COSIGN_PUB_PATH,
        "--signature", sig_path,
        "--insecure-ignore-tlog=true",  # el prototipo firma sin publicar en Rekor
        blob_path,
    ]
    print(f"[deployment-gate] Verificando firma de {label}: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[deployment-gate] stderr de cosign ({label}):\n{result.stderr.strip()}")
    return result.returncode == 0


def model_ref_declared_in_mlbom(mlbom_path: str):
    """
    (SHA-256, run_id) del único componente machine-learning-model del ML-BOM,
    o (None, None) si el documento no es válido.

    El run_id es la versión del componente: ata el ML-BOM a una versión
    concreta del registro. Sin esa comprobación, copiar el modelo, el ML-BOM
    y sus firmas de una versión anterior (reversión completa) pasaría los
    tres controles, porque los cuatro artefactos son auténticos y coherentes
    entre sí.
    """
    try:
        with open(mlbom_path, encoding="utf-8") as f:
            bom = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    if bom.get("bomFormat") != "CycloneDX":
        return None, None
    models = [c for c in bom.get("components", []) if c.get("type") == "machine-learning-model"]
    if len(models) != 1:
        return None, None
    sha = next((h.get("content") for h in models[0].get("hashes", []) if h.get("alg") == "SHA-256"), None)
    return sha, models[0].get("version")


def main():
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))

    if shutil.which("cosign") is None:
        print("ERROR CRÍTICO: el binario 'cosign' no está disponible en el contenedor.", file=sys.stderr)
        sys.exit(2)
    if not os.path.isfile(COSIGN_PUB_PATH):
        print(
            f"ERROR CRÍTICO: no se encontró la clave pública en {COSIGN_PUB_PATH}. "
            "Ejecuta ./scripts/generate_keys.sh",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        latest = get_latest_version(MLFLOW_MODEL_NAME)
        present = registered_files(latest.run_id)
    except Exception as exc:  # noqa: BLE001 - error claro para el usuario
        print(f"ERROR CRÍTICO consultando el Model Registry: {exc}", file=sys.stderr)
        sys.exit(2)

    print(
        f"[deployment-gate] Evaluando la versión {latest.version} de "
        f"'{MLFLOW_MODEL_NAME}' (run_id={latest.run_id}) para despliegue."
    )

    # Política de P-03: sin documento de enlace firmado no hay despliegue.
    # Es una decisión de seguridad (rechazo), no un fallo de infraestructura.
    required = {MODEL_FILE, f"{MODEL_FILE}.sig", MLBOM_FILE, f"{MLBOM_FILE}.sig"}
    missing = sorted(required - present)
    if missing:
        print(f"[deployment-gate] Artefactos ausentes en el registry: {', '.join(missing)}")
        print("")
        print("Versión sin ML-BOM firmado (política de P-03). Despliegue RECHAZADO.")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            model_path = download(latest.run_id, MODEL_FILE, tmp_dir)
            model_sig = download(latest.run_id, f"{MODEL_FILE}.sig", tmp_dir)
            mlbom_path = download(latest.run_id, MLBOM_FILE, tmp_dir)
            mlbom_sig = download(latest.run_id, f"{MLBOM_FILE}.sig", tmp_dir)
        except Exception as exc:  # noqa: BLE001 - error claro para el usuario
            print(f"ERROR CRÍTICO descargando artefactos (MLflow/MinIO): {exc}", file=sys.stderr)
            sys.exit(2)

        current_hash = sha256_of_file(model_path)
        declared_hash, declared_run = model_ref_declared_in_mlbom(mlbom_path)
        print(f"[deployment-gate] SHA-256 del modelo descargado:     {current_hash}")
        print(f"[deployment-gate] SHA-256 declarado en el ML-BOM:    {declared_hash}")
        print(f"[deployment-gate] run_id de la versión del registro: {latest.run_id}")
        print(f"[deployment-gate] run_id declarado en el ML-BOM:     {declared_run}")

        c1 = cosign_verify(mlbom_path, mlbom_sig, "ML-BOM")
        hash_ok = declared_hash is not None and declared_hash == current_hash
        run_ok = declared_run is not None and declared_run == latest.run_id
        c2 = hash_ok and run_ok
        c3 = cosign_verify(model_path, model_sig, "modelo")

    def mark(ok):
        return "✅" if ok else "❌"

    print("")
    print("[deployment-gate] Controles de P-03:")
    print(f"  {mark(c1)} C1  Firma del ML-BOM (documento de enlace auténtico)")
    print(f"  {mark(c2)} C2  Vínculo ML-BOM ↔ modelo y versión (hash y run_id declarados = descargados)")
    print(f"  {mark(c3)} C3  Firma del modelo (artefacto auténtico)")
    print("")

    if c1 and c2 and c3:
        print("Los tres controles pasaron. Modelo APROBADO para despliegue.")
        sys.exit(0)

    if c1 and c3 and hash_ok and not run_ok:
        print(
            "Modelo, ML-BOM y firmas son auténticos y coherentes entre sí, pero el "
            "ML-BOM pertenece a otra versión del registro: reversión a una versión "
            "anterior. Un gate que solo verificara firmas y hash la habría aprobado."
        )
    elif c3 and not c2:
        print(
            "El modelo tiene una firma VÁLIDA pero no es el artefacto que declara el "
            "ML-BOM de esta versión: sustitución por un modelo legítimamente firmado "
            "de otra versión. Un gate basado solo en la firma lo habría aprobado."
        )
    print("Despliegue RECHAZADO.")
    sys.exit(1)


if __name__ == "__main__":
    main()
