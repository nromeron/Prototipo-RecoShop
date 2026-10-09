#!/usr/bin/env bash
# =============================================================================
# run_layer1_external_model_demo.sh — Capa 1 (P-03): Validador de Modelos Externos
# =============================================================================
# Ejercita el sub-componente de P-03 que trata D-06: el proveedor publica un
# modelo base preentrenado y el validador decide si puede usarse como punto
# de partida del entrenamiento.
#
#   Escenario         Ataque                                      Esperado
#   legitimate        ninguno                                     exit 0 (ACEPTADO)
#   impostor          suplantación tipográfica del repositorio,   exit 1 (RECHAZADO)
#                     firmada con clave no registrada
#   malicious-pickle  pickle firmado que ejecuta código al        exit 1 (RECHAZADO)
#                     cargarse (cuenta del proveedor comprometida)
#   backdoor          modelo firmado con puerta trasera           exit 4 (CUARENTENA)
#                     (disparador price = 13.37)
#
# El pickle malicioso nunca se carga: el validador lo inspecciona con
# pickletools. Su carga útil solo imprimiría un mensaje.
#
# Convención de salida: 0 si los cuatro escenarios dan el código esperado;
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 1 — P-03 Validador de Modelos Externos (D-06)"
echo "=============================================================="

SCENARIOS=(
  "legitimate|0"
  "impostor|1"
  "malicious-pickle|1"
  "backdoor|4"
)

declare -A ACTUAL
OVERALL_EXIT=0
i=0

for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r scenario expected <<< "$entry"
  i=$((i + 1))
  echo ""
  echo "[$i/${#SCENARIOS[@]}] Escenario: $scenario (se espera exit $expected)"
  set +e
  docker compose run --rm trainer python external_model_validator.py --scenario "$scenario"
  CODE=$?
  set -e
  ACTUAL["$scenario"]=$CODE

  if [ "$CODE" -eq 2 ]; then
    echo "❌ ERROR DE INFRAESTRUCTURA (exit 2): no es una decisión del validador."
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
echo " RESUMEN — Validador de Modelos Externos"
echo "=============================================================="
for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r scenario expected <<< "$entry"
  code="${ACTUAL[$scenario]}"
  if [ "$code" -eq "$expected" ]; then mark="✅"; else mark="❌"; fi
  printf "  %s %-17s exit %s (esperado %s)\n" "$mark" "$scenario" "$code" "$expected"
done
echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO GLOBAL: los cuatro escenarios dieron la decisión esperada."
else
  echo "⚠️  RESULTADO GLOBAL: al menos un escenario no dio la decisión esperada."
fi
exit "$OVERALL_EXIT"
