# =============================================================================
# services/mlflow/Dockerfile
# =============================================================================
# Imagen propia del servidor MLflow (tracking + Model Registry), con boto3
# ya instalado para hablar con el almacenamiento S3-compatible de MinIO.
# Sustituye a la imagen pública ghcr.io/mlflow/mlflow:v2.9.2 + pip install
# en tiempo de arranque, fijando ambas dependencias en tiempo de build.
# =============================================================================

FROM python:3.11-slim

RUN pip install --no-cache-dir mlflow==2.9.2 boto3==1.34.51

WORKDIR /mlflow
