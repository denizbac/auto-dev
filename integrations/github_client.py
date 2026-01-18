"""
GitHub API Client for Auto-Dev

Provides a comprehensive interface to GitHub's REST API for:
- Issues and Pull Requests
- Repository operations (branches, commits, files)
- Actions/Workflows
- Comments and reviews
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
class GitHubConfig:
    """GitHub connection configuration."""
    owner: str
    repo: str
    token: str
    default_branch: str = "main"
    pr_prefix: str = "[AUTO-DEV]"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class GitHubClient:
    """
    GitHub API client for auto-dev operations.

    Supports all operations needed for autonomous software development:
    - Issue management
    - Pull Request lifecycle
    - Repository operations
    - Actions/Workflow management
    """

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.base_url = "https://api.github.com"
        self.repo_url = f"{self.base_url}/repos/{config.owner}/{config.repo}"
        self._rate_limit_remaining = 5000
        self._rate_limit_reset = 0

    @classmethod
    def from_repo_config(cls, repo_config: Dict[str, Any]) -> 'GitHubClient':
        """Create client from repo configuration stored in database."""
        token = cls._get_token(repo_config.get('token_ssm_path') or repo_config.get('slug'))

        # Parse owner/repo from github_url or project_id
        # Supports formats: "owner/repo" or "https://github.com/owner/repo"
        project_id = repo_config.get('gitlab_project_id', '')  # Reusing field for now
        if '/' in project_id and 'github.com' not in project_id:
            owner, repo = project_id.split('/', 1)
        elif 'github.com' in repo_config.get('gitlab_url', ''):
            # Parse from URL
            url = repo_config['gitlab_url']
            parts = url.rstrip('/').split('/')
            owner, repo = parts[-2], parts[-1]
        else:
            raise ValueError(f"Cannot parse GitHub owner/repo from config: {repo_config}")

        return cls(GitHubConfig(
            owner=owner,
            repo=repo,
            token=token,
            default_branch=repo_config.get('default_branch', 'main'),
            pr_prefix=repo_config.get('pr_prefix', '[AUTO-DEV]')
        ))

    @staticmethod
    def _get_token(repo_slug: str = None) -> str:
        """Get GitHub token from environment or AWS SSM."""
        # Try environment variable first
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            return token

        # Try global SSM path
        ssm_paths = ["/auto-dev/github-token"]
        if repo_slug:
            ssm_paths.insert(0, f"/auto-dev/{repo_slug}/github-token")

        for ssm_path in ssm_paths:
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
                logger.debug(f"Failed to get token from SSM {ssm_path}: {e}")

        raise ValueError(f"No GitHub token found")

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an API request to GitHub."""
        # Build URL
        url = endpoint if endpoint.startswith('http') else f"{self.repo_url}{endpoint}"
        if params:
            url += '?' + urllib.parse.urlencode(params)

        # Prepare request
        headers = {
            'Authorization': f'Bearer {self.config.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'Auto-Dev/1.0'
        }

        body = None
        if data:
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        # Check rate limit
        if self._rate_limit_remaining < 10 and time.time() < self._rate_limit_reset:
            wait_time = self._rate_limit_reset - time.time() + 1
            logger.warning(f"Rate limit low, waiting {wait_time:.0f}s")
            time.sleep(wait_time)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                # Update rate limit info
                self._rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 5000))
                self._rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', 0))

                content = response.read().decode('utf-8')
                return json.loads(content) if content else {}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            logger.error(f"GitHub API error: {e.code} {e.reason} - {error_body}")
            raise
        except urllib.error.URLError as e:
            logger.error(f"GitHub API connection error: {e.reason}")
            raise

    # ==================== Issues ====================

    def get_issue(self, issue_number: int) -> Dict[str, Any]:
        """Get a single issue."""
        return self._request('GET', f'/issues/{issue_number}')

    def list_issues(
        self,
        state: str = 'open',
        labels: Optional[List[str]] = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List issues."""
        params = {'state': state, 'per_page': per_page}
        if labels:
            params['labels'] = ','.join(labels)
        return self._request('GET', '/issues', params=params)

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new issue."""
        data = {'title': title, 'body': body}
        if labels:
            data['labels'] = labels
        if assignees:
            data['assignees'] = assignees
        return self._request('POST', '/issues', data=data)

    def update_issue(
        self,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Update an issue."""
        data = {}
        if title:
            data['title'] = title
        if body:
            data['body'] = body
        if state:
            data['state'] = state
        if labels is not None:
            data['labels'] = labels
        return self._request('PATCH', f'/issues/{issue_number}', data=data)

    def add_issue_comment(self, issue_number: int, body: str) -> Dict[str, Any]:
        """Add a comment to an issue."""
        return self._request('POST', f'/issues/{issue_number}/comments', data={'body': body})

    # ==================== Pull Requests ====================

    def get_pull_request(self, pr_number: int) -> Dict[str, Any]:
        """Get a single pull request."""
        return self._request('GET', f'/pulls/{pr_number}')

    def list_pull_requests(
        self,
        state: str = 'open',
        head: Optional[str] = None,
        base: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List pull requests."""
        params = {'state': state, 'per_page': per_page}
        if head:
            params['head'] = head
        if base:
            params['base'] = base
        return self._request('GET', '/pulls', params=params)

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
        draft: bool = False
    ) -> Dict[str, Any]:
        """Create a pull request."""
        data = {
            'title': f"{self.config.pr_prefix} {title}",
            'body': body,
            'head': head,
            'base': base or self.config.default_branch,
            'draft': draft
        }
        return self._request('POST', '/pulls', data=data)

    def merge_pull_request(
        self,
        pr_number: int,
        commit_title: Optional[str] = None,
        merge_method: str = 'squash'
    ) -> Dict[str, Any]:
        """Merge a pull request."""
        data = {'merge_method': merge_method}
        if commit_title:
            data['commit_title'] = commit_title
        return self._request('PUT', f'/pulls/{pr_number}/merge', data=data)

    def add_pr_comment(self, pr_number: int, body: str) -> Dict[str, Any]:
        """Add a comment to a pull request."""
        return self.add_issue_comment(pr_number, body)  # PRs use issue comments API

    def create_pr_review(
        self,
        pr_number: int,
        body: str,
        event: str = 'COMMENT'  # APPROVE, REQUEST_CHANGES, COMMENT
    ) -> Dict[str, Any]:
        """Create a pull request review."""
        return self._request('POST', f'/pulls/{pr_number}/reviews', data={
            'body': body,
            'event': event
        })

    # ==================== Branches ====================

    def get_branch(self, branch: str) -> Dict[str, Any]:
        """Get branch information."""
        return self._request('GET', f'/branches/{branch}')

    def list_branches(self, per_page: int = 30) -> List[Dict[str, Any]]:
        """List branches."""
        return self._request('GET', '/branches', params={'per_page': per_page})

    def create_branch(self, branch_name: str, from_branch: Optional[str] = None) -> Dict[str, Any]:
        """Create a new branch."""
        # Get the SHA of the source branch
        source = from_branch or self.config.default_branch
        source_branch = self.get_branch(source)
        sha = source_branch['commit']['sha']

        # Create the ref
        return self._request('POST', f'{self.base_url}/repos/{self.config.owner}/{self.config.repo}/git/refs', data={
            'ref': f'refs/heads/{branch_name}',
            'sha': sha
        })

    def delete_branch(self, branch: str) -> None:
        """Delete a branch."""
        self._request('DELETE', f'{self.base_url}/repos/{self.config.owner}/{self.config.repo}/git/refs/heads/{branch}')

    # ==================== Files ====================

    def get_file_content(self, path: str, ref: Optional[str] = None) -> Dict[str, Any]:
        """Get file content."""
        params = {}
        if ref:
            params['ref'] = ref
        return self._request('GET', f'/contents/{path}', params=params)

    def create_or_update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: Optional[str] = None,
        sha: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create or update a file."""
        import base64
        data = {
            'message': message,
            'content': base64.b64encode(content.encode()).decode(),
            'branch': branch or self.config.default_branch
        }
        if sha:
            data['sha'] = sha
        return self._request('PUT', f'/contents/{path}', data=data)

    def delete_file(
        self,
        path: str,
        message: str,
        sha: str,
        branch: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete a file."""
        data = {
            'message': message,
            'sha': sha,
            'branch': branch or self.config.default_branch
        }
        return self._request('DELETE', f'/contents/{path}', data=data)

    # ==================== Commits ====================

    def get_commit(self, sha: str) -> Dict[str, Any]:
        """Get a commit."""
        return self._request('GET', f'/commits/{sha}')

    def list_commits(
        self,
        sha: Optional[str] = None,
        path: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List commits."""
        params = {'per_page': per_page}
        if sha:
            params['sha'] = sha
        if path:
            params['path'] = path
        return self._request('GET', '/commits', params=params)

    def compare_commits(self, base: str, head: str) -> Dict[str, Any]:
        """Compare two commits."""
        return self._request('GET', f'/compare/{base}...{head}')

    # ==================== Actions/Workflows ====================

    def list_workflow_runs(
        self,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
        status: Optional[str] = None,
        per_page: int = 10
    ) -> Dict[str, Any]:
        """List workflow runs."""
        endpoint = f'/actions/workflows/{workflow_id}/runs' if workflow_id else '/actions/runs'
        params = {'per_page': per_page}
        if branch:
            params['branch'] = branch
        if status:
            params['status'] = status
        return self._request('GET', endpoint, params=params)

    def get_workflow_run(self, run_id: int) -> Dict[str, Any]:
        """Get a workflow run."""
        return self._request('GET', f'/actions/runs/{run_id}')

    def rerun_workflow(self, run_id: int) -> Dict[str, Any]:
        """Re-run a workflow."""
        return self._request('POST', f'/actions/runs/{run_id}/rerun')

    def cancel_workflow_run(self, run_id: int) -> Dict[str, Any]:
        """Cancel a workflow run."""
        return self._request('POST', f'/actions/runs/{run_id}/cancel')

    # ==================== Repository ====================

    def get_repository(self) -> Dict[str, Any]:
        """Get repository information."""
        return self._request('GET', '')

    def get_readme(self) -> Dict[str, Any]:
        """Get repository README."""
        return self._request('GET', '/readme')

    def list_contributors(self, per_page: int = 30) -> List[Dict[str, Any]]:
        """List repository contributors."""
        return self._request('GET', '/contributors', params={'per_page': per_page})

    # ==================== Labels ====================

    def list_labels(self) -> List[Dict[str, Any]]:
        """List repository labels."""
        return self._request('GET', '/labels')

    def create_label(self, name: str, color: str, description: Optional[str] = None) -> Dict[str, Any]:
        """Create a label."""
        data = {'name': name, 'color': color}
        if description:
            data['description'] = description
        return self._request('POST', '/labels', data=data)
