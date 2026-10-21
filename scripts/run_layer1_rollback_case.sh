#!/usr/bin/env bash
# =============================================================================
# run_layer1_rollback_case.sh — Capa 1 (P-03), caso negativo "rollback"
# =============================================================================
# Reversión completa a una versión anterior. El atacante copia sobre la
# versión vigente el modelo, el ML-BOM y sus dos firmas de la versión
# anterior: cuatro artefactos auténticos y coherentes entre sí.
#
#   - C1 pasa (el ML-BOM está firmado) y C3 pasa (el modelo está firmado).
#   - El hash del modelo coincide con el que declara el ML-BOM.
#   - Lo detiene C2: el ML-BOM declara el run_id de otra versión del registro.
#
# Convención de salida del script: 0 si el gate se comportó según el contrato
# (rechazo = código 1 del componente), 1 si se desvió.
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
echo " CASO NEGATIVO — Reversión completa a una versión anterior"
echo "=============================================================="

echo ""
echo "[1/4] Registrando una versión ANTERIOR legítima (semilla 7, firmada)..."
docker compose run --rm -e RANDOM_SEED=7 trainer python train.py

echo ""
echo "[2/4] Registrando la versión VIGENTE legítima (semilla 42, firmada)..."
docker compose run --rm trainer python train.py

echo ""
echo "[3/4] Ataque: modelo, ML-BOM y sus firmas de la versión anterior se copian"
echo "      sobre la versión vigente (sin falsificar ninguna firma)..."
docker compose run --rm trainer python tamper_model.py --mode rollback

echo ""
echo "[4/4] Ejecutando el deployment-gate contra la versión atacada..."
set +e
docker compose run --rm deployment-gate python verify_and_deploy.py
GATE_EXIT=$?
set -e

echo ""
if [ "$GATE_EXIT" -eq 1 ]; then
  echo "✅ RESULTADO: el gate RECHAZÓ la reversión (comportamiento esperado)."
  echo "   Firmas válidas (C1 ✅, C3 ✅) y hash coherente; el rechazo proviene del"
  echo "   vínculo del ML-BOM con la versión del registro (C2 ❌)."
  exit 0
elif [ "$GATE_EXIT" -eq 2 ]; then
  echo "❌ ERROR DE INFRAESTRUCTURA (código 2): esto NO es una decisión del gate."
  exit 1
else
  echo "⚠️  ADVERTENCIA: el gate APROBÓ una reversión. Revisa el paso 3."
  exit 1
fi
