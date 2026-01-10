"""
Auto-Dev Integrations Module

External service integrations for GitLab and other services.
"""

from .gitlab_client import GitLabClient

__all__ = ['GitLabClient']
