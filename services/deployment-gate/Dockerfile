# =============================================================================
# services/deployment-gate/Dockerfile
# =============================================================================
# Contenedor "deployment-gate": implementa el gate de despliegue que
# verifica la firma cosign del modelo ANTES de aprobarlo. Es el punto de
# decisión final del sub-componente Artifact Signing and Registry Gate de
# P-03: "verificación obligatoria de firma en despliegue: el pipeline
# CI/CD rechaza cualquier artefacto sin firma válida" (ver sección 3.4).
# =============================================================================

FROM ghcr.io/sigstore/cosign/cosign:v2.4.1 AS cosign-bin

FROM python:3.11-slim

COPY --from=cosign-bin /ko-app/cosign /usr/local/bin/cosign
RUN chmod +x /usr/local/bin/cosign && cosign version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY verify_and_deploy.py ./

CMD ["python", "verify_and_deploy.py"]
