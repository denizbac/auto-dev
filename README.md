# Auto-Dev: Autonomous Software Development System

An autonomous AI agent swarm that develops software on GitLab repositories with minimal human intervention. Powered by Codex (with Claude as fallback).

## Overview

Auto-Dev uses 8 specialized AI agents to handle the full software development lifecycle:

| Agent | Role | What They Do |
|-------|------|--------------|
| **PM** | Product Manager | Analyzes repos, creates epics/user stories, prioritizes backlog |
| **Architect** | Solution Designer | Evaluates feasibility, writes specs, creates implementation issues |
| **Builder** | Implementer | Implements features, fixes, and refactors based on specs |
| **Reviewer** | Quality Gate | Reviews merge requests for quality and best practices |
| **Tester** | QA Engineer | Writes tests, runs test suites, validates features |
| **Security** | Security Analyst | Scans for vulnerabilities, audits dependencies |
| **DevOps** | Operations | Manages CI/CD pipelines, deployments, rollbacks |
| **Bug Finder** | Detective | Proactive static analysis and bug detection |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Auto-Dev Dashboard                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │  Repo A     │ │  Repo B     │ │  Repo C     │  + Add    │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     Orchestrator (PostgreSQL)                │
│   Tasks │ Approvals │ Repos │ Reflections │ Learnings      │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │ Agents  │ ←───── │ Codex   │ ─────→ │ GitLab  │
   └─────────┘        └─────────┘        └─────────┘
```

## Agent Workflow

```
Human provides high-level goals
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ PM                                                          │
│  analyze_repo → create_epic → create_user_story →           │
│  prioritize_backlog                                         │
└─────────────────────────────────────────────────────────────┘
         │ User Story (GitLab Issue)
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Architect                                                   │
│  evaluate_feasibility → write_spec →                        │
│  create_implementation_issue                                │
└─────────────────────────────────────────────────────────────┘
         │ Implementation Issue + Spec
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Builder                                                     │
│  implement_feature/fix/refactor → (creates MR)              │
└─────────────────────────────────────────────────────────────┘
         │ Merge Request
         ▼
┌──────────────┬──────────────┬──────────────┐
│   Reviewer   │    Tester    │   Security   │  (parallel)
│   review_mr  │  run_tests   │security_scan │
└──────────────┴──────────────┴──────────────┘
         │ All checks pass
         ▼
┌─────────────────────────────────────────────────────────────┐
│ DevOps                                                      │
│  deploy (merge + deploy to environment)                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Bug Finder (independent, scheduled nightly)                 │
│  static_analysis → creates bug issues → PM prioritizes      │
└─────────────────────────────────────────────────────────────┘
```

## GitLab Object Mapping

| Agent | Creates | GitLab Object | Labels |
|-------|---------|---------------|--------|
| PM | Goals/Initiatives | Epic | `auto-dev` |
| PM | Requirements | Issue | `user-story` |
| Architect | Implementation work | Issue | `implementation` |
| Builder | Code changes | Merge Request | `auto-dev` |
| Bug Finder | Bug reports | Issue | `bug` |
| Security | Vulnerabilities | Issue | `security` |
| Tester | Test failures | Issue | `bug` |

## Key Features

- **Multi-Repo Support**: Manage multiple GitLab repositories from one dashboard
- **Two Autonomy Modes**:
  - **Guided**: Human approval at key points (spec, merge)
  - **Full**: Auto-approve if quality thresholds met
- **GitLab Integration**: Webhooks, issues, epics, MRs, pipelines
- **Reflection System**: Agents learn from their work and improve
- **Spec-Driven Development**: PM defines what → Architect designs how → Builder implements

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL
- GitLab account with API access
- Codex CLI (or Claude CLI as fallback)

### Installation

```bash
# Clone the repo
git clone <repo-url> /path/to/auto-dev
cd /path/to/auto-dev

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up PostgreSQL
createdb autodev

# Configure
cp config/settings.yaml.example config/settings.yaml
# Edit settings.yaml with your configuration
```

### Configuration

Edit `config/settings.yaml`:

```yaml
# LLM Provider (Codex primary)
llm:
  default_provider: "codex"
  fallback_provider: "claude"

# Autonomy mode
autonomy:
  default_mode: "guided"  # or "full"

# Database
database:
  type: "postgresql"
  host: "localhost"
  name: "autodev"
```

### Set Up GitLab Token

```bash
# Store in environment
export GITLAB_TOKEN="your-token"

# Or use AWS SSM (production)
aws ssm put-parameter \
  --name "/auto-dev/your-repo/gitlab-token" \
  --value "your-token" \
  --type SecureString
```

### Start the System

```bash
# Start dashboard
python dashboard/server.py

# Start agents (in separate terminals or use supervisor)
python watcher/supervisor.py --agent pm
python watcher/supervisor.py --agent architect
python watcher/supervisor.py --agent builder
# ... etc for other agents
```

### Add a Repository

1. Open dashboard: `http://localhost:8080`
2. Click "Add Repository"
3. Enter GitLab URL and project ID
4. Configure autonomy mode and settings
5. Set up webhook (dashboard provides URL and secret)

## Agents Detail

### PM (Product Manager)

| Task | Description |
|------|-------------|
| `analyze_repo` | Understand codebase, tech stack, current state |
| `create_epic` | Create GitLab Epic for business initiative |
| `break_down_epic` | Decompose epic into user stories |
| `create_user_story` | Write user story with acceptance criteria |
| `prioritize_backlog` | Score and rank issues by business value |
| `triage_issue` | Categorize and route incoming human issues |

### Architect

| Task | Description |
|------|-------------|
| `evaluate_feasibility` | Assess if user story is technically feasible |
| `write_spec` | Create detailed implementation specification |
| `create_implementation_issue` | Create GitLab issue for Builder |

