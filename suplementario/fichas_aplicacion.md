# Fichas de aplicación del método

Material suplementario de «Método para el diseño seguro de sistemas de machine learning basado en identificación de debilidades arquitectónicas». Hay una ficha por debilidad (D-01 a D-07) y una plantilla en blanco al final. Cada ficha recorre los cuatro pasos de uso del método (sección 2.1 y apertura del Capítulo 3) con cinco campos. Su contenido se deriva de las Tablas 2-1, A-2, 3-1, 3-2, 3-3, B-1 y B-2 del documento; los valores de severidad y de riesgo residual son los del caso RecoShop y sirven de referencia, no de resultado esperado en otro sistema.

## Cómo se completa una ficha

1. **Pregunta de localización.** Se responde sobre el diagrama de arquitectura del sistema: si la respuesta es afirmativa, se anota en qué componente se manifiesta la debilidad.
2. **Evidencia.** Se anota qué elemento del diagrama o de la configuración confirma la presencia (un flujo sin validador, una opción de configuración, una llamada sin verificación). Sin evidencia, la debilidad se marca como no presente.
3. **Severidad.** Se califica con la rúbrica de la Tabla 3-2: impacto (crítico, alto o medio) por probabilidad (baja, media o alta).
   - El impacto es *crítico* cuando el atacante controla el modelo servido en todo el sistema; *alto* cuando degrada, sesga o expone la recomendación o el modelo sin controlar el artefacto servido; y *medio* cuando altera respuestas individuales con daño acotado.
   - La probabilidad es *alta* si el componente es alcanzable desde el exterior y la explotación es de facilidad moderada o alta; *baja* si la explotación es difícil o exige una posición interna en la red; y *media* en los demás casos.
   - Una debilidad presente con un escenario concreto no se califica por debajo de Media.
4. **Patrón.** Se consulta la matriz (Tabla B-1): el patrón principal es el que tiene el subcomponente de la correspondencia directa; los refuerzos son los candidatos de soporte.
5. **Riesgo residual.** Se registra lo que el patrón deja sin cubrir y que el sistema debe aceptar o tratar aparte.

| Impacto \ Probabilidad | Baja | Media | Alta |
|---|---|---|---|
| Crítico | Alta | Crítica | Crítica |
| Alto | Media | Alta | Alta |
| Medio | Media | Media | Alta |

---

## D-01 Confianza implícita en el registro de modelos

1. **Pregunta de localización.** ¿El sistema da por sentado que el modelo guardado en el registro es el mismo que dejó el entrenamiento y lo despliega sin comprobarlo? Componentes donde buscar: registro de modelos (C6), integración y entrega continuas (C1) y servicio de inferencia (C8). Fase del ciclo de vida: posentrenamiento y predespliegue.
2. **Evidencia que confirma su presencia.** El entrenamiento escribe en el registro sin un intermediario de validación y el despliegue descarga el modelo sin verificar su firma ni una suma de verificación; la promoción depende del estado lógico del registro, no de una garantía criptográfica sobre el contenido.
3. **Severidad.** Genérica: Crítica / Alta, porque un compromiso del registro controla el modelo servido. En RecoShop: Crítica (impacto crítico × probabilidad media), con el despliegue automático de ArgoCD como agravante.
4. **Patrón principal, subcomponente y refuerzos.** P-03, Compuerta de Firma y Registro de Artefactos (correspondencias directas: I3 firma de artefactos e I9 registro inmutable). Refuerzos: familia S (control de acceso por atributos, confianza cero, mínimo privilegio, microsegmentación, auditoría, secretos) y firma de imágenes de contenedor (I8). El ML-BOM (I4) es parcial.
5. **Riesgo residual a registrar.** Bajo-Medio. Persiste si se compromete la clave de firma, si un actor legítimo aprueba un artefacto malicioso firmado o si quien controla el registro apunta producción a una versión anterior legítima.

## D-02 Exposición incontrolada en el punto de acceso de inferencia

