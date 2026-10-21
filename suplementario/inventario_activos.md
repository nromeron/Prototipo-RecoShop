# Inventario de activos críticos de ML

Material suplementario de la tesis (Anexo A, sección A.2).

| Zona | Activo | Amenazas OWASP | Tácticas y técnicas ATLAS | Contexto de seguridad |
|---|---|---|---|---|
| 1 | Fuentes de datos externas | ML02, ML06 | Resource Development; Initial Access; AML.T0010.002 | Un dato envenenado en origen se propaga si no hay validación en la frontera (Lewis et al., 2021) |
| 1 | Lago de datos (*Data Lake*) | ML02 | AI Attack Staging; Collection | El activo de mayor volumen y el más difícil de auditar a posteriori |
| 1 | Flujo de preprocesamiento | ML02, ML01 | Execution; AI Attack Staging | Fuente de deuda técnica oculta; en texto, vulnerable a ataques de carácter y de palabra (Goyal et al., 2023) |
| 1 | Almacén de características (*Feature Store*) | ML02 | AI Attack Staging; Persistence | Una característica envenenada afecta a todos los modelos que la consumen |
| 1 | Infraestructura de entrenamiento | ML07, ML10 | AI Attack Staging; Execution | El no determinismo dificulta distinguir un modelo comprometido de una variación natural |
| 1 | Almacén de metadatos y experimentos | ML08 | Defense Evasion; AI Attack Staging | Unas métricas falsificadas pueden promover un modelo malicioso |
| 1 | Datos de etiquetado | ML02 | AI Attack Staging; AML.T0010.002 | Punto de entrada humano en un flujo automatizado |
| 2 | Registro de modelos | ML10, ML05, ML06 | AI Model Access; Persistence; Collection; AML.T0018 | Activo pivote: un compromiso de integridad convierte un problema de entrenamiento en uno de servicio |
| 2 | Punto de acceso de inferencia | ML01, ML03, ML04, ML05, ML09 | AI Model Access; Collection; Exfiltration; AML.T0040 | El activo más expuesto: lo afectan cinco de las diez categorías |
| 2 | Preprocesamiento de inferencia | ML01, ML08 | Execution; AI Attack Staging; AML.T0043 | Las discrepancias con el preprocesamiento de entrenamiento causan errores silenciosos |
| 2 | Posprocesamiento | ML09, ML03 | Exfiltration; Impact; AML.T0048.001 | Último punto donde se puede limitar la información que sale del sistema |
| 2 | Pasarela de API (*API Gateway*) | ML05, ML03, ML04 | Initial Access; AI Model Access; AML.T0049; AML.T0040 | Primera línea de defensa contra la extracción y las consultas masivas |
| 2 | Sistema de monitoreo | ML08, ML01 | Defense Evasion; Impact | Si no distingue la deriva legítima del ataque, no ve los ataques graduales |
| 3 | Dependencias de software | ML06 | Resource Development; Initial Access; AML.T0010.001 | Vector documentado; Shorov et al. (2025) proponen SLSA, SBOM y Sigstore |
| 3 | Modelos preentrenados | ML06, ML07 | Resource Development; Initial Access; AML.T0010.003; AML.T0018 | Suplantación en repositorios y modelos base comprometidos, sin equivalente en el software tradicional |
| 3 | Contenedores e imágenes | ML06, ML10 | Initial Access; Execution; AML.T0010.004 | Un contenedor comprometido tras la construcción evade los controles del registro |
| 3 | Orquestador | ML06 | Initial Access; Privilege Escalation; Lateral Movement | Exige segmentación, identidad de servicio y autorización (Chandramouli et al., 2021) |
| 4 | Datos de producción y retroalimentación | ML08, ML02 | Collection; AI Attack Staging; AML.T0020 | El punto más expuesto a ataques graduales (Kreuzberger et al., 2023) |
| 4 | Flujo de reentrenamiento | ML08, ML10 | AI Attack Staging; Execution; AML.T0020; AML.T0031 | Reentrenar sin validar equivale a dar al atacante acceso de escritura al modelo |
| 4 | Compuerta de promoción | ML08 | Defense Evasion; Persistence | Activo derivado del análisis: sin ella, un modelo comprometido llega a producción |

*Nota:* Zona 1, flujo de entrenamiento; Zona 2, servicio de inferencia; Zona 3, cadena de suministro; Zona 4, ciclo de retroalimentación. Rahman et al. (2025) documentan 149 vulnerabilidades en 12 proyectos de despliegue de ML, con el acceso no autorizado como consecuencia más frecuente.
