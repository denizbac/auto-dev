#!/bin/bash
# Auto-Dev Service Installation Script
# =====================================
# Installs systemd services for Auto-Dev on Ubuntu/Debian
#
# Usage: sudo ./install_services.sh [--docker|--native]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTODEV_DIR="${AUTODEV_DIR:-/auto-dev}"
INSTALL_MODE="${1:-native}"

echo "==================================="
echo "Auto-Dev Service Installation"
echo "==================================="
echo "Install mode: $INSTALL_MODE"
echo "Install dir: $AUTODEV_DIR"
echo ""

# Check root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)"
   exit 1
fi

# Create autodev user if not exists
if ! id "autodev" &>/dev/null; then
    echo "Creating autodev user..."
    useradd -r -m -s /bin/bash -d /home/autodev autodev
fi

# Create directories
echo "Creating directories..."
mkdir -p "$AUTODEV_DIR"/{data,logs,config}
mkdir -p "$AUTODEV_DIR"/data/{workspaces,specs,memory}

# Set ownership
chown -R autodev:autodev "$AUTODEV_DIR"

if [[ "$INSTALL_MODE" == "--docker" ]]; then
    echo ""
    echo "Docker mode - skipping systemd native services"
    echo "Use: docker-compose up -d"
    exit 0
fi

# Install systemd services
echo ""
echo "Installing systemd services..."

SERVICES=(
    "autodev-dashboard"
    "autodev-supervisor"
    "autodev-scheduler"
    "autodev-webhook"
)

for service in "${SERVICES[@]}"; do
    echo "  Installing $service..."
    cp "$SCRIPT_DIR/systemd/$service.service" /etc/systemd/system/
    chmod 644 "/etc/systemd/system/$service.service"
done

# Reload systemd
echo ""
echo "Reloading systemd..."
systemctl daemon-reload

# Enable services
echo "Enabling services..."
for service in "${SERVICES[@]}"; do
    systemctl enable "$service"
done

# Create .env template if not exists
if [[ ! -f "$AUTODEV_DIR/.env" ]]; then
    echo ""
    echo "Creating .env template..."
    cat > "$AUTODEV_DIR/.env" << 'EOF'
# Auto-Dev Environment Configuration
# ===================================
# Copy to .env and fill in values

# Database
DB_HOST=localhost
DB_USER=autodev
DB_PASSWORD=your_secure_password
DB_NAME=autodev

# Redis
REDIS_URL=redis://localhost:6379

# Qdrant
QDRANT_HOST=localhost

# GitLab
GITLAB_TOKEN=your_gitlab_token
GITLAB_WEBHOOK_SECRET=your_webhook_secret

# LLM Providers
AUTODEV_LLM_PROVIDER=codex
CODEX_API_KEY=your_codex_key
ANTHROPIC_API_KEY=your_anthropic_key
EOF
    chown autodev:autodev "$AUTODEV_DIR/.env"
    chmod 600 "$AUTODEV_DIR/.env"
fi

echo ""
echo "==================================="
echo "Installation Complete!"
echo "==================================="
echo ""
echo "Next steps:"
echo "  1. Edit $AUTODEV_DIR/.env with your credentials"
echo "  2. Set up PostgreSQL database"
echo "  3. Start services:"
echo "     sudo systemctl start autodev-dashboard"
echo "     sudo systemctl start autodev-supervisor"
echo "     sudo systemctl start autodev-scheduler"
echo "     sudo systemctl start autodev-webhook"
echo ""
echo "View logs:"
echo "  journalctl -u autodev-dashboard -f"
echo "  journalctl -u autodev-supervisor -f"
echo ""
echo "Check status:"
echo "  systemctl status autodev-*"
echo ""
