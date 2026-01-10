# Auto-Dev - AWS Infrastructure
# ==============================
# This Terraform configuration provisions the EC2 instance and
# supporting infrastructure for running the Auto-Dev system.

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
    }
  }
}

# Get latest Ubuntu 24.04 AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# VPC - Use default VPC for simplicity
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security Group
resource "aws_security_group" "autonomous_claude" {
  name        = "${var.project_name}-sg"
  description = "Security group for Autonomous Claude agent"
  vpc_id      = data.aws_vpc.default.id

  # SSH access
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  # Dashboard access (restrict in production)
  ingress {
    description = "Dashboard"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  # All outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-sg"
  }
}

# IAM Role for EC2
resource "aws_iam_role" "autonomous_claude" {
  name = "${var.project_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy - Minimal permissions for the agent
resource "aws_iam_role_policy" "autonomous_claude" {
  name = "${var.project_name}-policy"
  role = aws_iam_role.autonomous_claude.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.project_name}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/ec2/${var.project_name}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/${var.project_name}/*"
      }
    ]
  })
}

# Instance Profile
resource "aws_iam_instance_profile" "autonomous_claude" {
  name = "${var.project_name}-profile"
  role = aws_iam_role.autonomous_claude.name
}

# EC2 Instance
resource "aws_instance" "autonomous_claude" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.autonomous_claude.id]
  iam_instance_profile   = aws_iam_instance_profile.autonomous_claude.name
  subnet_id              = data.aws_subnets.default.ids[0]

  root_block_device {
    volume_size           = var.volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = base64encode(file("${path.module}/user_data.sh"))

  # Tags for instance
  tags = {
    Name = "${var.project_name}-instance"
  }

  # Tags for root volume (required for DLM targeting)
  volume_tags = {
    Project     = var.project_name
    Environment = var.environment
    Name        = "${var.project_name}-root-volume"
  }

  lifecycle {
    ignore_changes = [ami] # Don't recreate on AMI updates
  }
}

# Elastic IP for stable access
resource "aws_eip" "autonomous_claude" {
  instance = aws_instance.autonomous_claude.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-eip"
  }
}

# CloudWatch Log Group for agent logs
resource "aws_cloudwatch_log_group" "autonomous_claude" {
  name              = "/aws/ec2/${var.project_name}"
  retention_in_days = 30
}

# =============================================================================
# EBS Backup Configuration (Data Lifecycle Manager)
# =============================================================================
# Automated nightly snapshots with 30-day retention

# IAM Role for DLM
resource "aws_iam_role" "dlm_lifecycle_role" {
  name = "${var.project_name}-dlm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "dlm.amazonaws.com"
        }
      }
    ]
  })
}

# Attach AWS managed policy for DLM
resource "aws_iam_role_policy_attachment" "dlm_lifecycle" {
  role       = aws_iam_role.dlm_lifecycle_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

# DLM Lifecycle Policy for nightly EBS snapshots
resource "aws_dlm_lifecycle_policy" "ebs_backup" {
  description        = "Nightly EBS backup for ${var.project_name}"
  execution_role_arn = aws_iam_role.dlm_lifecycle_role.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    # Target volumes attached to our EC2 instance
    target_tags = {
      Project = var.project_name
    }

    schedule {
      name = "nightly-backup"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]  # 3 AM UTC (adjust as needed)
      }

      retain_rule {
        count = 30  # Keep 30 daily snapshots
      }

      tags_to_add = {
        SnapshotCreator = "DLM"
        Project         = var.project_name
        Environment     = var.environment
      }

      copy_tags = true
    }
  }

  tags = {
    Name = "${var.project_name}-ebs-backup-policy"
  }
}

