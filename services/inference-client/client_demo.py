"""
client_demo.py
===============
Cliente verificador de referencia para la Capa 2 (P-01 Secure Inference
Gateway). Ejecuta ocho casos de demostración contra el endpoint
POST /v1/recommend, verificando en cada uno el comportamiento esperado de
los tres sub-componentes de P-01. Todas las conexiones usan autenticación
mutua TLS: cada caso presenta el certificado de su propia identidad.

  - valid              : solicitud bien formada -> 200, firma Ed25519
                          válida, payload sin scores crudos (solo
                          product_id/rank). Mitigación de D-02 y D-05.
  - invalid-input       : candidatos fuera de rango / NaN -> 422
                          (Input Validator, mitigación de D-04).
  - rate-limit          : ráfaga de solicitudes -> al menos un 429
                          (Output Controller, rate limiting).
  - cross-hardening     : endurecimiento cruzado. Un cliente con dos
                          entradas rechazadas pasa a modo endurecido: una
                          solicitud con un precio plausible para el dominio
                          pero fuera del perfil de entrenamiento se rechaza
                          (422) y una solicitud normal recibe menos
                          recomendaciones (3 en lugar de 5). Un cliente
                          limpio no se ve afectado.
  - tampered-response   : se altera un byte del payload firmado ANTES de
                          verificar -> la verificación Ed25519 debe
                          FALLAR (simulación de manipulación en tránsito,
                          mitigación de D-05).
  - no-client-cert      : conexión TLS sin certificado de cliente -> el
                          canal no se establece (Protector del Canal).
  - untrusted-cert      : certificado emitido por una CA ajena -> el canal
                          no se establece.
  - identity-rotation   : un cliente cambia el client_id declarado en cada
                          solicitud. La pasarela lo ignora y aplica el
                          estado al certificado: tras dos rechazos, el
                          cliente queda en modo endurecido (3 recomendaciones)
                          y la respuesta firmada lleva la identidad del
                          certificado.

Relación con la tesis: Patrón P-01 — Secure Inference Gateway (secciones
3.4 y 4.3). Cada caso imprime "[client] CASO <nombre>: OK/FALLO" y sale con
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

GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://inference-gateway:8080")
TLS_DIR = os.environ.get("TLS_DIR", "/keys/tls")
CA_CERT = os.path.join(TLS_DIR, "ca.crt")


def _cert(client_id: str, untrusted: bool = False):
    """Par (certificado, clave) de la identidad indicada."""
    base = os.path.join(TLS_DIR, "untrusted" if untrusted else "clients", client_id)
    return (base + ".crt", base + ".key")


def _post(client_id: str, session, declared_id=None):
    """POST con autenticación mutua: la identidad es la del certificado."""
    body = {"session": session}
    if declared_id is not None:
        body["client_id"] = declared_id
    return requests.post(
        f"{GATEWAY_URL}/v1/recommend", json=body, timeout=10,
        cert=_cert(client_id), verify=CA_CERT,
    )
RESPONSE_PUB_KEY_PATH = os.environ.get("RESPONSE_PUB_KEY_PATH", "/keys/response_ed25519.pub")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))


def _load_public_key() -> Ed25519PublicKey:
    with open(RESPONSE_PUB_KEY_PATH, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def _verify_signature(body: dict, public_key: Ed25519PublicKey) -> bool:
    """
    Reconstruye el JSON canónico del payload firmado y verifica la firma
    Ed25519 con la clave pública del Protector del Canal de Salida. Retorna False tanto
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
    resp = _post("demo-client-valid", _sample_session())

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

    resp = _post("demo-client-invalid", session)

    if resp.status_code != 422:
        print(f"[client] esperaba 422, recibí {resp.status_code}: {resp.text}")
        return False

    print(f"[client] entrada inválida correctamente rechazada con 422: {resp.json()}")
    return True


def case_rate_limit() -> bool:
    n_requests = RATE_LIMIT_PER_MINUTE + 5
    saw_429 = False
    for _ in range(n_requests):
        resp = _post("demo-client-rate-limit", _sample_session())
        if resp.status_code == 429:
            saw_429 = True
            break

    if not saw_429:
        print(f"[client] tras {n_requests} solicitudes en ráfaga, nunca se recibió 429.")
        return False

    print(f"[client] rate limiting activado correctamente (429 recibido dentro de {n_requests} solicitudes).")
    return True


