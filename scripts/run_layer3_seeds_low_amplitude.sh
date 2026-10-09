#!/usr/bin/env bash
# =============================================================================
# run_layer3_seeds_low_amplitude.sh — Frontera de la Capa 3 (P-02)
# =============================================================================
# Repite el protocolo de seis semillas con las amplitudes de deriva natural
# anteriores a la calibración (+5 % en precio, +0,03 en popularidad), en lugar
# de las calibradas (+9 % y +0,06).
#
# Documenta la frontera del detector: por debajo de las amplitudes calibradas,
# la alerta por deriva natural (código 3) deja de estar garantizada, mientras
# que la aceptación del lote limpio (0) y la cuarentena del adversarial (4) se
# mantienen.
#
# Convención de salida: 0 si el lote limpio da 0 y el adversarial da 4 en las
# seis semillas (la columna de deriva natural se reporta, sin condición);
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PRICE_PCT="0.05"
POPULARITY_DELTA="0.03"
SEEDS=(7 13 42 101 777 2026)
declare -A RESULTS
OVERALL_EXIT=0
NATURAL_ALERTS=0

echo "=============================================================="
echo " CAPA 3 — Frontera del detector (amplitud de deriva natural:"
echo " precio +5 %, popularidad +0,03)"
echo "=============================================================="

for seed in "${SEEDS[@]}"; do
  echo ""
  echo "--- Semilla $seed ---"
  docker compose run --rm --no-deps feedback-gate rm -rf /app/data/quarantine
  docker compose run --rm --no-deps \
    -e RANDOM_SEED="$seed" \
    -e NATURAL_DRIFT_PRICE_PCT="$PRICE_PCT" \
    -e NATURAL_DRIFT_POPULARITY_DELTA="$POPULARITY_DELTA" \
    feedback-gate python generate_feedback.py

  for batch in batch_clean.csv batch_natural_drift.csv batch_adversarial.csv; do
    set +e
    docker compose run --rm --no-deps -e RANDOM_SEED="$seed" \
      feedback-gate python feedback_gate.py --batch "/app/data/$batch" >/dev/null 2>&1
    CODE=$?
    set -e
    RESULTS["$seed/$batch"]=$CODE
  done

  [ "${RESULTS[$seed/batch_clean.csv]}" -ne 0 ] && OVERALL_EXIT=1
  [ "${RESULTS[$seed/batch_adversarial.csv]}" -ne 4 ] && OVERALL_EXIT=1
  [ "${RESULTS[$seed/batch_natural_drift.csv]}" -eq 3 ] && NATURAL_ALERTS=$((NATURAL_ALERTS + 1))
done

echo ""
echo "=============================================================="
echo " MATRIZ DE RESULTADOS (amplitud baja)"
echo "=============================================================="
printf "%-8s %-8s %-10s %-12s\n" "semilla" "clean" "natural" "adversarial"
for seed in "${SEEDS[@]}"; do
  printf "%-8s %-8s %-10s %-12s\n" "$seed" \
    "${RESULTS[$seed/batch_clean.csv]}" \
    "${RESULTS[$seed/batch_natural_drift.csv]}" \
    "${RESULTS[$seed/batch_adversarial.csv]}"
done
echo ""
echo "Alerta por deriva natural (código 3) en $NATURAL_ALERTS de ${#SEEDS[@]} semillas."
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ Lote limpio aceptado y lote adversarial en cuarentena en las seis semillas."
else
  echo "⚠️  El lote limpio o el adversarial se desviaron del contrato en alguna semilla."
fi
exit "$OVERALL_EXIT"
