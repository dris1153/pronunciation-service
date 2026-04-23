import os
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

model = os.environ.get("ASR_MODEL_NAME", "facebook/wav2vec2-base-960h")

cache_dir = "/app/model_cache"

print(f"Downloading model: {model}...")

Wav2Vec2Processor.from_pretrained(model, cache_dir=cache_dir)
Wav2Vec2ForCTC.from_pretrained(model, cache_dir=cache_dir)

print(f"Model {model} baked into image successfully")