def case_cross_hardening() -> bool:
    """
    Endurecimiento cruzado de P-01: lo que el Validador de Entrada observa
    sobre un cliente endurece al propio Validador y al Controlador de
    Información de Salida para ese cliente, y solo para él.
    """
    public_key = _load_public_key()

    def borderline_session():
        session = _sample_session()
        session[0]["price"] = 5000.0  # admisible por el dominio, fuera del perfil de entrenamiento
        return session

    def invalid_session():
        session = _sample_session()
        session[0]["price"] = -50
        return session

    # 1) Cliente limpio: la sesión con precio 5000 se acepta en modo normal.
    clean = _post("demo-client-clean", borderline_session())
    if clean.status_code != 200 or len(clean.json()["payload"]["recommendations"]) != 5:
        print(f"[client] el cliente limpio debía recibir 200 con 5 recomendaciones; recibió {clean.status_code}.")
        return False

    # 2) Cliente sospechoso: dos entradas rechazadas elevan su puntuación.
    suspect = "demo-client-suspect"
    for _ in range(2):
        r = _post(suspect, invalid_session())
        if r.status_code != 422:
            print(f"[client] se esperaba 422 por entrada inválida, se recibió {r.status_code}.")
            return False

    # 3) Ahora la misma sesión con precio 5000 se rechaza por el perfil de referencia.
    r = _post(suspect, borderline_session())
    if r.status_code != 422 or not any("perfil de referencia" in str(d) for d in r.json().get("details", [])):
        print(f"[client] en modo endurecido se esperaba 422 por perfil de referencia; se recibió {r.status_code}: {r.text}")
        return False

    # 4) Una solicitud normal se sirve, firmada, pero con menos recomendaciones.
    r = _post(suspect, _sample_session())
    if r.status_code != 200:
        print(f"[client] la solicitud normal del cliente sospechoso debía servirse; se recibió {r.status_code}.")
        return False
    body = r.json()
    n_recs = len(body["payload"]["recommendations"])
    if n_recs != 3 or not _verify_signature(body, public_key):
        print(f"[client] se esperaban 3 recomendaciones con firma válida; se recibieron {n_recs}.")
        return False

    print(
        "[client] endurecimiento cruzado verificado: cliente limpio con 5 recomendaciones; "
        "cliente sospechoso rechazado por el perfil de referencia y limitado a 3 recomendaciones."
    )
    return True


def case_tampered_response() -> bool:
    public_key = _load_public_key()
    resp = _post("demo-client-tampered", _sample_session())

    if resp.status_code != 200:
        print(f"[client] esperaba 200 antes de manipular la respuesta, recibí {resp.status_code}.")
        return False

    body = resp.json()

    # Simulación de manipulación en tránsito (D-05): se altera un producto
    # dentro del payload YA FIRMADO, sin volver a firmar (el atacante no
    # posee la clave privada del Protector del Canal de Salida).
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


def _expect_handshake_rejected(label: str, cert) -> bool:
    """El canal no debe establecerse: ninguna respuesta HTTP es aceptable."""
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/recommend", json={"session": _sample_session()},
            timeout=10, cert=cert, verify=CA_CERT,
        )
    except requests.exceptions.RequestException as exc:
        print(f"[client] {label}: el canal TLS no se estableció ({type(exc).__name__}).")
        return True
    print(f"[client] {label}: la pasarela respondió {resp.status_code}; debía rechazar el canal.")
    return False


def case_no_client_cert() -> bool:
    return _expect_handshake_rejected("sin certificado de cliente", None)


def case_untrusted_cert() -> bool:
    return _expect_handshake_rejected(
        "certificado de una CA ajena", _cert("demo-client-untrusted", untrusted=True)
    )


def case_identity_rotation() -> bool:
    """
    Sin autenticación, un cliente podría evadir el estado por cliente
    cambiando el identificador que declara. Con mTLS, el estado sigue al
    certificado: los identificadores declarados se ignoran.
    """
    public_key = _load_public_key()
    who = "demo-client-rotation"

    invalid = _sample_session()
    invalid[0]["price"] = -50
    for declared in ("rotating-id-1", "rotating-id-2"):
        r = _post(who, invalid, declared_id=declared)
        if r.status_code != 422:
            print(f"[client] se esperaba 422 por entrada inválida, se recibió {r.status_code}.")
            return False

    r = _post(who, _sample_session(), declared_id="rotating-id-3")
    if r.status_code != 200:
        print(f"[client] la solicitud normal debía servirse; se recibió {r.status_code}.")
        return False
    body = r.json()
    n_recs = len(body["payload"]["recommendations"])
    served_to = body["payload"].get("client_id")
    if n_recs != 3 or served_to != who or not _verify_signature(body, public_key):
        print(
            f"[client] se esperaban 3 recomendaciones firmadas para '{who}'; "
            f"se recibieron {n_recs} para '{served_to}'."
        )
        return False

    print(
        "[client] rotación de identidad neutralizada: tres client_id declarados distintos, "
        f"un solo estado para el certificado '{who}', que quedó en modo endurecido "
        "(3 recomendaciones firmadas)."
    )
    return True


CASES = {
    "valid": case_valid,
    "invalid-input": case_invalid_input,
    "rate-limit": case_rate_limit,
    "cross-hardening": case_cross_hardening,
    "tampered-response": case_tampered_response,
    "no-client-cert": case_no_client_cert,
    "untrusted-cert": case_untrusted_cert,
    "identity-rotation": case_identity_rotation,
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
