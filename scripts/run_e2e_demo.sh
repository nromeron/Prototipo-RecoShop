#!/usr/bin/env bash
# =============================================================================
# run_e2e_demo.sh — Integración de las tres capas en un ciclo de reentrenamiento
# =============================================================================
# Las demos por capa ejercitan cada patrón por separado. Esta demo encadena los
# tres en un mismo ciclo, y cada decisión sale del componente anterior, no de
# un parámetro del script:
#
#   Monitor de Drift de Seguridad (P-02) --(run en MLflow, etiqueta del ciclo)-->
#   Compuerta de Promoción (P-02) --(firma y ML-BOM, versión nueva)-->
#   Compuerta de despliegue (P-03) --> Pasarela de Inferencia (P-01) --> cliente
#
#   Escenario                Paso                                   Esperado
#   A. Ciclo adversarial     Monitor sobre el lote adversarial      exit 4 (cuarentena)
#                            Compuerta de Promoción (--register)    exit 1 (rechazado)
#                            Versión vigente del registro           sin cambios
#                            Compuerta de despliegue                exit 0 (vigente)
#   B. Ciclo legítimo        Monitor sobre el lote limpio           exit 0
#                            Compuerta de Promoción (--register)    exit 0, versión nueva
#                            Compuerta de despliegue                exit 0 (versión nueva)
#                            Arranque de la pasarela                sirve la versión nueva
#                            Cliente verificador (caso valid)       exit 0
#   C. Fallo en cascada      Alteración del modelo promovido        (ataque D-01)
#                            Compuerta de despliegue                exit 1
#                            Arranque de la pasarela                no arranca
#
# El reentrenamiento usa la retroalimentación por sesiones de la Compuerta de
# Promoción; los lotes del Monitor no tienen sesiones. Las dos piezas se
# conectan por el contrato de códigos de salida, registrado en MLflow.
#
# Convención de salida: 0 si todos los pasos dan el resultado esperado;
# 1 en caso contrario.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CYCLE_ADV="e2e-adversarial-${STAMP}"
CYCLE_LEG="e2e-legitimo-${STAMP}"
GATEWAY_CONTAINER="recoshop-inference-gateway"

STEPS=()        # "descripción|esperado|obtenido"
OVERALL_EXIT=0

record() {   # record <descripción> <esperado> <obtenido>
  STEPS+=("$1|$2|$3")
  if [ "$2" = "$3" ]; then
    echo "✅ OK: $1 → $3"
  else
    echo "❌ FALLO: $1 → se esperaba $2 y se obtuvo $3"
    OVERALL_EXIT=1
  fi
}

run_code() {   # ejecuta un comando y deja su código de salida en $CODE
  set +e
  "$@"
  CODE=$?
  set -e
}

latest_version() {
  docker compose run --rm -T trainer python -c \
    "from mlflow.tracking import MlflowClient as C; import mlflow, os; \
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI']); \
print(max(int(v.version) for v in C().search_model_versions(\"name='recoshop-ranker'\")))" \
    2>/dev/null | tail -1
}

restart_gateway() {   # deja en $STATE el estado final del contenedor y en $GW_LOG sus logs
  docker compose rm -sf inference-gateway >/dev/null 2>&1 || true
  docker compose up -d inference-gateway >/dev/null 2>&1 || true
  local elapsed=0 health="unknown"
  STATE="unknown"
  while [ "$elapsed" -lt 90 ]; do
    STATE="$(docker inspect --format='{{.State.Status}}' "$GATEWAY_CONTAINER" 2>/dev/null || echo unknown)"
    health="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$GATEWAY_CONTAINER" 2>/dev/null || echo unknown)"
    if [ "$STATE" = "exited" ] || [ "$health" = "healthy" ]; then break; fi
    sleep 2; elapsed=$((elapsed + 2))
  done
  if [ "$health" = "healthy" ]; then STATE="healthy"; fi
  GW_LOG="$(docker compose logs --no-color inference-gateway 2>/dev/null || true)"
  echo "$GW_LOG" | sed 's/^/   /'
  return 0
}

echo "=============================================================="
echo " INTEGRACIÓN — ciclo de reentrenamiento con las tres capas"
echo "=============================================================="

echo ""
echo "[0] Preparación: modelo vigente firmado y lotes de retroalimentación"
docker compose run --rm trainer python train.py
docker compose run --rm --no-deps feedback-gate rm -rf /app/data/quarantine
docker compose run --rm --no-deps feedback-gate python generate_feedback.py
VIGENTE="$(latest_version)"
echo "Versión vigente en el Model Registry: ${VIGENTE}"
echo "Ciclos: ${CYCLE_ADV} · ${CYCLE_LEG}"

