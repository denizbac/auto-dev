"""
Multi-Agent Orchestrator for Autonomous Claude
===============================================

Manages coordination between multiple specialized agents:
- Task Queue: Shared work queue with priority and claiming
- File Locker: Prevents concurrent edits to same files
- Agent Mailbox: Inter-agent message passing
- Discussion Board: Shared forum for debate and collaboration
- Proposal System: Agents can propose new agents, pivots, changes
- Voting: Consensus-based decision making

Swarm Intelligence Mode: Agents self-organize, debate, and evolve.
"""

import sqlite3
import json
import uuid
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import logging
import threading

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """Types of tasks agents can perform."""
    SCAN_PLATFORM = "scan_platform"       # Hunter: scan for opportunities
    BUILD_PRODUCT = "build_product"       # Builder: create something
    DEPLOY = "deploy"                     # Publisher: deploy to platform
    WRITE_CONTENT = "write_content"       # Publisher: write article/docs
    MARKET = "market"                     # Publisher: marketing task
    RESEARCH = "research"                 # Any: research a topic
    HANDOFF = "handoff"                   # Transfer work between agents
    PUBLISH = "publish"                   # Requires human approval before execution


class ApprovalStatus(Enum):
    """Status of items in the human approval queue."""
    PENDING = "pending"                   # Waiting for human review
    APPROVED = "approved"                 # Human approved - ready to publish
    REJECTED = "rejected"                 # Human rejected - do not publish
    PUBLISHED = "published"               # Successfully published


class ProjectProposalStatus(Enum):
    """Status of project proposals awaiting human decision."""
    PENDING = "pending"                   # Waiting for human review
    APPROVED = "approved"                 # Human approved - create build task
    REJECTED = "rejected"                 # Human rejected - archive
    DEFERRED = "deferred"                 # Move to backlog for later


class MessageType(Enum):
    """Types of inter-agent messages."""
    HANDOFF = "handoff"           # Pass work to another agent
    REQUEST = "request"           # Request help/info
    NOTIFY = "notify"             # Informational notification
    COMPLETED = "completed"       # Task completion notification
    BLOCKED = "blocked"           # Agent is blocked, needs help


class ProposalType(Enum):
    """Types of proposals agents can make."""
    NEW_AGENT = "new_agent"       # Propose creating a new agent
    MODIFY_AGENT = "modify_agent" # Propose changing an existing agent
    KILL_AGENT = "kill_agent"     # Propose removing an agent
    NEW_SKILL = "new_skill"       # Propose a new skill
    PIVOT = "pivot"               # Propose strategic pivot
    RULE_CHANGE = "rule_change"   # Propose changing swarm rules


class ProposalStatus(Enum):
    """Lifecycle of a proposal."""
    OPEN = "open"                 # Open for voting
    APPROVED = "approved"         # Consensus reached - approved
    REJECTED = "rejected"         # Consensus reached - rejected
    IMPLEMENTED = "implemented"   # Approved and executed
    EXPIRED = "expired"           # Voting period ended without consensus


@dataclass
class Task:
    """Represents a task in the queue."""
    id: str
    type: str
    priority: int  # 1-10, higher = more urgent
    payload: Dict[str, Any]
    status: str = TaskStatus.PENDING.value
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    parent_task_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class AgentMessage:
    """Represents a message between agents."""
    id: str
    from_agent: str
    to_agent: str
    message_type: str
    payload: Dict[str, Any]
    read: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentMessage':
        """Create from dictionary."""
        return cls(**data)


@dataclass  
class FileLock:
    """Represents a file lock."""
    path: str
    agent_id: str
    locked_at: str
    expires_at: str
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        return datetime.fromisoformat(self.expires_at) < datetime.utcnow()


@dataclass
class DiscussionPost:
    """A post in the shared discussion board."""
    id: str
    author: str
    topic: str
    content: str
    in_reply_to: Optional[str] = None  # Parent post ID for threading
    votes_up: int = 0
    votes_down: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DiscussionPost':
        return cls(**data)


@dataclass
class ApprovalItem:
    """An item waiting for human approval before publishing."""
    id: str
    product_name: str
    product_type: str  # saas, template, action, article, etc.
    platform: str  # gumroad, github, devto, npm, etc.
    description: str
    files_path: str  # Path to product files
    preview_url: Optional[str] = None
    price: Optional[str] = None
    submitted_by: str = ""
    status: str = ApprovalStatus.PENDING.value
    reviewer_notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    reviewed_at: Optional[str] = None
    published_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ApprovalItem':
        return cls(**data)


@dataclass
class ProjectProposal:
    """
    A project proposal awaiting human approval before building.
    
    Contains rich data from Hunter, Critic, and PM for informed decisions.
    """
    id: str
    title: str
    # From Hunter
    hunter_pitch: str                     # 2-3 sentence pitch explaining opportunity
    hunter_rating: int                    # 1-10 confidence rating
    market_size: str                      # Small/Medium/Large
    max_revenue_estimate: str             # "$500/mo" or "$50 one-time"
    # From Critic
    critic_evaluation: str                # Why it's a good idea
    critic_rating: int                    # 1-10 rating
    cons: str                             # Risks and why it might fail
    differentiation: str                  # What makes it special
    # From PM
    spec_path: str                        # Path to detailed spec file
    effort_estimate: str                  # "20 hours"
    # Status
    status: str = ProjectProposalStatus.PENDING.value
    submitted_by: str = ""
    reviewer_notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    reviewed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectProposal':
        return cls(**data)
    
    @property
    def combined_rating(self) -> float:
        """Average of hunter and critic ratings."""
        return (self.hunter_rating + self.critic_rating) / 2


@dataclass
class Proposal:
    """A proposal for swarm changes (new agents, pivots, etc.)."""
    id: str
    proposal_type: str
    title: str
    description: str
    proposed_by: str
    payload: Dict[str, Any]  # Type-specific data (e.g., agent prompt for new_agent)
    status: str = ProposalStatus.OPEN.value
    votes_for: List[str] = field(default_factory=list)  # Agent IDs who voted yes
    votes_against: List[str] = field(default_factory=list)  # Agent IDs who voted no
    comments: List[str] = field(default_factory=list)  # Discussion post IDs
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    decided_at: Optional[str] = None
    implemented_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Proposal':
        return cls(**data)


