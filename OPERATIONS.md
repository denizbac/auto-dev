# Autonomous Claude Swarm - Operations Guide

This document explains how to manage the autonomous AI swarm running on EC2.

## Quick Reference

```bash
# === CONNECTION ===
cd terraform && terraform output          # Get EC2 info
ssh -i ~/.ssh/<key>.pem ubuntu@<EC2_IP>   # SSH in

# === AGENT MANAGEMENT (on EC2) ===
cd /autonomous-claude
./scripts/start_agents.sh status    # Check all agents
./scripts/start_agents.sh           # Start all agents
./scripts/start_agents.sh stop      # Stop all agents
./scripts/start_agents.sh hunter    # Start specific agent
tmux attach -t claude-hunter        # View live (Ctrl+B, D to detach)
tail -f logs/hunter.log             # View logs

# === AWS CLI ===
aws ec2 start-instances --instance-ids <ID>   # Start EC2
aws ec2 stop-instances --instance-ids <ID>    # Stop EC2 (saves $)
aws ssm get-parameters-by-path --path "/autonomous-claude" --query "Parameters[].Name"

# === DASHBOARD ===
http://<EC2_IP>:8080
```

---

## 1. Connecting to EC2

### Get Connection Details

```bash
cd /Users/denizbac/Dev/auto-claude/terraform
terraform output
```

Output:
```
dashboard_url = "http://X.X.X.X:8080"
public_ip = "X.X.X.X"
ssh_command = "ssh -i ~/.ssh/your-key.pem ubuntu@X.X.X.X"
```

### SSH In

```bash
# Use the ssh_command from terraform output
ssh -i ~/.ssh/<your-key>.pem ubuntu@<EC2_IP>
```

---

## 2. Agent Management

### Check Status

```bash
cd /autonomous-claude
./scripts/start_agents.sh status
```

Output:
```
═══════════════════════════════════════════════════════════════
                    AGENT STATUS
═══════════════════════════════════════════════════════════════

AGENT           STATUS     SESSION
───────────────────────────────────────────────────────────────
hunter          RUNNING    claude-hunter
critic          RUNNING    claude-critic
pm              RUNNING    claude-pm
builder         RUNNING    claude-builder
reviewer        RUNNING    claude-reviewer
tester          RUNNING    claude-tester
publisher       RUNNING    claude-publisher
meta            RUNNING    claude-meta
liaison         RUNNING    claude-liaison
support         RUNNING    claude-support
```

### Start Agents

```bash
# Start all agents
./scripts/start_agents.sh

# Start specific agent
./scripts/start_agents.sh hunter
./scripts/start_agents.sh builder
./scripts/start_agents.sh publisher
```

### Stop Agents

```bash
# Stop all agents
./scripts/start_agents.sh stop

# Stop specific agent
./scripts/start_agents.sh stop hunter
```

### Restart Agent

```bash
./scripts/start_agents.sh stop hunter
./scripts/start_agents.sh hunter
```

---

## 3. Viewing Agent Activity

### Attach to Live Session

Each agent runs in a tmux session. You can watch them work in real-time:

```bash
# Attach to agent session
tmux attach -t claude-hunter

# Detach (keep agent running): Ctrl+B, then D
# Kill session (stops agent): Ctrl+C
```

### View Logs

```bash
# Live tail
tail -f /autonomous-claude/logs/hunter.log

# Last 100 lines
tail -100 /autonomous-claude/logs/builder.log

# Search logs
grep "ERROR" /autonomous-claude/logs/*.log
grep "income" /autonomous-claude/logs/*.log
```

### List All tmux Sessions

```bash
tmux ls
```

---

## 4. Dashboard

### Access

```bash
# Get URL
cd terraform && terraform output dashboard_url
```

Open in browser: `http://<EC2_IP>:8080`

### Dashboard Features

- **Agent Status**: See which agents are running
- **Task Queue**: Pending, in-progress, completed tasks
- **Approval Queue**: Products waiting for human review
- **Income Tracking**: Revenue by source
- **Memory Viewer**: Recent agent memories

### Restart Dashboard

```bash
# Via systemd
sudo systemctl restart autonomous-claude-dashboard

# Or manually
cd /autonomous-claude/dashboard
source ../venv/bin/activate
python server.py
```

---

## 5. Task Management

### View Tasks

```bash
cd /autonomous-claude
source venv/bin/activate

# Using CLI
./bin/claude-tasks list
./bin/claude-tasks list --status pending
./bin/claude-tasks list --status completed
```

### Create Task Manually

