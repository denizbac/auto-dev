# Terraform Variables for Auto-Dev Infrastructure (ECS Fargate)
# ==============================================================

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource tagging and naming"
  type        = string
  default     = "auto-dev"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "allowed_cidr" {
  description = "CIDR block allowed to access ALB (use your IP for security)"
  type        = string
  default     = "0.0.0.0/0"
}

# Agent types - used to create task definitions and services
variable "agent_types" {
  description = "List of agent types to deploy"
  type        = list(string)
  default     = [
    "pm",
    "architect",
    "builder",
    "reviewer",
    "tester",
    "security",
    "devops",
    "bug_finder"
  ]
}

# Legacy variables (kept for backwards compatibility during migration)
variable "instance_type" {
  description = "DEPRECATED: EC2 instance type (not used in ECS deployment)"
  type        = string
  default     = "t3.xlarge"
}

variable "volume_size" {
  description = "DEPRECATED: Root volume size (not used in ECS deployment)"
  type        = number
  default     = 100
}

variable "key_name" {
  description = "DEPRECATED: SSH key pair name (not used in ECS deployment)"
  type        = string
  default     = ""
}

variable "allowed_ssh_cidr" {
  description = "DEPRECATED: SSH CIDR (not used in ECS deployment)"
  type        = string
  default     = "0.0.0.0/0"
}
