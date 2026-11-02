# Inventario de los 27 patrones candidatos

Material suplementario de la tesis «Método para el diseño seguro de sistemas de machine learning basado en identificación de debilidades arquitectónicas» (Anexo B).

| Código | Candidato | Mecanismo | Fundamento | Aplicabilidad |
|---|---|---|---|---|
| F1 | Adaptive Query Monitor | Monitor con estado que analiza los patrones de consulta por cliente (frecuencia, diversidad, repetición, cambios de distribución) para detectar sondeo (*probing*), extracción o abuso de la API | Jiang et al. (2024), AMAO; OWASP | Sí |
| F2 | Adaptive Rate Limiting | Limitación dinámica de la tasa de solicitudes según identidad, reputación, volumen, patrón de consulta y sensibilidad del punto de acceso | Chandramouli (2019), limitación de tasa como función central de seguridad en microservicios; Chandramouli et al. (2021), como apoyo al control de acceso entre servicios | Parcial |
| F3 | Output Information Limiting | Reducción deliberada de la información devuelta: k clases principales, supresión de puntuaciones completas, redondeo, truncamiento o ruido calibrado | OWASP; Papernot | Parcial |
| F4 | Input Validation Gateway | Capa previa al modelo que valida formato, tipo, rango, esquema, distribución y propiedades básicas de la entrada antes de invocar la inferencia | OWASP; Papernot | Parcial |
| F5 | Adversarial Training | Entrenamiento con ejemplos adversariales para aumentar la robustez ante perturbaciones de la entrada | Papernot | Parcial |
| F6 | Output Noise / Privacy-Preserving Response | Ruido, redondeo o perturbación controlada de puntuaciones o respuestas para reducir la filtración de información sensible | Papernot; OWASP | Parcial |
| F7 | Output Channel Integrity (mTLS) | Protección del canal entre la inferencia y el consumidor mediante autenticación mutua TLS (mTLS), identidad de servicio y cifrado en tránsito | Chandramouli et al. (2021) | Parcial |
| F8 | Ownership Verification / Model Watermarking | Verificación de la propiedad del modelo mediante marcas o respuestas verificables en condiciones controladas | OWASP; fundamento conceptual en técnicas de verificación de propiedad de modelos | Parcial |
| I1 | Data Provenance Tracking | Trazabilidad del origen, las transformaciones, los responsables, las versiones y el linaje de los conjuntos de datos de entrenamiento y reentrenamiento | Kreuzberger et al. (2023); Lewis et al. (2021); Shorov et al. (2025) | Parcial |
| I2 | Training-Serving Isolation | Separación de redes, identidades, credenciales, permisos y entorno de ejecución entre entrenamiento, ajuste fino y servicio de inferencia | Chandramouli et al. (2021); Lewis et al. (2021) | Parcial |
| I3 | Model Artifact Signing | Firma criptográfica de los artefactos del modelo al registrarlos y verificación obligatoria antes del despliegue | Shorov et al. (2025), Sigstore y SLSA | Sí |
| I4 | ML-SBOM / AI-BOM | Inventario estructurado de dependencias de ML (modelos base, conjuntos de datos, bibliotecas, contenedores, marcos, resúmenes, licencias y versiones); práctica emergente | Shorov et al. (2025), Sigstore y SLSA; prácticas emergentes de SBOM para IA y ML | Parcial |
| I5 | Pre-trained Model Validation | Validación de modelos externos antes de su uso: procedencia o firma, evaluación en un entorno aislado (*sandbox*), pruebas de comportamiento y búsqueda de puertas traseras | OWASP; Shorov et al. (2025); literatura de detección de puertas traseras | Parcial |
| I6 | Statistical Data Validation Gate | Validación estadística de los lotes de datos antes del entrenamiento o reentrenamiento: esquema, distribución, valores atípicos y deriva (*drift*) | Kreuzberger et al. (2023); Lewis et al. (2021); OWASP | Parcial |
| I7 | Secure Retraining Gate | Compuerta entre producción o retroalimentación y reentrenamiento que valida la seguridad del corpus antes de permitir la actualización del modelo | Propuesta de este trabajo, derivada de OWASP (ML08), Kreuzberger et al. (2023) y Lewis et al. (2021) | No (propuesta) |
| I8 | Container Image Scanning & Signing | Escaneo, firma y verificación de las imágenes que empaquetan modelos, dependencias y entorno de ejecución antes del despliegue | Shorov et al. (2025), Sigstore y SLSA | Sí |
| I9 | Immutable Model Registry | Registro de modelos con versionado de solo anexado (*append-only*), auditoría, control de cambios y prohibición de sobrescribir artefactos | OWASP; Shorov et al. (2025); prácticas MLOps de versionado | Parcial |
| S1 | ABAC en Service Mesh para ML | Autorización basada en atributos de servicio, rol, operación, entorno, versión del modelo y sensibilidad del conjunto de datos | Chandramouli et al. (2021) | Parcial |
| S2 | Zero Trust entre componentes ML | Eliminación de la confianza implícita entre componentes de MLOps: autenticación, autorización y verificación continua entre servicios | Chandramouli et al. (2021); principios de identidad, autorización y segmentación entre microservicios | Parcial |
| S3 | Least Privilege para workloads ML | Permisos mínimos para los trabajos de entrenamiento y servicio, la integración y entrega continuas, el registro, el almacén de características y los flujos | Chandramouli et al. (2021); Rahman et al. (2025), como evidencia de riesgo operacional en infraestructura de ML | Parcial |
| S4 | Microsegmentación de red ML | Zonas de red separadas para entrenamiento, servicio, registro, datos, monitoreo y cadena de suministro | Chandramouli et al. (2021) | Parcial |
| S5 | Audit Trail inmutable | Registro inmutable de las operaciones críticas (registro de modelos, promoción, despliegue, cambios de datos, firmas, accesos); apoya la detección y el análisis forense, pero no previene por sí solo | Shorov et al. (2025); prácticas de auditoría y trazabilidad | Parcial |
| S6 | Secrets Management para pipelines ML | Gestión centralizada de secretos, tokens, credenciales de repositorios, claves de firma y credenciales de servicios de MLOps | Shorov et al. (2025); Chandramouli et al. (2021) | Parcial |
| V1 | Security Drift Monitor | Monitor que diferencia la deriva funcional esperada de señales compatibles con degradación adversarial o con manipulación progresiva del ciclo de retroalimentación | Propuesta de este trabajo, derivada de la monitorabilidad en Lewis et al. (2021) y de ML08 en OWASP | No (propuesta) |
| V2 | Anomalous Query Detector | Detector de consultas anómalas contra la API: sondeo, extracción, distribución anómala, automatización o abuso | Jiang et al. (2024), AMAO; OWASP | Sí |
| V3 | Model Behavior Baseline | Línea base del comportamiento esperado del modelo por versión, cohorte, subpoblación, distribución de entradas y métricas de desempeño | Kreuzberger et al. (2023); Lewis et al. (2021); Warnett y Zdun (2024) | Parcial |
| V4 | Information Leakage Detector | Inspección de las salidas para detectar exposición excesiva de información, fuga por memorización o patrones compatibles con extracción o inversión | OWASP; Papernot | No (propuesta) |

