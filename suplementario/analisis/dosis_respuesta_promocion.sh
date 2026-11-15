#!/usr/bin/env bash
# =============================================================================
# dosis_respuesta_promocion.sh — dosis-respuesta de la Compuerta de Promoción
# =============================================================================
# Ejecuta promotion_gate.py (servicio trainer) con retroalimentación envenenada
# en las fracciones 0,1 a 0,6 y con retroalimentación limpia, cada una con las
# semillas de retroalimentación 3000 a 3019, sin señal del Monitor. No cambia
# código: promotion_gate.py lee POISON_SESSION_FRACTION y FEEDBACK_SEED del
# entorno. Escribe una fila por ejecución (fracción, semilla, veredicto, delta
# global de NDCG@10, delta de exactitud por pares de la categoría 3) e imprime
# el resumen por fracción.
#
# Uso (desde la raíz del repositorio): ./suplementario/analisis/dosis_respuesta_promocion.sh
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

CSV="$SCRIPT_DIR/dosis_respuesta_promocion.csv"
FRACTIONS=(0.1 0.2 0.3 0.4 0.5 0.6)
SEEDS=$(seq 3000 3019)

# Extrae del registro de auditoría (JSON) el veredicto y los dos deltas.
extract() {
  python3 -I -c '
import json, sys
out = sys.stdin.read()
start = out.index("{", out.index("[promotion-gate] Registro de auditoría:"))
r, _ = json.JSONDecoder().raw_decode(out[start:])
m = r["metrics"]
print(r["exit_code"], m["global_ndcg_at_10"]["delta"], m["pairwise_accuracy_delta_by_category"]["3"], sep=",")
'
}

run() {
  local fraction="$1" seed="$2" feedback="$3" out code row
  out="$(docker compose run --rm --no-deps -e POISON_SESSION_FRACTION="$fraction" -e FEEDBACK_SEED="$seed" \
    trainer python promotion_gate.py --feedback "$feedback" --monitor-signal none 2>&1)"
  code=$?
  if ! row="$(printf '%s' "$out" | extract)"; then
    echo "ERROR: sin registro de auditoría (fracción $fraction, semilla $seed, exit $code)" >&2
    printf '%s\n' "$out" | tail -20 >&2
    exit 2
  fi
  [ "${row%%,*}" = "$code" ] || { echo "ERROR: exit $code distinto del registro ($row)" >&2; exit 2; }
  echo "$4,$seed,$row" >> "$CSV"
  echo "  $4 · semilla $seed · $row"
}

echo "fraccion,semilla,veredicto,delta_global,delta_categoria_3" > "$CSV"
for fraction in "${FRACTIONS[@]}"; do
  echo "Fracción envenenada $fraction"
  for seed in $SEEDS; do run "$fraction" "$seed" poisoned "$fraction"; done
done
echo "Retroalimentación limpia"
# Con --feedback clean, build_feedback() no usa POISON_SESSION_FRACTION.
for seed in $SEEDS; do run 0.6 "$seed" clean limpio; done

python3 -I - "$CSV" <<'EOF'
import csv, statistics, sys
from collections import defaultdict
filas = defaultdict(list)
for f in csv.DictReader(open(sys.argv[1], encoding="utf-8")):
    filas[f["fraccion"]].append(f)
print("\nfracción   retenidas (exit 4)   mediana delta categoría 3")
for fraccion, fs in filas.items():
    retenidas = sum(f["veredicto"] == "4" for f in fs)
    mediana = statistics.median(float(f["delta_categoria_3"]) for f in fs)
    print(f"{fraccion:9s}  {retenidas:2d} de {len(fs)}             {mediana:+.4f}")
EOF
