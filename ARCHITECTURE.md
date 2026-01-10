# Autonomous Claude Swarm - Architecture

## Overview

This is a self-organizing AI agent swarm designed to autonomously generate income through digital products, services, and content. The system runs on AWS EC2 with 10 specialized agents that collaborate, debate, and evolve together.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS EC2 INSTANCE                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         AGENT LAYER (10 Agents)                          │   │
│  │                                                                          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │  Hunter  │ │  Critic  │ │    PM    │ │ Builder  │ │ Reviewer │      │   │
│  │  │(Sonnet)  │ │ (Opus)   │ │(Sonnet)  │ │ (Opus)   │ │ (Opus)   │      │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘      │   │
│  │       │            │            │            │            │             │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │  Tester  │ │Publisher │ │   Meta   │ │ Liaison  │ │ Support  │      │   │
│  │  │ (Opus)   │ │(Sonnet)  │ │(Sonnet)  │ │(Sonnet)  │ │(Sonnet)  │      │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘      │   │
│  │       │            │            │            │            │             │   │
│  └───────┼────────────┼────────────┼────────────┼────────────┼─────────────┘   │
│          │            │            │            │            │                  │
│          ▼            ▼            ▼            ▼            ▼                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         SUPERVISOR LAYER                                 │   │
│  │                                                                          │   │
│  │  ┌────────────────────────────────────────────────────────────────┐     │   │
│  │  │                     supervisor.py                               │     │   │
│  │  │  • Spawns LLM CLI workers (Claude/Codex) for each agent        │     │   │
│  │  │  • Manages tmux sessions (claude-{agent})                      │     │   │
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

| Agent | Model | Role | Task Types |
|-------|-------|------|------------|
| **Hunter** | Sonnet | Scans platforms for opportunities | `scan_platform`, `research` |
| **Critic** | Opus | Gatekeeper - evaluates ideas | `evaluate_idea` |
| **PM** | Sonnet | Creates detailed product specs | `write_spec` |
| **Builder** | Opus | Creates products and fixes issues | `build_product`, `fix_product` |
| **Reviewer** | Opus | Code review for security/quality | `code_review` |
| **Tester** | Opus | 3-phase QA validation | `test_product` |
| **Publisher** | Sonnet | Deploys and markets products | `deploy`, `publish`, `market` |
| **Meta** | Sonnet | Swarm architect - implements proposals | `implement_proposal` |
| **Liaison** | Sonnet | Human interface | `respond_to_human`, `directive` |
| **Support** | Sonnet | Monitors GitHub/npm feedback | `monitor_github`, `triage_issue` |

**Model Selection Rationale:**
- **Opus** for agents requiring deep reasoning: Critic (strategic judgment), Builder (complex coding), Reviewer (security), Tester (thorough validation)
- **Sonnet** for agents with more structured/execution-focused work

---

