#!/usr/bin/env bash
# =============================================================================
# run_positive_case.sh — CASO POSITIVO
# =============================================================================
# Entrena un modelo, lo firma con cosign, lo registra en MLflow, y ejecuta
# el deployment-gate. Comportamiento esperado: el gate APRUEBA el modelo,
# porque la firma es válida y el artefacto no fue alterado después de
# firmarse.
#
# Relación con la tesis: demuestra el camino "feliz" del sub-componente
# Artifact Signing and Registry Gate de P-03 sobre la debilidad D-01.
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
echo " CASO POSITIVO — Modelo firmado correctamente (P-03 / D-01)"
echo "=============================================================="

echo ""
echo "[1/2] Entrenando el modelo LightGBM, firmándolo con cosign y"
echo "      registrándolo en MLflow Model Registry..."
docker compose run --rm trainer python train.py

echo ""
echo "[2/2] Ejecutando el deployment-gate para verificar la firma..."
set +e
docker compose run --rm deployment-gate python verify_and_deploy.py
GATE_EXIT=$?
set -e

echo ""
if [ "$GATE_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO: el gate APROBÓ el modelo (comportamiento esperado)."
  exit 0
else
  echo "⚠️  ADVERTENCIA: el gate rechazó un modelo que debería haber sido válido."
  echo "   Revisa los logs anteriores para diagnosticar el problema."
  exit 1
fi
