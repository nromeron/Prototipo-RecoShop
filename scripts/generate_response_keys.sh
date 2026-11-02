#!/usr/bin/env bash
# =============================================================================
# generate_response_keys.sh
# =============================================================================
# Genera (si no existe ya) un par de claves Ed25519 para el Response
# Signer de P-01 (Capa 2), separado del par de claves cosign de la Capa 1
# (que firma artefactos de modelo en el Model Registry, no respuestas de
# inferencia en tiempo real).
#
# Relación con la tesis: este par de claves representa, en miniatura, la
# autoridad de firma del Sub-componente 3 (Protector del Canal / Response
# Signer) del patrón P-01, mitigación de D-05.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_DIR="$PROJECT_ROOT/keys"

if [ -f "$KEYS_DIR/response_ed25519.key" ] && [ -f "$KEYS_DIR/response_ed25519.pub" ]; then
  echo "Ya existe un par de claves Ed25519 de respuesta en $KEYS_DIR."
  echo "Si deseas regenerarlo, elimina primero response_ed25519.key y response_ed25519.pub."
  exit 0
fi

mkdir -p "$KEYS_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: se requiere Docker para generar las claves con este script."
  echo "Instala Docker Desktop o Docker Engine y vuelve a intentarlo."
  exit 1
fi

cd "$PROJECT_ROOT"

echo "Generando par de claves Ed25519 (Protector del Canal de Salida, P-01) en $KEYS_DIR ..."

# Se reutiliza la imagen del servicio "inference-gateway" (ya tiene
# 'cryptography' instalado, ver requirements.txt) en lugar de depender de
# una imagen adicional. --no-deps evita levantar mlflow/minio solo para
# generar un par de claves.
docker compose run --rm --no-deps --entrypoint python \
  -v "$KEYS_DIR:/keys-rw" \
  inference-gateway \
  -c "
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()

with open('/keys-rw/response_ed25519.key', 'wb') as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open('/keys-rw/response_ed25519.pub', 'wb') as f:
    f.write(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))

print('Par de claves Ed25519 generado.')
"

if [ ! -f "$KEYS_DIR/response_ed25519.key" ] || [ ! -f "$KEYS_DIR/response_ed25519.pub" ]; then
  echo "ERROR: la generación de claves no produjo los archivos esperados."
  echo "Revisa que la imagen del servicio 'inference-gateway' se haya construido correctamente."
  exit 1
fi

echo ""
echo "Claves generadas correctamente:"
ls -la "$KEYS_DIR"/response_ed25519.*
echo ""
echo "IMPORTANTE: response_ed25519.key es la clave PRIVADA del Response"
echo "Signer. No la compartas ni la subas a un repositorio público."
