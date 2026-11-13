# AGENTS.md

Rules for AI coding agents working in this repository. Humans can read them too.

## Project

FastAPI service that scores English pronunciation. Two pipelines share one process: v1 (`/api/v1/evaluate`, Wav2Vec2) and v2 (`/api/v2/evaluate`, ONNX phone CTC + learned scorer, no PyTorch under `app/services/v2/`). Start with [README.md](README.md) and [docs/README.md](docs/README.md). Older conventions for v1 internals are in [.github/copilot-instructions.md](.github/copilot-instructions.md).

## Working rules

- Run `pytest tests/ -q` before committing. Two v1 sanity cases (`poor_001`, `poor_002`) are known failures.
- Keep files under about 200 lines, follow the existing structure ([docs/structure.md](docs/structure.md)), no features beyond the request.
- Code, comments, commit messages and identifiers are English. Commit messages use Conventional Commits, no AI references.
- Never commit secrets (`.env`, tokens). Model files and datasets live in `data/` (git-ignored).
- Do not switch branches or force-push unless the owner asks.

## Docs and translations (mandatory)

English is the source of truth: `README.md`, `docs/*.md`, `training/README.md`. Translations live in `languages/<lang>/` (`vi`, `zh`, `ja`, `es`) and mirror those paths. Every English doc starts with an ID line:

```
<!-- doc-id: docs-api | rev: 78459878 -->
```

`rev` is a hash of the file content, and each translation records the rev it was translated from (`source-rev`). Details: [languages/README.md](languages/README.md); current state: [languages/STATUS.md](languages/STATUS.md).

When you change any English doc:

1. Edit the English file, never the ID line by hand.
2. Run `python scripts/docs_sync.py bump`. It updates the `rev` of every changed English doc and regenerates `languages/STATUS.md`, which then shows the affected translations as stale.
3. Commit the English change, the new ID line and `STATUS.md` together. `pytest` (`tests/test_docs_sync.py`) fails if you skip step 2.
4. Tell the owner which translations are stale. Retranslate them only when asked (or when the task says so): translate from the **current** English text, then run `python scripts/docs_sync.py stamp <lang> <path>` to write the ID line, banner and relative links, then `bump` again to refresh `STATUS.md`.
5. Never edit a translation to "fix" content without checking it against the English file and its `source-rev`. If translation and English disagree, English wins.

Adding a new English doc: put it under `docs/` (or add its path to `sources()` in `scripts/docs_sync.py`), run `bump`, and it appears in `STATUS.md` as missing in every language.

Translations keep code blocks, commands, JSON, field names, URLs and file paths in English, and use [languages/GLOSSARY.md](languages/GLOSSARY.md) for terminology. `LICENSE` and `NOTICE` are not translated.
