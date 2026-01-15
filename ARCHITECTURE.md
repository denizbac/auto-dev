# Auto-Dev - Architecture

## Overview

Auto-Dev is an autonomous software development system that uses 8 specialized AI agents to develop software on GitLab repositories. The system runs on **AWS ECS (Fargate)** with each agent as a separate service, using PostgreSQL for coordination and Redis for agent control.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS ECS CLUSTER                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         AGENT LAYER (8 Agents)                           │   │
│  │                                                                          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │    PM    │ │ Architect│ │ Builder  │ │ Reviewer │                    │   │
│  │  │ (Codex)  │ │ (Codex)  │ │ (Codex)  │ │ (Codex)  │                    │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘                    │   │
│  │       │            │            │            │                           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │  Tester  │ │ Security │ │  DevOps  │ │Bug Finder│                    │   │
│  │  │ (Codex)  │ │ (Codex)  │ │ (Codex)  │ │ (Codex)  │                    │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘                    │   │
│  │       │            │            │            │                           │   │
│  └───────┼────────────┼────────────┼────────────┼───────────────────────────┘   │
│          │            │            │            │            │                  │
│          ▼            ▼            ▼            ▼            ▼                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        AGENT RUNNER LAYER                               │   │
│  │                                                                          │   │
│  │  ┌────────────────────────────────────────────────────────────────┐     │   │
│  │  │                     agent_runner.py                             │     │   │
│  │  │  • Spawns LLM CLI workers (Claude/Codex) for each agent        │     │   │
│  │  │  • Runs as Docker containers (one per agent type)              │     │   │
│  │  │  • Health checks & auto-restart on crashes                     │     │   │
│  │  │  • Token budget enforcement                                     │     │   │
│  │  │  • Rate limit detection & provider fallback                    │     │   │
│  │  └────────────────────────────────────────────────────────────────┘     │   │
│  │                                │                                         │   │
│  └────────────────────────────────┼─────────────────────────────────────────┘   │
│                                   │                                             │
│                                   ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        ORCHESTRATOR LAYER                                │   │
│  │                                                                          │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐            │   │
│  │  │Task Queue  │ │ File Lock  │ │  Mailbox   │ │ Discussion │            │   │
│  │  │• Priority  │ │• Prevent   │ │• Inter-    │ │• Debate    │            │   │
│  │  │  queue     │ │  conflicts │ │  agent     │ │• Proposals │            │   │
│  │  │• Task type │ │• Expire &  │ │  messages  │ │• Voting    │            │   │
│  │  │  routing   │ │  cleanup   │ │• Handoffs  │ │• Consensus │            │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘            │   │
│  │                                                                          │   │
│  │  ┌────────────────────────────────────────────────────────────────┐     │   │
│  │  │              Human Approval Queue                               │     │   │
│  │  │  • Products await human review before publishing               │     │   │
│  │  │  • Approve → creates publish task                              │     │   │
│  │  │  • Reject → notifies agents with reason                        │     │   │
│  │  └────────────────────────────────────────────────────────────────┘     │   │
│  │                                                                          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         MEMORY LAYER                                     │   │
│  │                                                                          │   │
│  │  ┌─────────────────────────┐    ┌─────────────────────────┐             │   │
│  │  │   Short-Term Memory     │    │   Long-Term Memory      │             │   │
│  │  │   (SQLite)              │    │   (Qdrant Vector DB)    │             │   │
│  │  │                         │    │                         │             │   │
│  │  │   • Last 50 actions     │    │   • Semantic search     │             │   │
│  │  │   • Recent observations │    │   • Lessons learned     │             │   │
│  │  │   • Income log          │    │   • Successful patterns │             │   │
│  │  │   • Session context     │    │   • Failed approaches   │             │   │
│  │  └─────────────────────────┘    └─────────────────────────┘             │   │
│  │                                                                          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         INTERFACE LAYER                                  │   │
│  │                                                                          │   │
│  │  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────────┐   │   │
│  │  │   Dashboard        │  │   CLI Tools        │  │  Slack Bot       │   │   │
│  │  │   (FastAPI:8080)   │  │                    │  │  (Optional)      │   │   │
│  │  │                    │  │  • claude-swarm    │  │                  │   │   │
│  │  │   • Agent status   │  │  • claude-tasks    │  │  • Notifications │   │   │
│  │  │   • Task queue     │  │  • gumroad-publish │  │  • Commands      │   │   │
│  │  │   • Approval queue │  │                    │  │  • Approvals     │   │   │
│  │  │   • Income stats   │  │                    │  │                  │   │   │
│  │  │   • Memory viewer  │  │                    │  │                  │   │   │
│  │  │   • WebSocket      │  │                    │  │                  │   │   │
│  │  └────────────────────┘  └────────────────────┘  └──────────────────┘   │   │
│  │                                                                          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌───────────────────────────────────────┐  ┌───────────────────────────────┐  │
│  │          Docker (Qdrant)              │  │       Browser (Playwright)    │  │
│  │          Port 6333                    │  │       Headless Chrome         │  │
│  └───────────────────────────────────────┘  └───────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL SERVICES                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Gumroad  │ │  GitHub  │ │   NPM    │ │ Vercel   │ │  Slack   │ │ AWS SSM  │ │
│  │ (Sales)  │ │(Releases)│ │(Packages)│ │(Deploy)  │ │(Notify)  │ │(Secrets) │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Roles & Models

