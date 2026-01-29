"""
GitLab Webhook Handler for Auto-Dev

Receives GitLab webhook events and routes them to appropriate agents
by creating tasks in the orchestrator queue.

Supported events:
- Issue events (open, update, close)
- Merge Request events (open, update, merge, close)
- Note events (comments on issues/MRs)
- Pipeline events (success, failure)
- Push events
"""

import os
import hmac
import hashlib
import logging
import re
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create router for webhook endpoints
router = APIRouter(prefix="/webhook", tags=["webhooks"])


@dataclass
class WebhookEvent:
    """Parsed webhook event."""
    event_type: str
    action: str
    repo_id: str
    payload: Dict[str, Any]
    timestamp: datetime


class WebhookConfig:
    """Webhook configuration loaded from settings.yaml."""

    # Default routing (fallback if config not loaded)
    DEFAULT_ROUTING = {
        # Issue events
        'issue:open': {'agent': 'pm', 'task_type': 'triage_issue'},
        'issue:update': None,  # Usually no action needed
        'issue:reopen': {'agent': 'pm', 'task_type': 'triage_issue'},

        # Merge Request events
        'merge_request:open': {'agent': 'reviewer', 'task_type': 'review_mr'},
        'merge_request:update': {'agent': 'reviewer', 'task_type': 'review_mr'},
        'merge_request:merge': None,

        # Note (comment) events
        'note:merge_request': {'agent': 'builder', 'task_type': 'address_review_feedback'},
        'note:issue': None,  # Usually human discussion

        # Pipeline events
        'pipeline:failed': {'agent': 'devops', 'task_type': 'fix_build'},
        'pipeline:success': None,  # Log only

        # Push events
        'push': None,  # No default action on push
    }

    def __init__(self, config_path: Optional[str] = None):
        """Load webhook triggers from settings.yaml."""
        self.routing = self.DEFAULT_ROUTING.copy()

        if config_path is None:
            # Try default locations
            for path in [
                '/auto-dev/config/settings.yaml',
                Path(__file__).parent.parent / 'config' / 'settings.yaml',
            ]:
                if Path(path).exists():
                    config_path = str(path)
                    break

        if config_path and Path(config_path).exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    triggers = config.get('webhook_triggers', {})
                    if triggers:
                        self.routing.update(triggers)
                        logger.info(f"Loaded {len(triggers)} webhook triggers from config")
            except Exception as e:
                logger.warning(f"Failed to load webhook config: {e}, using defaults")

    def get_routing(self, event_key: str) -> Optional[Dict[str, Any]]:
        """Get routing for an event key like 'issue:open' or 'merge_request:open'."""
        return self.routing.get(event_key)


