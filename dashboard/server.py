#!/usr/bin/env python3
"""
Auto-Dev Dashboard Server
=========================

Real-time monitoring dashboard for the autonomous income agent.
Shows activity streams, income tracking, token usage, and memory stats.
"""

import os
import sys
import subprocess
import signal
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json
import sqlite3
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yaml
import psutil

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from watcher.orchestrator_pg import get_orchestrator

# Import repo management router
from dashboard.repos import router as repos_router, set_orchestrator as set_repos_orchestrator

app = FastAPI(title="Auto-Dev Dashboard", version="2.0.0")

# Register routers
app.include_router(repos_router)


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/load balancer."""
    return {"status": "healthy", "service": "dashboard", "version": "2.0.0"}


# ============================================================================
# ADMIN/MIGRATION ENDPOINTS (temporary)
# ============================================================================

@app.post("/api/admin/run-migrations")
async def run_migrations():
    """Run database migrations to fix schema issues."""
    if not HAS_PSYCOPG2:
        return {"error": "PostgreSQL not available"}

    conn = get_postgres_db()
    if not conn:
        return {"error": "Could not connect to PostgreSQL"}

    results = []
    try:
        cursor = conn.cursor()
        migrations = [
            ("Add claimed_at column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP"),
            ("Add needs_approval column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS needs_approval INTEGER DEFAULT 0"),
            ("Add approval_status column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approval_status TEXT"),
            ("Add approved_by column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_by TEXT"),
            ("Add approved_at column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP"),
            ("Add rejection_reason column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS rejection_reason TEXT"),
            ("Add parent_task_id column", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id UUID"),
            ("Drop old status constraint", "ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check"),
            ("Add new status constraint", "ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN ('pending', 'claimed', 'in_progress', 'completed', 'failed', 'cancelled'))"),
            # Repos table migrations
            ("Add provider column to repos", "ALTER TABLE repos ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'gitlab'"),
        ]
        for name, sql in migrations:
            try:
                cursor.execute(sql)
                conn.commit()
                results.append({"migration": name, "status": "success"})
            except Exception as e:
                conn.rollback()
                results.append({"migration": name, "status": "failed", "error": str(e)})

        return {"status": "completed", "results": results}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()

# ============================================================================
# AUTONOMY & APPROVAL CONFIGURATION API
# ============================================================================

@app.get("/api/config/autonomy")
async def get_autonomy_config():
    """Get current autonomy and approval gate settings."""
    cfg = load_config()
    autonomy = cfg.get('autonomy', {})
    return {
        "default_mode": autonomy.get('default_mode', 'guided'),
        "approval_gates": autonomy.get('approval_gates', {
            "issue_creation": True,
            "spec_approval": True,
            "merge_approval": True,
            "deploy_approval": False
        }),
        "auto_approve_thresholds": autonomy.get('auto_approve_thresholds', {}),
        "safety_limits": autonomy.get('safety_limits', {})
    }


@app.put("/api/config/autonomy")
async def update_autonomy_config(request: Request):
    """Update autonomy and approval gate settings."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Invalid JSON in request: {e}")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    cfg = load_config()
    if 'autonomy' not in cfg:
        cfg['autonomy'] = {}

    # Update only the fields that were provided
    if 'default_mode' in body:
        cfg['autonomy']['default_mode'] = body['default_mode']

    if 'approval_gates' in body:
        if 'approval_gates' not in cfg['autonomy']:
            cfg['autonomy']['approval_gates'] = {}
        cfg['autonomy']['approval_gates'].update(body['approval_gates'])

    if 'auto_approve_thresholds' in body:
        if 'auto_approve_thresholds' not in cfg['autonomy']:
            cfg['autonomy']['auto_approve_thresholds'] = {}
        cfg['autonomy']['auto_approve_thresholds'].update(body['auto_approve_thresholds'])

    if 'safety_limits' in body:
        if 'safety_limits' not in cfg['autonomy']:
            cfg['autonomy']['safety_limits'] = {}
        cfg['autonomy']['safety_limits'].update(body['safety_limits'])

    save_config(cfg)
    return {"success": True, "autonomy": cfg['autonomy']}


# ============================================================================
# PENDING APPROVALS API
# ============================================================================

@app.get("/api/pending-approvals")
async def get_pending_approvals():
    """Get all items pending human approval (tasks, MRs, deployments)."""
    conn = get_postgres_db()
    if not conn:
        return {"approvals": [], "stats": {"tasks": 0, "merges": 0, "deploys": 0, "specs": 0, "issues": 0, "total": 0}}

    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get tasks pending approval from PostgreSQL
        cursor.execute("""
            SELECT id::text, task_type as type, priority, payload, assigned_agent as assigned_to,
                   created_by, created_at, approval_type, repo_id::text
            FROM tasks
            WHERE needs_approval = 1 AND approval_status = 'pending'
            ORDER BY priority DESC, created_at ASC
        """)
        tasks = []
        for row in cursor.fetchall():
            task = dict(row)
            task['item_type'] = 'task'
            task['created_at'] = task['created_at'].isoformat() if task.get('created_at') else None
            tasks.append(task)

        # Get from approvals table as well
        dev_approvals = []
        try:
            cursor.execute("""
                SELECT id::text, repo_id::text, approval_type, payload as context,
                       status, created_at
                FROM approvals
                WHERE status = 'pending'
                ORDER BY created_at ASC
            """)
            for row in cursor.fetchall():
                approval = dict(row)
                approval['item_type'] = 'approval'
                approval['created_at'] = approval['created_at'].isoformat() if approval.get('created_at') else None
                dev_approvals.append(approval)
        except Exception as e:
            print(f"Error fetching approvals: {e}")

        # Combine and categorize
        all_approvals = tasks + dev_approvals

        # Count by type
        stats = {
            "tasks": len([a for a in all_approvals if a.get('approval_type') == 'task' or (a.get('item_type') == 'task' and not a.get('approval_type'))]),
            "merges": len([a for a in all_approvals if a.get('approval_type') in ('merge', 'mr', 'merge_request')]),
            "deploys": len([a for a in all_approvals if a.get('approval_type') in ('deploy', 'deployment')]),
            "specs": len([a for a in all_approvals if a.get('approval_type') in ('spec', 'specification')]),
            "issues": len([a for a in all_approvals if a.get('approval_type') in ('issue', 'issue_creation')]),
            "total": len(all_approvals)
        }

        return {"approvals": all_approvals, "stats": stats}
    except Exception as e:
        return {"approvals": [], "stats": {"tasks": 0, "merges": 0, "deploys": 0, "specs": 0, "issues": 0, "total": 0}, "error": str(e)}
    finally:
        conn.close()


@app.post("/api/pending-approvals/{item_id}/approve")
async def approve_pending_item(item_id: str, request: Request):
    """Approve a pending item (task, MR, or deployment)."""
    try:
        body = await request.json()
        notes = body.get('notes', '')
    except (json.JSONDecodeError, ValueError, AttributeError):
        notes = ''

    conn = get_postgres_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)

    now = datetime.now()

    try:
        cursor = conn.cursor()

        # Try to update in tasks table first
        cursor.execute("""
            UPDATE tasks
            SET approval_status = 'approved', approved_by = 'human', approved_at = %s
            WHERE id::text = %s AND needs_approval = 1 AND approval_status = 'pending'
        """, (now, item_id))

        if cursor.rowcount > 0:
            conn.commit()
            return {"success": True, "message": "Task approved", "id": item_id}

        # Try approvals table
        cursor.execute("""
            UPDATE approvals
            SET status = 'approved', review_comment = %s, reviewed_at = %s
            WHERE id::text = %s AND status = 'pending'
        """, (notes, now, item_id))

        if cursor.rowcount > 0:
            conn.commit()
            return {"success": True, "message": "Approval granted", "id": item_id}

        return JSONResponse({"error": "Item not found or already processed"}, status_code=404)
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/pending-approvals/{item_id}/reject")
async def reject_pending_item(item_id: str, request: Request):
    """Reject a pending item (task, MR, or deployment)."""
    try:
        body = await request.json()
        reason = body.get('reason', 'Rejected by human reviewer')
    except (json.JSONDecodeError, ValueError, AttributeError):
        reason = 'Rejected by human reviewer'

    conn = get_postgres_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)

    now = datetime.now()

    try:
        cursor = conn.cursor()

        # Try to update in tasks table first
        cursor.execute("""
            UPDATE tasks
            SET approval_status = 'rejected', approved_by = 'human', approved_at = %s,
                rejection_reason = %s, status = 'cancelled'
            WHERE id::text = %s AND needs_approval = 1 AND approval_status = 'pending'
        """, (now, reason, item_id))

        if cursor.rowcount > 0:
            conn.commit()
            return {"success": True, "message": "Task rejected", "id": item_id}

        # Try approvals table
        cursor.execute("""
            UPDATE approvals
            SET status = 'rejected', review_comment = %s, reviewed_at = %s
            WHERE id::text = %s AND status = 'pending'
        """, (reason, now, item_id))

        if cursor.rowcount > 0:
            conn.commit()
            return {"success": True, "message": "Approval rejected", "id": item_id}

        return JSONResponse({"error": "Item not found or already processed"}, status_code=404)
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


# Configuration
CONFIG_PATH = Path("/auto-dev/config/settings.yaml")
DB_PATH = Path("/auto-dev/data/memory/short_term.db")
ORCHESTRATOR_DB_PATH = Path("/auto-dev/data/orchestrator.db")
SCREENSHOTS_PATH = Path("/auto-dev/data/screenshots")
REACT_BUILD_PATH = Path(__file__).parent / "frontend" / "dist"

# Agent types
AGENT_TYPES = ['pm', 'architect', 'builder', 'reviewer', 'tester', 'security', 'devops', 'bug_finder']

# Load config
def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    return {}

def save_config(updated: Dict[str, Any]) -> None:
    """Persist configuration to YAML file."""
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        yaml.safe_dump(updated, f, sort_keys=False)
    tmp_path.replace(CONFIG_PATH)

config = load_config()

# Initialize orchestrator for repos module on startup
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    try:
        orchestrator = get_orchestrator(db_path=str(ORCHESTRATOR_DB_PATH))
        set_repos_orchestrator(orchestrator)
    except Exception as e:
        print(f"Warning: Could not initialize orchestrator: {e}")

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except (ConnectionError, RuntimeError):
                # Connection closed or websocket error - will be cleaned up later
                pass

manager = ConnectionManager()


def get_db_connection():
    """Get SQLite database connection."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_recent_memories(limit: int = 50) -> List[Dict]:
    """Get recent memory entries."""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.execute(
            "SELECT * FROM memories ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_token_stats(days: int = 7) -> Dict[str, Any]:
    """Get token usage statistics from orchestrator's token_usage table."""
    try:
        orchestrator = get_orchestrator(
            db_path="/auto-dev/data/orchestrator.db"
        )
        summary = orchestrator.get_token_usage_summary(days)
        today_usage = orchestrator.get_token_usage_today()
        
        return {
            "total": summary.get("total_tokens", 0),
            "total_cost": summary.get("total_cost_usd", 0),
            "by_agent": summary.get("by_agent", {}),
            "by_day": summary.get("by_day", {}),
            "daily_average": summary.get("total_tokens", 0) / max(days, 1),
            "today": today_usage
        }
    except Exception as e:
        logger.error(f"Failed to get token stats: {e}")
        return {"total": 0, "by_day": {}, "by_agent": {}, "daily_average": 0, "today": {}}


def get_screenshots(limit: int = 20) -> List[Dict]:
    """Get recent screenshots."""
    if not SCREENSHOTS_PATH.exists():
        return []
    
    screenshots = []
    for png in sorted(SCREENSHOTS_PATH.glob("*.png"), reverse=True)[:limit]:
        meta_path = png.with_suffix('.meta')
        meta = {}
        if meta_path.exists():
            try:
                meta = dict(line.split(': ', 1) for line in meta_path.read_text().strip().split('\n'))
            except (OSError, ValueError):
                pass
        
        screenshots.append({
            "filename": png.name,
            "path": f"/screenshots/{png.name}",
            "timestamp": png.stat().st_mtime,
            "meta": meta
        })
    
    return screenshots


# Mount static files for screenshots
if SCREENSHOTS_PATH.exists():
    app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_PATH)), name="screenshots")

# Mount React build assets (must be after API routes but before catch-all)
if REACT_BUILD_PATH.exists():
    app.mount("/assets", StaticFiles(directory=str(REACT_BUILD_PATH / "assets")), name="react-assets")