| Agent | LLM Provider | Role | Task Types |
|-------|-------------|------|------------|
| **PM** | Codex | Product Manager - backlog management | `analyze_repo`, `create_epic`, `create_user_story`, `prioritize_backlog`, `triage_issue` |
| **Architect** | Codex | Solution Designer | `evaluate_feasibility`, `write_spec`, `create_implementation_issue` |
| **Builder** | Codex | Implementer | `implement_feature`, `implement_fix`, `implement_refactor`, `address_review_feedback` |
| **Reviewer** | Codex | Code Quality Gate | `review_mr` |
| **Tester** | Codex | QA Engineer | `write_tests`, `run_tests`, `validate_feature`, `analyze_coverage` |
| **Security** | Codex | Security Analyst | `security_scan`, `dependency_audit`, `compliance_check` |
| **DevOps** | Codex | Operations | `manage_pipeline`, `deploy`, `rollback`, `fix_build` |
| **Bug Finder** | Codex | Proactive Bug Detection | `static_analysis`, `bug_hunt` |

**LLM Provider:**
- **Codex** (gpt-4.1) is the primary provider
- **Claude** is available as fallback when rate limited
- Auto-switches on rate limits via `AUTODEV_LLM_PROVIDER` environment variable

---

## Development Workflow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DEVELOPMENT PIPELINE                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

