#!/usr/bin/env bash
# =============================================================================
# generate_keys.sh
# =============================================================================
# Genera (si no existen ya) un par de claves cosign para el prototipo,
# usando la imagen oficial de cosign en un contenedor efímero. No requiere
# que el evaluador tenga cosign instalado en su máquina.
#
# Relación con la tesis: este par de claves representa, en miniatura, la
# "autoridad de firma" del sub-componente Artifact Signing and Registry
# Gate de P-03. En un entorno de producción real, esta clave debe
# gestionarse mediante un KMS (ver Fuerzas de P-03: "Gestión criptográfica
# vs. capacidad del equipo ML"), nunca como un archivo plano en disco como
# se hace aquí por simplicidad pedagógica.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_DIR="$PROJECT_ROOT/keys"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo "No se encontró .env — cópialo desde .env.example antes de continuar:"
  echo "  cp .env.example .env"
  exit 1
fi

# shellcheck disable=SC1090
source "$PROJECT_ROOT/.env"
export COSIGN_PASSWORD

if [ -f "$KEYS_DIR/cosign.key" ] && [ -f "$KEYS_DIR/cosign.pub" ]; then
  echo "Ya existe un par de claves cosign en $KEYS_DIR."
  echo "Si deseas regenerarlo, elimina primero cosign.key y cosign.pub."
  exit 0
fi

mkdir -p "$KEYS_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: se requiere Docker para generar las claves con este script."
  echo "Instala Docker Desktop o Docker Engine y vuelve a intentarlo."
  exit 1
fi

echo "Generando par de claves cosign en $KEYS_DIR ..."

# Se reutiliza la imagen del servicio "trainer" (ya contiene cosign v2.4.1,
# ver services/trainer/Dockerfile) en lugar de depender de una imagen
# adicional de Sigstore. El -v de este comando puntual sobrescribe, de
# forma escribible, el mount read-only que trainer define en
# docker-compose.yml para ./keys.
cd "$PROJECT_ROOT"
docker compose run --rm --no-deps --entrypoint cosign \
  -v "$KEYS_DIR:/keys-rw" \
  -w /keys-rw \
  -e COSIGN_PASSWORD \
  trainer generate-key-pair

if [ ! -f "$KEYS_DIR/cosign.key" ] || [ ! -f "$KEYS_DIR/cosign.pub" ]; then
  echo "ERROR: la generación de claves no produjo los archivos esperados."
  echo "Revisa que la imagen del servicio 'trainer' se haya construido correctamente."
  exit 1
fi

echo ""
echo "Claves generadas correctamente:"
ls -la "$KEYS_DIR"
echo ""
echo "IMPORTANTE: cosign.key es la clave PRIVADA del prototipo. No la"
echo "compartas ni la subas a un repositorio público."
