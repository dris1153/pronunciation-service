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

# v2 phone model: private HF repo. Pass the token as a BuildKit secret so it never lands in a layer:
#   docker build --build-arg V2_MODEL_REPO=<org>/<repo> --secret id=hf_token,env=HF_TOKEN .
ARG V2_MODEL_REPO=""
ENV V2_MODEL_REPO=${V2_MODEL_REPO}
RUN --mount=type=secret,id=hf_token,required=false     HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null || true)" python download_model.py

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