1. **Pregunta de localización.** ¿La API del modelo responde con más información de la necesaria y sin vigilar quién pregunta ni cuánto? Componentes donde buscar: servicio de inferencia (C8), pasarela de API y flujo de posprocesamiento. Fase: inferencia.
2. **Evidencia que confirma su presencia.** La consulta sigue un flujo lineal (cliente, pasarela, servicio, modelo) sin un componente que limite la respuesta o registre la consulta; el contrato devuelve el vector completo de probabilidades (`probabilities`) en lugar de la clase predicha (`predicted_class`).
3. **Severidad.** Genérica: Alta, por ser la frontera pública de consulta. En RecoShop: Alta (impacto alto × probabilidad alta), con un competidor que emite unas 10.000 consultas sistemáticas y destila un modelo sustituto.
4. **Patrón principal, subcomponente y refuerzos.** P-01, Controlador de Información de Salida (correspondencias directas: F1 monitor adaptativo de consultas, F3 limitación de la información de salida; V4 figura como directa, pero no se incorporó como función propia, Tabla B-2). Refuerzos: control de acceso por atributos (S1) y marca de agua (F8).
5. **Riesgo residual a registrar.** Medio. Eleva el costo de una extracción, pero un atacante sostenido bajo los umbrales podría aproximar el modelo; depende de calibrar los umbrales con tráfico legítimo.

## D-03 Canal de retroalimentación no validado

1. **Pregunta de localización.** ¿El sistema se reentrena con lo que ocurre en producción y da por bueno todo lo que regresa? Componentes donde buscar: monitoreo (C9), integración y entrega continuas (C1), orquestación (C3), almacén de características (C4) y compuerta de promoción. Fase: monitoreo y reentrenamiento.
2. **Evidencia que confirma su presencia.** El monitoreo alimenta el lago de datos o el almacén de características sin validación; el reentrenamiento se dispara por tiempo o volumen y la promoción se decide solo por métricas de rendimiento.
3. **Severidad.** Genérica: Alta (insidiosa), porque el sesgado es gradual y el modelo envenenado se promueve en silencio. En RecoShop: Alta (impacto alto × probabilidad alta), con una red de programas automatizados que genera clics y compras falsos durante días.
4. **Patrón principal, subcomponente y refuerzos.** P-02, Guardián de Ingesta de Retroalimentación, Monitor de Deriva de Seguridad y Compuerta de Promoción del Modelo Reentrenado (correspondencias directas: I6 compuerta de validación estadística, I7 compuerta de reentrenamiento seguro, V1 monitor de deriva de seguridad). Refuerzos: firma del modelo reentrenado con P-03 y auditoría (S5).
5. **Riesgo residual a registrar.** Medio-Alto. La contaminación repartida en varios ciclos puede evadir la detección por lote.

## D-04 Ausencia de validación en la entrada de inferencia

1. **Pregunta de localización.** ¿El modelo recibe cualquier entrada que llegue desde afuera sin que nada la revise antes? Componentes donde buscar: servicio de inferencia (C8), flujo de preprocesamiento de inferencia y pasarela de API. Fase: inferencia.
2. **Evidencia que confirma su presencia.** La conexión entre el punto de entrada y el modelo es directa; el preprocesamiento reside en el contenedor del modelo, sin un proceso que aplique políticas de seguridad.
3. **Severidad.** Genérica: Alta, porque los ataques adversariales eluden controles de negocio. En RecoShop: Alta (impacto alto × probabilidad alta), con valores fuera de rango enviados para forzar salidas degeneradas.
4. **Patrón principal, subcomponente y refuerzos.** P-01, Validador de Entrada (correspondencia directa: F4 pasarela de validación de entrada). Refuerzos: entrenamiento adversarial (F5), línea base de comportamiento (V3) y confianza cero (S2).
5. **Riesgo residual a registrar.** Bajo-Medio. Bloquea entradas claramente fuera de distribución; persisten las perturbaciones sutiles.

## D-05 Canal de salida no asegurado