def evaluate_condition(condition: str, event: 'WebhookEvent') -> bool:
    """
    Evaluate a simple condition string against an event.

    Supported conditions:
    - not has_label('label-name')
    - has_label('label-name')
    - has_new_commits
    - target_branch in ['main', 'master']
    - is_review_comment and mentions_changes_needed
    - note_mentions_autodev
    """
    if not condition:
        return True

    # Support simple AND chaining
    if " and " in condition or "&&" in condition:
        parts = [p.strip() for p in re.split(r"\s+and\s+|&&", condition) if p.strip()]
        return all(evaluate_condition(p, event) for p in parts)

    payload = event.payload
    obj_attrs = payload.get('object_attributes', {})

    # Get labels from payload
    labels = []
    if 'labels' in payload:
        labels = [l.get('title', '').lower() for l in payload.get('labels', [])]
    elif obj_attrs.get('labels'):
        labels = [l.lower() for l in obj_attrs.get('labels', [])]

    # has_label check
    label_match = re.search(r"has_label\(['\"](.+?)['\"]\)", condition)
    if label_match:
        label = label_match.group(1).lower()
        has_it = label in labels
        if condition.startswith('not '):
            return not has_it
        return has_it

    # repo_autonomy_mode check (requires _auto_dev_repo injected into payload)
    repo_meta = payload.get('_auto_dev_repo', {}) if isinstance(payload, dict) else {}
    repo_mode = str(repo_meta.get('autonomy_mode', '')).lower()
    mode_match = re.search(r"(?:repo_autonomy_mode|autonomy_mode)\s*([!=]=)\s*['\"](.+?)['\"]", condition)
    if mode_match:
        op = mode_match.group(1)
        target = mode_match.group(2).lower()
        if op == "==":
            return repo_mode == target
        if op == "!=":
            return repo_mode != target
        return False

    # note_mentions_autodev (explicit trigger for guided mode)
    if condition == "note_mentions_autodev":
        if event.event_type != "note":
            return False
        note = obj_attrs.get("note", "") or ""
        return re.search(r"@auto-dev|\[auto-dev\]", note, re.IGNORECASE) is not None

    # has_new_commits
    if 'has_new_commits' in condition:
        # Check if action indicates new commits
        action = obj_attrs.get('action', '')
        return action in ['update', 'push']

    # target_branch in [...]
    branch_match = re.search(r"target_branch in \[(.+?)\]", condition)
    if branch_match:
        branches_str = branch_match.group(1)
        branches = [b.strip().strip("'\"") for b in branches_str.split(',')]
        target = obj_attrs.get('target_branch', '')
        return target in branches

    # is_review_comment and mentions_changes_needed
    if 'is_review_comment' in condition:
        note = obj_attrs.get('note', '')
        noteable_type = obj_attrs.get('noteable_type', '')
        is_review = noteable_type.lower() == 'mergerequest'

        if 'mentions_changes_needed' in condition:
            # Look for review feedback indicators
            change_keywords = ['change', 'fix', 'update', 'revise', 'please', 'should', 'must', 'need']
            mentions_changes = any(kw in note.lower() for kw in change_keywords)
            return is_review and mentions_changes

        return is_review

    # Default: condition not recognized, return True
    logger.warning(f"Unrecognized condition: {condition}")
    return True


