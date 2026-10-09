"""
generate_feedback.py
=====================
Genera el baseline y los tres lotes de feedback sintético usados por
feedback_gate.py para demostrar el patrón P-02 (Secure Retraining Gate)
sobre la debilidad D-03 (Canal de Retroalimentación No Validado).

IMPORTANTE: este módulo NO importa services/trainer/generate_data.py.
Replica deliberadamente sus mismos parámetros de distribución (misma
semilla, mismas 6 features: category, price, user_purchase_history,
product_popularity, discount_pct, is_weekend) para que el baseline de
esta capa sea estadísticamente consistente con los datos de
entrenamiento de la Capa 1, pero la lógica está copiada, no compartida
como código -- cada capa es independiente y auto-contenida.

ADAPTACIÓN DECLARADA: generate_data.py agrupa productos en sesiones y
calcula `relevance` por cuantiles INTRA-sesión (cada sesión tiene su
propio ranking relativo). Aquí no hay noción de sesión de ranking: cada
fila es un evento de feedback independiente (un clic/compra sobre un
producto), por lo que `relevance` se calcula por cuantiles GLOBALES sobre
el lote completo. Esto es una adaptación explícita al dominio de esta
capa (validación de lotes de feedback), no un intento de réplica exacta
fila a fila del generador de la Capa 1.

Columnas generadas (todas las tablas):
  - category, price, user_purchase_history, product_popularity,
    discount_pct, is_weekend, relevance: las mismas 6 features + relevance
    de la Capa 1.
  - time_window: entero 0-9, representa en qué ventana temporal de
    ingesta llegó el evento de feedback (usado por el Monitor de Drift de
    Seguridad para la concentración temporal).
  - product_id: identificador de producto, usado por el escenario
    adversarial para inflar la relevancia de un conjunto pequeño de
    productos objetivo.

Escenarios generados (relación con los escenarios de explotación de D-03
documentados en A4.2):

  - baseline.csv (5000 filas): distribución de referencia contra la que
    se comparan todos los lotes.
  - batch_clean.csv (1000 filas): misma distribución que el baseline; se
    espera que el Guardian de Ingesta lo acepte sin alertas.
  - batch_natural_drift.csv (1000 filas): TODAS las categorías sufren un
    desplazamiento pequeño y gradual (price +9%, product_popularity
    +0.06, creciente suavemente con time_window). Representa un cambio
    de comportamiento legítimo y difuso (p. ej. estacionalidad), no el
    ataque de D-03; se espera ACEPTADO_CON_ALERTA.
  - batch_adversarial.csv (1000 filas): el 80% es idéntico al lote
    limpio; el 20% restante se concentra en UNA categoría y DOS ventanas
    temporales contiguas, con relevance inflada a 3 para un conjunto
    pequeño de product_id objetivo y product_popularity desplazada
    fuerte (+0.4) solo ahí. Representa el escenario de explotación de
    D-03 de A4.2: un vendedor (o una red de bots a su servicio) genera
    clics/compras falsas concentradas en sus propios productos durante
    una ventana de tiempo corta, para sesgar el próximo ciclo de
    reentrenamiento. Se espera CUARENTENA.
"""

import os

import numpy as np
import pandas as pd

RANDOM_SEED = int(os.environ.get("RANDOM_SEED", "42"))
# Amplitud de la deriva natural (calibrada en +9 % y +0,06). Configurable para
# documentar la frontera del detector (run_layer3_seeds_low_amplitude.sh).
NATURAL_DRIFT_PRICE_PCT = float(os.environ.get("NATURAL_DRIFT_PRICE_PCT", "0.09"))
NATURAL_DRIFT_POPULARITY_DELTA = float(os.environ.get("NATURAL_DRIFT_POPULARITY_DELTA", "0.06"))
N_CATEGORIES = 8
N_TIME_WINDOWS = 10  # ventanas 0..9

BASELINE_ROWS = 5000
BATCH_ROWS = 1000

DATA_DIR = os.environ.get("FEEDBACK_DATA_DIR", "/app/data")

