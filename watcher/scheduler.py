"""
Scheduler for Auto-Dev

Runs scheduled jobs based on cron expressions from settings.yaml.
Creates tasks in the orchestrator queue when schedules trigger.

Usage:
    python -m watcher.scheduler

    Or integrated with agent runner:
    scheduler = Scheduler(orchestrator, config)
    scheduler.start()
"""

import time
import logging
import threading
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class CronExpression:
    """
    Simple cron expression parser.

    Format: minute hour day month weekday
    Supports: *, specific values, ranges (1-5), lists (1,3,5)
    """

    def __init__(self, expression: str):
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expression}")

        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.day = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.weekday = self._parse_field(parts[4], 0, 6)  # 0 = Sunday

    def _parse_field(self, field: str, min_val: int, max_val: int) -> set:
        """Parse a cron field into a set of valid values."""
        if field == '*':
            return set(range(min_val, max_val + 1))

        values = set()
        for part in field.split(','):
            if '-' in part:
                # Range
                start, end = part.split('-')
                values.update(range(int(start), int(end) + 1))
            elif '/' in part:
                # Step
                base, step = part.split('/')
                if base == '*':
                    base_vals = range(min_val, max_val + 1)
                else:
                    base_vals = range(int(base), max_val + 1)
                values.update(v for i, v in enumerate(base_vals) if i % int(step) == 0)
            else:
                values.add(int(part))

        return values

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches this cron expression."""
        # Convert Python weekday (0=Monday) to cron weekday (0=Sunday)
        cron_weekday = (dt.weekday() + 1) % 7
        return (
            dt.minute in self.minute and
            dt.hour in self.hour and
            dt.day in self.day and
            dt.month in self.month and
            cron_weekday in self.weekday
        )


class ScheduledJob:
    """A scheduled job configuration."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.agent = config['agent']
        self.task_type = config['task_type']
        self.cron = CronExpression(config['cron'])
        self.enabled = config.get('enabled', True)
        self.description = config.get('description', '')
        self.last_run: Optional[datetime] = None

    def should_run(self, dt: datetime) -> bool:
        """Check if job should run at the given time."""
        if not self.enabled:
            return False

        # Check if cron matches
        if not self.cron.matches(dt):
            return False

        # Prevent running multiple times in the same minute
        if self.last_run and self.last_run.replace(second=0, microsecond=0) == dt.replace(second=0, microsecond=0):
            return False

        return True

    def mark_run(self, dt: datetime):
        """Mark the job as having run."""
        self.last_run = dt


