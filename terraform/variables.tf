# Terraform Variables for Auto-Dev Infrastructure
# =================================================

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.medium"
}

variable "volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 50
}

variable "key_name" {
  description = "Name of the SSH key pair to use"
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "CIDR block allowed to SSH (use your IP for security)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
  default     = "auto-dev"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