1. **Pregunta de localización.** Cuando el modelo entrega su predicción, ¿hay algo que garantice que llegue sin alteraciones a quien la recibe? Componentes donde buscar: servicio de inferencia (C8), flujo de posprocesamiento, pasarela de API y sistema consumidor. Fase: inferencia (posmodelo).
2. **Evidencia que confirma su presencia.** El flujo de salida figura como HTTP y el contrato no especifica firma; en la malla de servicios, `PeerAuthentication` no está en modo `STRICT`.
3. **Severidad.** Genérica: Alta, porque la red no es de confianza. En RecoShop: Media (impacto medio × probabilidad baja), porque exige un atacante interpuesto (*Man-in-the-Middle*) dentro del clúster.
4. **Patrón principal, subcomponente y refuerzos.** P-01, Protector del Canal de Salida (correspondencias directas: F7 integridad del canal de salida con mTLS y S2 confianza cero, esta última como soporte). Refuerzos: control de acceso por atributos (S1), microsegmentación (S4) y auditoría (S5).
5. **Riesgo residual a registrar.** Bajo. Un atacante interpuesto interno que altere la respuesta es detectable; persiste si se exfiltra la clave privada del pod, si el consumidor no verifica la firma o si se reutiliza una respuesta firmada anterior, porque la firma no liga la respuesta a la solicitud ni al instante.

## D-06 Confianza implícita en modelos preentrenados

1. **Pregunta de localización.** ¿Se parte de un modelo descargado de un repositorio público y se lo adapta sin comprobar que no traiga una puerta trasera (*backdoor*)? Componentes donde buscar: infraestructura de entrenamiento (C5), repositorio de código fuente (C2), orquestación (C3) y registro de modelos (C6). Fase: entrenamiento (ajuste fino).
2. **Evidencia que confirma su presencia.** Una flecha va del repositorio externo al entrenamiento sin validador; el código usa `from_pretrained(...)` sin resumen de verificación ni escaneo previo.
3. **Severidad.** Genérica: Alta, porque un modelo base malicioso compromete todos sus derivados con poco esfuerzo. En RecoShop: Alta (impacto crítico × probabilidad baja), con un repositorio comprometido o un nombre suplantado (*typosquatting*).
4. **Patrón principal, subcomponente y refuerzos.** P-03, Validador de Modelos Externos (correspondencias directas: I5 validación de modelos preentrenados, I4 ML-BOM). Refuerzos: aislamiento entre entrenamiento y servicio (I2), mínimo privilegio (S3), microsegmentación (S4) y secretos (S6). La firma de artefactos (I3) es parcial.
5. **Riesgo residual a registrar.** Medio-Alto. La detección de puertas traseras funcionales es un área de investigación activa; una de activación estrecha podría evadir el conjunto canónico de seguridad.

## D-07 Ausencia de controles en la ingesta de datos

1. **Pregunta de localización.** ¿Los datos con los que se entrena el modelo entran al sistema sin comprobar que no fueron alterados ni de dónde vienen? Componentes donde buscar: fuentes externas, lago de datos, flujo de preprocesamiento y almacén de características (C4). Fase: entrenamiento (ingesta de datos).
2. **Evidencia que confirma su presencia.** Las fuentes externas llegan al lago de datos sin un componente de validación; los trabajos de ingesta no verifican sumas ni distribuciones ni registran metadatos de procedencia.
3. **Severidad.** Genérica: Alta, porque el envenenamiento de datos es una amenaza documentada como crítica. En RecoShop: Alta (impacto alto × probabilidad media), con registros sintéticos inyectados en la fuente.
4. **Patrón principal, subcomponente y refuerzos.** P-03, Compuerta de Procedencia de Datos para la ingesta primaria, y P-02, Guardián de Ingesta de Retroalimentación para la variante de retroalimentación (correspondencia directa: I6 compuerta de validación estadística). Refuerzos: aislamiento entre entrenamiento y servicio (I2) y auditoría (S5). El seguimiento de procedencia (I1), el ML-BOM (I4) y el monitor de deriva (V1) son parciales.
5. **Riesgo residual a registrar.** Bajo-Medio. La validación estadística básica detecta anomalías graves y violaciones del resumen o del esquema, pero un envenenamiento que imite la distribución legítima podría superarla.

---

## Plantilla en blanco

**Debilidad:** D-__ ______________________________  **Sistema:** ______________________  **Fecha:** ____________

1. **Pregunta de localización.** ¿Está presente la debilidad en el sistema? ☐ Sí ☐ No. Componente(s) donde se manifiesta:

2. **Evidencia que confirma su presencia** (flujo, diagrama o configuración):

3. **Severidad.** Impacto: ☐ Crítico ☐ Alto ☐ Medio. Probabilidad: ☐ Baja ☐ Media ☐ Alta. Severidad según la Tabla 3-2: ______

4. **Patrón principal, subcomponente y refuerzos** (Tabla B-1):

5. **Riesgo residual a registrar:**