# Parámetros del escenario adversarial: una única categoría atacada y dos
# ventanas temporales contiguas, consistentes con "concentración en un
# segmento y una ventana temporal estrecha" (ver docstring de
# feedback_gate.py, Monitor de Drift de Seguridad, Sub-componente 2).
ADVERSARIAL_FRACTION = 0.20
ADVERSARIAL_TARGET_CATEGORY = 3
ADVERSARIAL_TARGET_WINDOWS = [4, 5]
ADVERSARIAL_TARGET_PRODUCT_FRACTION = 0.20  # sobre el subconjunto adversarial


def _generate_base_records(rng: np.random.Generator, n_rows: int) -> pd.DataFrame:
    """
    Genera las 6 features + relevance replicando los parámetros de
    distribución de services/trainer/generate_data.py (sin importarlo,
    ver nota de adaptación en el docstring del módulo).
    """
    categories = rng.integers(0, N_CATEGORIES, size=n_rows)
    prices = np.round(rng.lognormal(mean=3.2, sigma=0.6, size=n_rows), 2)
    purchase_history = rng.poisson(lam=1.5, size=n_rows)
    popularity = rng.beta(2, 5, size=n_rows)
    discount = rng.choice(
        [0.0, 0.05, 0.10, 0.15, 0.20],
        size=n_rows,
        p=[0.55, 0.15, 0.15, 0.10, 0.05],
    )
    is_weekend = rng.integers(0, 2, size=n_rows)

    max_history = purchase_history.max() if purchase_history.max() > 0 else 1
    affinity_signal = (
        0.45 * (purchase_history / max_history)
        + 0.35 * popularity
        + 0.20 * discount
    )
    noise = rng.normal(0, 0.12, size=n_rows)
    score = affinity_signal + noise

    # Cuantiles GLOBALES sobre el lote (no intra-sesión, ver adaptación
    # declarada en el docstring del módulo).
    quantiles = np.quantile(score, [0.55, 0.80, 0.95])
    relevance = np.digitize(score, quantiles)

    return pd.DataFrame(
        {
            "category": categories.astype(int),
            "price": prices.astype(float),
            "user_purchase_history": purchase_history.astype(int),
            "product_popularity": popularity.astype(float),
            "discount_pct": discount.astype(float),
            "is_weekend": is_weekend.astype(int),
            "relevance": relevance.astype(int),
        }
    )


def generate_baseline(rng: np.random.Generator) -> pd.DataFrame:
    df = _generate_base_records(rng, BASELINE_ROWS)
    df["time_window"] = rng.integers(0, N_TIME_WINDOWS, size=BASELINE_ROWS)
    df["product_id"] = np.arange(BASELINE_ROWS)
    return df


def generate_batch_clean(rng: np.random.Generator, product_id_offset: int) -> pd.DataFrame:
    df = _generate_base_records(rng, BATCH_ROWS)
    df["time_window"] = rng.integers(0, N_TIME_WINDOWS, size=BATCH_ROWS)
    df["product_id"] = np.arange(product_id_offset, product_id_offset + BATCH_ROWS)
    return df


def generate_batch_natural_drift(rng: np.random.Generator, product_id_offset: int) -> pd.DataFrame:
    """
    Drift NATURAL (difuso): todas las categorías se desplazan por igual,
    de forma pequeña y creciente con time_window. No hay concentración en
    ningún segmento ni ventana temporal específica -- esta es precisamente
    la señal que el Monitor de Drift de Seguridad (Sub-componente 2) debe
    distinguir de un patrón adversarial.
    """
    df = _generate_base_records(rng, BATCH_ROWS)
    time_window = rng.integers(0, N_TIME_WINDOWS, size=BATCH_ROWS)
    df["time_window"] = time_window

    # Factor de crecimiento suave 0.0 (time_window=0) .. 1.0 (time_window=9),
    # aplicado UNIFORMEMENTE a todas las categorías (drift difuso).
    growth_factor = time_window / (N_TIME_WINDOWS - 1)
    df["price"] = df["price"] * (1.0 + NATURAL_DRIFT_PRICE_PCT * growth_factor)
    df["product_popularity"] = np.clip(
        df["product_popularity"] + NATURAL_DRIFT_POPULARITY_DELTA * growth_factor, 0.0, 1.0
    )

    df["product_id"] = np.arange(product_id_offset, product_id_offset + BATCH_ROWS)
    return df