## Product Workflow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              PRODUCT PIPELINE                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  Hunter → Critic → PM → Human Approval → Builder → Reviewer → Tester → Human Approval → Publisher
```

### Quality Gates

1. **Critic Gate**: Blocks bad ideas, bounty work, external contributions
2. **Reviewer Gate**: Code review for security, quality, maintainability
3. **Tester Gate**: Build verification → Functional testing → Customer experience
4. **Human Gate**: Required before building and before publishing

---

## Directory Structure

```
/autonomous-claude/
├── bin/                          # CLI tools
│   ├── claude-swarm              # Swarm communication
│   ├── claude-tasks              # Task management
│   └── gumroad-publish           # Publish to Gumroad
│
├── config/
│   ├── agents/                   # Agent prompts
│   │   ├── hunter.md
│   │   ├── critic.md
│   │   ├── pm.md
│   │   ├── builder.md
│   │   ├── reviewer.md
│   │   ├── tester.md
│   │   ├── publisher.md
│   │   ├── meta.md
│   │   ├── liaison.md
│   │   ├── support.md
│   │   ├── SWARM_BEHAVIORS.md    # Shared swarm behaviors
│   │   ├── QUALITY_GATE.md       # Quality gate rules
│   │   └── TEST_FIX_LOOP.md      # Test/fix loop rules
│   ├── master_prompt.md          # Master agent instructions
│   ├── settings.yaml             # Main configuration
│   └── secrets/                  # Local secrets (not in git)
│
├── dashboard/
│   ├── server.py                 # FastAPI dashboard
│   ├── slack_bot.py              # Slack bot integration
│   └── slack_notifications.py    # Slack notification helpers
│
├── data/
│   ├── memory/
│   │   └── short_term.db         # SQLite short-term memory
│   ├── orchestrator.db           # Orchestrator database
│   ├── projects/                 # Agent workspace for products
│   ├── specs/                    # Product specifications (PM)
│   ├── screenshots/              # Browser screenshots
│   └── income/                   # Income records
│
├── logs/                         # Agent logs
│   ├── hunter.log
│   ├── builder.log
│   └── ...
│
├── memory/
│   └── long_term/                # Markdown learning files
│
├── scripts/
│   ├── start_agents.sh           # Agent management
│   ├── deploy.sh                 # Deploy to EC2
│   ├── github_monitor.py         # GitHub issue monitor
│   └── ...
│
├── skills/                       # Reusable skill patterns
│   ├── freelance_upwork.md
│   ├── micro_saas.md
│   └── gumroad_publish.md
│
├── templates/
│   └── product_spec.md           # Spec template for PM
│
├── terraform/                    # AWS infrastructure
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
│
├── watcher/                      # Core supervisor system
│   ├── __init__.py
│   ├── supervisor.py             # Agent process manager
│   ├── orchestrator.py           # Multi-agent coordination
│   ├── memory.py                 # Memory management
│   └── gumroad_publisher.py      # Gumroad integration
│
├── downloads/                    # Built products ready for sale
├── README.md
├── OPERATIONS.md
└── requirements.txt
```

---

## Data Flow

### Task Queue Flow

```
                    ┌─────────────────────────────────────────────────┐
                    │              ORCHESTRATOR (SQLite)               │
                    │                                                  │
                    │  tasks table:                                    │
                    │  ┌─────────────────────────────────────────────┐│
                    │  │ id | type | priority | status | assigned_to ││
                    │  ├─────────────────────────────────────────────┤│
                    │  │ ... | evaluate_idea | 7 | pending | NULL    ││
                    │  │ ... | build_product | 8 | claimed | builder ││
                    │  └─────────────────────────────────────────────┘│
                    └─────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                │                          │                          │
                ▼                          ▼                          ▼
        ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
        │    Hunter    │          │    Builder   │          │   Publisher  │
        │              │          │              │          │              │
        │ claim_task() │          │ claim_task() │          │ claim_task() │
        │ task_types:  │          │ task_types:  │          │ task_types:  │
        │ [scan_*]     │          │ [build_*]    │          │ [deploy,     │
        │              │          │              │          │  publish,    │
        │              │          │              │          │  market]     │
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

### Proposal & Voting Flow

```
Any Agent                  Orchestrator                 All Agents
    │                          │                          │
    │  create_proposal()       │                          │
    │ ─────────────────────▶   │                          │
    │  ("New Researcher agent")│                          │
    │                          │                          │
    │                          │  get_open_proposals()    │
    │                          │ ◀────────────────────────│
    │                          │                          │
    │                          │                          │
    │                          │  vote_proposal()         │
    │                          │ ◀────────────────────────│
    │                          │                          │
    │                          │  check_consensus()       │
    │                          │  (quorum=3, threshold=60%)
    │                          │                          │
    │                          │  if APPROVED:            │
    │                          │  notify agents           │
    │                          │ ─────────────────────▶   │
    │                          │                          │
    │                          │  Meta implements         │
    │                          │ ◀────────────────────────│
```

---

## Component Details

