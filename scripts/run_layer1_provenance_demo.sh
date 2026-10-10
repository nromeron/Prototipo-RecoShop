#!/usr/bin/env bash
# =============================================================================
# run_layer1_provenance_demo.sh — Capa 1 (P-03): Compuerta de Procedencia de Datos
# =============================================================================
# Ejercita el sub-componente de P-03 que trata D-07 en la ingesta primaria:
# el socio comercial publica la exportación de eventos con un manifiesto
# firmado, y la compuerta decide si el lote entra al lago de datos.
#
#   Escenario      Ataque                                         Esperado
#   legitimate     ninguno (lote real del socio, semilla 42)      exit 0 (ACEPTADO)
#   tampered       lote alterado después de la firma              exit 1 (RECHAZADO)
#   unauthorized   feed suplantado, firmado con clave no          exit 1 (RECHAZADO)
#                  registrada
#   poisoned       lote firmado por el socio comprometido, con    exit 4 (CUARENTENA)
#                  10 % de registros falsificados
#   forged-record  registro de procedencia fabricado por quien     exit 1 (RECHAZADO)
#                  escribe en recoshop-provenance, sin la clave
#                  de RecoShop
#
# El escenario legítimo deja el registro de procedencia, firmado por RecoShop,
# que train.py verifica y enlaza en el ML-BOM; por eso esta demo se ejecuta
# antes que las de la Capa 1. El registro fabricado apunta al conjunto de
# datos de la semilla 7: las demos de sustitución firmada lo declaran no
# verificado.
#
# Convención de salida: 0 si los cinco escenarios dan el código esperado;
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 1 — P-03 Compuerta de Procedencia de Datos (D-07)"
echo "=============================================================="

SCENARIOS=(
  "tampered|1"
  "unauthorized|1"
  "poisoned|4"
  "forged-record|1"
  "legitimate|0"
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
  docker compose run --rm trainer python provenance_gate.py --scenario "$scenario"
  CODE=$?
  set -e
  ACTUAL["$scenario"]=$CODE

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
echo " RESUMEN — Compuerta de Procedencia de Datos"
echo "=============================================================="
for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r scenario expected <<< "$entry"
  code="${ACTUAL[$scenario]}"
  if [ "$code" -eq "$expected" ]; then mark="✅"; else mark="❌"; fi
  printf "  %s %-14s exit %s (esperado %s)\n" "$mark" "$scenario" "$code" "$expected"
done
echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO GLOBAL: los cinco escenarios dieron la decisión esperada."
else
  echo "⚠️  RESULTADO GLOBAL: al menos un escenario no dio la decisión esperada."
fi
exit "$OVERALL_EXIT"
