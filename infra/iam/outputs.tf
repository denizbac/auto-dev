output "eso_role_arn" {
  description = "IAM role ARN for ESO ServiceAccount"
  value       = aws_iam_role.eso.arn
}

output "oidc_provider_arn" {
  description = "OIDC provider ARN used for IRSA"
  value       = local.oidc_provider_arn
}
