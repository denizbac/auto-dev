#!/usr/bin/env python3
"""
GitHub Issue Monitor for Support Agent

Polls GitHub API for new issues across cybeleri/* repos,
classifies them, and tracks which have been processed.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Issue classification keywords
BUG_KEYWORDS = ['bug', 'error', 'broken', 'fix', 'crash', "doesn't work", 'fails', 'issue', 'problem', 'not working']
FEATURE_KEYWORDS = ['feature', 'enhancement', 'request', 'add', 'would be nice', 'suggestion', 'proposal', 'improve']
QUESTION_KEYWORDS = ['question', 'help', 'how to', 'how do i', 'what is', 'documentation', 'example', 'explain']

# Auto-reply templates
REPLY_TEMPLATES = {
    'bug': """Thanks for reporting this issue! 🙏

We're looking into it and will update this issue when we have more information.

In the meantime, if you have any additional details (steps to reproduce, error logs, environment info), please share them here.""",
    
    'feature': """Thanks for the suggestion! 💡

We've added this to our review queue. We evaluate all feature requests to ensure they align with our project goals.

We'll update this issue with our decision.""",
    
    'question': """Thanks for reaching out! 📚

We'll get back to you with an answer soon. In the meantime, you might find our README helpful for common questions."""
}


class GitHubMonitor:
    """Monitor GitHub issues across repositories."""
    
    def __init__(self, db_path: str = '/autonomous-claude/data/orchestrator.db'):
        """Initialize the monitor."""
        self.db_path = db_path
        self.github_token = self._get_github_token()
        self._ensure_table_exists()
    
    def _get_github_token(self) -> Optional[str]:
        """Get GitHub token from environment or AWS SSM."""
        # Try environment first
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            return token
        
        # Try AWS SSM
        try:
            result = subprocess.run([
                'aws', 'ssm', 'get-parameter',
                '--name', '/autonomous-claude/github/token',
                '--with-decryption',
                '--query', 'Parameter.Value',
                '--output', 'text',
                '--region', 'us-east-1'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to get token from SSM: {e}")
        
        return None
    
    def _ensure_table_exists(self):
        """Ensure the processed_issues table exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_issues (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    issue_number INTEGER,
                    issue_type TEXT,
                    task_id TEXT,
                    processed_at TEXT NOT NULL,
                    responded BOOLEAN DEFAULT FALSE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_issues_repo 
                ON processed_issues(repo, issue_number)
            """)
            conn.commit()
    
    def _run_gh_command(self, args: List[str]) -> Optional[str]:
        """Run a gh CLI command and return output."""
        if not self.github_token:
            logger.error("No GitHub token available")
            return None
        
        env = os.environ.copy()
        env['GITHUB_TOKEN'] = self.github_token
        
        try:
            result = subprocess.run(
                ['gh'] + args,
                capture_output=True,
                text=True,
                env=env,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"gh command failed: {result.stderr}")
                return None
            
            return result.stdout
        except Exception as e:
            logger.error(f"Failed to run gh command: {e}")
            return None
    
    def list_repos(self, owner: str = 'cybeleri') -> List[str]:
        """List all repositories for an owner."""
        output = self._run_gh_command([
            'repo', 'list', owner,
            '--limit', '50',
            '--json', 'name',
            '--no-archived'
        ])
        
        if not output:
            return []
        
        try:
            repos = json.loads(output)
            return [r['name'] for r in repos]
        except json.JSONDecodeError:
            logger.error("Failed to parse repo list")
            return []
    
    def get_issues(self, repo: str, owner: str = 'cybeleri') -> List[Dict]:
        """Get open issues for a repository."""
        output = self._run_gh_command([
            'issue', 'list',
            '--repo', f'{owner}/{repo}',
            '--state', 'open',
            '--json', 'number,title,body,labels,createdAt,url'
        ])
        
        if not output:
            return []
        
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse issues for {repo}")
            return []
    
    def is_processed(self, repo: str, issue_number: int) -> bool:
        """Check if an issue has already been processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM processed_issues WHERE repo = ? AND issue_number = ?",
                (repo, issue_number)
            )
            return cursor.fetchone() is not None
    
    def classify_issue(self, title: str, body: str, labels: List[Dict]) -> str:
        """Classify an issue as bug, feature, or question."""
        text = (title + ' ' + (body or '')).lower()
        label_names = [l.get('name', '').lower() for l in labels]
        
        # Check labels first (most reliable)
        if any('bug' in l for l in label_names):
            return 'bug'
        if any(l in ['enhancement', 'feature', 'feature request'] for l in label_names):
            return 'feature'
        if any(l in ['question', 'help', 'support'] for l in label_names):
            return 'question'
        
        # Check keywords in text
        bug_score = sum(1 for kw in BUG_KEYWORDS if kw in text)
        feature_score = sum(1 for kw in FEATURE_KEYWORDS if kw in text)
        question_score = sum(1 for kw in QUESTION_KEYWORDS if kw in text)
        
        scores = {'bug': bug_score, 'feature': feature_score, 'question': question_score}
        max_type = max(scores, key=scores.get)
        
        # Default to question if no clear signal
        if scores[max_type] == 0:
            return 'question'
        
        return max_type
    
    def post_comment(self, repo: str, issue_number: int, comment: str, owner: str = 'cybeleri') -> bool:
        """Post a comment on an issue."""
        result = self._run_gh_command([
            'issue', 'comment', str(issue_number),
            '--repo', f'{owner}/{repo}',
            '--body', comment
        ])
        return result is not None
    
    def mark_processed(self, repo: str, issue_number: int, issue_type: str, 
                       task_id: str, responded: bool = True):
        """Mark an issue as processed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO processed_issues 
                (id, source, repo, issue_number, issue_type, task_id, processed_at, responded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                'github',
                repo,
                issue_number,
                issue_type,
                task_id,
                datetime.utcnow().isoformat(),
                responded
            ))
            conn.commit()
    
    def get_priority(self, issue_type: str, title: str, body: str) -> int:
        """Determine task priority based on issue type and content."""
        text = (title + ' ' + (body or '')).lower()
        
        # Base priorities
        priorities = {'bug': 7, 'feature': 5, 'question': 6}
        priority = priorities.get(issue_type, 5)
        
        # Boost for critical bugs
        if issue_type == 'bug':
            if any(kw in text for kw in ['crash', 'security', 'urgent', 'critical', 'production']):
                priority = 9
        
        return priority
    
    def scan_all_repos(self, owner: str = 'cybeleri', auto_reply: bool = True) -> Dict:
        """Scan all repos for new issues."""
        repos = self.list_repos(owner)
        logger.info(f"Found {len(repos)} repos to scan")
        
        stats = {'bugs': 0, 'features': 0, 'questions': 0, 'skipped': 0, 'errors': 0}
        new_issues = []
        
        for repo in repos:
            issues = self.get_issues(repo, owner)
            logger.info(f"Found {len(issues)} open issues in {repo}")
            
            for issue in issues:
                issue_number = issue['number']
                
                # Skip if already processed
                if self.is_processed(repo, issue_number):
                    stats['skipped'] += 1
                    continue
                
                # Classify the issue
                issue_type = self.classify_issue(
                    issue['title'],
                    issue.get('body', ''),
                    issue.get('labels', [])
                )
                
                priority = self.get_priority(issue_type, issue['title'], issue.get('body', ''))
                
                # Generate task ID
                task_id = f"gh-{repo}-{issue_number}"
                
                # Auto-reply if enabled
                responded = False
                if auto_reply:
                    template = REPLY_TEMPLATES.get(issue_type, REPLY_TEMPLATES['question'])
                    if self.post_comment(repo, issue_number, template, owner):
                        responded = True
                        logger.info(f"Posted auto-reply to {repo}#{issue_number}")
                    else:
                        stats['errors'] += 1
                
                # Mark as processed
                self.mark_processed(repo, issue_number, issue_type, task_id, responded)
                
                # Track for reporting
                stats[f'{issue_type}s'] = stats.get(f'{issue_type}s', 0) + 1
                new_issues.append({
                    'repo': repo,
                    'number': issue_number,
                    'title': issue['title'],
                    'type': issue_type,
                    'priority': priority,
                    'url': issue.get('url', f'https://github.com/{owner}/{repo}/issues/{issue_number}'),
                    'task_id': task_id
                })
        
        return {
            'stats': stats,
            'new_issues': new_issues,
            'repos_scanned': len(repos)
        }
    
    def generate_task_commands(self, issues: List[Dict]) -> List[str]:
        """Generate task creation commands for new issues."""
        commands = []
        
        task_mapping = {
            'bug': ('fix_product', 'builder'),
            'feature': ('evaluate_idea', 'critic'),
            'question': ('respond_to_human', 'liaison')
        }
        
        for issue in issues:
            issue_type = issue['type']
            task_type, target_agent = task_mapping.get(issue_type, ('respond_to_human', 'liaison'))
            
            payload = json.dumps({
                'repo': issue['repo'],
                'issue_number': issue['number'],
                'issue_url': issue['url'],
                'title': issue['title'],
                'source': 'github'
            })
            
            cmd = f"claude-tasks create --type {task_type} --to {target_agent} --priority {issue['priority']} --payload '{payload}'"
            commands.append(cmd)
        
        return commands


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Monitor GitHub issues')
    parser.add_argument('--check', action='store_true', help='Check for new issues')
    parser.add_argument('--no-reply', action='store_true', help='Do not auto-reply to issues')
    parser.add_argument('--owner', default='cybeleri', help='GitHub owner/org to monitor')
    parser.add_argument('--db', default='/autonomous-claude/data/orchestrator.db', help='Database path')
    parser.add_argument('--dry-run', action='store_true', help='Print commands but do not execute')
    
    args = parser.parse_args()
    
    monitor = GitHubMonitor(db_path=args.db)
    
    if args.check:
        results = monitor.scan_all_repos(
            owner=args.owner,
            auto_reply=not args.no_reply
        )
        
        print(f"\n=== GitHub Issue Scan Results ===")
        print(f"Repos scanned: {results['repos_scanned']}")
        print(f"Bugs found: {results['stats']['bugs']}")
        print(f"Features found: {results['stats']['features']}")
        print(f"Questions found: {results['stats']['questions']}")
        print(f"Already processed: {results['stats']['skipped']}")
        
        if results['new_issues']:
            print(f"\n=== Task Commands to Run ===")
            commands = monitor.generate_task_commands(results['new_issues'])
            for cmd in commands:
                print(cmd)
                if not args.dry_run:
                    # Execute the command
                    subprocess.run(cmd, shell=True)
        else:
            print("\nNo new issues to process.")


if __name__ == '__main__':
    main()



