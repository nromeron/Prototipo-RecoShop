"""
input_validator.py
===================
Instancia el Sub-componente Input Validator de P-01 (validación estructural
y de rangos previa a la inferencia, mitigación de D-04).

Relación con la tesis: Patrón P-01 — Secure Inference Gateway,
Sub-componente 1 (Validador de Entrada). Corresponde al escenario de
D-04 en la sección 3.2 (input fuera de distribución en /v1/recommend) y a
la mitigación descrita en las secciones 3.4 y 4.3.

Este módulo usa un esquema Pandera declarativo sobre el DataFrame de
candidatos de una sesión. No realiza inferencia ni conoce nada del
modelo: su única responsabilidad es rechazar, con evidencia trazable,
cualquier solicitud que no cumpla el contrato estructural y de rangos
esperado por el modelo.
"""

from typing import List

import numpy as np
import pandas as pd
import pandera as pa
from pandera import Check, Column, DataFrameSchema

MIN_CANDIDATES = 1
MAX_CANDIDATES = 100

REQUIRED_COLUMNS = [
    "category",
    "price",
    "user_purchase_history",
    "product_popularity",
    "discount_pct",
    "is_weekend",
    "product_id",
]

# Esquema estructural y de rangos del Input Validator. `nullable=False`
# hace que Pandera rechace explícitamente NaN en cualquier columna; la
# comprobación adicional de infinitos se hace por separado más abajo,
# porque algunas columnas (p. ej. product_id, con Check.ge(0) sin cota
# superior) no acotan el valor +inf por sí solas.
CANDIDATE_SCHEMA = DataFrameSchema(
    {
        "category": Column(int, Check.in_range(0, 7), nullable=False),
        "price": Column(
            float, Check.in_range(0, 10000, include_min=False, include_max=False), nullable=False
        ),
        "user_purchase_history": Column(int, Check.in_range(0, 1000), nullable=False),
        "product_popularity": Column(float, Check.in_range(0, 1), nullable=False),
        "discount_pct": Column(float, Check.in_range(0, 1), nullable=False),
        "is_weekend": Column(int, Check.isin([0, 1]), nullable=False),
        "product_id": Column(int, Check.ge(0), nullable=False),
    },
    strict=False,
)

# Perfil de referencia de entrenamiento (modo endurecido). Rangos plausibles
# observados en los datos con que se entrena el modelo, más estrechos que los
# rangos admisibles por el dominio. Se aplica, además del esquema anterior,
# solo a los clientes marcados como sospechosos por el registro de sospecha
# compartido (endurecimiento cruzado de P-01).
STRICT_PROFILE_SCHEMA = DataFrameSchema(
    {
        "price": Column(float, Check.in_range(0, 500, include_min=False), nullable=False),
        "user_purchase_history": Column(int, Check.in_range(0, 20), nullable=False),
        "discount_pct": Column(float, Check.in_range(0, 0.5), nullable=False),
    },
    strict=False,
)


class InputValidationError(Exception):
    """Se lanza cuando la solicitud no supera el Input Validator de P-01."""

    def __init__(self, details: List[str]):
        self.details = details
        super().__init__("Validación de entrada fallida (Input Validator, P-01 / D-04)")


def validate_candidates(candidates: List[dict], strict: bool = False) -> pd.DataFrame:
    """
    Valida la lista de candidatos de una sesión contra el contrato
    estructural y de rangos de P-01. Retorna el DataFrame validado si todo
    es correcto, o lanza InputValidationError con el detalle de cada
    violación encontrada.
    """
    details: List[str] = []

    n_candidates = len(candidates)
    if n_candidates < MIN_CANDIDATES or n_candidates > MAX_CANDIDATES:
        details.append(
            f"Se esperaban entre {MIN_CANDIDATES} y {MAX_CANDIDATES} candidatos, "
            f"se recibieron {n_candidates}."
        )
        raise InputValidationError(details)

    df = pd.DataFrame(candidates)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        details.append(f"Faltan columnas requeridas: {missing}")
        raise InputValidationError(details)

    # Chequeo explícito de infinitos: Check.ge(0) sobre product_id, por
    # ejemplo, no rechazaría +inf por sí solo (+inf >= 0 es verdadero).
    numeric_df = df[REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    inf_mask = np.isinf(numeric_df.to_numpy(dtype=float))
    if inf_mask.any():
        details.append("Se detectaron valores infinitos (Inf/-Inf) en los candidatos.")
        raise InputValidationError(details)

    try:
        validated = CANDIDATE_SCHEMA.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        for _, row in exc.failure_cases.iterrows():
            details.append(f"{row['column']}: {row['check']} (valor={row['failure_case']})")
        raise InputValidationError(details) from exc

    # Modo endurecido: el cliente ya fue marcado como sospechoso, así que
    # además se exige el perfil de referencia de entrenamiento.
    if strict:
        try:
            STRICT_PROFILE_SCHEMA.validate(validated, lazy=True)
        except pa.errors.SchemaErrors as exc:
            for _, row in exc.failure_cases.iterrows():
                details.append(
                    f"{row['column']}: {row['check']} [perfil de referencia] (valor={row['failure_case']})"
                )
            raise InputValidationError(details) from exc

    return validated
