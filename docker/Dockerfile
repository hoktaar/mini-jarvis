# Mini-Jarvis – alles in einem Container (supervisord)
# Build:  docker build -t mini-jarvis -f docker/Dockerfile .
#
# Reproduzierbarkeit: Versionen per Build-Argument festlegen, z. B.
#   --build-arg OLLAMA_VERSION=0.12.6 --build-arg SEARXNG_REF=<commit>
ARG CUDA_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

# ---------------------------------------------------------------------------
# 1) CYD-Firmware bauen (für das Flashen aus der Web-UI und OTA-Updates)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS firmware
# pioarduino 55.x braucht PlatformIO Core ≥ 6.2 und git
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "platformio==6.2.0"
COPY firmware/cyd /src/cyd
WORKDIR /src/cyd
RUN pio run -e cyd -e cyd-st7789 \
 && python tools/package.py --out /firmware

# ---------------------------------------------------------------------------
# 2) Python-Umgebungen, Ollama und SearXNG bauen
# ---------------------------------------------------------------------------
FROM ${CUDA_IMAGE} AS build
ARG OLLAMA_VERSION=""
ARG SEARXNG_REF=master
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev build-essential git curl ca-certificates zstd libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Ollama (Binary + CUDA-Bibliotheken unter /usr/local)
RUN curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="${OLLAMA_VERSION}" sh

# SearXNG – Requirements VOR dem Editable-Install (setup.py importiert searx)
RUN git clone https://github.com/searxng/searxng.git /opt/searxng \
 && git -C /opt/searxng checkout "${SEARXNG_REF}" \
 && python3 -m venv /opt/searxng-venv \
 && /opt/searxng-venv/bin/pip install -U pip setuptools wheel \
 && /opt/searxng-venv/bin/pip install -r /opt/searxng/requirements.txt \
 && /opt/searxng-venv/bin/pip install --use-pep517 --no-build-isolation -e /opt/searxng

# Jarvis-Core
# torch nur als CPU-Variante (Router-Embeddings laufen auf der CPU) – spart mehrere GB.
# Whisper nutzt CTranslate2 mit den CUDA-Bibliotheken des Basis-Images.
# openWakeWord ohne tflite-runtime (gibt es nicht für Python 3.12), wir nutzen ONNX.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY server /src/server
RUN pip install -U pip \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install "/src/server[gpu,cloud,chat,extras]" "searxng-mcp-server==0.1.9" \
 && pip install --no-deps openwakeword==0.6.0 \
 && pip install onnxruntime scipy scikit-learn tqdm requests \
 && (python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])" || true)

# ---------------------------------------------------------------------------
# 3) Laufzeit-Image
# ---------------------------------------------------------------------------
FROM ${CUDA_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin \
    JARVIS_CONFIG_DIR=/config \
    JARVIS_DATA_DIR=/data \
    JARVIS_EXAMPLES_DIR=/opt/jarvis/config/examples \
    JARVIS_FIRMWARE_DIR=/opt/jarvis/firmware \
    OLLAMA_MODELS=/models/ollama \
    OLLAMA_HOST=127.0.0.1:11434 \
    HF_HOME=/models/hf \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 supervisor haproxy libgomp1 libsndfile1 libasound2t64 curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# Benutzer für die Rechtetrennung
RUN groupadd -r jarvis && useradd -r -g jarvis -d /opt/jarvis jarvis \
 && useradd -r -d /nonexistent runner && usermod -aG jarvis runner \
 && useradd -r -d /nonexistent proxy-docker \
 && useradd -r -d /opt/ollama ollama-svc

COPY --from=build /usr/local/bin/ollama /usr/local/bin/ollama
COPY --from=build /usr/local/lib/ollama /usr/local/lib/ollama
COPY --from=build /opt/searxng /opt/searxng
COPY --from=build /opt/searxng-venv /opt/searxng-venv
COPY --from=build /opt/venv /opt/venv
COPY --from=firmware /firmware /opt/jarvis/firmware
COPY config/examples /opt/jarvis/config/examples
COPY docker/searxng-settings.yml /etc/searxng/settings.yml
COPY docker/supervisord.conf /etc/supervisor/conf.d/jarvis.conf
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/init-models.sh /opt/jarvis/init-models.sh
RUN chmod +x /entrypoint.sh /opt/jarvis/init-models.sh

VOLUME ["/config", "/data", "/models", "/scripts"]
EXPOSE 8080 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -fs http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
