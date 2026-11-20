"""Bake models into the image at build time.

    python download_model.py            # v1 ASR model + v2 phone model
    python download_model.py --v2-only  # v2 phone model only

v2 files come from a Hugging Face repo (V2_MODEL_REPO; HF_TOKEN only if the repo is private).
Without V2_MODEL_REPO the v2 step is skipped and /api/v2 answers 503.
"""
import os
import sys

V2_FILES = ("model.int8.onnx", "vocab.json", "scorer.json")


def download_v1() -> None:
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    model = os.environ.get("ASR_MODEL_NAME", "facebook/wav2vec2-base-960h")
    cache_dir = "/app/model_cache"
    print(f"Downloading model: {model}...")
    Wav2Vec2Processor.from_pretrained(model, cache_dir=cache_dir)
    Wav2Vec2ForCTC.from_pretrained(model, cache_dir=cache_dir)
    print(f"Model {model} baked into image successfully")


def download_v2() -> None:
    repo = os.environ.get("V2_MODEL_REPO")
    if not repo:
        print("V2_MODEL_REPO not set: skipping v2 phone model")
        return
    from huggingface_hub import hf_hub_download

    target = os.environ.get("PHONE_MODEL_DIR", "/app/data/models/hubert-phone-ctc")
    token = os.environ.get("HF_TOKEN") or None
    for name in V2_FILES:
        hf_hub_download(repo, name, token=token, local_dir=target)
    print(f"v2 phone model from {repo} baked into {target}")


if __name__ == "__main__":
    if "--v2-only" not in sys.argv:
        download_v1()
    download_v2()
