"""
PostgreSQL Multi-Tenant Orchestrator for Auto-Dev
==================================================

Extends the base orchestrator with:
- PostgreSQL support (with SQLite fallback)
- Multi-tenant repo_id isolation
- Repository management
- Dev-specific task types
- Enhanced approval workflows

This is the primary orchestrator for auto-dev deployments.
"""

import json
import uuid
import os
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Try to import PostgreSQL driver
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("psycopg2 not installed, PostgreSQL unavailable")

# SQLite fallback
import sqlite3


def parse_json_field(value):
    """Parse JSON field handling both string (SQLite) and dict (PostgreSQL JSONB)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value

# Redis for real-time notifications
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# ==================== Enums ====================

class DevTaskType(Enum):
    """Task types for software development workflow."""
    # Analysis tasks
    ANALYZE_REPO = "analyze_repo"
    SUGGEST_IMPROVEMENT = "suggest_improvement"
    IDENTIFY_TECH_DEBT = "identify_tech_debt"

    # Design tasks
    DESIGN_SOLUTION = "design_solution"
    WRITE_SPEC = "write_spec"
    CREATE_ISSUE = "create_issue"
    CREATE_EPIC = "create_epic"
    EVALUATE_PROPOSAL = "evaluate_proposal"

    # Implementation tasks
    IMPLEMENT_FEATURE = "implement_feature"
    IMPLEMENT_FIX = "implement_fix"
    IMPLEMENT_REFACTOR = "implement_refactor"

    # Review tasks
    REVIEW_MR = "review_mr"
    REVIEW_CODE = "review_code"

    # Testing tasks
    WRITE_TESTS = "write_tests"
    RUN_TESTS = "run_tests"
    VALIDATE_FEATURE = "validate_feature"

    # Security tasks
    SECURITY_SCAN = "security_scan"
    VULNERABILITY_CHECK = "vulnerability_check"
    DEPENDENCY_AUDIT = "dependency_audit"

    # DevOps tasks
    MANAGE_PIPELINE = "manage_pipeline"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"

    # Bug finding tasks
    STATIC_ANALYSIS = "static_analysis"
    BUG_HUNT = "bug_hunt"


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Compatibility aliases for agent_runner.py
class TaskType(Enum):
    """Compatibility alias for TaskType used by agent_runner."""
    SCAN_PLATFORM = "scan_platform"
    BUILD_PRODUCT = "build_product"
    DEPLOY = "deploy"
    WRITE_CONTENT = "write_content"
    MARKET = "market"
    RESEARCH = "research"
    HANDOFF = "handoff"
    PUBLISH = "publish"


class MessageType(Enum):
    """Types of inter-agent messages (compatibility for agent_runner)."""
    HANDOFF = "handoff"
    REQUEST = "request"
    NOTIFY = "notify"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class DevApprovalType(Enum):
    """Types of approvals in dev workflow."""
    ISSUE_CREATION = "issue_creation"
    SPEC_APPROVAL = "spec_approval"
    MERGE_APPROVAL = "merge_approval"
    DEPLOY_APPROVAL = "deploy_approval"


class ApprovalStatus(Enum):
    """Status of approval items."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RepoStatus(Enum):
    """Status of managed repositories."""
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


# ==================== Data Classes ====================

@dataclass
class Repo:
    """A managed repository."""
    id: str
    name: str
    gitlab_url: str
    gitlab_project_id: str
    slug: str  # URL-safe identifier
    provider: str = "gitlab"  # 'gitlab' or 'github'
    default_branch: str = "main"
    autonomy_mode: str = "guided"  # 'guided' or 'full'
    settings: Dict[str, Any] = field(default_factory=dict)
    status: str = RepoStatus.ACTIVE.value
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Repo':
        return cls(**data)


@dataclass
class Task:
    """A task in the queue."""
    id: str
    repo_id: str  # Multi-tenant: which repo this task belongs to
    type: str
    priority: int
    payload: Dict[str, Any]
    status: str = TaskStatus.PENDING.value
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        return cls(**data)


@dataclass
class DevApproval:
    """An approval item in the dev workflow."""
    id: str
    repo_id: str
    approval_type: str  # DevApprovalType value
    title: str
    description: str
    context: Dict[str, Any]  # Type-specific context (issue details, MR details, etc.)
    submitted_by: str
    status: str = ApprovalStatus.PENDING.value
    reviewer_notes: Optional[str] = None
    gitlab_ref: Optional[str] = None  # GitLab issue/MR IID
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    reviewed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DevApproval':
        return cls(**data)


# ==================== Database Abstraction ====================

