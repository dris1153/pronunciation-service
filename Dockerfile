FROM python:3.11-slim

# ----------------------------
# System dependencies
# ----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

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

RUN python download_model.py

# ----------------------------
# Runtime config
# ----------------------------
ENV PORT=8001

EXPOSE 8001

# ----------------------------
# Start app
# ----------------------------
CMD ["python", "main.py"]