```bash
./bin/claude-tasks create \
  --type build_product \
  --priority 8 \
  --payload '{"idea": "Stripe webhook handler", "target": "gumroad"}'
```

### Task Types

| Type | Handled By | Description |
|------|-----------|-------------|
| `scan_platform` | Hunter | Scan for opportunities |
| `evaluate_idea` | Critic | Evaluate idea viability |
| `write_spec` | PM | Create product specification |
| `build_product` | Builder | Build a product |
| `code_review` | Reviewer | Code review before testing |
| `test_product` | Tester | Three-phase QA validation |
| `fix_product` | Builder | Fix issues found in review/testing |
| `deploy` | Publisher | Deploy to platform |
| `publish` | Publisher | Human-approved publish |

### Product Workflow

```
Hunter → Critic → PM → Human Approval → Builder → Reviewer → Tester → Human Approval → Publisher
```

**Key Quality Gates:**
1. **Critic**: Blocks bounties, external contributions, bad ideas
2. **Reviewer**: Code review for security, quality, maintainability  
3. **Tester**: Build verification + Functional testing + Customer experience
4. **Human Approval**: Required before building and before publishing

---

## 6. Swarm Communication

### View Discussions

```bash
./bin/claude-swarm discuss --recent
./bin/claude-swarm discuss --topic "market-strategy"
```

### View Proposals

```bash
./bin/claude-swarm proposals
./bin/claude-swarm proposals --approved
```

### Swarm Status

```bash
./bin/claude-swarm status
```

---

## 7. Human Approval Queues

**Projects cannot be built and products cannot be published without human approval.**

### Project Proposals (Pre-Build Approval)

1. Open dashboard: `http://<EC2_IP>:8080/projects`
2. Review the proposal details, spec, and ratings
3. Approve/Reject/Defer as needed

API options:
```bash
curl -X POST http://localhost:8080/api/projects/<id>/approve
curl -X POST http://localhost:8080/api/projects/<id>/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Not worth building right now"}'
curl -X POST http://localhost:8080/api/projects/<id>/defer \
  -H "Content-Type: application/json" \
  -d '{"notes": "Revisit next quarter"}'
```

### Publishing Approval Queue

1. Open dashboard: `http://<EC2_IP>:8080`
2. Go to "Approval Queue" section
3. Review product details and files

### Review Product Files

```bash
# On EC2, check product directory
ls -la /autonomous-claude/data/projects/

# Review specific product
cat /autonomous-claude/data/projects/<product-name>/README.md
cat /autonomous-claude/data/projects/<product-name>/GUMROAD_LISTING.md
```

### Approve/Reject via API

```bash
# Approve (creates publish task)
curl -X POST http://localhost:8080/api/approvals/<id>/approve

# Reject
curl -X POST http://localhost:8080/api/approvals/<id>/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Not ready - needs more documentation"}'
```

---

## 8. Deploying Code Changes

### From Local to EC2

```bash
# Option 1: rsync
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.git' \
  --exclude 'data' --exclude 'logs' --exclude '*.pyc' \
  -e "ssh -i ~/.ssh/<key>.pem" \
  /Users/denizbac/Dev/auto-claude/ \
  ubuntu@<EC2_IP>:/autonomous-claude/

# Option 2: Use deploy script (if configured)
./scripts/deploy.sh
```

### After Deployment

```bash
# SSH into EC2
ssh -i ~/.ssh/<key>.pem ubuntu@<EC2_IP>

# Restart agents to pick up changes
cd /autonomous-claude
./scripts/start_agents.sh stop
./scripts/start_agents.sh
```

### Deploy Specific Files

```bash
# Just agent prompts
scp -i ~/.ssh/<key>.pem config/agents/*.md ubuntu@<EC2_IP>:/autonomous-claude/config/agents/

# Just watcher code
scp -i ~/.ssh/<key>.pem watcher/*.py ubuntu@<EC2_IP>:/autonomous-claude/watcher/
```

---

## 9. Troubleshooting

### Agent Won't Start

```bash
# Check Claude CLI auth
claude auth status

# If not authenticated:
claude auth login

# Check for errors in logs
tail -50 /autonomous-claude/logs/<agent>.log

# Check Python dependencies
source venv/bin/activate
pip install -r requirements.txt
```

### Qdrant Not Running

```bash
# Check Docker
docker ps | grep qdrant

# Restart Qdrant
docker restart qdrant

# Check Qdrant logs
docker logs qdrant
```

### Out of Memory

