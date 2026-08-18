"""
client_demo.py
===============
Cliente verificador de referencia para la Capa 2 (P-01 Secure Inference
Gateway). Ejecuta cuatro casos de demostración contra el endpoint
POST /v1/recommend, verificando en cada uno el comportamiento esperado de
los tres sub-componentes de P-01:

  - valid              : solicitud bien formada -> 200, firma Ed25519
                          válida, payload sin scores crudos (solo
                          product_id/rank). Mitigación de D-02 y D-05.
  - invalid-input       : candidatos fuera de rango / NaN -> 422
                          (Input Validator, mitigación de D-04).
  - rate-limit          : ráfaga de solicitudes -> al menos un 429
                          (Output Controller, rate limiting).
  - tampered-response   : se altera un byte del payload firmado ANTES de
                          verificar -> la verificación Ed25519 debe
                          FALLAR (simulación de manipulación en tránsito,
                          mitigación de D-05).

Relación con la tesis: Patrón P-01 — Secure Inference Gateway, A4.4 §3.1 /
§4.1. Cada caso imprime "[client] CASO <nombre>: OK/FALLO" y sale con
código 0 (OK) o 1 (FALLO).
"""

import argparse
import base64
import json
import os
import sys

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://inference-gateway:8080")
RESPONSE_PUB_KEY_PATH = os.environ.get("RESPONSE_PUB_KEY_PATH", "/keys/response_ed25519.pub")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))


def _load_public_key() -> Ed25519PublicKey:
    with open(RESPONSE_PUB_KEY_PATH, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def _verify_signature(body: dict, public_key: Ed25519PublicKey) -> bool:
    """
    Reconstruye el JSON canónico del payload firmado y verifica la firma
    Ed25519 con la clave pública del Response Signer. Retorna False tanto
    si la firma no coincide como si el cuerpo no tiene la forma esperada.
    """
    try:
        payload = body["payload"]
        signature = base64.b64decode(body["signature"])
    except (KeyError, TypeError, ValueError):
        return False

    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        public_key.verify(signature, canonical_bytes)
        return True
    except InvalidSignature:
        return False


def _sample_session():
    return [
        {
            "category": i % 8,
            "price": 20.0 + i,
            "user_purchase_history": i,
            "product_popularity": 0.1 * (i % 10),
            "discount_pct": 0.05,
            "is_weekend": 0,
            "product_id": i,
        }
        for i in range(10)
    ]


def case_valid() -> bool:
    public_key = _load_public_key()
    payload = {"client_id": "demo-client-valid", "session": _sample_session()}
    resp = requests.post(f"{GATEWAY_URL}/v1/recommend", json=payload, timeout=10)

    if resp.status_code != 200:
        print(f"[client] esperaba 200, recibí {resp.status_code}: {resp.text}")
        return False

    body = resp.json()

    if not _verify_signature(body, public_key):
        print("[client] la firma Ed25519 de una respuesta válida NO verificó correctamente.")
        return False

    recommendations = body.get("payload", {}).get("recommendations", [])
    if not recommendations:
        print("[client] la respuesta válida no contiene recomendaciones.")
        return False

    for item in recommendations:
        if set(item.keys()) - {"product_id", "rank"}:
            print(f"[client] la respuesta expone campos no permitidos (posible fuga de scores): {item}")
            return False

    print(
        f"[client] respuesta válida, firma verificada, {len(recommendations)} "
        "recomendaciones sin scores crudos (D-02 / D-05 mitigadas)."
    )
    return True


def case_invalid_input() -> bool:
    session = _sample_session()
    session[0]["price"] = -50           # fuera de rango (0, 10000), mitigación de D-04
    session[1]["product_popularity"] = 9.9  # fuera de rango [0, 1], mitigación de D-04

    payload = {"client_id": "demo-client-invalid", "session": session}
    resp = requests.post(f"{GATEWAY_URL}/v1/recommend", json=payload, timeout=10)

    if resp.status_code != 422:
        print(f"[client] esperaba 422, recibí {resp.status_code}: {resp.text}")
        return False

    print(f"[client] entrada inválida correctamente rechazada con 422: {resp.json()}")
    return True


def case_rate_limit() -> bool:
    client_id = "demo-client-rate-limit"
    payload = {"client_id": client_id, "session": _sample_session()}

    n_requests = RATE_LIMIT_PER_MINUTE + 5
    saw_429 = False
    for _ in range(n_requests):
        resp = requests.post(f"{GATEWAY_URL}/v1/recommend", json=payload, timeout=10)
        if resp.status_code == 429:
            saw_429 = True
            break

    if not saw_429:
        print(f"[client] tras {n_requests} solicitudes en ráfaga, nunca se recibió 429.")
        return False

    print(f"[client] rate limiting activado correctamente (429 recibido dentro de {n_requests} solicitudes).")
    return True


def case_tampered_response() -> bool:
    public_key = _load_public_key()
    payload = {"client_id": "demo-client-tampered", "session": _sample_session()}
    resp = requests.post(f"{GATEWAY_URL}/v1/recommend", json=payload, timeout=10)

    if resp.status_code != 200:
        print(f"[client] esperaba 200 antes de manipular la respuesta, recibí {resp.status_code}.")
        return False

    body = resp.json()

    # Simulación de manipulación en tránsito (D-05): se altera un producto
    # dentro del payload YA FIRMADO, sin volver a firmar (el atacante no
    # posee la clave privada del Response Signer).
    recommendations = body.get("payload", {}).get("recommendations", [])
    if not recommendations:
        print("[client] no hay recomendaciones que manipular en la respuesta.")
        return False

    recommendations[0]["product_id"] += 999000

    if _verify_signature(body, public_key):
        print("[client] la verificación Ed25519 aceptó un payload manipulado (no debería).")
        return False

    print("[client] la manipulación del payload fue detectada correctamente (firma inválida, D-05 mitigada).")
    return True


CASES = {
    "valid": case_valid,
    "invalid-input": case_invalid_input,
    "rate-limit": case_rate_limit,
    "tampered-response": case_tampered_response,
}


def main():
    parser = argparse.ArgumentParser(description="Cliente verificador de la Capa 2 (P-01)")
    parser.add_argument("--case", required=True, choices=list(CASES.keys()))
    args = parser.parse_args()

    case_fn = CASES[args.case]
    try:
        ok = case_fn()
    except Exception as exc:  # noqa: BLE001 - script de demostración
        print(f"[client] ERROR inesperado ejecutando el caso '{args.case}': {exc}")
        ok = False

    print(f"[client] CASO {args.case}: {'OK' if ok else 'FALLO'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
