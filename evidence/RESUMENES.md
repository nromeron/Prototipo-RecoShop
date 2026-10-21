# Resúmenes SHA-256 de la captura final

Captura del 21 de octubre de 2026 (23:06:01–23:20:25 UTC), código en la revisión `f36f52f`, bitácoras en este directorio. El entrenamiento es determinista: con la misma semilla, cada captura produce los mismos resúmenes. Las versiones del registro cambian entre capturas y figuran en cada bitácora.

| Artefacto | Resumen SHA-256 |
|---|---|
| Modelo de referencia (semilla 42) | `a4fb66346a9e3d0bad3b1c3dc19a12aa0e06b03adf903d9ab088417ba62fd00c` |
| Conjunto de datos de la semilla 42 (3.916 filas) | `afbdc928189dc8ff70831d38bdefb954b035c029318880f2fd78acc830c82c7d` |
| Modelo de la semilla 7 (versión anterior en la sustitución firmada y la reversión) | `1e590f096c455109c36b7a22152e31468dad1e0fa9589d1131f262f7e982eb16` |
| Conjunto de datos de la semilla 7 | `cc773bd8a743be97f88bb39086caf3a17c2f1064dbbbc5897c9437d74ef86906` |
| Modelo con bytes alterados | `08bb7e3f5e6e234238bd2bde71b7a6eb386ee51ca9d9c95a81f329113c924c66` |
| Lote alterado tras la firma del socio | `342b4d7ac76beed27c50dfcd2994da61da4a70d55656a124f0a677365b6c9853` |
| Lote de la fuente suplantada y del socio comprometido (4.307 filas) | `04a2770a48774585c3d8fba0a5cabac59a7d55da368d38782fd0c13cb55ffb0e` |
| Modelo base legítimo | `1cc7d536969e5d058f39baef6ebe3a5f75d2761d155079619cd4e9f10968ca83` |
| Modelo base con puerta trasera | `a923575e9b4932e069c1a99b111a4919973117e522824a661ec8728b2be0c212` |
| Pickle con ejecución de código | `b0b2782cd600850ed9f3a06e96c5c2f639b4aa2caa362d3042af42b02ea130e1` |
| Conjunto canónico de seguridad (1.500 sesiones, 19.617 filas) | `642ff2d0f48c2b124c1319c08c7ba8c983e5e6089589df39f6c1f8dfba9260ce` |
| Candidato reentrenado con retroalimentación limpia (promovido en la integración) | `d5dd1a5182fb14aaeaaebd15e7197d8f76c69b0edab2299053ab799bb84ecd0f` |
| Candidato reentrenado con retroalimentación envenenada | `a42ca30aec2fcf6eed6d8421923f60b90fd20b64cd1f401f92757cab5bbdc0dc` |
| Modelo promovido, alterado tras su firma | `000702b39267ae3160259bb710de436b0e1f1f6df7226072e259f9add263c88b` |

El resumen de un ML-BOM cambia en cada ejecución, porque el documento incluye un número de serie y una marca de tiempo; el del modelo que declara, no.
