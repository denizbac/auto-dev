# Service Discovery (AWS Cloud Map)
# ==================================
# Provides internal DNS for service-to-service communication

resource "aws_service_discovery_private_dns_namespace" "autodev" {
  name        = "autodev.local"
  description = "Private DNS namespace for Auto-Dev services"
  vpc         = data.aws_vpc.default.id

  tags = {
    Name = "${var.project_name}-namespace"
  }
}

# Service discovery entries for infrastructure services
resource "aws_service_discovery_service" "postgres" {
  name = "postgres"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.autodev.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name = "${var.project_name}-sd-postgres"
  }
}

resource "aws_service_discovery_service" "redis" {
  name = "redis"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.autodev.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name = "${var.project_name}-sd-redis"
  }
}

# Service discovery for application services
resource "aws_service_discovery_service" "dashboard" {
  name = "dashboard"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.autodev.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name = "${var.project_name}-sd-dashboard"
  }
}

# Service discovery for agents (dynamic creation)
resource "aws_service_discovery_service" "agents" {
  for_each = toset(var.agent_types)
  name     = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.autodev.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name = "${var.project_name}-sd-${each.key}"
  }
}
