#!/bin/bash
# Local Development Start Script
# ===============================
# For testing components locally before deploying to AWS.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Starting Autonomous Claude locally..."

# Create local data directories
mkdir -p "$PROJECT_DIR/data/memory"
mkdir -p "$PROJECT_DIR/data/screenshots"
mkdir -p "$PROJECT_DIR/data/projects"
mkdir -p "$PROJECT_DIR/data/income"
mkdir -p "$PROJECT_DIR/logs"

# Check for virtual environment
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/venv"
fi

# Activate venv
source "$PROJECT_DIR/venv/bin/activate"

# Install dependencies
pip install -q -r "$PROJECT_DIR/requirements.txt"

# Check if .env exists
if [ ! -f "$PROJECT_DIR/config/.env" ]; then
    echo "Warning: config/.env not found. Copy from .env.template and add your API key."
fi

# Export environment
export PYTHONPATH="$PROJECT_DIR"

# Start Qdrant if Docker is available
if command -v docker &> /dev/null; then
    if ! docker ps | grep -q qdrant; then
        echo "Starting Qdrant..."
        docker run -d \
            --name qdrant-local \
            -p 6333:6333 \
            -v "$PROJECT_DIR/data/qdrant:/qdrant/storage" \
            qdrant/qdrant:latest 2>/dev/null || true
    fi
else
    echo "Warning: Docker not found. Qdrant (long-term memory) will not be available."
fi

# Start dashboard in background
echo "Starting dashboard on http://localhost:8080..."
cd "$PROJECT_DIR/dashboard"
uvicorn server:app --host 0.0.0.0 --port 8080 --reload &
DASHBOARD_PID=$!

# Wait for Ctrl+C
echo ""
echo "Dashboard running. Press Ctrl+C to stop."
echo ""

cleanup() {
    echo "Stopping services..."
    kill $DASHBOARD_PID 2>/dev/null || true
    docker stop qdrant-local 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

wait $DASHBOARD_PID

