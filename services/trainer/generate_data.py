"""
generate_data.py
================
Genera un dataset SINTÉTICO y REPRODUCIBLE de interacciones usuario-producto
para RecoShop, organizado en sesiones (grupos de consulta) con productos
candidatos y un grado de relevancia (0-3). Es apto para entrenar un modelo
de ranking (LGBMRanker), equivalente al "modelo de ranking (LightGBM)"
descrito en la sección 3.1 de la tesis (fine-tuning sobre embeddings +
LightGBM para producir el ranking final de RecoShop).

Este script NO usa datos reales de ningún sistema de e-commerce: todos los
valores se generan con una semilla aleatoria fija (por defecto 42) para que
el experimento sea reproducible entre ejecuciones, y para que el caso
positivo y el caso negativo del prototipo partan siempre del mismo modelo
"legítimo" antes de que el caso negativo lo manipule.
"""

import numpy as np
import pandas as pd

RANDOM_SEED = 42
N_SESSIONS = 300
MIN_CANDIDATES_PER_SESSION = 6
MAX_CANDIDATES_PER_SESSION = 20
N_CATEGORIES = 8


def generate_recoshop_dataset(seed: int = RANDOM_SEED) -> pd.DataFrame:
    """
    Genera un DataFrame con una fila por par (sesión, producto candidato).

    Columnas:
      - session_id: identificador de la sesión de compra (equivale al "query
        group" del ranking; NDCG y MAP se calculan por sesión).
      - product_id: identificador del producto candidato dentro de la sesión.
      - category: categoría del producto (entero codificado 0..N_CATEGORIES-1).
      - price: precio del producto (distribución log-normal, valores positivos).
      - user_purchase_history: compras previas del usuario en esa categoría
        (proxy de afinidad histórica -- equivalente a una feature del
        Feature Store / Feast en la arquitectura real de RecoShop).
      - product_popularity: popularidad agregada del producto (0-1).
      - discount_pct: descuento activo sobre el producto (0-1).
      - is_weekend: 1 si la sesión ocurre en fin de semana, 0 en otro caso.
      - relevance: grado de relevancia observado (0=no clic, 1=clic,
        2=agregado al carrito, 3=compra). Es la variable objetivo del
        ranking (equivalente al label real que alimentaría el
        fine-tuning del modelo en producción).
    """
    rng = np.random.default_rng(seed)

    rows = []
    for session_id in range(N_SESSIONS):
        n_candidates = int(rng.integers(MIN_CANDIDATES_PER_SESSION, MAX_CANDIDATES_PER_SESSION + 1))
        is_weekend = int(rng.random() < 0.28)

        categories = rng.integers(0, N_CATEGORIES, size=n_candidates)
        prices = np.round(rng.lognormal(mean=3.2, sigma=0.6, size=n_candidates), 2)
        purchase_history = rng.poisson(lam=1.5, size=n_candidates)
        popularity = rng.beta(2, 5, size=n_candidates)
        discount = rng.choice(
            [0.0, 0.05, 0.10, 0.15, 0.20],
            size=n_candidates,
            p=[0.55, 0.15, 0.15, 0.10, 0.05],
        )

        # Señal "verdadera" de relevancia: combinación de afinidad histórica,
        # popularidad y descuento, con ruido -- nunca perfecta, como en un
        # sistema real de recomendación.
        max_history = purchase_history.max() if purchase_history.max() > 0 else 1
        affinity_signal = (
            0.45 * (purchase_history / max_history)
            + 0.35 * popularity
            + 0.20 * discount
        )
        noise = rng.normal(0, 0.12, size=n_candidates)
        score = affinity_signal + noise

        # Convertir el score continuo en grados discretos de relevancia (0-3)
        # usando cuantiles internos a la sesión, para que cada sesión tenga
        # una distribución de relevancia razonable (no todo "no-clic").
        quantiles = np.quantile(score, [0.55, 0.80, 0.95])
        relevance = np.digitize(score, quantiles)  # produce valores enteros 0..3

        for i in range(n_candidates):
            rows.append(
                {
                    "session_id": session_id,
                    "product_id": f"S{session_id:04d}-P{i:03d}",
                    "category": int(categories[i]),
                    "price": float(prices[i]),
                    "user_purchase_history": int(purchase_history[i]),
                    "product_popularity": float(round(popularity[i], 4)),
                    "discount_pct": float(discount[i]),
                    "is_weekend": is_weekend,
                    "relevance": int(relevance[i]),
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = generate_recoshop_dataset()
    print(f"[generate_data] Dataset sintético generado: {len(df)} filas, "
          f"{df['session_id'].nunique()} sesiones.")
    print(df.head(10).to_string(index=False))
    df.to_csv("/tmp/recoshop_synthetic.csv", index=False)
    print("[generate_data] Guardado en /tmp/recoshop_synthetic.csv")
