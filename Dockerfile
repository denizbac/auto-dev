# Auto-Dev: Autonomous Software Development System
# ================================================
# Multi-stage build for minimal production image

# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /auto-dev

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash autodev

# Copy Python packages from builder
COPY --from=builder /root/.local /home/autodev/.local
ENV PATH=/home/autodev/.local/bin:$PATH

# Copy application code
COPY --chown=autodev:autodev config/ ./config/
COPY --chown=autodev:autodev dashboard/ ./dashboard/
COPY --chown=autodev:autodev watcher/ ./watcher/
COPY --chown=autodev:autodev integrations/ ./integrations/
COPY --chown=autodev:autodev scripts/ ./scripts/

# Create data directories
RUN mkdir -p data/workspaces data/specs data/memory logs \
    && chown -R autodev:autodev /auto-dev

USER autodev

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command (can be overridden)
CMD ["python", "-m", "dashboard.server"]
