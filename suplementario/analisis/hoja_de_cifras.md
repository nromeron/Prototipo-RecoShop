# Hoja de cifras — cierre de la Capa 3 (ji cuadrado) y recaptura

Fuente de cada cifra: las bitácoras de `evidence/` (revisión de evidencia) y los archivos de esta carpeta. La captura anterior es la del 21 de octubre de 2026 (código `f36f52f`, evidencia hasta `adadab9`).

## 1. Revisiones, fecha y entorno

| Concepto | Valor |
|---|---|
| Revisión de partida | `adadab9` |
| Código de la captura | `3188db7` (Capa 3: la señal de categoría exige una prueba ji cuadrado frente a la línea base) |
| Evidencia | `6502292` (recaptura) |
| Análisis | `484505b` (tasas en 500 semillas, dosis-respuesta y esta hoja) |
| Entrega | `0deb498` (fichas de aplicación, debilidades candidatas y figuras) |
| Fecha y ventana de la captura | 14 de noviembre de 2026, 23:37:28–23:45:45 UTC |
| Docker Engine / Compose | 29.8.2 / 5.6.0 (anterior: 29.8.2 / 5.5.1) |
| SHA-256 de `evidence/MANIFEST.sha256` | `34c1a833cf66437f2b8dfa077e9c98c14697ea8eebf2bcad5e041391a1531da5` |
| Resultado | 15 de 15 demostraciones con código 0; `sha256sum -c MANIFEST.sha256`: 15 OK |

Imágenes de la captura:

| Imagen | ID | Origen |
|---|---|---|
| `recoshop-prototype-trainer` | `435460b6e5fb` | PC original (misma de la captura anterior) |
| `recoshop-prototype-mlflow` | `6c81f2d724b5` | PC original |
| `recoshop-prototype-deployment-gate` | `33bc87fb0d9a` | PC original |
| `recoshop-prototype-inference-gateway` | `3d25a6929882` | PC original |
| `recoshop-prototype-inference-client` | `51848ce476ff` | PC original |
| `recoshop-prototype-feedback-gate` | `db5c5797f1ae` | reconstruida con el cambio (anterior: `c25777ca94f9`) |
| `minio/minio:RELEASE.2024-01-16T16-07-38Z`, `minio/mc:RELEASE.2024-01-13T08-44-48Z` | — | PC original (`docker save`/`docker load`) |

Condiciones del entorno (la captura se hizo en un PC distinto al original; ninguna cambia código):

- **Imágenes del PC original.** Docker Hub ya no sirve `minio/mc:RELEASE.2024-01-13T08-44-48Z` ("pull access denied"), y la imagen `mlflow` construida hoy no arranca: `services/mlflow/Dockerfile` fija `mlflow==2.9.2` y `boto3==1.34.51`, pero no SQLAlchemy, y la versión actual ya no trae `FallbackAsyncAdaptedQueuePool`. Se cargaron las imágenes exportadas del PC original (los ID coinciden con los encabezados de la captura anterior).
- **`trainer` con cuatro hilos.** LightGBM 4.3 (`n_jobs=None`) escribe `num_threads` = núcleos físicos en el archivo del modelo, y ese valor entra en el SHA-256. La captura anterior se hizo con 4; este PC usa 6 por defecto. Diagnóstico: con `n_jobs` de 1 a 32, los 33 archivos de modelo son idénticos salvo la línea `[num_threads: N]`, y `n_jobs=4` da `a4fb6634…`. Se fijó `LOKY_MAX_CPU_COUNT=4` para el servicio `trainer` con un archivo de override fuera del repositorio (`COMPOSE_FILE` en `.env`, que no se versiona).
- **`feedback-gate` reconstruida.** Los pines (numpy 1.26.3, scipy 1.11.4, pandas 2.1.4, mlflow 2.9.2, boto3 1.34.51) no cambian; 15 dependencias transitivas suben de parche o menor (entre ellas SQLAlchemy 2.1.4 → 2.1.8, pillow 12.3.0 → 13.0.0, threadpoolctl 3.7.0 → 3.8.0). Ninguna interviene en el cálculo de la compuerta.
- `COMPOSE_PROJECT_NAME=recoshop-prototype` en `.env`, para que las imágenes se llamen como en la captura anterior.

## 2. Puerta de reproducibilidad

Código sin modificar (`adadab9`), con las condiciones de la sección 1. La recaptura del paso 5 (`3188db7`) da los mismos catorce valores.

