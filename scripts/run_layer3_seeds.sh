#!/usr/bin/env bash
# =============================================================================
# run_layer3_seeds.sh — Protocolo de sensibilidad de semillas (Capa 3, P-02)
# =============================================================================
# Ejecuta el experimento completo de la Capa 3 con 6 semillas distintas y
# verifica que el contrato 0/3/4 (clean/natural/adversarial) se cumpla en
# las 18 evaluaciones. Este script produce el registro reproducible que
# sustenta la afirmación AF-08 del capítulo de evaluación: el determinismo
# del Secure Retraining Gate para amplitudes de drift natural >= +9%/+0.06.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

SEEDS=(7 13 42 101 777 2026)
BATCHES=("batch_clean.csv" "batch_natural_drift.csv" "batch_adversarial.csv")
declare -A EXPECTED=(
  ["batch_clean.csv"]=0
  ["batch_natural_drift.csv"]=3
  ["batch_adversarial.csv"]=4
)

OVERALL_EXIT=0
declare -A RESULTS

for seed in "${SEEDS[@]}"; do
  echo ""
  echo "=============================================================="
  echo " SEMILLA $seed"
  echo "=============================================================="
  docker compose run --rm --no-deps feedback-gate rm -rf /app/data/quarantine
  docker compose run --rm --no-deps -e RANDOM_SEED="$seed" \
    feedback-gate python generate_feedback.py

  for batch in "${BATCHES[@]}"; do
    set +e
    docker compose run --rm --no-deps -e RANDOM_SEED="$seed" \
      feedback-gate python feedback_gate.py --batch "/app/data/$batch" >/dev/null 2>&1
    CODE=$?
    set -e
    RESULTS["$seed/$batch"]=$CODE
    if [ "$CODE" -ne "${EXPECTED[$batch]}" ]; then
      OVERALL_EXIT=1
    fi
  done
done

echo ""
echo "=============================================================="
echo " MATRIZ DE RESULTADOS (esperado: clean=0, natural=3, adversarial=4)"
echo "=============================================================="
printf "%-8s %-8s %-10s %-12s\n" "semilla" "clean" "natural" "adversarial"
for seed in "${SEEDS[@]}"; do
  printf "%-8s %-8s %-10s %-12s\n" "$seed" \
    "${RESULTS[$seed/batch_clean.csv]}" \
    "${RESULTS[$seed/batch_natural_drift.csv]}" \
    "${RESULTS[$seed/batch_adversarial.csv]}"
done

echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ 18/18 veredictos según contrato: determinismo confirmado en las 6 semillas."
else
  echo "⚠️  Al menos un veredicto se desvió del contrato. Revisar la matriz."
fi
exit "$OVERALL_EXIT"