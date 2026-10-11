#!/usr/bin/env bash
# =============================================================================
# generate_tls_certs.sh
# =============================================================================
# Genera (si no existe ya) la infraestructura de autenticación mutua TLS del
# Protector del Canal de P-01 (Capa 2) en ./keys/tls: la CA del prototipo,
# el certificado de la pasarela y un certificado por identidad de cliente
# (ver services/inference-gateway/make_tls.py).
#
# Relación con la tesis: Anexo C, P-01 — el Protector del Canal establece
# autenticación mutua y verifica la identidad del cliente. Mitigación de
# D-05; además, el estado por cliente de D-02 y D-04 sigue a una identidad
# autenticada.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_DIR="$PROJECT_ROOT/keys"

if [ -f "$KEYS_DIR/tls/ca.crt" ] && [ -f "$KEYS_DIR/tls/server.crt" ]; then
  echo "Ya existen los certificados TLS en $KEYS_DIR/tls."
  echo "Si deseas regenerarlos, elimina primero el directorio $KEYS_DIR/tls."
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: se requiere Docker para generar los certificados con este script."
  exit 1
fi

mkdir -p "$KEYS_DIR"
cd "$PROJECT_ROOT"

echo "Generando la CA y los certificados de autenticación mutua (P-01) en $KEYS_DIR/tls ..."

# Se reutiliza la imagen de inference-gateway ('cryptography' ya instalado).
# --no-deps evita levantar mlflow/minio solo para generar certificados.
docker compose run --rm --no-deps --entrypoint python \
  -v "$KEYS_DIR:/keys-rw" \
  inference-gateway \
  make_tls.py /keys-rw/tls

if [ ! -f "$KEYS_DIR/tls/ca.crt" ] || [ ! -f "$KEYS_DIR/tls/server.key" ]; then
  echo "ERROR: la generación no produjo los archivos esperados."
  echo "Reconstruye la imagen: docker compose build inference-gateway"
  exit 1
fi

echo ""
echo "Certificados generados:"
ls -la "$KEYS_DIR/tls" "$KEYS_DIR/tls/clients"
echo ""
echo "IMPORTANTE: los archivos .key son claves PRIVADAS. El directorio keys/"
echo "está excluido del repositorio; no lo subas."
