# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Auto-Dev is an autonomous software development system that uses 8 AI agents to develop software on GitLab repositories. Uses Codex (primary) with Claude as fallback. Agents handle the full lifecycle: analysis, specs, implementation, review, testing, security, deployment.

## Commands

```bash
# Local Development
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
createdb autodev  # PostgreSQL required

# Start System
python dashboard/server.py                    # Dashboard on :8080
python watcher/supervisor.py --agent pm       # Start specific agent

# Deployment
cd terraform && terraform output              # Get EC2 info
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.git' \
  -e "ssh -i ~/.ssh/<key>.pem" . ubuntu@<IP>:/auto-dev/

# On EC2
./scripts/start_agents.sh status              # Check agents
./scripts/start_agents.sh                     # Start all
./scripts/start_agents.sh stop                # Stop all
tmux attach -t claude-<agent>                 # View session (Ctrl+B, D detach)
```

## Architecture

```
watcher/
├── supervisor.py      # Spawns agent processes, manages tmux sessions
├── orchestrator_pg.py # PostgreSQL task queue (primary)
├── orchestrator.py    # SQLite fallback
├── reflection.py      # Agent learning/improvement system
├── scheduler.py       # Cron-based job scheduling
└── memory.py          # Short-term (SQLite) + long-term (Qdrant) memory

integrations/
├── gitlab_client.py   # GitLab API wrapper
└── gitlab_webhook.py  # Webhook event handler

dashboard/
├── server.py          # FastAPI app
├── repos.py           # Multi-repo management
└── slack_bot.py       # Slack integration
```

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
- `OPERATIONS.md` - EC2/AWS operations guide

## LLM Providers

Default: Codex (gpt-4.1). Fallback: Claude. Auto-switches on rate limits.

```bash
AUTODEV_LLM_PROVIDER=claude ./scripts/start_agents.sh  # Manual override
```

## Autonomy Modes

- **Guided** (default): Human approval at spec and merge points
- **Full**: Auto-approve if thresholds met (architect_confidence>=8, reviewer_score>=9, coverage>=80%)

Credentials in AWS SSM under `/auto-dev/{repo-slug}/`
