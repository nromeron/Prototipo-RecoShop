#!/usr/bin/env bash
# =============================================================================
# run_layer2_swap_signed_startup.sh — Capa 2 (P-01) ante la sustitución firmada
# =============================================================================
# Defensa en profundidad entre P-03 y P-01. Se repite el ataque de la Capa 1
# (el modelo vigente y su firma se sustituyen por los de una versión anterior,
# sin falsificar ninguna firma) y se levanta la pasarela de inferencia.
#
# Comportamiento esperado: la pasarela se NIEGA A ARRANCAR, porque al iniciar
# verifica también el vínculo entre el modelo y su ML-BOM firmado. Una
# verificación basada solo en la firma del modelo lo habría servido.
#
# Convención de salida: 0 si la pasarela se comportó según el contrato (no
# arrancó y registró el motivo), 1 si se desvió.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================================="
echo " CAPA 2 — Arranque de la pasarela ante una sustitución firmada"
echo "=============================================================="

echo ""
echo "[1/4] Registrando una versión anterior (semilla 7) y la vigente (semilla 42)..."
docker compose run --rm -e RANDOM_SEED=7 trainer python train.py
docker compose run --rm trainer python train.py

echo ""
echo "[2/4] Ataque: el modelo vigente y su firma se sustituyen por los de la versión anterior..."
docker compose run --rm trainer python tamper_model.py --mode swap-signed

echo ""
echo "[3/4] Levantando la pasarela de inferencia desde cero..."
docker compose rm -sf inference-gateway >/dev/null 2>&1 || true
docker compose up -d inference-gateway

MAX_WAIT=60
elapsed=0
STATE="unknown"
HEALTH="unknown"
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  STATE="$(docker inspect --format='{{.State.Status}}' recoshop-inference-gateway 2>/dev/null || echo unknown)"
  HEALTH="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{end}}' recoshop-inference-gateway 2>/dev/null || echo unknown)"
  if [ "$STATE" = "exited" ] || [ "$HEALTH" = "healthy" ]; then
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

echo ""
echo "[4/4] Resultado (estado del contenedor: $STATE)"
docker compose logs --no-color inference-gateway | sed 's/^/   /'

echo ""
if [ "$STATE" = "exited" ] && docker compose logs --no-color inference-gateway | grep -q "no es el que declara el ML-BOM"; then
  echo "✅ RESULTADO: la pasarela se negó a servir el modelo sustituido (comportamiento esperado)."
  echo "   La firma del modelo era válida; el rechazo proviene del vínculo con el ML-BOM firmado."
  exit 0
fi
echo "⚠️  RESULTADO: la pasarela no se comportó según lo esperado."
exit 1
