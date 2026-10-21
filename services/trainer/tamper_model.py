"""
tamper_model.py
===============
ESTE SCRIPT NO ES PARTE DEL PIPELINE LEGÍTIMO DE ENTRENAMIENTO.

Simula el escenario de explotación concreto de la debilidad D-01
(Confianza Implícita en la Integridad de Artefactos del Model Registry),
descrito en el Entregable A4.2 de la tesis: un atacante que compromete el
almacenamiento del Model Registry (en este prototipo, el bucket
S3-compatible de MinIO donde MLflow guarda los artefactos) sustituye los
bytes del modelo YA REGISTRADO Y FIRMADO.

El atacante simulado NO puede regenerar una firma válida, porque no posee
la clave privada de firma (cosign.key permanece fuera de su alcance en todo
momento -- solo se monta, de solo lectura, en los contenedores trainer y
deployment-gate). Esto es exactamente lo que el sub-componente Artifact
Signing and Registry Gate de P-03 está diseñado para detectar.

Flujo:
  1. Consulta en MLflow cuál es la última versión registrada del modelo.
  2. Localiza el objeto S3 real (bucket + key) donde MLflow almacenó
     model.txt para esa versión.
  3. Sobrescribe ese objeto directamente en MinIO, añadiendo bytes
     arbitrarios al final del archivo. El archivo de firma (model.txt.sig)
     NO se modifica.

Después de ejecutar este script, el deployment-gate debe RECHAZAR el
modelo, porque el hash del artefacto ya no coincide con el hash que fue
firmado originalmente.

Modos de ataque (argumento --mode):
  append       (por defecto) Añade bytes al modelo de la última versión.
               Detectado por C2 (vínculo con el ML-BOM) y C3 (firma).
  swap-signed  Sustituye el modelo Y su firma de la última versión por los de
               la versión anterior: un artefacto auténtico, firmado con la
               clave legítima, pero que NO es el que esta versión declara.
               C3 pasa (la firma es válida); solo C2 lo detecta. Demuestra el
               aporte específico del ML-BOM firmado como documento de enlace.
  rollback     Reversión completa: copia sobre la última versión el modelo, el
               ML-BOM y sus dos firmas de la versión anterior. Los cuatro
               artefactos son auténticos y coherentes entre sí; C1 y C3 pasan y
               el hash coincide. Solo lo detecta el vínculo del ML-BOM con la
               versión del registro (run_id), parte de C2.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

import boto3
import mlflow
from mlflow.tracking import MlflowClient

MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "recoshop-ranker")


def get_latest_model_artifact_s3_location(model_name: str):
    """
    Retorna (bucket, key, version) del artefacto model.txt correspondiente
    a la versión más reciente registrada del modelo en MLflow.
    """
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise RuntimeError(
            f"No hay ninguna versión registrada del modelo '{model_name}' en MLflow. "
            "Ejecuta primero: docker compose run --rm trainer python train.py"
        )

    latest = max(versions, key=lambda v: int(v.version))
    run = client.get_run(latest.run_id)
    artifact_uri = run.info.artifact_uri  # ej: s3://mlflow-artifacts/<exp_id>/<run_id>/artifacts

    parsed = urlparse(artifact_uri)
    if parsed.scheme != "s3":
        raise RuntimeError(
            f"Se esperaba un artifact_uri de esquema s3://, se obtuvo: {artifact_uri}. "
            "Verifica que el servidor MLflow use --default-artifact-root s3://..."
        )

    bucket = parsed.netloc
    key = f"{parsed.path.lstrip('/')}/model/model.txt"

    return bucket, key, latest.version


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://minio:9000"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def _model_prefix(client: MlflowClient, model_version):
    """(bucket, prefijo s3 de la carpeta model/) de una versión registrada."""
    artifact_uri = client.get_run(model_version.run_id).info.artifact_uri
    parsed = urlparse(artifact_uri)
    return parsed.netloc, f"{parsed.path.lstrip('/')}/model"


def copy_from_previous(model_name: str, names) -> None:
    """Copia los artefactos `names` de la penúltima versión sobre la última."""
    client = MlflowClient()
    versions = sorted(
        client.search_model_versions(f"name='{model_name}'"), key=lambda v: int(v.version)
    )
    if len(versions) < 2:
        raise RuntimeError("Se requieren al menos dos versiones registradas.")
    source, target = versions[-2], versions[-1]
    src_bucket, src_prefix = _model_prefix(client, source)
    dst_bucket, dst_prefix = _model_prefix(client, target)
    s3 = _s3_client()
    for name in names:
        body = s3.get_object(Bucket=src_bucket, Key=f"{src_prefix}/{name}")["Body"].read()
        s3.put_object(Bucket=dst_bucket, Key=f"{dst_prefix}/{name}", Body=body)
        print(f"[tamper_model]   {name}: versión {source.version} -> versión {target.version}")


def rollback(model_name: str) -> None:
    """
    Reversión completa: la última versión pasa a contener, byte a byte, los
    artefactos firmados de la anterior. El atacante no necesita ninguna clave.
    """
    print("[tamper_model] Modo rollback: modelo, ML-BOM y sus firmas de la versión anterior.")
    copy_from_previous(
        model_name, ("model.txt", "model.txt.sig", "mlbom.cdx.json", "mlbom.cdx.json.sig")
    )


def swap_signed(model_name: str) -> None:
    """
    Sustituye model.txt y model.txt.sig de la última versión por los de la
    versión anterior. El atacante no necesita la clave de firma: reutiliza un
    artefacto que ya fue firmado legítimamente.
    """
    client = MlflowClient()
    versions = sorted(
        client.search_model_versions(f"name='{model_name}'"), key=lambda v: int(v.version)
    )
    if len(versions) < 2:
        raise RuntimeError(
            "El modo swap-signed requiere al menos dos versiones registradas "
            "(el script run_layer1_swap_signed_case.sh las crea)."
        )
    source, target = versions[-2], versions[-1]
    src_bucket, src_prefix = _model_prefix(client, source)
    dst_bucket, dst_prefix = _model_prefix(client, target)
    s3 = _s3_client()
    print(
        f"[tamper_model] Modo swap-signed: se copiará el modelo firmado de la versión "
        f"{source.version} sobre la versión {target.version}."
    )
    for name in ("model.txt", "model.txt.sig"):
        body = s3.get_object(Bucket=src_bucket, Key=f"{src_prefix}/{name}")["Body"].read()
        s3.put_object(Bucket=dst_bucket, Key=f"{dst_prefix}/{name}", Body=body)
        print(f"[tamper_model]   {name}: versión {source.version} -> versión {target.version}")
    print(
        "[tamper_model] NOTA: el ML-BOM de la versión atacada NO fue modificado "
        "(el atacante no puede re-firmarlo sin la clave privada)."
    )


def tamper_object(bucket: str, key: str) -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://minio:9000"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )

    print(f"[tamper_model] Descargando artefacto original: s3://{bucket}/{key}")
    original = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    print(f"[tamper_model] Tamaño original: {len(original)} bytes.")

    # Simulación del ataque: se añaden bytes arbitrarios al final del
    # artefacto, tal como haría un atacante que sustituye el modelo por una
    # versión con comportamiento alterado (D-01 / Model Poisoning /
    # MITRE ATLAS AML.T0018 - Manipulate AI Model).
    tampered = original + b"\n# BYTES INYECTADOS POR UN ATACANTE (simulacion D-01)\n"

    s3.put_object(Bucket=bucket, Key=key, Body=tampered)
    print(f"[tamper_model] Artefacto SOBRESCRITO en el registry ({len(tampered)} bytes).")
    print(
        "[tamper_model] NOTA: el archivo de firma (model.txt.sig) NO fue modificado, "
        "porque el atacante simulado no posee la clave privada de firma."
    )


def main():
    parser = argparse.ArgumentParser(description="Simulación de ataques D-01 (Capa 1)")
    parser.add_argument("--mode", choices=["append", "swap-signed", "rollback"], default="append")
    args = parser.parse_args()

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))

    if args.mode == "rollback":
        rollback(MLFLOW_MODEL_NAME)
        print(
            "[tamper_model] Simulación rollback completada. "
            "Ejecuta ahora el deployment-gate para observar el rechazo."
        )
        return

    if args.mode == "swap-signed":
        swap_signed(MLFLOW_MODEL_NAME)
        print(
            "[tamper_model] Simulación swap-signed completada. "
            "Ejecuta ahora el deployment-gate para observar el rechazo."
        )
        return

    bucket, key, version = get_latest_model_artifact_s3_location(MLFLOW_MODEL_NAME)
    print(
        f"[tamper_model] Atacando la versión {version} de '{MLFLOW_MODEL_NAME}' "
        f"en s3://{bucket}/{key}"
    )
    tamper_object(bucket, key)
    print(
        "[tamper_model] Simulación de ataque D-01 completada. "
        "Ejecuta ahora el deployment-gate para observar el rechazo."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - script de demostración
        print(f"ERROR en tamper_model.py: {exc}", file=sys.stderr)
        sys.exit(1)
