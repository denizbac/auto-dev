#!/bin/bash
# Sync swarm code changes from EC2 to local for review and commit
# Usage: ./scripts/sync_from_ec2.sh [--commit]

set -e

# Get EC2 IP from terraform
EC2_IP=$(cd terraform && terraform output -raw public_ip 2>/dev/null)
SSH_KEY="$HOME/.ssh/autonomous-claude.pem"

if [ -z "$EC2_IP" ]; then
    echo "❌ Could not get EC2 IP from terraform"
    exit 1
fi

echo "🔄 Syncing from EC2 ($EC2_IP)..."

# Files to sync (code that swarm might modify)
SYNC_FILES=(
    "watcher/orchestrator.py"
    "watcher/agent_runner.py"
    "watcher/memory.py"
    "watcher/gumroad_publisher.py"
    "config/settings.yaml"
)

# Also check for new files in watcher/
echo ""
echo "📁 Checking for new files on EC2..."
NEW_FILES=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$EC2_IP \
    "cd /autonomous-claude && find watcher -name '*.py' -type f" 2>/dev/null)

for remote_file in $NEW_FILES; do
    if [ ! -f "$remote_file" ]; then
        echo "  NEW: $remote_file"
        SYNC_FILES+=("$remote_file")
    fi
done

# Create temp dir for comparison
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo ""
echo "📥 Downloading files..."
CHANGED_FILES=()

for file in "${SYNC_FILES[@]}"; do
    # Download from EC2
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$EC2_IP \
        "cat /autonomous-claude/$file 2>/dev/null" > "$TEMP_DIR/$(basename $file)" 2>/dev/null || continue
    
    # Compare
    if [ -f "$file" ]; then
        if ! diff -q "$file" "$TEMP_DIR/$(basename $file)" > /dev/null 2>&1; then
            echo "  CHANGED: $file"
            CHANGED_FILES+=("$file")
        fi
    else
        echo "  NEW: $file"
        CHANGED_FILES+=("$file")
    fi
done

if [ ${#CHANGED_FILES[@]} -eq 0 ]; then
    echo ""
    echo "✅ No changes detected. Local and EC2 are in sync."
    exit 0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 CHANGES DETECTED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for file in "${CHANGED_FILES[@]}"; do
    echo ""
    echo "┌── $file ──"
    if [ -f "$file" ]; then
        diff -u "$file" "$TEMP_DIR/$(basename $file)" | head -50 || true
    else
        echo "  (new file - $(wc -l < "$TEMP_DIR/$(basename $file)") lines)"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$1" == "--commit" ]; then
    echo ""
    read -p "Apply these changes and commit? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Copy files
        for file in "${CHANGED_FILES[@]}"; do
            mkdir -p "$(dirname $file)"
            cp "$TEMP_DIR/$(basename $file)" "$file"
            git add "$file"
        done
        
        # Commit
        git commit -m "feat: Sync swarm-evolved changes from EC2

Files synced:
$(printf '- %s\n' "${CHANGED_FILES[@]}")"
        
        echo ""
        echo "✅ Changes committed. Run 'git push' to push to origin."
    fi
else
    echo ""
    echo "To apply these changes, run:"
    echo "  ./scripts/sync_from_ec2.sh --commit"
fi



