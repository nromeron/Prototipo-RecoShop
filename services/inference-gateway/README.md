# Capa 2 — P-01 Secure Inference Gateway

Implementación funcional del patrón **P-01 — Secure Inference Gateway**,
mitigando las debilidades **D-02** (extracción del modelo), **D-04**
(entradas adversariales) y **D-05** (integridad de la respuesta), sobre el
caso de estudio RecoShop. Ver secciones 3.4 y 4.3 de la tesis.

## Sub-componentes

| Archivo | Sub-componente de P-01 | Debilidad mitigada |
| :--- | :--- | :--- |
| `input_validator.py` | Validador de Entrada (esquema Pandera: rangos, tipos, ausencia de NaN/Inf, 1-100 candidatos) | D-04 |
| `output_controller.py` | Controlador de Información de Salida: top-k limiting (Output Information Limiting, P-01 candidato F3) + rate limiting (control general de seguridad de API en microservicios, NIST SP 800-204) | D-02 |
| `response_signer.py` | Protector del Canal de Salida (firma Ed25519 del JSON canónico de la respuesta) | D-05 |
| `app.py` | Orquesta los tres sub-componentes sobre `POST /v1/recommend` | D-02, D-04, D-05 |

## Punto de integración con la Capa 1 (P-03)

Al arrancar, `app.py` **no confía en ningún artefacto local**: descarga la
última versión registrada del modelo y su firma directamente del Model
Registry (MLflow + MinIO, el mismo registry de la Capa 1), y verifica la
firma con `cosign verify-blob` usando la clave pública de la Capa 1
(`COSIGN_PUB_PATH`) **antes** de cargar el modelo con
`lightgbm.Booster(...)`. Si la verificación falla, el proceso termina con
un código de salida distinto de cero: el gateway nunca sirve un modelo no
verificado.

## Alcance y limitaciones (léase antes de ejecutar)

- **Rate limiting en memoria**: el estado del token bucket vive en un
  diccionario Python dentro del proceso. Es una simplificación
  deliberada de prototipo; un despliegue con múltiples réplicas del
  gateway requeriría un almacén compartido (Redis) o un componente
  dedicado de API gateway (Envoy/Istio, Kong).
- **Claves en archivo plano**: tanto la clave pública cosign como la
  clave privada Ed25519 del Protector del Canal de Salida se montan como archivos PEM
  de solo lectura (`./keys:/keys:ro`). En producción, ambas deberían
  gestionarse con un KMS, no como archivos en disco.
- **Sin KServe ni Istio**: este gateway corre como un servicio FastAPI
  simple sobre Docker Compose, no como un sidecar o Transformer dentro de
  un pod de KServe con mTLS de Istio. Reproduce la *lógica* de los tres
  sub-componentes de P-01, no la topología completa de Kubernetes
  descrita en las secciones 3.1 y 3.4.
- **AMAO no implementado**: el rate limiting de esta capa es un control
  general de seguridad de API (NIST SP 800-204), no una implementación
  de AMAO (Jiang et al.) -- AMAO cubre detección de consultas
  maliciosas y respuesta adaptativa por patrón de consulta, lo cual
  queda fuera de alcance de esta capa y se deja como trabajo futuro.
- **Firma de integridad, no de benignidad**: igual que en la Capa 1, la
  firma cosign del modelo prueba que el artefacto no cambió después de
  firmarse, no que su contenido sea inofensivo.

## Servicios relacionados

- `services/inference-client/`: cliente verificador de referencia
  (`client_demo.py`), con cuatro casos de demostración.
- `scripts/generate_response_keys.sh`: genera el par de claves Ed25519
  del Protector del Canal de Salida.
- `scripts/run_layer2_demo.sh`: orquesta la demostración completa de
  esta capa.
