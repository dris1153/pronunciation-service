<!-- doc-id: docs-readme | lang: es | source-rev: 0557f5e0 -->

> 🌐 **Traducción al español** de [`docs/README.md`](../../../docs/README.md) (rev `0557f5e0`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Documentación

| Página | Qué cubre |
| --- | --- |
| [api.md](api.md) | Todos los endpoints, autenticación, errores, ejemplos de petición/respuesta (v1 y v2) |
| [architecture.md](architecture.md) | Diagrama del sistema, pipelines v1 frente a v2, secuencia de una petición v2, arranque, organización del código |
| [scoring-v2.md](scoring-v2.md) | Cómo puntúa el habla el pipeline nativo de fonemas, resultados, límites |
| [scoring-v1.md](scoring-v1.md) | El pipeline original con Wav2Vec2: fórmulas y ejemplos |
| [scoring-constants.md](scoring-constants.md) | Por qué cada constante de puntuación tiene su valor (v1 y v2) |
| [evaluation.md](evaluation.md) | Calidad frente a las puntuaciones de expertos, latencia, memoria, pruebas, plan de datos para vietnamita |
| [training.md](training.md) | Entrenamiento y exportación de los modelos v2, publicación de los archivos |
| [configuration.md](configuration.md) | Todas las variables de entorno |
| [deployment.md](deployment.md) | Docker, Railway, Coolify/nixpacks, archivos en Hugging Face, dimensionamiento |
| [internal-integration.md](internal-integration.md) | Llamar al servicio desde un backend: límites de peticiones por usuario, wrappers, migración a v2 |
| [workflow.md](workflow.md) | Flujo de una petición en forma de texto (v1), flujo de autenticación, arranque, flujo de despliegue |
| [structure.md](structure.md) | Organización de directorios y notas por archivo |

También: la documentación bilingüe de una sola página en [`index.html`](../../../index.html) y un diario del proyecto en [`journals/`](../../../docs/journals).

Las traducciones (Tiếng Việt, 中文, 日本語, Español) están en [`../languages/`](../../README.md); [STATUS.md](../../STATUS.md) muestra cuáles están al día respecto a estas páginas en inglés.
