#!/usr/bin/env bash
# =============================================================================
# run_layer3_demo.sh — Capa 3 (P-02 Secure Retraining Gate)
# =============================================================================
# Este script ES el experimento DSR de la Capa 3, no un utilitario: su
# propósito es demostrar que el Secure Retraining Gate distingue
# correctamente los tres escenarios sintéticos generados por
# generate_feedback.py, con resultados EXACTOS y deterministas:
#
#     batch_clean.csv           -> exit 0 (ACEPTADO)
#     batch_natural_drift.csv   -> exit 3 (ACEPTADO_CON_ALERTA)
#     batch_adversarial.csv     -> exit 4 (CUARENTENA)
#
# Cualquier otra combinación de resultados se reporta como FALLO (exit 1),
# distinguiendo explícitamente el caso "exit 2 = error de infraestructura"
# de una decisión incorrecta del gate.
#
# Relación con la tesis: Patrón P-02 — Secure Retraining Gate, mitigación
# de D-03 (y, de forma complementaria, la variante feedback de D-07). Ver
# secciones 3.4 y 4.4.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 3 — P-02 Secure Retraining Gate"
echo "=============================================================="

# --- 1) Generar baseline + 3 lotes sintéticos ---
echo ""
echo "[1/5] Generando baseline y lotes sintéticos de feedback..."
echo "      Limpiando cuarentena de corridas anteriores..."
docker compose run --rm --no-deps feedback-gate rm -rf /app/data/quarantine
docker compose run --rm --no-deps feedback-gate python generate_feedback.py

# --- 2) y 3) Ejecutar el gate contra los 3 lotes, en orden, validando el
#            resultado EXACTO esperado para cada uno ---
declare -A EXPECTED=(
  ["batch_clean.csv"]=0
  ["batch_natural_drift.csv"]=3
  ["batch_adversarial.csv"]=4
)
ORDER=("batch_clean.csv" "batch_natural_drift.csv" "batch_adversarial.csv")

declare -A ACTUAL
OVERALL_EXIT=0

echo ""
echo "[2/5] Evaluando los 3 lotes en orden clean -> natural -> adversarial..."

for batch in "${ORDER[@]}"; do
  echo ""
  echo "--- Evaluando $batch (se espera exit ${EXPECTED[$batch]}) ---"
  set +e
  docker compose run --rm --no-deps feedback-gate python feedback_gate.py --batch "/app/data/$batch"
  CODE=$?
  set -e
  ACTUAL["$batch"]=$CODE

  if [ "$CODE" -eq 2 ]; then
    echo "❌ ERROR DE INFRAESTRUCTURA evaluando $batch (exit 2) -- esto NO es una"
    echo "   decisión del gate, sino un problema de entorno (archivos, formato)."
    OVERALL_EXIT=1
  elif [ "$CODE" -ne "${EXPECTED[$batch]}" ]; then
    echo "❌ FALLO: se esperaba exit ${EXPECTED[$batch]} para $batch, se obtuvo $CODE."
    OVERALL_EXIT=1
  else
    echo "✅ OK: $batch se comportó como se esperaba (exit $CODE)."
  fi
done

# --- 4) Mostrar el reason.json de la cuarentena como evidencia ---
echo ""
echo "[3/5] Evidencia de cuarentena (reason.json del lote adversarial)..."
set +e
docker compose run --rm --no-deps feedback-gate cat /app/data/quarantine/batch_adversarial.csv.reason.json
REASON_EXIT=$?
set -e

if [ "$REASON_EXIT" -ne 0 ]; then
  echo "❌ No se encontró reason.json para batch_adversarial.csv -- se esperaba que"
  echo "   el lote adversarial hubiera sido puesto en cuarentena en el paso anterior."
  OVERALL_EXIT=1
fi

# --- 5) Resumen final ---
echo ""
echo "[4/5] Resumen de resultados:"
for batch in "${ORDER[@]}"; do
  if [ "${ACTUAL[$batch]}" -eq "${EXPECTED[$batch]}" ]; then
    echo "  ✅ $batch: exit ${ACTUAL[$batch]} (esperado: ${EXPECTED[$batch]})"
  else
    echo "  ❌ $batch: exit ${ACTUAL[$batch]} (esperado: ${EXPECTED[$batch]})"
  fi
done

echo ""
echo "[5/5] =============================================================="
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo " ✅ RESULTADO GLOBAL: el Secure Retraining Gate distinguió correctamente"
  echo "    los tres escenarios (clean/natural/adversarial) de forma determinista."
else
  echo " ⚠️  RESULTADO GLOBAL: al menos un escenario no dio el resultado esperado."
fi
echo "=============================================================="

exit "$OVERALL_EXIT"
