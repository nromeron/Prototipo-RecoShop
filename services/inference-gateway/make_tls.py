"""
make_tls.py
===========
Genera la infraestructura de autenticación mutua (mTLS) del Protector del
Canal de P-01 (Capa 2):

  <dir>/ca.crt                     autoridad de certificación del prototipo
  <dir>/server.crt, server.key     certificado de la pasarela
                                   (SAN: inference-gateway, localhost, 127.0.0.1)
  <dir>/clients/<id>.crt, .key     un certificado por identidad de cliente;
                                   la pasarela toma la identidad del CN
  <dir>/untrusted/<id>.crt, .key   cliente firmado por una CA ajena (caso
                                   negativo); la clave de esa CA se descarta

La clave privada de la CA no se guarda: una vez emitidos los certificados,
nadie puede emitir otros con la misma CA. Para añadir identidades hay que
regenerar todo el directorio.

Relación con la tesis: Anexo C, P-01 — «el Protector del Canal verifica la
identidad del cliente» y «establece autenticación mutua del canal». En
producción, la PKI sería la de la malla de servicios (p. ej., Istio).
"""

import datetime as dt
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CLIENT_IDS = [
    "demo-client-valid",
    "demo-client-invalid",
    "demo-client-rate-limit",
    "demo-client-clean",
    "demo-client-suspect",
    "demo-client-tampered",
    "demo-client-rotation",
    "healthcheck",
]
UNTRUSTED_IDS = ["demo-client-untrusted"]
VALIDITY_DAYS = 3650


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _name(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RecoShop (prototipo)"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def _ca(cn: str):
    key = _key()
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(_name(cn))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _leaf(cn: str, ca_key, ca_cert, server: bool):
    key = _key()
    now = dt.datetime.now(dt.timezone.utc)
    eku = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(ca_cert.subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    )
    if server:
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.DNSName("inference-gateway"),
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False)
    return key, builder.sign(ca_key, hashes.SHA256())


def _write(path: str, key, cert) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".key", "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    with open(path + ".crt", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def main(out_dir: str) -> None:
    ca_key, ca_cert = _ca("RecoShop Inference CA (prototipo)")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "ca.crt"), "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    _write(os.path.join(out_dir, "server"), *_leaf("inference-gateway", ca_key, ca_cert, server=True))
    for cid in CLIENT_IDS:
        _write(os.path.join(out_dir, "clients", cid), *_leaf(cid, ca_key, ca_cert, server=False))

    rogue_key, rogue_cert = _ca("CA ajena (atacante simulado)")
    for cid in UNTRUSTED_IDS:
        _write(os.path.join(out_dir, "untrusted", cid), *_leaf(cid, rogue_key, rogue_cert, server=False))

    print(f"CA, certificado de la pasarela y {len(CLIENT_IDS)} certificados de cliente en {out_dir}.")
    print("La clave privada de la CA no se conserva.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/keys-rw/tls")
