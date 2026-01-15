# EFS File System for Persistent Storage
# =======================================
# Used for PostgreSQL data, workspaces, and shared data across services

resource "aws_efs_file_system" "autodev" {
  creation_token = "${var.project_name}-efs"
  encrypted      = true

  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name = "${var.project_name}-efs"
  }
}

# Security group for EFS mount targets
resource "aws_security_group" "efs" {
  name        = "${var.project_name}-efs-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "NFS from ECS tasks"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-efs-sg"
  }
}

# Mount targets in each subnet
resource "aws_efs_mount_target" "autodev" {
  count           = length(data.aws_subnets.default.ids)
  file_system_id  = aws_efs_file_system.autodev.id
  subnet_id       = data.aws_subnets.default.ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

# Access point for PostgreSQL data
resource "aws_efs_access_point" "postgres" {
  file_system_id = aws_efs_file_system.autodev.id

  posix_user {
    gid = 999  # postgres group
    uid = 999  # postgres user
  }

  root_directory {
    path = "/postgres"
    creation_info {
      owner_gid   = 999
      owner_uid   = 999
      permissions = "0755"
    }
  }

  tags = {
    Name = "${var.project_name}-efs-postgres"
  }
}

# Access point for application data (workspaces, specs, etc.)
resource "aws_efs_access_point" "data" {
  file_system_id = aws_efs_file_system.autodev.id

  posix_user {
    gid = 1000  # autodev group
    uid = 1000  # autodev user
  }

  root_directory {
    path = "/data"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name = "${var.project_name}-efs-data"
  }
}

