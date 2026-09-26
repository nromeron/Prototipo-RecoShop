#!/usr/bin/env bash
# =============================================================================
# run_layer1_swap_signed_case.sh — Capa 1 (P-03), caso negativo "swap-signed"
# =============================================================================
# Demuestra el aporte específico del ML-BOM firmado como documento de enlace
# de P-03. El atacante no falsifica nada: sustituye el modelo de la versión
# más reciente por el de una versión anterior, JUNTO CON SU FIRMA LEGÍTIMA.
#
#   - Un gate basado solo en la firma del modelo (C3) lo APROBARÍA: la firma
#     es auténtica.
#   - El gate de P-03 lo RECHAZA por C2: el hash del modelo no coincide con
#     el declarado en el ML-BOM firmado de esa versión.
#
# Escenario real que representa: rollback malicioso o sustitución por un
# modelo más débil/vulnerable previamente aprobado (D-01).
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
echo " CASO NEGATIVO — Sustitución por un modelo legítimamente firmado"
echo "=============================================================="

echo ""
echo "[1/4] Registrando una versión ANTERIOR legítima (semilla 7, firmada)..."
docker compose run --rm -e RANDOM_SEED=7 trainer python train.py

echo ""
echo "[2/4] Registrando la versión VIGENTE legítima (semilla 42, firmada)..."
docker compose run --rm trainer python train.py

echo ""
echo "[3/4] Ataque: el modelo vigente y su firma se sustituyen por los de la"
echo "      versión anterior (sin falsificar ninguna firma)..."
docker compose run --rm trainer python tamper_model.py --mode swap-signed

echo ""
echo "[4/4] Ejecutando el deployment-gate contra la versión atacada..."
set +e
docker compose run --rm deployment-gate python verify_and_deploy.py
GATE_EXIT=$?
set -e

echo ""
if [ "$GATE_EXIT" -eq 1 ]; then
  echo "✅ RESULTADO: el gate RECHAZÓ el modelo sustituido (comportamiento esperado)."
  echo "   La firma del modelo era válida (C3 ✅); el rechazo proviene del vínculo"
  echo "   con el ML-BOM firmado (C2 ❌). Sin el documento de enlace de P-03,"
  echo "   este ataque habría sido aprobado."
  exit 0
elif [ "$GATE_EXIT" -eq 2 ]; then
  echo "❌ ERROR DE INFRAESTRUCTURA (código 2): esto NO es una decisión del gate."
  exit 1
else
  echo "⚠️  ADVERTENCIA: el gate APROBÓ un modelo sustituido. Revisa el paso 3."
  exit 1
fi
