#!/bin/bash
# Setup Gumroad credentials in AWS SSM Parameter Store
# Usage: ./setup_gumroad_secrets.sh <email> <password>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <gumroad_email> <gumroad_password>"
    exit 1
fi

GUMROAD_EMAIL="$1"
GUMROAD_PASSWORD="$2"

echo "Storing Gumroad credentials in SSM Parameter Store..."

# Store email (encrypted)
aws ssm put-parameter \
    --name "/autonomous-claude/gumroad/email" \
    --value "$GUMROAD_EMAIL" \
    --type "SecureString" \
    --overwrite \
    --region us-east-1

# Store password (encrypted)
aws ssm put-parameter \
    --name "/autonomous-claude/gumroad/password" \
    --value "$GUMROAD_PASSWORD" \
    --type "SecureString" \
    --overwrite \
    --region us-east-1

echo "✅ Gumroad credentials stored successfully!"
echo ""
echo "Parameters created:"
echo "  /autonomous-claude/gumroad/email"
echo "  /autonomous-claude/gumroad/password"
echo ""
echo "To verify: aws ssm get-parameter --name '/autonomous-claude/gumroad/email' --with-decryption --region us-east-1"

