# Prototipo RecoShop — Diseño Seguro de Sistemas de Machine Learning

Prototipo de validación (Design Science Research, Fase 4) de la tesis de maestría
**"Método para el Diseño Seguro de Sistemas de Machine Learning basado en
Identificación de Debilidades Arquitectónicas"** (Ingeniería de Sistemas y
Computación, Universidad Nacional de Colombia).

Sobre **RecoShop** — un sistema ficticio de recomendación de productos
e-commerce (ranker LightGBM) — el prototipo instancia de forma ejecutable los
tres patrones de seguridad del catálogo de la tesis, en tres capas
incrementales sobre un único stack Docker Compose. Cada capa produce evidencia
determinista y verificable mediante códigos de salida semánticos.

## Capas, patrones y debilidades

| Capa | Patrón | Sub-componentes demostrados | Debilidades mitigadas |
|------|--------|-----------------------------|-----------------------|
| 1 | **P-03** Trusted ML Artifact Pipeline | Artifact Signing & Registry Gate (cosign v2.4.1 + MLflow Model Registry), Deployment Gate | D-01 |
| 2 | **P-01** Secure Inference Gateway | Input Validator (Pandera), Output Controller (top-k + token bucket), Response Signer (Ed25519) | D-02, D-04, D-05 |
| 3 | **P-02** Secure Retraining Gate | Guardián de Ingesta (KS global por feature), Monitor de Drift de Seguridad (KS por segmento, índices de concentración, señal de manipulación de etiquetas) | D-03 (y variante de feedback de D-07) |

**Integración entre capas (defensa en profundidad):** el gateway de la Capa 2
no confía en ningún artefacto local — al arrancar descarga el modelo y su firma
del Model Registry y verifica con cosign (garantías de la Capa 1 / P-03) antes
de servir. Si la verificación falla, el proceso termina: el gateway nunca sirve
un modelo no verificado.

## Requisitos

- **Docker Desktop en ejecución** (Windows: con integración WSL2 activa) o
  Docker Engine (Linux/macOS).
- **bash 4+** — los scripts usan `declare -A` y `set -euo pipefail`.
- Git con finales de línea **LF** (el `.gitattributes` del repositorio lo
  fuerza al clonar).

## Inicio rápido

```bash
cp .env.example .env
chmod +x scripts/*.sh

# Claves (una sola vez)
./scripts/generate_keys.sh            # par cosign — firma de artefactos (Capa 1)
./scripts/generate_response_keys.sh   # par Ed25519 — firma de respuestas (Capa 2)

# Capa 1 — P-03 Trusted ML Artifact Pipeline
./scripts/run_layer1_positive_case.sh   # exit 0: el gate APRUEBA un modelo íntegro
./scripts/run_layer1_negative_case.sh   # exit 0: el gate RECHAZA un modelo manipulado

# Capa 2 — P-01 Secure Inference Gateway
./scripts/run_layer2_demo.sh            # exit 0: 4 casos del cliente verificador en verde

# Capa 3 — P-02 Secure Retraining Gate
./scripts/run_layer3_demo.sh            # exit 0: veredictos 0/3/4 con semilla 42
./scripts/run_layer3_seeds.sh           # exit 0: matriz 18/18 en 6 semillas (AF-08)
```

## Estructura del repositorio

```
├── docker-compose.yml          # stack único: las tres capas comparten red, registry y claves
├── keys/                       # claves generadas localmente (NUNCA se versionan)
├── evidence/                   # registros de ejecución que sustentan el Anexo E
├── scripts/                    # orquestadores de demo, uno por caso/capa
└── services/
    ├── minio, mlflow           # infraestructura: almacenamiento S3 + Model Registry
    ├── trainer                 # entrena, firma (cosign) y registra; incluye tamper_model.py (ataque D-01)
    ├── deployment-gate         # verifica firma ANTES de aprobar despliegue (Capa 1)
    ├── inference-gateway       # FastAPI: los 3 sub-componentes de P-01 (Capa 2)
    ├── inference-client        # cliente verificador de referencia: 4 casos (Capa 2)
    └── feedback-gate           # Guardián + Monitor de P-02, cuarentena con reason.json (Capa 3)
```

## Convención de códigos de salida

Existen **dos niveles**, deliberadamente distintos:

- **Componentes** (`verify_and_deploy.py`, `feedback_gate.py`): implementan el
  contrato semántico de la tesis —
  `0` = aceptar · `1` = rechazar · `2` = error de infraestructura ·
  `3` = alerta por drift natural · `4` = cuarentena por patrón adversarial.
- **Scripts de demo** (`run_layer*_*.sh`): capturan el código del componente,
  lo comparan contra el esperado del caso y retornan **0 si la demo se comportó
  según el contrato** y 1 si se desvió. Un caso negativo exitoso (el gate
  rechaza el modelo manipulado) termina por tanto en `exit 0`.

