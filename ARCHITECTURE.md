# Auto-Dev - Architecture

## Overview

Auto-Dev is an autonomous software development system that uses 8 specialized AI agents to develop software on GitLab repositories. The system runs on the shared KaaS (EKS) cluster with each agent as a dedicated deployment, using PostgreSQL for coordination and Redis for agent control.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    KaaS Shared EKS Cluster (nginx ingress)                      │
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
│  │  │  • Runs as Kubernetes Deployments (one per agent type)         │     │   │
│  │  │  • Health checks & auto-restart on crashes                     │     │   │
│  │  │  • Token budget enforcement                                    │     │   │
│  │  │  • Rate limit detection & provider fallback                    │     │   │
│  │  └────────────────────────────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        ORCHESTRATOR LAYER                               │   │
│  │  PostgreSQL + Redis + Qdrant (Stateful workloads in KaaS)               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         MEMORY LAYER                                    │   │
│  │  Shared RWX volume mounted at /auto-dev/data                            │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         INTERFACE LAYER                                 │   │
│  │  Dashboard + Webhook server exposed via nginx ingress                   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Key Components

- **Dashboard** (`dashboard/server.py`) — UI + API for approvals, monitoring, and repo management.
- **Webhook Server** (`integrations/webhook_server.py`) — receives GitLab webhooks.
- **Scheduler** (`watcher/scheduler.py`) — cron-based job scheduling.
- **Agent Runner** (`watcher/agent_runner.py`) — runs a single agent process.
- **Orchestrator** (`watcher/orchestrator_pg.py`) — task queue + approvals + repo orchestration.
- **Memory** (`watcher/memory.py`) — short-term SQLite + long-term Qdrant.

## Deployment Architecture (KaaS)

- **Ingress**: nginx controller, host must be `*.kaas.nimbus.amgen.com`.
- **Network Policy**: Cilium default-deny; explicit policy required to allow ingress/DNS.
- **Secrets**: External Secrets Operator (ESO) with AWS Secrets Manager + IRSA.
- **Storage**:
  - PostgreSQL, Redis, and Qdrant on EBS-backed PVCs (RWO).
  - `/auto-dev/data` is persisted per-deployment using dedicated PVCs (not shared across pods).

## Build & Release

- Container images are built and pushed to the GitLab Container Registry.
- GitLab CI deploys manifests in `k8s/` and updates deployment images.

## Operational Interfaces

- Dashboard: `https://<app>.kaas.nimbus.amgen.com`
- Webhook endpoint: `https://<app>.kaas.nimbus.amgen.com/webhook`

## Notes

- The shared KaaS cluster manages the underlying ALB and logging infrastructure.
- CloudWatch log groups are platform-managed (not `/ecs/*`).