| Artefacto (`RESUMENES.md`) | Valor anterior | Valor nuevo | ¿Coincide? |
|---|---|---|---|
| Modelo de referencia (semilla 42) | `a4fb66346a9e3d0bad3b1c3dc19a12aa0e06b03adf903d9ab088417ba62fd00c` | `a4fb66346a9e3d0bad3b1c3dc19a12aa0e06b03adf903d9ab088417ba62fd00c` | sí |
| Conjunto de datos de la semilla 42 | `afbdc928189dc8ff70831d38bdefb954b035c029318880f2fd78acc830c82c7d` | `afbdc928189dc8ff70831d38bdefb954b035c029318880f2fd78acc830c82c7d` | sí |
| Modelo de la semilla 7 | `1e590f096c455109c36b7a22152e31468dad1e0fa9589d1131f262f7e982eb16` | `1e590f096c455109c36b7a22152e31468dad1e0fa9589d1131f262f7e982eb16` | sí |
| Conjunto de datos de la semilla 7 | `cc773bd8a743be97f88bb39086caf3a17c2f1064dbbbc5897c9437d74ef86906` | `cc773bd8a743be97f88bb39086caf3a17c2f1064dbbbc5897c9437d74ef86906` | sí |
| Modelo con bytes alterados | `08bb7e3f5e6e234238bd2bde71b7a6eb386ee51ca9d9c95a81f329113c924c66` | `08bb7e3f5e6e234238bd2bde71b7a6eb386ee51ca9d9c95a81f329113c924c66` | sí |
| Lote alterado tras la firma del socio | `342b4d7ac76beed27c50dfcd2994da61da4a70d55656a124f0a677365b6c9853` | `342b4d7ac76beed27c50dfcd2994da61da4a70d55656a124f0a677365b6c9853` | sí |
| Lote de la fuente suplantada y del socio comprometido | `04a2770a48774585c3d8fba0a5cabac59a7d55da368d38782fd0c13cb55ffb0e` | `04a2770a48774585c3d8fba0a5cabac59a7d55da368d38782fd0c13cb55ffb0e` | sí |
| Modelo base legítimo | `1cc7d536969e5d058f39baef6ebe3a5f75d2761d155079619cd4e9f10968ca83` | `1cc7d536969e5d058f39baef6ebe3a5f75d2761d155079619cd4e9f10968ca83` | sí |
| Modelo base con puerta trasera | `a923575e9b4932e069c1a99b111a4919973117e522824a661ec8728b2be0c212` | `a923575e9b4932e069c1a99b111a4919973117e522824a661ec8728b2be0c212` | sí |
| Pickle con ejecución de código | `b0b2782cd600850ed9f3a06e96c5c2f639b4aa2caa362d3042af42b02ea130e1` | `b0b2782cd600850ed9f3a06e96c5c2f639b4aa2caa362d3042af42b02ea130e1` | sí |
| Conjunto canónico de seguridad | `642ff2d0f48c2b124c1319c08c7ba8c983e5e6089589df39f6c1f8dfba9260ce` | `642ff2d0f48c2b124c1319c08c7ba8c983e5e6089589df39f6c1f8dfba9260ce` | sí |
| Candidato con retroalimentación limpia | `d5dd1a5182fb14aaeaaebd15e7197d8f76c69b0edab2299053ab799bb84ecd0f` | `d5dd1a5182fb14aaeaaebd15e7197d8f76c69b0edab2299053ab799bb84ecd0f` | sí |
| Candidato con retroalimentación envenenada | `a42ca30aec2fcf6eed6d8421923f60b90fd20b64cd1f401f92757cab5bbdc0dc` | `a42ca30aec2fcf6eed6d8421923f60b90fd20b64cd1f401f92757cab5bbdc0dc` | sí |
| Modelo promovido, alterado tras su firma | `000702b39267ae3160259bb710de436b0e1f1f6df7226072e259f9add263c88b` | `000702b39267ae3160259bb710de436b0e1f1f6df7226072e259f9add263c88b` | sí |

Métricas: NDCG@10 de los modelos base 0,8751 (legítimo) y 0,8734 (con puerta trasera), igual que antes. `capa3_compuerta_promocion.log` coincide línea por línea (NDCG@10 global del vigente 0,8737; candidato limpio 0,8788, delta +0,0051; candidato envenenado 0,8702, delta −0,0035; categoría 3 del envenenado −0,0749, degradación selectiva).

Intentos previos de la puerta en este PC (no forman parte de la evidencia): con las imágenes construidas aquí fallaron diez demostraciones (MinIO no descargable; después, MLflow sin arrancar), y con seis hilos los modelos daban `c329c639…` (referencia), `c605cf88…` (limpio) y `3996d0a3…` (envenenado), con las mismas métricas.

