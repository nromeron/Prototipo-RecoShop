# =============================================================================
# services/trainer/Dockerfile
# =============================================================================
# Contenedor "trainer": entrena el modelo LightGBM de RecoShop, lo firma con
# cosign y lo registra en MLflow (sub-componente Artifact Signing and
# Registry Gate de P-03). También incluye tamper_model.py, que NO forma
# parte del pipeline legítimo: simula el ataque de sustitución de artefactos
# de la debilidad D-01 para el caso negativo del prototipo (ver README.md).
# =============================================================================

# Etapa 1: obtener el binario de cosign ya compilado desde la imagen oficial
# de Sigstore. Se usa una versión fijada (v2.4.1) por reproducibilidad: las
# versiones mayores (v3+) cambian el formato de firma por defecto (bundle),
# lo cual rompería el flujo --output-signature/--signature usado aquí.
FROM ghcr.io/sigstore/cosign/cosign:v2.4.1 AS cosign-bin

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copiamos el binario de cosign en lugar de descargarlo por script: es más
# reproducible y no depende de la disponibilidad de GitHub Releases durante
# el build.
COPY --from=cosign-bin /ko-app/cosign /usr/local/bin/cosign
RUN chmod +x /usr/local/bin/cosign && cosign version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generate_data.py train.py sign_model.py tamper_model.py mlbom.py ./

# Sin ENTRYPOINT fijo: cada script se invoca explícitamente desde
# "docker compose run --rm trainer python <script>.py" (ver scripts/).
CMD ["python", "train.py"]