@app.get("/")
async def dashboard():
    """Serve the React app."""
    react_index = REACT_BUILD_PATH / "index.html"
    if react_index.exists():
        return FileResponse(react_index)
    # Fallback to legacy HTML if React build not available
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/api/status")
async def get_status():
    """Get current agent status."""
    # Try to read watcher status from a status file
    status_file = Path("/auto-dev/data/watcher_status.json")
    if status_file.exists():
        try:
            return json.loads(status_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    
    return {
        "is_running": False,
        "current_session": None,
        "total_sessions": 0,
        "message": "Status file not found"
    }


@app.get("/api/memories")
async def api_memories(limit: int = 50):
    """Get recent memories."""
    return {"memories": get_recent_memories(limit)}


@app.get("/api/tokens")
async def api_tokens(days: int = 7):
    """Get token usage stats."""
    return get_token_stats(days)


@app.get("/api/screenshots")
async def api_screenshots(limit: int = 20):
    """Get recent screenshots."""
    return {"screenshots": get_screenshots(limit)}


@app.get("/api/stats")
async def api_stats():
    """Get aggregated statistics."""
    tokens = get_token_stats(7)
    memories = get_recent_memories(10)

    return {
        "tokens": {
            "total_7d": tokens['total'],
            "cost_7d": tokens.get('total_cost', 0),
            "daily_average": tokens['daily_average']
        },
        "recent_activity": memories[:5]
    }


def get_agent_processes() -> List[Dict]:
    """Get info about running agent processes."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_percent', 'cpu_percent']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'agent_runner.py' in cmdline or ('claude' in cmdline.lower() and 'code' not in cmdline.lower()):
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cmdline': cmdline[:100],
                    'uptime': datetime.now().timestamp() - proc.info['create_time'],
                    'memory_percent': round(proc.info['memory_percent'], 1),
                    'cpu_percent': proc.info['cpu_percent']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes


@app.get("/api/agents")
async def api_agents():
    """Get info about running agents."""
    processes = get_agent_processes()
    watcher_running = any('agent_runner.py' in p.get('cmdline', '') for p in processes)
    claude_processes = [p for p in processes if 'claude' in p.get('cmdline', '').lower()]
    
    return {
        "watcher_running": watcher_running,
        "claude_instances": len(claude_processes),
        "processes": processes,
        "max_parallel": 1,  # Current design is sequential
        "mode": "sequential"
    }


@app.post("/api/agent/start")
async def start_agent():
    """Enable all agents via Redis (instant soft-pause control)."""
    # Always use Redis for instant enable/disable (agents run continuously in KaaS)
    r = get_redis()
    if not r:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        # Enable all agents
        for agent_type in AGENT_TYPES:
            r.set(f"agent:{agent_type}:enabled", "1")
        # Notify agent runners
        r.publish("agent:control", json.dumps({"action": "start_all"}))
        return {"status": "started", "message": f"All {len(AGENT_TYPES)} agents enabled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/stop")
async def stop_agent():
    """Disable all agents via Redis (instant soft-pause control)."""
    # Always use Redis for instant enable/disable (agents run continuously in KaaS)
    r = get_redis()
    if not r:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        # Disable all agents
        for agent_type in AGENT_TYPES:
            r.set(f"agent:{agent_type}:enabled", "0")
        # Notify agent runners
        r.publish("agent:control", json.dumps({"action": "stop_all"}))
        return {"status": "stopped", "message": f"All {len(AGENT_TYPES)} agents disabled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/start/{agent_type}")
async def start_specific_agent(agent_type: str):
    """Enable a specific agent type via Redis (instant soft-pause control)."""
    if agent_type not in AGENT_TYPES:
        return {"status": "error", "message": f"Unknown agent type: {agent_type}"}

    # Always use Redis for instant enable/disable (agents run continuously in KaaS)
    r = get_redis()
    if not r:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        # Set agent as enabled in Redis
        r.set(f"agent:{agent_type}:enabled", "1")
        # Publish message to notify agent runner immediately
        r.publish("agent:control", json.dumps({"action": "start", "agent": agent_type}))
        return {"status": "started", "message": f"{agent_type} agent enabled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/stop/{agent_type}")
async def stop_specific_agent(agent_type: str):
    """Disable a specific agent type via Redis (instant soft-pause control)."""
    if agent_type not in AGENT_TYPES:
        return {"status": "error", "message": f"Unknown agent type: {agent_type}"}

    # Always use Redis for instant enable/disable (agents run continuously in KaaS)
    r = get_redis()
    if not r:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        # Set agent as disabled in Redis
        r.set(f"agent:{agent_type}:enabled", "0")
        # Publish message to notify agent runner immediately
        r.publish("agent:control", json.dumps({"action": "stop", "agent": agent_type}))
        return {"status": "stopped", "message": f"{agent_type} agent disabled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class DatabaseWrapper:
    """Wrapper to provide consistent interface for SQLite and PostgreSQL."""

    def __init__(self, conn, is_postgres=False):
        self._conn = conn
        self._is_postgres = is_postgres
        self._cursor = None

    def cursor(self):
        """Return self to allow cursor().execute() pattern."""
        return self

    def execute(self, query, params=None):
        """Execute query and return cursor-like object."""
        # Convert SQLite ? placeholders to PostgreSQL %s
        if self._is_postgres:
            query = query.replace('?', '%s')

        if self._is_postgres:
            self._cursor = self._conn.cursor()
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            return self._cursor
        else:
            if params:
                return self._conn.execute(query, params)
            else:
                return self._conn.execute(query)

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._cursor:
            self._cursor.close()
        self._conn.close()


def get_orchestrator_db():
    """Get orchestrator database connection (PostgreSQL preferred, SQLite fallback)."""
    # Try PostgreSQL first
    pg_conn = get_postgres_db()
    if pg_conn:
        return DatabaseWrapper(pg_conn, is_postgres=True)

    # Fall back to SQLite
    if not ORCHESTRATOR_DB_PATH.exists():
        return None
    conn = sqlite3.connect(ORCHESTRATOR_DB_PATH)
    conn.row_factory = sqlite3.Row
    return DatabaseWrapper(conn, is_postgres=False)


def get_postgres_db():
    """Get PostgreSQL database connection."""
    if not HAS_PSYCOPG2:
        return None

    # Check for individual connection params (Docker environment)
    db_host = os.environ.get('DB_HOST')
    db_user = os.environ.get('DB_USER')
    db_password = os.environ.get('DB_PASSWORD')
    db_name = os.environ.get('DB_NAME')

    if db_host and db_user and db_name:
        try:
            conn = psycopg2.connect(
                host=db_host,
                user=db_user,
                password=db_password or '',
                dbname=db_name,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            return conn
        except Exception as e:
            print(f"PostgreSQL connection error: {e}")

    # Check for DATABASE_URL
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        try:
            conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
            return conn
        except Exception as e:
            print(f"PostgreSQL connection error: {e}")

    return None


def get_redis():
    """Get Redis connection for agent control."""
    if not HAS_REDIS:
        return None
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    try:
        return redis.from_url(redis_url)
    except Exception as e:
        print(f"Redis connection error: {e}")
        return None


def init_postgres_schema():
    """Initialize PostgreSQL schema if tables don't exist."""
    if not HAS_PSYCOPG2:
        print("PostgreSQL driver not available, skipping schema init")
        return

    conn = get_postgres_db()
    if not conn:
        print("No PostgreSQL connection available, skipping schema init")
        return

    try:
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'tasks'
            ) as table_exists
        """)
        result = cursor.fetchone()
        tables_exist = result.get('table_exists', False) if isinstance(result, dict) else result[0]

        if tables_exist:
            print("Database schema exists, checking for missing columns...")
            # Add missing columns and fix constraints
            migrations = [
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS needs_approval INTEGER DEFAULT 0",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approval_status TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_by TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
                # Fix status check constraint to include 'claimed'
                "ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check",
                "ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN ('pending', 'claimed', 'in_progress', 'completed', 'failed', 'cancelled'))",
            ]
            for migration in migrations:
                try:
                    cursor.execute(migration)
                    conn.commit()
                except Exception as e:
                    print(f"Migration note: {e}")
                    conn.rollback()
            print("Schema migrations complete")
            cursor.close()
            conn.close()
            return

        print("Initializing database schema...")

        # Execute each statement separately for better error handling
        statements = [
            'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',

            """CREATE TABLE IF NOT EXISTS repos (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                provider TEXT DEFAULT 'gitlab' CHECK (provider IN ('gitlab', 'github')),
                gitlab_url TEXT NOT NULL,
                gitlab_project_id TEXT NOT NULL,
                default_branch TEXT DEFAULT 'main',
                autonomy_mode TEXT DEFAULT 'guided' CHECK (autonomy_mode IN ('full', 'guided')),
                settings JSONB DEFAULT '{}',
                webhook_secret_hash TEXT,
                token_ssm_path TEXT,
                mr_prefix TEXT DEFAULT '[AUTO-DEV]',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                active BOOLEAN DEFAULT true
            )""",

            # Migration: Add provider column to existing repos tables
            "ALTER TABLE repos ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'gitlab'",

            """CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
                parent_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
                task_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'in_progress', 'completed', 'failed', 'cancelled')),
                priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
                payload JSONB DEFAULT '{}',
                result JSONB,
                error TEXT,
                created_by TEXT,
                assigned_to TEXT,
                assigned_agent TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                claimed_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                needs_approval INTEGER DEFAULT 0,
                approval_status TEXT,
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT
            )""",

            """CREATE TABLE IF NOT EXISTS approvals (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
                task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
                approval_type TEXT NOT NULL CHECK (approval_type IN ('spec', 'merge', 'issue_creation', 'deploy')),
                status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                payload JSONB DEFAULT '{}',
                reviewer TEXT,
                review_comment TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                auto_approved BOOLEAN DEFAULT false,
                auto_approve_reason TEXT
            )""",

            """CREATE TABLE IF NOT EXISTS agent_status (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                agent_type TEXT NOT NULL,
                repo_id UUID REFERENCES repos(id) ON DELETE SET NULL,
                status TEXT DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'error', 'stopped')),
                current_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
                last_heartbeat TIMESTAMP DEFAULT NOW(),
                session_started TIMESTAMP,
                metadata JSONB DEFAULT '{}'
            )""",

            """CREATE TABLE IF NOT EXISTS reflections (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
                task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
                agent_type TEXT NOT NULL,
                reflection_type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.5,
                tags TEXT[],
                created_at TIMESTAMP DEFAULT NOW()
            )""",

            """CREATE TABLE IF NOT EXISTS learnings (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
                agent_type TEXT NOT NULL,
                category TEXT NOT NULL,
                insight TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.5,
                usage_count INTEGER DEFAULT 0,
                last_used TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                active BOOLEAN DEFAULT true
            )""",

            "CREATE INDEX IF NOT EXISTS idx_tasks_repo_status ON tasks(repo_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to)",
            "CREATE INDEX IF NOT EXISTS idx_approvals_repo_status ON approvals(repo_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status) WHERE status = 'pending'",
            "CREATE INDEX IF NOT EXISTS idx_approvals_created_at ON approvals(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_agent_status_type ON agent_status(agent_type)",
            "CREATE INDEX IF NOT EXISTS idx_agent_status_heartbeat ON agent_status(last_heartbeat DESC)",
            "CREATE INDEX IF NOT EXISTS idx_reflections_repo_agent ON reflections(repo_id, agent_type)",
            "CREATE INDEX IF NOT EXISTS idx_learnings_repo_agent ON learnings(repo_id, agent_type) WHERE active = true",
        ]

        for stmt in statements:
            try:
                cursor.execute(stmt)
            except Exception as e:
                print(f"Warning: Statement failed (may already exist): {e}")
                conn.rollback()
                cursor = conn.cursor()  # Get a fresh cursor after rollback

        conn.commit()
        print("Database schema initialized successfully")

    except Exception as e:
        print(f"Error initializing database schema: {e}")
        try:
            conn.rollback()
        except:
            pass
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass


# Schema initialization is now handled by orchestrator_pg.py
# init_postgres_schema() - disabled to avoid UUID/TEXT type conflicts


@app.get("/api/tasks")
async def get_tasks(status: str = None, limit: int = 50):
    """Get tasks from the queue."""
    conn = get_orchestrator_db()
    if not conn:
        return {"tasks": [], "stats": {}}
    
    try:
        if status:
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM tasks ORDER BY priority DESC, created_at DESC LIMIT ?",
                (limit,)
            )
        
        tasks = []
        for row in cursor.fetchall():
            task = dict(row)
            task['payload'] = parse_json_field(task['payload']) or {}
            task['result'] = parse_json_field(task.get('result'))
            tasks.append(task)
        
        # Get stats
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count FROM tasks GROUP BY status
        """)
        stats = {row['status']: row['count'] for row in cursor.fetchall()}
        
        return {"tasks": tasks, "stats": stats}
    finally:
        conn.close()


@app.post("/api/tasks")
async def create_task(request: Request):
    """Create a new task."""
    data = await request.json()
    conn = get_orchestrator_db()
    if not conn:
        return {"status": "error", "message": "Orchestrator database not available"}

    try:
        import uuid
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Extract repo_id and assigned_to from the request
        repo_id = data.get('repo_id')
        parent_task_id = data.get('parent_task_id')
        assigned_to = data.get('to')  # Agent to assign task to

        # Include repo_id in payload if provided
        payload = data.get('payload', {})
        if repo_id:
            payload['repo_id'] = repo_id

        conn.execute("""
            INSERT INTO tasks (id, task_type, priority, payload, status, created_by, created_at, assigned_to, repo_id, parent_task_id)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        """, (
            task_id,
            data.get('type', 'build_product'),
            data.get('priority', 5),
            json.dumps(payload),
            data.get('created_by', 'dashboard'),
            now,
            assigned_to,
            repo_id,
            parent_task_id
        ))
        conn.commit()

        return {"status": "created", "task_id": task_id, "repo_id": repo_id, "assigned_to": assigned_to}
    finally:
        conn.close()


@app.post("/api/tasks/reset-stale")
async def reset_stale_tasks(hours: int = 1):
    """Reset tasks that have been claimed for too long back to pending."""
    conn = get_orchestrator_db()
    if not conn:
        return {"status": "error", "message": "Database not available"}

    try:
        # Find tasks claimed more than X hours ago
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        cursor = conn.execute("""
            SELECT id, task_type, assigned_to, claimed_at
            FROM tasks
            WHERE status = 'claimed' AND claimed_at < ?
        """, (cutoff,))
        stale_tasks = cursor.fetchall()

        if not stale_tasks:
            return {"status": "ok", "reset_count": 0, "message": "No stale tasks found"}

        # Reset them to pending
        task_ids = [t[0] if isinstance(t, tuple) else t['id'] for t in stale_tasks]
        placeholders = ','.join(['?' for _ in task_ids])
        conn.execute(f"""
            UPDATE tasks
            SET status = 'pending', claimed_at = NULL, assigned_to = NULL
            WHERE id IN ({placeholders})
        """, task_ids)
        conn.commit()

        return {
            "status": "ok",
            "reset_count": len(task_ids),
            "task_ids": task_ids
        }
    finally:
        conn.close()


@app.get("/api/agent-tasks")
async def get_agent_tasks(agent: str = None, status: str = None, limit: int = 100):
    """Get tasks grouped by agent with optional filtering."""
    conn = get_orchestrator_db()
    if not conn:
        return {"agents": {}, "summary": {}}
    
    try:
        # Build query based on filters
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if agent:
            query += " AND assigned_to = ?"
            params.append(agent)
        
        if status:
            if status == "closed":
                query += " AND status IN ('completed', 'cancelled', 'failed')"
            elif status != "all":
                query += " AND status = ?"
                params.append(status)
        
        query += " ORDER BY completed_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor = conn.execute(query, params)
        
        # Group tasks by agent
        agents = {}
        for row in cursor.fetchall():
            task = dict(row)
            task['payload'] = parse_json_field(task['payload']) or {}
            task['result'] = parse_json_field(task.get('result'))
            
            agent_id = task.get('assigned_to') or 'unassigned'
            if agent_id not in agents:
                agents[agent_id] = []
            agents[agent_id].append(task)
        
        # Get summary stats per agent
        cursor = conn.execute("""
            SELECT 
                COALESCE(assigned_to, 'unassigned') as agent,
                status,
                COUNT(*) as count
            FROM tasks
            GROUP BY assigned_to, status
        """)
        
        summary = {}
        for row in cursor.fetchall():
            agent_id = row['agent']
            if agent_id not in summary:
                summary[agent_id] = {'total': 0, 'completed': 0, 'pending': 0, 'failed': 0, 'claimed': 0}
            summary[agent_id][row['status']] = row['count']
            summary[agent_id]['total'] += row['count']
        
        return {"agents": agents, "summary": summary}
    finally:
        conn.close()


# React app routes - serve index.html for client-side routing
@app.get("/agents")
@app.get("/repos")
@app.get("/tasks")
@app.get("/approvals")
@app.get("/learnings")
@app.get("/settings")
@app.get("/projects")
async def react_routes():
    """Serve React app for all frontend routes."""
    react_index = REACT_BUILD_PATH / "index.html"
    if react_index.exists():
        return FileResponse(react_index)
    # Fallback to legacy HTML
    return HTMLResponse(content=DASHBOARD_HTML)


# ==================== Task Outcomes (Learning System) ====================

@app.get("/api/outcomes")
async def get_outcomes(
    agent: str = None,
    task_type: str = None,
    repo_id: str = None,
    outcome: str = None,
    limit: int = 50
):
    """Get recent task outcomes with optional filters."""
    conn = get_orchestrator_db()
    if not conn:
        return {"outcomes": [], "error": "No database connection"}

    try:
        # Build query
        query = "SELECT * FROM task_outcomes WHERE 1=1"
        params = []

        if agent:
            query += " AND agent_id = ?"
            params.append(agent)
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        if repo_id:
            query += " AND repo_id = ?"
            params.append(repo_id)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        outcomes = [dict(row) for row in cursor.fetchall()]

        return {"outcomes": outcomes}
    except Exception as e:
        return {"outcomes": [], "error": str(e)}
    finally:
        conn.close()