class Scheduler:
    """
    Scheduler that runs jobs based on cron expressions.

    Reads scheduling config from settings.yaml and creates tasks
    in the orchestrator when schedules trigger.
    """

    def __init__(
        self,
        orchestrator,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None
    ):
        self.orchestrator = orchestrator
        self.jobs: List[ScheduledJob] = []
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.config: Dict[str, Any] = {}

        # Load config
        if config:
            self.config = config
            self._load_from_config(config)
        elif config_path:
            self._load_from_file(config_path)
        else:
            self._load_from_file()

    def _load_from_file(self, config_path: Optional[str] = None):
        """Load scheduling config from settings.yaml."""
        if config_path is None:
            for path in [
                '/auto-dev/config/settings.yaml',
                Path(__file__).parent.parent / 'config' / 'settings.yaml',
            ]:
                if Path(path).exists():
                    config_path = str(path)
                    break

        if not config_path or not Path(config_path).exists():
            logger.warning("No settings.yaml found, scheduler has no jobs")
            return

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                self.config = config or {}
                self._load_from_config(config)
        except Exception as e:
            logger.error(f"Failed to load scheduler config: {e}")

    def _load_from_config(self, config: Dict[str, Any]):
        """Load jobs from config dict."""
        scheduling = config.get('scheduling', {})

        if not scheduling.get('enabled', True):
            logger.info("Scheduling is disabled in config")
            return

        jobs_config = scheduling.get('jobs', {})
        for name, job_config in jobs_config.items():
            try:
                job = ScheduledJob(name, job_config)
                self.jobs.append(job)
                status = "enabled" if job.enabled else "disabled"
                logger.info(f"Loaded scheduled job: {name} ({status})")
            except Exception as e:
                logger.error(f"Failed to load job {name}: {e}")

        logger.info(f"Loaded {len(self.jobs)} scheduled jobs")

    def start(self, blocking: bool = False):
        """
        Start the scheduler.

        Args:
            blocking: If True, run in current thread. If False, spawn background thread.
        """
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True

        if blocking:
            self._run_loop()
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("Scheduler started in background thread")

    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop."""
        logger.info(f"Scheduler running with {len(self.jobs)} jobs")

        while self.running:
            try:
                now = datetime.utcnow()
                self._check_jobs(now)
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            # Sleep until next minute
            time.sleep(60 - datetime.utcnow().second)

    def _check_jobs(self, now: datetime):
        """Check all jobs and run those that match."""
        for job in self.jobs:
            if job.should_run(now):
                self._run_job(job, now)

    def _run_job(self, job: ScheduledJob, now: datetime):
        """Execute a scheduled job by creating a task."""
        logger.info(f"Running scheduled job: {job.name} ({job.task_type})")

        try:
            # Internal jobs (no tasks)
            if job.task_type == "poll_gitlab_issues":
                from watcher.gitlab_issue_poll import poll_gitlab_issues
                poll_gitlab_issues(self.orchestrator)
                job.mark_run(now)
                return

            auto_feature_cfg = self._get_auto_feature_config()
            guidance_status: Optional[Tuple[int, int]] = None
            if job.task_type == "auto_feature_creation":
                if not auto_feature_cfg.get("enabled", False):
                    logger.info("Auto feature creation disabled; skipping")
                    job.mark_run(now)
                    return

                guidance_path = auto_feature_cfg.get(
                    "guidance_path",
                    "/auto-dev/config/product_guidance.md"
                )
                guidance_status = self._get_guidance_progress(guidance_path)
                if not guidance_status:
                    logger.info("Auto feature creation skipped: no guidance or no open requirements")
                    job.mark_run(now)
                    return

            # Get all active repos for this job
            repos = self._get_active_repos()

            for repo in repos:
                # Check if job is enabled for this repo
                if not self._job_enabled_for_repo(job, repo):
                    continue

                if job.task_type == "auto_feature_creation":
                    if not self._auto_feature_repo_ready(repo, auto_feature_cfg):
                        continue

                payload = {
                    'source': 'scheduler',
                    'job_name': job.name,
                    'scheduled_time': now.isoformat(),
                    'description': job.description,
                }
                if job.task_type == "auto_feature_creation":
                    payload['auto_feature'] = self._build_auto_feature_payload(
                        auto_feature_cfg,
                        guidance_status
                    )

                task = self.orchestrator.create_task(
                    task_type=job.task_type,
                    payload=payload,
                    priority=3,  # Lower priority for scheduled jobs
                    created_by='scheduler',
                    repo_id=repo.get('id')
                )

                if task:
                    logger.info(
                        f"Created task {task.id} for scheduled job {job.name} "
                        f"in repo {repo.get('id')}"
                    )

            job.mark_run(now)

        except Exception as e:
            logger.error(f"Failed to run scheduled job {job.name}: {e}")

    def _get_auto_feature_config(self) -> Dict[str, Any]:
        """Fetch auto feature creation config."""
        return (
            self.config.get("product", {})
            .get("auto_feature_creation", {})
        )

    def _get_guidance_progress(self, guidance_path: str) -> Optional[Tuple[int, int]]:
        """
        Return (pending, total) requirements from guidance. None if missing/empty/all done.
        """
        if not guidance_path:
            return None

        path = Path(guidance_path)
        if not path.exists():
            return None

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None

        total = 0
        pending = 0
        for line in content.splitlines():
            match = re.match(r"^\s*[-*]\s+\[( |x|X)\]\s+.+", line)
            if not match:
                continue
            total += 1
            if match.group(1).lower() != "x":
                pending += 1

        if total == 0 or pending == 0:
            return None

        return pending, total

    def _auto_feature_repo_ready(self, repo: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
        """Check repo readiness and open-issue caps for auto feature creation."""
        token = os.getenv("GITLAB_TOKEN")
        if not token:
            logger.warning("GITLAB_TOKEN missing; skipping auto feature creation")
            return False

        if repo.get("provider", "gitlab") != "gitlab":
            logger.warning("Auto feature creation only supports GitLab repos")
            return False

        gitlab_url = repo.get("gitlab_url")
        project_id = repo.get("gitlab_project_id")
        if not gitlab_url or not project_id:
            logger.warning("Missing gitlab_url/project_id; skipping auto feature creation")
            return False

        label = cfg.get("label", "auto-feature")
        max_open = int(cfg.get("max_open_issues", 6))

        try:
            from integrations.gitlab_client import GitLabClient, GitLabConfig
            client = GitLabClient(GitLabConfig(url=gitlab_url, project_id=project_id))
            issues = client.list_issues(state="opened", labels=[label], per_page=max_open + 1, page=1)
            if len(issues) >= max_open:
                logger.info(
                    f"Auto feature creation skipped: {len(issues)} open '{label}' issues (cap {max_open})"
                )
                return False
        except Exception as e:
            logger.warning(f"Failed to check open auto-feature issues: {e}")
            return False

        return True

    def _build_auto_feature_payload(
        self,
        cfg: Dict[str, Any],
        guidance_status: Optional[Tuple[int, int]]
    ) -> Dict[str, Any]:
        """Build payload details for auto feature creation tasks."""
        pending, total = guidance_status or (0, 0)
        return {
            "guidance_path": cfg.get("guidance_path", "/auto-dev/config/product_guidance.md"),
            "max_new_issues_per_run": int(cfg.get("max_new_issues_per_run", 3)),
            "max_open_issues": int(cfg.get("max_open_issues", 6)),
            "label": cfg.get("label", "auto-feature"),
            "pending_requirements": pending,
            "total_requirements": total,
        }

    def _get_active_repos(self) -> List[Dict[str, Any]]:
        """Get list of active repositories."""
        try:
            if hasattr(self.orchestrator, 'list_repos'):
                repos = self.orchestrator.list_repos(active_only=True)
                if repos:
                    return [
                        r.to_dict() if hasattr(r, 'to_dict') else r
                        for r in repos
                    ]
            if hasattr(self.orchestrator, 'get_repos'):
                return self.orchestrator.get_repos(active_only=True)
            elif hasattr(self.orchestrator, 'repos'):
                return [r for r in self.orchestrator.repos if r.get('active', True)]
        except Exception as e:
            logger.warning(f"Failed to get repos: {e}")

        # Return empty list to skip repo-specific jobs
        return [{'id': None}]  # None repo_id for global jobs

    def _job_enabled_for_repo(self, job: ScheduledJob, repo: Dict[str, Any]) -> bool:
        """Check if a job is enabled for a specific repo."""
        # Check repo-specific settings
        settings = repo.get('settings', {})
        scheduling_overrides = settings.get('scheduling', {})

        if job.name in scheduling_overrides:
            return scheduling_overrides[job.name].get('enabled', job.enabled)

        return job.enabled

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status for dashboard."""
        return {
            'running': self.running,
            'jobs': [
                {
                    'name': job.name,
                    'agent': job.agent,
                    'task_type': job.task_type,
                    'enabled': job.enabled,
                    'description': job.description,
                    'last_run': job.last_run.isoformat() if job.last_run else None,
                }
                for job in self.jobs
            ]
        }

    def run_job_now(self, job_name: str) -> bool:
        """Manually trigger a job to run immediately."""
        for job in self.jobs:
            if job.name == job_name:
                self._run_job(job, datetime.utcnow())
                return True
        return False


# CLI entry point
if __name__ == '__main__':
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Import orchestrator
    try:
        from watcher.orchestrator_pg import get_orchestrator
        orchestrator = get_orchestrator()
    except Exception:
        from watcher.orchestrator import Orchestrator
        orchestrator = Orchestrator()

    scheduler = Scheduler(orchestrator)

    print(f"Starting scheduler with {len(scheduler.jobs)} jobs...")
    for job in scheduler.jobs:
        print(f"  - {job.name}: {job.task_type} ({job.agent})")

    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        print("\nShutting down...")
        scheduler.stop()