## 3. Tabla 4-7 (semilla 42, amplitud calibrada)

| Lote | Características marcadas por KS (estadístico) | Categorías significativas | Concentración por categoría | Ji cuadrado (estadístico; p) | Concentración temporal | Delta de etiquetas | Decisión |
|---|---|---|---|---|---|---|---|
| Limpio | ninguna (máx.: category 0,0338) | 0 | 0,4516 (top 5) | 7,1425; 0,4142 | 0,5714 | 0,0324 | ACEPTADO (0) |
| Deriva natural | price 0,0598; product_popularity 0,0846 | 4 | 0,3542 (top 7) | 7,5335; 0,3755 | 0,4138 | 0,0310 | ACEPTADO_CON_ALERTA (3) |
| Adversarial | category 0,0956 | 1 | 1,0000 (top 3) | 226,8406; 2,328·10⁻⁴⁵ | 0,5523 | 0,1149 (cat. 3) | CUARENTENA (4) |

Reglas:

- Limpio: «El Guardian de Ingesta no detectó drift global significativo.»
- Deriva natural: «El Guardian detectó drift global, pero el Monitor de Drift de Seguridad no encontró concentración por categoría/tiempo ni manipulación de etiquetas: el patrón es compatible con drift natural (difuso).»
- Adversarial: «El Guardian detectó drift global Y el Monitor de Drift de Seguridad detectó un patrón concentrado: concentración por categoría (1.000 >= 0.6) con ji cuadrado significativo (chi2=226.84, p=2.33e-45 < 0.01), categoría más afectada=3; manipulación de etiquetas (delta=0.115 >= 0.06), categoría=3»

## 4. Tabla 4-8 (veredictos por semilla)

| Semilla | Calibrada: limpio / natural / adversarial | Baja: limpio / natural / adversarial |
|---|---|---|
| 7 | 0 / 3 / 4 | 0 / 3 / 4 |
| 13 | 0 / 3 / 4 | 0 / 0 / 4 |
| 42 | 0 / 3 / 4 | 0 / 3 / 4 |
| 101 | 0 / 3 / 4 | 0 / 3 / 4 |
| 777 | 0 / 3 / 4 | 0 / 0 / 4 |
| 2026 | 0 / 3 / 4 | 0 / 0 / 4 |

Amplitud calibrada: precio +9 %, popularidad +0,06. Baja: +5 %, +0,03. Sin cambios respecto de la captura anterior.

## 5. Tasas en 500 semillas (0 a 499)

Aceptado / alerta / cuarentena, en % de las semillas. Medido en el contenedor `feedback-gate` con las versiones fijadas, con `tasas_monitor_semillas.py`; filas por lote en `tasas_500_semillas_antes.csv` y `tasas_500_semillas_despues.csv`.

| Amplitud | Lote | Antes | Después |
|---|---|---|---|
| Calibrada | limpio | 86,6 / 10,2 / 3,2 | 86,6 / 13,0 / 0,4 |
| Calibrada | natural | 0 / 79,6 / 20,4 | 0 / 97,8 / 2,2 |
| Calibrada | adversarial | 0 / 0 / 100 | 0 / 0 / 100 |
| Baja | limpio | 86,6 / 10,2 / 3,2 | 86,6 / 13,0 / 0,4 |
| Baja | natural | 30,2 / 57,4 / 12,4 | 30,2 / 68,4 / 1,4 |
| Baja | adversarial | 0 / 0 / 100 | 0 / 0 / 100 |

Criterio de aceptación (fijado antes de ejecutar, amplitud calibrada): adversarial en cuarentena ≥ 99 % → 100 %; natural ≤ 5 % → 2,2 %; limpio ≤ 1 % → 0,4 %; Tabla 4-8 sin cambios → sí. **Se cumple.**

El CSV «antes» se generó con la versión del guion que llama a `monitor_concentration_index_category(lote)` (firma anterior), por eso sus columnas de ji cuadrado están vacías; la versión de esta carpeta usa la firma nueva.

## 6. Dosis-respuesta de la Compuerta de Promoción

`promotion_gate.py --monitor-signal none`, semillas de retroalimentación 3000 a 3019, tolerancia global 0,02 y degradación máxima por subpoblación 0,03. Filas en `dosis_respuesta_promocion.csv`, generado por `dosis_respuesta_promocion.sh`.

| Fracción envenenada | Retenidas (exit 4) de 20 | Mediana del delta de la categoría 3 |
|---|---|---|
| 0,1 | 0 | +0,0069 |
| 0,2 | 0 | +0,0031 |
| 0,3 | 2 | −0,0107 |
| 0,4 | 8 | −0,0288 |
| 0,5 | 18 | −0,0454 |
| 0,6 | 20 | −0,0680 |
| Limpia | 0 | +0,0045 |

