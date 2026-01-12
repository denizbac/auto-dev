#!/usr/bin/env python3
"""
Webhook Server for Auto-Dev
============================

Standalone FastAPI server for receiving GitLab webhooks.
Routes incoming webhooks to the orchestrator task queue.

Usage:
    python -m integrations.webhook_server
"""

import os
import sys
import logging
from pathlib import Path

from fastapi import FastAPI
import uvicorn

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.gitlab_webhook import create_webhook_routes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Auto-Dev Webhook Server",
    version="1.0.0",
    description="Receives GitLab webhooks and creates tasks"
)


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/load balancer."""
    return {"status": "healthy", "service": "webhook", "version": "1.0.0"}


@app.on_event("startup")
async def startup():
    """Initialize orchestrator and register webhook routes."""
    logger.info("Starting webhook server...")

    # Import orchestrator (lazy to avoid circular imports)
    try:
        from watcher.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()

        # Register webhook routes with orchestrator
        webhook_router = create_webhook_routes(orchestrator)
        app.include_router(webhook_router)

        logger.info("Webhook routes registered with orchestrator")
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")
        # Server can still run for health checks
        logger.warning("Running in degraded mode without orchestrator")


def main():
    """Run the webhook server."""
    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8081"))

    logger.info(f"Starting webhook server on {host}:{port}")

    uvicorn.run(
        "integrations.webhook_server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