### Builder

| Task | Description |
|------|-------------|
| `implement_feature` | Build new feature from spec |
| `implement_fix` | Fix a bug |
| `implement_refactor` | Refactor code for improvement |
| `address_review_feedback` | Fix issues from code review |

### Reviewer

| Task | Description |
|------|-------------|
| `review_mr` | Review merge request for quality and correctness |

### Tester

| Task | Description |
|------|-------------|
| `write_tests` | Write unit/integration tests |
| `run_tests` | Execute test suites, report results |
| `validate_feature` | Verify feature meets acceptance criteria |
| `analyze_coverage` | Identify gaps in test coverage |

### Security

| Task | Description |
|------|-------------|
| `security_scan` | SAST scanning for vulnerabilities |
| `dependency_audit` | Check dependencies for CVEs |
| `compliance_check` | Verify security compliance |

### DevOps

| Task | Description |
|------|-------------|
| `manage_pipeline` | Fix or configure CI/CD pipelines |
| `deploy` | Deploy to environment |
| `rollback` | Rollback failed deployment |
| `fix_build` | Fix build failures in CI |

### Bug Finder

| Task | Description |
|------|-------------|
| `static_analysis` | Deep code analysis for bugs |
| `bug_hunt` | Proactive search for issues |

## Workflows

### New Repository Onboarding

```
1. Add repo via dashboard
2. Configure webhook in GitLab
3. PM runs analyze_repo
4. PM creates epics for major initiatives
5. PM breaks down into user stories
6. Work begins flowing through pipeline
```

### Issue-to-Implementation (Guided Mode)

```
Human creates GitLab Issue (or PM creates user story)
    ↓
PM triages and prioritizes
    ↓
Architect evaluates feasibility
    ↓
Architect writes spec
    ↓
[Human Approval] ← spec review
    ↓
Architect creates implementation issue
    ↓
Builder implements, creates MR
    ↓
Reviewer + Tester + Security (parallel)
    ↓
[Human Approval] ← merge review
    ↓
DevOps merges and deploys
```

### Full Autonomy Mode

Same flow but approvals auto-pass if thresholds are met:
- Architect confidence >= 8
- Reviewer score >= 9
- Security severity <= low
- Test coverage >= 80%

## Directory Structure

```
/auto-dev/
├── config/
│   ├── settings.yaml      # Main configuration
│   └── agents/            # Agent prompt files
│       ├── pm.md
│       ├── architect.md
│       ├── builder.md
│       ├── reviewer.md
│       ├── tester.md
│       ├── security.md
│       ├── devops.md
│       └── bug_finder.md
├── integrations/
│   ├── gitlab_client.py   # GitLab API client
│   └── gitlab_webhook.py  # Webhook handler
├── watcher/
│   ├── supervisor.py      # Agent process manager
│   ├── orchestrator_pg.py # Task queue (PostgreSQL)
│   ├── reflection.py      # Learning framework
│   └── memory.py          # Memory systems
├── dashboard/
│   ├── server.py          # FastAPI dashboard
│   └── repos.py           # Repo management API
└── data/
    ├── workspaces/        # Cloned repos
    ├── specs/             # Specifications
    └── memory/            # SQLite databases
```

## Configuration Options

### Autonomy Settings

```yaml
autonomy:
  default_mode: "guided"
  approval_gates:
    issue_creation: true
    spec_approval: true
    merge_approval: true
  auto_approve_thresholds:
    architect_confidence: 8
    reviewer_score: 9
    test_coverage: 80
```

### Safety Limits

```yaml
autonomy:
  safety_limits:
    max_issues_per_day: 10
    max_mrs_per_day: 20
    require_human_for_breaking_changes: true
```

## Reflection & Learning

Agents learn from their work:

1. **Reflections**: After tasks, agents record what worked/didn't
2. **Learnings**: High-confidence insights are extracted
3. **Prompt Suggestions**: Agents can suggest improvements to their prompts
4. **Context Injection**: Relevant learnings are provided before new tasks

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/repos` | List repositories |
| `POST /api/repos` | Add repository |
| `GET /api/repos/{id}` | Get repository details |
| `PUT /api/repos/{id}` | Update repository |
| `GET /api/repos/{id}/webhook` | Get webhook setup info |
| `GET /api/repos/{id}/tasks` | Get repo tasks |
| `GET /api/repos/{id}/stats` | Get repo statistics |
| `POST /api/repos/{id}/trigger` | Trigger analysis |
| `GET /api/tasks` | List all tasks |
| `GET /api/approvals` | Pending approvals |
| `POST /webhook/gitlab/{repo_id}` | GitLab webhook |

## Troubleshooting

### Agent not starting
```bash
# Check Codex CLI
codex --version

# Check authentication
codex login status
```

### Webhook not receiving events
```bash
# Verify webhook URL is accessible
curl https://your-server/webhook/gitlab

# Check GitLab webhook configuration
# Project → Settings → Webhooks
```

### Database connection issues
```bash
# Check PostgreSQL is running
pg_isready

# Test connection
psql -d autodev -c "SELECT 1"
```

## Issue Permissions

| Agent | Create | Close |
|-------|--------|-------|
| PM | Epic, User Story | Yes (won't fix, duplicate) |
| Architect | Implementation Issue | No |
| Builder | - | No (MR merge closes) |
| Bug Finder | Bug Issue | No |
| Security | Vulnerability Issue | No |
| Tester | Bug Issue | No |
| DevOps | - | Yes (verified complete) |

## License

MIT

## Acknowledgments

- Forked from [auto-claude](https://github.com/...)
- Uses Codex CLI for AI operations
