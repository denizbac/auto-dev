#!/bin/bash
# Auto-Dev Deploy Script
# =======================
# Deploys Auto-Dev to a remote server
#
# Usage:
#   ./deploy.sh <EC2_IP> [SSH_KEY_PATH] [--docker|--native]
#
# Examples:
#   ./deploy.sh 54.123.45.67                          # Native mode with default key
#   ./deploy.sh 54.123.45.67 ~/.ssh/mykey.pem        # Native mode with custom key
#   ./deploy.sh 54.123.45.67 ~/.ssh/mykey.pem --docker  # Docker mode

set -e

EC2_IP="${1:?Usage: ./deploy.sh <EC2_IP> [SSH_KEY_PATH] [--docker|--native]}"
SSH_KEY="${2:-~/.ssh/auto-dev.pem}"
DEPLOY_MODE="${3:---native}"

REMOTE_DIR="/auto-dev"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

echo "============================================"
echo "Auto-Dev Deployment"
echo "============================================"
echo "Target: $EC2_IP"
echo "Mode: $DEPLOY_MODE"
echo "Remote dir: $REMOTE_DIR"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Files and directories to deploy
DEPLOY_ITEMS=(
    "config"
    "dashboard"
    "watcher"
    "integrations"
    "scripts"
    "requirements.txt"
    "Dockerfile"
    "docker-compose.yaml"
)

# Create a temporary directory for the bundle
BUNDLE_DIR=$(mktemp -d)
trap "rm -rf $BUNDLE_DIR" EXIT

echo "Bundling files..."
for item in "${DEPLOY_ITEMS[@]}"; do
    src="$PROJECT_DIR/$item"
    if [ -e "$src" ]; then
        cp -r "$src" "$BUNDLE_DIR/"
        echo "  + $item"
    else
        echo "  - $item (not found, skipping)"
    fi
done

# Create tarball
echo ""
echo "Creating archive..."
tar -czf "$BUNDLE_DIR/deploy.tar.gz" -C "$BUNDLE_DIR" .
ARCHIVE_SIZE=$(du -h "$BUNDLE_DIR/deploy.tar.gz" | cut -f1)
echo "Archive size: $ARCHIVE_SIZE"

# Upload to server
echo ""
echo "Uploading to $EC2_IP..."
scp $SSH_OPTS -i "$SSH_KEY" "$BUNDLE_DIR/deploy.tar.gz" "ubuntu@${EC2_IP}:/tmp/"

# Extract and set up on server
echo ""
echo "Deploying on server..."
ssh $SSH_OPTS -i "$SSH_KEY" "ubuntu@${EC2_IP}" << ENDSSH
set -e

# Ensure directory exists
sudo mkdir -p $REMOTE_DIR
sudo chown ubuntu:ubuntu $REMOTE_DIR

# Backup existing config
if [ -f "$REMOTE_DIR/config/settings.yaml" ]; then
    cp "$REMOTE_DIR/config/settings.yaml" "/tmp/settings.yaml.backup"
    echo "Backed up existing settings.yaml"
fi

# Extract new files
cd $REMOTE_DIR
tar -xzf /tmp/deploy.tar.gz
rm /tmp/deploy.tar.gz

# Restore config if backed up
if [ -f "/tmp/settings.yaml.backup" ]; then
    cp "/tmp/settings.yaml.backup" "$REMOTE_DIR/config/settings.yaml"
    echo "Restored settings.yaml"
fi

# Ensure correct permissions
chmod +x scripts/*.sh 2>/dev/null || true

# Create data directories
mkdir -p data/{workspaces,specs,memory} logs

echo ""
echo "Deploy mode: $DEPLOY_MODE"

if [ "$DEPLOY_MODE" == "--docker" ]; then
    echo "Starting Docker services..."

    # Build and start
    docker-compose build
    docker-compose up -d

    echo ""
    echo "Docker services started. Check with: docker-compose ps"
else
    echo "Restarting native services..."

    # Install/update Python dependencies
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
        pip install -q -r requirements.txt
    fi

    # Restart services if running
    sudo systemctl restart autodev-dashboard 2>/dev/null || echo "Dashboard not running"
    # Note: In Docker mode, agents run as separate containers, not systemd services
    # For native mode, restart any running agent services
    for agent in pm architect builder reviewer tester security devops bug_finder; do
        sudo systemctl restart autodev-\${agent} 2>/dev/null || true
    done
    sudo systemctl restart autodev-scheduler 2>/dev/null || echo "Scheduler not running"
    sudo systemctl restart autodev-webhook 2>/dev/null || echo "Webhook not running"

    # Show status
    echo ""
    sudo systemctl status autodev-* --no-pager || true
fi

echo ""
echo "Deployment complete!"
ENDSSH

echo ""
echo "============================================"
echo "Deployment successful!"
echo "============================================"
echo ""
echo "Dashboard: http://${EC2_IP}:8080"
echo "Webhook:   http://${EC2_IP}:8081/webhook/gitlab"
echo ""
echo "SSH access: ssh -i $SSH_KEY ubuntu@${EC2_IP}"
echo ""
