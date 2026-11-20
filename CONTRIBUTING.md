# Contributing

Thanks for helping. The easiest way in is an issue labelled [good first issue](https://github.com/dris1153/pronunciation-service/labels/good%20first%20issue) or [help wanted](https://github.com/dris1153/pronunciation-service/labels/help%20wanted). Comment on the issue you take so work is not duplicated. For anything bigger, open an issue first to agree on the approach.

## Set up

Python 3.11.

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install torch==2.5.1+cpu torchaudio==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env                                     # DEBUG=true skips API key checks locally
python download_model.py                                 # v1 model (public); the v2 step is skipped without V2_MODEL_REPO
python main.py                                           # http://localhost:8000/docs
```

The v2 model files (`model.int8.onnx`, `vocab.json`, `scorer.json`) are not in this repo. They are published at [huggingface.co/dris1153/pronunciation-v2](https://huggingface.co/dris1153/pronunciation-v2) and are **not** needed for most work: tests that need them skip themselves. To run v2 locally or work on scoring or the model:

```bash
PHONE_MODEL_DIR=data/models/hubert-phone-ctc V2_MODEL_REPO=dris1153/pronunciation-v2 python download_model.py --v2-only
```

You can also reproduce the files yourself with [docs/training.md](docs/training.md).

## Before you open a PR

- Run `pytest tests/ -q`. Two v1 sanity cases (`poor_001`, `poor_002`) fail on `main` today, see issue #9. Anything else failing is yours to fix.
- Keep the change small and on topic. Follow the structure in [docs/structure.md](docs/structure.md); keep files under about 200 lines.
- Code, comments, identifiers and commit messages are English. Commit messages use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, ...).
- Never commit secrets (`.env`, tokens) or data. Model files and datasets live in `data/`, which is git-ignored.

## Docs and translations

English is the source of truth: `README.md`, `docs/*.md`, `training/README.md`. After editing any of them run:

```bash
python scripts/docs_sync.py bump
```

and commit the result with your change (`pytest` fails if you skip it). That marks the translations in `languages/` as stale; you do not have to retranslate them. If you do want to update a translation, translate from the current English text, then run `python scripts/docs_sync.py stamp <lang> <path>`. Full rules: [AGENTS.md](AGENTS.md) and [languages/README.md](languages/README.md). This file itself is not translated.

## Reporting a bad score

Open an issue with: the reference text, your L1 and accent, the audio (or a description if you cannot share it), the score you got and the one you expected. Scores for accents other than Mandarin-L1 speakers are the least tested part of the project, so these reports are valuable.

## License

By contributing you agree that your work is released under the [Apache License 2.0](LICENSE).
