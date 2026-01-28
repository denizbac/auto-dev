variable "aws_region" {
  description = "AWS region for IAM resources"
  type        = string
  default     = "us-west-2"
}

variable "secrets_region" {
  description = "Region where Secrets Manager secrets live"
  type        = string
  default     = "us-west-2"
}

variable "create_oidc_provider" {
  description = "Whether to create the OIDC provider in this account"
  type        = bool
  default     = false
}

variable "oidc_provider_url" {
  description = "KaaS cluster OIDC provider URL"
  type        = string
  default     = "https://oidc.eks.us-west-2.amazonaws.com/id/257CD7A69AC4446FAA02098C09C32FD6"
}

variable "oidc_provider_arn" {
  description = "Existing OIDC provider ARN (required if create_oidc_provider is false)"
  type        = string
  default     = ""
}

variable "k8s_namespace" {
  description = "Kubernetes namespace for the ESO ServiceAccount"
  type        = string
  default     = "autodev"
}

variable "k8s_service_account" {
  description = "Kubernetes ServiceAccount name for ESO"
  type        = string
  default     = "auto-dev-secrets"
}

variable "role_name" {
  description = "IAM role name for ESO"
  type        = string
  default     = "auto-dev-eso-role"
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary ARN (optional)"
  type        = string
  default     = "arn:aws:iam::013335207122:policy/atmos-iam-boundary-POLICY"
}

variable "secrets_prefix" {
  description = "Prefix for Secrets Manager secrets"
  type        = string
  default     = "auto-dev/"
}

variable "secrets_arns" {
  description = "Explicit secret ARNs to allow (overrides secrets_prefix)"
  type        = list(string)
  default     = []
}
