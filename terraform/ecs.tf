# ECS Cluster, Task Definitions, and Services
# ============================================

# ECS Cluster
resource "aws_ecs_cluster" "autodev" {
  name = var.project_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

# CloudWatch Log Group for ECS
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 30

  tags = {
    Name = "${var.project_name}-ecs-logs"
  }
}

# =============================================================================
# Infrastructure Services (Always On)
# =============================================================================

# PostgreSQL Task Definition
resource "aws_ecs_task_definition" "postgres" {
  family                   = "${var.project_name}-postgres"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "postgres"
      image     = "postgres:16-alpine"
      essential = true

      portMappings = [
        {
          containerPort = 5432
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "POSTGRES_USER", value = "autodev" },
        { name = "POSTGRES_DB", value = "autodev" }
      ]

      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/db-password"
        }
      ]

      # Note: Using ephemeral storage for now. Data is lost on task restart.
      # TODO: Configure EFS with proper permissions for persistence

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "postgres"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-postgres-task"
  }
}

# PostgreSQL Service
resource "aws_ecs_service" "postgres" {
  name            = "${var.project_name}-postgres"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.postgres.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  enable_execute_command = true

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.postgres.arn
  }

  tags = {
    Name = "${var.project_name}-postgres-service"
  }
}

# Redis Task Definition
resource "aws_ecs_task_definition" "redis" {
  family                   = "${var.project_name}-redis"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512  # Minimum for 256 CPU
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "redis"
      image     = "redis:7-alpine"
      essential = true

      portMappings = [
        {
          containerPort = 6379
          protocol      = "tcp"
        }
      ]

      command = ["redis-server", "--appendonly", "yes", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "redis"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-redis-task"
  }
}

# Redis Service
resource "aws_ecs_service" "redis" {
  name            = "${var.project_name}-redis"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.redis.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.redis.arn
  }

  tags = {
    Name = "${var.project_name}-redis-service"
  }
}

# =============================================================================
# Application Services (Always On)
# =============================================================================

# Dashboard Task Definition
resource "aws_ecs_task_definition" "dashboard" {
  family                   = "${var.project_name}-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_dashboard.arn  # Dashboard needs ECS permissions

  container_definitions = jsonencode([
    {
      name      = "dashboard"
      image     = "${aws_ecr_repository.autodev.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      command = ["python", "-m", "dashboard.server"]

      environment = [
        { name = "DB_HOST", value = "postgres.autodev.local" },
        { name = "DB_USER", value = "autodev" },
        { name = "DB_NAME", value = "autodev" },
        { name = "REDIS_URL", value = "redis://redis.autodev.local:6379" },
        { name = "ECS_CLUSTER", value = var.project_name },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "USE_ECS", value = "true" }
      ]

      secrets = [
        {
          name      = "DB_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/db-password"
        },
        {
          name      = "GITLAB_TOKEN"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/gitlab-token"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "app-data"
          containerPath = "/auto-dev/data"
          readOnly      = false
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "dashboard"
        }
      }
    }
  ])

  volume {
    name = "app-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.autodev.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.data.id
        iam             = "ENABLED"
      }
    }
  }

  tags = {
    Name = "${var.project_name}-dashboard-task"
  }
}

# Dashboard Service
resource "aws_ecs_service" "dashboard" {
  name            = "${var.project_name}-dashboard"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8080
  }

  service_registries {
    registry_arn = aws_service_discovery_service.dashboard.arn
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "${var.project_name}-dashboard-service"
  }
}

# Webhook Task Definition
resource "aws_ecs_task_definition" "webhook" {
  family                   = "${var.project_name}-webhook"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512  # Minimum for Fargate with 256 CPU
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "webhook"
      image     = "${aws_ecr_repository.autodev.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8081
          protocol      = "tcp"
        }
      ]

      command = ["python", "-m", "integrations.webhook_server"]

      environment = [
        { name = "DB_HOST", value = "postgres.autodev.local" },
        { name = "DB_USER", value = "autodev" },
        { name = "DB_NAME", value = "autodev" },
        { name = "REDIS_URL", value = "redis://redis.autodev.local:6379" }
      ]

      secrets = [
        {
          name      = "DB_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/db-password"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "webhook"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-webhook-task"
  }
}

# Webhook Service
resource "aws_ecs_service" "webhook" {
  name            = "${var.project_name}-webhook"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.webhook.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.webhook.arn
    container_name   = "webhook"
    container_port   = 8081
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "${var.project_name}-webhook-service"
  }
}

# Scheduler Task Definition
resource "aws_ecs_task_definition" "scheduler" {
  family                   = "${var.project_name}-scheduler"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512  # Minimum for Fargate with 256 CPU
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "scheduler"
      image     = "${aws_ecr_repository.autodev.repository_url}:latest"
      essential = true

      command = ["python", "-m", "watcher.scheduler"]

      environment = [
        { name = "DB_HOST", value = "postgres.autodev.local" },
        { name = "DB_USER", value = "autodev" },
        { name = "DB_NAME", value = "autodev" },
        { name = "REDIS_URL", value = "redis://redis.autodev.local:6379" }
      ]

      secrets = [
        {
          name      = "DB_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/db-password"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "scheduler"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-scheduler-task"
  }
}

# Scheduler Service
resource "aws_ecs_service" "scheduler" {
  name            = "${var.project_name}-scheduler"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.scheduler.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  tags = {
    Name = "${var.project_name}-scheduler-service"
  }
}

# =============================================================================
# Agent Services (On-Demand)
# =============================================================================

# Agent Task Definitions (dynamically created for each agent type)
resource "aws_ecs_task_definition" "agents" {
  for_each                 = toset(var.agent_types)
  family                   = "${var.project_name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.key == "builder" ? 1024 : 512
  memory                   = each.key == "builder" ? 2048 : 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${aws_ecr_repository.autodev.repository_url}:latest"
      essential = true

      command = ["python", "-m", "watcher.agent_runner", "--agent", each.key]

      environment = [
        { name = "DB_HOST", value = "postgres.autodev.local" },
        { name = "DB_USER", value = "autodev" },
        { name = "DB_NAME", value = "autodev" },
        { name = "REDIS_URL", value = "redis://redis.autodev.local:6379" },
        { name = "AUTODEV_LLM_PROVIDER", value = "codex" }
      ]

      secrets = [
        {
          name      = "DB_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/db-password"
        },
        {
          name      = "GITLAB_TOKEN"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/gitlab-token"
        },
        {
          name      = "CODEX_API_KEY"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/codex-api-key"
        },
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/anthropic-api-key"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "app-data"
          containerPath = "/auto-dev/data"
          readOnly      = false
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = each.key
        }
      }
    }
  ])

  volume {
    name = "app-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.autodev.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.data.id
        iam             = "ENABLED"
      }
    }
  }

  tags = {
    Name = "${var.project_name}-${each.key}-task"
  }
}

# Agent Services (always running, Redis controls task processing)
resource "aws_ecs_service" "agents" {
  for_each        = toset(var.agent_types)
  name            = "${var.project_name}-${each.key}"
  cluster         = aws_ecs_cluster.autodev.id
  task_definition = aws_ecs_task_definition.agents[each.key].arn
  desired_count   = 1  # Always running, Redis soft-pause controls processing
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.agents[each.key].arn
  }

  tags = {
    Name = "${var.project_name}-${each.key}-service"
  }
}

# Data source for AWS account ID
data "aws_caller_identity" "current" {}
