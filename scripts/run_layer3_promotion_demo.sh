#!/usr/bin/env bash
# =============================================================================
# run_layer3_promotion_demo.sh — Capa 3 (P-02): Compuerta de Promoción
# =============================================================================
# Ejercita el tercer sub-componente de P-02, la Compuerta de Promoción del
# Modelo Reentrenado, con la matriz completa de su política: retroalimentación
# limpia o envenenada, con o sin alerta adversarial del Monitor de Drift de
# Seguridad.
#
#   Escenario                                   Esperado
#   limpia,     Monitor sin alerta              exit 0 (APROBADO)
#   envenenada, Monitor sin alerta              exit 4 (RETENIDO: degradación
#                                                       selectiva que el Monitor
#                                                       no detectó)
#   envenenada, Monitor con alerta adversarial  exit 1 (RECHAZADO)
#   limpia,     Monitor con alerta adversarial  exit 4 (RETENIDO: alerta sin
#                                                       degradación medible)
#
# Convención de salida: 0 si los cuatro escenarios dan el código esperado;
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 3 — P-02 Compuerta de Promoción del Modelo Reentrenado"
echo "=============================================================="

SCENARIOS=(
  "clean|none|0"
  "poisoned|none|4"
  "poisoned|adversarial|1"
  "clean|adversarial|4"
)

declare -A ACTUAL
OVERALL_EXIT=0
i=0

for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r feedback signal expected <<< "$entry"
  i=$((i + 1))
  echo ""
  echo "[$i/${#SCENARIOS[@]}] Retroalimentación: $feedback · señal del Monitor: $signal (se espera exit $expected)"
  set +e
  docker compose run --rm --no-deps trainer \
    python promotion_gate.py --feedback "$feedback" --monitor-signal "$signal"
  CODE=$?
  set -e
  ACTUAL["$feedback/$signal"]=$CODE

  if [ "$CODE" -eq 2 ]; then
    echo "❌ ERROR DE INFRAESTRUCTURA (exit 2): no es una decisión de la compuerta."
    OVERALL_EXIT=1
  elif [ "$CODE" -ne "$expected" ]; then
    echo "❌ FALLO: se esperaba exit $expected y se obtuvo $CODE."
    OVERALL_EXIT=1
  else
    echo "✅ OK: exit $CODE, según lo esperado."
  fi
done

echo ""
echo "=============================================================="
echo " RESUMEN — Compuerta de Promoción"
echo "=============================================================="
for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r feedback signal expected <<< "$entry"
  code="${ACTUAL[$feedback/$signal]}"
  if [ "$code" -eq "$expected" ]; then mark="✅"; else mark="❌"; fi
  printf "  %s %-9s %-12s exit %s (esperado %s)\n" "$mark" "$feedback" "$signal" "$code" "$expected"
done
echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO GLOBAL: los cuatro escenarios dieron la decisión esperada."
else
  echo "⚠️  RESULTADO GLOBAL: al menos un escenario no dio la decisión esperada."
fi
exit "$OVERALL_EXIT"
