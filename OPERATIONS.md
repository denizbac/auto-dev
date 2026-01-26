# Auto-Dev - Operations Guide

This document explains how to manage the autonomous AI swarm running on **AWS ECS (Fargate)**.

## Quick Reference

```bash
# === DASHBOARD (internal) ===
http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com

# === DEPLOY CODE CHANGES ===
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest

# Redeploy all services
for svc in auto-dev-dashboard auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1
done

# === VIEW LOGS (CloudWatch) ===
aws logs tail /ecs/auto-dev --follow                          # All logs
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm"    # Filter by agent

# === CHECK STATUS ===
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0].deployments'

# === AWS SSM (Credentials) ===
aws ssm get-parameters-by-path --path "/auto-dev" --query "Parameters[].Name"
```

---

## 1. ECS Infrastructure

### Get Connection Details

```bash
cd terraform
terraform output
```

Output:
```
alb_dns_name = "internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com"
dashboard_url = "http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com"
ecr_repository_url = "569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev"
ecs_cluster_name = "auto-dev"
cloudwatch_log_group = "/ecs/auto-dev"
```

### ECS Services

| Service | Purpose |
|---------|---------|
| auto-dev-dashboard | Web UI and API |
| auto-dev-pm | Product Manager agent |
| auto-dev-architect | Architect agent |
| auto-dev-builder | Builder agent |
| auto-dev-reviewer | Reviewer agent |
| auto-dev-tester | Tester agent |
| auto-dev-security | Security agent |
| auto-dev-devops | DevOps agent |
| auto-dev-bug_finder | Bug Finder agent |
| auto-dev-postgres | PostgreSQL database |
| auto-dev-qdrant | Qdrant vector database |
| auto-dev-redis | Redis for coordination |

---

## 2. Agent Management

### Check Status

```bash
# List all services
aws ecs list-services --cluster auto-dev --region us-east-1 | jq -r '.serviceArns[]'

# Check specific service status
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0] | {name: .serviceName, running: .runningCount, desired: .desiredCount}'

# Check all agents at once
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs describe-services --cluster auto-dev --services $svc --region us-east-1 | jq -r '.services[0] | "\(.serviceName): \(.runningCount)/\(.desiredCount)"'
done
```

### Restart Agent

```bash
# Force redeploy a specific agent
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1

# Restart all agents
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1
done
```

### Scale Agent

```bash
# Scale down (stop agent)
aws ecs update-service --cluster auto-dev --service auto-dev-pm --desired-count 0 --region us-east-1

# Scale up (start agent)
aws ecs update-service --cluster auto-dev --service auto-dev-pm --desired-count 1 --region us-east-1
```

---

## 3. Viewing Agent Activity

### CloudWatch Logs

```bash
# Live tail all logs
aws logs tail /ecs/auto-dev --follow --region us-east-1

# Filter by agent
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm" --region us-east-1
aws logs tail /ecs/auto-dev --follow --filter-pattern "builder" --region us-east-1

# Search for errors
aws logs tail /ecs/auto-dev --filter-pattern "ERROR" --since 1h --region us-east-1

# Get specific log stream
aws logs describe-log-streams --log-group-name /ecs/auto-dev --order-by LastEventTime --descending --limit 10 --region us-east-1 | jq -r '.logStreams[].logStreamName'
```

### Get Recent Logs for Agent

```bash
# List PM agent log streams
aws logs describe-log-streams --log-group-name /ecs/auto-dev --log-stream-name-prefix "pm/" --order-by LastEventTime --descending --limit 3 --region us-east-1

# Get log events from a specific stream
aws logs get-log-events --log-group-name /ecs/auto-dev --log-stream-name "pm/pm/<task-id>" --limit 50 --region us-east-1 | jq -r '.events[].message'
```

---

## 4. Dashboard

### Access

Dashboard URL: `http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com`

### Dashboard Features