```bash
# Check memory
free -h

# Clear old logs
rm /autonomous-claude/logs/*.log

# Restart agents with fresh state
./scripts/start_agents.sh stop
./scripts/start_agents.sh
```

### Agent Stuck

```bash
# Kill and restart specific agent
./scripts/start_agents.sh stop hunter
./scripts/start_agents.sh hunter
```

### Dashboard 502/Connection Refused

```bash
# Check if running
sudo systemctl status autonomous-claude-dashboard

# Check port
sudo lsof -i :8080

# Restart
sudo systemctl restart autonomous-claude-dashboard
```

---

## 10. Configuration

### Main Config

File: `/autonomous-claude/config/settings.yaml`

Key settings:
```yaml
tokens:
  daily_budget: 0        # 0 = unlimited (Claude Max)
  session_max: 200000

watcher:
  max_session_duration: 3600   # 1 hour per session
  restart_delay: 10
```

LLM provider switching:
```yaml
llm:
  default_provider: "claude"
  fallback_provider: "codex"
  auto_fallback_on_rate_limit: true
  manual_override_env: "SWARM_LLM_PROVIDER"
```
When Claude hits a rate limit, agents will automatically use the fallback provider until the reset time.

Manual switchover (requires restart of agents):
```bash
SWARM_LLM_PROVIDER=codex ./scripts/start_agents.sh stop
SWARM_LLM_PROVIDER=codex ./scripts/start_agents.sh
```

Per-agent override (optional):
```yaml
agents:
  builder:
    provider: "codex"
```

Codex login (device auth, no API key):
```bash
codex login --device-auth
codex login status
```

Codex CLI notes:
- Codex runs via `codex exec --json` under the hood.
- Agents run with `--dangerously-bypass-approvals-and-sandbox` and `--skip-git-repo-check`.

### Agent Prompts

Directory: `/autonomous-claude/config/agents/`

Files:
- `hunter.md` - Opportunity scanning (NO bounties/external repos)
- `critic.md` - Idea evaluation (gatekeeper)
- `pm.md` - Product specification
- `builder.md` - Product creation (NO research/external repos)
- `reviewer.md` - Code review (security, quality, maintainability)
- `tester.md` - Three-phase QA (build, functional, customer experience)
- `publisher.md` - Deployment and marketing
- `meta.md` - Swarm evolution
- `liaison.md` - Human interface
- `support.md` - GitHub/npm issue monitoring

---

## 11. Credentials

Credentials are stored in AWS SSM Parameter Store:

```bash
# View stored credentials
aws ssm get-parameters-by-path --path "/autonomous-claude" --query "Parameters[].Name"

# Add/update credential
aws ssm put-parameter \
  --name "/autonomous-claude/gumroad/email" \
  --value "your@email.com" \
  --type "SecureString" \
  --overwrite
```

Required for publishing:
- `/autonomous-claude/gumroad/email`
- `/autonomous-claude/gumroad/password`
- `/autonomous-claude/github/token`
- `/autonomous-claude/npm/token`
- `/autonomous-claude/vercel/token`
- `/autonomous-claude/apify/api_key`

Optional (Codex fallback):
- `/autonomous-claude/openai/api_key` (only if you want API-key auth instead of device login)

---

## 12. AWS CLI Management

### Check AWS CLI Setup

```bash
# Verify AWS CLI is configured
aws sts get-caller-identity

# If not configured:
aws configure
# Enter: Access Key, Secret Key, Region (us-east-1), Output (json)
```

### EC2 Instance Control

```bash
# Get instance ID from terraform
cd terraform && terraform output instance_id

# Check instance status
aws ec2 describe-instance-status --instance-ids <INSTANCE_ID>

# Quick status check
aws ec2 describe-instances --instance-ids <INSTANCE_ID> \
  --query 'Reservations[0].Instances[0].State.Name' --output text

# Start instance
aws ec2 start-instances --instance-ids <INSTANCE_ID>

# Stop instance (SAVES MONEY when not using!)
aws ec2 stop-instances --instance-ids <INSTANCE_ID>

# Reboot instance
aws ec2 reboot-instances --instance-ids <INSTANCE_ID>

# Get current public IP
aws ec2 describe-instances --instance-ids <INSTANCE_ID> \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

### SSM Parameter Store (Credentials)

```bash
# List all credentials
aws ssm get-parameters-by-path \
  --path "/autonomous-claude" \
  --query "Parameters[].Name" \
  --output table

# Get specific credential (decrypted)
aws ssm get-parameter \
  --name "/autonomous-claude/gumroad/email" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text

