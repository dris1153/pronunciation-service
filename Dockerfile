FROM python:3.11-slim

# ----------------------------
# System dependencies
# ----------------------------
# util-linux provides `prlimit` (used by Phase 02 ffprobe sandbox).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Non-root user (Phase 01 / Finding 14)
# ----------------------------
RUN useradd -m -u 1000 appuser \
 && mkdir -p /app /app/tmp /app/model_cache

# ----------------------------
# Workdir
# ----------------------------
WORKDIR /app

# ----------------------------
# Python dependencies
# ----------------------------
COPY requirements.txt .

# Install CPU-only PyTorch first (lighter, avoid CUDA)
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir torch==2.5.1+cpu torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# ----------------------------
# Copy source
# ----------------------------
COPY . .

# ----------------------------
# Model cache config
# ----------------------------
ENV TRANSFORMERS_CACHE=/app/model_cache

# Build arg (can override when deploy)
ARG ASR_MODEL_NAME=facebook/wav2vec2-base-960h
ENV ASR_MODEL_NAME=${ASR_MODEL_NAME}

# ----------------------------
# Pre-download model (bake image)
# ----------------------------
COPY download_model.py .

# v2 phone model from a Hugging Face repo. A public repo needs no token; for a private one pass it as a BuildKit secret so it never lands in a layer:
#   docker build --build-arg V2_MODEL_REPO=<org>/<repo> --secret id=HF_TOKEN,env=HF_TOKEN .
# Without a mounted secret the HF_TOKEN build arg (if the platform injects one) is used as is.
ARG V2_MODEL_REPO=""
ENV V2_MODEL_REPO=${V2_MODEL_REPO}
RUN --mount=type=secret,id=HF_TOKEN,required=false \
    --mount=type=secret,id=V2_MODEL_REPO,required=false \
    for v in HF_TOKEN V2_MODEL_REPO; do \
      if [ -f "/run/secrets/$v" ]; then export "$v=$(cat "/run/secrets/$v")"; fi; \
    done; \
    python download_model.py

# ----------------------------
# Runtime config
# ----------------------------
ENV PORT=8001
ENV TMPDIR=/app/tmp

EXPOSE 8001

# ----------------------------
# Drop privileges (Phase 01 / Finding 14)
# ----------------------------
RUN chown -R appuser:appuser /app
USER appuser

# ----------------------------
# Start app
# ----------------------------
CMD ["python", "main.py"]