- **Agent Status**: See which agents are running
- **Task Queue**: Pending, in-progress, completed tasks
- **Approval Queue**: Specs and MRs waiting for human review
- **Repository Management**: Add/configure GitLab repos
- **Send Instructions**: Direct commands to agents

### Restart Dashboard

```bash
aws ecs update-service --cluster auto-dev --service auto-dev-dashboard --force-new-deployment --region us-east-1
```

---

## 5. Task Management

### View Tasks

```bash
cd /auto-dev
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
| `analyze_repo` | PM | Analyze repository structure |
| `create_epic` | PM | Create GitLab Epic |
| `create_user_story` | PM | Create user story issue |
| `prioritize_backlog` | PM | Prioritize issues |
| `evaluate_feasibility` | Architect | Evaluate technical feasibility |
| `write_spec` | Architect | Create implementation specification |
| `implement_feature` | Builder | Implement new feature |
| `implement_fix` | Builder | Fix a bug |
| `review_mr` | Reviewer | Code review merge request |
| `run_tests` | Tester | Run test suites |
| `security_scan` | Security | SAST security scanning |
| `deploy` | DevOps | Deploy to environment |
| `static_analysis` | Bug Finder | Proactive bug detection |

### Development Workflow

```
PM → Architect → [Human Approval] → Builder → Reviewer/Tester/Security (parallel) → [Human Approval] → DevOps
```

**Key Quality Gates:**
1. **Spec Approval**: Human reviews architect's spec before implementation
2. **Reviewer**: Code review for security, quality, maintainability
3. **Tester**: Tests must pass with required coverage
4. **Security**: No critical vulnerabilities
5. **Merge Approval**: Human approves before deployment

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
ls -la /auto-dev/data/projects/

# Review specific product
cat /auto-dev/data/projects/<product-name>/README.md
cat /auto-dev/data/projects/<product-name>/GUMROAD_LISTING.md
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

### Build and Push Docker Image

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev

# Build for linux/amd64 (ECS uses x86)
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .

# Push to ECR
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest
```

### Redeploy Services

```bash
# Redeploy a specific service
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1

# Redeploy all services (recommended after code changes)
for svc in auto-dev-dashboard auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder auto-dev-webhook auto-dev-scheduler; do
  echo "Redeploying $svc..."
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1 | jq -r '.service.serviceName'
done
```

### Verify Deployment

```bash
# Check deployment status
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0].deployments | map({status, runningCount, desiredCount})'

# Check for errors in events
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq -r '.services[0].events[0:3][] | .message'

# Watch logs for the new deployment
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm" --region us-east-1
```

---

## 9. Troubleshooting

### Agent Won't Start / Task Not Running

```bash
# Check service events for errors
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq -r '.services[0].events[0:5][] | .message'

# Check task status
TASK_ARN=$(aws ecs list-tasks --cluster auto-dev --service-name auto-dev-pm --region us-east-1 | jq -r '.taskArns[0]')
aws ecs describe-tasks --cluster auto-dev --tasks $TASK_ARN --region us-east-1 | jq '.tasks[0] | {lastStatus, stoppedReason, healthStatus}'

# Check CloudWatch logs for errors
aws logs tail /ecs/auto-dev --filter-pattern "ERROR" --since 30m --region us-east-1
```

### Image Pull Errors (Platform Mismatch)

If you see `CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'`:

```bash
# Rebuild with correct platform
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest

# Force redeploy
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1
```

### Task Keeps Stopping

```bash
# Check stopped reason
aws ecs describe-tasks --cluster auto-dev --tasks $(aws ecs list-tasks --cluster auto-dev --service-name auto-dev-pm --desired-status STOPPED --region us-east-1 | jq -r '.taskArns[0]') --region us-east-1 | jq '.tasks[0].stoppedReason'

# Check container exit code
aws ecs describe-tasks --cluster auto-dev --tasks <task-arn> --region us-east-1 | jq '.tasks[0].containers[] | {name, exitCode, reason}'
```

### Dashboard 502/Connection Refused

