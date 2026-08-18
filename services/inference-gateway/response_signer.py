"""
response_signer.py
===================
Instancia el Sub-componente Response Signer de P-01 (firma digital de la
respuesta de inferencia, mitigación de D-05: integridad de la respuesta
frente a manipulación en tránsito -- por ejemplo, un actor con posición de
red dentro del clúster que altere el ranking después de que el modelo
respondió, sin que el consumidor lo note; ver Escenario A3 de A4.2).

Relación con la tesis: Patrón P-01 — Secure Inference Gateway,
Sub-componente 3 (Protector del Canal / Response Signer). Mitigación de
D-05 documentada en A4.4 §3.1 / §4.1.

Usa un par de claves Ed25519 generado localmente para el prototipo (ver
scripts/generate_response_keys.sh), separado del par de claves cosign de
la Capa 1 (que firma ARTEFACTOS DE MODELO en el Model Registry, no
respuestas de inferencia en tiempo real).
"""

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ResponseSigner:
    def __init__(self, private_key_path: str):
        with open(private_key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)

        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(
                f"La clave en {private_key_path} no es una clave privada Ed25519."
            )

        self._private_key: Ed25519PrivateKey = key

    def sign_payload(self, payload: dict) -> dict:
        """
        Serializa `payload` en JSON canónico (claves ordenadas, sin
        espacios) para asegurar que firmante y verificador calculen la
        firma sobre exactamente los mismos bytes, firma con Ed25519, y
        retorna el sobre {"payload": ..., "signature": ..., "signature_alg": ...}.
        """
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = self._private_key.sign(canonical_bytes)
        return {
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
            "signature_alg": "Ed25519",
        }
