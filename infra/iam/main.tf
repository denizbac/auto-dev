terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "tls_certificate" "oidc" {
  url = var.oidc_provider_url
}

resource "aws_iam_openid_connect_provider" "kaas" {
  count           = var.create_oidc_provider ? 1 : 0
  url             = var.oidc_provider_url
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.kaas[0].arn : var.oidc_provider_arn
  oidc_provider_host = replace(var.oidc_provider_url, "https://", "")
}

resource "aws_iam_policy" "eso_secrets" {
  name = "${var.role_name}-secrets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = length(var.secrets_arns) > 0 ? var.secrets_arns : [
          "arn:aws:secretsmanager:${var.secrets_region}:${data.aws_caller_identity.current.account_id}:secret:${var.secrets_prefix}*"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "eso" {
  name                 = var.role_name
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = local.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"
            "${local.oidc_provider_host}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "eso_secrets" {
  role       = aws_iam_role.eso.name
  policy_arn = aws_iam_policy.eso_secrets.arn
}
