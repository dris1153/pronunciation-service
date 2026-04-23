FROM python:3.11-slim

# System dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (separate layer for better caching)
# Install CPU-only PyTorch first (avoids downloading ~2GB CUDA packages)
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.5.1+cpu torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# ---------------------------------------------------------------
# Bake Wav2Vec2 model into the image at build time.
# Railway does NOT have persistent volumes, so the model must be
# downloaded once here and shipped as part of the image.
# Cache dir is set to /app/model_cache to match ASR_MODEL_CACHE_DIR.
#
# Override at build time:
#   docker build --build-arg ASR_MODEL_NAME=facebook/wav2vec2-base-960h .
# ---------------------------------------------------------------
ARG ASR_MODEL_NAME=facebook/wav2vec2-base-960h
# Persist the ARG as an ENV *before* the RUN step so that os.environ inside
# the build script sees the correct value when --build-arg is passed.
# Can still be overridden at runtime via Railway Dashboard / docker-compose.
ENV ASR_MODEL_NAME=${ASR_MODEL_NAME}
RUN python -c "\
import os; \
model = os.environ.get('ASR_MODEL_NAME', 'facebook/wav2vec2-base-960h'); \
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor; \
Wav2Vec2Processor.from_pretrained(model, cache_dir='/app/model_cache'); \
Wav2Vec2ForCTC.from_pretrained(model, cache_dir='/app/model_cache'); \
print(f'Model {model} baked into image successfully')"

# Railway injects PORT at runtime; default to 8000 for local Docker runs.
# pydantic-settings reads the PORT env var directly into Settings.port —
# no shell expansion needed, avoids the "$PORT is not a valid integer" error.
ENV PORT=8001

EXPOSE 8001

CMD ["python", "main.py"]