PM → Architect → [Human Approval] → Builder → Reviewer/Tester/Security (parallel) → [Human Approval] → DevOps
```

### Approval Gates

1. **Spec Approval**: Human reviews architect's spec before implementation begins
2. **Reviewer Gate**: Code review for security, quality, maintainability
3. **Tester Gate**: Tests must pass with required coverage
4. **Security Gate**: No critical vulnerabilities
5. **Merge Approval**: Human approves merge request before deployment

### Autonomy Modes

- **Guided** (default): Human approval required at spec and merge points
- **Full Autonomy**: Auto-approve if thresholds met (architect_confidence>=8, reviewer_score>=9, coverage>=80%)

---

## Directory Structure

```
/auto-dev/
├── config/
│   ├── agents/                   # Agent prompts
│   │   ├── pm.md
│   │   ├── architect.md
│   │   ├── builder.md
│   │   ├── reviewer.md
│   │   ├── tester.md
│   │   ├── security.md
│   │   ├── devops.md
│   │   └── bugfinder.md
│   └── settings.yaml             # Main configuration
│
├── dashboard/
│   ├── server.py                 # FastAPI dashboard
│   ├── repos.py                  # Multi-repo management API
│   ├── slack_bot.py              # Slack bot integration
│   └── frontend/                 # React frontend
│
├── data/
│   ├── memory/
│   │   └── short_term.db         # SQLite short-term memory
│   └── orchestrator.db           # SQLite fallback (not used in production)
│
├── integrations/
│   ├── gitlab_client.py          # GitLab API wrapper
│   └── gitlab_webhook.py         # Webhook event handler
│
├── logs/                         # Agent logs
│   ├── pm.log
│   ├── builder.log
│   └── ...
│
├── scripts/
│   ├── start_agents.sh           # Agent management
│   ├── deploy.sh                 # Deploy to EC2
│   └── ...
│
├── terraform/                    # AWS infrastructure
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
│
├── watcher/                      # Core agent system
│   ├── __init__.py
│   ├── agent_runner.py           # Agent process manager
│   ├── orchestrator_pg.py        # PostgreSQL orchestrator (primary)
│   ├── orchestrator.py           # SQLite orchestrator (fallback)
│   ├── scheduler.py              # Cron-based job scheduling
│   ├── reflection.py             # Agent learning system
│   └── memory.py                 # Memory management
│
├── docker-compose.yaml           # Docker services
├── Dockerfile                    # Agent container image
├── README.md
├── ARCHITECTURE.md
├── CLAUDE.md
└── requirements.txt
```

---

## Data Flow

### Task Queue Flow

```
                    ┌─────────────────────────────────────────────────┐
                    │              ORCHESTRATOR (PostgreSQL)           │
                    │                                                  │
                    │  tasks table:                                    │
                    │  ┌─────────────────────────────────────────────┐│
                    │  │ id | task_type | priority | status | agent  ││
                    │  ├─────────────────────────────────────────────┤│
                    │  │ ... | write_spec | 7 | pending | NULL       ││
                    │  │ ... | implement  | 8 | claimed | builder    ││
                    │  └─────────────────────────────────────────────┘│
                    └─────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                │                          │                          │
                ▼                          ▼                          ▼
        ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
        │      PM      │          │    Builder   │          │    DevOps    │
        │              │          │              │          │              │
        │ claim_task() │          │ claim_task() │          │ claim_task() │
        │ task_types:  │          │ task_types:  │          │ task_types:  │
        │ [analyze_*,  │          │ [implement_*,│          │ [deploy,     │
        │  create_*,   │          │  address_*]  │          │  rollback,   │
        │  triage_*]   │          │              │          │  fix_build]  │
        └──────────────┘          └──────────────┘          └──────────────┘
```

### Inter-Agent Communication

```
Agent A                  Orchestrator                  Agent B
   │                          │                          │
   │  send_message()          │                          │
   │ ─────────────────────▶   │                          │
   │  (handoff, request, etc) │                          │
   │                          │                          │
   │                          │  get_messages()          │
   │                          │ ◀─────────────────────   │
   │                          │                          │
   │                          │  message payload         │
   │                          │ ─────────────────────▶   │
   │                          │                          │
   │  post_discussion()       │                          │
   │ ─────────────────────▶   │                          │
   │  ("I think we should...") │                         │
   │                          │                          │
   │                          │  get_discussions()       │
   │                          │ ◀─────────────────────   │
   │                          │                          │
```

### Approval Flow

```
Agent                      Orchestrator                  Human
    │                          │                          │
    │  create_approval()       │                          │
    │ ─────────────────────▶   │                          │
    │  (spec or merge request) │                          │
    │                          │                          │
    │                          │  Dashboard shows pending │
    │                          │ ─────────────────────────▶│
    │                          │                          │
    │                          │  Human reviews           │
    │                          │ ◀─────────────────────────│
    │                          │  approve/reject          │
    │                          │                          │
    │  get_approval_status()   │                          │
    │ ◀─────────────────────   │                          │
    │                          │                          │
    │  if APPROVED:            │                          │
    │  continue to next stage  │                          │
```

---

## Component Details

### Agent Runner (`watcher/agent_runner.py`)

Each agent runs in its own Docker container, managed by the AgentRunner:

```python
class AgentRunner:
    """
    Responsibilities:
    - Spawn LLM CLI worker processes (Claude/Codex)
    - Claim tasks from orchestrator queue
    - Pass task context to LLM via prompts
    - Handle session lifecycle (start, monitor, restart)
    - Enforce token budgets
    - Detect and propagate rate limits
    - Respond to Redis enable/disable signals
    """

    AGENT_TASK_TYPES = {
        'pm': ['analyze_repo', 'create_epic', 'break_down_epic', ...],
        'architect': ['evaluate_feasibility', 'write_spec', ...],
        'builder': ['implement_feature', 'implement_fix', ...],
        'reviewer': ['review_mr'],
        'tester': ['write_tests', 'run_tests', ...],
        'security': ['security_scan', 'dependency_audit', ...],
        'devops': ['manage_pipeline', 'deploy', ...],
        'bug_finder': ['static_analysis', 'bug_hunt'],
        # ...
    }