@app.get("/api/outcomes/stats")
async def get_outcome_stats(repo_id: str = None, days: int = 30):
    """Get aggregated outcome statistics for the learning dashboard."""
    conn = get_orchestrator_db()
    if not conn:
        return {"by_agent": [], "by_task_type": [], "recent_failures": [], "period_days": days}

    try:
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        where_clause = "created_at >= ?"
        params = [cutoff]

        if repo_id:
            where_clause += " AND repo_id = ?"
            params.append(repo_id)

        # Stats by agent
        cursor = conn.execute(f"""
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
        by_agent = [dict(row) for row in cursor.fetchall()]

        # Stats by task type
        cursor = conn.execute(f"""
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
        by_task_type = [dict(row) for row in cursor.fetchall()]

        # Recent failures
        cursor = conn.execute(f"""
            SELECT agent_id, task_type, error_summary, context_summary, created_at
            FROM task_outcomes
            WHERE {where_clause} AND outcome = 'failure'
            ORDER BY created_at DESC
            LIMIT 10
        """, params)
        recent_failures = [dict(row) for row in cursor.fetchall()]

        return {
            "by_agent": by_agent,
            "by_task_type": by_task_type,
            "recent_failures": recent_failures,
            "period_days": days
        }
    except Exception as e:
        return {"by_agent": [], "by_task_type": [], "recent_failures": [], "period_days": days, "error": str(e)}
    finally:
        conn.close()


# ==================== Reflections API ====================

@app.get("/api/reflections")
async def get_reflections(
    agent_type: str = None,
    task_type: str = None,
    repo_id: str = None,
    limit: int = 50
):
    """Get agent reflections."""
    conn = get_orchestrator_db()
    if not conn:
        return {'reflections': []}

    try:
        conditions = []
        params = []

        if agent_type:
            conditions.append("agent_type = %s")
            params.append(agent_type)
        if task_type:
            conditions.append("reflection_type = %s")
            params.append(task_type)
        if repo_id:
            conditions.append("repo_id = %s")
            params.append(repo_id)

        where = " AND ".join(conditions) if conditions else "1=1"

        cursor = conn.execute(f"""
            SELECT id, agent_type, task_id, reflection_type,
                   content, confidence, tags, created_at
            FROM reflections
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, params + [limit])

        reflections = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            reflections.append({
                'id': str(row_dict['id']),
                'agent_id': row_dict['agent_type'],
                'task_id': str(row_dict['task_id']) if row_dict['task_id'] else None,
                'reflection_type': row_dict['reflection_type'],
                'summary': row_dict['content'],
                'confidence': row_dict['confidence'],
                'tags': row_dict.get('tags') or [],
                'created_at': row_dict['created_at'].isoformat() if hasattr(row_dict['created_at'], 'isoformat') else str(row_dict['created_at'])
            })

        return {'reflections': reflections}
    except Exception as e:
        return {'reflections': [], 'error': str(e)}
    finally:
        conn.close()


@app.get("/api/reflections/stats")
async def get_reflection_stats(days: int = 30):
    """Get reflection statistics."""
    conn = get_orchestrator_db()
    if not conn:
        return {'by_agent': [], 'by_type': [], 'period_days': days}

    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # Count by agent
        cursor = conn.execute("""
            SELECT agent_type, COUNT(*), AVG(confidence)
            FROM reflections
            WHERE created_at > %s
            GROUP BY agent_type
        """, [cutoff])

        by_agent = [
            {'agent_id': r[0], 'count': r[1], 'avg_confidence': float(r[2] or 0)}
            for r in cursor.fetchall()
        ]

        # Count by type
        cursor = conn.execute("""
            SELECT reflection_type, COUNT(*)
            FROM reflections
            WHERE created_at > %s
            GROUP BY reflection_type
        """, [cutoff])

        by_type = [
            {'type': r[0], 'count': r[1]}
            for r in cursor.fetchall()
        ]

        return {'by_agent': by_agent, 'by_type': by_type, 'period_days': days}
    except Exception as e:
        return {'by_agent': [], 'by_type': [], 'period_days': days, 'error': str(e)}
    finally:
        conn.close()


@app.post("/api/reflections")
async def create_reflection(request: Request):
    """Record a new reflection (called by agents)."""
    data = await request.json()
    conn = get_orchestrator_db()
    if not conn:
        return {'error': 'Database unavailable'}

    try:
        cursor = conn.execute("""
            INSERT INTO reflections
            (agent_type, task_id, reflection_type, content, confidence, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data['agent_id'],
            data.get('task_id'),
            data['reflection_type'],
            data['summary'],
            data.get('confidence', 0.5),
            data.get('tags', [])
        ))

        result = cursor.fetchone()
        reflection_id = str(result[0]) if result else None
        conn.commit()

        # Auto-extract learning if high confidence
        if data.get('confidence', 0) >= 0.7 and data.get('learning_content'):
            conn.execute("""
                INSERT INTO learnings
                (agent_type, category, insight, confidence)
                VALUES (%s, %s, %s, %s)
            """, (
                data['agent_id'],
                data.get('category', 'general'),
                data['learning_content'],
                data.get('confidence', 0.5)
            ))
            conn.commit()

        return {'id': reflection_id, 'status': 'created'}
    except Exception as e:
        return {'error': str(e)}
    finally:
        conn.close()


# ==================== Learnings API ====================

@app.get("/api/learnings")
async def get_learnings(
    agent_type: str = None,
    category: str = None,
    validated_only: bool = False,
    limit: int = 50
):
    """Get validated learnings."""
    conn = get_orchestrator_db()
    if not conn:
        return {'learnings': []}

    try:
        conditions = ["active = true"]
        params = []

        if agent_type:
            conditions.append("agent_type = %s")
            params.append(agent_type)
        if category:
            conditions.append("category = %s")
            params.append(category)
        if validated_only:
            conditions.append("usage_count > 0")

        where = " AND ".join(conditions)

        cursor = conn.execute(f"""
            SELECT id, agent_type, category, insight,
                   confidence, usage_count, created_at
            FROM learnings
            WHERE {where}
            ORDER BY usage_count DESC, created_at DESC
            LIMIT %s
        """, params + [limit])

        learnings = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            learnings.append({
                'id': str(row_dict['id']),
                'agent_id': row_dict['agent_type'],
                'category': row_dict['category'],
                'content': row_dict['insight'],
                'confidence': row_dict['confidence'],
                'validation_count': row_dict['usage_count'],
                'created_at': row_dict['created_at'].isoformat() if hasattr(row_dict['created_at'], 'isoformat') else str(row_dict['created_at'])
            })

        return {'learnings': learnings}
    except Exception as e:
        return {'learnings': [], 'error': str(e)}
    finally:
        conn.close()


@app.get("/api/agent-statuses")
async def get_agent_statuses():
    """Get status of all agents (Redis + database)."""
    conn = get_orchestrator_db()
    r = get_redis()
    statuses = {}

    # Initialize with defaults
    for agent_type in AGENT_TYPES:
        statuses[agent_type] = {
            "agent_id": agent_type,
            "status": "offline",
            "enabled": True,  # Default to enabled
            "current_task_id": None,
            "tasks_completed": 0,
            "tokens_used": 0
        }

    # Get enabled state from Redis
    if r:
        try:
            for agent_type in AGENT_TYPES:
                enabled = r.get(f"agent:{agent_type}:enabled")
                # If key doesn't exist, default to enabled (None means enabled)
                statuses[agent_type]["enabled"] = enabled is None or enabled == b"1"
        except Exception as e:
            print(f"Redis error getting agent states: {e}")

    # Get from orchestrator DB if available
    if conn:
        try:
            # Use DatabaseWrapper's execute method
            cursor = conn.execute("SELECT * FROM agent_status")
            for row in cursor.fetchall():
                # Convert row to dict first
                row_dict = dict(row)
                # PostgreSQL uses 'agent_type', SQLite uses 'agent_id'
                agent_id = row_dict.get('agent_type') or row_dict.get('agent_id')
                if agent_id in statuses:
                    row_dict['agent_id'] = agent_id  # Normalize field name
                    # Preserve enabled state from Redis
                    row_dict['enabled'] = statuses[agent_id]['enabled']
                    statuses[agent_id] = row_dict
        finally:
            conn.close()

    # Update status based on enabled state
    for agent_type in AGENT_TYPES:
        if not statuses[agent_type]['enabled']:
            statuses[agent_type]['status'] = 'disabled'

    # Check for global rate limit
    rate_limit_info = None
    rate_limit_file = Path('/auto-dev/data/.rate_limited')
    if rate_limit_file.exists():
        try:
            import json
            data = json.loads(rate_limit_file.read_text())
            reset_time = data.get('reset_time')
            if reset_time:
                from datetime import datetime
                reset_dt = datetime.fromisoformat(reset_time)
                if datetime.utcnow() < reset_dt:
                    rate_limit_info = {
                        'limited': True,
                        'provider': data.get('provider', 'unknown'),
                        'reset_time': reset_time,
                        'set_by': data.get('agent_id'),
                        'remaining_seconds': int((reset_dt - datetime.utcnow()).total_seconds())
                    }
        except Exception:
            pass

    return {"agents": statuses, "rate_limit": rate_limit_info}




@app.get("/api/agent-providers")
async def get_agent_providers():
    """Get configured provider overrides and active provider for agents."""
    config_data = load_config()
    agents_config = config_data.get("agents", {})
    llm_config = config_data.get("llm", {})
    default_provider = llm_config.get("default_provider", "claude")

    providers = []
    for agent_id, agent_cfg in agents_config.items():
        override = agent_cfg.get("provider")
        status_path = Path(f"/auto-dev/data/watcher_status_{agent_id}.json")
        active_provider = None
        if status_path.exists():
            try:
                status_data = json.loads(status_path.read_text())
                active_provider = status_data.get("current_session", {}).get("provider")
            except Exception:
                active_provider = None

        providers.append({
            "agent_id": agent_id,
            "provider_override": override,
            "default_provider": default_provider,
            "active_provider": active_provider
        })

    return {"providers": providers, "default_provider": default_provider}


@app.get("/api/agent-config")
async def get_agent_config():
    """Get agent definitions from settings.yaml for dynamic UI rendering."""
    config_data = load_config()
    agents_config = config_data.get("agents", {})

    # Map agent types to icons
    AGENT_ICONS = {
        "pm": "📋",
        "architect": "📐",
        "builder": "🔨",
        "reviewer": "🔍",
        "tester": "🧪",
        "security": "🛡️",
        "devops": "⚙️",
        "bug_finder": "🐛",
        # Legacy agent icons for backwards compatibility
        "hunter": "🔍",
        "critic": "🧐",
        "publisher": "🚀",
        "meta": "🧠",
    }

    agents = []
    for agent_id, agent_cfg in agents_config.items():
        agents.append({
            "id": agent_id,
            "name": agent_cfg.get("name", agent_id.title()),
            "description": agent_cfg.get("description", ""),
            "icon": AGENT_ICONS.get(agent_id, "🤖"),
            "task_types": agent_cfg.get("task_types", []),
            "model": agent_cfg.get("model", "primary"),
            "provider": agent_cfg.get("provider"),
        })

    return {"agents": agents}


@app.post("/api/agent/provider/{agent_type}")
async def set_agent_provider(agent_type: str, request: Request):
    """Set provider override for an agent and restart it."""
    payload = await request.json()
    provider = str(payload.get("provider", "")).strip().lower()

    allowed = {"default", "auto", "claude", "codex"}
    if provider not in allowed:
        return JSONResponse(
            {"success": False, "error": f"Invalid provider '{provider}'"},
            status_code=400
        )

    config_data = load_config()
    agents_config = config_data.get("agents", {})
    if agent_type not in agents_config:
        return JSONResponse(
            {"success": False, "error": f"Unknown agent '{agent_type}'"},
            status_code=404
        )

    agent_cfg = agents_config.get(agent_type, {})
    if provider in {"default", "auto", ""}:
        agent_cfg.pop("provider", None)
    else:
        agent_cfg["provider"] = provider
    agents_config[agent_type] = agent_cfg
    config_data["agents"] = agents_config
    save_config(config_data)

    restart_cmd = (
        f"cd /auto-dev && ./scripts/start_agents.sh stop {agent_type} "
        f"&& sleep 2 && ./scripts/start_agents.sh {agent_type}"
    )
    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", restart_cmd],
            capture_output=True,
            text=True,
            timeout=120
        )
        restart_ok = result.returncode == 0
    except Exception as exc:
        restart_ok = False
        result = None

    return {
        "success": True,
        "agent": agent_type,
        "provider": provider,
        "restarted": restart_ok,
        "message": "Provider updated; agent restarted" if restart_ok else "Provider updated; restart failed"
    }

@app.get("/api/messages")
async def get_messages(agent_id: str = None, limit: int = 50):
    """Get agent messages."""
    conn = get_orchestrator_db()
    if not conn:
        return {"messages": []}
    
    try:
        if agent_id:
            cursor = conn.execute(
                "SELECT * FROM agent_mail WHERE to_agent = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM agent_mail ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            msg['payload'] = parse_json_field(msg['payload']) or {}
            messages.append(msg)
        
        return {"messages": messages}
    finally:
        conn.close()


@app.get("/api/discussions")
async def get_discussions(topic: str = None, limit: int = 100):
    """Get swarm discussions."""
    conn = get_orchestrator_db()
    if not conn:
        return {"discussions": []}
    
    try:
        if topic:
            cursor = conn.execute(
                "SELECT * FROM discussions WHERE topic = ? ORDER BY created_at DESC LIMIT ?",
                (topic, limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM discussions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        
        discussions = []
        for row in cursor.fetchall():
            discussions.append(dict(row))
        
        return {"discussions": discussions}
    except Exception as e:
        return {"discussions": [], "error": str(e)}
    finally:
        conn.close()


@app.get("/api/proposals")
async def get_proposals(status: str = None):
    """Get swarm proposals."""
    conn = get_orchestrator_db()
    if not conn:
        return {"proposals": []}
    
    try:
        if status:
            cursor = conn.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT 50"
            )
        
        proposals = []
        for row in cursor.fetchall():
            p = dict(row)
            p['payload'] = parse_json_field(p['payload']) or {}
            p['votes_for'] = json.loads(p['votes_for']) if p['votes_for'] else []
            p['votes_against'] = json.loads(p['votes_against']) if p['votes_against'] else []
            p['comments'] = json.loads(p['comments']) if p['comments'] else []
            proposals.append(p)
        
        return {"proposals": proposals}
    except Exception as e:
        return {"proposals": [], "error": str(e)}
    finally:
        conn.close()


# ==================== HUMAN APPROVAL QUEUE ====================

@app.get("/api/approvals")
async def get_approvals(status: str = None, repo_id: str = None):
    """Get dev approval queue items using orchestrator_pg."""
    try:
        orchestrator = get_orchestrator()

        # List approvals - if no status specified, get all
        if status:
            approvals = orchestrator.list_approvals(repo_id=repo_id, status=status, limit=50)
        else:
            # Get both pending and recent reviewed
            pending = orchestrator.list_approvals(repo_id=repo_id, status='pending', limit=50)
            approved = orchestrator.list_approvals(repo_id=repo_id, status='approved', limit=20)
            rejected = orchestrator.list_approvals(repo_id=repo_id, status='rejected', limit=10)
            approvals = pending + approved + rejected

        # Convert DevApproval objects to dicts
        approval_dicts = []
        for a in approvals:
            approval_dicts.append({
                'id': a.id,
                'repo_id': a.repo_id,
                'approval_type': a.approval_type,
                'title': a.title,
                'description': a.description,
                'context': a.context,
                'submitted_by': a.submitted_by,
                'status': a.status,
                'reviewer_notes': a.reviewer_notes,
                'gitlab_ref': a.gitlab_ref,
                'created_at': a.created_at,
                'reviewed_at': a.reviewed_at
            })

        # Get pending count
        pending_approvals = orchestrator.list_approvals(repo_id=repo_id, status='pending', limit=1000)
        pending_count = len(pending_approvals)

        return {"approvals": approval_dicts, "pending_count": pending_count}
    except Exception as e:
        logger.error(f"Error getting approvals: {e}")
        return {"approvals": [], "pending_count": 0, "error": str(e)}


@app.post("/api/approvals/{item_id}/approve")
async def approve_item(item_id: str, request: Request):
    """Approve a dev workflow item (spec, merge, deploy) using orchestrator_pg."""
    try:
        body = await request.json()
        notes = body.get('notes', '')
    except (json.JSONDecodeError, ValueError, AttributeError):
        notes = ''

    try:
        orchestrator = get_orchestrator()

        # The orchestrator.approve() handles post-approval actions (creating follow-up tasks)
        success = orchestrator.approve(item_id, reviewer_notes=notes)

        if success:
            return {"success": True, "message": f"Approved: {item_id}"}
        else:
            return JSONResponse({"error": "Item not found or already reviewed"}, status_code=404)
    except Exception as e:
        logger.error(f"Error approving {item_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chat")
async def send_chat(request: Request):
    """Send a message to the swarm. Liaison agent will respond."""
    try:
        body = await request.json()
        message = body.get('message', '')
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Invalid chat request: {e}")
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    if not message:
        return JSONResponse({"error": "Message required"}, status_code=400)

    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)

    try:
        import uuid
        now = datetime.utcnow().isoformat()
        post_id = str(uuid.uuid4())

        # Post human message to chat topic
        conn.execute("""
            INSERT INTO discussions (id, author, topic, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, 'human', 'human_chat', message, now))
        
        # Create high-priority task for Liaison agent
        task_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO tasks (id, type, priority, payload, status, assigned_to, created_by, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
        """, (
            task_id, 'respond_to_human', 10,
            json.dumps({"message": message, "post_id": post_id}),
            'liaison', 'human', now
        ))
        
        conn.commit()
        return {"success": True, "post_id": post_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.get("/api/chat")
async def get_chat():
    """Get chat messages between human and liaison."""
    conn = get_orchestrator_db()
    if not conn:
        return {"messages": []}
    
    try:
        cursor = conn.execute("""
            SELECT * FROM discussions 
            WHERE topic = 'human_chat'
            ORDER BY created_at DESC
            LIMIT 50
        """)
        
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "id": row['id'],
                "author": row['author'],
                "content": row['content'],
                "created_at": row['created_at']
            })
        
        return {"messages": list(reversed(messages))}
    except Exception as e:
        return {"messages": [], "error": str(e)}
    finally:
        conn.close()


