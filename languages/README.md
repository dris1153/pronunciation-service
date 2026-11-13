# Translations

| Language | Folder | Entry point |
| --- | --- | --- |
| English (source of truth) | repo root | [README.md](../README.md), [docs/](../docs/README.md) |
| Tiếng Việt | [`vi/`](vi/) | [vi/README.md](vi/README.md) |
| 中文 | [`zh/`](zh/) | [zh/README.md](zh/README.md) |
| 日本語 | [`ja/`](ja/) | [ja/README.md](ja/README.md) |
| Español | [`es/`](es/) | [es/README.md](es/README.md) |

Which translations are up to date: [STATUS.md](STATUS.md). The translations are machine-made (Claude) and have not been reviewed by native speakers; **the English text always wins** if they disagree.

## How matching works

Each translated file mirrors an English file (`docs/api.md` -> `languages/<lang>/docs/api.md`) and starts with an ID line plus a banner:

```
<!-- doc-id: docs-api | lang: vi | source-rev: 78459878 -->
```

The English file starts with `<!-- doc-id: docs-api | rev: 78459878 -->`, where `rev` is the first 8 hex characters of the SHA-256 of the file content (ID line excluded, line endings normalised). Any English edit changes the rev, so every translation made from the old text shows as **stale** in [STATUS.md](STATUS.md) until it is retranslated and restamped.

## Workflow

```bash
# 1. after editing English docs
python scripts/docs_sync.py bump          # updates revs + languages/STATUS.md
python scripts/docs_sync.py check         # what CI/pytest enforces (errors fail, stale translations only warn)

# 2. retranslate a stale file (from the CURRENT English text), then
python scripts/docs_sync.py stamp vi docs/api.md        # ID line, banner, relative links
python scripts/docs_sync.py bump                         # refresh STATUS.md
```

`stamp` takes `--rev=<rev>` if the translation was made from a revision other than the current one. Without paths it stamps every file of that language.

## Translation rules

- Translate prose, table text, headings, alt text and Mermaid node/edge labels. Keep Mermaid ids and syntax.
- Keep **unchanged**: code blocks, commands, JSON/YAML, field and variable names, environment variables, endpoint paths, file paths, URLs, badge URLs, version numbers, numbers and units.
- Leave links exactly as in English: `stamp` rewrites relative links to point at the translated or original file. Heading anchors (`#...`) follow the translated heading, so fix them if a link target heading was translated.
- Do not translate `LICENSE` or `NOTICE` (legal text).
- Use [GLOSSARY.md](GLOSSARY.md) for consistent terminology. Keep proper nouns, model and dataset names, and metric names (GOP, PCC, F1, PER, MDD, CTC) as is.
- Do not add or remove content: a translation is the same document, not a rewrite.
