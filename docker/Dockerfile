# Mini-Jarvis – alles in einem Container (supervisord)
# Build:  docker build -t mini-jarvis -f docker/Dockerfile .
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    JARVIS_CONFIG_DIR=/config \
    JARVIS_DATA_DIR=/data \
    OLLAMA_MODELS=/models/ollama \
    OLLAMA_HOST=127.0.0.1:11434 \
    HF_HOME=/models/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev build-essential git curl ca-certificates \
        supervisor haproxy libgomp1 libsndfile1 zstd \
    && rm -rf /var/lib/apt/lists/*

# Benutzer für die Rechtetrennung
RUN groupadd -r jarvis && useradd -r -g jarvis -d /opt/jarvis jarvis \
 && useradd -r -d /nonexistent runner && usermod -aG jarvis runner \
 && useradd -r -d /nonexistent proxy-docker \
 && useradd -r -d /opt/ollama ollama-svc

# Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# SearXNG (nur localhost) + SearXNG-MCP-Server
# SearXNG braucht seine Requirements VOR dem Editable-Install (setup.py importiert searx).
RUN git clone --depth 1 https://github.com/searxng/searxng.git /opt/searxng \
 && python3 -m venv /opt/searxng-venv \
 && /opt/searxng-venv/bin/pip install --no-cache-dir -U pip setuptools wheel \
 && /opt/searxng-venv/bin/pip install --no-cache-dir -r /opt/searxng/requirements.txt \
 && /opt/searxng-venv/bin/pip install --no-cache-dir --use-pep517 --no-build-isolation -e /opt/searxng
COPY docker/searxng-settings.yml /etc/searxng/settings.yml

# Jarvis-Core
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY server /opt/jarvis/server
COPY config/examples /opt/jarvis/config/examples
# torch nur als CPU-Variante (Router-Embeddings laufen auf der CPU) – spart mehrere GB.
# Whisper nutzt CTranslate2 mit den CUDA-Bibliotheken des Basis-Images.
# openWakeWord ohne tflite-runtime (gibt es nicht für Python 3.12), wir nutzen ONNX.
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "/opt/jarvis/server[gpu,cloud]" searxng-mcp-server \
 && pip install --no-cache-dir --no-deps openwakeword==0.6.0 \
 && pip install --no-cache-dir onnxruntime scipy scikit-learn tqdm requests

COPY docker/supervisord.conf /etc/supervisor/conf.d/jarvis.conf
COPY docker/haproxy.cfg /etc/haproxy/haproxy.cfg
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/init-models.sh /opt/jarvis/init-models.sh
RUN chmod +x /entrypoint.sh /opt/jarvis/init-models.sh

VOLUME ["/config", "/data", "/models", "/scripts"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
