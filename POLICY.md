# Policy

This file is the single source of truth. If any prompt or document conflicts with this policy, the policy wins.

## Scope
- Auto-Dev develops software on **configured GitLab repositories only**.
- Agents work within the repositories they are assigned to.

## Prohibited
- Working in repositories not configured in the system
- Committing secrets or credentials to repositories
- Bypassing approval gates
- Modifying production data without approval
- Force-pushing to protected branches

## Required Approvals
- **Spec approval**: Human reviews architect's specification before implementation begins
- **Merge approval**: Human reviews merge request before deployment

## Pipeline
PM → Architect → [Human Approval] → Builder → Reviewer/Tester/Security (parallel) → [Human Approval] → DevOps

## Task Naming
- PM: `analyze_repo`, `create_epic`, `create_user_story`, `prioritize_backlog`, `triage_issue`
- Architect: `evaluate_feasibility`, `write_spec`, `create_implementation_issue`
- Builder: `implement_feature`, `implement_fix`, `implement_refactor`, `address_review_feedback`
- Reviewer: `review_mr`
- Tester: `write_tests`, `run_tests`, `validate_feature`, `analyze_coverage`
- Security: `security_scan`, `dependency_audit`, `compliance_check`
- DevOps: `manage_pipeline`, `deploy`, `rollback`, `fix_build`
- Bug Finder: `static_analysis`, `bug_hunt`

## Autonomy Modes
- **Guided** (default): Human approval required at spec and merge points
- **Full**: Auto-approve if thresholds met (architect_confidence>=8, reviewer_score>=9, coverage>=80%)

## Safety
- Never commit secrets or credentials
- Always follow rate limits and API quotas
- Webhook authentication is required (no unauthenticated webhooks)
- All external API calls must use tokens from AWS SSM
