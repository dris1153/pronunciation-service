<!-- doc-id: docs-readme | rev: 0557f5e0 -->
# Documentation

| Page | What it covers |
| --- | --- |
| [api.md](api.md) | Every endpoint, auth, errors, request/response examples (v1 and v2) |
| [architecture.md](architecture.md) | System diagram, v1 vs v2 pipelines, v2 request sequence, startup, code layout |
| [scoring-v2.md](scoring-v2.md) | How the phoneme-native pipeline scores speech, results, limits |
| [scoring-v1.md](scoring-v1.md) | The original Wav2Vec2 pipeline: formulas and examples |
| [scoring-constants.md](scoring-constants.md) | Why each scoring constant has its value (v1 and v2) |
| [evaluation.md](evaluation.md) | Quality vs expert scores, latency, memory, tests, Vietnamese data plan |
| [training.md](training.md) | Training and exporting the v2 models, publishing artifacts |
| [configuration.md](configuration.md) | All environment variables |
| [deployment.md](deployment.md) | Docker, Railway, Coolify/nixpacks, Hugging Face artifacts, sizing |
| [internal-integration.md](internal-integration.md) | Calling the service from a backend: per-user rate limits, wrappers, switching to v2 |
| [workflow.md](workflow.md) | Request flow in text form (v1), auth flow, startup, deployment flow |
| [structure.md](structure.md) | Directory layout and per-file notes |

Also: the bilingual single-page docs in [`index.html`](../index.html) and a project journal in [`journals/`](journals/).

Translations (Tiếng Việt, 中文, 日本語, Español) live in [`../languages/`](../languages/README.md); [STATUS.md](../languages/STATUS.md) shows which ones are up to date with these English pages.