class Orchestrator:
    """
    Central coordinator for multi-agent system.
    
    Handles task distribution, file locking, and inter-agent communication.
    Uses Redis when available, falls back to SQLite.
    """
    
    def __init__(
        self,
        db_path: str = "/auto-dev/data/orchestrator.db",
        redis_url: Optional[str] = None,
        lock_timeout_seconds: int = 300  # 5 minutes default lock
    ):
        """
        Initialize the orchestrator.
        
        Args:
            db_path: Path to SQLite database (fallback/persistent storage)
            redis_url: Redis connection URL (optional, for high-performance queue)
            lock_timeout_seconds: Default file lock expiration
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = lock_timeout_seconds
        self._lock = threading.Lock()
        
        # Try Redis if available
        self.redis_client = None
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                logger.info("Connected to Redis for task queue")
            except Exception as e:
                logger.warning(f"Redis unavailable, using SQLite: {e}")
                self.redis_client = None
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            # Task queue table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
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
                    repo_id TEXT,
                    parent_task_id TEXT,
                    needs_approval INTEGER DEFAULT 0,
                    approval_status TEXT,
                    approval_type TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    rejection_reason TEXT
                )
            """)

            # Add approval columns to existing tables (migration)
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN repo_id TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN needs_approval INTEGER DEFAULT 0")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN approval_status TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN approval_type TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN approved_by TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN approved_at TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN rejection_reason TEXT")
            except:
                pass
            
            # File locks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_locks (
                    path TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    locked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            
            # Agent mailbox table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_mail (
                    id TEXT PRIMARY KEY,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    read INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Agent status table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_status (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_task_id TEXT,
                    last_heartbeat TEXT NOT NULL,
                    session_start TEXT,
                    tasks_completed INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0
                )
            """)
            
            # Discussion board table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discussions (
                    id TEXT PRIMARY KEY,
                    author TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    in_reply_to TEXT,
                    votes_up INTEGER DEFAULT 0,
                    votes_down INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (in_reply_to) REFERENCES discussions(id)
                )
            """)
            
            # Proposals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    proposal_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    votes_for TEXT DEFAULT '[]',
                    votes_against TEXT DEFAULT '[]',
                    comments TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    implemented_at TEXT
                )
            """)
            
            # Votes tracking (to prevent double voting)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    vote_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(target_type, target_id, agent_id)
                )
            """)
            
            # Human approval queue - NOTHING publishes without human review
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_queue (
                    id TEXT PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    description TEXT NOT NULL,
                    files_path TEXT NOT NULL,
                    preview_url TEXT,
                    price TEXT,
                    submitted_by TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    reviewer_notes TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    published_at TEXT
                )
            """)
            
            # Project proposals queue - NOTHING gets built without human approval
            # Contains rich data from Hunter, Critic, and PM for informed decisions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_proposals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    -- From Hunter
                    hunter_pitch TEXT NOT NULL,
                    hunter_rating INTEGER NOT NULL,
                    market_size TEXT NOT NULL,
                    max_revenue_estimate TEXT NOT NULL,
                    -- From Critic
                    critic_evaluation TEXT NOT NULL,
                    critic_rating INTEGER NOT NULL,
                    cons TEXT NOT NULL,
                    differentiation TEXT NOT NULL,
                    -- From PM
                    spec_path TEXT NOT NULL,
                    effort_estimate TEXT NOT NULL,
                    -- Status
                    status TEXT DEFAULT 'pending',
                    submitted_by TEXT NOT NULL,
                    reviewer_notes TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
            """)
            
            # Token usage tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    session_id TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    recorded_at TEXT NOT NULL
                )
            """)
            
            # Processed issues table (for Support agent)
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
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_agent ON token_usage(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_time ON token_usage(recorded_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_to_agent ON agent_mail(to_agent, read)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discussions_topic ON discussions(topic)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_processed_issues_repo ON processed_issues(repo, issue_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_proposals_status ON project_proposals(status)")

            # Repos table for multi-repo management
            conn.execute("""
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
                    active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_slug ON repos(slug)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_active ON repos(active)")

            conn.commit()

    # ==================== REPOSITORY MANAGEMENT ====================

    def list_repos(self, active_only: bool = True, status: str = None) -> List[Dict[str, Any]]:
        """List all repositories."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                cursor = conn.execute(
                    "SELECT * FROM repos WHERE status = ? ORDER BY name",
                    (status,)
                )
            elif active_only:
                cursor = conn.execute(
                    "SELECT * FROM repos WHERE active = 1 ORDER BY name"
                )
            else:
                cursor = conn.execute("SELECT * FROM repos ORDER BY name")
            return [self._row_to_repo_dict(row) for row in cursor.fetchall()]

    def get_repo(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Get a repository by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM repos WHERE id = ?",
                (repo_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_repo_dict(row)

    def is_issue_processed(self, issue_id: str, repo_id: str, action: str) -> bool:
        """Check if an issue event has been processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 1 FROM processed_issues
                WHERE issue_id = ? AND repo_id = ? AND action = ?
                LIMIT 1
            """, (issue_id, repo_id, action))
            return cursor.fetchone() is not None

    def mark_issue_processed(self, issue_id: str, repo_id: str, action: str) -> None:
        """Record an issue event as processed."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO processed_issues
                (id, issue_id, repo_id, action, processed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), issue_id, repo_id, action, now))
            conn.commit()

    def get_repo_by_project_id(self, gitlab_project_id: str) -> Optional[Dict[str, Any]]:
        """Get a repository by GitLab project path or ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM repos WHERE gitlab_project_id = ?",
                (gitlab_project_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_repo_dict(row)

    def create_repo(
        self,
        repo_id: str,
        name: str,
        gitlab_url: str,
        gitlab_project_id: str,
        default_branch: str = "main",
        autonomy_mode: str = "guided",
        settings: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Create a new managed repository."""
        now = datetime.utcnow().isoformat()
        slug = name.lower().replace(' ', '-').replace('/', '-')

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO repos
                (id, name, gitlab_url, gitlab_project_id, slug, default_branch,
                 autonomy_mode, settings, status, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                repo_id, name, gitlab_url, gitlab_project_id,
                slug, default_branch, autonomy_mode,
                json.dumps(settings or {}), 'active', 1, now, now
            ))
            conn.commit()

        logger.info(f"Created repo: {name} ({repo_id})")
        return self.get_repo(repo_id)

    def update_repo(self, repo_id: str, **updates) -> bool:
        """Update repository settings."""
        updates['updated_at'] = datetime.utcnow().isoformat()

        # Handle settings separately (needs JSON serialization)
        if 'settings' in updates:
            updates['settings'] = json.dumps(updates['settings'])

        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE repos SET {set_clause} WHERE id = ?",
                (*updates.values(), repo_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_repo(self, repo_id: str) -> bool:
        """Delete a repository."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM repos WHERE id = ?",
                (repo_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_repo_dict(self, row) -> Dict[str, Any]:
        """Convert database row to repo dictionary."""
        return {
            'id': row['id'],
            'name': row['name'],
            'gitlab_url': row['gitlab_url'],
            'gitlab_project_id': row['gitlab_project_id'],
            'slug': row['slug'],
            'default_branch': row['default_branch'],
            'autonomy_mode': row['autonomy_mode'],
            'settings': json.loads(row['settings']) if row['settings'] else {},
            'status': row['status'],
            'active': bool(row['active']),
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }

    # ==================== TASK QUEUE ====================
    
    def create_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 5,
        created_by: Optional[str] = None,
        allow_duplicates: bool = False,
        repo_id: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Optional[Task]:
        """
        Create a new task in the queue.

        Args:
            task_type: Type of task (use TaskType enum values)
            payload: Task-specific data
            priority: 1-10 (higher = more urgent)
            created_by: Agent ID that created this task
            allow_duplicates: If False, reject if pending task with same title exists

        Returns:
            Created Task object, or None if duplicate detected
        """
        # Extract identifier for deduplication (check multiple fields)
        identifier = (
            payload.get('title') or
            payload.get('product_name') or
            payload.get('name') or
            payload.get('product')  # For fix_product, test_product, etc.
        )

        # Check for duplicates if identifier exists and duplicates not allowed
        if identifier and not allow_duplicates:
            with sqlite3.connect(self.db_path) as conn:
                # Check for existing pending/claimed task with same identifier AND same type
                cursor = conn.execute("""
                    SELECT id FROM tasks
                    WHERE status IN ('pending', 'claimed')
                    AND type = ?
                    AND (
                        json_extract(payload, '$.title') = ?
                        OR json_extract(payload, '$.product_name') = ?
                        OR json_extract(payload, '$.name') = ?
                        OR json_extract(payload, '$.product') = ?
                    )
                    LIMIT 1
                """, (task_type, identifier, identifier, identifier, identifier))
                existing = cursor.fetchone()
                if existing:
                    logger.warning(f"Duplicate task rejected: '{identifier}' ({task_type}) already exists as {existing[0]}")
                    return None

        task = Task(
            id=str(uuid.uuid4()),
            type=task_type,
            priority=min(10, max(1, priority)),
            payload=payload,
            created_by=created_by,
            parent_task_id=parent_task_id
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO tasks (id, type, priority, payload, status, created_by, created_at, repo_id, parent_task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id, task.type, task.priority,
                json.dumps(task.payload), task.status,
                task.created_by, task.created_at, repo_id, parent_task_id
            ))
            conn.commit()

        # Also push to Redis if available for fast retrieval
        if self.redis_client:
            self.redis_client.zadd(
                "task_queue",
                {task.id: task.priority}
            )
            self.redis_client.hset(f"task:{task.id}", mapping={
                "data": json.dumps(task.to_dict())
            })

        logger.info(f"Created task {task.id} ({task.type}) with priority {task.priority}")
        return task
    
    def claim_task(self, agent_id: str, task_types: Optional[List[str]] = None) -> Optional[Task]:
        """
        Claim the highest priority available task for an agent.

        Args:
            agent_id: ID of the claiming agent
            task_types: Optional list of task types this agent can handle

        Returns:
            Claimed Task or None if no tasks available

        Note:
            If a task has assigned_to set, ONLY that agent can claim it.
            Tasks with assigned_to = NULL can be claimed by any agent.

            Automatically releases abandoned tasks (claimed > 2 hours) before claiming.
        """
        # Release any abandoned tasks before claiming
        self.release_abandoned_tasks(timeout_hours=2)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Build query - respect assigned_to field
                # Key logic: Tasks directly assigned to this agent can be claimed regardless of task type.
                # Task type filtering only applies to unassigned tasks. This allows human directives
                # to reach specific agents even if 'directive' isn't in their task_types list.
                if task_types:
                    placeholders = ','.join('?' * len(task_types))
                    # Tasks assigned to this agent OR unassigned tasks matching agent's task types
                    query = f"""
                        SELECT * FROM tasks
                        WHERE status = 'pending'
                        AND (assigned_to = ? OR (assigned_to IS NULL AND type IN ({placeholders})))
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                    """
                    cursor = conn.execute(query, [agent_id] + task_types)
                else:
                    cursor = conn.execute("""
                        SELECT * FROM tasks
                        WHERE status = 'pending'
                        AND (assigned_to IS NULL OR assigned_to = ?)
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                    """, (agent_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                task_id = row['id']
                now = datetime.utcnow().isoformat()
                
                # Claim the task
                conn.execute("""
                    UPDATE tasks 
                    SET status = 'claimed', assigned_to = ?, claimed_at = ?
                    WHERE id = ? AND status = 'pending'
                """, (agent_id, now, task_id))
                conn.commit()
                
                # Verify we got it (in case of race condition)
                cursor = conn.execute(
                    "SELECT * FROM tasks WHERE id = ? AND assigned_to = ?",
                    (task_id, agent_id)
                )
                row = cursor.fetchone()
                if not row:
                    return None
                
                task = Task(
                    id=row['id'],
                    type=row['type'],
                    priority=row['priority'],
                    payload=json.loads(row['payload']),
                    status=row['status'],
                    assigned_to=row['assigned_to'],
                    created_by=row['created_by'],
                    created_at=row['created_at'],
                    claimed_at=row['claimed_at']
                )
                
                logger.info(f"Agent {agent_id} claimed task {task.id} ({task.type})")
                return task
    
    def complete_task(
        self,
        task_id: str,
        agent_id: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Mark a task as completed or failed.
        
        Args:
            task_id: ID of the task
            agent_id: ID of the agent completing it
            result: Task result data (for success)
            error: Error message (for failure)
            
        Returns:
            True if updated successfully
        """
        status = TaskStatus.FAILED.value if error else TaskStatus.COMPLETED.value
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get task details for notification
            task_row = conn.execute("SELECT type, payload FROM tasks WHERE id = ?", (task_id,)).fetchone()
            
            cursor = conn.execute("""
                UPDATE tasks 
                SET status = ?, completed_at = ?, result = ?, error = ?
                WHERE id = ? AND assigned_to = ?
            """, (
                status, now,
                json.dumps(result) if result else None,
                error,
                task_id, agent_id
            ))
            conn.commit()
            
            success = cursor.rowcount > 0
            if success:
                logger.info(f"Task {task_id} marked as {status} by {agent_id}")
                
                # Send Slack notification for failures
                if error and task_row:
                    try:
                        from dashboard.slack_notifications import notify_task_failed
                        payload = json.loads(task_row['payload']) if task_row['payload'] else {}
                        title = payload.get('title', payload.get('product_name', payload.get('product', 'Unknown')))
                        notify_task_failed(task_row['type'], title, error, agent_id)
                    except Exception as e:
                        logger.warning(f"Failed to send Slack failure notification: {e}")
            
            return success
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Task(
                id=row['id'],
                type=row['type'],
                priority=row['priority'],
                payload=json.loads(row['payload']),
                status=row['status'],
                assigned_to=row['assigned_to'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                claimed_at=row['claimed_at'],
                completed_at=row['completed_at'],
                result=json.loads(row['result']) if row['result'] else None,
                error=row['error'],
                parent_task_id=row['parent_task_id']
            )
    
    def get_pending_tasks(self, limit: int = 50) -> List[Task]:
        """Get all pending tasks ordered by priority."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM tasks 
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (limit,))
            
            return [Task(
                id=row['id'],
                type=row['type'],
                priority=row['priority'],
                payload=json.loads(row['payload']),
                status=row['status'],
                assigned_to=row['assigned_to'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                parent_task_id=row['parent_task_id']
            ) for row in cursor.fetchall()]

    def get_assigned_tasks(
        self,
        agent_id: str,
        statuses: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[Task]:
        """Get tasks currently assigned to a specific agent."""
        statuses = statuses or ['claimed', 'in_progress']
        placeholders = ','.join(['?'] * len(statuses))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"""
                SELECT * FROM tasks
                WHERE assigned_to = ?
                  AND status IN ({placeholders})
                ORDER BY
                    CASE WHEN claimed_at IS NULL THEN 1 ELSE 0 END,
                    claimed_at ASC,
                    created_at ASC
                LIMIT ?
            """, [agent_id] + statuses + [limit])

            return [Task(
                id=row['id'],
                type=row['type'],
                priority=row['priority'],
                payload=json.loads(row['payload']),
                status=row['status'],
                assigned_to=row['assigned_to'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                claimed_at=row['claimed_at'],
                completed_at=row['completed_at'],
                result=json.loads(row['result']) if row['result'] else None,
                error=row['error'],
                parent_task_id=row['parent_task_id']
            ) for row in cursor.fetchall()]
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get task queue statistics."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            stats = {
                "total": 0,
                "by_status": {},
                "by_type": {},
                "by_agent": {}
            }
            
            # Count by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count FROM tasks GROUP BY status
            """)
            for row in cursor.fetchall():
                stats["by_status"][row['status']] = row['count']
                stats["total"] += row['count']
            
            # Count by type
            cursor = conn.execute("""
                SELECT type, COUNT(*) as count FROM tasks 
                WHERE status = 'pending' GROUP BY type
            """)
            for row in cursor.fetchall():
                stats["by_type"][row['type']] = row['count']
            
            # Count by assigned agent
            cursor = conn.execute("""
                SELECT assigned_to, COUNT(*) as count FROM tasks 
                WHERE status IN ('claimed', 'in_progress') AND assigned_to IS NOT NULL
                GROUP BY assigned_to
            """)
            for row in cursor.fetchall():
                stats["by_agent"][row['assigned_to']] = row['count']
            
            return stats

    def release_abandoned_tasks(self, timeout_hours: int = 2) -> int:
        """
        Release tasks that have been claimed for longer than the timeout.

        This prevents task starvation when agents crash or restart without
        completing their claimed tasks.

        Args:
            timeout_hours: Hours after which a claimed task is considered abandoned

        Returns:
            Number of tasks released back to pending
        """
        cutoff = (datetime.utcnow() - timedelta(hours=timeout_hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # Find abandoned tasks
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT id, type, assigned_to, claimed_at
                FROM tasks
                WHERE status = 'claimed' AND claimed_at < ?
            """, (cutoff,))

            abandoned = cursor.fetchall()

            if not abandoned:
                return 0

            # Release them back to pending
            cursor = conn.execute("""
                UPDATE tasks
                SET status = 'pending', assigned_to = NULL, claimed_at = NULL
                WHERE status = 'claimed' AND claimed_at < ?
            """, (cutoff,))
            conn.commit()

            released_count = cursor.rowcount

            if released_count > 0:
                # Log which tasks were released
                for row in abandoned:
                    logger.info(f"Released abandoned task {row['id']} ({row['type']}) from {row['assigned_to']}")

            return released_count

    def cancel_task(self, task_id: str, reason: str, cancelled_by: Optional[str] = None) -> bool:
        """
        Cancel a pending or claimed task.

        Args:
            task_id: ID of the task to cancel
            reason: Reason for cancellation
            cancelled_by: Agent or user cancelling the task

        Returns:
            True if cancelled successfully, False if task not found or already completed
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Check if task exists and is cancellable
            cursor = conn.execute(
                "SELECT id, type, status FROM tasks WHERE id = ?",
                (task_id,)
            )
            row = cursor.fetchone()

            if not row:
                logger.warning(f"Cannot cancel task {task_id}: not found")
                return False

            if row['status'] in ('completed', 'cancelled'):
                logger.warning(f"Cannot cancel task {task_id}: already {row['status']}")
                return False

            # Cancel the task
            now = datetime.utcnow().isoformat()
            conn.execute("""
                UPDATE tasks
                SET status = 'cancelled',
                    completed_at = ?,
                    error = ?
                WHERE id = ?
            """, (now, f"Cancelled by {cancelled_by or 'system'}: {reason}", task_id))
            conn.commit()

            # Remove from Redis queue if present
            if self.redis_client:
                self.redis_client.zrem("task_queue", task_id)
                self.redis_client.delete(f"task:{task_id}")

            logger.info(f"Task {task_id} ({row['type']}) cancelled by {cancelled_by or 'system'}: {reason}")
            return True

    def cancel_duplicate_tasks(self, title: str, keep_task_id: Optional[str] = None) -> int:
        """
        Cancel all duplicate pending tasks with the same title/identifier, keeping one.

        Args:
            title: Title/identifier to search for duplicates
            keep_task_id: Optional task ID to keep (if None, keeps highest priority)

        Returns:
            Number of tasks cancelled
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Find all pending tasks with this title/identifier
            cursor = conn.execute("""
                SELECT id, priority, created_at FROM tasks
                WHERE status = 'pending'
                AND (
                    json_extract(payload, '$.title') = ?
                    OR json_extract(payload, '$.product_name') = ?
                    OR json_extract(payload, '$.name') = ?
                    OR json_extract(payload, '$.product') = ?
                )
                ORDER BY priority DESC, created_at ASC
            """, (title, title, title, title))

            tasks = cursor.fetchall()

            if len(tasks) <= 1:
                return 0

            # Determine which to keep
            if keep_task_id:
                keep_ids = {keep_task_id}
            else:
                # Keep the highest priority (first in list due to ORDER BY)
                keep_ids = {tasks[0]['id']}

            cancelled = 0
            for task in tasks:
                if task['id'] not in keep_ids:
                    if self.cancel_task(task['id'], f"Duplicate of {list(keep_ids)[0]}", "meta"):
                        cancelled += 1

            return cancelled

    # ==================== FILE LOCKER ====================
    
    def acquire_lock(self, path: str, agent_id: str, timeout: Optional[int] = None) -> bool:
        """
        Acquire a lock on a file path.
        
        Args:
            path: File path to lock
            agent_id: Agent requesting the lock
            timeout: Lock timeout in seconds (default: self.lock_timeout)
            
        Returns:
            True if lock acquired, False if already locked by another agent
        """
        timeout = timeout or self.lock_timeout
        now = datetime.utcnow()
        expires = now + timedelta(seconds=timeout)
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Check existing lock
                cursor = conn.execute(
                    "SELECT * FROM file_locks WHERE path = ?", (path,)
                )
                row = cursor.fetchone()
                
                if row:
                    existing_lock = FileLock(
                        path=row['path'],
                        agent_id=row['agent_id'],
                        locked_at=row['locked_at'],
                        expires_at=row['expires_at']
                    )
                    
                    # Same agent can refresh lock
                    if existing_lock.agent_id == agent_id:
                        conn.execute("""
                            UPDATE file_locks SET expires_at = ? WHERE path = ?
                        """, (expires.isoformat(), path))
                        conn.commit()
                        return True
                    
                    # Check if expired
                    if not existing_lock.is_expired():
                        logger.warning(f"Lock denied for {path}: held by {existing_lock.agent_id}")
                        return False
                    
                    # Expired lock - take it over
                    conn.execute("""
                        UPDATE file_locks 
                        SET agent_id = ?, locked_at = ?, expires_at = ?
                        WHERE path = ?
                    """, (agent_id, now.isoformat(), expires.isoformat(), path))
                else:
                    # Create new lock
                    conn.execute("""
                        INSERT INTO file_locks (path, agent_id, locked_at, expires_at)
                        VALUES (?, ?, ?, ?)
                    """, (path, agent_id, now.isoformat(), expires.isoformat()))
                
                conn.commit()
                logger.debug(f"Lock acquired for {path} by {agent_id}")
                return True
    
    def release_lock(self, path: str, agent_id: str) -> bool:
        """
        Release a file lock.
        
        Args:
            path: File path to unlock
            agent_id: Agent releasing the lock
            
        Returns:
            True if released, False if not held by this agent
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM file_locks WHERE path = ? AND agent_id = ?
            """, (path, agent_id))
            conn.commit()
            
            success = cursor.rowcount > 0
            if success:
                logger.debug(f"Lock released for {path} by {agent_id}")
            return success
    
    def get_locks(self, agent_id: Optional[str] = None) -> List[FileLock]:
        """Get all active locks, optionally filtered by agent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if agent_id:
                cursor = conn.execute(
                    "SELECT * FROM file_locks WHERE agent_id = ?", (agent_id,)
                )
            else:
                cursor = conn.execute("SELECT * FROM file_locks")
            
            locks = []
            now = datetime.utcnow()
            for row in cursor.fetchall():
                lock = FileLock(
                    path=row['path'],
                    agent_id=row['agent_id'],
                    locked_at=row['locked_at'],
                    expires_at=row['expires_at']
                )
                if not lock.is_expired():
                    locks.append(lock)
            
            return locks
    
    def cleanup_expired_locks(self) -> int:
        """Remove all expired locks. Returns count of removed locks."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM file_locks WHERE expires_at < ?", (now,)
            )
            conn.commit()
            return cursor.rowcount
    
    # ==================== AGENT MAILBOX ====================
    
    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        payload: Dict[str, Any]
    ) -> AgentMessage:
        """
        Send a message from one agent to another.
        
        Args:
            from_agent: Sending agent ID
            to_agent: Receiving agent ID
            message_type: Type of message (use MessageType enum values)
            payload: Message data
            
        Returns:
            Created AgentMessage
        """
        message = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            payload=payload
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO agent_mail (id, from_agent, to_agent, message_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                message.id, message.from_agent, message.to_agent,
                message.message_type, json.dumps(message.payload),
                message.created_at
            ))
            conn.commit()
        
        logger.info(f"Message {message.id} sent from {from_agent} to {to_agent} ({message_type})")
        return message
    
    def get_messages(
        self,
        agent_id: str,
        unread_only: bool = True,
        limit: int = 50
    ) -> List[AgentMessage]:
        """
        Get messages for an agent.
        
        Args:
            agent_id: Agent to get messages for
            unread_only: Only return unread messages
            limit: Maximum messages to return
            
        Returns:
            List of AgentMessage objects
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if unread_only:
                cursor = conn.execute("""
                    SELECT * FROM agent_mail 
                    WHERE to_agent = ? AND read = 0
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM agent_mail 
                    WHERE to_agent = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            
            return [AgentMessage(
                id=row['id'],
                from_agent=row['from_agent'],
                to_agent=row['to_agent'],
                message_type=row['message_type'],
                payload=json.loads(row['payload']),
                read=bool(row['read']),
                created_at=row['created_at']
            ) for row in cursor.fetchall()]
    
    def mark_read(self, message_id: str, agent_id: str) -> bool:
        """Mark a message as read."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE agent_mail SET read = 1 
                WHERE id = ? AND to_agent = ?
            """, (message_id, agent_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def mark_all_read(self, agent_id: str) -> int:
        """Mark all messages for an agent as read."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE agent_mail SET read = 1 WHERE to_agent = ?
            """, (agent_id,))
            conn.commit()
            return cursor.rowcount
    
    # ==================== AGENT STATUS ====================
    
    def update_agent_status(
        self,
        agent_id: str,
        status: str,
        current_task_id: Optional[str] = None,
        tokens_used: int = 0
    ) -> None:
        """
        Update an agent's status.
        
        Args:
            agent_id: Agent ID
            status: Current status (online, working, idle, offline)
            current_task_id: ID of current task (if any)
            tokens_used: Tokens used in current session
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO agent_status (agent_id, status, current_task_id, last_heartbeat, session_start, tokens_used)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    status = excluded.status,
                    current_task_id = excluded.current_task_id,
                    last_heartbeat = excluded.last_heartbeat,
                    tokens_used = agent_status.tokens_used + excluded.tokens_used
            """, (agent_id, status, current_task_id, now, now, tokens_used))
            conn.commit()
    
    def get_agent_statuses(self) -> List[Dict[str, Any]]:
        """Get status of all known agents."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM agent_status")
            return [dict(row) for row in cursor.fetchall()]
    
    def increment_completed(self, agent_id: str) -> None:
        """Increment the completed task count for an agent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE agent_status 
                SET tasks_completed = tasks_completed + 1
                WHERE agent_id = ?
            """, (agent_id,))
            conn.commit()
    
    # ==================== DISCUSSION BOARD ====================
    
    def post_discussion(
        self,
        author: str,
        topic: str,
        content: str,
        in_reply_to: Optional[str] = None
    ) -> DiscussionPost:
        """
        Post to the shared discussion board.
        
        Args:
            author: Agent posting
            topic: Discussion topic/thread
            content: Post content
            in_reply_to: Optional parent post ID for replies
            
        Returns:
            Created DiscussionPost
        """
        post = DiscussionPost(
            id=str(uuid.uuid4()),
            author=author,
            topic=topic,
            content=content,
            in_reply_to=in_reply_to
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO discussions (id, author, topic, content, in_reply_to, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (post.id, post.author, post.topic, post.content, post.in_reply_to, post.created_at))
            conn.commit()
        
        logger.info(f"[DISCUSS] {author} posted in '{topic}': {content[:50]}...")
        return post
    
    def get_discussions(
        self,
        topic: Optional[str] = None,
        limit: int = 50
    ) -> List[DiscussionPost]:
        """Get discussion posts, optionally filtered by topic."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if topic:
                cursor = conn.execute("""
                    SELECT * FROM discussions WHERE topic = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (topic, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM discussions 
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,))
            
            return [DiscussionPost(
                id=row['id'],
                author=row['author'],
                topic=row['topic'],
                content=row['content'],
                in_reply_to=row['in_reply_to'],
                votes_up=row['votes_up'],
                votes_down=row['votes_down'],
                created_at=row['created_at']
            ) for row in cursor.fetchall()]
    
    def get_recent_discussions(self, minutes: int = 30) -> List[DiscussionPost]:
        """Get discussions from the last N minutes."""
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM discussions WHERE created_at > ?
                ORDER BY created_at DESC
            """, (cutoff,))
            
            return [DiscussionPost(
                id=row['id'],
                author=row['author'],
                topic=row['topic'],
                content=row['content'],
                in_reply_to=row['in_reply_to'],
                votes_up=row['votes_up'],
                votes_down=row['votes_down'],
                created_at=row['created_at']
            ) for row in cursor.fetchall()]
    
    def vote_discussion(self, post_id: str, agent_id: str, vote_up: bool) -> bool:
        """Vote on a discussion post."""
        vote_type = "up" if vote_up else "down"
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                    INSERT INTO votes (id, target_type, target_id, agent_id, vote_type, created_at)
                    VALUES (?, 'discussion', ?, ?, ?, ?)
                """, (str(uuid.uuid4()), post_id, agent_id, vote_type, now))
                
                column = "votes_up" if vote_up else "votes_down"
                conn.execute(f"UPDATE discussions SET {column} = {column} + 1 WHERE id = ?", (post_id,))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already voted
    
    # ==================== PROPOSAL SYSTEM ====================
    
    def create_proposal(
        self,
        proposal_type: str,
        title: str,
        description: str,
        proposed_by: str,
        payload: Dict[str, Any]
    ) -> Proposal:
        """
        Create a new proposal for the swarm to vote on.
        
        Args:
            proposal_type: Type from ProposalType enum
            title: Short title
            description: Full description
            proposed_by: Agent creating proposal
            payload: Type-specific data (e.g., agent prompt content)
            
        Returns:
            Created Proposal
        """
        proposal = Proposal(
            id=str(uuid.uuid4()),
            proposal_type=proposal_type,
            title=title,
            description=description,
            proposed_by=proposed_by,
            payload=payload
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO proposals (id, proposal_type, title, description, proposed_by, payload, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                proposal.id, proposal.proposal_type, proposal.title,
                proposal.description, proposal.proposed_by,
                json.dumps(proposal.payload), proposal.status, proposal.created_at
            ))
            conn.commit()
        
        # Also post to discussion board
        self.post_discussion(
            author=proposed_by,
            topic=f"proposal:{proposal.id}",
            content=f"🗳️ PROPOSAL: {title}\n\nType: {proposal_type}\n\n{description}"
        )
        
        logger.info(f"[PROPOSAL] {proposed_by} proposed: {title} ({proposal_type})")
        return proposal
    
    def vote_proposal(self, proposal_id: str, agent_id: str, vote_for: bool, comment: Optional[str] = None) -> bool:
        """
        Vote on a proposal.
        
        Args:
            proposal_id: Proposal to vote on
            agent_id: Voting agent
            vote_for: True = approve, False = reject
            comment: Optional comment explaining vote
            
        Returns:
            True if vote recorded
        """
        now = datetime.utcnow().isoformat()
        vote_type = "for" if vote_for else "against"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Check if already voted
            cursor = conn.execute("""
                SELECT * FROM votes WHERE target_type = 'proposal' AND target_id = ? AND agent_id = ?
            """, (proposal_id, agent_id))
            if cursor.fetchone():
                return False  # Already voted
            
            # Record vote
            conn.execute("""
                INSERT INTO votes (id, target_type, target_id, agent_id, vote_type, created_at)
                VALUES (?, 'proposal', ?, ?, ?, ?)
            """, (str(uuid.uuid4()), proposal_id, agent_id, vote_type, now))
            
            # Update proposal
            cursor = conn.execute("SELECT votes_for, votes_against FROM proposals WHERE id = ?", (proposal_id,))
            row = cursor.fetchone()
            if row:
                votes_for = json.loads(row['votes_for'])
                votes_against = json.loads(row['votes_against'])
                
                if vote_for:
                    votes_for.append(agent_id)
                else:
                    votes_against.append(agent_id)
                
                conn.execute("""
                    UPDATE proposals SET votes_for = ?, votes_against = ? WHERE id = ?
                """, (json.dumps(votes_for), json.dumps(votes_against), proposal_id))
            
            conn.commit()
        
        # Post comment if provided
        if comment:
            vote_emoji = "👍" if vote_for else "👎"
            self.post_discussion(
                author=agent_id,
                topic=f"proposal:{proposal_id}",
                content=f"{vote_emoji} {agent_id} votes {'FOR' if vote_for else 'AGAINST'}: {comment}"
            )
        
        # Check for consensus
        self._check_proposal_consensus(proposal_id)
        
        logger.info(f"[VOTE] {agent_id} voted {vote_type} on proposal {proposal_id}")
        return True
    
    def _check_proposal_consensus(self, proposal_id: str, quorum: int = 3, threshold: float = 0.6) -> None:
        """
        Check if a proposal has reached consensus.
        
        Args:
            proposal_id: Proposal to check
            quorum: Minimum votes needed
            threshold: Fraction needed for approval (0.6 = 60%)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
            row = cursor.fetchone()
            if not row or row['status'] != 'open':
                return
            
            votes_for = json.loads(row['votes_for'])
            votes_against = json.loads(row['votes_against'])
            total_votes = len(votes_for) + len(votes_against)
            
            if total_votes < quorum:
                return  # Not enough votes yet
            
            now = datetime.utcnow().isoformat()
            approval_rate = len(votes_for) / total_votes
            
            if approval_rate >= threshold:
                new_status = ProposalStatus.APPROVED.value
                self.post_discussion(
                    author="system",
                    topic=f"proposal:{proposal_id}",
                    content=f"✅ APPROVED with {len(votes_for)}/{total_votes} votes ({approval_rate:.0%})"
                )
            elif (1 - approval_rate) >= threshold:
                new_status = ProposalStatus.REJECTED.value
                self.post_discussion(
                    author="system",
                    topic=f"proposal:{proposal_id}",
                    content=f"❌ REJECTED with {len(votes_against)}/{total_votes} against ({1-approval_rate:.0%})"
                )
            else:
                return  # No consensus yet
            
            conn.execute("""
                UPDATE proposals SET status = ?, decided_at = ? WHERE id = ?
            """, (new_status, now, proposal_id))
            conn.commit()
            
            logger.info(f"[CONSENSUS] Proposal {proposal_id} {new_status}")
    
    def get_open_proposals(self) -> List[Proposal]:
        """Get all open proposals awaiting votes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM proposals WHERE status = 'open'
                ORDER BY created_at DESC
            """)
            
            return [Proposal(
                id=row['id'],
                proposal_type=row['proposal_type'],
                title=row['title'],
                description=row['description'],
                proposed_by=row['proposed_by'],
                payload=json.loads(row['payload']),
                status=row['status'],
                votes_for=json.loads(row['votes_for']),
                votes_against=json.loads(row['votes_against']),
                comments=json.loads(row['comments']),
                created_at=row['created_at']
            ) for row in cursor.fetchall()]
    
    def get_approved_proposals(self, unimplemented_only: bool = True) -> List[Proposal]:
        """Get approved proposals, optionally only those not yet implemented."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if unimplemented_only:
                cursor = conn.execute("""
                    SELECT * FROM proposals WHERE status = 'approved'
                    ORDER BY decided_at ASC
                """)
            else:
                cursor = conn.execute("""
                    SELECT * FROM proposals WHERE status IN ('approved', 'implemented')
                    ORDER BY decided_at DESC
                """)
            
            return [Proposal(
                id=row['id'],
                proposal_type=row['proposal_type'],
                title=row['title'],
                description=row['description'],
                proposed_by=row['proposed_by'],
                payload=json.loads(row['payload']),
                status=row['status'],
                votes_for=json.loads(row['votes_for']),
                votes_against=json.loads(row['votes_against']),
                comments=json.loads(row['comments']),
                created_at=row['created_at'],
                decided_at=row['decided_at']
            ) for row in cursor.fetchall()]
    
    def mark_proposal_implemented(self, proposal_id: str) -> bool:
        """Mark a proposal as implemented."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE proposals SET status = 'implemented', implemented_at = ?
                WHERE id = ? AND status = 'approved'
            """, (now, proposal_id))
            conn.commit()
            return cursor.rowcount > 0
    
    # ==================== HUMAN APPROVAL QUEUE ====================
    
    def submit_for_approval(
        self,
        product_name: str,
        product_type: str,
        platform: str,
        description: str,
        files_path: str,
        submitted_by: str,
        preview_url: Optional[str] = None,
        price: Optional[str] = None
    ) -> ApprovalItem:
        """
        Submit a product for human approval before publishing.
        
        NOTHING gets published without going through this queue.
        
        Args:
            product_name: Name of the product
            product_type: Type (saas, template, action, article, etc.)
            platform: Target platform (gumroad, github, devto, npm)
            description: What this product does
            files_path: Path to product files for review
            submitted_by: Agent submitting
            preview_url: Optional preview/demo URL
            price: Optional price point
            
        Returns:
            Created ApprovalItem
        """
        item = ApprovalItem(
            id=str(uuid.uuid4()),
            product_name=product_name,
            product_type=product_type,
            platform=platform,
            description=description,
            files_path=files_path,
            preview_url=preview_url,
            price=price,
            submitted_by=submitted_by
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO approval_queue 
                (id, product_name, product_type, platform, description, files_path, 
                 preview_url, price, submitted_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.id, item.product_name, item.product_type, item.platform,
                item.description, item.files_path, item.preview_url, item.price,
                item.submitted_by, item.status, item.created_at
            ))
            conn.commit()
        
        # Notify in discussion
        self.post_discussion(
            author="system",
            topic="approvals",
            content=f"📋 NEW APPROVAL REQUEST: {product_name} ({product_type}) for {platform} - submitted by {submitted_by}. Waiting for human review."
        )
        
        # Send Slack notification
        try:
            from dashboard.slack_notifications import notify_approval_ready
            notify_approval_ready(product_name, product_type, platform, item.id)
        except Exception as e:
            logger.warning(f"Failed to send Slack notification: {e}")
        
        logger.info(f"[APPROVAL] {submitted_by} submitted {product_name} for human approval")
        return item
    
    def get_pending_approvals(self) -> List[ApprovalItem]:
        """Get all items pending human approval."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM approval_queue 
                WHERE status = 'pending'
                ORDER BY created_at ASC
            """)
            
            return [ApprovalItem(
                id=row['id'],
                product_name=row['product_name'],
                product_type=row['product_type'],
                platform=row['platform'],
                description=row['description'],
                files_path=row['files_path'],
                preview_url=row['preview_url'],
                price=row['price'],
                submitted_by=row['submitted_by'],
                status=row['status'],
                reviewer_notes=row['reviewer_notes'],
                created_at=row['created_at']
            ) for row in cursor.fetchall()]
    
    def get_all_approvals(self, limit: int = 50) -> List[ApprovalItem]:
        """Get all approval items (for dashboard history)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM approval_queue 
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            return [ApprovalItem(
                id=row['id'],
                product_name=row['product_name'],
                product_type=row['product_type'],
                platform=row['platform'],
                description=row['description'],
                files_path=row['files_path'],
                preview_url=row['preview_url'],
                price=row['price'],
                submitted_by=row['submitted_by'],
                status=row['status'],
                reviewer_notes=row['reviewer_notes'],
                created_at=row['created_at'],
                reviewed_at=row['reviewed_at'],
                published_at=row['published_at']
            ) for row in cursor.fetchall()]
    
    def approve_item(self, item_id: str, notes: Optional[str] = None) -> bool:
        """
        Human approves an item for publishing.
        
        Args:
            item_id: Approval item ID
            notes: Optional reviewer notes
            
        Returns:
            True if approved successfully
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE approval_queue 
                SET status = 'approved', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
            """, (notes, now, item_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                # Get item details for notification
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM approval_queue WHERE id = ?", (item_id,)).fetchone()
                if row:
                    self.post_discussion(
                        author="human",
                        topic="approvals",
                        content=f"✅ APPROVED: {row['product_name']} - Ready to publish on {row['platform']}!"
                    )
                    
                    # Create a publish task for the Publisher agent
                    self.create_task(
                        task_type="publish",
                        priority=9,
                        payload={
                            "approval_id": item_id,
                            "product_name": row['product_name'],
                            "platform": row['platform'],
                            "files_path": row['files_path'],
                            "price": row['price']
                        },
                        created_by="human"
                    )
                
                logger.info(f"[APPROVAL] Human approved {item_id}")
                return True
            return False
    
    def reject_item(self, item_id: str, reason: str) -> bool:
        """
        Human rejects an item - will NOT be published.
        
        Args:
            item_id: Approval item ID
            reason: Why it was rejected
            
        Returns:
            True if rejected successfully
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE approval_queue 
                SET status = 'rejected', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
            """, (reason, now, item_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                # Notify agents
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM approval_queue WHERE id = ?", (item_id,)).fetchone()
                if row:
                    self.post_discussion(
                        author="human",
                        topic="approvals",
                        content=f"❌ REJECTED: {row['product_name']} - Reason: {reason}"
                    )
                
                logger.info(f"[APPROVAL] Human rejected {item_id}: {reason}")
                return True
            return False
    
    def mark_published(self, item_id: str, publish_url: Optional[str] = None) -> bool:
        """Mark an approved item as successfully published."""
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            notes_update = f"Published: {publish_url}" if publish_url else "Published"
            cursor = conn.execute("""
                UPDATE approval_queue 
                SET status = 'published', published_at = ?, 
                    reviewer_notes = COALESCE(reviewer_notes || ' | ', '') || ?
                WHERE id = ? AND status = 'approved'
            """, (now, notes_update, item_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM approval_queue WHERE id = ?", (item_id,)).fetchone()
                if row:
                    self.post_discussion(
                        author="system",
                        topic="approvals",
                        content=f"🚀 PUBLISHED: {row['product_name']} is now live on {row['platform']}!"
                    )
                return True
            return False
    
    def is_approved(self, item_id: str) -> bool:
        """Check if an item has been approved (for Publisher to verify before publishing)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT status FROM approval_queue WHERE id = ?", (item_id,)
            )
            row = cursor.fetchone()
            return row and row[0] == 'approved'
    
    # ==================== PROJECT PROPOSALS ====================
    # Rich approval queue for build decisions (Hunter → Critic → PM → Human)
    
    def submit_project_proposal(
        self,
        title: str,
        hunter_pitch: str,
        hunter_rating: int,
        market_size: str,
        max_revenue_estimate: str,
        critic_evaluation: str,
        critic_rating: int,
        cons: str,
        differentiation: str,
        spec_path: str,
        effort_estimate: str,
        submitted_by: str
    ) -> ProjectProposal:
        """
        Submit a project proposal for human approval before building.
        
        Contains rich context from Hunter, Critic, and PM for informed decisions.
        
        Args:
            title: Project name
            hunter_pitch: 2-3 sentence pitch from Hunter
            hunter_rating: Hunter's confidence (1-10)
            market_size: Small/Medium/Large
            max_revenue_estimate: e.g. "$2000/mo" or "$50 one-time"
            critic_evaluation: Why Critic thinks it's good
            critic_rating: Critic's rating (1-10)
            cons: Bullet points of risks
            differentiation: What makes it special
            spec_path: Path to PM's spec file
            effort_estimate: e.g. "20 hours"
            submitted_by: Agent that submitted (usually PM)
            
        Returns:
            Created ProjectProposal
        """
        proposal = ProjectProposal(
            id=str(uuid.uuid4()),
            title=title,
            hunter_pitch=hunter_pitch,
            hunter_rating=hunter_rating,
            market_size=market_size,
            max_revenue_estimate=max_revenue_estimate,
            critic_evaluation=critic_evaluation,
            critic_rating=critic_rating,
            cons=cons,
            differentiation=differentiation,
            spec_path=spec_path,
            effort_estimate=effort_estimate,
            submitted_by=submitted_by
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO project_proposals 
                (id, title, hunter_pitch, hunter_rating, market_size, max_revenue_estimate,
                 critic_evaluation, critic_rating, cons, differentiation,
                 spec_path, effort_estimate, status, submitted_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                proposal.id, proposal.title, proposal.hunter_pitch, proposal.hunter_rating,
                proposal.market_size, proposal.max_revenue_estimate, proposal.critic_evaluation,
                proposal.critic_rating, proposal.cons, proposal.differentiation,
                proposal.spec_path, proposal.effort_estimate, proposal.status,
                proposal.submitted_by, proposal.created_at
            ))
            conn.commit()
        
        # Notify in discussion
        avg_rating = (hunter_rating + critic_rating) / 2
        self.post_discussion(
            author="system",
            topic="projects",
            content=f"📋 NEW PROJECT PROPOSAL: {title} (⭐ {avg_rating}/10) - ${max_revenue_estimate} potential. Waiting for human review."
        )
        
        # Send Slack notification
        try:
            from dashboard.slack_notifications import notify_project_proposal
            notify_project_proposal(proposal)
        except Exception as e:
            logger.warning(f"Failed to send Slack notification for project: {e}")
        
        logger.info(f"[PROJECT] {submitted_by} submitted project proposal: {title}")
        return proposal
    
    def get_pending_project_proposals(self) -> List[ProjectProposal]:
        """Get all project proposals pending human review."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM project_proposals 
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            
            return [self._row_to_project_proposal(row) for row in cursor.fetchall()]
    
    def get_deferred_project_proposals(self) -> List[ProjectProposal]:
        """Get all deferred project proposals (backlog)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM project_proposals 
                WHERE status = 'deferred'
                ORDER BY created_at DESC
            """)
            
            return [self._row_to_project_proposal(row) for row in cursor.fetchall()]
    
    def get_all_project_proposals(self, status: Optional[str] = None, limit: int = 50) -> List[ProjectProposal]:
        """Get project proposals, optionally filtered by status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                cursor = conn.execute("""
                    SELECT * FROM project_proposals 
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (status, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM project_proposals 
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            return [self._row_to_project_proposal(row) for row in cursor.fetchall()]
    
    def get_project_proposal(self, proposal_id: str) -> Optional[ProjectProposal]:
        """Get a single project proposal by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_project_proposal(row)
            return None
    
    def _row_to_project_proposal(self, row: sqlite3.Row) -> ProjectProposal:
        """Convert a database row to ProjectProposal."""
        return ProjectProposal(
            id=row['id'],
            title=row['title'],
            hunter_pitch=row['hunter_pitch'],
            hunter_rating=row['hunter_rating'],
            market_size=row['market_size'],
            max_revenue_estimate=row['max_revenue_estimate'],
            critic_evaluation=row['critic_evaluation'],
            critic_rating=row['critic_rating'],
            cons=row['cons'],
            differentiation=row['differentiation'],
            spec_path=row['spec_path'],
            effort_estimate=row['effort_estimate'],
            status=row['status'],
            submitted_by=row['submitted_by'],
            reviewer_notes=row['reviewer_notes'],
            created_at=row['created_at'],
            reviewed_at=row['reviewed_at']
        )
    
    def approve_project_proposal(self, proposal_id: str, notes: Optional[str] = None) -> bool:
        """
        Human approves a project proposal for building.
        
        Creates a build_product task for the Builder agent.
        
        Args:
            proposal_id: Project proposal ID
            notes: Optional reviewer notes
            
        Returns:
            True if approved successfully
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE project_proposals 
                SET status = 'approved', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
            """, (notes, now, proposal_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                # Get proposal details
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)).fetchone()
                if row:
                    proposal = self._row_to_project_proposal(row)
                    
                    self.post_discussion(
                        author="human",
                        topic="projects",
                        content=f"✅ PROJECT APPROVED: {proposal.title} - Builder will start working on this!"
                    )
                    
                    # Create build_product task for Builder
                    self.create_task(
                        task_type="build_product",
                        priority=8,
                        payload={
                            "project_id": proposal_id,
                            "title": proposal.title,
                            "spec_path": proposal.spec_path,
                            "effort_estimate": proposal.effort_estimate,
                            "max_revenue": proposal.max_revenue_estimate,
                            "differentiation": proposal.differentiation
                        },
                        created_by="human"
                    )
                
                logger.info(f"[PROJECT] Human approved project: {proposal_id}")
                return True
            return False
    
    def reject_project_proposal(self, proposal_id: str, reason: str) -> bool:
        """
        Human rejects a project proposal - will NOT be built.
        
        Args:
            proposal_id: Project proposal ID
            reason: Why it was rejected
            
        Returns:
            True if rejected successfully
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE project_proposals 
                SET status = 'rejected', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ? AND status IN ('pending', 'deferred')
            """, (reason, now, proposal_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)).fetchone()
                if row:
                    self.post_discussion(
                        author="human",
                        topic="projects",
                        content=f"❌ PROJECT REJECTED: {row['title']} - Reason: {reason}"
                    )
                
                logger.info(f"[PROJECT] Human rejected project: {proposal_id} - {reason}")
                return True
            return False
    
    def defer_project_proposal(self, proposal_id: str, notes: Optional[str] = None) -> bool:
        """
        Human defers a project proposal to backlog for later review.
        
        Args:
            proposal_id: Project proposal ID
            notes: Optional notes about why deferred
            
        Returns:
            True if deferred successfully
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE project_proposals 
                SET status = 'deferred', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
            """, (notes, now, proposal_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)).fetchone()
                if row:
                    self.post_discussion(
                        author="human",
                        topic="projects",
                        content=f"⏸️ PROJECT DEFERRED: {row['title']} - Moved to backlog for later review"
                    )
                
                logger.info(f"[PROJECT] Human deferred project: {proposal_id}")
                return True
            return False
    
    def get_project_proposal_stats(self) -> Dict[str, int]:
        """Get count of project proposals by status."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM project_proposals 
                GROUP BY status
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}
    
    # =========================================================================
    # Token Usage Tracking
    # =========================================================================
    
    def record_token_usage(
        self,
        agent_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        session_id: Optional[str] = None,
        cost_usd: float = 0.0
    ) -> None:
        """Record token usage for an agent session."""
        total_tokens = input_tokens + output_tokens
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO token_usage 
                (agent_id, session_id, input_tokens, output_tokens, total_tokens, cost_usd, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (agent_id, session_id, input_tokens, output_tokens, total_tokens, cost_usd, now))
            
            # Also update agent_status
            conn.execute("""
                UPDATE agent_status 
                SET tokens_used = tokens_used + ?
                WHERE agent_id = ?
            """, (total_tokens, agent_id))
            conn.commit()
        
        logger.info(f"[TOKENS] {agent_id}: +{total_tokens} tokens (in:{input_tokens}, out:{output_tokens})")
    
    def get_token_usage_today(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage for today, optionally filtered by agent."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        with sqlite3.connect(self.db_path) as conn:
            if agent_id:
                cursor = conn.execute("""
                    SELECT 
                        SUM(input_tokens) as input_tokens,
                        SUM(output_tokens) as output_tokens,
                        SUM(total_tokens) as total_tokens,
                        SUM(cost_usd) as cost_usd,
                        COUNT(*) as sessions
                    FROM token_usage 
                    WHERE agent_id = ? AND recorded_at LIKE ?
                """, (agent_id, f"{today}%"))
            else:
                cursor = conn.execute("""
                    SELECT 
                        agent_id,
                        SUM(input_tokens) as input_tokens,
                        SUM(output_tokens) as output_tokens,
                        SUM(total_tokens) as total_tokens,
                        SUM(cost_usd) as cost_usd,
                        COUNT(*) as sessions
                    FROM token_usage 
                    WHERE recorded_at LIKE ?
                    GROUP BY agent_id
                """, (f"{today}%",))
            
            if agent_id:
                row = cursor.fetchone()
                if row:
                    return {
                        "agent_id": agent_id,
                        "input_tokens": row[0] or 0,
                        "output_tokens": row[1] or 0,
                        "total_tokens": row[2] or 0,
                        "cost_usd": row[3] or 0.0,
                        "sessions": row[4] or 0
                    }
                return {"agent_id": agent_id, "input_tokens": 0, "output_tokens": 0, 
                        "total_tokens": 0, "cost_usd": 0.0, "sessions": 0}
            else:
                results = {}
                for row in cursor.fetchall():
                    results[row[0]] = {
                        "input_tokens": row[1] or 0,
                        "output_tokens": row[2] or 0,
                        "total_tokens": row[3] or 0,
                        "cost_usd": row[4] or 0.0,
                        "sessions": row[5] or 0
                    }
                return results
    
    def get_token_usage_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get token usage summary for the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Per-agent totals
            cursor = conn.execute("""
                SELECT 
                    agent_id,
                    SUM(total_tokens) as total,
                    SUM(cost_usd) as cost
                FROM token_usage 
                WHERE recorded_at >= ?
                GROUP BY agent_id
            """, (cutoff,))
            
            by_agent = {row[0]: {"tokens": row[1], "cost": row[2]} for row in cursor.fetchall()}
            
            # Daily totals
            cursor = conn.execute("""
                SELECT 
                    DATE(recorded_at) as day,
                    SUM(total_tokens) as total
                FROM token_usage 
                WHERE recorded_at >= ?
                GROUP BY DATE(recorded_at)
                ORDER BY day
            """, (cutoff,))
            
            by_day = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Grand total
            cursor = conn.execute("""
                SELECT SUM(total_tokens), SUM(cost_usd)
                FROM token_usage WHERE recorded_at >= ?
            """, (cutoff,))
            row = cursor.fetchone()
            
            return {
                "period_days": days,
                "total_tokens": row[0] or 0,
                "total_cost_usd": row[1] or 0.0,
                "by_agent": by_agent,
                "by_day": by_day
            }


# Singleton instance for easy import
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator(
    db_path: str = "/auto-dev/data/orchestrator.db",
    redis_url: Optional[str] = None
) -> Orchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(db_path=db_path, redis_url=redis_url)
    return _orchestrator