```

### Orchestrator (`watcher/orchestrator_pg.py`)

Central coordination database (PostgreSQL) with these tables:

| Table | Purpose |
|-------|---------|
| `repos` | Multi-repo management (GitLab projects) |
| `tasks` | Priority queue with claiming, status tracking |
| `approvals` | Human approval queue for specs and merges |
| `agent_status` | Heartbeat, current task, status |
| `reflections` | Agent learning and improvements |
| `learnings` | Accumulated knowledge base |
| `gitlab_objects` | Cached GitLab data |

The orchestrator auto-detects PostgreSQL from `DB_HOST` environment variable and falls back to SQLite if unavailable.

### Memory Systems

**Short-Term (SQLite)**:
- Last 50 actions/observations
- Session context
- Income log
- Pruned on startup

**Long-Term (Qdrant Vector DB)**:
- Semantic search over lessons learned
- Importance-scored memories (1-10)
- Successful patterns, failed approaches
- Uses `all-MiniLM-L6-v2` embeddings

---

## Agent Coordination Features

### Reflection & Learning

Agents learn from their work through the reflection system:
1. **Record** outcomes after completing tasks
2. **Extract** learnings from successful/failed approaches
3. **Retrieve** relevant context before new tasks
4. **Improve** prompts based on accumulated insights

### CLI Tools

```bash
# Agent management
./scripts/start_agents.sh status    # Check agent status
./scripts/start_agents.sh pm        # Start specific agent
./scripts/start_agents.sh stop      # Stop all agents

# View agent activity
tmux attach -t claude-pm            # Live view (Ctrl+B, D to detach)
tail -f logs/pm.log                 # View logs
```

---

## Infrastructure (Terraform)

```
AWS Resources:
├── ECS Cluster (Fargate)
│   ├── 8 Agent Services (PM, Architect, Builder, Reviewer, Tester, Security, DevOps, Bug Finder)
│   ├── Dashboard Service
│   ├── Webhook Service
│   └── Scheduler Service
│
├── Application Load Balancer (ALB)
│   └── Routes traffic to Dashboard
│
├── ECR Repository
│   └── auto-dev:latest Docker image
│
├── EFS File System
│   └── Shared storage for agent workspaces
│
├── Service Discovery (Cloud Map)
│   └── autodev.local namespace
│       ├── postgres.autodev.local
│       └── redis.autodev.local
│
├── SSM Parameter Store
│   └── /auto-dev/{repo-slug}/
│       └── gitlab-token
│
├── ECS Services (supporting)
│   ├── PostgreSQL
│   └── Redis
│
└── GitLab Webhooks (external)
```

### Cost Breakdown (ECS Fargate)

| Component | Monthly Cost |
|-----------|-------------|
| ECS Fargate (11 tasks) | ~$150-200 |
| ALB | ~$20 |
| EFS | ~$10 |
| CloudWatch Logs | ~$5 |
| Data transfer | ~$5-10 |
| Codex Pro | $200 |
| **Total** | **~$400-450/month** |

---

## Quick Reference

### Deploy Changes to ECS
```bash
# Build and push Docker image
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest

# Redeploy all services
for svc in auto-dev-dashboard auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1
done
```

### View Agent Activity
```bash
# CloudWatch Logs
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm"

# List recent log streams
aws logs describe-log-streams --log-group-name /ecs/auto-dev --order-by LastEventTime --descending --limit 10

# Get specific agent logs
aws logs get-log-events --log-group-name /ecs/auto-dev --log-stream-name "pm/pm/<task-id>" --limit 50
```

### Check ECS Status
```bash
# List services
aws ecs list-services --cluster auto-dev --region us-east-1

# Check deployment status
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0].deployments'

# Check events
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0].events[0:5]'
```

### Human Approval
```bash
# Via Dashboard
http://auto-dev-alb-588827158.us-east-1.elb.amazonaws.com → Approval Queue

# Via API
curl -X POST http://auto-dev-alb-588827158.us-east-1.elb.amazonaws.com/api/approvals/<id>/approve
curl -X POST http://auto-dev-alb-588827158.us-east-1.elb.amazonaws.com/api/approvals/<id>/reject \
  -d '{"reason": "Needs more work"}'
```