Todas las retenciones se deben a la degradación selectiva (delta de la categoría 3 < −0,03); el delta global no supera la tolerancia en ninguna ejecución. El delta de la categoría 3 es una exactitud por pares sobre 1.442 pares, así que avanza en pasos de 1/1.442 ≈ 0,000693.

## 7. Tamaños

Calculados con las funciones de `promotion_gate.py` en el contenedor `trainer` (semilla 42 para el corpus; semilla 500 de retroalimentación, la de la evidencia).

| Conjunto | Filas | Sesiones |
|---|---|---|
| Corpus (semilla 42) | 3.916 | 300 |
| Entrenamiento | 3.152 | 240 |
| Evaluación | 764 | 60 |
| Retroalimentación (300 sesiones, limpia o envenenada) | 4.011 | 300 |
| Reentrenamiento (entrenamiento + retroalimentación) | 7.163 | 540 |
| Conjunto canónico de seguridad (semillas 9001–9005) | 19.617 | 1.500 |

Capa 3: línea base de 5.000 filas y lotes de 1.000 filas. Lote de la fuente suplantada y del socio comprometido: 4.307 filas.

## 8. Diferencias con la captura anterior

Cifras de la Capa 3 (cambian por el código):

| Bitácora | Valor anterior | Valor nuevo |
|---|---|---|
| `capa3_demo_semilla42` | — | ji cuadrado del lote limpio: 7,1425; p = 0,4142; no significativo |
| `capa3_demo_semilla42` | — | ji cuadrado del lote natural: 7,5335; p = 0,3755; no significativo |
| `capa3_demo_semilla42`, `integracion_tres_capas` | — | ji cuadrado del lote adversarial: 226,8406; p = 2,328·10⁻⁴⁵; significativo |
| `capa3_demo_semilla42`, `integracion_tres_capas` | regla sin ji cuadrado | regla con «con ji cuadrado significativo (chi2=226.84, p=2.33e-45 < 0.01)» |
| `capa3_demo_semilla42` (`reason.json`) | — | umbral `CATEGORY_CHI2_ALPHA`: 0,01; métricas `chi2_statistic`, `chi2_p_value`, `chi2_significant` |
| `integracion_tres_capas` | — | ji cuadrado del lote limpio del ciclo: 7,1425; p = 0,4142 |
| `capa3_sensibilidad_6semillas` | «determinismo confirmado en las 6 semillas» | «los 18 veredictos coinciden en las 6 semillas» |

Los veredictos no cambian en ninguna bitácora.

Versiones del registro (MLflow empezó vacío en este PC):

| Bitácora | Anterior | Nueva |
|---|---|---|
| `capa1_caso_positivo` | 71 | 14 |
| `capa1_caso_negativo_append` | 72 | 15 |
| `capa1_caso_negativo_swap_signed` | 73, 74 | 16, 17 |
| `capa1_caso_negativo_reversion` | 75, 76 | 18, 19 |
| `capa2_demo_8casos` | 77 | 20 |
| `capa2_arranque_sustitucion_firmada` | 78, 79 | 21, 22 |
| `capa2_arranque_reversion` | 80, 81 | 23, 24 |
| `integracion_tres_capas` | 82, 83 (vigente 82, registrada 83) | 25, 26 (vigente 25, registrada 26) |

Fechas e identificadores: cambian las fechas de los encabezados y de los registros (`*_at_utc`, MLflow), los identificadores de ejecución de MLflow, los identificadores de ciclo (`e2e-*-20261114T234425Z`), las rutas temporales, los identificadores de contenedor, el puerto de origen de una línea `GET /health` y los resúmenes de los ML-BOM, que cambian en cada ejecución porque llevan número de serie y marca de tiempo. En el encabezado cambian el commit, la versión de Compose (5.5.1 → 5.6.0) y el ID de `feedback-gate`.

Archivos de `evidence/` actualizados a mano, como en `819a234`: `RESUMENES.md` (fecha, ventana, revisión y un párrafo sobre las condiciones del entorno), `reason_capa3_adversarial_semilla42.json` (bloque impreso en `capa3_demo_semilla42.log`) y `mlbom_modelo_promovido.cdx.json` (artefacto de MLflow de la versión 26, SHA-256 `ae5caf3aa1f1127f175b32238e4198ae27c254019b50e987025038bcaeb4db77`, igual al de la bitácora; declara el modelo `d5dd1a51…`).
