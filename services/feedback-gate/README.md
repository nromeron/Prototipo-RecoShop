# Capa 3 — P-02 Secure Retraining Gate

Implementación funcional del patrón **P-02 — Secure Retraining Gate**,
mitigando **D-03** (Canal de Retroalimentación No Validado) y, de forma
complementaria, la variante feedback de **D-07**, sobre el caso de
estudio RecoShop. Ver secciones 3.4 y 4.4 de la tesis.

## Dos sub-componentes, explícitamente distinguidos

| Sub-componente | Función | Archivo |
| :--- | :--- | :--- |
| **1 — Guardian de Ingesta** | Validación estadística del lote de feedback contra un baseline: KS test global por feature. Responde "¿hay drift, en absoluto?" | `feedback_gate.py`, funciones `guardian_*` |
| **2 — Monitor de Drift de Seguridad** (versión mínima) | Distingue drift natural (difuso) de drift adversarial (concentrado): KS por segmento, índices de concentración por categoría y por tiempo, señal de manipulación de etiquetas. Responde "si hay drift, ¿es un ataque?" | `feedback_gate.py`, funciones `monitor_*` |

## Declaración de honestidad metodológica (léase antes de citar esto como validación)

Esta es una instanciación **parcial** y con **datos sintéticos** del
Sub-componente 2. El Monitor de Drift de Seguridad es, según el catálogo
de patrones de la tesis, una **contribución original** (validación
**Nivel 4**: sin precedente directo en el corpus revisado). Este
prototipo demuestra que el mecanismo es computacionalmente viable y que
distingue los tres escenarios sintéticos generados por
`generate_feedback.py`, pero el Monitor **completo** —calibrado con
distribuciones reales de tráfico, estacionalidad genuina y patrones de
ataque no conocidos de antemano— requiere datos de producción que quedan
fuera del alcance de este prototipo.

Los umbrales de decisión (ver `.env.example` / variables de entorno) están
**calibrados empíricamente contra los tres escenarios sintéticos**
generados por `generate_feedback.py`, no validados contra tráfico real.
Ningún umbral está codificado sin su correspondiente variable de entorno.

## Los tres escenarios y el resultado esperado

| Escenario | Descripción | Decisión esperada | Exit code |
| :--- | :--- | :--- | :---: |
| `batch_clean.csv` | Misma distribución que el baseline. | ACEPTADO | 0 |
| `batch_natural_drift.csv` | Todas las categorías se desplazan por igual, de forma pequeña y creciente con `time_window` (difuso). | ACEPTADO_CON_ALERTA | 3 |
| `batch_adversarial.csv` | 20% del lote concentrado en una categoría y dos ventanas temporales contiguas, con relevancia inflada para un conjunto pequeño de productos objetivo (escenario de explotación de D-03, sección 3.2 de la tesis). | CUARENTENA | 4 |

Un cuarto código de salida, **2**, indica un **error de infraestructura**
(archivo no encontrado, CSV malformado) y debe distinguirse siempre de una
decisión del gate — `scripts/run_layer3_demo.sh` hace esta distinción
explícitamente.

## Alcance y limitaciones

- **Datos enteramente sintéticos**: ni el baseline ni los lotes provienen
  de tráfico real de RecoShop; los tres escenarios fueron diseñados para
  ser distinguibles por el gate, no extraídos de producción.
- **Sin dependencia de MLflow por defecto**: esta capa no necesita el
  Model Registry para su demostración. El registro opcional de la
  decisión como run de MLflow (`LOG_TO_MLFLOW=true`) es un añadido, no un
  requisito.
- **Umbrales calibrados para el prototipo**: ver la declaración de
  honestidad metodológica arriba. No deben interpretarse como valores
  recomendados para un despliegue real sin recalibración contra tráfico
  de producción.
- **Sin intervención humana**: el catálogo de patrones prevé una vía de
  escalamiento a revisión humana para casos ambiguos (ver Anexo C de la tesis);
  este prototipo solo implementa la decisión automática de tres vías
  (aceptar / alertar / cuarentena), no el flujo de escalamiento humano.

## Archivos

- `generate_feedback.py`: genera el baseline (5000 filas) y los tres
  lotes (1000 filas cada uno) con semilla fija (reproducible).
- `feedback_gate.py`: CLI `python feedback_gate.py --batch <ruta>`,
  implementa el Guardian y el Monitor, decide, e imprime siempre una
  tabla-resumen de las métricas y la regla que decidió.
- `scripts/run_layer3_demo.sh`: el experimento DSR completo -- genera los
  datos, evalúa los tres lotes en orden, valida que los exit codes sean
  exactamente 0/3/4, y muestra el `reason.json` de la cuarentena como
  evidencia.
