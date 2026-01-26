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
mkdir -p /auto-dev/{config,data,logs,dashboard,watcher,skills}
mkdir -p /auto-dev/data/{memory,screenshots,projects,income}

# Set ownership (ubuntu user)
chown -R ubuntu:ubuntu /auto-dev

# Signal completion
touch /auto-dev/.user_data_complete
echo "User data script completed at $(date)" >> /auto-dev/logs/setup.log

