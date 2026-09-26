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
RUN git clone --depth 1 https://github.com/searxng/searxng.git /opt/searxng \
 && python3 -m venv /opt/searxng-venv \
 && /opt/searxng-venv/bin/pip install --no-cache-dir -U pip setuptools wheel pyyaml \
 && /opt/searxng-venv/bin/pip install --no-cache-dir -e /opt/searxng
COPY docker/searxng-settings.yml /etc/searxng/settings.yml

# Jarvis-Core
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY server /opt/jarvis/server
COPY config/examples /opt/jarvis/config/examples
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir "/opt/jarvis/server[gpu,cloud]" searxng-mcp-server

COPY docker/supervisord.conf /etc/supervisor/conf.d/jarvis.conf
COPY docker/haproxy.cfg /etc/haproxy/haproxy.cfg
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/init-models.sh /opt/jarvis/init-models.sh
RUN chmod +x /entrypoint.sh /opt/jarvis/init-models.sh

VOLUME ["/config", "/data", "/models", "/scripts"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
