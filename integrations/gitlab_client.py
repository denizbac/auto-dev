"""
GitLab API Client for Auto-Dev

Provides a comprehensive interface to GitLab's REST API for:
- Issues and Epics
- Merge Requests
- Repository operations (branches, commits, files)
- Pipelines
- Comments and discussions
"""

import os
import json
import time
import logging
import subprocess
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)


@dataclass
class GitLabConfig:
    """GitLab connection configuration."""
    url: str
    project_id: str
    token: str
    default_branch: str = "main"
    mr_prefix: str = "[AUTO-DEV]"


class GitLabClient:
    """
    GitLab API client for auto-dev operations.

    Supports all operations needed for autonomous software development:
    - Issue/Epic management
    - Merge Request lifecycle
    - Repository operations
    - Pipeline management
    """

    def __init__(self, config: GitLabConfig):
        self.config = config
        self.base_url = f"{config.url}/api/v4"
        self.project_url = f"{self.base_url}/projects/{urllib.parse.quote(config.project_id, safe='')}"
        self._rate_limit_remaining = 100
        self._rate_limit_reset = 0

    @classmethod
    def from_repo_config(cls, repo_config: Dict[str, Any]) -> 'GitLabClient':
        """Create client from repo configuration stored in database."""
        token = cls._get_token(repo_config.get('token_ssm_path') or repo_config.get('slug'))
        return cls(GitLabConfig(
            url=repo_config['gitlab_url'],
            project_id=repo_config['gitlab_project_id'],
            token=token,
            default_branch=repo_config.get('default_branch', 'main'),
            mr_prefix=repo_config.get('mr_prefix', '[AUTO-DEV]')
        ))

    @staticmethod
    def _get_token(repo_slug: str) -> str:
        """Get GitLab token from environment or AWS SSM."""
        # Try environment variable first
        token = os.environ.get('GITLAB_TOKEN')
        if token:
            return token

        # Try SSM
        ssm_path = f"/auto-dev/{repo_slug}/gitlab-token"
        try:
            result = subprocess.run([
                'aws', 'ssm', 'get-parameter',
                '--name', ssm_path,
                '--with-decryption',
                '--query', 'Parameter.Value',
                '--output', 'text',
                '--region', os.environ.get('AWS_REGION', 'us-east-1')
            ], capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to get token from SSM: {e}")

        raise ValueError(f"No GitLab token found for repo: {repo_slug}")

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an API request to GitLab."""
        url = f"{self.project_url}{endpoint}"
        if params:
            url += '?' + urllib.parse.urlencode(params)

        headers = {
            'PRIVATE-TOKEN': self.config.token,
            'Content-Type': 'application/json'
        }

        body = json.dumps(data).encode() if data else None

        request = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            # Respect rate limits
            if self._rate_limit_remaining < 5:
                wait_time = max(0, self._rate_limit_reset - time.time())
                if wait_time > 0:
                    logger.info(f"Rate limit low, waiting {wait_time:.1f}s")
                    time.sleep(wait_time)

            with urllib.request.urlopen(request, timeout=60) as response:
                # Update rate limit tracking
                self._rate_limit_remaining = int(response.headers.get('RateLimit-Remaining', 100))
                self._rate_limit_reset = int(response.headers.get('RateLimit-Reset', 0))

                content = response.read().decode()
                return json.loads(content) if content else {}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ''
            logger.error(f"GitLab API error: {e.code} - {error_body}")
            raise
        except urllib.error.URLError as e:
            logger.error(f"GitLab connection error: {e.reason}")
            raise

    # ========== Issues ==========

    def create_issue(
        self,
        title: str,
        description: str,
        labels: Optional[List[str]] = None,
        assignee_ids: Optional[List[int]] = None,
        milestone_id: Optional[int] = None,
        epic_id: Optional[int] = None,
        weight: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new issue."""
        data = {
            'title': title,
            'description': description,
        }
        if labels:
            data['labels'] = ','.join(labels)
        if assignee_ids:
            data['assignee_ids'] = assignee_ids
        if milestone_id:
            data['milestone_id'] = milestone_id
        if epic_id:
            data['epic_id'] = epic_id
        if weight:
            data['weight'] = weight

        return self._request('POST', '/issues', data)

    def get_issue(self, issue_iid: int) -> Dict[str, Any]:
        """Get issue by IID (internal ID)."""
        return self._request('GET', f'/issues/{issue_iid}')

    def update_issue(
        self,
        issue_iid: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[List[str]] = None,
        state_event: Optional[str] = None,  # 'close' or 'reopen'
        **kwargs
    ) -> Dict[str, Any]:
        """Update an existing issue."""
        data = {}
        if title:
            data['title'] = title
        if description:
            data['description'] = description
        if labels is not None:
            data['labels'] = ','.join(labels)
        if state_event:
            data['state_event'] = state_event
        data.update(kwargs)

        return self._request('PUT', f'/issues/{issue_iid}', data)

    def close_issue(self, issue_iid: int) -> Dict[str, Any]:
        """Close an issue."""
        return self.update_issue(issue_iid, state_event='close')

    def list_issues(
        self,
        state: str = 'opened',
        labels: Optional[List[str]] = None,
        search: Optional[str] = None,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """List issues with optional filters."""
        params = {'state': state, 'per_page': per_page}
        if labels:
            params['labels'] = ','.join(labels)
        if search:
            params['search'] = search

        return self._request('GET', '/issues', params=params)

    def add_issue_comment(self, issue_iid: int, body: str) -> Dict[str, Any]:
        """Add a comment to an issue."""
        return self._request('POST', f'/issues/{issue_iid}/notes', {'body': body})

    # ========== Merge Requests ==========

    def create_mr(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: Optional[List[str]] = None,
        assignee_ids: Optional[List[int]] = None,
        remove_source_branch: bool = True,
        squash: bool = True
    ) -> Dict[str, Any]:
        """Create a new merge request."""
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'description': description,
            'remove_source_branch': remove_source_branch,
            'squash': squash
        }
        if labels:
            data['labels'] = ','.join(labels)
        if assignee_ids:
            data['assignee_ids'] = assignee_ids

        return self._request('POST', '/merge_requests', data)

    def get_mr(self, mr_iid: int) -> Dict[str, Any]:
        """Get merge request by IID."""
        return self._request('GET', f'/merge_requests/{mr_iid}')

    def update_mr(
        self,
        mr_iid: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[List[str]] = None,
        state_event: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Update a merge request."""
        data = {}
        if title:
            data['title'] = title
        if description:
            data['description'] = description
        if labels is not None:
            data['labels'] = ','.join(labels)
        if state_event:
            data['state_event'] = state_event
        data.update(kwargs)

        return self._request('PUT', f'/merge_requests/{mr_iid}', data)

    def approve_mr(self, mr_iid: int) -> Dict[str, Any]:
        """Approve a merge request."""
        return self._request('POST', f'/merge_requests/{mr_iid}/approve')

    def unapprove_mr(self, mr_iid: int) -> Dict[str, Any]:
        """Remove approval from a merge request."""
        return self._request('POST', f'/merge_requests/{mr_iid}/unapprove')

    def merge_mr(
        self,
        mr_iid: int,
        squash: bool = True,
        should_remove_source_branch: bool = True,
        merge_commit_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Merge a merge request."""
        data = {
            'squash': squash,
            'should_remove_source_branch': should_remove_source_branch
        }
        if merge_commit_message:
            data['merge_commit_message'] = merge_commit_message

        return self._request('PUT', f'/merge_requests/{mr_iid}/merge', data)

    def list_mrs(
        self,
        state: str = 'opened',
        labels: Optional[List[str]] = None,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """List merge requests."""
        params = {'state': state, 'per_page': per_page}
        if labels:
            params['labels'] = ','.join(labels)

        return self._request('GET', '/merge_requests', params=params)

    def get_mr_changes(self, mr_iid: int) -> Dict[str, Any]:
        """Get the changes (diff) in a merge request."""
        return self._request('GET', f'/merge_requests/{mr_iid}/changes')

    def get_mr_commits(self, mr_iid: int) -> List[Dict[str, Any]]:
        """Get commits in a merge request."""
        return self._request('GET', f'/merge_requests/{mr_iid}/commits')

    # ========== MR Comments/Discussions ==========

    def add_mr_comment(
        self,
        mr_iid: int,
        body: str,
        position: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Add a comment to a merge request.

        For inline comments, provide position dict with:
        - base_sha, head_sha, start_sha
        - old_path, new_path
        - old_line or new_line
        - position_type: 'text'
        """
        data = {'body': body}
        if position:
            data['position'] = position

        return self._request('POST', f'/merge_requests/{mr_iid}/discussions', data)

    def add_inline_comment(
        self,
        mr_iid: int,
        body: str,
        file_path: str,
        line: int,
        line_type: str = 'new'  # 'new' or 'old'
    ) -> Dict[str, Any]:
        """
        Add an inline comment to a specific line in the diff.

        Simplified version of add_mr_comment for common use case.
        """
        # Get MR diff refs
        mr = self.get_mr(mr_iid)
        diff_refs = mr.get('diff_refs', {})

        position = {
            'base_sha': diff_refs.get('base_sha'),
            'head_sha': diff_refs.get('head_sha'),
            'start_sha': diff_refs.get('start_sha'),
            'position_type': 'text',
            'new_path': file_path,
            'old_path': file_path,
        }

        if line_type == 'new':
            position['new_line'] = line
        else:
            position['old_line'] = line

        return self.add_mr_comment(mr_iid, body, position)

    def resolve_discussion(self, mr_iid: int, discussion_id: str) -> Dict[str, Any]:
        """Resolve a discussion thread."""
        return self._request(
            'PUT',
            f'/merge_requests/{mr_iid}/discussions/{discussion_id}',
            {'resolved': True}
        )

    # ========== Repository ==========

    def get_file(
        self,
        file_path: str,
        ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get file content from repository."""
        ref = ref or self.config.default_branch
        encoded_path = urllib.parse.quote(file_path, safe='')
        return self._request('GET', f'/repository/files/{encoded_path}', params={'ref': ref})

    def get_file_content(self, file_path: str, ref: Optional[str] = None) -> str:
        """Get decoded file content."""
        import base64
        file_data = self.get_file(file_path, ref)
        return base64.b64decode(file_data['content']).decode()

    def list_tree(
        self,
        path: str = '',
        ref: Optional[str] = None,
        recursive: bool = False
    ) -> List[Dict[str, Any]]:
        """List repository tree (files and directories)."""
        ref = ref or self.config.default_branch
        params = {'ref': ref, 'recursive': str(recursive).lower()}
        if path:
            params['path'] = path

        return self._request('GET', '/repository/tree', params=params)

    def create_branch(
        self,
        branch_name: str,
        ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new branch."""
        ref = ref or self.config.default_branch
        return self._request('POST', '/repository/branches', {
            'branch': branch_name,
            'ref': ref
        })

    def delete_branch(self, branch_name: str) -> bool:
        """Delete a branch."""
        encoded_branch = urllib.parse.quote(branch_name, safe='')
        try:
            self._request('DELETE', f'/repository/branches/{encoded_branch}')
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def commit_files(
        self,
        branch: str,
        commit_message: str,
        actions: List[Dict[str, Any]],
        start_branch: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Commit multiple file changes.

        Each action should have:
        - action: 'create', 'delete', 'move', 'update', 'chmod'
        - file_path: path to file
        - content: file content (for create/update)
        - previous_path: for move action
        """
        data = {
            'branch': branch,
            'commit_message': commit_message,
            'actions': actions
        }
        if start_branch:
            data['start_branch'] = start_branch

        return self._request('POST', '/repository/commits', data)

    def create_file(
        self,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str
    ) -> Dict[str, Any]:
        """Create a single file."""
        return self.commit_files(branch, commit_message, [{
            'action': 'create',
            'file_path': file_path,
            'content': content
        }])

    def update_file(
        self,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str
    ) -> Dict[str, Any]:
        """Update a single file."""
        return self.commit_files(branch, commit_message, [{
            'action': 'update',
            'file_path': file_path,
            'content': content
        }])

    # ========== Pipelines ==========

    def get_pipeline(self, pipeline_id: int) -> Dict[str, Any]:
        """Get pipeline by ID."""
        return self._request('GET', f'/pipelines/{pipeline_id}')

    def list_pipelines(
        self,
        ref: Optional[str] = None,
        status: Optional[str] = None,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """List pipelines."""
        params = {'per_page': per_page}
        if ref:
            params['ref'] = ref
        if status:
            params['status'] = status

        return self._request('GET', '/pipelines', params=params)

    def get_pipeline_jobs(self, pipeline_id: int) -> List[Dict[str, Any]]:
        """Get jobs in a pipeline."""
        return self._request('GET', f'/pipelines/{pipeline_id}/jobs')

    def retry_pipeline(self, pipeline_id: int) -> Dict[str, Any]:
        """Retry a failed pipeline."""
        return self._request('POST', f'/pipelines/{pipeline_id}/retry')

    def cancel_pipeline(self, pipeline_id: int) -> Dict[str, Any]:
        """Cancel a running pipeline."""
        return self._request('POST', f'/pipelines/{pipeline_id}/cancel')

    def get_job_log(self, job_id: int) -> str:
        """Get job log output."""
        # This endpoint returns plain text, not JSON
        url = f"{self.project_url}/jobs/{job_id}/trace"
        request = urllib.request.Request(url, headers={
            'PRIVATE-TOKEN': self.config.token
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode()

    # ========== Epics (Premium feature) ==========

    def create_epic(
        self,
        title: str,
        description: str,
        labels: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create an epic (requires GitLab Premium)."""
        # Epics are at group level, need to extract group from project
        # This is a simplified implementation
        data = {
            'title': title,
            'description': description
        }
        if labels:
            data['labels'] = ','.join(labels)
        if start_date:
            data['start_date'] = start_date
        if due_date:
            data['due_date'] = due_date

        # Note: Epic API uses group endpoint, not project
        # This assumes project_id contains group/project format
        group_path = '/'.join(self.config.project_id.split('/')[:-1])
        group_url = f"{self.base_url}/groups/{urllib.parse.quote(group_path, safe='')}/epics"

        request = urllib.request.Request(
            group_url,
            data=json.dumps(data).encode(),
            headers={
                'PRIVATE-TOKEN': self.config.token,
                'Content-Type': 'application/json'
            },
            method='POST'
        )

        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())

    # ========== Webhooks ==========

    def list_webhooks(self) -> List[Dict[str, Any]]:
        """List project webhooks."""
        return self._request('GET', '/hooks')

    def create_webhook(
        self,
        url: str,
        secret_token: str,
        push_events: bool = True,
        issues_events: bool = True,
        merge_requests_events: bool = True,
        note_events: bool = True,
        pipeline_events: bool = True
    ) -> Dict[str, Any]:
        """Create a project webhook."""
        return self._request('POST', '/hooks', {
            'url': url,
            'token': secret_token,
            'push_events': push_events,
            'issues_events': issues_events,
            'merge_requests_events': merge_requests_events,
            'note_events': note_events,
            'pipeline_events': pipeline_events
        })

    # ========== Utility Methods ==========

    def clone_repo(self, target_dir: str, branch: Optional[str] = None) -> bool:
        """Clone the repository to a local directory."""
        branch = branch or self.config.default_branch
        clone_url = f"{self.config.url}/{self.config.project_id}.git"

        # Use token in URL for auth
        if '://' in clone_url:
            protocol, rest = clone_url.split('://', 1)
            clone_url = f"{protocol}://oauth2:{self.config.token}@{rest}"

        try:
            subprocess.run([
                'git', 'clone',
                '--branch', branch,
                '--single-branch',
                '--depth', '1',
                clone_url,
                target_dir
            ], check=True, capture_output=True, timeout=300)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Clone failed: {e.stderr.decode()}")
            return False

    def get_project_info(self) -> Dict[str, Any]:
        """Get project information."""
        url = f"{self.base_url}/projects/{urllib.parse.quote(self.config.project_id, safe='')}"
        request = urllib.request.Request(url, headers={
            'PRIVATE-TOKEN': self.config.token
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
