# Auto-Dev Makefile
# ==================
# Common operations for development and deployment

.PHONY: help install dev up down logs build deploy test clean

# Default target
help:
	@echo "Auto-Dev - Autonomous Software Development System"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Development:"
	@echo "  install     Install Python dependencies locally"
	@echo "  dev         Start development environment (infra only)"
	@echo "  run         Run dashboard locally"
	@echo "  test        Run tests"
	@echo ""
	@echo "Docker:"
	@echo "  up          Start all Docker services"
	@echo "  down        Stop all Docker services"
	@echo "  logs        View Docker logs (use SERVICE=name for specific)"
	@echo "  build       Build Docker images"
	@echo "  rebuild     Rebuild and restart services"
	@echo "  ps          Show running containers"
	@echo ""
	@echo "Database:"
	@echo "  db-shell    Connect to PostgreSQL shell"
	@echo "  db-init     Initialize database schema"
	@echo "  db-reset    Reset database (WARNING: deletes all data)"
	@echo ""
	@echo "Deployment:"
	@echo "  k8s-apply   Apply KaaS manifests (requires kubeconfig)"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean       Clean temporary files"
	@echo "  status      Show service status"

# =============================================================================
# Development
# =============================================================================

install:
	python -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Activate with: source venv/bin/activate"

dev:
	docker-compose up -d postgres redis qdrant
	@echo ""
	@echo "Infrastructure started. Run 'make run' to start dashboard."

run:
	./venv/bin/python -m dashboard.server

run-agents:
	./venv/bin/python -m watcher.agent_runner --all-agents

# Backwards compatibility alias
run-supervisor: run-agents

run-scheduler:
	./venv/bin/python -m watcher.scheduler

test:
	./venv/bin/pytest tests/ -v

# =============================================================================
# Docker
# =============================================================================

up:
	docker-compose up -d
	@echo ""
	@make ps

down:
	docker-compose down

logs:
ifdef SERVICE
	docker-compose logs -f $(SERVICE)
else
	docker-compose logs -f
endif

build:
	docker-compose build

rebuild:
	docker-compose build --no-cache
	docker-compose up -d

ps:
	docker-compose ps

shell:
ifdef SERVICE
	docker-compose exec $(SERVICE) /bin/bash
else
	@echo "Usage: make shell SERVICE=dashboard"
endif

# =============================================================================
# Database
# =============================================================================

db-shell:
	docker-compose exec postgres psql -U autodev -d autodev

db-init:
	docker-compose exec postgres psql -U autodev -d autodev -f /docker-entrypoint-initdb.d/init.sql

db-reset:
	@echo "WARNING: This will delete all data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	docker-compose down -v
	docker-compose up -d postgres
	@sleep 5
	@make db-init
	@echo "Database reset complete"

db-backup:
	@mkdir -p backups
	docker-compose exec postgres pg_dump -U autodev autodev > backups/autodev_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "Backup saved to backups/"

db-restore:
ifndef BACKUP
	@echo "Usage: make db-restore BACKUP=backups/autodev_20240101_120000.sql"
else
	docker-compose exec -T postgres psql -U autodev autodev < $(BACKUP)
	@echo "Restored from $(BACKUP)"
endif

# =============================================================================
# Deployment
# =============================================================================

k8s-apply:
	kubectl apply -k k8s/

# =============================================================================
# Maintenance
# =============================================================================

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ 2>/dev/null || true
	@echo "Cleaned temporary files"

status:
	@echo "=== Docker Containers ==="
	@docker-compose ps 2>/dev/null || echo "Docker not running"
	@echo ""
	@echo "=== Systemd Services ==="
	@systemctl status autodev-* --no-pager 2>/dev/null || echo "Systemd services not installed"

# Environment file template
env-template:
	@cat > .env.example << 'EOF'
# Auto-Dev Environment Configuration
# Copy to .env and fill in values

# Database
DB_HOST=localhost
DB_PASSWORD=your_secure_password

# GitLab
GITLAB_TOKEN=your_gitlab_token
GITLAB_WEBHOOK_SECRET=your_webhook_secret

# LLM Providers
AUTODEV_LLM_PROVIDER=codex
CODEX_API_KEY=your_codex_key
ANTHROPIC_API_KEY=your_anthropic_key

# Optional: pgAdmin
PGADMIN_PASSWORD=admin
EOF
	@echo "Created .env.example"
