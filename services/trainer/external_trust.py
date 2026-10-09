"""
external_trust.py
=================
Utilidades compartidas por los dos sub-componentes de P-03 que reciben
artefactos de TERCEROS: la Compuerta de Procedencia de Datos
(provenance_gate.py) y el Validador de Modelos Externos
(external_model_validator.py).

Simula, sobre el MinIO del prototipo, tres espacios separados:

  - external-sources   : lo que publican los terceros (el socio que exporta
                         eventos de comercio y el proveedor de modelos base).
                         Es territorio NO confiable: un atacante puede
                         escribir en él.
  - recoshop-trust     : el almacén de anclas de confianza de RecoShop: las
                         claves públicas de las fuentes registradas. Lo
                         escribe solo el proceso de alta de una fuente.
  - recoshop-provenance: los registros de procedencia y de validación que
                         emiten las compuertas cuando aceptan un artefacto.

Cada tercero simulado tiene su propio par de claves cosign. La clave privada
vive en el espacio del tercero (no en keys/ de RecoShop) y la pública se
registra en recoshop-trust al dar de alta la fuente. Un atacante que firme
con su propia clave produce una firma válida para SU clave, pero esa clave no
está registrada: la verificación contra el ancla de confianza falla.

Las claves de los terceros se generan sin contraseña porque son de terceros
SIMULADOS; las claves propias de RecoShop siguen en keys/ (generate_keys.sh).
"""

import hashlib
import os
import subprocess
import tempfile

import boto3
from botocore.exceptions import ClientError

EXTERNAL_BUCKET = "external-sources"
TRUST_BUCKET = "recoshop-trust"
PROVENANCE_BUCKET = "recoshop-provenance"

# Fuentes registradas: identificador lógico -> nombre del ancla de confianza.
DATA_PARTNER = "recoshop-commerce-api"          # socio que exporta /export/events
MODEL_PROVIDER = "models-hub/sessions-ranker-base"  # proveedor del modelo base


def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://minio:9000"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def ensure_buckets(client=None) -> None:
    client = client or s3()
    for bucket in (EXTERNAL_BUCKET, TRUST_BUCKET, PROVENANCE_BUCKET):
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            client.create_bucket(Bucket=bucket)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def _party_key_prefix(party: str) -> str:
    return "_parties/" + party.replace("/", "__")


def _trust_key(party: str) -> str:
    return party.replace("/", "__") + ".pub"


def _cosign_env() -> dict:
    env = dict(os.environ)
    env["COSIGN_PASSWORD"] = ""   # claves de terceros simulados, sin contraseña
    return env


def generate_key_pair(workdir: str, prefix: str):
    """Genera un par de claves cosign en workdir. Retorna (privada, pública)."""
    subprocess.run(
        ["cosign", "generate-key-pair", "--output-key-prefix", prefix],
        cwd=workdir, env=_cosign_env(), check=True, capture_output=True, text=True,
    )
    return os.path.join(workdir, prefix + ".key"), os.path.join(workdir, prefix + ".pub")


def onboard_party(party: str, client=None) -> None:
    """
    Alta de una fuente externa (idempotente): genera el par de claves del
    tercero en su propio espacio y registra la clave pública en el almacén de
    anclas de confianza de RecoShop.
    """
    client = client or s3()
    ensure_buckets(client)
    prefix = _party_key_prefix(party)
    if object_exists(client, EXTERNAL_BUCKET, prefix + "/cosign.key") and \
            object_exists(client, TRUST_BUCKET, _trust_key(party)):
        return
    with tempfile.TemporaryDirectory() as tmp:
        priv, pub = generate_key_pair(tmp, "party")
        client.upload_file(priv, EXTERNAL_BUCKET, prefix + "/cosign.key")
        client.upload_file(pub, EXTERNAL_BUCKET, prefix + "/cosign.pub")
        client.upload_file(pub, TRUST_BUCKET, _trust_key(party))
    print(f"[alta-de-fuente] Fuente registrada: {party} (clave pública en {TRUST_BUCKET}/{_trust_key(party)})")


def party_private_key(party: str, dest_dir: str, client=None) -> str:
    """Clave privada del tercero simulado (solo la usa el propio tercero)."""
    client = client or s3()
    path = os.path.join(dest_dir, "party.key")
    client.download_file(EXTERNAL_BUCKET, _party_key_prefix(party) + "/cosign.key", path)
    return path


def trust_anchor(party: str, dest_dir: str, client=None):
    """Clave pública registrada para `party`, o None si la fuente no está registrada."""
    client = client or s3()
    path = os.path.join(dest_dir, "anchor.pub")
    try:
        client.download_file(TRUST_BUCKET, _trust_key(party), path)
    except ClientError:
        return None
    return path


def sign_blob(blob_path: str, key_path: str, sig_path: str) -> None:
    subprocess.run(
        ["cosign", "sign-blob", "--key", key_path, "--output-signature", sig_path,
         "--tlog-upload=false", "--yes", blob_path],
        env=_cosign_env(), check=True, capture_output=True, text=True,
    )


def verify_blob(blob_path: str, sig_path: str, pub_path: str) -> bool:
    result = subprocess.run(
        ["cosign", "verify-blob", "--key", pub_path, "--signature", sig_path,
         "--insecure-ignore-tlog=true", blob_path],
        env=_cosign_env(), capture_output=True, text=True,
    )
    return result.returncode == 0
