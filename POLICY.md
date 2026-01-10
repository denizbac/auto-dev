# Policy

This file is the single source of truth. If any prompt or document conflicts with this policy, the policy wins.

## Scope
- This swarm only builds and ships **owned products/tools/content**.
- No services, consulting, managed work, or client delivery.

## Prohibited
- Services/consulting/managed work of any kind
- Bounties or external contributions
- Forking/cloning public repos
- Working in external repos we do not own
- Client communication or account access on behalf of others

## Required Approvals
- **Human approval before building** any new product (PM submits proposal; human approves).
- **Human approval before publishing** any product (Tester submits approval; human approves, Publisher publishes).

## Pipeline
Hunter → Critic → PM → Human Approval → Builder → Reviewer (code_review) → Tester → Human Approval → Publisher

## Task Naming
- Use `code_review` for Reviewer tasks.
- Use `test_product` for Tester tasks.
- Only Publisher executes `publish` tasks created by human approval.

## Safety
- Never commit secrets.
- Always follow rate limits and approval gates for external platforms.
