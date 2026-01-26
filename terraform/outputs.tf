# Terraform Outputs (ECS Fargate)
# ================================

output "dashboard_url" {
  description = "Dashboard URL (ALB)"
  value       = "http://${aws_lb.autodev.dns_name}"
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.autodev.dns_name
}

output "vpc_id" {
  description = "VPC ID in use"
  value       = var.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnets used by ECS/ALB"
  value       = var.private_subnet_ids
}

output "ecr_repository_url" {
  description = "ECR repository URL for pushing images"
  value       = aws_ecr_repository.autodev.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.autodev.name
}

output "efs_file_system_id" {
  description = "EFS file system ID"
  value       = aws_efs_file_system.autodev.id
}

output "service_discovery_namespace" {
  description = "Service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.autodev.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for ECS tasks"
  value       = aws_cloudwatch_log_group.ecs.name
}

# Helpful commands
output "docker_login_command" {
  description = "Command to login to ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.autodev.repository_url}"
}

output "docker_push_command" {
  description = "Command to build and push image"
  value       = "docker build -t ${aws_ecr_repository.autodev.repository_url}:latest . && docker push ${aws_ecr_repository.autodev.repository_url}:latest"
}

output "ssm_setup_commands" {
  description = "Commands to set SSM parameters (run these with your actual values)"
  value       = <<-EOT
    # Set these parameters with your actual values:
    aws ssm put-parameter --name "/${var.project_name}/db-password" --value "YOUR_DB_PASSWORD" --type SecureString --overwrite
    aws ssm put-parameter --name "/${var.project_name}/gitlab-token" --value "YOUR_GITLAB_TOKEN" --type SecureString --overwrite
    aws ssm put-parameter --name "/${var.project_name}/gitlab-webhook-secret" --value "YOUR_WEBHOOK_SECRET" --type SecureString --overwrite
    aws ssm put-parameter --name "/${var.project_name}/codex-api-key" --value "YOUR_CODEX_KEY" --type SecureString --overwrite
    aws ssm put-parameter --name "/${var.project_name}/anthropic-api-key" --value "YOUR_ANTHROPIC_KEY" --type SecureString --overwrite
  EOT
}

output "agent_services" {
  description = "ECS service names for agents"
  value       = [for agent in var.agent_types : "${var.project_name}-${agent}"]
}