# Store new credential
aws ssm put-parameter \
  --name "/autonomous-claude/stripe/secret_key" \
  --value "sk_live_xxx" \
  --type "SecureString"

# Update existing credential
aws ssm put-parameter \
  --name "/autonomous-claude/gumroad/password" \
  --value "new_password" \
  --type "SecureString" \
  --overwrite

# Delete credential
aws ssm delete-parameter --name "/autonomous-claude/old/credential"

# Check if credential exists
aws ssm get-parameter --name "/autonomous-claude/gumroad/email" \
  --query "Parameter.Name" --output text 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

### Security Groups

```bash
# Get security group ID
cd terraform && terraform output security_group_id

# List current rules
aws ec2 describe-security-groups \
  --group-ids <SG_ID> \
  --query "SecurityGroups[0].IpPermissions"

# Add your IP for SSH access
MY_IP=$(curl -s ifconfig.me)
aws ec2 authorize-security-group-ingress \
  --group-id <SG_ID> \
  --protocol tcp \
  --port 22 \
  --cidr ${MY_IP}/32

# Add your IP for dashboard access
aws ec2 authorize-security-group-ingress \
  --group-id <SG_ID> \
  --protocol tcp \
  --port 8080 \
  --cidr ${MY_IP}/32

# Remove overly permissive rule
aws ec2 revoke-security-group-ingress \
  --group-id <SG_ID> \
  --protocol tcp \
  --port 8080 \
  --cidr 0.0.0.0/0
```

### Cost Management

```bash
# Check current month AWS costs
aws ce get-cost-and-usage \
  --time-period Start=$(date -v1d +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost

# Instance cost breakdown
aws ce get-cost-and-usage \
  --time-period Start=$(date -v-7d +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Compute Cloud - Compute"]}}' \
  --metrics BlendedCost
```

### Terraform Commands

```bash
cd terraform

# View current infrastructure state
terraform show

# Get all outputs (IP, SSH command, etc.)
terraform output

# Preview changes before applying
terraform plan

# Apply infrastructure changes
terraform apply

# Destroy everything (CAREFUL!)
terraform destroy
```

---

## 13. Monitoring

### Quick Health Check

```bash
# All agents running?
./scripts/start_agents.sh status

# Recent errors?
grep -i error logs/*.log | tail -20

# Tasks processing?
./bin/claude-tasks list --status pending | wc -l

# Income generated?
# Check dashboard or:
sqlite3 data/memory/short_term.db "SELECT * FROM income_log ORDER BY id DESC LIMIT 10;"
```

### Set Up Alerts (Optional)

```bash
# Simple cron check - add to crontab
*/5 * * * * /autonomous-claude/scripts/health_check.sh >> /var/log/claude-health.log
```

---

## Summary Commands

```bash
# === GET EC2 INFO ===
cd terraform && terraform output

# === SSH INTO EC2 ===
ssh -i ~/.ssh/<key>.pem ubuntu@<IP>

# === AGENT MANAGEMENT (on EC2) ===
./scripts/start_agents.sh status        # Check status
./scripts/start_agents.sh               # Start all
./scripts/start_agents.sh stop          # Stop all
./scripts/start_agents.sh hunter        # Start one

# === VIEW AGENT ACTIVITY ===
tmux attach -t claude-hunter            # Live view (Ctrl+B,D to detach)
tail -f logs/hunter.log                 # View logs
http://<IP>:8080                        # Dashboard

# === TASK MANAGEMENT ===
./bin/claude-tasks list                 # View tasks
./bin/claude-swarm status               # Swarm health

# === AWS: EC2 CONTROL ===
aws ec2 start-instances --instance-ids <ID>   # Start instance
aws ec2 stop-instances --instance-ids <ID>    # Stop (saves $$$)
aws ec2 describe-instances --instance-ids <ID> --query 'Reservations[0].Instances[0].State.Name'

# === AWS: CREDENTIALS ===
aws ssm get-parameters-by-path --path "/autonomous-claude" --query "Parameters[].Name"
aws ssm put-parameter --name "/autonomous-claude/key" --value "val" --type SecureString --overwrite
aws ssm get-parameter --name "/autonomous-claude/key" --with-decryption --query "Parameter.Value"

# === DEPLOY CHANGES ===
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.git' \
  -e "ssh -i ~/.ssh/<key>.pem" . ubuntu@<IP>:/autonomous-claude/
# Then on EC2:
./scripts/start_agents.sh stop && ./scripts/start_agents.sh
```
