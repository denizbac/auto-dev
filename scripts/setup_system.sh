#!/bin/bash
# Full System Setup Script
# =========================
# Run this script after SSH'ing into the EC2 instance.
# Usage: ./setup_system.sh

set -e

echo "=========================================="
echo "Autonomous Claude Agent - System Setup"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as ubuntu user
if [ "$USER" != "ubuntu" ]; then
    log_error "Please run as ubuntu user"
    exit 1
fi

# Wait for user_data to complete
while [ ! -f /autonomous-claude/.user_data_complete ]; do
    log_warn "Waiting for user_data script to complete..."
    sleep 5
done

log_info "User data complete, proceeding with setup..."

# ========================================
# Node.js 20 LTS Installation
# ========================================
log_info "Installing Node.js 20 LTS..."

curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

node --version
npm --version

# ========================================
# Python 3.12 Installation (Ubuntu 24.04 default)
# ========================================
log_info "Installing Python 3.12..."

sudo apt-get install -y python3 python3-venv python3-pip

# Create virtual environment for the project
python3 -m venv /autonomous-claude/venv
source /autonomous-claude/venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# ========================================
# Docker Installation
# ========================================
log_info "Installing Docker..."

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add ubuntu user to docker group
sudo usermod -aG docker ubuntu

log_info "Docker installed. You may need to log out and back in for docker group membership."

# ========================================
# Chromium & Playwright Dependencies
# ========================================
log_info "Installing Chromium and Playwright dependencies..."

# Install Chromium
sudo apt-get install -y chromium-browser

# Install Playwright system dependencies
sudo apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0

# Install Playwright via npm globally for Claude Code
sudo npm install -g playwright
sudo npx playwright install chromium
sudo npx playwright install-deps chromium

# ========================================
# Install Python Dependencies
# ========================================
log_info "Installing Python dependencies..."

source /autonomous-claude/venv/bin/activate

pip install \
    fastapi[standard] \
    uvicorn \
    jinja2 \
    aiofiles \
    aiohttp \
    qdrant-client \
    sentence-transformers \
    python-dotenv \
    pyyaml \
    psutil \
    watchdog

# ========================================
# Start Qdrant via Docker
# ========================================
log_info "Starting Qdrant vector database..."

# Need to use newgrp to access docker without logout
sudo docker pull qdrant/qdrant:latest

sudo docker run -d \
    --name qdrant \
    --restart unless-stopped \
    -p 6333:6333 \
    -v /autonomous-claude/data/qdrant:/qdrant/storage \
    qdrant/qdrant:latest

log_info "Qdrant started on port 6333"

# ========================================
# Claude Code CLI Installation
# ========================================
log_info "Installing Claude Code CLI..."

# Install Claude Code CLI via npm
sudo npm install -g @anthropic-ai/claude-code

log_info "Claude Code CLI installed"

# ========================================
# Codex CLI (Optional)
# ========================================
if command -v npm >/dev/null 2>&1; then
    if ! command -v codex >/dev/null 2>&1; then
        log_info "Installing Codex CLI..."
        if sudo npm install -g @openai/codex; then
            log_info "Codex CLI installed"
        else
            log_warning "Codex CLI install failed. You can retry later."
        fi
    fi
else
    log_warning "npm not found; skipping Codex CLI install."
fi

# ========================================
# Create systemd service files
# ========================================
log_info "Creating systemd service files..."

# Watcher service
sudo tee /etc/systemd/system/autonomous-claude-watcher.service > /dev/null << 'EOF'
[Unit]
Description=Autonomous Claude Watcher Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/autonomous-claude
Environment="PATH=/autonomous-claude/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/autonomous-claude/venv/bin/python /autonomous-claude/watcher/supervisor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Dashboard service
sudo tee /etc/systemd/system/autonomous-claude-dashboard.service > /dev/null << 'EOF'
[Unit]
Description=Autonomous Claude Dashboard Service
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/autonomous-claude/dashboard
Environment="PATH=/autonomous-claude/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/autonomous-claude/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# ========================================
# Setup environment file
# ========================================
log_info "Creating environment file template..."

cat > /autonomous-claude/config/.env.template << 'EOF'
# Claude Code Authentication
# Option 1: Use subscription (recommended - cheaper for continuous use)
#   Run: claude auth login
#   This uses your Claude Pro/Max subscription
#
# Option 2: Use API key (pay per token)
#   ANTHROPIC_API_KEY=your_api_key_here

# Token budget settings (for tracking, even with subscription)
DAILY_TOKEN_BUDGET=1000000
SESSION_MAX_TOKENS=100000

# Dashboard settings
DASHBOARD_PORT=8080

# Qdrant settings
QDRANT_HOST=localhost
QDRANT_PORT=6333
EOF

# ========================================
# Claude Code CLI Authentication
# ========================================
log_info "Claude Code authentication setup..."
echo ""
echo "IMPORTANT: To use Claude Code with your subscription (cheaper):"
echo "  1. SSH into this server"
echo "  2. Run: claude auth login"
echo "  3. Follow the browser auth flow"
echo ""
echo "Or set ANTHROPIC_API_KEY in .env for API billing (pay per token)"
echo ""

# ========================================
# Final checks
# ========================================
log_info "Running final checks..."

echo ""
echo "=========================================="
echo "Installation Summary"
echo "=========================================="
echo "Node.js: $(node --version)"
echo "npm: $(npm --version)"
echo "Python: $(python3 --version)"
echo "Docker: $(docker --version 2>/dev/null || echo 'requires re-login for group access')"
echo "Chromium: $(chromium-browser --version)"
echo ""
echo "Next steps:"
echo "1. Log out and back in (for docker group access)"
echo "2. Copy .env.template to .env and add your ANTHROPIC_API_KEY"
echo "3. Deploy the watcher and dashboard code"
echo "4. Start services with: sudo systemctl start autonomous-claude-watcher"
echo ""
log_info "Setup complete!"
