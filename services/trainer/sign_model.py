"""
sign_model.py
=============
Wrapper del CLI de cosign para el sub-componente "Artifact Signing and
Registry Gate" de P-03 (Trusted ML Artifact Pipeline).

Este módulo NO reimplementa criptografía: invoca el binario `cosign`
instalado en la imagen del contenedor (ver Dockerfile) para firmar un
artefacto arbitrario mediante `cosign sign-blob`, usando un par de claves
generado localmente para el prototipo (ver scripts/generate_keys.sh).

Se firma con `--output-signature` (formato de firma simple, sin "bundle") y
con `--tlog-upload=false`, para que el prototipo pueda ejecutarse
completamente offline, sin depender de la disponibilidad del transparency
log público de Sigstore (Rekor). Esta es una simplificación deliberada de
Capa 1: en un pipeline de producción real conectado a Sigstore público, se
recomendaría mantener la publicación en Rekor (ver Fuerzas de P-03).
"""

import os
import shutil
import subprocess
import sys


class CosignNotFoundError(RuntimeError):
    """El binario cosign no está disponible en el contenedor."""


class CosignSigningError(RuntimeError):
    """cosign sign-blob terminó con un código de error."""


def _check_cosign_available() -> None:
    if shutil.which("cosign") is None:
        raise CosignNotFoundError(
            "El binario 'cosign' no está disponible en este contenedor. "
            "Verifica que la imagen se construyó correctamente a partir del "
            "Dockerfile de services/trainer (que instala cosign v2.4.1)."
        )


def sign_artifact(artifact_path: str, private_key_path: str, signature_output_path: str) -> str:
    """
    Firma `artifact_path` con la clave privada `private_key_path` usando
    `cosign sign-blob`, escribiendo la firma en `signature_output_path`.

    Requiere que la variable de entorno COSIGN_PASSWORD esté definida
    (puede ser una cadena vacía) para evitar que cosign solicite la
    contraseña de la clave privada de forma interactiva, lo cual
    bloquearía la ejecución dentro de un contenedor no interactivo.

    Retorna la ruta del archivo de firma generado.
    """
    _check_cosign_available()

    if not os.path.isfile(artifact_path):
        raise FileNotFoundError(f"No se encontró el artefacto a firmar: {artifact_path}")

    if not os.path.isfile(private_key_path):
        raise FileNotFoundError(
            f"No se encontró la clave privada en {private_key_path}. "
            "Ejecuta ./scripts/generate_keys.sh antes de entrenar el modelo."
        )

    if "COSIGN_PASSWORD" not in os.environ:
        raise CosignSigningError(
            "La variable de entorno COSIGN_PASSWORD no está definida. "
            "Defínela (puede ser vacía) en el archivo .env del proyecto."
        )

    cmd = [
        "cosign", "sign-blob",
        "--key", private_key_path,
        "--output-signature", signature_output_path,
        "--tlog-upload=false",   # prototipo offline: no se publica en Rekor
        "--yes",                 # sin confirmación interactiva (uso en CI/CD)
        artifact_path,
    ]

    print(f"[sign_model] Firmando artefacto: {artifact_path}")
    print(f"[sign_model] Comando: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise CosignSigningError(
            f"cosign sign-blob falló (código {result.returncode}).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    print(f"[sign_model] Firma generada correctamente en: {signature_output_path}")
    if result.stdout.strip():
        print(f"[sign_model] Salida de cosign: {result.stdout.strip()}")

    return signature_output_path


if __name__ == "__main__":
    # Uso manual (fuera del flujo normal de train.py):
    #   python sign_model.py <artefacto> <clave_privada> <salida_firma>
    if len(sys.argv) != 4:
        print("Uso: python sign_model.py <artefacto> <clave_privada> <salida_firma>")
        sys.exit(1)

    try:
        sign_artifact(sys.argv[1], sys.argv[2], sys.argv[3])
    except (CosignNotFoundError, CosignSigningError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
