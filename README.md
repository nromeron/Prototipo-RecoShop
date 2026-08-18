# RecoShop Prototype — Capa 1: P-03 (Trusted ML Artifact Pipeline)

Prototipo funcional que demuestra la **viabilidad técnica** del sub-componente
**Artifact Signing and Registry Gate** del patrón **P-03 — Trusted ML Artifact
Pipeline**, sobre la debilidad arquitectónica **D-01 (Confianza Implícita en
la Integridad de Artefactos del Model Registry)**, aplicado al caso de
estudio RecoShop (sistema de recomendación de productos e-commerce).

Este prototipo **no es un despliegue de producción**: es una demostración
reproducible, ejecutable con Docker Compose en una sola máquina, de que la
firma criptográfica de artefactos ML y la verificación obligatoria antes del
despliegue son mecánicamente viables y detectan una sustitución maliciosa
del modelo.

---

## 1. Qué demuestra este prototipo

| Elemento | Descripción |
| :--- | :--- |
| **Patrón** | P-03 — Trusted ML Artifact Pipeline (Flujo C: registro y despliegue de artefactos internos) |
| **Sub-componente** | Artifact Signing and Registry Gate |
| **Debilidad mitigada** | D-01 — Confianza Implícita en la Integridad de Artefactos del Model Registry |
| **Caso positivo** | Un modelo LightGBM se entrena, se firma con cosign y se registra en MLflow. El deployment-gate descarga el artefacto y su firma directamente del registry, verifica la firma y **aprueba** el despliegue. |
| **Caso negativo** | Después de firmar y registrar el modelo, se simula un atacante con acceso de escritura al almacenamiento del registry (MinIO) que sustituye los bytes del modelo. El deployment-gate detecta que el hash ya no coincide con la firma y **rechaza** el despliegue. |

El caso negativo simula exactamente el escenario de explotación descrito en
el Entregable A4.2 de la tesis para D-01: *"un atacante que compromete el
Model Registry (o el flujo de red hacia él) puede sustituir un modelo
legítimo por uno malicioso sin ser detectado"* — excepto que, gracias a
P-03, **ahora sí es detectado**.

---

## 2. Alcance y limitaciones (léase antes de ejecutar)

- Esta es la **Capa 1** del prototipo de Fase 4 de la tesis. Implementa
  únicamente el flujo de firma y verificación de artefactos (P-03, Flujo C).
  No implementa los otros dos flujos de P-03 (Data Provenance Gate para
  ingesta de datos, External Model Validator para modelos pre-entrenados
  externos), ni los patrones P-01 (Secure Inference Gateway) o P-02 (Secure
  Retraining Gate).
- **No usa KServe ni Istio.** Esos componentes pertenecen a un clúster de
  Kubernetes y están fuera del alcance de esta capa. En la arquitectura de
  producción descrita en el Entregable A4.1, el Artifact Signing and
  Registry Gate se instancia **sobre el pipeline CI/CD** (GitHub Actions +
  ArgoCD), verificando la firma antes de que ArgoCD sincronice el
  despliegue hacia el clúster KServe — no como un contenedor aislado como
  se simula aquí. Este prototipo reproduce la *lógica* del gate (verificar
  antes de aprobar), no la topología completa de Kubernetes.
- El "despliegue" que aprueba o rechaza `deployment-gate` es **simbólico**:
  el script solo imprime la decisión. No hay un servidor de inferencia real
  sirviendo el modelo en esta capa.
