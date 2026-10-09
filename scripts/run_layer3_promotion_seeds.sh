#!/usr/bin/env bash
# =============================================================================
# run_layer3_promotion_seeds.sh — Sensibilidad de la Compuerta de Promoción
# =============================================================================
# Repite los dos escenarios sin alerta del Monitor con seis semillas de la
# retroalimentación (FEEDBACK_SEED = 500 + semilla), para comprobar que la
# decisión no depende de una muestra particular:
#
#   retroalimentación limpia     -> exit 0 (APROBADO)
#   retroalimentación envenenada -> exit 4 (RETENIDO por degradación selectiva)
#
# Reporta, por semilla, el delta de NDCG@10 global y el de la exactitud por
# pares en la categoría atacada (3).
#
# Convención de salida: 0 si los 12 veredictos coinciden con lo esperado;
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

SEEDS=(7 13 42 101 777 2026)
declare -A CODES GLOBAL CAT3
OVERALL_EXIT=0
OK=0

echo "=============================================================="
echo " CAPA 3 — Compuerta de Promoción: sensibilidad (6 semillas)"
echo "=============================================================="

for seed in "${SEEDS[@]}"; do
  fb_seed=$((500 + seed))
  for feedback in clean poisoned; do
    echo ""
    echo "--- Semilla $seed (FEEDBACK_SEED=$fb_seed) · retroalimentación $feedback ---"
    set +e
    OUT="$(docker compose run --rm --no-deps -e FEEDBACK_SEED="$fb_seed" trainer \
      python promotion_gate.py --feedback "$feedback" --monitor-signal none 2>&1)"
    CODE=$?
    set -e
    echo "$OUT" | grep -E '^  vigente|^  categoría 3:|^  (APROBADO|RETENIDO|RECHAZADO) ' || true
    CODES["$seed/$feedback"]=$CODE
    GLOBAL["$seed/$feedback"]="$(echo "$OUT" | grep -m1 -oE 'delta [+-][0-9.]+ \(tolerancia' | awk '{print $2}')"
    CAT3["$seed/$feedback"]="$(echo "$OUT" | grep -m1 -E '^  categoría 3:' | grep -oE 'delta [+-][0-9.]+' | awk '{print $2}')"
  done
  [ "${CODES[$seed/clean]}" -eq 0 ] && OK=$((OK + 1)) || OVERALL_EXIT=1
  [ "${CODES[$seed/poisoned]}" -eq 4 ] && OK=$((OK + 1)) || OVERALL_EXIT=1
done

echo ""
echo "=============================================================="
echo " MATRIZ DE RESULTADOS (esperado: limpia=0, envenenada=4)"
echo "=============================================================="
printf "%-8s %-7s %-14s %-12s %-11s %-14s %-12s\n" \
  "semilla" "limpia" "d_global" "d_cat3" "envenenada" "d_global" "d_cat3"
for seed in "${SEEDS[@]}"; do
  printf "%-8s %-7s %-14s %-12s %-11s %-14s %-12s\n" "$seed" \
    "${CODES[$seed/clean]}" "${GLOBAL[$seed/clean]}" "${CAT3[$seed/clean]}" \
    "${CODES[$seed/poisoned]}" "${GLOBAL[$seed/poisoned]}" "${CAT3[$seed/poisoned]}"
done
echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ $OK/12 veredictos según contrato."
else
  echo "⚠️  $OK/12 veredictos según contrato."
fi
exit "$OVERALL_EXIT"
