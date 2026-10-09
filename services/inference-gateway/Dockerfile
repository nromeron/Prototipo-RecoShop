# =============================================================================
# services/inference-gateway/Dockerfile
# =============================================================================
# Contenedor "inference-gateway": expone POST /v1/recommend detrás de los
# tres sub-componentes de P-01 (Secure Inference Gateway). Al arrancar,
# descarga el modelo firmado del Model Registry de la Capa 1 y verifica su
# firma con cosign ANTES de cargarlo -- por eso esta imagen también incluye
# el binario de cosign, igual que trainer y deployment-gate en la Capa 1.
# =============================================================================

# Misma versión fijada (v2.4.1) que el resto del proyecto: v3+ cambia el
# formato de firma por defecto (bundle), lo que rompería el flujo
# --output-signature/--signature usado en toda la Capa 1 y en esta Capa 2.
FROM ghcr.io/sigstore/cosign/cosign:v2.4.1 AS cosign-bin

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=cosign-bin /ko-app/cosign /usr/local/bin/cosign
RUN chmod +x /usr/local/bin/cosign && cosign version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py input_validator.py output_controller.py response_signer.py suspicion.py ./

CMD ["python", "app.py"]
