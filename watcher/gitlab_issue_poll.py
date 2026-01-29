import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from integrations.gitlab_client import GitLabClient, GitLabConfig

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _get_repos(orchestrator) -> List[Any]:
    if hasattr(orchestrator, "list_repos"):
        return orchestrator.list_repos(active_only=True)
    if hasattr(orchestrator, "get_repos"):
        return orchestrator.get_repos(active_only=True)
    return []


def _repo_to_dict(repo: Any) -> Dict[str, Any]:
    if hasattr(repo, "to_dict"):
        return repo.to_dict()
    if isinstance(repo, dict):
        return repo
    return {}


def poll_gitlab_issues(orchestrator) -> None:
    """
    Poll GitLab for new/updated issues as a fallback when webhooks are unavailable.

    Creates triage_issue tasks for issues that are open and not labeled auto-dev.
    """
    token = os.getenv("GITLAB_TOKEN")
    if not token:
        logger.warning("GITLAB_TOKEN not set; skipping GitLab issue polling")
        return

    now = _now_utc()
    repos = _get_repos(orchestrator)
    if not repos:
        logger.info("No repos available for GitLab issue polling")
        return

    for repo_obj in repos:
        repo = _repo_to_dict(repo_obj)
        if not repo or repo.get("provider", "gitlab") != "gitlab":
            continue

        settings = repo.get("settings") or {}
        poll_settings = settings.get("gitlab_polling", {})
        if poll_settings.get("enabled") is False:
            continue

        lookback_hours = int(poll_settings.get("lookback_hours", 24))
        last_polled_at = poll_settings.get("last_polled_at")
        if last_polled_at:
            last_dt = _parse_iso(last_polled_at)
            if last_dt:
                updated_after = (last_dt - timedelta(minutes=5)).isoformat()
            else:
                updated_after = (now - timedelta(hours=lookback_hours)).isoformat()
        else:
            updated_after = (now - timedelta(hours=lookback_hours)).isoformat()

        client = GitLabClient(GitLabConfig(
            url=repo["gitlab_url"],
            project_id=repo["gitlab_project_id"],
            token=token,
            default_branch=repo.get("default_branch", "main"),
        ))

        try:
            issues = client.list_issues(
                state="opened",
                updated_after=updated_after,
                order_by="updated_at",
                sort="desc",
                per_page=100,
            )
        except Exception as e:
            logger.warning(f"Failed to poll issues for {repo.get('name')}: {e}")
            continue

        for issue in issues:
            labels = [str(l).lower() for l in issue.get("labels", [])]

            issue_id = str(issue.get("id") or issue.get("iid"))
            if hasattr(orchestrator, "is_issue_processed"):
                if orchestrator.is_issue_processed(issue_id, repo["id"], "open"):
                    continue

            payload = {
                "source": "gitlab_poll",
                "event_type": "issue",
                "action": "open",
                "repo_id": repo["id"],
                "timestamp": now.isoformat(),
                "repo": {
                    "id": repo.get("id"),
                    "autonomy_mode": repo.get("autonomy_mode", "guided"),
                },
                "project": {
                    "id": repo.get("gitlab_project_id"),
                    "name": repo.get("name"),
                    "path_with_namespace": repo.get("gitlab_project_id"),
                    "web_url": f"{repo.get('gitlab_url')}/{repo.get('gitlab_project_id')}",
                    "default_branch": repo.get("default_branch", "main"),
                },
                "issue": {
                    "id": issue.get("id"),
                    "iid": issue.get("iid"),
                    "title": issue.get("title"),
                    "description": issue.get("description"),
                    "state": issue.get("state"),
                    "labels": issue.get("labels", []),
                    "url": issue.get("web_url") or issue.get("url"),
                },
            }

            task = orchestrator.create_task(
                task_type="triage_issue",
                payload=payload,
                priority=3,
                created_by="gitlab_poll",
                repo_id=repo["id"],
            )
            if task and hasattr(orchestrator, "mark_issue_processed"):
                orchestrator.mark_issue_processed(issue_id, repo["id"], "open")

        poll_settings["last_polled_at"] = now.isoformat()
        settings["gitlab_polling"] = poll_settings
        if hasattr(orchestrator, "update_repo"):
            orchestrator.update_repo(repo["id"], settings=settings)