class DatabaseConnection:
    """
    Database abstraction layer supporting PostgreSQL and SQLite.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize database connection.

        Config should have:
        - type: 'postgresql' or 'sqlite'
        - For PostgreSQL: host, port, name, user, password
        - For SQLite: path
        """
        self.config = config
        self.db_type = config.get('type', 'sqlite')
        self._conn = None

    @contextmanager
    def get_connection(self):
        """Get a database connection."""
        if self.db_type == 'postgresql' and POSTGRES_AVAILABLE:
            conn = psycopg2.connect(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 5432),
                dbname=self.config.get('name', 'autodev'),
                user=self.config.get('user', 'autodev'),
                password=self._get_password(),
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            # SQLite fallback
            path = self.config.get('path', '/auto-dev/data/orchestrator.db')
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _get_password(self) -> str:
        """Get database password from config or environment."""
        if 'password' in self.config:
            return self.config['password']

        password_env = self.config.get('password_env', 'DB_PASSWORD')
        return os.environ.get(password_env, '')

    def execute(self, query: str, params: tuple = None) -> Any:
        """Execute a query and return results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                # Convert %s to ? for SQLite
                if self.db_type == 'sqlite':
                    query = query.replace('%s', '?')
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            try:
                return cursor.fetchall()
            except Exception as e:
                # Query didn't return results (e.g., INSERT/UPDATE)
                logger.debug(f"Query did not return results (expected for INSERT/UPDATE): {e}")
                return None

    def execute_one(self, query: str, params: tuple = None) -> Any:
        """Execute a query and return single result."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                if self.db_type == 'sqlite':
                    query = query.replace('%s', '?')
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchone()

    @property
    def placeholder(self) -> str:
        """Get the parameter placeholder for this DB type."""
        return '%s' if self.db_type == 'postgresql' else '?'


# ==================== Multi-Tenant Orchestrator ====================

