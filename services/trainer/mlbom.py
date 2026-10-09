"""
mlbom.py
========
Construye el ML-BOM (Machine Learning Bill of Materials) del modelo de
RecoShop en formato CycloneDX v1.7 (ECMA-424, 2.ª edición, diciembre de
2025).

Relación con la tesis:
  - Patrón P-03 (Trusted ML Artifact Pipeline). El catálogo prescribe el
    ML-SBOM como documento de enlace del pipeline unificado: vincula el
    artefacto del modelo con los datos y las dependencias que lo produjeron.
  - El ML-BOM se FIRMA con la misma clave cosign que el modelo. Un ML-BOM
    sin firma sería un documento que cualquiera con acceso al registry
    podría reescribir; firmado, es una declaración verificable de
    procedencia.

Decisión de implementación: el JSON se construye directamente sobre el
esquema CycloneDX en lugar de usar cyclonedx-python-lib, porque esa librería
aún no serializa el campo modelCard ni el campo data de los componentes
(issues #911 y #912 del repositorio CycloneDX/cyclonedx-python-lib).
"""

import hashlib
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

import pandas as pd

MLBOM_SPEC_VERSION = "1.7"
MLBOM_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"

MODEL_BOM_REF = "model-recoshop-ranker"
DATASET_BOM_REF = "dataset-recoshop-synthetic-sessions"

# Dependencias de software que determinan el comportamiento del modelo.
TRACKED_LIBRARIES = ["lightgbm", "scikit-learn", "numpy", "pandas", "mlflow"]


def sha256_of_dataframe(df: pd.DataFrame) -> str:
    """
    Huella del dataset de entrenamiento. Se serializa a CSV sin índice, de
    modo que el hash depende solo del contenido; con la misma semilla, el
    dataset sintético (y por tanto su hash) es reproducible.
    """
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


def _library_components():
    components = []
    for name in TRACKED_LIBRARIES:
        try:
            lib_version = version(name)
        except PackageNotFoundError:
            continue
        purl = f"pkg:pypi/{name}@{lib_version}"
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": name,
                "version": lib_version,
                "purl": purl,
            }
        )
    return components


def _provenance_properties(provenance):
    if not provenance:
        return [{"name": "recoshop:provenance:status", "value": "no-verificada"}]
    return [
        {"name": "recoshop:provenance:status", "value": "verificada"},
        {"name": "recoshop:provenance:source", "value": provenance["source"]},
        {"name": "recoshop:provenance:endpoint", "value": provenance["endpoint"]},
        {"name": "recoshop:provenance:exported_at", "value": provenance["exported_at_utc"]},
        {"name": "recoshop:provenance:accepted_at", "value": provenance["accepted_at_utc"]},
        {"name": "recoshop:provenance:manifest_sha256", "value": provenance["manifest_sha256"]},
        {"name": "recoshop:provenance:record",
         "value": f"s3://recoshop-provenance/datasets/{provenance['dataset_sha256']}.json"},
    ]


def build_mlbom(
    *,
    model_name: str,
    run_id: str,
    model_sha256: str,
    dataset_sha256: str,
    n_dataset_rows: int,
    feature_columns: list,
    ndcg_at_10: float,
    random_seed: int,
    n_train_sessions: int,
    n_eval_sessions: int,
    provenance: dict = None,
) -> dict:
    """Retorna el ML-BOM como diccionario listo para serializar a JSON."""
    libraries = _library_components()

    model_component = {
        "type": "machine-learning-model",
        "bom-ref": MODEL_BOM_REF,
        "name": model_name,
        "version": run_id,
        "description": (
            "Modelo de ranking de productos del caso de estudio RecoShop "
            "(sistema de recomendación e-commerce ficticio)."
        ),
        "hashes": [{"alg": "SHA-256", "content": model_sha256}],
        "modelCard": {
            "modelParameters": {
                "approach": {"type": "supervised"},
                "task": "ranking",
                "architectureFamily": "gradient boosted decision trees",
                "modelArchitecture": "LightGBM LGBMRanker (objetivo lambdarank)",
                "datasets": [{"ref": DATASET_BOM_REF}],
                "inputs": [{"format": "tabular: " + ", ".join(feature_columns)}],
                "outputs": [{"format": "puntaje de relevancia por candidato (ranking)"}],
            },
            "quantitativeAnalysis": {
                "performanceMetrics": [
                    {
                        "type": "NDCG@10",
                        "value": f"{ndcg_at_10:.4f}",
                        "slice": f"conjunto de evaluación ({n_eval_sessions} sesiones)",
                    }
                ]
            },
        },
        "properties": [
            {"name": "recoshop:mlflow_run_id", "value": run_id},
            {"name": "recoshop:random_seed", "value": str(random_seed)},
            {"name": "recoshop:n_train_sessions", "value": str(n_train_sessions)},
            {"name": "recoshop:signature", "value": "cosign sign-blob (clave ECDSA local, sin Rekor)"},
        ],
    }

    dataset_component = {
        "type": "data",
        "bom-ref": DATASET_BOM_REF,
        "name": "recoshop-synthetic-sessions",
        "version": f"seed-{random_seed}",
        "hashes": [{"alg": "SHA-256", "content": dataset_sha256}],
        "data": [
            {
                "type": "dataset",
                "name": "recoshop-synthetic-sessions",
                "description": (
                    f"Sesiones sintéticas de navegación e-commerce ({n_dataset_rows} filas), "
                    f"generadas de forma determinista con semilla {random_seed}."
                ),
                "classification": "sintético, sin datos personales",
            }
        ],
        # Enlace con la Compuerta de Procedencia de Datos (P-03): si el lote
        # pasó por ella, su registro queda declarado en el ML-BOM firmado.
        "properties": _provenance_properties(provenance),
    }

    return {
        "$schema": MLBOM_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": MLBOM_SPEC_VERSION,
        # Número de serie determinista por run: el mismo run produce el mismo
        # identificador, y cada run nuevo produce uno distinto.
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'recoshop:{run_id}')}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "recoshop-trainer",
                        "description": "Pipeline de entrenamiento del prototipo RecoShop (P-03)",
                    }
                ]
            },
        },
        "components": [model_component, dataset_component, *libraries],
        "dependencies": [
            {
                "ref": MODEL_BOM_REF,
                "dependsOn": [DATASET_BOM_REF, *[lib["bom-ref"] for lib in libraries]],
            }
        ],
    }


def model_hash_from_mlbom(bom: dict):
    """
    Extrae el SHA-256 declarado para el único componente de tipo
    machine-learning-model. Retorna None si el documento no cumple la
    estructura esperada (formato distinto, cero o varios modelos, o sin hash).
    """
    if bom.get("bomFormat") != "CycloneDX":
        return None
    models = [c for c in bom.get("components", []) if c.get("type") == "machine-learning-model"]
    if len(models) != 1:
        return None
    for h in models[0].get("hashes", []):
        if h.get("alg") == "SHA-256":
            return h.get("content")
    return None
