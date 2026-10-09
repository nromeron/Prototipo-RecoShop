"""
app.py
======
Aplicación FastAPI del Secure Inference Gateway (Patrón P-01), Capa 2 del
prototipo de tesis. Expone POST /v1/recommend, coordinando los tres
sub-componentes del patrón:

  1. input_validator.py  -- Validador de Entrada (mitigación de D-04)
  2. output_controller.py -- Controlador de Información de Salida,
     incluye top-k limiting y rate limiting (mitigación de D-02)
  3. response_signer.py  -- Protector del Canal / Response Signer
     (mitigación de D-05)

PUNTO DE INTEGRACIÓN CON LA CAPA 1 (P-03): al arrancar, este servicio NO
confía en ningún artefacto local. Descarga el modelo y su firma
directamente del Model Registry (MLflow + MinIO, el mismo registry que
usa la Capa 1) y verifica la firma con cosign ANTES de cargar el modelo
con lightgbm.Booster(...). Si la verificación falla, el proceso termina
con un código de salida distinto de cero: el gateway NUNCA sirve un
modelo no verificado. Esta verificación ocurre a nivel de módulo (no
dentro de un handler de FastAPI), de modo que corre exactamente una vez,
antes de que uvicorn empiece a aceptar conexiones.

Además de la firma del modelo, verifica su ML-BOM firmado (documento de
enlace de P-03): la firma del ML-BOM y que el resumen criptográfico del
modelo descargado coincida con el que el ML-BOM declara. Así la pasarela
rechaza también la sustitución por un modelo legítimamente firmado de otra
versión, igual que la compuerta de despliegue.

ENDURECIMIENTO CRUZADO: los sub-componentes comparten un registro de
sospecha por cliente (suspicion.py). Los rechazos del Validador y los
excesos de tasa del Controlador elevan la puntuación del cliente; por
encima del umbral, el Validador aplica el perfil de referencia de
entrenamiento y el Controlador reduce el número de recomendaciones.

Relación con la tesis: A4.4 §3.1 (Cambios concretos por patrón, P-01) y
§4.1 (Análisis de impacto en seguridad). Mitigación de D-02, D-04 y D-05.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List

import lightgbm as lgb
import mlflow
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mlflow.tracking import MlflowClient
from pydantic import BaseModel

from input_validator import InputValidationError, validate_candidates
from output_controller import OutputController, RateLimitExceeded
from response_signer import ResponseSigner
from suspicion import SuspicionRegistry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("inference-gateway")

MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "recoshop-ranker")
COSIGN_PUB_PATH = os.environ.get("COSIGN_PUB_PATH", "/keys/cosign.pub")
RESPONSE_SIGNING_KEY_PATH = os.environ.get("RESPONSE_SIGNING_KEY_PATH", "/keys/response_ed25519.key")
TOP_K = int(os.environ.get("TOP_K", "5"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
SUSPICION_THRESHOLD = float(os.environ.get("SUSPICION_THRESHOLD", "0.5"))
SUSPICION_HALF_LIFE_SECONDS = float(os.environ.get("SUSPICION_HALF_LIFE_SECONDS", "600"))
RESTRICTED_TOP_K = int(os.environ.get("RESTRICTED_TOP_K", "3"))

FEATURE_COLUMNS = [
    "category",
    "price",
    "user_purchase_history",
    "product_popularity",
    "discount_pct",
    "is_weekend",
]


class Candidate(BaseModel):
    # Sin restricciones de rango a nivel de Pydantic: los rangos y la
    # ausencia de NaN/Inf son responsabilidad explícita del Input
    # Validator (input_validator.py), no de esta capa de serialización.
    category: int
    price: float
    user_purchase_history: int
    product_popularity: float
    discount_pct: float
    is_weekend: int
    product_id: int


class RecommendRequest(BaseModel):
    client_id: str
    session: List[Candidate]


def _sha256_of_file(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _cosign_verify(blob_path: str, sig_path: str) -> subprocess.CompletedProcess:
    cmd = [
        "cosign", "verify-blob",
        "--key", COSIGN_PUB_PATH,
        "--signature", sig_path,
        "--insecure-ignore-tlog=true",
        blob_path,
    ]
    logger.info(f"[inference-gateway] Verificando firma: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def _model_hash_declared_in_mlbom(mlbom_path: str):
    """SHA-256 del único componente machine-learning-model del ML-BOM, o None."""
    try:
        with open(mlbom_path, encoding="utf-8") as f:
            bom = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if bom.get("bomFormat") != "CycloneDX":
        return None
    models = [c for c in bom.get("components", []) if c.get("type") == "machine-learning-model"]
    if len(models) != 1:
        return None
    for h in models[0].get("hashes", []):
        if h.get("alg") == "SHA-256":
            return h.get("content")
    return None


def load_and_verify_model() -> lgb.Booster:
    """
    Descarga la última versión registrada de MLFLOW_MODEL_NAME desde
    MLflow, verifica su firma cosign con la clave pública de la Capa 1, y
    la carga como Booster de LightGBM. Termina el proceso (sys.exit(1)) si
    cualquier paso falla -- el gateway nunca sirve un modelo no verificado.
    """
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{MLFLOW_MODEL_NAME}'")
    if not versions:
        logger.critical(
            f"[inference-gateway] ERROR CRÍTICO: no hay ninguna versión registrada "
            f"del modelo '{MLFLOW_MODEL_NAME}' en MLflow. Ejecuta primero "
            "'docker compose run --rm trainer python train.py' (Capa 1)."
        )
        sys.exit(1)

    latest = max(versions, key=lambda v: int(v.version))
    logger.info(
        f"[inference-gateway] Evaluando la versión {latest.version} de "
        f"'{MLFLOW_MODEL_NAME}' (run_id={latest.run_id})."
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        model_path = mlflow.artifacts.download_artifacts(
            run_id=latest.run_id, artifact_path="model/model.txt", dst_path=tmp_dir
        )
        sig_path = mlflow.artifacts.download_artifacts(
            run_id=latest.run_id, artifact_path="model/model.txt.sig", dst_path=tmp_dir
        )
        try:
            mlbom_path = mlflow.artifacts.download_artifacts(
                run_id=latest.run_id, artifact_path="model/mlbom.cdx.json", dst_path=tmp_dir
            )
            mlbom_sig_path = mlflow.artifacts.download_artifacts(
                run_id=latest.run_id, artifact_path="model/mlbom.cdx.json.sig", dst_path=tmp_dir
            )
        except Exception as exc:  # noqa: BLE001 - política de falla segura
            logger.critical(
                "[inference-gateway] ERROR CRÍTICO: la versión no tiene ML-BOM firmado "
                f"(política de P-03). El gateway no la sirve. Detalle: {exc}"
            )
            sys.exit(1)

        if shutil.which("cosign") is None:
            logger.critical(
                "[inference-gateway] ERROR CRÍTICO: el binario 'cosign' no está "
                "disponible en este contenedor. Revisa el Dockerfile."
            )
            sys.exit(1)

        if not os.path.isfile(COSIGN_PUB_PATH):
            logger.critical(
                f"[inference-gateway] ERROR CRÍTICO: no se encontró la clave "
                f"pública cosign en {COSIGN_PUB_PATH}. Ejecuta "
                "./scripts/generate_keys.sh (Capa 1) antes de levantar el gateway."
            )
            sys.exit(1)

        current_hash = _sha256_of_file(model_path)
        declared_hash = _model_hash_declared_in_mlbom(mlbom_path)
        logger.info(f"[inference-gateway] SHA-256 del artefacto descargado: {current_hash}")
        logger.info(f"[inference-gateway] SHA-256 declarado en el ML-BOM:   {declared_hash}")

        mlbom_check = _cosign_verify(mlbom_path, mlbom_sig_path)
        if mlbom_check.returncode != 0:
            logger.critical(
                "[inference-gateway] ERROR CRÍTICO: FIRMA DEL ML-BOM INVÁLIDA. "
                "El gateway nunca sirve un modelo sin documento de enlace auténtico."
            )
            logger.critical(f"[inference-gateway] stderr de cosign: {mlbom_check.stderr.strip()}")
            sys.exit(1)

        if declared_hash is None or declared_hash != current_hash:
            logger.critical(
                "[inference-gateway] ERROR CRÍTICO: el modelo descargado no es el que "
                "declara el ML-BOM de esta versión (posible sustitución por un modelo "
                "firmado de otra versión). El gateway no lo sirve."
            )
            sys.exit(1)

        result = _cosign_verify(model_path, sig_path)

        if result.returncode != 0:
            logger.critical(
                "[inference-gateway] ERROR CRÍTICO: FIRMA INVÁLIDA. El gateway "
                "nunca sirve un modelo no verificado (integración con el "
                "Artifact Signing and Registry Gate de P-03, Capa 1)."
            )
            logger.critical(f"[inference-gateway] stderr de cosign: {result.stderr.strip()}")
            sys.exit(1)

        logger.info(
            "[inference-gateway] ML-BOM, vínculo y firma del modelo verificados. Cargando modelo..."
        )
        booster = lgb.Booster(model_file=model_path)

    logger.info("[inference-gateway] Modelo cargado y listo para servir.")
    return booster


# --- Carga y verificación a nivel de módulo: corre exactamente una vez,
# --- antes de que uvicorn acepte ninguna conexión. ---
_model = load_and_verify_model()
_output_controller = OutputController(top_k=TOP_K, rate_limit_per_minute=RATE_LIMIT_PER_MINUTE)
_response_signer = ResponseSigner(RESPONSE_SIGNING_KEY_PATH)
_suspicion = SuspicionRegistry(threshold=SUSPICION_THRESHOLD, half_life_seconds=SUSPICION_HALF_LIFE_SECONDS)

app = FastAPI(title="RecoShop Secure Inference Gateway (P-01, Capa 2)")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Unifica el formato de error de FastAPI/Pydantic (tipos malformados)
    # con el contrato {"error": "input_validation_failed", "details": [...]}
    # del Input Validator, para que el cliente siempre reciba la misma
    # forma de respuesta ante un 422, sea cual sea la causa.
    return JSONResponse(
        status_code=422,
        content={"error": "input_validation_failed", "details": exc.errors()},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/recommend")
async def recommend(payload: RecommendRequest):
    client_id = payload.client_id

    # 1) Rate limiting (Output Controller) -- control de primera línea,
    #    antes de gastar cómputo en validación e inferencia.
    try:
        _output_controller.check_rate_limit(client_id)
    except RateLimitExceeded:
        score = _suspicion.record(client_id, "rate_limit")
        logger.warning(
            f"[inference-gateway] Rate limit excedido para client_id={client_id} "
            f"(sospecha={score:.2f})"
        )
        return JSONResponse(status_code=429, content={"error": "rate_limit_exceeded"})

    # Endurecimiento cruzado: el estado de sospecha del cliente, alimentado
    # por el Validador y el Controlador, decide el modo de esta solicitud.
    hardened = _suspicion.is_suspicious(client_id)
    if hardened:
        logger.warning(f"[inference-gateway] Modo endurecido para client_id={client_id}")

    # 2) Input Validator (mitigación de D-04)
    candidates = [c.model_dump() for c in payload.session]
    try:
        validated_df = validate_candidates(candidates, strict=hardened)
    except InputValidationError as exc:
        score = _suspicion.record(client_id, "validation_failure")
        logger.warning(
            f"[inference-gateway] Solicitud rechazada por el Input Validator "
            f"(sospecha={score:.2f}): {exc.details}"
        )
        return JSONResponse(
            status_code=422,
            content={"error": "input_validation_failed", "details": exc.details},
        )

    # 3) Inferencia (sin cambios respecto al modelo firmado en la Capa 1)
    scores = _model.predict(validated_df[FEATURE_COLUMNS])
    product_ids = validated_df["product_id"].tolist()

    # 4) Output Controller: top-k limiting, sin scores crudos (D-02)
    recommendations = _output_controller.build_response(
        product_ids, scores, top_k=RESTRICTED_TOP_K if hardened else None
    )

    # 5) Response Signer: firma Ed25519 de la respuesta (D-05)
    signed_body = _response_signer.sign_payload(
        {"client_id": client_id, "recommendations": recommendations}
    )

    return JSONResponse(status_code=200, content=signed_body)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
