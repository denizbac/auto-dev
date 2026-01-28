#!/bin/bash
# Setup Gumroad credentials in AWS Secrets Manager
# Usage: ./setup_gumroad_secrets.sh <email> <password>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <gumroad_email> <gumroad_password>"
    exit 1
fi

GUMROAD_EMAIL="$1"
GUMROAD_PASSWORD="$2"
REGION="${AWS_REGION:-us-west-2}"

echo "Storing Gumroad credentials in Secrets Manager..."

create_or_update_secret() {
    local name="$1"
    local value="$2"

    if aws secretsmanager describe-secret --secret-id "$name" --region "$REGION" >/dev/null 2>&1; then
        aws secretsmanager put-secret-value \
            --secret-id "$name" \
            --secret-string "$value" \
            --region "$REGION"
    else
        aws secretsmanager create-secret \
            --name "$name" \
            --secret-string "$value" \
            --region "$REGION"
    fi
}

create_or_update_secret "auto-dev/gumroad/email" "$GUMROAD_EMAIL"
create_or_update_secret "auto-dev/gumroad/password" "$GUMROAD_PASSWORD"

echo "✅ Gumroad credentials stored successfully!"
echo ""
echo "Secrets created/updated:"
echo "  auto-dev/gumroad/email"
echo "  auto-dev/gumroad/password"
echo ""
echo "To verify: aws secretsmanager get-secret-value --secret-id 'auto-dev/gumroad/email' --region $REGION"