# --------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " A. Ciclo adversarial"
echo "=============================================================="
echo ""
echo "[A1] Monitor de Drift de Seguridad sobre el lote adversarial"
run_code docker compose run --rm feedback-gate \
  python feedback_gate.py --batch /app/data/batch_adversarial.csv --cycle-id "$CYCLE_ADV"
record "A1 Monitor, lote adversarial" "exit 4" "exit $CODE"

echo ""
echo "[A2] Compuerta de Promoción: señal leída de MLflow, vigente desde el registro"
run_code docker compose run --rm trainer \
  python promotion_gate.py --feedback poisoned --cycle-id "$CYCLE_ADV" --register
record "A2 Compuerta de Promoción, retroalimentación envenenada" "exit 1" "exit $CODE"

AFTER_A="$(latest_version)"
record "A3 Versión vigente tras el ciclo adversarial" "versión ${VIGENTE}" "versión ${AFTER_A}"

echo ""
echo "[A4] Compuerta de despliegue sobre la versión vigente"
run_code docker compose run --rm deployment-gate python verify_and_deploy.py
record "A4 Compuerta de despliegue, versión ${AFTER_A}" "exit 0" "exit $CODE"

# --------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " B. Ciclo legítimo"
echo "=============================================================="
echo ""
echo "[B1] Monitor de Drift de Seguridad sobre el lote limpio"
run_code docker compose run --rm feedback-gate \
  python feedback_gate.py --batch /app/data/batch_clean.csv --cycle-id "$CYCLE_LEG"
record "B1 Monitor, lote limpio" "exit 0" "exit $CODE"

echo ""
echo "[B2] Compuerta de Promoción: aprobación, firma y registro del candidato"
run_code docker compose run --rm trainer \
  python promotion_gate.py --feedback clean --cycle-id "$CYCLE_LEG" --register
record "B2 Compuerta de Promoción, retroalimentación limpia" "exit 0" "exit $CODE"

NUEVA="$(latest_version)"
record "B3 Versión registrada por la Compuerta de Promoción" "versión $((VIGENTE + 1))" "versión ${NUEVA}"

echo ""
echo "[B4] Compuerta de despliegue sobre la versión promovida"
run_code docker compose run --rm deployment-gate python verify_and_deploy.py
record "B4 Compuerta de despliegue, versión ${NUEVA}" "exit 0" "exit $CODE"

echo ""
echo "[B5] Arranque de la pasarela de inferencia"
restart_gateway
SERVED="ninguna (estado: ${STATE})"
if [ "$STATE" = "healthy" ] && echo "$GW_LOG" | grep -q "Evaluando la versión ${NUEVA} "; then
  SERVED="versión ${NUEVA}"
fi
record "B5 Pasarela en servicio" "versión ${NUEVA}" "$SERVED"

echo ""
echo "[B6] Cliente verificador contra la pasarela"
run_code docker compose run --rm inference-client python client_demo.py --case valid
record "B6 Cliente, respuesta firmada" "exit 0" "exit $CODE"

# --------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " C. Fallo en cascada: el modelo promovido se altera tras su firma"
echo "=============================================================="
echo ""
echo "[C1] Ataque D-01 sobre la versión ${NUEVA}"
docker compose run --rm trainer python tamper_model.py --mode append

echo ""
echo "[C2] Compuerta de despliegue sobre la versión alterada"
run_code docker compose run --rm deployment-gate python verify_and_deploy.py
record "C2 Compuerta de despliegue, versión ${NUEVA} alterada" "exit 1" "exit $CODE"

echo ""
echo "[C3] Reinicio de la pasarela con la versión alterada"
restart_gateway
record "C3 Pasarela tras el reinicio" "exited" "$STATE"

# --------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " RESUMEN — integración de las tres capas"
echo "=============================================================="
for step in "${STEPS[@]}"; do
  IFS='|' read -r desc expected actual <<< "$step"
  if [ "$expected" = "$actual" ]; then mark="✅"; else mark="❌"; fi
  pad=$((56 - ${#desc})); [ "$pad" -lt 1 ] && pad=1
  printf "  %s %s%*s%s (esperado %s)\n" "$mark" "$desc" "$pad" "" "$actual" "$expected"
done
echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO GLOBAL: las tres capas se encadenaron según lo esperado."
else
  echo "⚠️  RESULTADO GLOBAL: al menos un paso no dio el resultado esperado."
fi
exit "$OVERALL_EXIT"