El código `2` nunca es una decisión de seguridad: señala un problema de entorno
(archivos ausentes, formato) y los scripts lo reportan como tal, separado de
las decisiones incorrectas del gate.

## Protocolo de sensibilidad de semillas (Capa 3)

`run_layer3_seeds.sh` ejecuta el experimento completo con las semillas
`7, 13, 42, 101, 777, 2026` y verifica el contrato `0/3/4` en las 18
evaluaciones. Con las amplitudes de drift natural calibradas
(**price +9 %, product_popularity +0.06**), el veredicto es determinista en
las 6 semillas. Este es el límite de validez documentado del detector: por
debajo de esas amplitudes, la alerta de drift natural no está garantizada
(la detección adversarial no se ve afectada). Los registros de referencia
están en `evidence/`.

## Notas de reproducibilidad

Hallazgos documentados durante la validación en runtime (WSL2 + Docker
Desktop, agosto 2026):

1. **Docker Desktop debe estar en ejecución** antes de invocar cualquier
   script. En WSL2, si está apagado o arrancando, el comando `docker` existe
   (stub) pero falla con "could not be found in this WSL 2 distro". Verificar
   además la integración WSL (Docker Desktop → Settings → Resources →
   WSL Integration).
2. **bash 4+** es requisito de los scripts (`declare -A`, `set -euo pipefail`).
3. **libgomp1**: la imagen base `python:3.11-slim` no incluye esta dependencia
   nativa de LightGBM; los Dockerfiles de `trainer` e `inference-gateway` la
   instalan explícitamente.
4. **Generación de claves**: los scripts montan `./keys` en un destino
   alternativo (`/keys-rw`) porque `docker compose run -v` no sobrescribe de
   forma fiable un montaje read-only que el servicio ya define sobre el mismo
   destino (`/keys:ro`).
5. **Finales de línea**: los scripts requieren LF. El `.gitattributes` lo
   fuerza; si se edita desde Windows sin esa configuración, normalizar con
   `sed -i 's/\r$//' scripts/*.sh`.
6. **Estado del registry entre demos**: el caso negativo de la Capa 1 deja un
   artefacto manipulado como versión más reciente del Model Registry (por
   diseño). Las demos posteriores registran siempre una versión fresca; el
   rechazo del artefacto manipulado por el inference-gateway al arrancar es
   comportamiento correcto de la integración P-03 → P-01.
7. **Reconstrucción tras editar código**: los servicios con `build:` congelan
   su código dentro de la imagen. Toda edición a un `.py` o `Dockerfile`
   requiere `docker compose build <servicio>` antes de re-ejecutar.
8. **NaN/Infinity por la API JSON**: la serialización JSON estándar
   (requests ≥ 2.27, `allow_nan=False`) impide inyectar NaN/Infinity por esta
   interfaz; el caso `invalid-input` usa valores serializables fuera de rango,
   y el chequeo de no-finitud del Input Validator queda como defensa en
   profundidad para otros canales de entrada.
9. **Códigos de salida a través de pipes**: `script | tee log` reporta en `$?`
   el código de `tee`, no del script. Para verificar el código real:
   `echo "exit: ${PIPESTATUS[0]}"`.
10. **Estado de la cuarentena entre corridas**: el volumen `feedback-data`
    persiste; `run_layer3_demo.sh` limpia `/app/data/quarantine` antes de
    generar, de modo que la evidencia `reason.json` corresponde siempre a la
    corrida actual.

## Gestión de claves

`cosign.key` (firma de artefactos) y `response_ed25519.key` (firma de
respuestas) son claves **privadas** generadas localmente. El `.gitignore`
excluye todo el contenido de `keys/` salvo `.gitkeep` — nunca deben
versionarse. Los archivos generados dentro de contenedores quedan como
propiedad de `root` en el host; para regenerarlos: `sudo rm keys/<archivo>` y
re-ejecutar el script correspondiente. En un entorno de producción, estas
claves se gestionarían mediante un KMS con rotación y revocación (ver
"Fuerzas" del patrón P-03 en el catálogo de la tesis) — el archivo plano es
una simplificación deliberada del prototipo.

## Alcance y contexto académico

Este prototipo es una **demostración de viabilidad en entorno de laboratorio**
(validación DSR de Nivel 4 donde así se documenta en la tesis), no una
implementación de producción: umbrales calibrados sobre datos sintéticos,
un solo stack tecnológico, sin adversario adaptativo. Las taxonomías de
referencia son OWASP ML Top 10 y MITRE ATLAS v5.4.0. La evidencia de
ejecución (logs, matriz de sensibilidad, `reason.json`) alimenta el capítulo
de evaluación y el Anexo E del documento de tesis.
