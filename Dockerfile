# Auto-Dev: Autonomous Software Development System
# ================================================
# Multi-stage build for minimal production image

# Stage 1: Python dependencies builder
FROM registry.nimbus.amgen.com/dbac/autodev/python:3.11-slim as python-builder

WORKDIR /build

# Trust Amgen proxy CA during builds (file is provided locally (not in git)).
ARG AMGEN_PROXY_CA_FILE=k8s/local/amgen-proxy-chain.pem

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install proxy CA so pip can reach PyPI through the MITM proxy
COPY ${AMGEN_PROXY_CA_FILE} /usr/local/share/ca-certificates/amgen-proxy-ca.crt
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: React frontend builder
FROM registry.nimbus.amgen.com/dbac/autodev/node:20-slim as frontend-builder

WORKDIR /app

# Trust Amgen proxy CA during frontend build
ARG AMGEN_PROXY_CA_FILE=k8s/local/amgen-proxy-chain.pem
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY ${AMGEN_PROXY_CA_FILE} /usr/local/share/ca-certificates/amgen-proxy-ca.crt
RUN update-ca-certificates

# Copy frontend package files
COPY dashboard/frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy frontend source
COPY dashboard/frontend/ ./

# Build production bundle
RUN npm run build

# Stage 3: Production image
FROM registry.nimbus.amgen.com/dbac/autodev/python:3.11-slim

WORKDIR /auto-dev

# Trust Amgen proxy CA in runtime image
ARG AMGEN_PROXY_CA_FILE=k8s/local/amgen-proxy-chain.pem

# Install runtime dependencies including Node.js for Codex CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    postgresql-client \
    ca-certificates \
    gnupg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install proxy CA so Codex/Node can reach ChatGPT through the MITM proxy
COPY ${AMGEN_PROXY_CA_FILE} /usr/local/share/ca-certificates/amgen-proxy-ca.crt
RUN update-ca-certificates \
    && npm install -g @openai/codex@0.80.0 @anthropic-ai/claude-code@2.1.7 \
    && useradd -m -s /bin/bash autodev

# Copy Python packages from builder
COPY --from=python-builder /root/.local /home/autodev/.local
ENV PATH=/home/autodev/.local/bin:$PATH

# Copy application code
COPY --chown=autodev:autodev config/ ./config/
COPY --chown=autodev:autodev dashboard/*.py ./dashboard/
COPY --chown=autodev:autodev watcher/ ./watcher/
COPY --chown=autodev:autodev integrations/ ./integrations/
COPY --chown=autodev:autodev scripts/ ./scripts/

# Copy React build from frontend builder
COPY --from=frontend-builder --chown=autodev:autodev /app/dist ./dashboard/frontend/dist

# Create data directories and symlink .codex to persistent volume for credential persistence
RUN mkdir -p data/workspaces data/specs data/memory data/projects data/.codex data/.claude logs \
    && chown -R autodev:autodev /auto-dev \
    && ln -s /auto-dev/data/.codex /home/autodev/.codex \
    && ln -s /auto-dev/data/.claude /home/autodev/.claude \
    && chown -h autodev:autodev /home/autodev/.codex /home/autodev/.claude

USER autodev

# Note: Health checks are defined per-service in docker-compose.yaml
# Dashboard uses: curl -f http://localhost:8080/health
# Agents use: pgrep -f agent_runner (process-based check)

# Default command (can be overridden)
CMD ["python", "-m", "dashboard.server"]