class MultiTenantOrchestrator:
    """
    Multi-tenant orchestrator for Auto-Dev.

    Manages multiple repositories with tenant isolation.
    All operations require a repo_id for proper isolation.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the orchestrator.

        Args:
            config: Database and orchestrator configuration
        """
        self.config = config
        self.db = DatabaseConnection(config.get('database', {}))
        self.redis_client = None

        # Try Redis for real-time notifications
        redis_url = config.get('redis_url')
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                logger.info("Connected to Redis")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}")

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder

            # For PostgreSQL, we use CREATE TABLE IF NOT EXISTS for all tables
            # This allows adding new tables without breaking existing installations
            if self.db.db_type == 'postgresql':
                logger.info("Ensuring PostgreSQL schema is up to date...")

                # Migration: Drop FK constraints before converting UUID to TEXT
                # This is necessary because FKs prevent column type changes
                fk_constraints = [
                    ('tasks', 'tasks_repo_id_fkey'),
                    ('dev_approvals', 'dev_approvals_repo_id_fkey'),
                ]
                for table, constraint in fk_constraints:
                    try:
                        cursor.execute(f"SAVEPOINT drop_fk_{table}")
                        cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
                        cursor.execute(f"RELEASE SAVEPOINT drop_fk_{table}")
                    except Exception:
                        cursor.execute(f"ROLLBACK TO SAVEPOINT drop_fk_{table}")

                # Migration: Convert repos.id from UUID to TEXT if needed
                # This is necessary because older schemas used UUID type
                try:
                    cursor.execute("SAVEPOINT repos_migration")
                    cursor.execute("""
                        ALTER TABLE repos
                        ALTER COLUMN id TYPE TEXT USING id::TEXT
                    """)
                    cursor.execute("RELEASE SAVEPOINT repos_migration")
                    logger.info("Migrated repos.id from UUID to TEXT")
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT repos_migration")
                    # Table doesn't exist or already TEXT - continue

            # Repos table - central registry of managed repositories
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repos (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    gitlab_url TEXT NOT NULL,
                    gitlab_project_id TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    default_branch TEXT DEFAULT 'main',
                    autonomy_mode TEXT DEFAULT 'guided',
                    settings TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Migration: Convert tasks columns from UUID to TEXT if needed
            if self.db.db_type == 'postgresql':
                for table, col in [('tasks', 'id'), ('tasks', 'repo_id'),
                                   ('dev_approvals', 'id'), ('dev_approvals', 'repo_id')]:
                    try:
                        cursor.execute(f"SAVEPOINT migrate_{table}_{col}")
                        cursor.execute(f"""
                            ALTER TABLE {table}
                            ALTER COLUMN {col} TYPE TEXT USING {col}::TEXT
                        """)
                        cursor.execute(f"RELEASE SAVEPOINT migrate_{table}_{col}")
                    except Exception:
                        cursor.execute(f"ROLLBACK TO SAVEPOINT migrate_{table}_{col}")

            # Tasks table with repo_id for multi-tenant isolation
            # Note: Using task_type to match PostgreSQL schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    priority INTEGER DEFAULT 5,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    assigned_to TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT,
                    needs_approval INTEGER DEFAULT 0,
                    approval_status TEXT,
                    approval_type TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    rejection_reason TEXT
                )
            """)

            # Add approval columns to existing tasks table (migration)
            # Whitelist of allowed columns to prevent SQL injection
            ALLOWED_MIGRATION_COLUMNS = {
                'needs_approval': ('INTEGER', '0'),
                'approval_status': ('TEXT', None),
                'approval_type': ('TEXT', None),
                'approved_by': ('TEXT', None),
                'approved_at': ('TEXT', None),
                'rejection_reason': ('TEXT', None),
            }
            for col, (col_type, default) in ALLOWED_MIGRATION_COLUMNS.items():
                # Validate column name is alphanumeric with underscores only
                if not col.replace('_', '').isalnum():
                    logger.warning(f"Skipping invalid column name: {col}")
                    continue
                try:
                    # Use savepoint for PostgreSQL to avoid transaction abort on error
                    if self.db.db_type == 'postgresql':
                        cursor.execute(f"SAVEPOINT migration_{col}")
                    if default is not None:
                        cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {col_type} DEFAULT {default}")
                    else:
                        cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {col_type}")
                    if self.db.db_type == 'postgresql':
                        cursor.execute(f"RELEASE SAVEPOINT migration_{col}")
                except Exception as e:
                    # Column already exists - expected on subsequent runs
                    # Rollback to savepoint to restore transaction state in PostgreSQL
                    if self.db.db_type == 'postgresql':
                        cursor.execute(f"ROLLBACK TO SAVEPOINT migration_{col}")
                    logger.debug(f"Migration column {col} already exists or failed: {e}")

            # Dev approvals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dev_approvals (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    approval_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    context TEXT DEFAULT '{}',
                    submitted_by TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    reviewer_notes TEXT,
                    gitlab_ref TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
            """)

            # Agent status with repo context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_status (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    repo_id TEXT,
                    status TEXT NOT NULL,
                    current_task_id TEXT,
                    last_heartbeat TEXT NOT NULL,
                    tasks_completed INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    UNIQUE(agent_id, repo_id)
                )
            """)

            # Agent messages with repo context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_mail (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    read INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # Discussions with repo context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discussions (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT,
                    author TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    in_reply_to TEXT,
                    votes_up INTEGER DEFAULT 0,
                    votes_down INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # Token usage tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT,
                    agent_id TEXT NOT NULL,
                    session_id TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    recorded_at TEXT NOT NULL
                )
            """)

            # Task outcomes - tracks success/failure for learning system
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_outcomes (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_seconds INTEGER,
                    error_summary TEXT,
                    context_summary TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Processed issues - deduplication for webhook events
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_issues (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    UNIQUE(issue_id, repo_id, action)
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_repo ON tasks(repo_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_approvals_repo ON dev_approvals(repo_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON dev_approvals(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_status_repo ON agent_status(repo_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_agent ON task_outcomes(agent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_repo ON task_outcomes(repo_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_type ON task_outcomes(task_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_created ON task_outcomes(created_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_issues_repo ON processed_issues(repo_id)")

            conn.commit()

    # ==================== Repository Management ====================

    def create_repo(
        self,
        name: str,
        gitlab_url: str,
        gitlab_project_id: str,
        default_branch: str = "main",
        autonomy_mode: str = "guided",
        settings: Dict[str, Any] = None,
        repo_id: str = None,
        provider: str = "gitlab"
    ) -> Repo:
        """Create a new managed repository."""
        # Generate slug from name
        slug = name.lower().replace(' ', '-').replace('/', '-')

        repo = Repo(
            id=repo_id or str(uuid.uuid4()),
            name=name,
            gitlab_url=gitlab_url,
            gitlab_project_id=gitlab_project_id,
            slug=slug,
            provider=provider,
            default_branch=default_branch,
            autonomy_mode=autonomy_mode,
            settings=settings or {}
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                INSERT INTO repos
                (id, name, gitlab_url, gitlab_project_id, slug, provider, default_branch,
                 autonomy_mode, settings, status, created_at, updated_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                repo.id, repo.name, repo.gitlab_url, repo.gitlab_project_id,
                repo.slug, repo.provider, repo.default_branch, repo.autonomy_mode,
                json.dumps(repo.settings), repo.status, repo.created_at, repo.updated_at
            ))
            conn.commit()

        logger.info(f"Created repo: {repo.name} ({repo.id}) [provider: {provider}]")
        return repo

    def get_repo(self, repo_id: str) -> Optional[Repo]:
        """Get a repository by ID."""
        row = self.db.execute_one(
            f"SELECT * FROM repos WHERE id = {self.db.placeholder}",
            (repo_id,)
        )
        if not row:
            return None
        return self._row_to_repo(row)

    def get_repo_by_slug(self, slug: str) -> Optional[Repo]:
        """Get a repository by slug."""
        row = self.db.execute_one(
            f"SELECT * FROM repos WHERE slug = {self.db.placeholder}",
            (slug,)
        )
        if not row:
            return None
        return self._row_to_repo(row)

    def list_repos(self, status: str = None, active_only: bool = False) -> List[Repo]:
        """List all repositories."""
        if status:
            # For PostgreSQL with 'active' boolean column
            if status == 'active':
                rows = self.db.execute("SELECT * FROM repos WHERE active = true ORDER BY name")
            else:
                rows = self.db.execute("SELECT * FROM repos WHERE active = false ORDER BY name")
        elif active_only:
            rows = self.db.execute("SELECT * FROM repos WHERE active = true ORDER BY name")
        else:
            rows = self.db.execute("SELECT * FROM repos ORDER BY name")
        return [self._row_to_repo(row) for row in rows]

    def delete_repo(self, repo_id: str) -> bool:
        """Delete a repository."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM repos WHERE id = {self.db.placeholder}",
                (repo_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_repo(self, repo_id: str, **updates) -> bool:
        """Update repository settings."""
        updates['updated_at'] = datetime.utcnow().isoformat()

        # Handle settings separately (needs JSON serialization)
        if 'settings' in updates:
            updates['settings'] = json.dumps(updates['settings'])

        set_clause = ', '.join(f"{k} = {self.db.placeholder}" for k in updates.keys())

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE repos SET {set_clause} WHERE id = {self.db.placeholder}",
                (*updates.values(), repo_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_repo(self, row) -> Repo:
        """Convert database row to Repo object."""
        if hasattr(row, 'keys'):
            # Dict-like row (PostgreSQL RealDictRow or SQLite Row)
            # Handle settings - might be dict (jsonb) or string (json text)
            settings = row.get('settings', {})
            if isinstance(settings, str):
                settings = parse_json_field(settings) or {}

            # Handle status vs active column
            if 'status' in row.keys():
                status = row['status']
            else:
                status = 'active' if row.get('active') else 'inactive'

            # Handle timestamps - might be datetime or string
            created_at = row.get('created_at', '')
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            updated_at = row.get('updated_at', '')
            if hasattr(updated_at, 'isoformat'):
                updated_at = updated_at.isoformat()

            return Repo(
                id=str(row['id']),  # Convert UUID to string if needed
                name=row['name'],
                gitlab_url=row['gitlab_url'],
                gitlab_project_id=str(row['gitlab_project_id']),
                slug=row['slug'],
                provider=row.get('provider', 'gitlab'),
                default_branch=row.get('default_branch', 'main'),
                autonomy_mode=row.get('autonomy_mode', 'guided'),
                settings=settings,
                status=status,
                created_at=str(created_at),
                updated_at=str(updated_at)
            )
        else:
            # Tuple row - use positional access (SQLite fallback)
            return Repo(
                id=str(row[0]),
                name=row[1],
                gitlab_url=row[2],
                gitlab_project_id=str(row[3]),
                slug=row[4],
                default_branch=row[5] if len(row) > 5 else 'main',
                autonomy_mode=row[6] if len(row) > 6 else 'guided',
                settings=parse_json_field(row[7]) if len(row) > 7 else {},
                status=row[8] if len(row) > 8 else 'active',
                created_at=str(row[9]) if len(row) > 9 else '',
                updated_at=str(row[10]) if len(row) > 10 else ''
            )

    # ==================== Task Queue ====================

    def create_task(
        self,
        repo_id: str,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 5,
        created_by: Optional[str] = None,
        assigned_to: Optional[str] = None
    ) -> Task:
        """Create a new task for a repository."""
        task = Task(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            type=task_type,
            priority=min(10, max(1, priority)),
            payload=payload,
            created_by=created_by,
            assigned_to=assigned_to
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                INSERT INTO tasks
                (id, repo_id, task_type, priority, payload, status, assigned_to, created_by, created_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                task.id, task.repo_id, task.type, task.priority,
                json.dumps(task.payload), task.status, task.assigned_to,
                task.created_by, task.created_at
            ))
            conn.commit()

        # Notify via Redis
        if self.redis_client:
            self.redis_client.publish(f"repo:{repo_id}:tasks", json.dumps({
                'event': 'task_created',
                'task_id': task.id,
                'type': task.type
            }))

        logger.info(f"Created task {task.id} ({task.type}) for repo {repo_id}")
        return task

    def claim_task(
        self,
        agent_id: str,
        repo_id: Optional[str] = None,
        task_types: Optional[List[str]] = None
    ) -> Optional[Task]:
        """
        Claim the highest priority available task atomically.

        Uses FOR UPDATE SKIP LOCKED on PostgreSQL to prevent race conditions
        where multiple agents try to claim the same task.

        Args:
            agent_id: ID of the claiming agent
            repo_id: Optional repo filter (if None, claims from any repo)
            task_types: Optional list of task types this agent handles
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            now = datetime.utcnow().isoformat()

            # Build WHERE conditions
            # Key logic: Tasks directly assigned to this agent can be claimed regardless of task_type.
            # Task type filtering only applies to unassigned tasks to prevent agents from claiming
            # tasks they shouldn't handle. This allows human directives to reach specific agents.
            conditions = ["status = 'pending'"]
            params = []

            if repo_id:
                conditions.append(f"repo_id = {p}")
                params.append(repo_id)

            # Build the assignment/task_type condition:
            # Either: task is assigned directly to this agent (claim regardless of type)
            # Or: task is unassigned AND matches agent's task types
            if task_types:
                placeholders = ', '.join([p] * len(task_types))
                # Tasks assigned to this agent OR unassigned tasks matching agent's task types
                assignment_condition = f"(assigned_to = {p} OR (assigned_to IS NULL AND task_type IN ({placeholders})))"
                conditions.append(assignment_condition)
                params.append(agent_id)
                params.extend(task_types)
            else:
                # No task_type filter - can claim any task assigned to this agent or unassigned
                conditions.append(f"(assigned_to IS NULL OR assigned_to = {p})")
                params.append(agent_id)

            where_clause = ' AND '.join(conditions)

            if self.db.db_type == 'postgresql':
                # PostgreSQL: Use atomic UPDATE...FROM...RETURNING with FOR UPDATE SKIP LOCKED
                # This prevents race conditions by locking the selected row
                cursor.execute(f"""
                    UPDATE tasks
                    SET status = 'claimed', assigned_to = {p}, claimed_at = {p}
                    WHERE id = (
                        SELECT id FROM tasks
                        WHERE {where_clause}
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                """, [agent_id, now] + params)
                row = cursor.fetchone()
            else:
                # SQLite: Use two-step approach with immediate transaction
                # SQLite's locking is database-level, so less prone to races
                cursor.execute(f"""
                    SELECT id FROM tasks
                    WHERE {where_clause}
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """, params)
                id_row = cursor.fetchone()
                if not id_row:
                    return None

                task_id = id_row[0] if isinstance(id_row, tuple) else id_row['id']
                cursor.execute(f"""
                    UPDATE tasks
                    SET status = 'claimed', assigned_to = {p}, claimed_at = {p}
                    WHERE id = {p} AND status = 'pending'
                """, (agent_id, now, task_id))

                # Check if update succeeded (another agent may have claimed it)
                if cursor.rowcount == 0:
                    return None

                cursor.execute(f"SELECT * FROM tasks WHERE id = {p}", (task_id,))
                row = cursor.fetchone()

            conn.commit()

            if not row:
                return None

            task = self._row_to_task(row)
            logger.info(f"Agent {agent_id} claimed task {task.id}")
            return task

    def complete_task(
        self,
        task_id: str,
        agent_id: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """Mark a task as completed or failed."""
        status = TaskStatus.FAILED.value if error else TaskStatus.COMPLETED.value
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                UPDATE tasks
                SET status = {p}, completed_at = {p}, result = {p}, error = {p}
                WHERE id = {p} AND assigned_to = {p}
            """, (
                status, now,
                json.dumps(result) if result else None,
                error, task_id, agent_id
            ))
            conn.commit()
            success = cursor.rowcount > 0

        if success:
            logger.info(f"Task {task_id} completed with status {status}")
        return success

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        row = self.db.execute_one(
            f"SELECT * FROM tasks WHERE id = {self.db.placeholder}",
            (task_id,)
        )
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(
        self,
        repo_id: Optional[str] = None,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Task]:
        """List tasks with optional filters."""
        conditions = []
        params = []
        p = self.db.placeholder

        if repo_id:
            conditions.append(f"repo_id = {p}")
            params.append(repo_id)
        if status:
            conditions.append(f"status = {p}")
            params.append(status)
        if task_type:
            conditions.append(f"task_type = {p}")
            params.append(task_type)

        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        params.append(limit)

        rows = self.db.execute(f"""
            SELECT * FROM tasks
            WHERE {where_clause}
            ORDER BY priority DESC, created_at DESC
            LIMIT {p}
        """, tuple(params))

        return [self._row_to_task(row) for row in rows]

    def _row_to_task(self, row) -> Task:
        """Convert database row to Task object."""
        if hasattr(row, 'keys'):
            return Task(
                id=row['id'],
                repo_id=row['repo_id'],
                type=row['task_type'],
                priority=row['priority'],
                payload=parse_json_field(row['payload']) or {},
                status=row['status'],
                assigned_to=row['assigned_to'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                claimed_at=row['claimed_at'],
                completed_at=row['completed_at'],
                result=parse_json_field(row['result']),
                error=row['error']
            )
        else:
            return Task(
                id=row[0],
                repo_id=row[1],
                type=row[2],
                priority=row[3],
                payload=parse_json_field(row[4]) or {},
                status=row[5],
                assigned_to=row[6],
                created_by=row[7],
                created_at=row[8],
                claimed_at=row[9],
                completed_at=row[10],
                result=parse_json_field(row[11]),
                error=row[12]
            )

    # ==================== Dev Approvals ====================

    def create_approval(
        self,
        repo_id: str,
        approval_type: str,
        title: str,
        description: str,
        submitted_by: str,
        context: Dict[str, Any] = None,
        gitlab_ref: Optional[str] = None
    ) -> DevApproval:
        """Create a new approval request."""
        approval = DevApproval(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            approval_type=approval_type,
            title=title,
            description=description,
            context=context or {},
            submitted_by=submitted_by,
            gitlab_ref=gitlab_ref
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                INSERT INTO dev_approvals
                (id, repo_id, approval_type, title, description, context,
                 submitted_by, status, gitlab_ref, created_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                approval.id, approval.repo_id, approval.approval_type,
                approval.title, approval.description, json.dumps(approval.context),
                approval.submitted_by, approval.status, approval.gitlab_ref,
                approval.created_at
            ))
            conn.commit()

        logger.info(f"Created approval {approval.id} ({approval_type}) for repo {repo_id}")
        return approval

    def approve(
        self,
        approval_id: str,
        reviewer_notes: str = ""
    ) -> bool:
        """Approve an approval request."""
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                UPDATE dev_approvals
                SET status = 'approved', reviewer_notes = {p}, reviewed_at = {p}
                WHERE id = {p} AND status = 'pending'
            """, (reviewer_notes, now, approval_id))
            conn.commit()

            if cursor.rowcount > 0:
                # Get the approval to create follow-up task
                cursor.execute(f"SELECT * FROM dev_approvals WHERE id = {p}", (approval_id,))
                row = cursor.fetchone()
                if row:
                    approval = self._row_to_approval(row)
                    self._handle_approval(approval)
                return True
        return False

    def reject(
        self,
        approval_id: str,
        reviewer_notes: str = ""
    ) -> bool:
        """Reject an approval request."""
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                UPDATE dev_approvals
                SET status = 'rejected', reviewer_notes = {p}, reviewed_at = {p}
                WHERE id = {p} AND status = 'pending'
            """, (reviewer_notes, now, approval_id))
            conn.commit()
            return cursor.rowcount > 0

    def _handle_approval(self, approval: DevApproval) -> None:
        """Handle post-approval actions (create follow-up tasks)."""
        if approval.approval_type == DevApprovalType.SPEC_APPROVAL.value:
            # Create implementation task
            self.create_task(
                repo_id=approval.repo_id,
                task_type=DevTaskType.IMPLEMENT_FEATURE.value,
                payload={
                    'approval_id': approval.id,
                    'title': approval.title,
                    'spec': approval.context.get('spec'),
                    'issue_iid': approval.gitlab_ref
                },
                priority=8,
                created_by='approval_system'
            )

        elif approval.approval_type == DevApprovalType.MERGE_APPROVAL.value:
            # MR can now be merged - notify via Redis
            if self.redis_client:
                self.redis_client.publish(f"repo:{approval.repo_id}:approvals", json.dumps({
                    'event': 'merge_approved',
                    'approval_id': approval.id,
                    'mr_iid': approval.gitlab_ref
                }))

    def list_approvals(
        self,
        repo_id: Optional[str] = None,
        status: str = "pending",
        approval_type: Optional[str] = None,
        limit: int = 50
    ) -> List[DevApproval]:
        """List approval requests."""
        conditions = [f"status = {self.db.placeholder}"]
        params = [status]

        if repo_id:
            conditions.append(f"repo_id = {self.db.placeholder}")
            params.append(repo_id)
        if approval_type:
            conditions.append(f"approval_type = {self.db.placeholder}")
            params.append(approval_type)

        where_clause = ' AND '.join(conditions)
        params.append(limit)

        rows = self.db.execute(f"""
            SELECT * FROM dev_approvals
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT {self.db.placeholder}
        """, tuple(params))

        return [self._row_to_approval(row) for row in rows]

    def _row_to_approval(self, row) -> DevApproval:
        """Convert database row to DevApproval object."""
        if hasattr(row, 'keys'):
            return DevApproval(
                id=row['id'],
                repo_id=row['repo_id'],
                approval_type=row['approval_type'],
                title=row['title'],
                description=row['description'],
                context=parse_json_field(row['context']) or {},
                submitted_by=row['submitted_by'],
                status=row['status'],
                reviewer_notes=row['reviewer_notes'],
                gitlab_ref=row['gitlab_ref'],
                created_at=row['created_at'],
                reviewed_at=row['reviewed_at']
            )
        else:
            return DevApproval(
                id=row[0],
                repo_id=row[1],
                approval_type=row[2],
                title=row[3],
                description=row[4],
                context=parse_json_field(row[5]) or {},
                submitted_by=row[6],
                status=row[7],
                reviewer_notes=row[8],
                gitlab_ref=row[9],
                created_at=row[10],
                reviewed_at=row[11]
            )

    # ==================== Agent Status ====================

    def update_agent_status(
        self,
        agent_id: str,
        status: str,
        repo_id: Optional[str] = None,
        current_task_id: Optional[str] = None
    ) -> None:
        """Update agent status."""
        now = datetime.utcnow()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder

            if self.db.db_type == 'postgresql':
                # Map status values to PostgreSQL allowed values
                # PostgreSQL constraint: idle, running, error, stopped
                status_map = {
                    'online': 'running',
                    'offline': 'stopped',
                    'idle': 'idle',
                    'rate_limited': 'idle',
                    'budget_exceeded': 'stopped',
                    'waiting': 'idle',
                    'disabled': 'stopped',
                    'in_progress': 'running',
                    'error': 'error'
                }
                status = status_map.get(status, 'idle')

                # Check if record exists first (match repo_id when provided)
                if repo_id is None:
                    cursor.execute(f"""
                        SELECT id FROM agent_status WHERE agent_id = {p} AND repo_id IS NULL
                    """, (agent_id,))
                else:
                    cursor.execute(f"""
                        SELECT id FROM agent_status WHERE agent_id = {p} AND repo_id = {p}
                    """, (agent_id, repo_id))
                existing = cursor.fetchone()

                if existing:
                    if repo_id is None:
                        cursor.execute(f"""
                            UPDATE agent_status
                            SET status = {p}, current_task_id = {p}, last_heartbeat = {p}
                            WHERE agent_id = {p} AND repo_id IS NULL
                        """, (status, current_task_id, now, agent_id))
                    else:
                        cursor.execute(f"""
                            UPDATE agent_status
                            SET status = {p}, current_task_id = {p}, last_heartbeat = {p}
                            WHERE agent_id = {p} AND repo_id = {p}
                        """, (status, current_task_id, now, agent_id, repo_id))
                else:
                    cursor.execute(f"""
                        INSERT INTO agent_status (id, agent_id, repo_id, status, current_task_id, last_heartbeat)
                        VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                    """, (str(uuid.uuid4()), agent_id, repo_id, status, current_task_id, now))
            else:
                # SQLite schema
                cursor.execute(f"""
                    INSERT OR REPLACE INTO agent_status
                    (agent_id, status, current_task_id, last_heartbeat, tasks_completed, tokens_used)
                    VALUES ({p}, {p}, {p}, {p},
                        COALESCE((SELECT tasks_completed FROM agent_status WHERE agent_id = {p}), 0),
                        COALESCE((SELECT tokens_used FROM agent_status WHERE agent_id = {p}), 0))
                """, (agent_id, status, current_task_id, now.isoformat(), agent_id, agent_id))
            conn.commit()

    def get_agent_status(self, agent_id: str, repo_id: Optional[str] = None) -> Optional[Dict]:
        """Get agent status."""
        # Schema uses agent_id for both SQLite and PostgreSQL
        col = 'agent_id'

        if repo_id:
            row = self.db.execute_one(f"""
                SELECT * FROM agent_status
                WHERE {col} = {self.db.placeholder} AND repo_id = {self.db.placeholder}
            """, (agent_id, repo_id))
        else:
            row = self.db.execute_one(f"""
                SELECT * FROM agent_status
                WHERE {col} = {self.db.placeholder}
                ORDER BY last_heartbeat DESC
                LIMIT 1
            """, (agent_id,))

        if not row:
            return None

        if hasattr(row, 'keys'):
            return dict(row)
        return {
            'id': row[0],
            'agent_id': row[1],
            'repo_id': row[2],
            'status': row[3],
            'current_task_id': row[4],
            'last_heartbeat': row[5],
            'tasks_completed': row[6],
            'tokens_used': row[7]
        }

    def increment_completed(self, agent_id: str, repo_id: Optional[str] = None) -> None:
        """Increment tasks completed counter for an agent."""
        # PostgreSQL schema doesn't have tasks_completed column
        if self.db.db_type == 'postgresql':
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            if repo_id:
                cursor.execute(f"""
                    UPDATE agent_status
                    SET tasks_completed = tasks_completed + 1
                    WHERE agent_id = {p} AND repo_id = {p}
                """, (agent_id, repo_id))
            else:
                cursor.execute(f"""
                    UPDATE agent_status
                    SET tasks_completed = tasks_completed + 1
                    WHERE agent_id = {p}
                """, (agent_id,))
            conn.commit()

    # ==================== Utility Methods ====================

    def get_queue_stats(self, repo_id: Optional[str] = None) -> Dict[str, int]:
        """Get task queue statistics."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder

            if repo_id:
                cursor.execute(f"""
                    SELECT status, COUNT(*) as count
                    FROM tasks WHERE repo_id = {p}
                    GROUP BY status
                """, (repo_id,))
            else:
                cursor.execute("""
                    SELECT status, COUNT(*) as count
                    FROM tasks
                    GROUP BY status
                """)

            stats = {'total': 0}
            for row in cursor.fetchall():
                status = row[0] if isinstance(row, tuple) else row['status']
                count = row[1] if isinstance(row, tuple) else row['count']
                stats[status] = count
                stats['total'] += count

            return stats

    def should_auto_approve(
        self,
        repo_id: str,
        approval_type: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if an approval should be auto-approved based on repo settings.

        Only applies in 'full' autonomy mode.
        """
        repo = self.get_repo(repo_id)
        if not repo or repo.autonomy_mode != 'full':
            return False

        thresholds = repo.settings.get('auto_approve_thresholds', {})

        if approval_type == DevApprovalType.SPEC_APPROVAL.value:
            required = thresholds.get('architect_confidence', 8)
            actual = context.get('confidence', 0)
            return actual >= required

        elif approval_type == DevApprovalType.MERGE_APPROVAL.value:
            required_score = thresholds.get('reviewer_score', 9)
            required_coverage = thresholds.get('test_coverage', 80)
            actual_score = context.get('reviewer_score', 0)
            actual_coverage = context.get('test_coverage', 0)
            return actual_score >= required_score and actual_coverage >= required_coverage

        return False


    # ==================== Compatibility Methods for agent_runner ====================

    def get_messages(self, agent_id: str, unread_only: bool = True) -> List[Any]:
        """Get messages for an agent (stub for compatibility)."""
        # Inter-agent messaging not implemented in PostgreSQL orchestrator
        return []

    def mark_read(self, message_id: str, agent_id: str) -> None:
        """Mark a message as read (stub for compatibility)."""
        # Inter-agent messaging not implemented in PostgreSQL orchestrator
        pass

    def record_token_usage(
        self,
        agent_id: str,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_usd: float = 0.0
    ) -> None:
        """Record token usage for an agent session."""
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder

            if self.db.db_type == 'postgresql':
                # Insert into token_usage table for PostgreSQL
                cursor.execute(f"""
                    INSERT INTO token_usage
                    (id, agent_id, session_id, input_tokens, output_tokens, total_tokens, recorded_at)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                """, (str(uuid.uuid4()), agent_id, session_id, input_tokens, output_tokens, total_tokens, now))
            else:
                # Update tokens_used in agent_status for SQLite
                cursor.execute(f"""
                    UPDATE agent_status
                    SET tokens_used = tokens_used + {p}
                    WHERE agent_id = {p}
                """, (total_tokens, agent_id))
            conn.commit()

    # ==================== Task Outcomes (Learning System) ====================

    def record_outcome(
        self,
        task_id: str,
        repo_id: str,
        agent_id: str,
        task_type: str,
        outcome: str,
        duration_seconds: Optional[int] = None,
        error_summary: Optional[str] = None,
        context_summary: Optional[str] = None
    ) -> str:
        """
        Record the outcome of a completed task for learning purposes.

        Args:
            task_id: ID of the completed task
            repo_id: Repository the task belongs to
            agent_id: Agent that executed the task
            task_type: Type of task (implement_fix, review_mr, etc.)
            outcome: 'success', 'failure', or 'partial'
            duration_seconds: How long the task took
            error_summary: Brief description of error if failed
            context_summary: Brief description of what the task involved

        Returns:
            ID of the created outcome record
        """
        outcome_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            p = self.db.placeholder
            cursor.execute(f"""
                INSERT INTO task_outcomes
                (id, task_id, repo_id, agent_id, task_type, outcome,
                 duration_seconds, error_summary, context_summary, created_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                outcome_id, task_id, repo_id, agent_id, task_type, outcome,
                duration_seconds, error_summary, context_summary, now
            ))
            conn.commit()

        logger.info(f"Recorded outcome for task {task_id}: {outcome}")
        return outcome_id

    def get_recent_outcomes(
        self,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
        repo_id: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get recent task outcomes with optional filters.

        Args:
            agent_id: Filter by specific agent
            task_type: Filter by task type
            repo_id: Filter by repository
            outcome: Filter by outcome ('success', 'failure', 'partial')
            limit: Maximum results to return

        Returns:
            List of outcome records as dictionaries
        """
        conditions = []
        params = []
        p = self.db.placeholder

        if agent_id:
            conditions.append(f"agent_id = {p}")
            params.append(agent_id)
        if task_type:
            conditions.append(f"task_type = {p}")
            params.append(task_type)
        if repo_id:
            conditions.append(f"repo_id = {p}")
            params.append(repo_id)
        if outcome:
            conditions.append(f"outcome = {p}")
            params.append(outcome)

        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        params.append(limit)

        rows = self.db.execute_many(f"""
            SELECT * FROM task_outcomes
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT {p}
        """, params)

        return [dict(row) for row in rows]

    def get_outcome_stats(
        self,
        repo_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get aggregated outcome statistics.

        Args:
            repo_id: Optional repository filter
            days: Number of days to include

        Returns:
            Dictionary with stats by agent and task type
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        p = self.db.placeholder

        conditions = [f"created_at >= {p}"]
        params = [cutoff]

        if repo_id:
            conditions.append(f"repo_id = {p}")
            params.append(repo_id)

        where_clause = ' AND '.join(conditions)

        # Stats by agent
        agent_rows = self.db.execute_many(f"""
            SELECT
                agent_id,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failure,
                SUM(CASE WHEN outcome = 'partial' THEN 1 ELSE 0 END) as partial,
                AVG(duration_seconds) as avg_duration
            FROM task_outcomes
            WHERE {where_clause}
            GROUP BY agent_id
            ORDER BY total DESC
        """, params)

        # Stats by task type
        type_rows = self.db.execute_many(f"""
            SELECT
                task_type,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failure
            FROM task_outcomes
            WHERE {where_clause}
            GROUP BY task_type
            ORDER BY total DESC
        """, params)

        # Recent failures
        failure_rows = self.db.execute_many(f"""
            SELECT agent_id, task_type, error_summary, created_at
            FROM task_outcomes
            WHERE {where_clause} AND outcome = 'failure' AND error_summary IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 10
        """, params)

        return {
            'by_agent': [dict(row) for row in agent_rows],
            'by_task_type': [dict(row) for row in type_rows],
            'recent_failures': [dict(row) for row in failure_rows],
            'period_days': days
        }


# ==================== Singleton Access ====================

_orchestrator_instance: Optional[MultiTenantOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_orchestrator(config: Dict[str, Any] = None, db_path: str = None, redis_url: str = None) -> MultiTenantOrchestrator:
    """Get or create the orchestrator singleton (thread-safe)."""
    global _orchestrator_instance

    # Double-checked locking pattern for thread safety
    if _orchestrator_instance is None:
        with _orchestrator_lock:
            # Check again inside the lock
            if _orchestrator_instance is None:
                if config is None:
                    # Auto-detect database from environment
                    db_host = os.environ.get('DB_HOST')
                    if db_host:
                        # PostgreSQL from environment
                        config = {
                            'database': {
                                'type': 'postgresql',
                                'host': db_host,
                                'name': os.environ.get('DB_NAME', 'autodev'),
                                'user': os.environ.get('DB_USER', 'autodev'),
                                'password': os.environ.get('DB_PASSWORD', '')
                            },
                            'redis_url': redis_url or os.environ.get('REDIS_URL')
                        }
                    else:
                        # Fallback to SQLite
                        config = {
                            'database': {
                                'type': 'sqlite',
                                'path': db_path or '/auto-dev/data/orchestrator.db'
                            },
                            'redis_url': redis_url or os.environ.get('REDIS_URL')
                        }
                _orchestrator_instance = MultiTenantOrchestrator(config)

    return _orchestrator_instance


# Compatibility alias for agent_runner imports
Orchestrator = MultiTenantOrchestrator
