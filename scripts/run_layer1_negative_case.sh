#!/usr/bin/env bash
# =============================================================================
# run_negative_case.sh — CASO NEGATIVO
# =============================================================================
# Entrena y firma un modelo válido, luego SIMULA el ataque descrito en la
# debilidad D-01: un actor con acceso al almacenamiento del Model Registry
# sustituye los bytes del modelo YA FIRMADO, sin poder regenerar una firma
# válida porque no posee la clave privada. Comportamiento esperado: el
# deployment-gate RECHAZA el modelo manipulado.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -f keys/cosign.key ] || [ ! -f keys/cosign.pub ]; then
  echo "ERROR: no se encontró el par de claves cosign en ./keys."
  echo "Ejecuta primero: ./scripts/generate_keys.sh"
  exit 1
fi

echo "=============================================================="
echo " CASO NEGATIVO — Simulación de ataque D-01 sobre RecoShop"
echo "=============================================================="

echo ""
echo "[1/3] Entrenando y firmando un modelo íntegro (idéntico al caso positivo)..."
docker compose run --rm trainer python train.py

echo ""
echo "[2/3] Simulando el ataque: sustitución de bytes del modelo YA FIRMADO"
echo "      directamente en el almacenamiento del Model Registry (MinIO)..."
docker compose run --rm trainer python tamper_model.py

echo ""
echo "[3/3] Ejecutando el deployment-gate contra el modelo manipulado..."
set +e
docker compose run --rm deployment-gate python verify_and_deploy.py
GATE_EXIT=$?
set -e

echo ""
if [ "$GATE_EXIT" -eq 1 ]; then
  echo "✅ RESULTADO: el gate RECHAZÓ el modelo manipulado (comportamiento esperado)."
  echo "   Esto demuestra que el sub-componente Artifact Signing and Registry"
  echo "   Gate de P-03 detecta la sustitución maliciosa descrita en D-01."
  exit 0
elif [ "$GATE_EXIT" -eq 2 ]; then
  echo "❌ ERROR DE INFRAESTRUCTURA: el gate no pudo evaluar el modelo (código 2)."
  echo "   Esto NO es un rechazo de firma; revisa la conexión con MLflow/MinIO"
  echo "   y la disponibilidad de las claves antes de reintentar."
  exit 1
else
  echo "⚠️  ADVERTENCIA: el gate aprobó un modelo que debería haber sido"
  echo "   rechazado. Revisa la configuración de claves y el paso de"
  echo "   manipulación anterior."
  exit 1
fi
