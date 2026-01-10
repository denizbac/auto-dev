"""
Repository Management Endpoints
================================

API endpoints for managing GitLab repositories in the Auto-Dev system.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
import secrets
import os
import sys
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Will be imported from main server
orchestrator = None

router = APIRouter(prefix="/api/repos", tags=["repos"])


def set_orchestrator(orch):
    """Set the orchestrator instance (called from main server)."""
    global orchestrator
    orchestrator = orch


# Pydantic models for request/response
class RepoCreate(BaseModel):
    """Create a new repository."""
    name: str = Field(..., min_length=1, max_length=100)
    gitlab_url: str = Field(..., description="GitLab instance URL")
    gitlab_project_id: str = Field(..., description="GitLab project ID or path")
    default_branch: str = Field(default="main")
    autonomy_mode: str = Field(default="guided", pattern="^(guided|full)$")
    settings: Optional[Dict[str, Any]] = Field(default=None)


class RepoUpdate(BaseModel):
    """Update repository settings."""
    name: Optional[str] = None
    default_branch: Optional[str] = None
    autonomy_mode: Optional[str] = Field(default=None, pattern="^(guided|full)$")
    settings: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None


class RepoResponse(BaseModel):
    """Repository response model."""
    id: str
    name: str
    gitlab_url: str
    gitlab_project_id: str
    default_branch: str
    autonomy_mode: str
    settings: Optional[Dict[str, Any]]
    created_at: str
    active: bool


class WebhookInfo(BaseModel):
    """Webhook setup information."""
    webhook_url: str
    webhook_secret: str
    events: List[str]
    instructions: str


@router.get("")
async def list_repos(
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """List all repositories."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        repos = orchestrator.list_repos(active_only=active_only)

        # Apply pagination
        total = len(repos)
        repos = repos[offset:offset + limit]

        return {
            "repos": repos,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_repo(repo: RepoCreate) -> Dict[str, Any]:
    """Create a new repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        # Generate repo ID from name (slug format)
        repo_id = repo.name.lower().replace(" ", "-").replace("_", "-")
        # Remove any non-alphanumeric chars except hyphen
        repo_id = "".join(c for c in repo_id if c.isalnum() or c == "-")

        result = orchestrator.create_repo(
            repo_id=repo_id,
            name=repo.name,
            gitlab_url=repo.gitlab_url,
            gitlab_project_id=repo.gitlab_project_id,
            default_branch=repo.default_branch,
            autonomy_mode=repo.autonomy_mode,
            settings=repo.settings or {}
        )

        return {
            "status": "created",
            "repo_id": repo_id,
            "message": f"Repository '{repo.name}' created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}")
async def get_repo(repo_id: str) -> Dict[str, Any]:
    """Get repository details."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        repo = orchestrator.get_repo(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        return repo
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{repo_id}")
async def update_repo(repo_id: str, updates: RepoUpdate) -> Dict[str, Any]:
    """Update repository settings."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        # Build update dict from non-None values
        update_dict = {k: v for k, v in updates.dict().items() if v is not None}

        if not update_dict:
            raise HTTPException(status_code=400, detail="No updates provided")

        orchestrator.update_repo(repo_id, **update_dict)

        return {
            "status": "updated",
            "repo_id": repo_id,
            "updates": update_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{repo_id}")
async def delete_repo(repo_id: str, hard_delete: bool = False) -> Dict[str, Any]:
    """Delete or deactivate a repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        if hard_delete:
            # Actually delete from database
            orchestrator.delete_repo(repo_id)
            return {
                "status": "deleted",
                "repo_id": repo_id,
                "message": "Repository permanently deleted"
            }
        else:
            # Soft delete - just deactivate
            orchestrator.update_repo(repo_id, active=False)
            return {
                "status": "deactivated",
                "repo_id": repo_id,
                "message": "Repository deactivated (use hard_delete=true to permanently remove)"
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/webhook")
async def get_webhook_info(repo_id: str) -> WebhookInfo:
    """Get webhook setup information for a repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    repo = orchestrator.get_repo(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Generate or retrieve webhook secret
    settings = repo.get("settings", {}) or {}
    webhook_secret = settings.get("webhook_secret")

    if not webhook_secret:
        # Generate new secret
        webhook_secret = secrets.token_hex(32)
        settings["webhook_secret"] = webhook_secret
        orchestrator.update_repo(repo_id, settings=settings)

    # Get the dashboard URL from environment or default
    base_url = os.environ.get("AUTO_DEV_URL", "http://localhost:8080")
    webhook_url = f"{base_url}/webhook/gitlab/{repo_id}"

    return WebhookInfo(
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        events=[
            "push_events",
            "merge_request_events",
            "issue_events",
            "pipeline_events",
            "note_events"
        ],
        instructions=f"""
## GitLab Webhook Setup

1. Go to your GitLab project: {repo.get('gitlab_url')}/{repo.get('gitlab_project_id')}
2. Navigate to Settings → Webhooks
3. Add a new webhook with these settings:

   **URL**: {webhook_url}
   **Secret Token**: {webhook_secret}

   **Trigger events**:
   - ✅ Push events
   - ✅ Merge request events
   - ✅ Issue events
   - ✅ Pipeline events
   - ✅ Comments (Note events)

4. Click "Add webhook"
5. Test the webhook using the "Test" button

The webhook will route events to the appropriate Auto-Dev agents.
"""
    )


@router.get("/{repo_id}/tasks")
async def get_repo_tasks(
    repo_id: str,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get tasks for a specific repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        tasks = orchestrator.list_tasks(
            repo_id=repo_id,
            status=status,
            limit=limit
        )

        # Filter by task_type if provided
        if task_type:
            tasks = [t for t in tasks if t.get("task_type") == task_type]

        return {
            "repo_id": repo_id,
            "tasks": tasks,
            "count": len(tasks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/approvals")
async def get_repo_approvals(
    repo_id: str,
    status: str = "pending",
    limit: int = 50
) -> Dict[str, Any]:
    """Get pending approvals for a specific repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        approvals = orchestrator.list_approvals(
            repo_id=repo_id,
            status=status,
            limit=limit
        )

        return {
            "repo_id": repo_id,
            "approvals": approvals,
            "count": len(approvals)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/stats")
async def get_repo_stats(repo_id: str) -> Dict[str, Any]:
    """Get statistics for a specific repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        repo = orchestrator.get_repo(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Get task counts by status
        all_tasks = orchestrator.list_tasks(repo_id=repo_id, limit=1000)

        task_stats = {
            "total": len(all_tasks),
            "pending": len([t for t in all_tasks if t.get("status") == "pending"]),
            "in_progress": len([t for t in all_tasks if t.get("status") == "in_progress"]),
            "completed": len([t for t in all_tasks if t.get("status") == "completed"]),
            "failed": len([t for t in all_tasks if t.get("status") == "failed"])
        }

        # Get approval counts
        pending_approvals = orchestrator.list_approvals(repo_id=repo_id, status="pending")

        # Get task types breakdown
        task_types = {}
        for task in all_tasks:
            tt = task.get("task_type", "unknown")
            task_types[tt] = task_types.get(tt, 0) + 1

        return {
            "repo_id": repo_id,
            "repo_name": repo.get("name"),
            "autonomy_mode": repo.get("autonomy_mode"),
            "active": repo.get("active"),
            "tasks": task_stats,
            "task_types": task_types,
            "pending_approvals": len(pending_approvals),
            "created_at": repo.get("created_at")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{repo_id}/trigger")
async def trigger_analysis(
    repo_id: str,
    task_type: str = "analyze_repo",
    background_tasks: BackgroundTasks = None
) -> Dict[str, Any]:
    """Manually trigger an analysis task for a repository."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        repo = orchestrator.get_repo(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Create the analysis task
        task_id = orchestrator.create_task(
            repo_id=repo_id,
            task_type=task_type,
            payload={
                "repo_name": repo.get("name"),
                "gitlab_url": repo.get("gitlab_url"),
                "gitlab_project_id": repo.get("gitlab_project_id"),
                "triggered_manually": True,
                "triggered_at": datetime.now().isoformat()
            },
            priority=5  # Medium priority for manual triggers
        )

        return {
            "status": "triggered",
            "task_id": task_id,
            "task_type": task_type,
            "repo_id": repo_id,
            "message": f"Task '{task_type}' created for repository"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Dashboard stats endpoint (aggregates across all repos)
@router.get("/dashboard/stats")
async def dashboard_stats() -> Dict[str, Any]:
    """Get aggregated stats for the dashboard."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        repos = orchestrator.list_repos(active_only=True)

        total_tasks = 0
        pending_tasks = 0
        in_progress_tasks = 0
        total_approvals = 0

        repo_stats = []
        for repo in repos:
            repo_id = repo.get("id")
            tasks = orchestrator.list_tasks(repo_id=repo_id, limit=1000)
            approvals = orchestrator.list_approvals(repo_id=repo_id, status="pending")

            pending = len([t for t in tasks if t.get("status") == "pending"])
            in_progress = len([t for t in tasks if t.get("status") == "in_progress"])

            total_tasks += len(tasks)
            pending_tasks += pending
            in_progress_tasks += in_progress
            total_approvals += len(approvals)

            repo_stats.append({
                "id": repo_id,
                "name": repo.get("name"),
                "autonomy_mode": repo.get("autonomy_mode"),
                "task_count": len(tasks),
                "pending_tasks": pending,
                "in_progress_tasks": in_progress,
                "pending_approvals": len(approvals)
            })

        return {
            "total_repos": len(repos),
            "total_tasks": total_tasks,
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks,
            "total_pending_approvals": total_approvals,
            "repos": repo_stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