```bash
# Check ALB target health
aws elbv2 describe-target-health --target-group-arn $(aws elbv2 describe-target-groups --names auto-dev-dashboard-tg --region us-east-1 | jq -r '.TargetGroups[0].TargetGroupArn') --region us-east-1

# Restart dashboard service
aws ecs update-service --cluster auto-dev --service auto-dev-dashboard --force-new-deployment --region us-east-1

# Check dashboard logs
aws logs tail /ecs/auto-dev --follow --filter-pattern "dashboard" --region us-east-1
```

### Database Connection Issues

```bash
# Check if postgres service is running
aws ecs describe-services --cluster auto-dev --services auto-dev-postgres --region us-east-1 | jq '.services[0] | {running: .runningCount, desired: .desiredCount}'

# Check postgres logs
aws logs tail /ecs/auto-dev --filter-pattern "postgres" --since 10m --region us-east-1
```

---

## 10. Configuration

### Main Config

File: `/auto-dev/config/settings.yaml`

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

Directory: `/auto-dev/config/agents/`

Files:
- `pm.md` - Product management, backlog, user stories
- `architect.md` - Technical design and specifications
- `builder.md` - Code implementation
- `reviewer.md` - Code review (security, quality, maintainability)
- `tester.md` - Testing and quality assurance
- `security.md` - Security scanning and audits
- `devops.md` - CI/CD and deployment
- `bug_finder.md` - Proactive bug detection

---

## 11. Credentials

Credentials are stored in AWS SSM Parameter Store:

```bash
# View stored credentials
aws ssm get-parameters-by-path --path "/auto-dev" --query "Parameters[].Name"

# Add/update credential
aws ssm put-parameter \
  --name "/auto-dev/gumroad/email" \
  --value "your@email.com" \
  --type "SecureString" \
  --overwrite
```

Required for publishing:
- `/auto-dev/gumroad/email`
- `/auto-dev/gumroad/password`
- `/auto-dev/github/token`
- `/auto-dev/npm/token`
- `/auto-dev/vercel/token`
- `/auto-dev/apify/api_key`
Required for GitLab webhooks:
- `/auto-dev/gitlab-webhook-secret`

Optional (Codex fallback):
- `/auto-dev/openai/api_key` (only if you want API-key auth instead of device login)

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

### ECS Service Control

```bash
# List all ECS services
aws ecs list-services --cluster auto-dev --region us-east-1 | jq -r '.serviceArns[]'

# Check service status
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0] | {name: .serviceName, running: .runningCount, desired: .desiredCount, status: .status}'

# Scale down all agents (SAVES MONEY when not using!)
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --desired-count 0 --region us-east-1
done

# Scale up all agents
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --desired-count 1 --region us-east-1
done

# Force restart a service
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1
```

### SSM Parameter Store (Credentials)