def generate_batch_adversarial(rng: np.random.Generator, product_id_offset: int) -> pd.DataFrame:
    """
    Drift ADVERSARIAL (concentrado): el 80% del lote es indistinguible del
    lote limpio. El 20% restante se fuerza a UNA categoría y DOS ventanas
    temporales contiguas (concentración de segmento y tiempo), y dentro de
    ese 20%, un subconjunto pequeño de product_id recibe relevance=3 y un
    salto fuerte de product_popularity -- la señal de "manipulación de
    etiquetas" que el Monitor de Drift de Seguridad busca explícitamente,
    distinta de la concentración de segmento/tiempo por sí sola.
    """
    df = _generate_base_records(rng, BATCH_ROWS)
    df["time_window"] = rng.integers(0, N_TIME_WINDOWS, size=BATCH_ROWS)
    df["product_id"] = np.arange(product_id_offset, product_id_offset + BATCH_ROWS)

    n_adversarial = int(ADVERSARIAL_FRACTION * BATCH_ROWS)
    adversarial_idx = rng.choice(BATCH_ROWS, size=n_adversarial, replace=False)

    # Concentración de segmento y tiempo: el subconjunto adversarial
    # completo se reasigna a una única categoría y a dos ventanas
    # temporales contiguas.
    df.loc[adversarial_idx, "category"] = ADVERSARIAL_TARGET_CATEGORY
    df.loc[adversarial_idx, "time_window"] = rng.choice(
        ADVERSARIAL_TARGET_WINDOWS, size=n_adversarial
    )

    # Manipulación de etiquetas: solo un subconjunto pequeño DENTRO del
    # subconjunto adversarial recibe la inflación de relevance/popularity
    # (un atacante realista no infla el 100% del tráfico concentrado, solo
    # los productos que quiere beneficiar).
    n_target_products = max(1, int(ADVERSARIAL_TARGET_PRODUCT_FRACTION * n_adversarial))
    target_idx = rng.choice(adversarial_idx, size=n_target_products, replace=False)

    df.loc[target_idx, "relevance"] = 3
    df.loc[target_idx, "product_popularity"] = np.clip(
        df.loc[target_idx, "product_popularity"] + 0.4, 0.0, 1.0
    )

    return df


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "quarantine"), exist_ok=True)

    rng = np.random.default_rng(RANDOM_SEED)

    baseline = generate_baseline(rng)
    baseline_path = os.path.join(DATA_DIR, "baseline.csv")
    baseline.to_csv(baseline_path, index=False)
    print(f"[generate_feedback] baseline.csv generado: {len(baseline)} filas -> {baseline_path}")

    batch_clean = generate_batch_clean(rng, product_id_offset=BASELINE_ROWS)
    clean_path = os.path.join(DATA_DIR, "batch_clean.csv")
    batch_clean.to_csv(clean_path, index=False)
    print(f"[generate_feedback] batch_clean.csv generado: {len(batch_clean)} filas -> {clean_path}")

    batch_natural = generate_batch_natural_drift(rng, product_id_offset=BASELINE_ROWS + BATCH_ROWS)
    natural_path = os.path.join(DATA_DIR, "batch_natural_drift.csv")
    batch_natural.to_csv(natural_path, index=False)
    print(f"[generate_feedback] batch_natural_drift.csv generado: {len(batch_natural)} filas -> {natural_path}")

    batch_adversarial = generate_batch_adversarial(rng, product_id_offset=BASELINE_ROWS + 2 * BATCH_ROWS)
    adversarial_path = os.path.join(DATA_DIR, "batch_adversarial.csv")
    batch_adversarial.to_csv(adversarial_path, index=False)
    print(
        f"[generate_feedback] batch_adversarial.csv generado: {len(batch_adversarial)} filas -> {adversarial_path}"
    )

    print("[generate_feedback] Generación completa (semilla fija: reproducible entre ejecuciones).")


if __name__ == "__main__":
    main()
