# Auto-Dev - AWS Infrastructure (ECS Fargate)
# ============================================
# This Terraform configuration provisions ECS Fargate infrastructure
# for running the Auto-Dev autonomous software development system.

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Application = "auto_dev"
    }
  }
}

# =============================================================================
# VPC - Use provided VPC and private subnets
# =============================================================================

data "aws_vpc" "selected" {
  id = var.vpc_id
}

# =============================================================================
# SSM Parameters (create placeholders, values set manually or via CLI)
# =============================================================================

# Note: These are placeholder parameters. Set actual values using AWS CLI:
# aws ssm put-parameter --name "/auto-dev/db-password" --value "YOUR_PASSWORD" --type SecureString --overwrite
# aws ssm put-parameter --name "/auto-dev/gitlab-token" --value "YOUR_TOKEN" --type SecureString --overwrite
# aws ssm put-parameter --name "/auto-dev/gitlab-webhook-secret" --value "YOUR_WEBHOOK_SECRET" --type SecureString --overwrite
# aws ssm put-parameter --name "/auto-dev/codex-api-key" --value "YOUR_KEY" --type SecureString --overwrite
# aws ssm put-parameter --name "/auto-dev/anthropic-api-key" --value "YOUR_KEY" --type SecureString --overwrite

resource "aws_ssm_parameter" "db_password" {
  name        = "/${var.project_name}/db-password"
  description = "PostgreSQL database password"
  type        = "SecureString"
  value       = "CHANGE_ME"  # Placeholder - update via AWS Console or CLI

  lifecycle {
    ignore_changes = [value]  # Don't overwrite manually set values
  }

  tags = {
    Name = "${var.project_name}-db-password"
  }
}

resource "aws_ssm_parameter" "gitlab_token" {
  name        = "/${var.project_name}/gitlab-token"
  description = "GitLab API token"
  type        = "SecureString"
  value       = "CHANGE_ME"  # Placeholder - update via AWS Console or CLI

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.project_name}-gitlab-token"
  }
}

resource "aws_ssm_parameter" "gitlab_webhook_secret" {
  name        = "/${var.project_name}/gitlab-webhook-secret"
  description = "GitLab webhook secret token"
  type        = "SecureString"
  value       = "CHANGE_ME"  # Placeholder - update via AWS Console or CLI

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.project_name}-gitlab-webhook-secret"
  }
}

resource "aws_ssm_parameter" "codex_api_key" {
  name        = "/${var.project_name}/codex-api-key"
  description = "OpenAI Codex API key"
  type        = "SecureString"
  value       = "CHANGE_ME"  # Placeholder - update via AWS Console or CLI

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.project_name}-codex-api-key"
  }
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/${var.project_name}/anthropic-api-key"
  description = "Anthropic Claude API key"
  type        = "SecureString"
  value       = "CHANGE_ME"  # Placeholder - update via AWS Console or CLI

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.project_name}-anthropic-api-key"
  }
}