### Supervisor (`watcher/supervisor.py`)

Each agent runs as a separate process managed by the supervisor:

```python
class AutonomousClaudeWatcher:
    """
    Responsibilities:
    - Spawn LLM CLI worker processes (Claude/Codex)
    - Claim tasks from orchestrator queue
    - Pass task context to Claude via prompts
    - Handle session lifecycle (start, monitor, restart)
    - Enforce token budgets
    - Detect and propagate rate limits
    """
    
    AGENT_TASK_TYPES = {
        'hunter': ['scan_platform', 'research'],
        'critic': ['evaluate_idea'],
        'pm': ['write_spec'],
        'builder': ['build_product', 'fix_product'],
        'reviewer': ['code_review'],
        'tester': ['test_product'],
        'publisher': ['deploy', 'publish', 'market'],
        # ...
    }
```

### Orchestrator (`watcher/orchestrator.py`)

Central coordination database with these tables:

| Table | Purpose |
|-------|---------|
| `tasks` | Priority queue with claiming, status tracking |
| `file_locks` | Prevent concurrent file edits |
| `agent_mail` | Inter-agent messages |
| `agent_status` | Heartbeat, current task, tokens used |
| `discussions` | Threaded debate forum |
| `proposals` | Swarm change proposals |
| `votes` | Track voting (prevent duplicates) |
| `approval_queue` | Human approval before publishing |
| `token_usage` | Token tracking per agent |
| `processed_issues` | GitHub/npm issues (Support agent) |

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

## Swarm Intelligence Features

### Emergent Behaviors

Agents don't just follow orders - they:
1. **Discuss** strategies and observations
2. **Propose** new agents, pivots, rule changes
3. **Vote** on proposals (60% threshold, 3 quorum)
4. **Debate** before building controversial features

### CLI Tools

```bash
# Discussion
claude-swarm discuss "hunter" "Market insight: templates are dead"
claude-swarm discuss --recent

# Proposals
claude-swarm propose new_agent "Researcher" "We need market validation"
claude-swarm proposals

# Voting
claude-swarm vote <proposal_id> for "Agreed - we need this"

# Tasks
claude-tasks list
claude-tasks create --type evaluate_idea --priority 7 --payload '{...}'
```

---

## Infrastructure (Terraform)

```
AWS Resources:
├── EC2 Instance (t3.medium)
│   ├── Ubuntu 22.04
│   ├── 50GB gp3 EBS
│   └── Security Group (SSH + 8080)
│
├── SSM Parameter Store
│   └── /autonomous-claude/
│       ├── gumroad/email
│       ├── gumroad/password
│       ├── github/token
│       ├── npm/token
│       └── vercel/token
│
└── (Optional) Redis for high-performance queue
```

### Cost Breakdown

| Component | Monthly Cost |
|-----------|-------------|
| EC2 t3.medium | ~$30 |
| EBS 50GB gp3 | ~$4 |
| Data transfer | ~$5-10 |
| Claude (Max subscription) | $100 |
| **Total** | **~$140/month** |

---

## Quick Reference

### Start/Stop Agents
```bash
./scripts/start_agents.sh           # Start all
./scripts/start_agents.sh status    # Check status
./scripts/start_agents.sh stop      # Stop all
./scripts/start_agents.sh hunter    # Start one
```

### View Agent Activity
```bash
tmux attach -t claude-hunter        # Live view (Ctrl+B, D to detach)
tail -f logs/hunter.log             # Tail logs
```

### Deploy Changes
```bash
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.git' \
  -e "ssh -i ~/.ssh/<key>.pem" \
  . ubuntu@<EC2_IP>:/autonomous-claude/
```

### Human Approval
```bash
# Via Dashboard
http://<EC2_IP>:8080 → Approval Queue

# Via API
curl -X POST http://localhost:8080/api/approvals/<id>/approve
curl -X POST http://localhost:8080/api/approvals/<id>/reject \
  -d '{"reason": "Needs more work"}'
```
