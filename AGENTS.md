# Repository Guidelines

## Project Structure & Module Organization
- `dashboard/`: web UI and API server for the control panel.
- `watcher/`: agent runtime, scheduler, and background orchestration.
- `integrations/`: GitLab and external system connectors.
- `config/`: YAML settings and agent configuration.
- `skills/` and `templates/`: prompt/skill definitions and scaffolding.
- `scripts/` and `bin/`: operational helpers and CLI utilities.
- `terraform/`: AWS ECS/EFS/ALB infrastructure as code.
- `docker-compose.yaml`, `Dockerfile`: local and containerized runtime.

## Build, Test, and Development Commands
Use the Makefile targets for common tasks:
```bash
make install        # set up venv + dependencies
make dev            # start postgres/redis/qdrant only
make run            # run dashboard locally
make run-agents     # run all agents
make run-scheduler  # run scheduler service
make up|down|logs   # docker-compose lifecycle
make build          # build Docker images
```
Infrastructure runs via `terraform/` (AWS ECS + EFS). Use `terraform init/plan/apply` there.

## Coding Style & Naming Conventions
- Python code uses 4-space indentation and `snake_case` names.
- Environment variables are uppercase (`GITLAB_TOKEN`, `CODEX_API_KEY`).
- Keep configuration in `config/*.yaml` and secrets out of Git.
- Prefer explicit, readable names over abbreviations.

## Testing Guidelines
There is no full test suite checked in yet. The Makefile exposes:
```bash
make test   # runs pytest tests/ -v
```
When adding tests, place them under `tests/` with `test_*.py` naming.

## Commit & Pull Request Guidelines
Recent history uses conventional prefixes like `feat:`, `fix:`, `docs:`, `perf:`, `ui:`. Follow this format for clarity.
For PRs, include:
- a short problem/solution description,
- linked issue or ticket (if applicable),
- screenshots for dashboard UI changes,
- notes on infra changes (especially `terraform/`).

## Security & Configuration Tips
- Store secrets in `.env` for local dev and SSM parameters for AWS.
- Do not expose services publicly; the ALB is internal-only by design.