*Nota:* en la columna de fundamento, OWASP remite a OWASP (2023) y Papernot, a Papernot et al. (2018). La aplicabilidad es Sí cuando el candidato tiene fundamento directo en la literatura de seguridad de ML o en un estándar aplicable; Parcial, cuando es un mecanismo de seguridad general adaptado al contexto de ML, o un mecanismo de ML útil que no es un patrón arquitectónico completo; y No (propuesta), cuando es una propuesta de este trabajo o carece de validación suficiente en el corpus revisado.

## Referencias

Chandramouli, R. (2019). *Security strategies for microservices-based application systems* (NIST Special Publication 800-204). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-204

Chandramouli, R., Butcher, Z. y Chetal, A. (2021). *Attribute-based access control for microservices-based applications using a service mesh* (NIST Special Publication 800-204B). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-204B

Jiang, W., Li, H., Xu, G., Zhang, T. y Lu, R. (2024). A comprehensive defense framework against model extraction attacks. *IEEE Transactions on Dependable and Secure Computing*, *21*(2), 685–700. https://doi.org/10.1109/TDSC.2023.3261327

Kreuzberger, D., Kühl, N. y Hirschl, S. (2023). Machine learning operations (MLOps): Overview, definition, and architecture. *IEEE Access*, *11*, 31866–31879. https://doi.org/10.1109/ACCESS.2023.3262138

Lewis, G. A., Ozkaya, I. y Xu, X. (2021). Software architecture challenges for ML systems. En *2021 IEEE International Conference on Software Maintenance and Evolution (ICSME)* (pp. 634–638). IEEE. https://doi.org/10.1109/ICSME52107.2021.00071

OWASP. (2023). *OWASP Machine Learning Security Top Ten* (versión 0.3, borrador). https://owasp.org/www-project-machine-learning-security-top-10/

Papernot, N., McDaniel, P., Sinha, A. y Wellman, M. P. (2018). SoK: Security and privacy in machine learning. En *2018 IEEE European Symposium on Security and Privacy (EuroS&P)* (pp. 399–414). IEEE. https://doi.org/10.1109/EuroSP.2018.00035

Rahman, A., Skjellum, A. y Zhang, Y. (2025). An exploratory study of security vulnerabilities in machine learning deployment projects. En *2025 IEEE/ACM 3rd International Workshop on Software Vulnerability Management (SVM)* (pp. 33–36). IEEE. https://doi.org/10.1109/SVM66695.2025.00009

Shorov, A., Ustundag Soykan, E., Evans, S. y Shammary, B. (2025, agosto). *Visualizing secure MLOps (MLSecOps): A practical guide for building robust AI/ML pipeline security*. Open Source Security Foundation. https://openssf.org/wp-content/uploads/2025/08/OpenSSF_MLSecOps_Whitepaper.pdf

Warnett, S. J. y Zdun, U. (2024). On the understandability of MLOps system architectures. *IEEE Transactions on Software Engineering*, *50*(5), 1015–1039. https://doi.org/10.1109/TSE.2024.3367488
