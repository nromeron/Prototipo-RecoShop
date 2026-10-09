"""
output_controller.py
=====================
Instancia el Sub-componente Output Controller de P-01. Tiene dos
responsabilidades sobre la respuesta de inferencia:

  (a) Output Information Limiting (P-01, candidato A3): la respuesta
      expone únicamente product_id y rank de los primeros TOP_K
      candidatos -- nunca los scores crudos del modelo -- mitigando la
      extracción de modelo por consulta sistemática descrita en el
      Escenario A2 de A4.2 (debilidad D-02).
  (b) Rate limiting: control general de seguridad de API en
      microservicios (NIST SP 800-204), aplicado aquí como un token
      bucket en memoria por client_id.

Relación con la tesis: Patrón P-01 — Secure Inference Gateway,
Sub-componente 2 (Controlador de Información de Salida). Mitigación de
D-02 documentada en A4.4 §3.1 / §4.1.

NOTA DE ALCANCE: el estado del rate limiter vive en memoria del proceso
(un diccionario Python por client_id), lo cual es una simplificación
deliberada de prototipo. Un despliegue de producción con múltiples
réplicas del gateway requeriría un almacén compartido (p. ej. Redis) o
un componente dedicado de API gateway (p. ej. Envoy/Istio, Kong), no
estado local por proceso como se hace aquí.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Sequence


class RateLimitExceeded(Exception):
    """Se lanza cuando un client_id excede el límite de solicitudes/minuto."""


@dataclass
class _TokenBucket:
    capacity: float
    tokens: float
    last_refill: float


class OutputController:
    def __init__(self, top_k: int = 5, rate_limit_per_minute: int = 30):
        self.top_k = top_k
        self.rate_limit_per_minute = rate_limit_per_minute
        self._refill_rate_per_second = rate_limit_per_minute / 60.0
        self._buckets: Dict[str, _TokenBucket] = {}

    def check_rate_limit(self, client_id: str) -> None:
        """
        Token bucket en memoria por client_id (control general de
        seguridad de API en microservicios, NIST SP 800-204). Cada
        client_id tiene una cubeta con capacidad `rate_limit_per_minute`
        que se recarga continuamente a razón de rate_limit_per_minute
        tokens por minuto. Lanza RateLimitExceeded si no queda al menos
        un token disponible.
        """
        now = time.monotonic()
        bucket = self._buckets.get(client_id)
        if bucket is None:
            bucket = _TokenBucket(
                capacity=float(self.rate_limit_per_minute),
                tokens=float(self.rate_limit_per_minute),
                last_refill=now,
            )
            self._buckets[client_id] = bucket

        elapsed = now - bucket.last_refill
        bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * self._refill_rate_per_second)
        bucket.last_refill = now

        if bucket.tokens < 1.0:
            raise RateLimitExceeded(
                f"client_id={client_id} excedió el límite de "
                f"{self.rate_limit_per_minute} solicitudes/minuto."
            )

        bucket.tokens -= 1.0

    def build_response(self, product_ids: Sequence[int], scores: Sequence[float], top_k: int = None) -> List[dict]:
        """
        Ordena los candidatos por score descendente y retorna únicamente
        product_id y rank para los primeros self.top_k -- los scores
        crudos del modelo NUNCA se incluyen en la respuesta (Output
        Information Limiting, P-01 candidato A3, mitigación de D-02).
        """
        order = sorted(range(len(product_ids)), key=lambda i: scores[i], reverse=True)
        # top_k explícito: lo usa la pasarela para reducir la información
        # entregada a un cliente marcado como sospechoso.
        top_indices = order[: (top_k if top_k is not None else self.top_k)]
        return [
            {"product_id": product_ids[i], "rank": rank}
            for rank, i in enumerate(top_indices, start=1)
        ]