```bash
# List all credentials
aws ssm get-parameters-by-path \
  --path "/auto-dev" \
  --query "Parameters[].Name" \
  --output table

# Get specific credential (decrypted)
aws ssm get-parameter \
  --name "/auto-dev/gumroad/email" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text

# Store new credential
aws ssm put-parameter \
  --name "/auto-dev/stripe/secret_key" \
  --value "sk_live_xxx" \
  --type "SecureString"

# Update existing credential
aws ssm put-parameter \
  --name "/auto-dev/gumroad/password" \
  --value "new_password" \
  --type "SecureString" \
  --overwrite

# Delete credential
aws ssm delete-parameter --name "/auto-dev/old/credential"

# Check if credential exists
aws ssm get-parameter --name "/auto-dev/gumroad/email" \
  --query "Parameter.Name" --output text 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

### Cost Management

```bash
# Check current month AWS costs
aws ce get-cost-and-usage \
  --time-period Start=$(date -v1d +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --region us-east-1

# ECS/Fargate cost breakdown
aws ce get-cost-and-usage \
  --time-period Start=$(date -v-7d +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Container Service"]}}' \
  --metrics BlendedCost \
  --region us-east-1

# Scale down to save money (keeps dashboard/postgres/redis)
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --desired-count 0 --region us-east-1
done
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

### Required Terraform Inputs (Internal Subnets)

Set these in `terraform.tfvars` before `terraform apply`:

```hcl
vpc_id = "vpc-xxxxxxxx"
private_subnet_ids = [
  "subnet-aaaa",
  "subnet-bbbb",
  "subnet-cccc",
  "subnet-dddd"
]
```

---

## 13. Monitoring

### Quick Health Check

```bash
# Check all agent services are running
for svc in auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs describe-services --cluster auto-dev --services $svc --region us-east-1 | jq -r '.services[0] | "\(.serviceName): \(.runningCount)/\(.desiredCount)"'
done

# Check for recent errors in CloudWatch
aws logs tail /ecs/auto-dev --filter-pattern "ERROR" --since 1h --region us-east-1

# Check dashboard health (from within VPC)
curl -s http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com/health | jq .

# Check pending tasks via API (from within VPC)
curl -s http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com/api/tasks?status=pending | jq '.tasks | length'
```

### CloudWatch Alarms (Optional)

You can set up CloudWatch alarms for:
- ECS service running count < desired count
- High error rate in logs
- ALB unhealthy targets

```bash
# Example: Create alarm for PM agent not running
aws cloudwatch put-metric-alarm \
  --alarm-name "auto-dev-pm-not-running" \
  --metric-name CPUUtilization \
  --namespace AWS/ECS \
  --dimensions Name=ServiceName,Value=auto-dev-pm Name=ClusterName,Value=auto-dev \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 0 \
  --comparison-operator LessThanOrEqualToThreshold \
  --alarm-actions <SNS_TOPIC_ARN> \
  --region us-east-1
```

---

## Summary Commands

```bash
# === DASHBOARD (internal) ===
http://internal-auto-dev-alb-588827158.us-east-1.elb.amazonaws.com

# === DEPLOY CODE CHANGES ===
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev
docker build --platform linux/amd64 -t 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest .
docker push 569498020693.dkr.ecr.us-east-1.amazonaws.com/auto-dev:latest
# Redeploy services
for svc in auto-dev-dashboard auto-dev-pm auto-dev-architect auto-dev-builder auto-dev-reviewer auto-dev-tester auto-dev-security auto-dev-devops auto-dev-bug_finder; do
  aws ecs update-service --cluster auto-dev --service $svc --force-new-deployment --region us-east-1
done

# === VIEW LOGS ===
aws logs tail /ecs/auto-dev --follow --region us-east-1               # All logs
aws logs tail /ecs/auto-dev --follow --filter-pattern "pm"            # Filter by agent
aws logs tail /ecs/auto-dev --filter-pattern "ERROR" --since 1h       # Errors

# === CHECK STATUS ===
aws ecs describe-services --cluster auto-dev --services auto-dev-pm --region us-east-1 | jq '.services[0] | {running: .runningCount, desired: .desiredCount}'

# === RESTART AGENT ===
aws ecs update-service --cluster auto-dev --service auto-dev-pm --force-new-deployment --region us-east-1

# === SCALE AGENT ===
aws ecs update-service --cluster auto-dev --service auto-dev-pm --desired-count 0 --region us-east-1  # Stop
aws ecs update-service --cluster auto-dev --service auto-dev-pm --desired-count 1 --region us-east-1  # Start

# === AWS SSM (Credentials) ===
aws ssm get-parameters-by-path --path "/auto-dev" --query "Parameters[].Name"
aws ssm put-parameter --name "/auto-dev/key" --value "val" --type SecureString --overwrite
aws ssm get-parameter --name "/auto-dev/key" --with-decryption --query "Parameter.Value"

# === TERRAFORM ===
cd terraform && terraform output                    # Get infrastructure info
cd terraform && terraform plan                      # Preview changes
cd terraform && terraform apply                     # Apply changes
```
