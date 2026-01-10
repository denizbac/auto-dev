# Terraform Outputs
# =================

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.autonomous_claude.id
}

output "public_ip" {
  description = "Elastic IP address"
  value       = aws_eip.autonomous_claude.public_ip
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${aws_eip.autonomous_claude.public_ip}"
}

output "dashboard_url" {
  description = "Dashboard URL"
  value       = "http://${aws_eip.autonomous_claude.public_ip}:8080"
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.autonomous_claude.id
}

output "iam_role_arn" {
  description = "IAM role ARN"
  value       = aws_iam_role.autonomous_claude.arn
}

output "ebs_backup_policy_id" {
  description = "DLM lifecycle policy ID for EBS backups"
  value       = aws_dlm_lifecycle_policy.ebs_backup.id
}

