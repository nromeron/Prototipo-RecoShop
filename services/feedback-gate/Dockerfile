# =============================================================================
# services/feedback-gate/Dockerfile
# =============================================================================
# Contenedor "feedback-gate": implementa el Secure Retraining Gate de P-02
# (Guardian de Ingesta + Monitor de Drift de Seguridad). No firma ni
# verifica artefactos de modelo, por lo que -- a diferencia de trainer,
# deployment-gate e inference-gateway -- esta imagen NO incluye cosign.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generate_feedback.py feedback_gate.py ./

CMD ["python", "feedback_gate.py", "--batch", "/app/data/batch_clean.csv"]
