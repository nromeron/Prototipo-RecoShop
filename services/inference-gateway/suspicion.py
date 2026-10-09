"""
suspicion.py
=============
Registro de sospecha por cliente compartido por los sub-componentes de P-01.
Materializa el endurecimiento cruzado del patrón: lo que un sub-componente
observa sobre un cliente modifica el comportamiento de los otros.

  - El Controlador de Información de Salida y el Validador de Entrada
    REGISTRAN eventos sospechosos (exceso de la tasa de solicitudes,
    entradas rechazadas).
  - Cuando la puntuación de un cliente supera el umbral, el Validador aplica
    el perfil de referencia de entrenamiento (rangos más estrechos) y el
    Controlador reduce el número de recomendaciones devueltas.

La puntuación por cliente que modula la respuesta sigue la idea de la
puntuación de sospecha por consulta de RADEP (Chakraborty et al., 2025) y de
la respuesta adaptativa de AMAO (Jiang et al., 2024), aplicada aquí a nivel
de pasarela y compartida entre sub-componentes.

La puntuación decae con el tiempo (vida media configurable), de modo que un
cliente legítimo que cometió errores aislados recupera el modo normal.

NOTA DE ALCANCE: el estado vive en memoria del proceso, igual que el
limitador de tasa. Con varias réplicas de la pasarela se necesitaría un
almacén compartido (por ejemplo, Redis).
"""

import time
from typing import Dict, Tuple

# Peso de cada evento en la puntuación (la puntuación se acota a 1.0).
# Con el umbral por defecto (0.5), un rechazo aislado no endurece la
# pasarela; dos rechazos cercanos en el tiempo, o un solo exceso de la tasa
# de solicitudes, sí.
EVENT_WEIGHTS = {
    "validation_failure": 0.3,  # entrada rechazada por el Validador de Entrada
    "rate_limit": 0.6,          # exceso de la tasa de solicitudes
}


class SuspicionRegistry:
    def __init__(self, threshold: float = 0.5, half_life_seconds: float = 600.0):
        self.threshold = threshold
        self.half_life_seconds = half_life_seconds
        self._state: Dict[str, Tuple[float, float]] = {}  # client_id -> (puntuación, instante)

    def _decayed(self, client_id: str, now: float) -> float:
        score, last = self._state.get(client_id, (0.0, now))
        if self.half_life_seconds <= 0:
            return score
        return score * 0.5 ** ((now - last) / self.half_life_seconds)

    def record(self, client_id: str, event: str) -> float:
        """Registra un evento sospechoso y retorna la puntuación actualizada."""
        now = time.monotonic()
        score = min(1.0, self._decayed(client_id, now) + EVENT_WEIGHTS[event])
        self._state[client_id] = (score, now)
        return score

    def score(self, client_id: str) -> float:
        return self._decayed(client_id, time.monotonic())

    def is_suspicious(self, client_id: str) -> bool:
        return self.score(client_id) >= self.threshold
