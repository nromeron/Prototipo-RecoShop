"""
tasas_monitor_semillas.py — tasas de veredicto de la Capa 3 (feedback-gate) sobre muchas semillas.

Uso (dentro del contenedor feedback-gate, que fija las versiones de numpy, pandas y scipy):
    python tasas_monitor_semillas.py <carpeta> <salida.csv> <semillas>
  <carpeta>  carpeta donde están feedback_gate.py y generate_feedback.py
  <semillas> intervalo inclusivo "0-499" o lista "7,13,42,101,777,2026"
Ejemplo:
    python tasas_monitor_semillas.py /src /analisis/tasas_500_semillas_antes.csv 0-499

No modifica el repositorio: importa generate_feedback.py y feedback_gate.py tal como están y
repite, para cada semilla y cada amplitud de la deriva natural, la misma secuencia de main()
(línea base, limpio, natural, adversarial). Escribe una fila por lote e imprime las tasas de
veredicto por amplitud y tipo de lote.
"""
import collections, csv, importlib.util, os, sys, tempfile
import numpy as np
carpeta, salida, semillas = sys.argv[1], sys.argv[2], sys.argv[3]
if "-" in semillas:
    lo, hi = (int(s) for s in semillas.split("-")); semillas = list(range(lo, hi + 1))
else:
    semillas = [int(s) for s in semillas.split(",")]
AMPLITUDES = {"calibrada": (0.09, 0.06), "baja": (0.05, 0.03)}  # (precio, popularidad)
VEREDICTOS = {0: "aceptado", 3: "alerta", 4: "cuarentena"}
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
os.environ["FEEDBACK_DATA_DIR"] = tempfile.mkdtemp()
fg = load("fg", os.path.join(carpeta, "feedback_gate.py"))
gen = load("gen", os.path.join(carpeta, "generate_feedback.py"))
COLUMNAS = ["semilla", "amplitud", "lote", "veredicto", "ks_marcadas", "concentracion_categoria",
            "chi2_estadistico", "chi2_p", "concentracion_temporal", "delta_etiquetas"]
conteo = collections.defaultdict(collections.Counter)
with open(salida, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNAS); w.writeheader()
    for amplitud, (precio, popularidad) in AMPLITUDES.items():
        # generate_batch_natural_drift lee la amplitud de las globales del módulo al llamarse
        gen.NATURAL_DRIFT_PRICE_PCT = precio; gen.NATURAL_DRIFT_POPULARITY_DELTA = popularidad
        for seed in semillas:
            rng = np.random.default_rng(seed)
            base = gen.generate_baseline(rng)
            lotes = {"limpio": gen.generate_batch_clean(rng, 5000),
                     "natural": gen.generate_batch_natural_drift(rng, 6000),
                     "adversarial": gen.generate_batch_adversarial(rng, 7000)}
            for lote, df in lotes.items():
                g = fg.guardian_ks_global(base, df); cc = fg.monitor_concentration_index_category(base, df)
                ct = fg.monitor_concentration_index_temporal(df); ls = fg.monitor_label_manipulation_signal(base, df)
                d = fg.decide(g, cc, ct, ls); conteo[(amplitud, lote)][d["exit_code"]] += 1
                w.writerow({"semilla": seed, "amplitud": amplitud, "lote": lote, "veredicto": d["exit_code"],
                            "ks_marcadas": "|".join(k for k, v in g["per_feature"].items() if v["flagged"]),
                            "concentracion_categoria": round(cc["concentration"], 6),
                            "chi2_estadistico": "" if cc.get("chi2_statistic") is None else round(cc["chi2_statistic"], 6),
                            "chi2_p": "" if cc.get("chi2_p_value") is None else f"{cc['chi2_p_value']:.6g}",
                            "concentracion_temporal": round(ct["concentration"], 6),
                            "delta_etiquetas": round(ls["max_delta"], 6)})
n = len(semillas)
print(f"{n} semillas ({semillas[0]}…{semillas[-1]}) · CSV: {salida}")
for (amplitud, lote), c in conteo.items():
    tasas = " · ".join(f"{VEREDICTOS[k]} {100 * v / n:.1f} %" for k, v in sorted(c.items()))
    print(f"  {amplitud:9s} {lote:11s} {tasas}")
