# Debilidades arquitectónicas candidatas de la Fase 0

Material suplementario de la tesis (Fase 0, actividad 1: síntesis amenaza-por-activo, Tabla A-1). A partir de esa síntesis se derivan las debilidades arquitectónicas candidatas siguientes. Una categoría del OWASP ML Top 10 puede generar más de una debilidad cuando existen causas arquitectónicas distintas.

| ID | Debilidad candidata | Origen (OWASP ML) |
|---|---|---|
| D-C01 | Exposición directa del modelo a inputs no validados. | ML01 |
| D-C02 | Ausencia de detección de inputs fuera de distribución. | ML01, ML08 |
| D-C03 | Falta de procedencia y trazabilidad de datos de entrenamiento. | ML02 |
| D-C04 | Falta de separación entre datos de producción, datos externos y corpus de entrenamiento. | ML02, ML08 |
| D-C05 | Exposición excesiva de scores, probabilidades o información inferencial en la API. | ML03, ML04 |
| D-C06 | Ausencia de controles privacy-preserving en inferencia. | ML03, ML04 |
| D-C07 | Ausencia de monitoreo de patrones de consulta para extracción. | ML05 |
| D-C08 | Falta de protección de artefactos del modelo en reposo. | ML05, ML10 |
| D-C09 | Ausencia de firma o verificación de artefactos ML externos. | ML06, ML07, ML10 |
| D-C10 | Dependencias ML externas sin SBOM ni verificación de integridad. | ML06 |
| D-C11 | Modelos pre-entrenados sin validación de comportamiento antes de fine-tuning. | ML07 |
| D-C12 | Falta de aislamiento entre entrenamiento, fine-tuning y producción. | ML07, ML10 |
| D-C13 | Feedback loop de reentrenamiento sin gate estadístico de seguridad. | ML08 |
| D-C14 | Canal post-inferencia sin garantías de integridad extremo a extremo. | ML09 |
| D-C15 | Model Registry mutable o sin auditoría/versionado inmutable. | ML10 |
| D-C16 | Interfaces MLOps expuestas sin autenticación/autorización robusta. | ML06, ML10 |