@app.post("/api/directive")
async def send_directive(request: Request):
    """Send a directive to all agents via the discussion board."""
    try:
        body = await request.json()
        message = body.get('message', '')
        priority = body.get('priority', 10)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Invalid directive request: {e}")
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    if not message:
        return JSONResponse({"error": "Message required"}, status_code=400)
    
    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)
    
    try:
        import uuid
        now = datetime.utcnow().isoformat()
        post_id = str(uuid.uuid4())
        
        # Post directive to discussion board
        conn.execute("""
            INSERT INTO discussions (id, author, topic, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, 'human', 'directive', f"🎯 HUMAN DIRECTIVE (Priority {priority}): {message}", now))
        
        # Create high-priority tasks for all agents
        for agent in AGENT_TYPES:
            task_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO tasks (id, task_type, priority, payload, status, assigned_to, created_by, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (
                task_id, 'directive', priority,
                json.dumps({"instruction": message, "from": "human", "urgent": True}),
                agent, 'human', now
            ))
        
        conn.commit()
        return {"success": True, "message": "Directive sent to all agents"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/approvals/{item_id}/reject")
async def reject_item(item_id: str, request: Request):
    """Reject a dev workflow item using orchestrator_pg."""
    try:
        body = await request.json()
        reason = body.get('reason', 'No reason provided')
    except (json.JSONDecodeError, ValueError, AttributeError):
        reason = 'No reason provided'

    try:
        orchestrator = get_orchestrator()

        success = orchestrator.reject(item_id, reviewer_notes=reason)

        if success:
            return {"success": True, "message": f"Rejected: {item_id}"}
        else:
            return JSONResponse({"error": "Item not found or already reviewed"}, status_code=404)
    except Exception as e:
        logger.error(f"Error rejecting {item_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Send periodic updates
            await asyncio.sleep(5)
            stats = await api_stats()
            await websocket.send_json({"type": "stats", "data": stats})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ============================================================================
# PROJECT PROPOSALS API - Rich approval queue for build decisions
# ============================================================================

@app.get("/api/projects")
async def get_projects(status: str = None):
    """Get project proposals from the approval queue."""
    conn = get_orchestrator_db()
    if not conn:
        return {"projects": [], "stats": {"pending": 0, "deferred": 0, "approved": 0, "rejected": 0}}
    
    try:
        # Ensure table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_proposals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                hunter_pitch TEXT NOT NULL,
                hunter_rating INTEGER NOT NULL,
                market_size TEXT NOT NULL,
                max_revenue_estimate TEXT NOT NULL,
                critic_evaluation TEXT NOT NULL,
                critic_rating INTEGER NOT NULL,
                cons TEXT NOT NULL,
                differentiation TEXT NOT NULL,
                spec_path TEXT NOT NULL,
                effort_estimate TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                submitted_by TEXT NOT NULL,
                reviewer_notes TEXT,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )
        """)
        conn.commit()
        
        if status:
            cursor = conn.execute(
                "SELECT * FROM project_proposals WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM project_proposals ORDER BY created_at DESC LIMIT 50"
            )
        
        projects = []
        for row in cursor.fetchall():
            project = dict(row)
            project['combined_rating'] = (project['hunter_rating'] + project['critic_rating']) / 2
            projects.append(project)
        
        # Get stats
        stats = {}
        for s in ['pending', 'deferred', 'approved', 'rejected']:
            count = conn.execute(
                "SELECT COUNT(*) FROM project_proposals WHERE status = ?", (s,)
            ).fetchone()[0]
            stats[s] = count
        
        return {"projects": projects, "stats": stats}
    except Exception as e:
        return {"projects": [], "stats": {"pending": 0, "deferred": 0, "approved": 0, "rejected": 0}, "error": str(e)}
    finally:
        conn.close()


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get a single project proposal by ID."""
    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)
    
    try:
        cursor = conn.execute(
            "SELECT * FROM project_proposals WHERE id = ? OR id LIKE ?",
            (project_id, f"{project_id}%")
        )
        row = cursor.fetchone()
        
        if not row:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        
        project = dict(row)
        project['combined_rating'] = (project['hunter_rating'] + project['critic_rating']) / 2
        return {"project": project}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/projects/{project_id}/approve")
async def approve_project(project_id: str, request: Request):
    """Approve a project for building - creates build_product task."""
    try:
        body = await request.json()
        notes = body.get('notes', '')
    except (json.JSONDecodeError, ValueError, AttributeError):
        notes = ''

    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)
    
    try:
        now = datetime.utcnow().isoformat()
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'approved', reviewer_notes = ?, reviewed_at = ?
            WHERE id = ? AND status = 'pending'
        """, (notes, now, project_id))
        conn.commit()
        
        if cursor.rowcount > 0:
            # Get project details
            row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (project_id,)).fetchone()
            if row:
                import uuid
                # Create build_product task for Builder
                task_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO tasks (id, type, priority, payload, status, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id, 'build_product', 8,
                    json.dumps({
                        "project_id": project_id,
                        "title": row['title'],
                        "spec_path": row['spec_path'],
                        "effort_estimate": row['effort_estimate'],
                        "max_revenue": row['max_revenue_estimate'],
                        "differentiation": row['differentiation']
                    }),
                    'pending', 'human', now
                ))
                
                # Post to discussion
                conn.execute("""
                    INSERT INTO discussions (id, author, topic, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), 'human', 'projects',
                    f"✅ PROJECT APPROVED: {row['title']} - Builder will start working on this!",
                    now
                ))
                conn.commit()
            
            return {"success": True, "message": f"Approved: {row['title'] if row else project_id}"}
        else:
            return JSONResponse({"error": "Project not found or not pending"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/projects/{project_id}/reject")
async def reject_project(project_id: str, request: Request):
    """Reject a project - will NOT be built."""
    try:
        body = await request.json()
        reason = body.get('reason', 'No reason provided')
    except (json.JSONDecodeError, ValueError, AttributeError):
        reason = 'No reason provided'

    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)
    
    try:
        now = datetime.utcnow().isoformat()
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'rejected', reviewer_notes = ?, reviewed_at = ?
            WHERE id = ? AND status IN ('pending', 'deferred')
        """, (reason, now, project_id))
        conn.commit()
        
        if cursor.rowcount > 0:
            row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (project_id,)).fetchone()
            if row:
                import uuid
                conn.execute("""
                    INSERT INTO discussions (id, author, topic, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), 'human', 'projects',
                    f"❌ PROJECT REJECTED: {row['title']} - Reason: {reason}",
                    now
                ))
                conn.commit()
            
            return {"success": True, "message": f"Rejected: {row['title'] if row else project_id}"}
        else:
            return JSONResponse({"error": "Project not found or already reviewed"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/projects/{project_id}/defer")
async def defer_project(project_id: str, request: Request):
    """Defer a project to backlog for later review."""
    try:
        body = await request.json()
        notes = body.get('notes', 'Deferred for later review')
    except (json.JSONDecodeError, ValueError, AttributeError):
        notes = 'Deferred for later review'

    conn = get_orchestrator_db()
    if not conn:
        return JSONResponse({"error": "Database unavailable"}, status_code=500)
    
    try:
        now = datetime.utcnow().isoformat()
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'deferred', reviewer_notes = ?, reviewed_at = ?
            WHERE id = ? AND status = 'pending'
        """, (notes, now, project_id))
        conn.commit()
        
        if cursor.rowcount > 0:
            row = conn.execute("SELECT * FROM project_proposals WHERE id = ?", (project_id,)).fetchone()
            if row:
                import uuid
                conn.execute("""
                    INSERT INTO discussions (id, author, topic, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), 'human', 'projects',
                    f"⏸️ PROJECT DEFERRED: {row['title']} - Moved to backlog for later",
                    now
                ))
                conn.commit()
            
            return {"success": True, "message": f"Deferred: {row['title'] if row else project_id}"}
        else:
            return JSONResponse({"error": "Project not found or not pending"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


# Agent Activity Page HTML
AGENTS_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Activity - Auto-Dev</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 1.5rem 2rem;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 1.5rem;
            background: linear-gradient(90deg, #00d4ff, #7c3aed);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav-links a {
            color: #888;
            text-decoration: none;
            margin-left: 1.5rem;
            transition: color 0.2s;
        }
        .nav-links a:hover { color: #00d4ff; }
        .nav-links a.active { color: #00d4ff; }
        .container { padding: 2rem; max-width: 1600px; margin: 0 auto; }
        .filters {
            display: flex;
            gap: 1rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }
        .filter-btn {
            padding: 0.5rem 1rem;
            background: #1a1a2e;
            border: 1px solid #333;
            color: #888;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .filter-btn:hover { border-color: #00d4ff; color: #00d4ff; }
        .filter-btn.active { background: #00d4ff; color: #0a0a0f; border-color: #00d4ff; }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .summary-card {
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 1rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        .summary-card:hover { border-color: #00d4ff; transform: translateY(-2px); }
        .summary-card.selected { border-color: #7c3aed; background: #1a1a3e; }
        .summary-card h3 { font-size: 0.9rem; color: #888; margin-bottom: 0.5rem; }
        .summary-card .count { font-size: 1.8rem; font-weight: bold; color: #00d4ff; }
        .summary-card .stats { font-size: 0.75rem; color: #666; margin-top: 0.5rem; }
        .stats span { margin-right: 0.75rem; }
        .stats .completed { color: #10b981; }
        .stats .pending { color: #f59e0b; }
        .stats .failed { color: #ef4444; }
        .tasks-container { margin-top: 2rem; }
        .agent-section {
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            overflow: hidden;
        }
        .agent-header {
            background: #16213e;
            padding: 1rem 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }
        .agent-header h2 {
            font-size: 1.1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .agent-header .badge {
            background: #333;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
        }
        .task-list { padding: 0; }
        .task-item {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid #222;
            display: grid;
            grid-template-columns: 100px 1fr 120px 150px;
            gap: 1rem;
            align-items: center;
        }
        .task-item:last-child { border-bottom: none; }
        .task-item:hover { background: #1f1f3a; }
        .task-type {
            font-size: 0.8rem;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            text-align: center;
        }
        .task-type.build_product { background: #7c3aed33; color: #a78bfa; }
        .task-type.code_review { background: #3b82f633; color: #60a5fa; }
        .task-type.test_product { background: #10b98133; color: #34d399; }
        .task-type.scan_platform { background: #f59e0b33; color: #fbbf24; }
        .task-type.evaluate_idea { background: #ec489933; color: #f472b6; }
        .task-type.deploy { background: #06b6d433; color: #22d3ee; }
        .task-type.fix_product { background: #ef444433; color: #f87171; }
        .task-title {
            font-size: 0.9rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .task-status {
            font-size: 0.75rem;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            text-align: center;
        }
        .task-status.completed { background: #10b98133; color: #34d399; }
        .task-status.pending { background: #f59e0b33; color: #fbbf24; }
        .task-status.claimed { background: #3b82f633; color: #60a5fa; }
        .task-status.failed { background: #ef444433; color: #f87171; }
        .task-status.cancelled { background: #6b728033; color: #9ca3af; }
        .task-time { font-size: 0.75rem; color: #666; }
        .empty-state {
            text-align: center;
            padding: 3rem;
            color: #666;
        }
        .loading {
            text-align: center;
            padding: 2rem;
            color: #666;
        }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .loading { animation: pulse 1.5s infinite; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Agent Activity</h1>
        <div class="nav-links">
            <a href="/">Dashboard</a>
            <a href="/repos">Repositories</a>
            <a href="/projects">Approvals</a>
            <a href="/agents" class="active">Agents</a>
        </div>
    </div>
    
    <div class="container">
        <div class="filters">
            <button class="filter-btn active" data-status="all">All Tasks</button>
            <button class="filter-btn" data-status="closed">Closed</button>
            <button class="filter-btn" data-status="completed">Completed</button>
            <button class="filter-btn" data-status="pending">Pending</button>
            <button class="filter-btn" data-status="claimed">In Progress</button>
            <button class="filter-btn" data-status="failed">Failed</button>
        </div>
        
        <div class="summary-grid" id="summaryGrid">
            <div class="loading">Loading agent summary...</div>
        </div>
        
        <div class="tasks-container" id="tasksContainer">
            <div class="loading">Loading tasks...</div>
        </div>
    </div>
    
    <script>
        let currentStatus = 'all';
        let currentAgent = null;
        let summaryData = {};
        
        function formatTime(isoString) {
            if (!isoString) return '-';
            const date = new Date(isoString);
            const now = new Date();
            const diff = now - date;
            
            if (diff < 60000) return 'just now';
            if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
            if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
            return date.toLocaleDateString();
        }
        
        function getTaskTitle(task) {
            const p = task.payload || {};
            return p.title || p.product || p.product_name || p.name || p.task || task.type;
        }
        
        async function loadData() {
            try {
                let url = `/api/agent-tasks?limit=200`;
                if (currentStatus && currentStatus !== 'all') {
                    url += `&status=${currentStatus}`;
                }
                if (currentAgent) {
                    url += `&agent=${currentAgent}`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                summaryData = data.summary || {};
                
                renderSummary(summaryData);
                renderTasks(data.agents || {});
            } catch (error) {
                console.error('Failed to load data:', error);
            }
        }
        
        function renderSummary(summary) {
            const grid = document.getElementById('summaryGrid');
            const agents = Object.keys(summary).filter(a => a !== 'unassigned').sort();
            
            if (agents.length === 0) {
                grid.innerHTML = '<div class="empty-state">No agent activity yet</div>';
                return;
            }
            
            grid.innerHTML = agents.map(agent => {
                const s = summary[agent];
                const isSelected = currentAgent === agent;
                return `
                    <div class="summary-card ${isSelected ? 'selected' : ''}" onclick="selectAgent('${agent}')">
                        <h3>${agent}</h3>
                        <div class="count">${s.total || 0}</div>
                        <div class="stats">
                            <span class="completed">✓ ${s.completed || 0}</span>
                            <span class="pending">◔ ${s.pending || 0}</span>
                            <span class="failed">✗ ${s.failed || 0}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function renderTasks(agents) {
            const container = document.getElementById('tasksContainer');
            const agentList = Object.keys(agents).filter(a => a !== 'unassigned').sort();
            
            if (agentList.length === 0) {
                container.innerHTML = '<div class="empty-state">No tasks found for current filter</div>';
                return;
            }
            
            container.innerHTML = agentList.map(agent => {
                const tasks = agents[agent] || [];
                return `
                    <div class="agent-section">
                        <div class="agent-header">
                            <h2>
                                ${agent}
                                <span class="badge">${tasks.length} tasks</span>
                            </h2>
                        </div>
                        <div class="task-list">
                            ${tasks.slice(0, 20).map(task => `
                                <div class="task-item">
                                    <span class="task-type ${task.type}">${task.type}</span>
                                    <span class="task-title" title="${getTaskTitle(task)}">${getTaskTitle(task)}</span>
                                    <span class="task-status ${task.status}">${task.status}</span>
                                    <span class="task-time">${formatTime(task.completed_at || task.created_at)}</span>
                                </div>
                            `).join('')}
                            ${tasks.length > 20 ? `<div class="task-item" style="justify-content: center; color: #666;">+ ${tasks.length - 20} more tasks</div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function selectAgent(agent) {
            currentAgent = currentAgent === agent ? null : agent;
            loadData();
        }
        
        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentStatus = btn.dataset.status;
                loadData();
            });
        });
        
        // Initial load
        loadData();
        
        // Refresh every 30 seconds
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""


# Projects Page HTML - Rich approval UI for project proposals
PROJECTS_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pending Approvals - Auto-Dev</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a24;
            --text-primary: #e8e8ed;
            --text-secondary: #8b8b9e;
            --text-muted: #5a5a6e;
            --accent-green: #00ff88;
            --accent-blue: #00a8ff;
            --accent-purple: #a855f7;
            --accent-orange: #ff6b35;
            --accent-red: #ff4757;
            --accent-yellow: #ffd93d;
            --border-color: #2a2a3a;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top, rgba(168, 85, 247, 0.05) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(0, 255, 136, 0.03) 0%, transparent 50%);
        }
        
        .header {
            background: var(--bg-secondary);
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 1.5rem;
            background: linear-gradient(90deg, var(--accent-purple), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .nav-links a {
            color: var(--text-secondary);
            text-decoration: none;
            margin-left: 1.5rem;
            transition: color 0.2s;
        }
        .nav-links a:hover { color: var(--accent-blue); }
        .nav-links a.active { color: var(--accent-purple); }
        
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            padding: 2rem; 
        }
        
        .stats-bar {
            display: flex;
            gap: 1rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }
        
        .stat-btn {
            padding: 0.75rem 1.5rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
            font-size: 0.9rem;
        }
        
        .stat-btn:hover { border-color: var(--accent-purple); }
        .stat-btn.active { 
            background: var(--accent-purple); 
            color: white; 
            border-color: var(--accent-purple); 
        }
        
        .stat-btn .count {
            font-weight: 700;
            margin-left: 0.5rem;
        }
        
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
        }
        
        .empty-state h3 { margin-bottom: 1rem; color: var(--text-secondary); }
        
        .project-list {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        
        .project-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            transition: all 0.3s;
        }
        
        .project-card:hover {
            border-color: var(--accent-purple);
            box-shadow: 0 0 30px rgba(168, 85, 247, 0.1);
        }
        
        .project-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding: 1.5rem;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
        }
        
        .project-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }
        
        .project-meta {
            display: flex;
            gap: 1rem;
            color: var(--text-muted);
            font-size: 0.8rem;
        }
        
        .rating {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 1.5rem;
            font-weight: 700;
        }
        
        .rating.high { color: var(--accent-green); }
        .rating.medium { color: var(--accent-yellow); }
        .rating.low { color: var(--accent-red); }
        
        .rating-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 400;
        }
        
        .project-body {
            padding: 1.5rem;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }
        
        .section {
            background: var(--bg-secondary);
            border-radius: 8px;
            padding: 1rem;
        }
        
        .section-title {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .section-content {
            font-size: 0.9rem;
            line-height: 1.6;
            color: var(--text-secondary);
        }
        
        .section-content.pitch {
            font-style: italic;
            color: var(--text-primary);
        }
        
        .cons-list {
            list-style: none;
            padding: 0;
        }
        
        .cons-list li {
            padding: 0.25rem 0;
            padding-left: 1.25rem;
            position: relative;
        }
        
        .cons-list li:before {
            content: "⚠️";
            position: absolute;
            left: 0;
            font-size: 0.8rem;
        }
        
        .metrics-row {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
            grid-column: span 2;
        }
        
        .metric {
            flex: 1;
            background: var(--bg-secondary);
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
        }
        
        .metric-value {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--accent-green);
        }
        
        .metric-label {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
            margin-top: 0.25rem;
        }
        
        .project-actions {
            padding: 1.5rem;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 1rem;
        }
        
        .action-btn {
            flex: 1;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .action-btn.approve {
            background: var(--accent-green);
            color: #000;
        }
        .action-btn.approve:hover { background: #00cc6a; }
        
        .action-btn.reject {
            background: var(--accent-red);
            color: white;
        }
        .action-btn.reject:hover { background: #ff2d3d; }
        
        .action-btn.defer {
            background: var(--accent-orange);
            color: white;
        }
        .action-btn.defer:hover { background: #e55a2b; }
        
        .action-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .status-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .status-badge.approved { background: rgba(0, 255, 136, 0.2); color: var(--accent-green); }
        .status-badge.rejected { background: rgba(255, 71, 87, 0.2); color: var(--accent-red); }
        .status-badge.deferred { background: rgba(255, 107, 53, 0.2); color: var(--accent-orange); }
        .status-badge.pending { background: rgba(168, 85, 247, 0.2); color: var(--accent-purple); }
        
        .reject-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        
        .reject-modal.show { display: flex; }
        
        .modal-content {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 2rem;
            max-width: 500px;
            width: 90%;
        }
        
        .modal-content h3 { margin-bottom: 1rem; }
        
        .modal-content textarea {
            width: 100%;
            padding: 1rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.9rem;
            resize: vertical;
            min-height: 100px;
        }
        
        .modal-actions {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }
        
        @media (max-width: 768px) {
            .project-body { grid-template-columns: 1fr; }
            .metrics-row { grid-column: span 1; flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Project Approvals</h1>
        <div class="nav-links">
            <a href="/">Dashboard</a>
            <a href="/repos">Repositories</a>
            <a href="/projects" class="active">Approvals</a>
            <a href="/agents">Agents</a>
        </div>
    </div>
    
    <div class="container">
        <div class="stats-bar" id="statsBar">
            <button class="stat-btn active" data-status="pending">
                ⏳ Pending <span class="count" id="pendingCount">0</span>
            </button>
            <button class="stat-btn" data-status="deferred">
                ⏸️ Deferred <span class="count" id="deferredCount">0</span>
            </button>
            <button class="stat-btn" data-status="approved">
                ✅ Approved <span class="count" id="approvedCount">0</span>
            </button>
            <button class="stat-btn" data-status="rejected">
                ❌ Rejected <span class="count" id="rejectedCount">0</span>
            </button>
        </div>
        
        <div class="project-list" id="projectList">
            <div class="empty-state">
                <h3>Loading projects...</h3>
            </div>
        </div>
    </div>
    
    <div class="reject-modal" id="rejectModal">
        <div class="modal-content">
            <h3>Reject Project</h3>
            <p style="color: var(--text-secondary); margin-bottom: 1rem;">Why is this project not worth building?</p>
            <textarea id="rejectReason" placeholder="Enter reason for rejection..."></textarea>
            <div class="modal-actions">
                <button class="action-btn" style="background: var(--border-color); color: var(--text-primary);" onclick="closeRejectModal()">Cancel</button>
                <button class="action-btn reject" onclick="confirmReject()">Reject</button>
            </div>
        </div>
    </div>
    
    <script>
        const API_BASE = window.location.origin;
        let currentStatus = 'pending';
        let rejectProjectId = null;
        
        async function loadProjects() {
            try {
                const response = await fetch(`${API_BASE}/api/projects?status=${currentStatus}`);
                const data = await response.json();
                
                // Update stats
                document.getElementById('pendingCount').textContent = data.stats?.pending || 0;
                document.getElementById('deferredCount').textContent = data.stats?.deferred || 0;
                document.getElementById('approvedCount').textContent = data.stats?.approved || 0;
                document.getElementById('rejectedCount').textContent = data.stats?.rejected || 0;
                
                renderProjects(data.projects || []);
            } catch (error) {
                console.error('Failed to load projects:', error);
            }
        }
        
        function renderProjects(projects) {
            const container = document.getElementById('projectList');
            
            if (projects.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <h3>No ${currentStatus} projects</h3>
                        <p>Projects will appear here when agents submit them for approval.</p>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = projects.map(p => {
                const avgRating = ((p.hunter_rating + p.critic_rating) / 2).toFixed(1);
                const ratingClass = avgRating >= 7 ? 'high' : avgRating >= 5 ? 'medium' : 'low';
                const isPending = p.status === 'pending';
                const isDeferred = p.status === 'deferred';
                
                // Parse cons into list items
                const consList = p.cons.split('\\n').filter(c => c.trim())
                    .map(c => `<li>${c.replace(/^[-•]\\s*/, '')}</li>`).join('');
                
                return `
                    <div class="project-card">
                        <div class="project-header">
                            <div>
                                <div class="project-title">${escapeHtml(p.title)}</div>
                                <div class="project-meta">
                                    <span>📁 ${p.market_size} Market</span>
                                    <span>⏱️ ${escapeHtml(p.effort_estimate)}</span>
                                    <span>📅 ${new Date(p.created_at).toLocaleDateString()}</span>
                                    ${!isPending ? `<span class="status-badge ${p.status}">${p.status}</span>` : ''}
                                </div>
                            </div>
                            <div class="rating ${ratingClass}">
                                ⭐ ${avgRating}
                                <span class="rating-label">/10</span>
                            </div>
                        </div>
                        
                        <div class="project-body">
                            <div class="section">
                                <div class="section-title">🔍 Hunter's Pitch</div>
                                <div class="section-content pitch">"${escapeHtml(p.hunter_pitch)}"</div>
                                <div style="margin-top: 0.5rem; font-size: 0.75rem; color: var(--text-muted);">
                                    Hunter rating: <strong style="color: var(--accent-blue);">${p.hunter_rating}/10</strong>
                                </div>
                            </div>
                            
                            <div class="section">
                                <div class="section-title">🧐 Critic's Take</div>
                                <div class="section-content">${escapeHtml(p.critic_evaluation)}</div>
                                <div style="margin-top: 0.5rem; font-size: 0.75rem; color: var(--text-muted);">
                                    Critic rating: <strong style="color: var(--accent-purple);">${p.critic_rating}/10</strong>
                                </div>
                            </div>
                            
                            <div class="section">
                                <div class="section-title">⚠️ Risks / Cons</div>
                                <ul class="cons-list">${consList || '<li>No cons identified</li>'}</ul>
                            </div>
                            
                            <div class="section">
                                <div class="section-title">✨ Differentiation</div>
                                <div class="section-content">${escapeHtml(p.differentiation)}</div>
                            </div>
                            
                            <div class="metrics-row">
                                <div class="metric">
                                    <div class="metric-value">${escapeHtml(p.max_revenue_estimate)}</div>
                                    <div class="metric-label">Max Revenue</div>
                                </div>
                                <div class="metric">
                                    <div class="metric-value" style="color: var(--accent-blue);">${escapeHtml(p.effort_estimate)}</div>
                                    <div class="metric-label">Effort Estimate</div>
                                </div>
                                <div class="metric">
                                    <div class="metric-value" style="color: var(--accent-purple);">${avgRating}/10</div>
                                    <div class="metric-label">Combined Score</div>
                                </div>
                            </div>
                        </div>
                        
                        ${isPending || isDeferred ? `
                        <div class="project-actions">
                            <button class="action-btn approve" onclick="approveProject('${p.id}')">✅ Approve</button>
                            <button class="action-btn reject" onclick="showRejectModal('${p.id}')">❌ Reject</button>
                            ${isPending ? `<button class="action-btn defer" onclick="deferProject('${p.id}')">⏸️ Defer</button>` : ''}
                        </div>
                        ` : `
                        <div class="project-actions" style="justify-content: center; color: var(--text-muted);">
                            ${p.reviewer_notes ? `<span>Notes: ${escapeHtml(p.reviewer_notes)}</span>` : ''}
                        </div>
                        `}
                    </div>
                `;
            }).join('');
        }
        
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function approveProject(id) {
            if (!confirm('Approve this project? Builder will start working on it.')) return;
            
            try {
                const response = await fetch(`${API_BASE}/api/projects/${id}/approve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: 'Approved via dashboard' })
                });
                
                if (response.ok) {
                    loadProjects();
                } else {
                    const err = await response.json();
                    alert('Failed to approve: ' + (err.error || 'Unknown error'));
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        function showRejectModal(id) {
            rejectProjectId = id;
            document.getElementById('rejectModal').classList.add('show');
            document.getElementById('rejectReason').focus();
        }
        
        function closeRejectModal() {
            rejectProjectId = null;
            document.getElementById('rejectModal').classList.remove('show');
            document.getElementById('rejectReason').value = '';
        }
        
        async function confirmReject() {
            const reason = document.getElementById('rejectReason').value.trim();
            if (!reason) {
                alert('Please provide a reason for rejection');
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/api/projects/${rejectProjectId}/reject`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason })
                });
                
                if (response.ok) {
                    closeRejectModal();
                    loadProjects();
                } else {
                    const err = await response.json();
                    alert('Failed to reject: ' + (err.error || 'Unknown error'));
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        async function deferProject(id) {
            if (!confirm('Defer this project to backlog? You can review it later.')) return;
            
            try {
                const response = await fetch(`${API_BASE}/api/projects/${id}/defer`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: 'Deferred for later review' })
                });
                
                if (response.ok) {
                    loadProjects();
                } else {
                    const err = await response.json();
                    alert('Failed to defer: ' + (err.error || 'Unknown error'));
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        // Filter buttons
        document.querySelectorAll('.stat-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.stat-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentStatus = btn.dataset.status;
                loadProjects();
            });
        });
        
        // Initial load
        loadProjects();

        // Refresh every 30 seconds
        setInterval(loadProjects, 30000);
    </script>
</body>
</html>
"""


# Repository Management HTML template
REPOS_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repository Management - Auto-Dev</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a24;
            --text-primary: #e8e8ed;
            --text-secondary: #8b8b9e;
            --text-muted: #5a5a6e;
            --accent-green: #00ff88;
            --accent-blue: #00a8ff;
            --accent-purple: #a855f7;
            --accent-orange: #ff6b35;
            --accent-red: #ff4757;
            --border-color: #2a2a3a;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image:
                radial-gradient(ellipse at top, rgba(168, 85, 247, 0.05) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(0, 255, 136, 0.03) 0%, transparent 50%);
        }

        .header {
            background: var(--bg-secondary);
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header h1 {
            font-size: 1.5rem;
            background: linear-gradient(90deg, var(--accent-green), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .nav-links a {
            color: var(--text-secondary);
            text-decoration: none;
            margin-left: 1.5rem;
            transition: color 0.2s;
        }
        .nav-links a:hover { color: var(--accent-blue); }
        .nav-links a.active { color: var(--accent-green); }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        .page-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }

        .page-title h2 {
            font-size: 1.5rem;
            color: var(--text-primary);
        }

        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.9rem;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--accent-green);
            color: #0a0a0f;
        }
        .btn-primary:hover { filter: brightness(1.1); }

        .btn-secondary {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
        }
        .btn-secondary:hover { border-color: var(--accent-blue); color: var(--accent-blue); }

        .btn-danger {
            background: var(--accent-red);
            color: white;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
        }

        .stat-card h3 {
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }

        .stat-card .value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent-blue);
        }

        .repos-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 1.5rem;
        }

        .repo-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            transition: all 0.2s;
        }

        .repo-card:hover {
            border-color: var(--accent-purple);
            transform: translateY(-2px);
        }

        .repo-card.inactive {
            opacity: 0.6;
        }

        .repo-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
        }

        .repo-name {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .repo-mode {
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
        }

        .repo-mode.guided {
            background: rgba(0, 168, 255, 0.2);
            color: var(--accent-blue);
        }

        .repo-mode.full {
            background: rgba(0, 255, 136, 0.2);
            color: var(--accent-green);
        }

        .repo-url {
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 1rem;
            font-family: 'JetBrains Mono', monospace;
        }

        .repo-stats {
            display: flex;
            gap: 1.5rem;
            margin-bottom: 1rem;
            padding: 1rem 0;
            border-top: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
        }

        .repo-stat {
            text-align: center;
        }

        .repo-stat .label {
            color: var(--text-muted);
            font-size: 0.75rem;
        }

        .repo-stat .value {
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .repo-actions {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .repo-actions .btn {
            padding: 0.5rem 1rem;
            font-size: 0.8rem;
        }

        /* Modal styles */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }

        .modal.active { display: flex; }

        .modal-content {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            max-width: 500px;
            width: 90%;
            max-height: 90vh;
            overflow-y: auto;
        }

        .modal-content h2 {
            margin-bottom: 1.5rem;
            color: var(--accent-purple);
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 0.75rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 1rem;
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: var(--accent-purple);
        }

        .modal-actions {
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
            margin-top: 2rem;
        }

        .webhook-info {
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
        }

        .webhook-info pre {
            white-space: pre-wrap;
            word-break: break-all;
        }

        .copy-btn {
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
            margin-left: 0.5rem;
        }

        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 4rem;
            color: var(--text-muted);
        }

        .empty-state {
            text-align: center;
            padding: 4rem;
            color: var(--text-muted);
        }

        .empty-state h3 {
            margin-bottom: 1rem;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <header class="header">
        <h1>Auto-Dev</h1>
        <nav class="nav-links">
            <a href="/">Dashboard</a>
            <a href="/agents">Agents</a>
            <a href="/repos" class="active">Repositories</a>
            <a href="/projects">Approvals</a>
        </nav>
    </header>

    <div class="container">
        <div class="page-title">
            <h2>Repository Management</h2>
            <button class="btn btn-primary" onclick="showAddModal()">+ Add Repository</button>
        </div>

        <div class="stats-grid" id="stats-grid">
            <div class="stat-card">
                <h3>Total Repositories</h3>
                <div class="value" id="total-repos">-</div>
            </div>
            <div class="stat-card">
                <h3>Active Tasks</h3>
                <div class="value" id="active-tasks">-</div>
            </div>
            <div class="stat-card">
                <h3>Pending Approvals</h3>
                <div class="value" id="pending-approvals">-</div>
            </div>
            <div class="stat-card">
                <h3>In Progress</h3>
                <div class="value" id="in-progress">-</div>
            </div>
        </div>

        <div id="repos-container" class="repos-grid">
            <div class="loading">Loading repositories...</div>
        </div>
    </div>

    <!-- Add Repository Modal -->
    <div class="modal" id="add-modal">
        <div class="modal-content">
            <h2>Add Repository</h2>
            <form id="add-form" onsubmit="addRepo(event)">
                <div class="form-group">
                    <label for="repo-name">Repository Name</label>
                    <input type="text" id="repo-name" required placeholder="my-project">
                </div>
                <div class="form-group">
                    <label for="gitlab-url">GitLab URL</label>
                    <input type="url" id="gitlab-url" required placeholder="https://gitlab.com">
                </div>
                <div class="form-group">
                    <label for="project-id">Project ID or Path</label>
                    <input type="text" id="project-id" required placeholder="group/project or 12345">
                </div>
                <div class="form-group">
                    <label for="default-branch">Default Branch</label>
                    <input type="text" id="default-branch" value="main" placeholder="main">
                </div>
                <div class="form-group">
                    <label for="autonomy-mode">Autonomy Mode</label>
                    <select id="autonomy-mode">
                        <option value="guided">Guided (Human Approval Required)</option>
                        <option value="full">Full Autonomy</option>
                    </select>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="hideModal('add-modal')">Cancel</button>
                    <button type="submit" class="btn btn-primary">Add Repository</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Webhook Info Modal -->
    <div class="modal" id="webhook-modal">
        <div class="modal-content">
            <h2>Webhook Setup</h2>
            <div id="webhook-content"></div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="hideModal('webhook-modal')">Close</button>
            </div>
        </div>
    </div>

    <script>
        async function loadRepos() {
            try {
                // Load stats
                const statsRes = await fetch('/api/repos/dashboard/stats');
                const stats = await statsRes.json();

                document.getElementById('total-repos').textContent = stats.total_repos || 0;
                document.getElementById('active-tasks').textContent = stats.pending_tasks || 0;
                document.getElementById('pending-approvals').textContent = stats.total_pending_approvals || 0;
                document.getElementById('in-progress').textContent = stats.in_progress_tasks || 0;

                // Load repos
                const reposRes = await fetch('/api/repos');
                const data = await reposRes.json();

                const container = document.getElementById('repos-container');

                if (!data.repos || data.repos.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <h3>No repositories configured</h3>
                            <p>Add a GitLab repository to get started with Auto-Dev</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = data.repos.map(repo => {
                    const repoStats = stats.repos?.find(r => r.id === repo.id) || {};
                    return `
                        <div class="repo-card ${!repo.active ? 'inactive' : ''}">
                            <div class="repo-header">
                                <div class="repo-name">${repo.name}</div>
                                <span class="repo-mode ${repo.autonomy_mode}">${repo.autonomy_mode}</span>
                            </div>
                            <div class="repo-url">${repo.gitlab_url}/${repo.gitlab_project_id}</div>
                            <div class="repo-stats">
                                <div class="repo-stat">
                                    <div class="value">${repoStats.task_count || 0}</div>
                                    <div class="label">Tasks</div>
                                </div>
                                <div class="repo-stat">
                                    <div class="value">${repoStats.pending_tasks || 0}</div>
                                    <div class="label">Pending</div>
                                </div>
                                <div class="repo-stat">
                                    <div class="value">${repoStats.in_progress_tasks || 0}</div>
                                    <div class="label">In Progress</div>
                                </div>
                                <div class="repo-stat">
                                    <div class="value">${repoStats.pending_approvals || 0}</div>
                                    <div class="label">Approvals</div>
                                </div>
                            </div>
                            <div class="repo-actions">
                                <button class="btn btn-secondary" onclick="showWebhook('${repo.id}')">Webhook</button>
                                <button class="btn btn-secondary" onclick="triggerAnalysis('${repo.id}')">Analyze</button>
                                <button class="btn btn-secondary" onclick="toggleMode('${repo.id}', '${repo.autonomy_mode}')">${repo.autonomy_mode === 'guided' ? 'Enable Full' : 'Enable Guided'}</button>
                                ${repo.active
                                    ? `<button class="btn btn-danger" onclick="deactivateRepo('${repo.id}')">Deactivate</button>`
                                    : `<button class="btn btn-primary" onclick="activateRepo('${repo.id}')">Activate</button>`
                                }
                            </div>
                        </div>
                    `;
                }).join('');

            } catch (err) {
                console.error('Failed to load repos:', err);
                document.getElementById('repos-container').innerHTML = `
                    <div class="empty-state">
                        <h3>Error loading repositories</h3>
                        <p>${err.message}</p>
                    </div>
                `;
            }
        }

        function showAddModal() {
            document.getElementById('add-modal').classList.add('active');
        }

        function hideModal(id) {
            document.getElementById(id).classList.remove('active');
        }

        async function addRepo(event) {
            event.preventDefault();

            const data = {
                name: document.getElementById('repo-name').value,
                gitlab_url: document.getElementById('gitlab-url').value,
                gitlab_project_id: document.getElementById('project-id').value,
                default_branch: document.getElementById('default-branch').value || 'main',
                autonomy_mode: document.getElementById('autonomy-mode').value
            };

            try {
                const res = await fetch('/api/repos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await res.json();

                if (!res.ok) {
                    alert('Error: ' + (result.detail || 'Failed to add repository'));
                    return;
                }

                hideModal('add-modal');
                document.getElementById('add-form').reset();
                loadRepos();

                // Show webhook setup
                showWebhook(result.repo_id);

            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        async function showWebhook(repoId) {
            try {
                const res = await fetch(`/api/repos/${repoId}/webhook`);
                const data = await res.json();

                document.getElementById('webhook-content').innerHTML = `
                    <div class="webhook-info">
                        <p><strong>Webhook URL:</strong></p>
                        <pre>${data.webhook_url}</pre>
                        <p style="margin-top: 1rem;"><strong>Secret Token:</strong></p>
                        <pre>${data.webhook_secret}</pre>
                    </div>
                    <div style="margin-top: 1rem; white-space: pre-wrap; color: var(--text-secondary); font-size: 0.9rem;">
${data.instructions}
                    </div>
                `;

                document.getElementById('webhook-modal').classList.add('active');

            } catch (err) {
                alert('Error loading webhook info: ' + err.message);
            }
        }

        async function triggerAnalysis(repoId) {
            try {
                const res = await fetch(`/api/repos/${repoId}/trigger`, { method: 'POST' });
                const result = await res.json();

                if (!res.ok) {
                    alert('Error: ' + (result.detail || 'Failed to trigger analysis'));
                    return;
                }

                alert('Analysis task created: ' + result.task_id);
                loadRepos();

            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        async function toggleMode(repoId, currentMode) {
            const newMode = currentMode === 'guided' ? 'full' : 'guided';

            try {
                const res = await fetch(`/api/repos/${repoId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ autonomy_mode: newMode })
                });

                if (!res.ok) {
                    const result = await res.json();
                    alert('Error: ' + (result.detail || 'Failed to update mode'));
                    return;
                }

                loadRepos();

            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        async function deactivateRepo(repoId) {
            if (!confirm('Are you sure you want to deactivate this repository?')) return;

            try {
                const res = await fetch(`/api/repos/${repoId}`, { method: 'DELETE' });

                if (!res.ok) {
                    const result = await res.json();
                    alert('Error: ' + (result.detail || 'Failed to deactivate'));
                    return;
                }

                loadRepos();

            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        async function activateRepo(repoId) {
            try {
                const res = await fetch(`/api/repos/${repoId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ active: true })
                });

                if (!res.ok) {
                    const result = await res.json();
                    alert('Error: ' + (result.detail || 'Failed to activate'));
                    return;
                }

                loadRepos();

            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        // Initial load
        loadRepos();

        // Refresh every 30 seconds
        setInterval(loadRepos, 30000);
    </script>
</body>
</html>
"""


# Dashboard HTML template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Auto-Dev Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a24;
            --bg-card-hover: #22222e;
            --text-primary: #e8e8ed;
            --text-secondary: #8b8b9e;
            --text-muted: #5a5a6e;
            --accent-green: #00ff88;
            --accent-green-dim: rgba(0, 255, 136, 0.15);
            --accent-blue: #00a8ff;
            --accent-purple: #a855f7;
            --accent-orange: #ff6b35;
            --accent-red: #ff4757;
            --border-color: #2a2a3a;
            --glow-green: 0 0 20px rgba(0, 255, 136, 0.3);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top, rgba(0, 255, 136, 0.05) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(168, 85, 247, 0.05) 0%, transparent 50%);
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 24px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 32px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--accent-green), var(--accent-blue));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }
        
        .logo h1 {
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-green), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .header-controls {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        
        .agent-controls {
            display: flex;
            gap: 8px;
        }
        
        .control-btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .start-btn {
            background: var(--accent-green);
            color: #000;
        }
        
        .start-btn:hover {
            background: #00cc6a;
            box-shadow: 0 0 15px rgba(0, 255, 136, 0.4);
        }
        
        .start-btn:disabled {
            background: var(--text-muted);
            cursor: not-allowed;
            box-shadow: none;
        }
        
        .stop-btn {
            background: var(--accent-red);
            color: white;
        }
        
        .stop-btn:hover {
            background: #ff2d3d;
            box-shadow: 0 0 15px rgba(255, 71, 87, 0.4);
        }
        
        .stop-btn:disabled {
            background: var(--text-muted);
            cursor: not-allowed;
            box-shadow: none;
        }
        
        .agents-info {
            display: flex;
            gap: 12px;
            padding: 12px 20px;
            background: var(--bg-card);
            border-radius: 10px;
            border: 1px solid var(--border-color);
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 24px;
        }
        
        .agents-info strong {
            color: var(--accent-blue);
        }

        .rate-limit-banner {
            background: linear-gradient(135deg, #f59e0b22, #ef444422);
            border: 1px solid #f59e0b;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            animation: pulse-border 2s ease-in-out infinite;
        }

        @keyframes pulse-border {
            0%, 100% { border-color: #f59e0b; }
            50% { border-color: #ef4444; }
        }

        .rate-limit-icon {
            font-size: 24px;
        }

        .rate-limit-text {
            color: #fbbf24;
            font-size: 14px;
        }

        .rate-limit-text strong {
            color: #f59e0b;
        }

        .agent-cards {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .agent-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .agent-card:hover {
            border-color: var(--accent-blue);
        }
        
        .agent-card.active {
            border-color: var(--accent-green);
            box-shadow: 0 0 15px rgba(0, 255, 136, 0.2);
        }
        
        .agent-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }
        
        .agent-icon {
            font-size: 20px;
        }
        
        .agent-name {
            font-weight: 600;
            font-size: 16px;
            flex: 1;
        }
        
        .agent-status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--accent-green);
        }
        
        .agent-status-dot.offline {
            background: var(--text-muted);
        }
        
        .agent-status-dot.working {
            background: var(--accent-blue);
            animation: pulse 1.5s infinite;
        }
        
        .agent-role {
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }
        
        .agent-stats {
            font-size: 12px;
            color: var(--text-secondary);
            margin-bottom: 12px;
        }
        
        .agent-stats strong {
            color: var(--text-primary);
        }
        
        .agent-actions {
            display: flex;
            gap: 8px;
        }
        
        .agent-btn {
            flex: 1;
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .agent-btn.start {
            background: var(--accent-green);
            color: #000;
        }
        
        .agent-btn.start:hover {
            background: #00cc6a;
        }
        
        .agent-btn.stop {
            background: var(--accent-red);
            color: white;
        }
        
        .agent-btn.stop:hover {
            background: #ff2d3d;
        }
        
        .agent-btn:disabled {
            background: var(--text-muted);
            cursor: not-allowed;
        }
        
        .directive-btn {
            padding: 8px 16px;
            background: transparent;
            border: 2px solid var(--accent-purple);
            border-radius: 20px;
            color: var(--accent-purple);
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .directive-btn:hover {
            background: rgba(168, 85, 247, 0.15);
            transform: scale(1.02);
        }
        
        @media (max-width: 900px) {
            .agent-cards {
                grid-template-columns: 1fr;
            }
        }
        
        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: var(--bg-card);
            border-radius: 20px;
            border: 1px solid var(--border-color);
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 2s infinite;
        }
        
        .status-dot.offline {
            background: var(--accent-red);
            animation: none;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 255, 136, 0.4); }
            50% { opacity: 0.8; box-shadow: 0 0 0 10px rgba(0, 255, 136, 0); }
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 32px;
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .card:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-green);
            box-shadow: var(--glow-green);
        }
        
        .card-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }
        
        .card-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 32px;
            font-weight: 700;
            color: var(--accent-green);
        }
        
        .card-value.blue { color: var(--accent-blue); }
        .card-value.purple { color: var(--accent-purple); }
        .card-value.orange { color: var(--accent-orange); }
        
        .card-subtitle {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }
        
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
        }
        
        .panel {
            background: var(--bg-card);
            border-radius: 16px;
            border: 1px solid var(--border-color);
            overflow: hidden;
        }
        
        .panel-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .panel-title {
            font-size: 16px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .panel-subtitle {
            font-size: 12px;
            color: var(--text-muted);
        }

        .provider-panel {
            margin-bottom: 24px;
        }

        .provider-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 12px;
            padding: 16px 24px 24px;
        }

        .provider-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .provider-name {
            font-size: 13px;
            font-weight: 600;
        }

        .provider-select {
            width: 100%;
            background: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 6px 8px;
            font-size: 12px;
        }

        .provider-status {
            font-size: 11px;
            color: var(--text-muted);
            min-height: 14px;
        }

        .provider-status.active {
            color: var(--accent-green);
        }
        
        .panel-content {
            padding: 16px 24px;
            max-height: 500px;
            overflow-y: auto;
        }
        
        .activity-item {
            padding: 12px 0;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            gap: 12px;
        }
        
        .activity-item:last-child {
            border-bottom: none;
        }
        
        .activity-icon {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            flex-shrink: 0;
        }
        
        .activity-icon.action { background: var(--accent-green-dim); }
        .activity-icon.observation { background: rgba(0, 168, 255, 0.15); }
        .activity-icon.thought { background: rgba(168, 85, 247, 0.15); }
        .activity-icon.goal { background: rgba(255, 107, 53, 0.15); }
        .activity-icon.income { background: rgba(0, 255, 136, 0.25); }
        
        .activity-content {
            flex: 1;
            min-width: 0;
        }
        
        .activity-type {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
        }
        
        .activity-text {
            font-size: 14px;
            color: var(--text-primary);
            margin-top: 4px;
            word-wrap: break-word;
        }
        
        .activity-time {
            font-size: 11px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }
        
        .income-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid var(--border-color);
        }
        
        .income-item:last-child {
            border-bottom: none;
        }
        
        .income-source {
            font-size: 14px;
            color: var(--text-primary);
        }
        
        .income-amount {
            font-family: 'JetBrains Mono', monospace;
            font-size: 16px;
            font-weight: 600;
            color: var(--accent-green);
        }
        
        .efficiency-bar {
            margin-top: 16px;
            padding: 16px;
            background: var(--bg-secondary);
            border-radius: 12px;
        }
        
        .efficiency-label {
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }
        
        .efficiency-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 24px;
            font-weight: 700;
            color: var(--accent-purple);
        }
        
        .screenshots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 12px;
        }
        
        .screenshot-thumb {
            aspect-ratio: 16/9;
            border-radius: 8px;
            overflow: hidden;
            background: var(--bg-secondary);
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        .screenshot-thumb:hover {
            transform: scale(1.05);
        }
        
        .screenshot-thumb img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }
        
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 3px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-muted);
        }
        
        @media (max-width: 1200px) {
            .grid { grid-template-columns: repeat(2, 1fr); }
            .main-grid { grid-template-columns: 1fr; }
        }
        
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .container { padding: 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">🤖</div>
                <h1>Auto-Dev</h1>
            </div>
            <div class="nav-links" style="display: flex; gap: 1.5rem; margin-right: 2rem;">
                <a href="/" style="color: var(--accent-green); text-decoration: none;">Dashboard</a>
                <a href="/repos" style="color: var(--text-secondary); text-decoration: none;">Repositories</a>
                <a href="/projects" style="color: var(--text-secondary); text-decoration: none;">Approvals</a>
                <a href="/agents" style="color: var(--text-secondary); text-decoration: none;">Agents</a>
            </div>
            <div class="header-controls">
                <div class="agent-controls">
                    <button class="control-btn start-btn" id="startBtn" onclick="startAgent()">▶ Start</button>
                    <button class="control-btn stop-btn" id="stopBtn" onclick="stopAgent()">⏹ Stop</button>
                </div>
                <div class="status-badge">
                    <div class="status-dot" id="statusDot"></div>
                    <span id="statusText">Connecting...</span>
                </div>
            </div>
        </header>
        
        <div class="agents-info" id="agentsInfo">
            <span>🔄 Active Agents: <strong id="agentCount">0</strong></span>
            <span>│</span>
            <span>Mode: <strong>Parallel</strong></span>
            <span>│</span>
            <span>📋 Tasks: <strong id="taskCount">0</strong> pending</span>
        </div>
        
        <!-- Rate Limit Banner -->
        <div class="rate-limit-banner" id="rateLimitBanner" style="display: none;">
            <span class="rate-limit-icon">⏳</span>
            <span class="rate-limit-text">
                <strong id="rateLimitProvider">Provider</strong> rate limited.
                Resets in <strong id="rateLimitCountdown">--:--</strong>
            </span>
        </div>

        <!-- Agent Status Cards - dynamically loaded from settings.yaml -->
        <div class="agent-cards" id="agentCards">
            <div class="empty-state">Loading agents...</div>
        </div>

        <div class="panel provider-panel">
            <div class="panel-header">
                <div class="panel-title">LLM Providers</div>
                <div class="panel-subtitle" id="providerSubtitle">Default: claude (auto fallback to codex on rate limit)</div>
            </div>
            <div class="provider-grid" id="providerGrid">
                <div class="empty-state">Loading providers...</div>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <div class="card-label">Total Income (30d)</div>
                <div class="card-value" id="totalIncome">$0.00</div>
                <div class="card-subtitle">Across all sources</div>
            </div>
            <div class="card">
                <div class="card-label">Tokens Used (7d)</div>
                <div class="card-value blue" id="totalTokens">0</div>
                <div class="card-subtitle" id="tokenCost">$0.00 cost</div>
            </div>
            <div class="card">
                <div class="card-label">Efficiency</div>
                <div class="card-value purple" id="efficiency">$0.00</div>
                <div class="card-subtitle">per 1K tokens</div>
            </div>
            <div class="card">
                <div class="card-label">Sessions Today</div>
                <div class="card-value orange" id="sessions">0</div>
                <div class="card-subtitle" id="sessionDuration">0h runtime</div>
            </div>
        </div>

        <!-- Repository Summary Widget -->
        <div class="panel" style="margin-bottom: 24px;">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📁</span>
                    Repositories
                </div>
                <a href="/repos" style="font-size: 12px; color: var(--accent-blue); text-decoration: none;">View All →</a>
            </div>
            <div class="panel-content" id="repoSummary" style="max-height: 200px; overflow-y: auto;">
                <div class="empty-state">Loading repositories...</div>
            </div>
        </div>

        <!-- Swarm Discussion Panel -->
        <div class="panel" style="margin-bottom: 24px;">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🐝</span>
                    Swarm Discussion
                </div>
                <span style="font-size: 12px; color: var(--text-muted);">Agents debating in real-time</span>
            </div>
            <div class="panel-content" id="swarmDiscussion" style="max-height: 400px;">
                <div class="empty-state">Loading discussions...</div>
            </div>
        </div>
        
        <!-- Proposals Panel -->
        <div class="panel" style="margin-bottom: 24px;">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🗳️</span>
                    Open Proposals
                </div>
                <span style="font-size: 12px; color: var(--text-muted);">Vote on swarm changes</span>
            </div>
            <div class="panel-content" id="proposalsList" style="max-height: 300px;">
                <div class="empty-state">No open proposals</div>
            </div>
        </div>

        <!-- LEARNINGS - Agent performance and learning system -->
        <div class="panel" style="margin-bottom: 24px; border: 2px solid var(--accent-blue);">
            <div class="panel-header" style="background: rgba(0, 168, 255, 0.1);">
                <div class="panel-title">
                    <span>📊</span>
                    Agent Learnings
                </div>
                <span style="font-size: 12px; color: var(--accent-blue);">Performance tracking and improvement</span>
            </div>
            <div class="panel-content" id="learningsPanel" style="max-height: 500px; overflow-y: auto;">
                <div class="empty-state">Loading learnings...</div>
            </div>
        </div>

        <!-- HUMAN APPROVAL QUEUE - Nothing publishes without your review! -->
        <div class="panel" style="margin-bottom: 24px; border: 2px solid var(--accent-orange);">
            <div class="panel-header" style="background: rgba(255, 107, 53, 0.1);">
                <div class="panel-title">
                    <span>📋</span>
                    Human Approval Queue
                    <span id="pendingCount" class="badge" style="background: var(--accent-orange); margin-left: 8px;">0</span>
                </div>
                <span style="font-size: 12px; color: var(--accent-orange);">⚠️ Nothing publishes without your approval</span>
            </div>
            <div class="panel-content" id="approvalQueue" style="max-height: 500px;">
                <div class="empty-state">No items pending approval</div>
            </div>
        </div>
        
        <!-- CHAT WITH SWARM - Two-way communication -->
        <div class="panel" style="margin-bottom: 24px; border: 2px solid var(--accent-purple);">
            <div class="panel-header" style="background: rgba(168, 85, 247, 0.1);">
                <div class="panel-title">
                    <span>💬</span>
                    Chat with Swarm
                </div>
                <span style="font-size: 12px; color: var(--accent-purple);">Liaison Agent responds to your messages</span>
            </div>
            <div class="panel-content" style="padding: 0;">
                <!-- Chat messages -->
                <div id="chatMessages" style="
                    height: 250px;
                    overflow-y: auto;
                    padding: 16px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                ">
                    <div class="empty-state">No messages yet. Ask a question or give an order!</div>
                </div>
                
                <!-- Chat input -->
                <div style="padding: 16px; border-top: 1px solid var(--border-color); background: var(--bg-secondary);">
                    <div style="display: flex; gap: 12px;">
                        <input type="text" id="chatInput" placeholder="Ask a question or give an order..." 
                            onkeypress="if(event.key==='Enter')sendChat()"
                            style="
                                flex: 1;
                                padding: 12px 16px;
                                background: var(--bg-primary);
                                border: 1px solid var(--border-color);
                                border-radius: 8px;
                                color: var(--text-primary);
                                font-size: 14px;
                            ">
                        <button onclick="sendChat()" style="
                            padding: 12px 24px;
                            background: var(--accent-purple);
                            color: white;
                            border: none;
                            border-radius: 8px;
                            font-weight: 700;
                            cursor: pointer;
                        ">Send</button>
                    </div>
                    
                    <!-- Quick actions -->
                    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px;">
                        <button onclick="sendQuickChat('What\\'s the current status?')" class="directive-btn" style="font-size: 11px; padding: 6px 12px;">📊 Status?</button>
                        <button onclick="sendQuickChat('What are you all working on?')" class="directive-btn" style="font-size: 11px; padding: 6px 12px;">🔍 What's happening?</button>
                        <button onclick="sendQuickChat('What\\'s blocking progress?')" class="directive-btn" style="font-size: 11px; padding: 6px 12px;">🚧 Blockers?</button>
                        <button onclick="sendQuickChat('Focus on bounties - fastest path to income')" class="directive-btn" style="font-size: 11px; padding: 6px 12px; border-color: var(--accent-green);">🎯 Focus: Bounties</button>
                        <button onclick="sendQuickChat('STOP new projects, finish existing ones')" class="directive-btn" style="font-size: 11px; padding: 6px 12px; border-color: var(--accent-red);">⏸️ Finish Existing</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ASSIGN TASK - Direct task to specific agent -->
        <div class="panel" style="margin-bottom: 24px;">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📋</span>
                    Assign Task
                </div>
                <span style="font-size: 12px; color: var(--text-muted);">Send work directly to an agent</span>
            </div>
            <div class="panel-content" style="padding: 16px;">
                <div style="display: grid; grid-template-columns: 1fr 180px 150px 80px; gap: 12px; align-items: end;">
                    <div>
                        <label style="font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px;">Task Description</label>
                        <input type="text" id="taskDescription" placeholder="e.g., Add feature X to handle Y..." style="
                            width: 100%;
                            padding: 10px 14px;
                            background: var(--bg-secondary);
                            border: 1px solid var(--border-color);
                            border-radius: 8px;
                            color: var(--text-primary);
                            font-size: 14px;
                        ">
                    </div>
                    <div>
                        <label style="font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px;">Target Repository</label>
                        <select id="taskRepo" style="
                            width: 100%;
                            padding: 10px 14px;
                            background: var(--bg-secondary);
                            border: 1px solid var(--border-color);
                            border-radius: 8px;
                            color: var(--text-primary);
                            font-size: 14px;
                        ">
                            <option value="">Global / All Repos</option>
                            <!-- Populated dynamically from /api/repos -->
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px;">Assign To</label>
                        <select id="taskAgent" style="
                            width: 100%;
                            padding: 10px 14px;
                            background: var(--bg-secondary);
                            border: 1px solid var(--border-color);
                            border-radius: 8px;
                            color: var(--text-primary);
                            font-size: 14px;
                        ">
                            <!-- Populated dynamically from /api/agent-config -->
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px;">Priority</label>
                        <select id="taskPriority" style="
                            width: 100%;
                            padding: 10px 14px;
                            background: var(--bg-secondary);
                            border: 1px solid var(--border-color);
                            border-radius: 8px;
                            color: var(--text-primary);
                            font-size: 14px;
                        ">
                            <option value="10">🔴 10</option>
                            <option value="9">🟠 9</option>
                            <option value="8" selected>🟡 8</option>
                            <option value="5">🟢 5</option>
                            <option value="3">🔵 3</option>
                        </select>
                    </div>
                </div>
                <button onclick="createTask()" style="
                    margin-top: 12px;
                    width: 100%;
                    padding: 12px 24px;
                    background: var(--accent-blue);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: 700;
                    font-size: 14px;
                    cursor: pointer;
                ">
                    📤 Assign Task
                </button>
            </div>
        </div>
        
        <div class="main-grid">
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>📊</span>
                        Activity Stream
                    </div>
                    <span style="font-size: 12px; color: var(--text-muted);">Last 50 entries</span>
                </div>
                <div class="panel-content" id="activityStream">
                    <div class="empty-state">Loading activities...</div>
                </div>
            </div>
            
            <div style="display: flex; flex-direction: column; gap: 24px;">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">
                            <span>💰</span>
                            Income by Source
                        </div>
                    </div>
                    <div class="panel-content" id="incomeBySource">
                        <div class="empty-state">No income recorded yet</div>
                    </div>
                </div>
                
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">
                            <span>📸</span>
                            Recent Screenshots
                        </div>
                    </div>
                    <div class="panel-content">
                        <div class="screenshots-grid" id="screenshotsGrid">
                            <div class="empty-state">No screenshots yet</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const API_BASE = '';
        
        function formatCurrency(amount) {
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD'
            }).format(amount);
        }
        
        function formatNumber(num) {
            return new Intl.NumberFormat('en-US').format(num);
        }
        
        function formatTime(timestamp) {
            const date = new Date(timestamp);
            return date.toLocaleTimeString('en-US', { 
                hour: '2-digit', 
                minute: '2-digit' 
            });
        }
        
        function getActivityIcon(type) {
            const icons = {
                'action': '⚡',
                'observation': '👁',
                'thought': '💭',
                'goal': '🎯',
                'income': '💵'
            };
            return icons[type] || '📝';
        }
        
        async function fetchStats() {
            try {
                const response = await fetch(`${API_BASE}/api/stats`);
                const data = await response.json();
                
                // Update cards
                document.getElementById('totalIncome').textContent = 
                    formatCurrency(data.income?.total_30d || 0);
                document.getElementById('totalTokens').textContent = 
                    formatNumber(data.tokens?.total_7d || 0);
                document.getElementById('tokenCost').textContent = 
                    formatCurrency(data.tokens?.cost_7d || 0) + ' cost';
                document.getElementById('efficiency').textContent = 
                    formatCurrency(data.efficiency?.income_per_1k_tokens || 0);
                
                // Update income by source
                const incomeContainer = document.getElementById('incomeBySource');
                const sources = data.income?.by_source || {};
                
                if (Object.keys(sources).length > 0) {
                    incomeContainer.innerHTML = Object.entries(sources)
                        .map(([source, amount]) => `
                            <div class="income-item">
                                <span class="income-source">${source.replace('_', ' ')}</span>
                                <span class="income-amount">${formatCurrency(amount)}</span>
                            </div>
                        `).join('');
                }
            } catch (error) {
                console.error('Failed to fetch stats:', error);
            }
        }
        
        async function fetchActivities() {
            try {
                const response = await fetch(`${API_BASE}/api/memories?limit=50`);
                const data = await response.json();
                
                const container = document.getElementById('activityStream');
                const memories = data.memories || [];
                
                if (memories.length > 0) {
                    container.innerHTML = memories.map(m => `
                        <div class="activity-item">
                            <div class="activity-icon ${m.type}">
                                ${getActivityIcon(m.type)}
                            </div>
                            <div class="activity-content">
                                <div class="activity-type">${m.type}</div>
                                <div class="activity-text">${m.content}</div>
                            </div>
                            <div class="activity-time">${formatTime(m.timestamp)}</div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No activity yet</div>';
                }
            } catch (error) {
                console.error('Failed to fetch activities:', error);
            }
        }
        
        async function fetchScreenshots() {
            try {
                const response = await fetch(`${API_BASE}/api/screenshots?limit=8`);
                const data = await response.json();
                
                const container = document.getElementById('screenshotsGrid');
                const screenshots = data.screenshots || [];
                
                if (screenshots.length > 0) {
                    container.innerHTML = screenshots.map(s => `
                        <div class="screenshot-thumb" onclick="window.open('${s.path}', '_blank')">
                            <img src="${s.path}" alt="${s.filename}" loading="lazy">
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No screenshots yet</div>';
                }
            } catch (error) {
                console.error('Failed to fetch screenshots:', error);
            }
        }
        
        async function fetchStatus() {
            try {
                const response = await fetch(`${API_BASE}/api/status`);
                const data = await response.json();
                
                const dot = document.getElementById('statusDot');
                const text = document.getElementById('statusText');
                
                if (data.is_running) {
                    dot.classList.remove('offline');
                    text.textContent = 'Running';
                    
                    if (data.current_session?.id) {
                        text.textContent = `Session: ${data.current_session.id}`;
                    }
                    
                    document.getElementById('sessions').textContent = 
                        data.total_sessions || 0;
                } else {
                    dot.classList.add('offline');
                    text.textContent = 'Offline';
                }
            } catch (error) {
                document.getElementById('statusDot').classList.add('offline');
                document.getElementById('statusText').textContent = 'Disconnected';
            }
        }
        
        async function fetchAgents() {
            try {
                const response = await fetch(`${API_BASE}/api/agents`);
                const data = await response.json();
                
                document.getElementById('agentCount').textContent = data.claude_instances || 0;
                
                const startBtn = document.getElementById('startBtn');
                const stopBtn = document.getElementById('stopBtn');
                
                if (data.watcher_running) {
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                } else {
                    startBtn.disabled = false;
                    stopBtn.disabled = true;
                }
            } catch (error) {
                console.error('Failed to fetch agents:', error);
            }
        }
        
        async function fetchAgentStatuses() {
            try {
                const response = await fetch(`${API_BASE}/api/agent-statuses`);
                const data = await response.json();
                
                let activeCount = 0;
                
                for (const [agentId, status] of Object.entries(data.agents || {})) {
                    const dot = document.getElementById(`${agentId}-dot`);
                    const tasksEl = document.getElementById(`${agentId}-tasks`);
                    const card = document.querySelector(`.agent-card[data-agent="${agentId}"]`);
                    
                    if (dot) {
                        dot.classList.remove('offline', 'working');
                        if (status.status === 'working') {
                            dot.classList.add('working');
                            card?.classList.add('active');
                            activeCount++;
                        } else if (status.status === 'online' || status.status === 'idle') {
                            card?.classList.add('active');
                            activeCount++;
                        } else {
                            dot.classList.add('offline');
                            card?.classList.remove('active');
                        }
                    }
                    
                    if (tasksEl) {
                        tasksEl.textContent = status.tasks_completed || 0;
                    }
                }
                
                document.getElementById('agentCount').textContent = activeCount;

                // Handle rate limit banner
                const rateLimitBanner = document.getElementById('rateLimitBanner');
                const rateLimit = data.rate_limit;
                if (rateLimit && rateLimit.limited) {
                    rateLimitBanner.style.display = 'flex';
                    document.getElementById('rateLimitProvider').textContent =
                        rateLimit.provider.charAt(0).toUpperCase() + rateLimit.provider.slice(1);

                    // Format countdown
                    const remaining = rateLimit.remaining_seconds;
                    const mins = Math.floor(remaining / 60);
                    const secs = remaining % 60;
                    document.getElementById('rateLimitCountdown').textContent =
                        `${mins}:${secs.toString().padStart(2, '0')}`;
                } else {
                    rateLimitBanner.style.display = 'none';
                }
            } catch (error) {
                console.error('Failed to fetch agent statuses:', error);
            }
        }

        async function fetchProviders() {
            try {
                const response = await fetch(`${API_BASE}/api/agent-providers`);
                const data = await response.json();
                const providers = data.providers || [];

                const grid = document.getElementById('providerGrid');
                const subtitle = document.getElementById('providerSubtitle');
                if (subtitle && data.default_provider) {
                    subtitle.textContent = `Default: ${data.default_provider} (auto fallback to codex on rate limit)`;
                }

                if (providers.length === 0) {
                    grid.innerHTML = '<div class="empty-state">No providers configured</div>';
                    return;
                }

                grid.innerHTML = providers.map(p => {
                    const override = (p.provider_override || 'default').toLowerCase();
                    const active = p.active_provider ? `Active: ${p.active_provider}` : 'Active: idle';
                    const statusClass = p.active_provider ? 'provider-status active' : 'provider-status';
                    return `
                        <div class="provider-card">
                            <div class="provider-name">${p.agent_id}</div>
                            <select class="provider-select" id="provider-${p.agent_id}" onchange="updateProvider('${p.agent_id}')">
                                <option value="default" ${override === 'default' ? 'selected' : ''}>default</option>
                                <option value="claude" ${override === 'claude' ? 'selected' : ''}>claude</option>
                                <option value="codex" ${override === 'codex' ? 'selected' : ''}>codex</option>
                            </select>
                            <div class="${statusClass}" id="provider-status-${p.agent_id}">${active}</div>
                        </div>
                    `;
                }).join('');
            } catch (error) {
                console.error('Failed to fetch providers:', error);
            }
        }

        async function updateProvider(agentId) {
            const select = document.getElementById(`provider-${agentId}`);
            const statusEl = document.getElementById(`provider-status-${agentId}`);
            if (!select) {
                return;
            }
            const provider = select.value;
            select.disabled = true;
            if (statusEl) {
                statusEl.textContent = 'Updating...';
            }

            try {
                const response = await fetch(`${API_BASE}/api/agent/provider/${agentId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({provider})
                });
                const data = await response.json();
                if (!data.success) {
                    alert(`Failed to update ${agentId}: ${data.error}`);
                } else if (statusEl) {
                    statusEl.textContent = data.message || 'Updated';
                }
            } catch (error) {
                alert(`Error updating ${agentId}: ${error}`);
            } finally {
                select.disabled = false;
                fetchProviders();
                fetchAgentStatuses();
            }
        }
        
        async function fetchTasks() {
            try {
                const response = await fetch(`${API_BASE}/api/tasks?status=pending`);
                const data = await response.json();
                
                document.getElementById('taskCount').textContent = data.tasks?.length || 0;
            } catch (error) {
                console.error('Failed to fetch tasks:', error);
            }
        }
        
        async function startSpecificAgent(agentType) {
            try {
                const response = await fetch(`${API_BASE}/api/agent/start/${agentType}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.status === 'started' || data.status === 'already_running') {
                    setTimeout(() => {
                        fetchAgentStatuses();
                    }, 2000);
                } else {
                    alert('Failed to start ' + agentType + ': ' + data.message);
                }
            } catch (error) {
                alert('Error starting agent: ' + error);
            }
        }
        
        async function stopSpecificAgent(agentType) {
            try {
                const response = await fetch(`${API_BASE}/api/agent/stop/${agentType}`, { method: 'POST' });
                const data = await response.json();
                
                setTimeout(() => {
                    fetchAgentStatuses();
                }, 1000);
            } catch (error) {
                alert('Error stopping agent: ' + error);
            }
        }
        
        async function startAgent() {
            const btn = document.getElementById('startBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Starting...';
            
            try {
                const response = await fetch(`${API_BASE}/api/agent/start`, { method: 'POST' });
                const data = await response.json();
                
                if (data.status === 'started' || data.status === 'already_running') {
                    btn.textContent = '✓ Started';
                    setTimeout(() => {
                        btn.textContent = '▶ Start';
                        fetchAgents();
                        fetchStatus();
                    }, 1500);
                } else {
                    alert('Failed to start: ' + data.message);
                    btn.textContent = '▶ Start';
                    btn.disabled = false;
                }
            } catch (error) {
                alert('Error starting agent: ' + error);
                btn.textContent = '▶ Start';
                btn.disabled = false;
            }
        }
        
        async function stopAgent() {
            const btn = document.getElementById('stopBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Stopping...';
            
            try {
                const response = await fetch(`${API_BASE}/api/agent/stop`, { method: 'POST' });
                const data = await response.json();
                
                btn.textContent = '✓ Stopped';
                setTimeout(() => {
                    btn.textContent = '⏹ Stop';
                    fetchAgents();
                    fetchStatus();
                }, 1500);
            } catch (error) {
                alert('Error stopping agent: ' + error);
                btn.textContent = '⏹ Stop';
                btn.disabled = false;
            }
        }
        
        async function fetchDiscussions() {
            try {
                const response = await fetch(`${API_BASE}/api/discussions?limit=50`);
                const data = await response.json();
                
                const container = document.getElementById('swarmDiscussion');
                const discussions = data.discussions || [];
                
                if (discussions.length > 0) {
                    container.innerHTML = discussions.reverse().map(d => {
                        const time = d.created_at ? d.created_at.split('T')[1]?.substring(0,8) || '' : '';
                        const isReply = d.in_reply_to ? '↳ ' : '';
                        const agentColors = {
                            'hunter': '#00ff88',
                            'critic': '#ff6b35',
                            'builder': '#00a8ff',
                            'tester': '#a855f7',
                            'publisher': '#ffcc00',
                            'meta': '#ff00ff',
                            'system': '#888'
                        };
                        const color = agentColors[d.author] || '#888';
                        return `
                            <div class="activity-item" style="border-left: 3px solid ${color}; padding-left: 12px;">
                                <div class="activity-content">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <span style="color: ${color}; font-weight: 600; font-size: 12px;">${isReply}${d.author.toUpperCase()}</span>
                                        <span class="activity-time">${time}</span>
                                    </div>
                                    <div class="activity-text" style="margin-top: 4px;">${d.content}</div>
                                    ${d.topic !== 'general' ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 4px;">📌 ${d.topic}</div>` : ''}
                                </div>
                            </div>
                        `;
                    }).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No discussions yet. Agents will start debating soon!</div>';
                }
            } catch (error) {
                console.error('Failed to fetch discussions:', error);
            }
        }
        
        async function fetchProposals() {
            try {
                const response = await fetch(`${API_BASE}/api/proposals?status=open`);
                const data = await response.json();
                
                const container = document.getElementById('proposalsList');
                const proposals = data.proposals || [];
                
                if (proposals.length > 0) {
                    container.innerHTML = proposals.map(p => {
                        const votesFor = p.votes_for?.length || 0;
                        const votesAgainst = p.votes_against?.length || 0;
                        const total = votesFor + votesAgainst;
                        const pct = total > 0 ? Math.round((votesFor / total) * 100) : 0;
                        
                        const typeIcons = {
                            'new_agent': '🤖',
                            'modify_agent': '✏️',
                            'kill_agent': '💀',
                            'pivot': '🔄',
                            'rule_change': '📜',
                            'new_skill': '🛠️'
                        };
                        const icon = typeIcons[p.proposal_type] || '📋';
                        
                        return `
                            <div class="activity-item" style="border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                                <div style="flex: 1;">
                                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                                        <span style="font-size: 18px;">${icon}</span>
                                        <span style="font-weight: 600;">${p.title}</span>
                                    </div>
                                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 8px;">${p.description.substring(0, 100)}${p.description.length > 100 ? '...' : ''}</div>
                                    <div style="display: flex; align-items: center; gap: 12px; font-size: 12px;">
                                        <span style="color: var(--accent-green);">👍 ${votesFor}</span>
                                        <span style="color: var(--accent-red);">👎 ${votesAgainst}</span>
                                        <span style="color: var(--text-muted);">by ${p.proposed_by}</span>
                                        <div style="flex: 1; height: 4px; background: var(--bg-secondary); border-radius: 2px; overflow: hidden;">
                                            <div style="width: ${pct}%; height: 100%; background: ${pct >= 60 ? 'var(--accent-green)' : 'var(--accent-orange)'}"></div>
                                        </div>
                                        <span style="color: var(--text-muted);">${pct}%</span>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No open proposals. Agents can propose changes anytime!</div>';
                }
            } catch (error) {
                console.error('Failed to fetch proposals:', error);
            }
        }

        // Fetch agent learnings and performance stats
        async function fetchLearnings() {
            try {
                const response = await fetch(`${API_BASE}/api/outcomes/stats?days=30`);
                const data = await response.json();

                const container = document.getElementById('learningsPanel');
                const byAgent = data.by_agent || [];
                const failures = data.recent_failures || [];

                if (byAgent.length === 0 && failures.length === 0) {
                    container.innerHTML = '<div class="empty-state">No task outcomes recorded yet. Agents will start learning soon!</div>';
                    return;
                }

                let html = '';

                // Agent performance table
                if (byAgent.length > 0) {
                    html += `
                        <div style="margin-bottom: 16px;">
                            <div style="font-weight: 600; margin-bottom: 8px; color: var(--text-secondary);">Agent Performance (Last 30 Days)</div>
                            <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
                                <thead>
                                    <tr style="border-bottom: 1px solid var(--border-color);">
                                        <th style="text-align: left; padding: 8px 4px;">Agent</th>
                                        <th style="text-align: right; padding: 8px 4px;">Tasks</th>
                                        <th style="text-align: right; padding: 8px 4px;">Success</th>
                                        <th style="text-align: right; padding: 8px 4px;">Rate</th>
                                        <th style="text-align: left; padding: 8px 4px; width: 100px;"></th>
                                    </tr>
                                </thead>
                                <tbody>
                    `;

                    byAgent.forEach(agent => {
                        const rate = agent.total > 0 ? Math.round((agent.success / agent.total) * 100) : 0;
                        const rateColor = rate >= 80 ? 'var(--accent-green)' : rate >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                        html += `
                            <tr style="border-bottom: 1px solid var(--border-color);">
                                <td style="padding: 8px 4px; font-weight: 500;">${escapeHtml(agent.agent_id)}</td>
                                <td style="text-align: right; padding: 8px 4px;">${agent.total}</td>
                                <td style="text-align: right; padding: 8px 4px; color: var(--accent-green);">${agent.success}</td>
                                <td style="text-align: right; padding: 8px 4px; color: ${rateColor};">${rate}%</td>
                                <td style="padding: 8px 4px;">
                                    <div style="height: 8px; background: var(--bg-secondary); border-radius: 4px; overflow: hidden;">
                                        <div style="width: ${rate}%; height: 100%; background: ${rateColor};"></div>
                                    </div>
                                </td>
                            </tr>
                        `;
                    });

                    html += '</tbody></table></div>';
                }

                // Recent failures
                if (failures.length > 0) {
                    html += `
                        <div>
                            <div style="font-weight: 600; margin-bottom: 8px; color: var(--accent-red);">Recent Failures</div>
                    `;

                    failures.forEach(f => {
                        const time = new Date(f.created_at).toLocaleString();
                        html += `
                            <div style="background: rgba(255, 71, 87, 0.1); border-radius: 6px; padding: 10px; margin-bottom: 8px; border-left: 3px solid var(--accent-red);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                    <span style="font-weight: 500;">${escapeHtml(f.agent_id)}</span>
                                    <span style="font-size: 11px; color: var(--text-muted);">${time}</span>
                                </div>
                                <div style="font-size: 12px; color: var(--text-secondary);">
                                    <span style="color: var(--accent-purple);">${escapeHtml(f.task_type)}</span>
                                    ${f.error_summary ? ` - ${escapeHtml(f.error_summary)}` : ''}
                                </div>
                                ${f.context_summary ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">${escapeHtml(f.context_summary.substring(0, 100))}${f.context_summary.length > 100 ? '...' : ''}</div>` : ''}
                            </div>
                        `;
                    });

                    html += '</div>';
                }

                container.innerHTML = html;
            } catch (error) {
                console.error('Failed to fetch learnings:', error);
                document.getElementById('learningsPanel').innerHTML = '<div class="empty-state">Error loading learnings</div>';
            }
        }

        // Fetch human approval queue
        async function fetchApprovals() {
            try {
                const response = await fetch(`${API_BASE}/api/approvals`);
                const data = await response.json();
                
                // Update pending count badge
                const countBadge = document.getElementById('pendingCount');
                countBadge.textContent = data.pending_count || 0;
                countBadge.style.display = (data.pending_count || 0) > 0 ? 'inline-block' : 'none';
                
                const container = document.getElementById('approvalQueue');
                const approvals = data.approvals || [];
                
                // Only show pending and recently reviewed items
                const relevant = approvals.filter(a => a.status === 'pending' || 
                    (new Date() - new Date(a.reviewed_at) < 3600000)); // Last hour
                
                if (relevant.length > 0) {
                    container.innerHTML = relevant.map(a => {
                        const isPending = a.status === 'pending';
                        const statusColors = {
                            'pending': 'var(--accent-orange)',
                            'approved': 'var(--accent-green)',
                            'rejected': 'var(--accent-red)',
                            'published': 'var(--accent-blue)'
                        };
                        const statusIcons = {
                            'pending': '⏳',
                            'approved': '✅',
                            'rejected': '❌',
                            'published': '🚀'
                        };
                        const platformIcons = {
                            'gumroad': '🛒',
                            'github': '🐙',
                            'npm': '📦',
                            'devto': '✍️',
                            'lemonsqueezy': '🍋'
                        };
                        
                        const time = a.created_at ? new Date(a.created_at).toLocaleString() : '';
                        
                        return `
                            <div class="approval-item" style="
                                border: 2px solid ${statusColors[a.status]};
                                border-radius: 12px;
                                padding: 16px;
                                margin-bottom: 12px;
                                background: ${isPending ? 'rgba(255, 107, 53, 0.05)' : 'transparent'};
                            ">
                                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                                    <div>
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                                            <span style="font-size: 20px;">${platformIcons[a.platform] || '📋'}</span>
                                            <span style="font-weight: 700; font-size: 16px;">${a.product_name}</span>
                                            ${a.price ? `<span style="background: var(--accent-green); color: black; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">${a.price}</span>` : ''}
                                        </div>
                                        <div style="font-size: 12px; color: var(--text-secondary);">
                                            ${a.product_type} → ${a.platform} • by ${a.submitted_by} • ${time}
                                        </div>
                                    </div>
                                    <span style="
                                        background: ${statusColors[a.status]};
                                        color: ${a.status === 'pending' ? 'black' : 'white'};
                                        padding: 4px 12px;
                                        border-radius: 20px;
                                        font-size: 12px;
                                        font-weight: 600;
                                    ">${statusIcons[a.status]} ${a.status.toUpperCase()}</span>
                                </div>
                                
                                <div style="font-size: 14px; color: var(--text-primary); margin-bottom: 12px; line-height: 1.5;">
                                    ${a.description}
                                </div>
                                
                                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
                                    📁 Files: <code style="background: var(--bg-secondary); padding: 2px 6px; border-radius: 4px;">${a.files_path}</code>
                                </div>
                                
                                ${isPending ? `
                                    <div style="display: flex; gap: 12px; margin-top: 16px;">
                                        <button onclick="approveItem('${a.id}', '${a.product_name}')" style="
                                            flex: 1;
                                            padding: 12px 24px;
                                            background: var(--accent-green);
                                            color: black;
                                            border: none;
                                            border-radius: 8px;
                                            font-weight: 700;
                                            font-size: 14px;
                                            cursor: pointer;
                                            transition: all 0.2s;
                                        " onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'">
                                            ✅ APPROVE & PUBLISH
                                        </button>
                                        <button onclick="rejectItem('${a.id}', '${a.product_name}')" style="
                                            padding: 12px 24px;
                                            background: transparent;
                                            color: var(--accent-red);
                                            border: 2px solid var(--accent-red);
                                            border-radius: 8px;
                                            font-weight: 700;
                                            font-size: 14px;
                                            cursor: pointer;
                                            transition: all 0.2s;
                                        " onmouseover="this.style.background='rgba(255,71,87,0.1)'" onmouseout="this.style.background='transparent'">
                                            ❌ REJECT
                                        </button>
                                    </div>
                                ` : (a.reviewer_notes ? `
                                    <div style="font-size: 12px; color: var(--text-secondary); font-style: italic; border-top: 1px solid var(--border-color); padding-top: 12px; margin-top: 8px;">
                                        💬 ${a.reviewer_notes}
                                    </div>
                                ` : '')}
                            </div>
                        `;
                    }).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No items pending approval. Products will appear here after Tester validates them.</div>';
                }
            } catch (error) {
                console.error('Failed to fetch approvals:', error);
            }
        }
        
        // Approve item
        async function approveItem(itemId, productName) {
            if (!confirm(`Approve "${productName}" for publishing?`)) return;
            
            const notes = prompt('Optional notes (leave blank for none):') || '';
            
            try {
                const response = await fetch(`${API_BASE}/api/approvals/${itemId}/approve`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({notes})
                });
                
                const data = await response.json();
                if (data.success) {
                    alert(`✅ Approved! Publisher agent will now deploy "${productName}".`);
                    fetchApprovals();
                } else {
                    alert(`Error: ${data.error}`);
                }
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }
        
        // Reject item
        async function rejectItem(itemId, productName) {
            const reason = prompt(`Why are you rejecting "${productName}"?`);
            if (!reason) return;
            
            try {
                const response = await fetch(`${API_BASE}/api/approvals/${itemId}/reject`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reason})
                });
                
                const data = await response.json();
                if (data.success) {
                    alert(`❌ Rejected. The agents will be notified.`);
                    fetchApprovals();
                } else {
                    alert(`Error: ${data.error}`);
                }
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }
        
        // Chat with swarm
        async function sendChat() {
            const input = document.getElementById('chatInput');
            const message = input.value.trim();
            if (!message) return;
            
            input.value = '';
            
            // Add message to UI immediately
            addChatMessage('human', message);
            
            try {
                const response = await fetch(`${API_BASE}/api/chat`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message})
                });
                
                const data = await response.json();
                if (!data.success) {
                    addChatMessage('system', `Error: ${data.error}`);
                }
            } catch (error) {
                addChatMessage('system', `Error: ${error.message}`);
            }
        }
        
        function sendQuickChat(message) {
            document.getElementById('chatInput').value = message;
            sendChat();
        }
        
        function addChatMessage(author, content) {
            const container = document.getElementById('chatMessages');
            const isHuman = author === 'human';
            const isLiaison = author === 'liaison';
            
            const colors = {
                'human': 'var(--accent-purple)',
                'liaison': 'var(--accent-green)',
                'system': 'var(--text-muted)'
            };
            
            const html = `
                <div style="
                    display: flex;
                    flex-direction: column;
                    align-items: ${isHuman ? 'flex-end' : 'flex-start'};
                ">
                    <div style="
                        max-width: 80%;
                        padding: 10px 14px;
                        border-radius: 12px;
                        background: ${isHuman ? 'var(--accent-purple)' : 'var(--bg-secondary)'};
                        color: ${isHuman ? 'white' : 'var(--text-primary)'};
                        border: ${isLiaison ? '2px solid var(--accent-green)' : 'none'};
                    ">
                        ${!isHuman ? `<div style="font-size: 10px; color: ${colors[author]}; font-weight: 600; margin-bottom: 4px;">${author.toUpperCase()}</div>` : ''}
                        <div style="font-size: 14px; line-height: 1.4;">${content}</div>
                    </div>
                </div>
            `;
            
            // Remove empty state if present
            const emptyState = container.querySelector('.empty-state');
            if (emptyState) emptyState.remove();
            
            container.insertAdjacentHTML('beforeend', html);
            container.scrollTop = container.scrollHeight;
        }
        
        async function fetchChat() {
            try {
                const response = await fetch(`${API_BASE}/api/chat`);
                const data = await response.json();
                
                const container = document.getElementById('chatMessages');
                const messages = data.messages || [];
                
                if (messages.length > 0) {
                    container.innerHTML = messages.map(m => {
                        const isHuman = m.author === 'human';
                        const isLiaison = m.author === 'liaison';
                        const colors = {
                            'human': 'var(--accent-purple)',
                            'liaison': 'var(--accent-green)',
                            'system': 'var(--text-muted)'
                        };
                        
                        return `
                            <div style="
                                display: flex;
                                flex-direction: column;
                                align-items: ${isHuman ? 'flex-end' : 'flex-start'};
                            ">
                                <div style="
                                    max-width: 80%;
                                    padding: 10px 14px;
                                    border-radius: 12px;
                                    background: ${isHuman ? 'var(--accent-purple)' : 'var(--bg-secondary)'};
                                    color: ${isHuman ? 'white' : 'var(--text-primary)'};
                                    border: ${isLiaison ? '2px solid var(--accent-green)' : 'none'};
                                ">
                                    ${!isHuman ? `<div style="font-size: 10px; color: ${colors[m.author] || 'var(--text-muted)'}; font-weight: 600; margin-bottom: 4px;">${m.author.toUpperCase()}</div>` : ''}
                                    <div style="font-size: 14px; line-height: 1.4;">${m.content}</div>
                                </div>
                            </div>
                        `;
                    }).join('');
                    container.scrollTop = container.scrollHeight;
                }
            } catch (error) {
                console.error('Failed to fetch chat:', error);
            }
        }
        
        // Send a quick directive to the swarm
        async function sendDirective(message) {
            try {
                const response = await fetch(`${API_BASE}/api/directive`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message, priority: 10})
                });
                
                const data = await response.json();
                if (data.success) {
                    alert(`📢 Directive sent to all agents!`);
                    fetchDiscussions();
                } else {
                    alert(`Error: ${data.error}`);
                }
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }
        
        // Create a task for a specific agent
        async function createTask() {
            const description = document.getElementById('taskDescription').value.trim();
            const agent = document.getElementById('taskAgent').value;
            const priority = parseInt(document.getElementById('taskPriority').value);
            const repoId = document.getElementById('taskRepo').value || null;

            if (!description) {
                alert('Please enter a task description');
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/api/tasks`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        type: 'directive',
                        to: agent,
                        priority: priority,
                        repo_id: repoId,
                        payload: {
                            instruction: description,
                            from: 'human',
                            urgent: priority >= 9,
                            repo_id: repoId
                        }
                    })
                });

                const data = await response.json();
                if (data.task_id) {
                    const repoText = repoId ? ` (Repo: ${repoId})` : '';
                    alert(`✅ Task sent to ${agent.toUpperCase()}!${repoText}`);
                    document.getElementById('taskDescription').value = '';
                    fetchTasks();
                } else {
                    alert(`Error: ${data.error || 'Unknown error'}`);
                }
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }

        // Load agent cards dynamically from settings.yaml
        async function loadAgentCards() {
            try {
                const response = await fetch(`${API_BASE}/api/agent-config`);
                const data = await response.json();
                const container = document.getElementById('agentCards');

                if (!data.agents || data.agents.length === 0) {
                    container.innerHTML = '<div class="empty-state">No agents configured</div>';
                    return;
                }

                // Calculate grid columns based on agent count
                const cols = Math.min(data.agents.length, 8);
                container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

                container.innerHTML = data.agents.map(agent => `
                    <div class="agent-card" data-agent="${agent.id}">
                        <div class="agent-header">
                            <span class="agent-icon">${agent.icon}</span>
                            <span class="agent-name">${agent.name}</span>
                            <span class="agent-status-dot offline" id="${agent.id}-dot"></span>
                        </div>
                        <div class="agent-role">${agent.description.substring(0, 40)}${agent.description.length > 40 ? '...' : ''}</div>
                        <div class="agent-stats">
                            <span>Tasks: <strong id="${agent.id}-tasks">0</strong></span>
                        </div>
                        <div class="agent-actions">
                            <button class="agent-btn start" onclick="startSpecificAgent('${agent.id}')">▶</button>
                            <button class="agent-btn stop" onclick="stopSpecificAgent('${agent.id}')">⏹</button>
                        </div>
                    </div>
                `).join('');

                // Update agent count
                document.getElementById('agentCount').textContent = data.agents.length;
            } catch (error) {
                console.error('Error loading agent cards:', error);
            }
        }

        // Populate agent dropdown in task form
        async function loadTaskAgentDropdown() {
            try {
                const response = await fetch(`${API_BASE}/api/agent-config`);
                const data = await response.json();
                const select = document.getElementById('taskAgent');

                if (!data.agents || data.agents.length === 0) return;

                select.innerHTML = data.agents.map(agent =>
                    `<option value="${agent.id}">${agent.icon} ${agent.name}</option>`
                ).join('');
            } catch (error) {
                console.error('Error loading task agent dropdown:', error);
            }
        }

        // Populate repo dropdown in task form
        async function loadTaskRepoDropdown() {
            try {
                const response = await fetch(`${API_BASE}/api/repos`);
                const data = await response.json();
                const select = document.getElementById('taskRepo');

                select.innerHTML = '<option value="">Global / All Repos</option>';
                if (data.repos && data.repos.length > 0) {
                    select.innerHTML += data.repos.map(repo =>
                        `<option value="${repo.id}">${repo.name}</option>`
                    ).join('');
                }
            } catch (error) {
                console.error('Error loading repo dropdown:', error);
            }
        }

        // Load repository summary for dashboard widget
        async function loadRepoSummary() {
            try {
                const response = await fetch(`${API_BASE}/api/repos`);
                const data = await response.json();
                const container = document.getElementById('repoSummary');

                if (!data.repos || data.repos.length === 0) {
                    container.innerHTML = '<div class="empty-state">No repositories configured. <a href="/repos" style="color: var(--accent-blue);">Add one →</a></div>';
                    return;
                }

                container.innerHTML = data.repos.slice(0, 5).map(repo => `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                        <div>
                            <div style="font-weight: 600; color: var(--text-primary);">${repo.name}</div>
                            <div style="font-size: 11px; color: var(--text-muted);">${repo.url || repo.gitlab_path || ''}</div>
                        </div>
                        <div style="text-align: right;">
                            <span style="font-size: 11px; padding: 2px 8px; background: ${repo.autonomy_mode === 'full' ? 'var(--accent-green-dim)' : 'var(--bg-secondary)'}; border-radius: 4px; color: ${repo.autonomy_mode === 'full' ? 'var(--accent-green)' : 'var(--text-secondary)'};">
                                ${repo.autonomy_mode || 'guided'}
                            </span>
                        </div>
                    </div>
                `).join('');

                if (data.repos.length > 5) {
                    container.innerHTML += `<div style="text-align: center; padding: 8px; font-size: 12px; color: var(--text-muted);">+${data.repos.length - 5} more repositories</div>`;
                }
            } catch (error) {
                console.error('Error loading repo summary:', error);
                document.getElementById('repoSummary').innerHTML = '<div class="empty-state">Error loading repositories</div>';
            }
        }

        // Initial load
        loadAgentCards();
        loadTaskAgentDropdown();
        loadTaskRepoDropdown();
        loadRepoSummary();
        fetchStats();
        fetchActivities();
        fetchScreenshots();
        fetchStatus();
        fetchAgents();
        fetchAgentStatuses();
        fetchProviders();
        fetchTasks();
        fetchDiscussions();
        fetchProposals();
        fetchLearnings();
        fetchApprovals();
        fetchChat();
        
        // Refresh every 5 seconds
        setInterval(() => {
            fetchStats();
            fetchActivities();
            fetchStatus();
            fetchAgents();
            fetchAgentStatuses();
            fetchProviders();
            fetchTasks();
            fetchDiscussions();
            fetchProposals();
            fetchLearnings();
            fetchApprovals();
            fetchChat();
        }, 5000);
        
        // Screenshots refresh every 30 seconds
        setInterval(fetchScreenshots, 30000);
        
        // WebSocket for real-time updates
        function connectWebSocket() {
            const ws = new WebSocket(`ws://${window.location.host}/ws`);
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'stats') {
                    // Update with real-time data
                    const stats = data.data;
                    document.getElementById('totalIncome').textContent = 
                        formatCurrency(stats.income?.total_30d || 0);
                    document.getElementById('totalTokens').textContent = 
                        formatNumber(stats.tokens?.total_7d || 0);
                }
            };
            
            ws.onclose = () => {
                setTimeout(connectWebSocket, 5000);
            };
        }
        
        connectWebSocket();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
