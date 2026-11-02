#!/usr/bin/env bash
# =============================================================================
# run_layer2_demo.sh — Capa 2 (P-01 Secure Inference Gateway)
# =============================================================================
# Orquesta la demostración completa de la Capa 2:
#   1. Verifica que existan las claves cosign (Capa 1), Ed25519 (Capa 2) y
#      los certificados de autenticación mutua (Capa 2).
#   2. Levanta la infraestructura (MinIO + MLflow).
#   3. Si no hay modelo registrado, entrena uno reutilizando la Capa 1
#      SIN modificarla (docker compose run --rm trainer python train.py).
#   4. Levanta inference-gateway y espera su healthcheck.
#   5. Ejecuta los 8 casos del cliente verificador (client_demo.py).
#   6. Imprime un resumen final; sale 0 solo si los 8 casos dieron el
#      resultado esperado.
#
# Relación con la tesis: Patrón P-01 — Secure Inference Gateway, mitigación
# de D-02, D-04 y D-05 (ver secciones 3.4 y 4.3).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 2 — P-01 Secure Inference Gateway"
echo "=============================================================="

# --- 1) Verificar prerrequisitos: claves cosign (Capa 1) y Ed25519 (Capa 2) ---
if [ ! -f keys/cosign.key ] || [ ! -f keys/cosign.pub ]; then
  echo ""
  echo "ERROR: no se encontró el par de claves cosign en ./keys."
  echo "Ejecuta primero: ./scripts/generate_keys.sh"
  exit 1
fi

if [ ! -f keys/response_ed25519.key ] || [ ! -f keys/response_ed25519.pub ]; then
  echo ""
  echo "ERROR: no se encontró el par de claves Ed25519 de respuesta en ./keys."
  echo "Ejecuta primero: ./scripts/generate_response_keys.sh"
  exit 1
fi

if [ ! -f keys/tls/ca.crt ] || [ ! -f keys/tls/server.crt ]; then
  echo ""
  echo "ERROR: no se encontraron los certificados de autenticación mutua en ./keys/tls."
  echo "Ejecuta primero: ./scripts/generate_tls_certs.sh"
  exit 1
fi

echo ""
echo "[1/6] Claves cosign y Ed25519 y certificados TLS verificados."

# --- 2) Levantar infraestructura (MinIO + MLflow, transitivamente) ---
echo ""
echo "[2/6] Levantando infraestructura (MinIO + MLflow)..."
docker compose up -d mlflow

echo "      Esperando a que mlflow esté healthy..."
MLFLOW_MAX_WAIT=60
elapsed=0
while [ "$elapsed" -lt "$MLFLOW_MAX_WAIT" ]; do
  HEALTH="$(docker inspect --format='{{.State.Health.Status}}' recoshop-mlflow 2>/dev/null || echo "unknown")"
  if [ "$HEALTH" = "healthy" ]; then
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if [ "$HEALTH" != "healthy" ]; then
  echo ""
  echo "ERROR: mlflow no alcanzó el estado 'healthy' tras ${MLFLOW_MAX_WAIT}s."
  docker compose logs mlflow
  exit 1
fi
echo "      mlflow está healthy."

# --- 3) Registrar una versión fresca del modelo ---
# Se entrena SIEMPRE una versión nueva en lugar de reutilizar la última:
# el caso negativo de la Capa 1 deja deliberadamente un artefacto
# manipulado como versión más reciente del registry, y esta demo debe
# arrancar desde un modelo íntegro con independencia del estado previo.
echo ""
echo "[3/6] Registrando una versión fresca del modelo (Capa 1, sin modificarla)..."
docker compose run --rm trainer python train.py

# --- 4) Levantar inference-gateway y esperar su healthcheck ---
echo ""
echo "[4/6] Levantando inference-gateway y esperando su healthcheck..."
docker compose up -d inference-gateway

GATEWAY_MAX_WAIT=60
elapsed=0
GATEWAY_STATUS=""
while [ "$elapsed" -lt "$GATEWAY_MAX_WAIT" ]; do
  STATE="$(docker inspect --format='{{.State.Status}}' recoshop-inference-gateway 2>/dev/null || echo "unknown")"
  HEALTH="$(docker inspect --format='{{.State.Health.Status}}' recoshop-inference-gateway 2>/dev/null || echo "unknown")"

  if [ "$STATE" = "exited" ]; then
    echo ""
    echo "ERROR: el contenedor inference-gateway terminó inesperadamente."
    echo "Esto normalmente significa que la verificación de firma cosign del"
    echo "modelo falló al arrancar (integración con P-03, Capa 1). Revisa los logs:"
    docker compose logs inference-gateway
    exit 1
  fi

  if [ "$HEALTH" = "healthy" ]; then
    GATEWAY_STATUS="healthy"
    break
  fi

  sleep 2
  elapsed=$((elapsed + 2))
done

if [ "$GATEWAY_STATUS" != "healthy" ]; then
  echo ""
  echo "ERROR: inference-gateway no alcanzó el estado 'healthy' tras ${GATEWAY_MAX_WAIT}s."
  docker compose logs inference-gateway
  exit 1
fi
echo "      inference-gateway está healthy."

# --- 5) Ejecutar los 8 casos del cliente verificador ---
echo ""
echo "[5/6] Ejecutando los casos del cliente verificador (client_demo.py)..."

CASES=("valid" "invalid-input" "rate-limit" "cross-hardening" "tampered-response"
       "no-client-cert" "untrusted-cert" "identity-rotation")
declare -A CASE_RESULTS
OVERALL_EXIT=0

for demo_case in "${CASES[@]}"; do
  echo ""
  echo "--- Caso: $demo_case ---"
  set +e
  docker compose run --rm inference-client python client_demo.py --case "$demo_case"
  CASE_EXIT=$?
  set -e
  CASE_RESULTS["$demo_case"]=$CASE_EXIT
  if [ "$CASE_EXIT" -ne 0 ]; then
    OVERALL_EXIT=1
  fi
done

# --- 6) Resumen final ---
echo ""
echo "=============================================================="
echo " RESUMEN — Capa 2 (P-01 Secure Inference Gateway)"
echo "=============================================================="
for demo_case in "${CASES[@]}"; do
  if [ "${CASE_RESULTS[$demo_case]}" -eq 0 ]; then
    echo "  ✅ $demo_case: OK"
  else
    echo "  ❌ $demo_case: FALLÓ"
  fi
done

echo ""
if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "✅ RESULTADO GLOBAL: los 8 casos de la Capa 2 dieron el resultado esperado."
else
  echo "⚠️  RESULTADO GLOBAL: al menos un caso de la Capa 2 no dio el resultado esperado."
fi

exit "$OVERALL_EXIT"