class WebhookHandler:
    """
    Handles incoming GitLab webhooks and creates tasks.

    Usage:
        handler = WebhookHandler(orchestrator)
        handler.register_routes(app)
    """

    def __init__(self, orchestrator, repo_manager=None, config_path: Optional[str] = None):
        """
        Initialize webhook handler.

        Args:
            orchestrator: The orchestrator instance for creating tasks
            repo_manager: Optional repo manager for looking up repo config
            config_path: Optional path to settings.yaml
        """
        self.orchestrator = orchestrator
        self.repo_manager = repo_manager
        self.config = WebhookConfig(config_path)

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str
    ) -> bool:
        """Verify GitLab webhook signature."""
        if not secret:
            logger.warning("No webhook secret configured - rejecting webhook for security")
            return False

        # GitLab sends the secret token directly in X-Gitlab-Token header
        # Use timing-safe comparison to prevent timing attacks
        if not signature:
            return False
        return hmac.compare_digest(signature, secret)

    def get_webhook_secret(self, repo_id: str) -> Optional[str]:
        """Get webhook secret for a repo from settings, SSM, or environment."""
        # Try environment variable first
        secret = os.environ.get('GITLAB_WEBHOOK_SECRET')
        if secret:
            return secret

        # Try repo-specific secret from repo settings or SSM
        if self.repo_manager:
            repo = self.repo_manager.get_repo(repo_id)
            if repo:
                # Handle Repo dataclass or dict
                settings = getattr(repo, 'settings', None)
                if settings is None and isinstance(repo, dict):
                    settings = repo.get('settings')
                settings = settings or {}

                secret = settings.get('webhook_secret')
                if secret:
                    return secret

                ssm_path = settings.get('webhook_secret_ssm_path')
                if not ssm_path and isinstance(repo, dict):
                    ssm_path = repo.get('webhook_secret_ssm_path')

            if repo and ssm_path:
                # Get from SSM
                import subprocess
                try:
                    result = subprocess.run([
                        'aws', 'ssm', 'get-parameter',
                        '--name', ssm_path,
                        '--with-decryption',
                        '--query', 'Parameter.Value',
                        '--output', 'text'
                    ], capture_output=True, text=True, timeout=30)
                    if result.returncode == 0:
                        return result.stdout.strip()
                except Exception as e:
                    logger.warning(f"Failed to get webhook secret from SSM: {e}")

        return None

    def parse_event(self, headers: Dict[str, str], body: Dict[str, Any]) -> WebhookEvent:
        """Parse GitLab webhook payload into structured event."""
        event_type = headers.get('X-Gitlab-Event', '').lower().replace(' hook', '')

        # Determine action based on event type
        action = None
        if event_type == 'issue':
            action = body.get('object_attributes', {}).get('action')
        elif event_type == 'merge_request':
            action = body.get('object_attributes', {}).get('action')
        elif event_type == 'note':
            action = body.get('object_attributes', {}).get('noteable_type', '').lower()
        elif event_type == 'pipeline':
            action = body.get('object_attributes', {}).get('status')
        elif event_type == 'push':
            action = None

        # Get repo identifier from payload
        project = body.get('project', {})
        repo_id = project.get('path_with_namespace', str(project.get('id', 'unknown')))

        return WebhookEvent(
            event_type=event_type,
            action=action,
            repo_id=repo_id,
            payload=body,
            timestamp=datetime.utcnow()
        )

    def _resolve_repo(self, project: Dict[str, Any]) -> Optional[Any]:
        """Resolve Auto-Dev repo from GitLab project metadata."""
        if not self.repo_manager:
            return None

        project_path = project.get('path_with_namespace')
        project_id = project.get('id')
        if not project_path and project_id is not None:
            project_path = str(project_id)

        if not project_path:
            return None

        # Prefer lookup by GitLab project path/id
        getter = getattr(self.repo_manager, 'get_repo_by_project_id', None)
        if callable(getter):
            return getter(project_path)

        return None

    def route_event(self, event: WebhookEvent) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Route event to appropriate task creation.

        Returns task info if created, None if event was ignored.
        Supports parallel task creation for events like merge_request:open.
        """
        # Build event key like 'issue:open' or 'merge_request:open'
        if event.action:
            event_key = f"{event.event_type}:{event.action}"
        else:
            event_key = event.event_type

        # Look up routing from config
        routing = self.config.get_routing(event_key)

        # Try without action for catch-all routes
        if routing is None and event.action:
            routing = self.config.get_routing(event.event_type)

        if routing is None:
            logger.info(f"No routing for event: {event_key}")
            return None

        # Check condition if present
        condition = routing.get('condition') if isinstance(routing, dict) else None
        if condition and not evaluate_condition(condition, event):
            logger.info(f"Condition not met for {event_key}: {condition}")
            return None

        # Build task payload
        task_payload = self._build_task_payload(event)

        # Determine priority
        priority = self._calculate_priority(event)

        # Handle parallel task creation
        if isinstance(routing, dict) and 'parallel' in routing:
            return self._create_parallel_tasks(routing['parallel'], task_payload, priority, event)

        # Single task creation
        return self._create_single_task(routing, task_payload, priority, event)

    def _create_single_task(
        self,
        routing: Dict[str, Any],
        task_payload: Dict[str, Any],
        priority: int,
        event: WebhookEvent
    ) -> Optional[Dict[str, Any]]:
        """Create a single task from routing config."""
        task = self.orchestrator.create_task(
            task_type=routing['task_type'],
            payload=task_payload,
            priority=priority,
            created_by='gitlab_webhook',
            repo_id=event.repo_id
        )

        if task:
            logger.info(
                f"Created task {task.id} ({routing['task_type']}) "
                f"for {event.event_type}/{event.action} in {event.repo_id}"
            )
            return {
                'task_id': task.id,
                'task_type': routing['task_type'],
                'agent': routing['agent'],
                'repo_id': event.repo_id
            }

        return None

    def _create_parallel_tasks(
        self,
        parallel_routes: List[Dict[str, Any]],
        task_payload: Dict[str, Any],
        priority: int,
        event: WebhookEvent
    ) -> List[Dict[str, Any]]:
        """Create multiple tasks in parallel from routing config."""
        results = []

        for route in parallel_routes:
            # Check individual condition if present
            condition = route.get('condition')
            if condition and not evaluate_condition(condition, event):
                logger.info(f"Skipping parallel task {route['task_type']}: condition not met")
                continue

            task = self.orchestrator.create_task(
                task_type=route['task_type'],
                payload=task_payload,
                priority=priority,
                created_by='gitlab_webhook',
                repo_id=event.repo_id
            )

            if task:
                logger.info(
                    f"Created parallel task {task.id} ({route['task_type']}) "
                    f"for {event.event_type}/{event.action} in {event.repo_id}"
                )
                results.append({
                    'task_id': task.id,
                    'task_type': route['task_type'],
                    'agent': route['agent'],
                    'repo_id': event.repo_id
                })

        return results if results else None

    def _build_task_payload(self, event: WebhookEvent) -> Dict[str, Any]:
        """Build task payload from webhook event."""
        payload = {
            'source': 'gitlab_webhook',
            'event_type': event.event_type,
            'action': event.action,
            'repo_id': event.repo_id,
            'timestamp': event.timestamp.isoformat(),
        }
        repo_meta = event.payload.get('_auto_dev_repo') if isinstance(event.payload, dict) else None
        if repo_meta:
            payload['repo'] = repo_meta

        obj_attrs = event.payload.get('object_attributes', {})
        project = event.payload.get('project', {})

        # Add common fields
        payload['project'] = {
            'id': project.get('id'),
            'name': project.get('name'),
            'path_with_namespace': project.get('path_with_namespace'),
            'web_url': project.get('web_url'),
            'default_branch': project.get('default_branch', 'main'),
        }

        # Add event-specific fields
        if event.event_type == 'issue':
            payload['issue'] = {
                'iid': obj_attrs.get('iid'),
                'title': obj_attrs.get('title'),
                'description': obj_attrs.get('description'),
                'state': obj_attrs.get('state'),
                'labels': [l.get('title') for l in event.payload.get('labels', [])],
                'url': obj_attrs.get('url'),
            }

        elif event.event_type == 'merge_request':
            payload['merge_request'] = {
                'iid': obj_attrs.get('iid'),
                'title': obj_attrs.get('title'),
                'description': obj_attrs.get('description'),
                'state': obj_attrs.get('state'),
                'source_branch': obj_attrs.get('source_branch'),
                'target_branch': obj_attrs.get('target_branch'),
                'labels': [l.get('title') for l in event.payload.get('labels', [])],
                'url': obj_attrs.get('url'),
                'merge_status': obj_attrs.get('merge_status'),
            }

        elif event.event_type == 'note':
            payload['note'] = {
                'id': obj_attrs.get('id'),
                'body': obj_attrs.get('note'),
                'noteable_type': obj_attrs.get('noteable_type'),
                'noteable_id': obj_attrs.get('noteable_id'),
                'author': event.payload.get('user', {}).get('username'),
            }
            # Include the related issue/MR info
            if event.payload.get('issue'):
                payload['issue'] = {
                    'iid': event.payload['issue'].get('iid'),
                    'title': event.payload['issue'].get('title'),
                }
            if event.payload.get('merge_request'):
                payload['merge_request'] = {
                    'iid': event.payload['merge_request'].get('iid'),
                    'title': event.payload['merge_request'].get('title'),
                }

        elif event.event_type == 'pipeline':
            payload['pipeline'] = {
                'id': obj_attrs.get('id'),
                'status': obj_attrs.get('status'),
                'ref': obj_attrs.get('ref'),
                'sha': obj_attrs.get('sha'),
                'duration': obj_attrs.get('duration'),
                'url': event.payload.get('project', {}).get('web_url') +
                       f"/-/pipelines/{obj_attrs.get('id')}",
            }

        elif event.event_type == 'push':
            payload['push'] = {
                'ref': event.payload.get('ref'),
                'before': event.payload.get('before'),
                'after': event.payload.get('after'),
                'commits': [
                    {
                        'id': c.get('id'),
                        'message': c.get('message'),
                        'author': c.get('author', {}).get('name'),
                    }
                    for c in event.payload.get('commits', [])[:10]  # Limit to 10
                ],
                'total_commits': event.payload.get('total_commits_count', 0),
            }

        return payload

    def _calculate_priority(self, event: WebhookEvent) -> int:
        """Calculate task priority based on event type and labels."""
        base_priority = 5

        # Higher priority for certain events
        priority_boost = {
            ('pipeline', 'failed'): 3,  # Failed pipeline is urgent
            ('merge_request', 'open'): 1,
            ('issue', 'open'): 0,
        }

        boost = priority_boost.get((event.event_type, event.action), 0)

        # Check for priority labels
        labels = []
        if 'labels' in event.payload:
            labels = [l.get('title', '').lower() for l in event.payload.get('labels', [])]
        elif 'object_attributes' in event.payload:
            labels = event.payload['object_attributes'].get('labels', [])

        if any(l in ['critical', 'urgent', 'p0', 'priority::critical'] for l in labels):
            boost += 3
        elif any(l in ['high', 'p1', 'priority::high'] for l in labels):
            boost += 2
        elif any(l in ['low', 'p3', 'priority::low'] for l in labels):
            boost -= 1

        return min(10, max(1, base_priority + boost))

    async def handle_webhook(
        self,
        request: Request,
        x_gitlab_event: str = Header(None),
        x_gitlab_token: str = Header(None)
    ) -> Dict[str, Any]:
        """
        Handle incoming webhook request.

        This is the main entry point for webhook processing.
        """
        # Parse body
        body = await request.json()

        # Get repo/project from payload for secret lookup
        project = body.get('project', {})
        repo = self._resolve_repo(project)
        repo_id = repo.id if repo else project.get('path_with_namespace', 'unknown')
        if repo:
            body['_auto_dev_repo'] = {
                'id': repo.id,
                'autonomy_mode': repo.autonomy_mode,
            }

        # Verify signature using timing-safe comparison
        secret = self.get_webhook_secret(repo_id)
        if secret and (not x_gitlab_token or not hmac.compare_digest(x_gitlab_token, secret)):
            logger.warning(f"Invalid webhook token for {repo_id}")
            raise HTTPException(status_code=401, detail="Invalid webhook token")

        # Parse event
        headers = {'X-Gitlab-Event': x_gitlab_event or ''}
        event = self.parse_event(headers, body)
        if repo:
            event.repo_id = repo.id

        logger.info(
            f"Received webhook: {event.event_type}/{event.action} "
            f"for {event.repo_id}"
        )

        # Route to task(s)
        result = self.route_event(event)

        if result:
            # Handle parallel results (list of tasks)
            if isinstance(result, list):
                task_types = [r['task_type'] for r in result]
                task_ids = [r['task_id'] for r in result]
                return {
                    'status': 'accepted',
                    'message': f"Tasks created: {', '.join(task_types)}",
                    'task_ids': task_ids,
                    'tasks': result
                }
            # Single task result
            return {
                'status': 'accepted',
                'message': f"Task created: {result['task_type']}",
                'task_id': result['task_id']
            }

        return {
            'status': 'ignored',
            'message': f"Event {event.event_type}/{event.action} not routed"
        }


# FastAPI route registration
def create_webhook_routes(
    orchestrator,
    repo_manager=None,
    config_path: Optional[str] = None
) -> APIRouter:
    """
    Create webhook routes with injected dependencies.

    Usage:
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(create_webhook_routes(orchestrator))
    """
    handler = WebhookHandler(orchestrator, repo_manager, config_path)

    @router.post("/gitlab")
    async def gitlab_webhook(
        request: Request,
        x_gitlab_event: str = Header(None),
        x_gitlab_token: str = Header(None)
    ):
        return await handler.handle_webhook(request, x_gitlab_event, x_gitlab_token)

    # Backward-compatible route (repo_id is ignored; repo is resolved from payload)
    @router.post("/gitlab/{repo_id}")
    async def gitlab_webhook_repo(
        repo_id: str,
        request: Request,
        x_gitlab_event: str = Header(None),
        x_gitlab_token: str = Header(None)
    ):
        return await handler.handle_webhook(request, x_gitlab_event, x_gitlab_token)

    @router.get("/health")
    async def webhook_health():
        return {"status": "ok", "service": "gitlab_webhook"}

    return router


# Standalone webhook verification for testing
def verify_gitlab_signature(payload: bytes, token: str, secret: str) -> bool:
    """Verify GitLab webhook token.

    GitLab uses simple token-based verification where the secret is sent
    directly in the X-Gitlab-Token header. The payload is not used for
    verification (unlike GitHub's HMAC-based approach).
    """
    if not token or not secret:
        return False
    return hmac.compare_digest(token, secret)
