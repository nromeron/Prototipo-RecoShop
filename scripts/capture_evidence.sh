#!/usr/bin/env bash
# =============================================================================
# capture_evidence.sh — Captura reproducible de la evidencia del prototipo
# =============================================================================
# Ejecuta todas las demos de las tres capas y guarda un log por demo en
# evidence/, cada uno con un encabezado de procedencia (fecha UTC, commit,
# versiones de Docker e identificadores de imagen). Al final genera un
# resumen y un manifiesto SHA-256 de los logs.
#
# Propósito: que la evidencia del Anexo E sea verificable. Cualquier persona
# que clone el repositorio puede ejecutar este script y obtener registros
# comparables con los publicados.
#
# Uso: ./scripts/capture_evidence.sh
# Requisitos: Docker en ejecución y claves generadas (generate_keys.sh,
# generate_response_keys.sh, generate_tls_certs.sh).
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

EVIDENCE_DIR="evidence"
mkdir -p "$EVIDENCE_DIR"

# Demos en orden de ejecución: "nombre_del_log|script"
DEMOS=(
  "capa1_procedencia_datos|run_layer1_provenance_demo.sh"
  "capa1_validador_modelos_externos|run_layer1_external_model_demo.sh"
  "capa1_caso_positivo|run_layer1_positive_case.sh"
  "capa1_caso_negativo_append|run_layer1_negative_case.sh"
  "capa1_caso_negativo_swap_signed|run_layer1_swap_signed_case.sh"
  "capa2_demo_8casos|run_layer2_demo.sh"
  "capa2_arranque_sustitucion_firmada|run_layer2_swap_signed_startup.sh"
  "capa3_demo_semilla42|run_layer3_demo.sh"
  "capa3_sensibilidad_6semillas|run_layer3_seeds.sh"
  "capa3_sensibilidad_amplitud_baja|run_layer3_seeds_low_amplitude.sh"
  "capa3_compuerta_promocion|run_layer3_promotion_demo.sh"
  "capa3_compuerta_promocion_6semillas|run_layer3_promotion_seeds.sh"
  "integracion_tres_capas|run_e2e_demo.sh"
)

# --- Procedencia común a todos los logs ---
GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo 'sin-git')"
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  GIT_COMMIT="${GIT_COMMIT} (con cambios sin commitear)"
fi
DOCKER_VERSION="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'desconocida')"
COMPOSE_VERSION="$(docker compose version --short 2>/dev/null || echo 'desconocida')"

write_header() {
  local log_file="$1" script="$2"
  {
    echo "=============================================================="
    echo " EVIDENCIA — prototipo RecoShop"
    echo "=============================================================="
    echo " Demo:            scripts/${script}"
    echo " Fecha (UTC):     $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo " Commit:          ${GIT_COMMIT}"
    echo " Docker Engine:   ${DOCKER_VERSION}"
    echo " Docker Compose:  ${COMPOSE_VERSION}"
    echo " Imágenes:"
    docker image ls --filter "reference=recoshop-prototype-*" \
      --format '   {{.Repository}}  {{.ID}}' 2>/dev/null
    echo "=============================================================="
    echo ""
  } > "$log_file"
}

declare -A RESULTS
OVERALL=0

for entry in "${DEMOS[@]}"; do
  name="${entry%%|*}"
  script="${entry##*|}"
  log_file="${EVIDENCE_DIR}/${name}.log"

  echo ""
  echo ">>> Ejecutando ${script}  →  ${log_file}"
  write_header "$log_file" "$script"

  "./scripts/${script}" 2>&1 | tee -a "$log_file"
  code="${PIPESTATUS[0]}"

  {
    echo ""
    echo "=============================================================="
    echo " CÓDIGO DE SALIDA DEL SCRIPT: ${code}  (0 = comportamiento según contrato)"
    echo "=============================================================="
  } >> "$log_file"

  RESULTS["$name"]=$code
  [ "$code" -ne 0 ] && OVERALL=1
done

# --- Resumen y manifiesto ---
SUMMARY="${EVIDENCE_DIR}/RESUMEN.txt"
{
  echo "Captura de evidencia — $(date -u +%Y-%m-%dT%H:%M:%SZ) — commit ${GIT_COMMIT}"
  echo ""
  for entry in "${DEMOS[@]}"; do
    name="${entry%%|*}"
    if [ "${RESULTS[$name]}" -eq 0 ]; then mark="✅"; else mark="❌"; fi
    printf "%s  %-36s exit %s\n" "$mark" "$name" "${RESULTS[$name]}"
  done
} > "$SUMMARY"

( cd "$EVIDENCE_DIR" && sha256sum ./*.log > MANIFEST.sha256 )

echo ""
echo "=============================================================="
cat "$SUMMARY"
echo ""
echo "Manifiesto de integridad: ${EVIDENCE_DIR}/MANIFEST.sha256"
echo "=============================================================="
exit "$OVERALL"
