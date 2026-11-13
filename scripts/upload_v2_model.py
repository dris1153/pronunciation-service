"""Upload the v2 phone model files to a private Hugging Face repo.

    HF_TOKEN=<write token> python scripts/upload_v2_model.py --repo <user-or-org>/<name>

Uploads model.int8.onnx, vocab.json and scorer.json from data/models/hubert-phone-ctc.
The repo is created private if it does not exist; nothing is made public.
"""
import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
FILES = ("model.int8.onnx", "vocab.json", "scorer.json")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--dir", type=Path, default=ROOT / "data" / "models" / "hubert-phone-ctc")
    args = p.parse_args()

    missing = [f for f in FILES if not (args.dir / f).exists()]
    if missing:
        raise SystemExit(f"missing in {args.dir}: {missing}")
    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(args.repo, private=True, exist_ok=True)
    for name in FILES:
        api.upload_file(path_or_fileobj=str(args.dir / name), path_in_repo=name, repo_id=args.repo)
        print(f"uploaded {name}")


if __name__ == "__main__":
    main()
