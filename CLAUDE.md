# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Auto-Dev is an autonomous software development system that uses 8 AI agents to develop software on GitLab repositories. Uses Codex (primary) with Claude as fallback. Agents handle the full lifecycle: analysis, specs, implementation, review, testing, security, deployment.

## Pre-Commit Checklist

**IMPORTANT: Before committing any changes, review and update relevant documentation.**

When you make changes to:
- **Infrastructure** (terraform/, Dockerfile, docker-compose.yaml) → Update `OPERATIONS.md` and `ARCHITECTURE.md`
- **Agent behavior** (watcher/, config/agents/) → Update `ARCHITECTURE.md` and agent task tables in `README.md`
- **API endpoints** (dashboard/server.py) → Update API section in `README.md`
- **Configuration** (config/settings.yaml) → Update relevant config sections in docs
- **Commands/workflows** → Update `CLAUDE.md` commands section and `OPERATIONS.md`

Documentation files to check:
| File | What it covers |
|------|----------------|
| `CLAUDE.md` | Quick reference for Claude Code - commands, architecture overview |
| `README.md` | User-facing docs - setup, agents, workflows, API |
| `ARCHITECTURE.md` | Technical deep-dive - system design, data flows, infrastructure |
| `OPERATIONS.md` | Day-to-day operations - deployment, monitoring, troubleshooting |
| `POLICY.md` | Approval gates and autonomy rules |

**Rule**: If your code change would make any documentation inaccurate, update the docs in the same commit.

## Commands

```bash
# Local Development
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
createdb autodev  # PostgreSQL required

# Start System (Local)
python dashboard/server.py                    # Dashboard on :8080
python -m watcher.agent_runner --agent pm     # Start specific agent

# Deployment to ECS
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest

# Redeploy ECS services (after push)
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1
# Or redeploy all agents:
for svc in auto-dev-dashboard auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1
done

# View ECS Logs
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm"

# Check deployment status
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0].deployments'
```

## Dashboard URL

```bash
cd terraform && terraform output dashboard_url
# http://auto-dev-alb-588827158.us-east-1.elb.amazonaws.com
```

## Architecture

```
watcher/
├── agent_runner.py    # Spawns agent processes, manages LLM sessions
├── orchestrator_pg.py # PostgreSQL orchestrator (primary, used by all components)
├── orchestrator.py    # SQLite orchestrator (legacy fallback, not used in production)
├── reflection.py      # Agent learning/improvement system
├── scheduler.py       # Cron-based job scheduling
└── memory.py          # Short-term (SQLite) + long-term (Qdrant) memory

integrations/
├── gitlab_client.py   # GitLab API wrapper
└── gitlab_webhook.py  # Webhook event handler

dashboard/
├── server.py          # FastAPI app (uses orchestrator_pg)
├── repos.py           # Multi-repo management
└── slack_bot.py       # Slack integration
```

## Database

PostgreSQL is the primary database. All components (dashboard, agents, scheduler) use `orchestrator_pg.py` which auto-detects the database from environment variables:

- `DB_HOST` - PostgreSQL host (e.g., `postgres`)
- `DB_NAME` - Database name (default: `autodev`)
- `DB_USER` - Database user (default: `autodev`)
- `DB_PASSWORD` - Database password

If `DB_HOST` is not set, falls back to SQLite at `/auto-dev/data/orchestrator.db`.

## Agent Workflow

```
PM → Architect → [Human Approval] → Builder → Reviewer/Tester/Security (parallel) → [Human Approval] → DevOps
```

| Agent | Task Types | Purpose |
|-------|------------|---------|
| PM | analyze_repo, create_epic, create_user_story, prioritize_backlog, triage_issue | Backlog management |
| Architect | evaluate_feasibility, write_spec, create_implementation_issue | Solution design |
| Builder | implement_feature, implement_fix, implement_refactor, address_review_feedback | Code implementation |
| Reviewer | review_mr | Code review |
| Tester | write_tests, run_tests, validate_feature, analyze_coverage | Quality assurance |
| Security | security_scan, dependency_audit, compliance_check | Security scanning |
| DevOps | manage_pipeline, deploy, rollback, fix_build | CI/CD management |
| Bug Finder | static_analysis, bug_hunt | Proactive bug detection |

## Key Files

- `config/settings.yaml` - Main configuration (agents, LLM providers, autonomy settings)
- `config/agents/*.md` - Individual agent prompts
- `POLICY.md` - Authoritative policy (approval gates, scope limits)
- `ARCHITECTURE.md` - Detailed system architecture
- `OPERATIONS.md` - ECS/AWS operations guide (deployment, monitoring, troubleshooting)

## LLM Providers

Default: Codex (gpt-4.1). Fallback: Claude. Auto-switches on rate limits.

```bash
AUTODEV_LLM_PROVIDER=claude ./scripts/start_agents.sh  # Manual override
```

## Autonomy Modes

- **Guided** (default): Human approval at spec and merge points
- **Full**: Auto-approve if thresholds met (architect_confidence>=8, reviewer_score>=9, coverage>=80%)

Credentials in AWS SSM under `/auto-dev/{repo-slug}/`
