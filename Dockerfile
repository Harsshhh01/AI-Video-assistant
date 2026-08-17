# AI Video Assistant — container image
#
# Targets Hugging Face Spaces (Docker SDK) but works on any container host:
#   docker build -t ai-video-assistant .
#   docker run -p 7860:7860 -e MISTRAL_API_KEY=... ai-video-assistant

FROM python:3.11-slim

# ffmpeg is a hard requirement — pydub and Whisper both shell out to it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as UID 1000, and only $HOME and /tmp are
# writable. Everything the app touches must belong to that user.
# Create the working directory as root and hand it over explicitly: a bare
# WORKDIR can end up root-owned, and then the app cannot create data/ at runtime.
RUN useradd -m -u 1000 user \
    && mkdir -p /home/user/app \
    && chown -R user:user /home/user

USER user

# NUMBA_CACHE_DIR matters: numba (a Whisper dependency) writes a JIT cache at
# import time and raises if its target directory is read-only.
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/user/.cache/huggingface \
    XDG_CACHE_HOME=/home/user/.cache \
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /home/user/app

# Install CPU-only torch first. The default PyPI wheel drags in ~2.5 GB of CUDA
# libraries that are useless without a GPU. Installing it up front means the
# `torch>=2.2.0` line in requirements.txt is already satisfied.
COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Bake the models into the image. A free Space has an ephemeral disk, so without
# this every cold start re-downloads several hundred MB before it can transcribe
# a single second of audio.
#   base   ~142 MB, the sensible default on 2 shared vCPUs
#   small  ~466 MB, noticeably better but roughly 2-3x slower
ARG WHISPER_MODEL=base
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "import whisper; whisper.load_model('${WHISPER_MODEL}')" \
 && python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY --chown=user:user app ./app
COPY --chown=user:user web ./web

# Spaces routes external traffic to 7860. Uploads are capped well below the
# local default because they travel through the platform's proxy.
ENV HOST=0.0.0.0 \
    PORT=7860 \
    DATA_DIR=/home/user/app/data \
    MAX_UPLOAD_MB=200

EXPOSE 7860

# Fail the container start loudly if the app cannot import.
CMD ["python", "-m", "app.server"]
