# =============================================================================
# services/inference-client/Dockerfile
# =============================================================================
# Contenedor "inference-client": cliente verificador de referencia para la
# Capa 2 (P-01). Ejecuta los cuatro casos de demostración contra
# inference-gateway (ver client_demo.py). No requiere cosign: solo verifica
# la firma Ed25519 de las respuestas con la clave pública del Response
# Signer, no artefactos de modelo.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY client_demo.py ./

CMD ["python", "client_demo.py", "--case", "valid"]