- El par de claves cosign se genera y almacena en disco plano
  (`./keys/cosign.key`) únicamente por simplicidad pedagógica. En
  producción, esta clave debe gestionarse con un KMS (ver la sección
  "Fuerzas" del patrón P-03 en el catálogo de la tesis: *"Gestión
  criptográfica vs. capacidad del equipo ML"*).
- La firma se realiza completamente **offline**: no se publica en el
  transparency log público de Sigstore (Rekor), para que el prototipo
  pueda ejecutarse sin depender de conectividad externa a servicios de
  Sigstore. En un pipeline de producción conectado a Sigstore público, se
  recomienda mantener la publicación en Rekor.

---

## 3. Prerrequisitos

- Docker Engine o Docker Desktop, con **Docker Compose v2** (`docker compose`,
  sin guion).
- Acceso a Internet la primera vez que se construyen las imágenes (para
  descargar `python:3.11-slim`, `ghcr.io/sigstore/cosign/cosign:v2.4.1`,
  `ghcr.io/mlflow/mlflow:v2.9.2`, `minio/minio` y `minio/mc`).
- No se requiere tener `cosign` instalado en la máquina anfitriona: el
  binario se ejecuta siempre dentro de los contenedores.
- Puertos libres en la máquina anfitriona: `5000` (MLflow UI), `9000` (API
  S3 de MinIO), `9001` (consola web de MinIO).

## Notas de reproducibilidad

Hallazgos documentados durante la validación en runtime (WSL2 + Docker Desktop,
agosto 2026):

1. **Docker Desktop debe estar en ejecución** antes de invocar cualquier script.
   En WSL2, si Docker Desktop está apagado o arrancando, el comando `docker`
   existe pero falla con "could not be found in this WSL 2 distro". Verificar
   además que la integración WSL esté activa (Docker Desktop → Settings →
   Resources → WSL Integration).
2. **bash 4+** es requisito de los scripts (`declare -A`, `set -euo pipefail`).
3. **libgomp1**: la imagen base `python:3.11-slim` no incluye esta dependencia
   nativa de LightGBM; el Dockerfile del trainer la instala explícitamente.
4. **Generación de claves**: `generate_keys.sh` monta `./keys` en un destino
   alternativo (`/keys-rw`) porque `docker compose run -v` no sobrescribe de
   forma fiable el montaje read-only que el servicio define sobre `/keys`.
5. **Finales de línea**: los scripts requieren LF. El `.gitattributes` del
   repositorio lo fuerza; si se editan desde Windows sin clonar con esa
   configuración, normalizar con `sed -i 's/\r$//' scripts/*.sh`.
6. **Estado del registry entre demos**: el caso negativo de la Capa 1 deja
  un artefacto manipulado como versión más reciente del Model Registry
  (por diseño). Las demos posteriores registran siempre una versión
  fresca para no depender del estado previo; el rechazo del artefacto
  manipulado por parte del inference-gateway al arrancar es comportamiento
  correcto de la integración P-03 ↔ P-01 (defensa en profundidad).
7. **Reconstrucción tras editar código**: los servicios con `build:` congelan
   su código dentro de la imagen al construirla. Cualquier edición a un `.py`
   o `Dockerfile` requiere `docker compose build <servicio>` antes de
   re-ejecutar; de lo contrario el contenedor corre la versión anterior.
8. **NaN/Infinity por la API JSON**: la serialización JSON estándar
   (requests ≥ 2.27, `allow_nan=False`) impide inyectar NaN/Infinity por
   esta interfaz; el caso `invalid-input` usa valores serializables fuera
   de rango, y el chequeo de no-finitud del Input Validator queda como
   defensa en profundidad para otros canales de entrada.

## Convención de códigos de salida

Existen dos niveles, deliberadamente distintos:

- **Componentes** (`verify_and_deploy.py`, guardián de ingesta, monitor de
  drift): implementan el contrato semántico de la tesis — 0 = aceptar,
  1 = rechazar, 2 = error de infraestructura, 3 = alerta por drift natural,
  4 = cuarentena por patrón adversarial.
- **Scripts de demo** (`run_layer*_*.sh`): capturan el código del componente,
  lo comparan contra el esperado del caso, y retornan **0 si la demo se
  comportó según el contrato** y 1 si se desvió. Un caso negativo exitoso
  (el gate rechaza el modelo manipulado) termina por tanto en exit 0.

---

## 4. Estructura del proyecto

```
recoshop-prototype/
├── docker-compose.yml
├── README.md
├── .env.example
├── keys/                      # se crea al ejecutar generate_keys.sh
│   ├── cosign.key              (privada — NO compartir)
│   └── cosign.pub
├── services/
│   ├── trainer/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── generate_data.py    # datos sintéticos de RecoShop
│   │   ├── train.py            # entrena, firma y registra el modelo
│   │   ├── sign_model.py        # wrapper de cosign sign-blob
│   │   └── tamper_model.py     # simula el ataque D-01 (caso negativo)
│   └── deployment-gate/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── verify_and_deploy.py  # verifica firma → aprueba/rechaza
└── scripts/
    ├── generate_keys.sh
    ├── run_layer1_positive_case.sh
    └── run_layer1_negative_case.sh
```

> **Nota sobre `tamper_model.py`:** no forma parte del pipeline legítimo de
> entrenamiento; representa al **atacante** simulado del caso negativo. Se
> empaquetó dentro de la imagen `trainer` porque reutiliza las mismas
> dependencias (boto3, cliente de MLflow) ya instaladas ahí, no porque sea
> parte del flujo de entrenamiento real.

---

## 5. Cómo ejecutar el prototipo, paso a paso

### 5.1 Preparar el entorno

```bash
cd recoshop-prototype
cp .env.example .env
chmod +x scripts/*.sh
```

### 5.2 Generar el par de claves cosign del prototipo

```bash
./scripts/generate_keys.sh
```

Esto crea `keys/cosign.key` (privada) y `keys/cosign.pub` (pública) usando
la imagen oficial de cosign en un contenedor efímero. Si el archivo `.env`
define `COSIGN_PASSWORD`, se usa esa contraseña para cifrar la clave
privada sin pedirla interactivamente.

### 5.3 Levantar la infraestructura (MinIO + MLflow)

```bash
docker compose up -d mlflow
```

Este único comando levanta también `minio` y `minio-init` de forma
transitiva (por las dependencias declaradas en `docker-compose.yml`).
Verifica que todo esté saludable:

```bash
docker compose ps
```

Espera a que `recoshop-mlflow` muestre estado `healthy` (puede tardar
10-20 segundos la primera vez, mientras se instala `boto3` dentro del
contenedor). Puedes explorar:

- MLflow UI: http://localhost:5000
- Consola de MinIO: http://localhost:9001 (usuario/contraseña definidos en `.env`)

### 5.4 Ejecutar el caso positivo

```bash
./scripts/run_layer1_positive_case.sh
```

Salida esperada (resumida):

```
[train] Modelo registrado: 'recoshop-ranker' versión 1 (run_id=...)
...
Firma verificada correctamente. Modelo APROBADO para despliegue.
✅ RESULTADO: el gate APROBÓ el modelo (comportamiento esperado).
```

### 5.5 Ejecutar el caso negativo

```bash
./scripts/run_layer1_negative_case.sh
```

Salida esperada (resumida):

```
[train] Modelo registrado: 'recoshop-ranker' versión 2 (run_id=...)
...
[tamper_model] Artefacto SOBRESCRITO en el registry (... bytes).
[tamper_model] NOTA: el archivo de firma (model.txt.sig) NO fue modificado...
...
[deployment-gate] ⚠️  El hash actual del artefacto NO coincide con el hash
registrado al momento de la firma...
FIRMA INVÁLIDA. Despliegue RECHAZADO.
✅ RESULTADO: el gate RECHAZÓ el modelo manipulado (comportamiento esperado).
```

Puedes ejecutar `run_layer1_positive_case.sh` y `run_layer1_negative_case.sh` varias
veces; cada ejecución de `train.py` registra una **nueva versión** del
modelo en MLflow (política append-only), y el gate y el atacante simulado
siempre operan sobre la **versión más reciente**.

### 5.6 Limpieza al finalizar

```bash
docker compose down -v
```

Esto elimina los contenedores y los volúmenes de MinIO/MLflow. El par de
claves en `./keys/` **no** se elimina (bórralo manualmente si lo deseas).

---

## 6. Resumen de comandos (de principio a fin)

```bash
cd recoshop-prototype
cp .env.example .env
chmod +x scripts/*.sh
./scripts/generate_keys.sh
docker compose up -d mlflow
docker compose ps                     # esperar a que mlflow esté "healthy"
./scripts/run_layer1_positive_case.sh
./scripts/run_layer1_negative_case.sh
docker compose down -v                # limpieza
```

---

## 7. Manejo de errores esperado

| Situación | Comportamiento |
| :--- | :--- |
| `cosign` no disponible en el contenedor | `sign_model.py` y `verify_and_deploy.py` lanzan `CosignNotFoundError` / `RuntimeError` con un mensaje explícito antes de intentar firmar o verificar. |
| MLflow no responde | `docker compose run` para `trainer`/`deployment-gate` espera automáticamente a que `mlflow` esté `healthy` (declarado en `depends_on`); si el servicio nunca queda saludable, el comando fallará con un timeout claro de Docker Compose. |
| No existe ninguna versión registrada del modelo | `verify_and_deploy.py` y `tamper_model.py` lanzan `RuntimeError` indicando que se debe ejecutar `train.py` primero. |
| Faltan las claves cosign | Los tres scripts de `scripts/` verifican la existencia de `keys/cosign.key` y `keys/cosign.pub` antes de continuar, e indican ejecutar `generate_keys.sh`. |
| `COSIGN_PASSWORD` no definida | `sign_model.py` lanza `CosignSigningError` explícito en lugar de dejar que `cosign` quede esperando un prompt interactivo que nunca llegará dentro del contenedor. |

---

## 8. Relación con el resto de la tesis

- **A4.1** describe la arquitectura de referencia RecoShop v1.0 y ubica el
  punto de inserción de P-03 en la transición Model Registry → Deployment.
- **A4.2** identifica D-01 como la debilidad de mayor severidad contextual
  en RecoShop (Crítica), precisamente por la ausencia de firma antes del
  despliegue automático vía ArgoCD.
- **A4.4** documenta el cambio concreto propuesto: *"firma criptográfica del
  modelo antes del registro"* + *"verificación obligatoria de firma en
  despliegue: el pipeline CI/CD rechaza cualquier artefacto sin firma
  válida"*. Este prototipo implementa exactamente esa verificación
  obligatoria, aunque sobre Docker Compose en lugar de sobre ArgoCD.
- El **riesgo residual** reconocido en A4.4 §7 también aplica aquí: la
  firma prueba integridad (que el artefacto no cambió después de
  firmarse), **no benignidad** (que el contenido del modelo sea inofensivo).
  Este prototipo no evalúa si el modelo entrenado es "bueno" en ningún
  sentido de seguridad; solo demuestra que un artefacto alterado después
  de la firma es detectado.

## 9. Capa 2 — P-01 Secure Inference Gateway

Sobre la misma base de la Capa 1, la Capa 2 implementa el patrón **P-01 —
Secure Inference Gateway**, mitigando **D-02** (extracción del modelo),
**D-04** (entradas adversariales) y **D-05** (integridad de la
respuesta). Ver `services/inference-gateway/README.md` para el detalle
completo de sub-componentes, alcance y limitaciones.

### 9.1 Qué demuestra

| Elemento | Descripción |
| :--- | :--- |
| **Patrón** | P-01 — Secure Inference Gateway |
| **Sub-componentes** | Input Validator (D-04) · Output Controller: top-k limiting + rate limiting (D-02) · Response Signer Ed25519 (D-05) |
| **Integración con la Capa 1** | Al arrancar, `inference-gateway` descarga el modelo y su firma del mismo Model Registry de P-03 y verifica la firma cosign con la clave pública de la Capa 1 antes de cargarlo. Si la firma no es válida, el servicio termina con error crítico y nunca sirve el modelo. |
| **Cliente verificador** | `inference-client` ejecuta 4 casos contra `POST /v1/recommend`: `valid`, `invalid-input`, `rate-limit`, `tampered-response`. |

### 9.2 Servicios y archivos nuevos

```
services/
├── inference-gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                 # aplicación FastAPI, orquesta los 3 sub-componentes
│   ├── input_validator.py     # Sub-componente Input Validator (D-04)
│   ├── output_controller.py   # Sub-componente Output Controller (D-02)
│   ├── response_signer.py     # Sub-componente Response Signer (D-05)
│   └── README.md
└── inference-client/
    ├── Dockerfile
    ├── requirements.txt
    └── client_demo.py         # cliente verificador, 4 casos

scripts/
├── generate_response_keys.sh  # genera el par Ed25519 del Response Signer
└── run_layer2_demo.sh         # orquesta la demo completa de la Capa 2
```

### 9.3 Prerrequisitos adicionales

- Puerto adicional libre en la máquina anfitriona: `8080` (API del
  inference-gateway).
- Las claves de la Capa 1 (`keys/cosign.key`, `keys/cosign.pub`) deben
  existir antes de levantar el gateway (ver §5.2).

### 9.4 Cómo ejecutar la Capa 2

```bash
./scripts/generate_response_keys.sh
./scripts/run_layer2_demo.sh
```

`run_layer2_demo.sh` verifica las claves necesarias, levanta MinIO +
MLflow, entrena un modelo si no existe ninguno registrado (reutilizando
`trainer` de la Capa 1 sin modificarlo), levanta `inference-gateway` y
espera su healthcheck, y ejecuta los 4 casos del cliente en orden,
terminando con un resumen y saliendo con código 0 solo si los 4 casos
dieron el resultado esperado.

### 9.5 Manejo de errores esperado (Capa 2)

| Situación | Comportamiento |
| :--- | :--- |
| Firma del modelo inválida al arrancar el gateway | `app.py` termina el proceso con código de salida distinto de cero antes de exponer `/v1/recommend`; el contenedor queda en estado `exited` y `run_layer2_demo.sh` lo detecta y muestra los logs. |
| Faltan las claves Ed25519 de respuesta | `generate_response_keys.sh` y `run_layer2_demo.sh` verifican su existencia antes de continuar. |
| Candidato fuera de rango, tipo incorrecto o NaN/Inf | `input_validator.py` responde `422` con `{"error": "input_validation_failed", "details": [...]}`. |
| Más de 30 solicitudes/minuto (configurable) de un mismo `client_id` | `output_controller.py` responde `429` con `{"error": "rate_limit_exceeded"}`. |
| Respuesta alterada después de firmarse | La verificación Ed25519 en `client_demo.py` (o en cualquier consumidor) falla explícitamente; no hay forma de "arreglar" la firma sin la clave privada del Response Signer. |

### 9.6 Relación con el resto de la tesis

- **A4.4 §3.1 / §4.1** documentan los cambios concretos y el análisis de
  impacto de P-01 sobre RecoShop; esta capa los implementa para D-02,
  D-04 y D-05 (P-01 no cubre D-01, D-03, D-06 ni D-07).
- El rate limiting se justifica como control general de seguridad de API
  en microservicios (NIST SP 800-204), y el top-k limiting como Output
  Information Limiting (P-01, candidato A3) -- **no** como una
  implementación de AMAO (Jiang et al.), que cubre detección de consultas
  maliciosas y respuesta adaptativa y queda fuera de alcance de esta capa.
- Igual que en la Capa 1, la firma (aquí, Ed25519 sobre la respuesta)
  prueba integridad, no benignidad: un modelo legítimamente firmado y sin
  manipular puede seguir produciendo una recomendación de mala calidad;
  eso no es algo que el Response Signer esté diseñado para detectar.
