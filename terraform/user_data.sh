#!/bin/bash
# User Data Script - Initial EC2 Setup
# =====================================
# This script runs on first boot to prepare the instance.
# Full setup is done via the setup scripts after SSH access.

set -e

# Update system
apt-get update
apt-get upgrade -y

# Install basic dependencies
apt-get install -y \
    curl \
    wget \
    git \
    unzip \
    jq \
    htop \
    tmux \
    sqlite3 \
    ca-certificates \
    gnupg \
    lsb-release

# Create project directory structure
mkdir -p /autonomous-claude/{config,data,logs,dashboard,watcher,skills}
mkdir -p /autonomous-claude/data/{memory,screenshots,projects,income}

# Set ownership (ubuntu user)
chown -R ubuntu:ubuntu /autonomous-claude

# Signal completion
touch /autonomous-claude/.user_data_complete
echo "User data script completed at $(date)" >> /autonomous-claude/logs/setup.log

