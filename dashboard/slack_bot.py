"""
Slack Bot Service for Auto-Dev
==============================

Provides slash command interface to control the swarm from Slack.

Commands:
    /swarm status     - Queue stats, agent status, current tasks
    /swarm tasks      - List pending tasks with IDs
    /swarm cancel <id> - Cancel a pending/claimed task
    /swarm priority <id> <1-10> - Change task priority
    /swarm agents     - Show all agent statuses
    /swarm restart <agent> - Restart specific agent
    /swarm approve <id> - Approve item in approval queue
    /swarm reject <id> <reason> - Reject item
    /swarm tell <message> - Send directive to Liaison agent

Run with: uvicorn dashboard.slack_bot:app --host 0.0.0.0 --port 8081
"""

import hashlib
import hmac
import time
import logging
import subprocess
import json
import sqlite3
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Form, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from watcher.orchestrator import get_orchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Swarm Control Slack Bot")

# ============================================================================
# Configuration - loaded from AWS SSM
# ============================================================================

_config_cache = {}

def get_ssm_parameter(name: str) -> Optional[str]:
    """Fetch parameter from AWS SSM Parameter Store."""
    if name in _config_cache:
        return _config_cache[name]
    
    try:
        result = subprocess.run(
            ["aws", "ssm", "get-parameter", "--name", name, "--with-decryption", "--query", "Parameter.Value", "--output", "text"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            _config_cache[name] = value
            return value
    except Exception as e:
        logger.error(f"Failed to get SSM parameter {name}: {e}")
    return None


def get_signing_secret() -> str:
    return get_ssm_parameter("/auto-dev/slack/signing_secret") or ""


def get_bot_token() -> str:
    return get_ssm_parameter("/auto-dev/slack/bot_token") or ""


def get_allowed_users() -> set:
    users = get_ssm_parameter("/auto-dev/slack/allowed_users") or ""
    return set(u.strip() for u in users.split(",") if u.strip())


# ============================================================================
# Security - Slack Request Verification
# ============================================================================

def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify that the request came from Slack using HMAC-SHA256.
    
    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    signing_secret = get_signing_secret()
    if not signing_secret:
        logger.error("No signing secret configured")
        return False
    
    # Check timestamp to prevent replay attacks (allow 5 min window)
    try:
        req_timestamp = int(timestamp)
        if abs(time.time() - req_timestamp) > 300:
            logger.warning("Request timestamp too old")
            return False
    except ValueError:
        return False
    
    # Create signature base string
    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    
    # Calculate expected signature
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(my_signature, signature)


def is_user_allowed(user_id: str) -> bool:
    """Check if user is in the allowed list."""
    allowed = get_allowed_users()
    if not allowed:
        logger.warning("No allowed users configured - denying all")
        return False
    return user_id in allowed


# ============================================================================
# Slack API Helpers
# ============================================================================

async def send_slack_message(channel: str, text: str, blocks: Optional[list] = None):
    """Send a message to Slack."""
    bot_token = get_bot_token()
    if not bot_token:
        logger.error("No bot token configured")
        return
    
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={
                "channel": channel,
                "text": text,
                "blocks": blocks
            }
        )


def format_response(text: str) -> dict:
    """Format a simple text response for Slack."""
    return {
        "response_type": "in_channel",
        "text": text
    }


def format_error(text: str) -> dict:
    """Format an error response (ephemeral - only visible to user)."""
    return {
        "response_type": "ephemeral",
        "text": f"❌ {text}"
    }


# ============================================================================
# Command Handlers
# ============================================================================

def cmd_status() -> str:
    """Get swarm status overview with rich formatting."""
    orchestrator = get_orchestrator()
    stats = orchestrator.get_queue_stats()
    
    # Get agent statuses from files
    agents_running = 0
    agents_stopped = 0
    agents_paused = 0
    status_dir = Path("/auto-dev/data")
    for f in status_dir.glob("watcher_status_*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("rate_limit", {}).get("limited"):
                agents_paused += 1
            elif data.get("is_running"):
                agents_running += 1
            else:
                agents_stopped += 1
        except:
            pass
    
    # Get currently claimed tasks
    claimed = []
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT assigned_to, type, payload FROM tasks 
            WHERE status = 'claimed' 
            ORDER BY claimed_at DESC LIMIT 5
        """)
        for row in cursor.fetchall():
            payload = json.loads(row['payload']) if row['payload'] else {}
            title = payload.get('title', payload.get('product_name', payload.get('product', 'N/A')))[:25]
            claimed.append(f"  • `{row['assigned_to']}` → {title}")
        conn.close()
    except Exception as e:
        claimed = [f"  Error: {e}"]
    
    # Get pending approvals count
    pending_approvals = len(orchestrator.get_pending_approvals())
    
    # Build status line for agents
    agent_parts = []
    if agents_running > 0:
        agent_parts.append(f"🟢 {agents_running} running")
    if agents_paused > 0:
        agent_parts.append(f"⏸️ {agents_paused} paused")
    if agents_stopped > 0:
        agent_parts.append(f"🔴 {agents_stopped} stopped")
    
    pending = stats.get('by_status', {}).get('pending', 0)
    in_progress = stats.get('by_status', {}).get('claimed', 0)
    completed = stats.get('by_status', {}).get('completed', 0)
    failed = stats.get('by_status', {}).get('failed', 0)
    
    lines = [
        "┌─────────────────────────────────┐",
        "│        *SWARM STATUS*           │",
        "└─────────────────────────────────┘",
        "",
        f"*Agents:* {' · '.join(agent_parts)}",
        "",
        f"*Queue:*",
        f"  ⏳ Pending: `{pending}`  🔄 In Progress: `{in_progress}`",
        f"  ✅ Completed: `{completed}`  ❌ Failed: `{failed}`",
        "",
        "*Active Tasks:*",
    ]
    
    if claimed:
        lines.extend(claimed)
    else:
        lines.append("  _No tasks in progress_")
    
    if pending_approvals > 0:
        lines.append(f"\n📋 *{pending_approvals} items awaiting your approval*")
        lines.append("   Use `/swarm approvals` to review")
    
    return "\n".join(lines)


def cmd_tasks(limit: int = 15) -> str:
    """List pending tasks."""
    orchestrator = get_orchestrator()
    tasks = orchestrator.get_pending_tasks(limit=limit)
    
    if not tasks:
        return "No pending tasks in queue."
    
    lines = ["*Pending Tasks:*", "```"]
    for t in tasks:
        title = t.payload.get('title', t.payload.get('product_name', t.payload.get('product', 'N/A')))[:35]
        assigned = t.assigned_to or "any"
        lines.append(f"{t.id[:8]} | P{t.priority} | {t.type:<15} | {assigned:<10} | {title}")
    lines.append("```")
    
    return "\n".join(lines)


def cmd_cancel(task_id: str) -> str:
    """Cancel a task."""
    orchestrator = get_orchestrator()
    
    # Find task by partial ID
    import sqlite3
    conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
    cursor = conn.execute("SELECT id, type, status FROM tasks WHERE id LIKE ?", (f"{task_id}%",))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return f"No task found matching `{task_id}`"
    if len(rows) > 1:
        return f"Multiple tasks match `{task_id}`. Be more specific."
    
    full_id, task_type, status = rows[0]
    
    if status in ('completed', 'cancelled'):
        return f"Task `{full_id[:8]}` is already {status}."
    
    success = orchestrator.cancel_task(full_id, "Cancelled via Slack", "slack_user")
    if success:
        return f"✓ Cancelled task `{full_id[:8]}` ({task_type})"
    else:
        return f"Failed to cancel task `{full_id[:8]}`"


def cmd_priority(task_id: str, priority: int) -> str:
    """Change task priority."""
    if not 1 <= priority <= 10:
        return "Priority must be between 1 and 10."
    
    import sqlite3
    conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
    cursor = conn.execute("SELECT id, type FROM tasks WHERE id LIKE ? AND status = 'pending'", (f"{task_id}%",))
    rows = cursor.fetchall()
    
    if not rows:
        return f"No pending task found matching `{task_id}`"
    if len(rows) > 1:
        return f"Multiple tasks match `{task_id}`. Be more specific."
    
    full_id, task_type = rows[0]
    conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, full_id))
    conn.commit()
    conn.close()
    
    return f"✓ Set priority of `{full_id[:8]}` ({task_type}) to {priority}"


def cmd_agents() -> str:
    """Show agent statuses."""
    import json
    status_dir = Path("/auto-dev/data")
    
    lines = ["*Agent Status:*", "```"]
    lines.append(f"{'Agent':<12} {'Status':<10} {'Rate Limit':<12} {'Task'}")
    lines.append("-" * 60)
    
    for f in sorted(status_dir.glob("watcher_status_*.json")):
        try:
            data = json.loads(f.read_text())
            agent = data.get("agent_id", "?")
            running = "RUNNING" if data.get("is_running") else "STOPPED"
            rate_info = data.get("rate_limit", {})
            rate_status = "PAUSED" if rate_info.get("limited") else "OK"
            task = data.get("current_task", "-") or "-"
            lines.append(f"{agent:<12} {running:<10} {rate_status:<12} {str(task)[:20]}")
        except:
            pass
    
    lines.append("```")
    return "\n".join(lines)


def cmd_restart(agent: str) -> str:
    """Restart an agent."""
    valid_agents = ["hunter", "critic", "pm", "builder", "reviewer", "tester", "publisher", "meta", "liaison", "support"]
    
    if agent not in valid_agents:
        return f"Unknown agent `{agent}`. Valid: {', '.join(valid_agents)}"
    
    try:
        # Stop then start the agent
        subprocess.run(
            ["ssh", "-i", "/home/ubuntu/.ssh/id_rsa", "localhost", 
             f"cd /auto-dev && ./scripts/start_agents.sh stop {agent} && sleep 2 && ./scripts/start_agents.sh {agent}"],
            timeout=30
        )
        return f"✓ Restarted agent `{agent}`"
    except Exception as e:
        # Try direct approach
        try:
            subprocess.run(
                f"cd /auto-dev && ./scripts/start_agents.sh stop {agent}",
                shell=True, timeout=15
            )
            subprocess.run(
                f"cd /auto-dev && ./scripts/start_agents.sh {agent}",
                shell=True, timeout=15
            )
            return f"✓ Restarted agent `{agent}`"
        except Exception as e2:
            return f"Failed to restart `{agent}`: {e2}"


def cmd_approve(item_id: str) -> str:
    """Approve an item in the approval queue."""
    orchestrator = get_orchestrator()
    
    # Find by partial ID
    pending = orchestrator.get_pending_approvals()
    matches = [p for p in pending if p.id.startswith(item_id)]
    
    if not matches:
        return f"No pending approval matching `{item_id}`"
    if len(matches) > 1:
        return f"Multiple items match `{item_id}`. Be more specific."
    
    item = matches[0]
    success = orchestrator.approve_item(item.id, "Approved via Slack")
    
    if success:
        return f"✓ Approved `{item.product_name}` for publishing on {item.platform}"
    else:
        return f"Failed to approve `{item_id}`"


def cmd_reject(item_id: str, reason: str) -> str:
    """Reject an item in the approval queue."""
    orchestrator = get_orchestrator()
    
    pending = orchestrator.get_pending_approvals()
    matches = [p for p in pending if p.id.startswith(item_id)]
    
    if not matches:
        return f"No pending approval matching `{item_id}`"
    if len(matches) > 1:
        return f"Multiple items match `{item_id}`. Be more specific."
    
    item = matches[0]
    success = orchestrator.reject_item(item.id, reason)
    
    if success:
        return f"✓ Rejected `{item.product_name}`: {reason}"
    else:
        return f"Failed to reject `{item_id}`"


def cmd_tell(message: str) -> str:
    """Send a directive to the Liaison agent."""
    orchestrator = get_orchestrator()
    
    # Create a high-priority task for the liaison agent
    task = orchestrator.create_task(
        task_type="human_directive",
        payload={
            "message": message,
            "source": "slack",
            "priority": "high"
        },
        priority=9,
        created_by="slack_user"
    )
    
    # Also send a message to the liaison agent
    orchestrator.send_message(
        from_agent="human",
        to_agent="liaison",
        message_type="directive",
        payload={"message": message, "source": "slack"}
    )
    
    if task:
        return f"✓ Directive sent to Liaison agent (task `{task.id[:8]}`)"
    else:
        return "✓ Directive sent to Liaison agent"


def cmd_approvals() -> str:
    """List items pending approval."""
    orchestrator = get_orchestrator()
    pending = orchestrator.get_pending_approvals()
    
    if not pending:
        return "No items pending approval."
    
    lines = ["*Pending Approvals:*", "```"]
    for item in pending:
        lines.append(f"{item.id[:8]} | {item.platform:<10} | {item.product_name}")
    lines.append("```")
    lines.append("\nUse `/swarm approve <id>` or `/swarm reject <id> <reason>`")
    
    return "\n".join(lines)


# ============================================================================
# PROJECT PROPOSAL COMMANDS - Rich approval queue for build decisions
# ============================================================================

def cmd_projects(status: str = "pending") -> str:
    """List project proposals awaiting human review."""
    import sqlite3
    
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        cursor = conn.execute("""
            SELECT * FROM project_proposals 
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (status,))
        
        projects = list(cursor.fetchall())
        
        # Get stats
        stats = {}
        for s in ['pending', 'deferred', 'approved', 'rejected']:
            count = conn.execute(
                "SELECT COUNT(*) FROM project_proposals WHERE status = ?", (s,)
            ).fetchone()[0]
            stats[s] = count
        
        conn.close()
        
        if not projects:
            return f"No {status} project proposals.\n\n*Stats:* Pending: {stats['pending']} | Deferred: {stats['deferred']} | Approved: {stats['approved']} | Rejected: {stats['rejected']}"
        
        lines = [f"*Project Proposals ({status}):*", ""]
        
        for p in projects:
            avg_rating = (p['hunter_rating'] + p['critic_rating']) / 2
            rating_emoji = "🟢" if avg_rating >= 7 else "🟡" if avg_rating >= 5 else "🔴"
            
            lines.append(f"{rating_emoji} *{p['title']}* ⭐ {avg_rating:.1f}/10")
            lines.append(f"   💰 {p['max_revenue_estimate']} | ⏱️ {p['effort_estimate']} | 📁 {p['market_size']}")
            lines.append(f"   ID: `{p['id'][:8]}`")
            lines.append("")
        
        lines.append(f"*Stats:* Pending: {stats['pending']} | Deferred: {stats['deferred']} | Approved: {stats['approved']} | Rejected: {stats['rejected']}")
        lines.append("")
        lines.append("Use `/swarm project <id>` for details, or `/swarm approve-project <id>`")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def cmd_project_detail(project_id: str) -> str:
    """Get detailed view of a single project proposal."""
    import sqlite3
    
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        cursor = conn.execute(
            "SELECT * FROM project_proposals WHERE id = ? OR id LIKE ?",
            (project_id, f"{project_id}%")
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return f"Project not found: `{project_id}`"
        
        p = dict(row)
        avg_rating = (p['hunter_rating'] + p['critic_rating']) / 2
        rating_emoji = "🟢" if avg_rating >= 7 else "🟡" if avg_rating >= 5 else "🔴"
        
        # Format cons as bullet list
        cons_lines = [f"  • {c.strip().lstrip('-• ')}" for c in p['cons'].split('\n') if c.strip()]
        cons_text = "\n".join(cons_lines) if cons_lines else "  • None identified"
        
        lines = [
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📋 *{p['title']}*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"{rating_emoji} *Combined Rating:* {avg_rating:.1f}/10",
            f"📊 Status: `{p['status']}`",
            f"",
            f"*🔍 Hunter's Pitch:*",
            f"> _{p['hunter_pitch']}_",
            f"Hunter Rating: {p['hunter_rating']}/10",
            f"",
            f"*🧐 Critic's Take:*",
            f"{p['critic_evaluation']}",
            f"Critic Rating: {p['critic_rating']}/10",
            f"",
            f"*⚠️ Risks/Cons:*",
            cons_text,
            f"",
            f"*✨ Differentiation:*",
            f"{p['differentiation']}",
            f"",
            f"*📊 Metrics:*",
            f"  💰 Max Revenue: *{p['max_revenue_estimate']}*",
            f"  ⏱️ Effort: *{p['effort_estimate']}*",
            f"  📁 Market: *{p['market_size']}*",
            f"",
            f"ID: `{p['id'][:8]}`",
        ]
        
        if p['status'] in ('pending', 'deferred'):
            lines.append("")
            lines.append("*Actions:*")
            lines.append(f"`/swarm approve-project {p['id'][:8]}` - Start building")
            lines.append(f"`/swarm reject-project {p['id'][:8]} <reason>` - Reject")
            if p['status'] == 'pending':
                lines.append(f"`/swarm defer-project {p['id'][:8]}` - Defer to backlog")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def cmd_approve_project(project_id: str) -> str:
    """Approve a project proposal for building."""
    import sqlite3
    import uuid
    from datetime import datetime
    
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        now = datetime.utcnow().isoformat()
        
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'approved', reviewer_notes = 'Approved via Slack', reviewed_at = ?
            WHERE (id = ? OR id LIKE ?) AND status = 'pending'
        """, (now, project_id, f"{project_id}%"))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return f"Project not found or not pending: `{project_id}`"
        
        # Get project details
        cursor = conn.execute(
            "SELECT * FROM project_proposals WHERE id = ? OR id LIKE ?",
            (project_id, f"{project_id}%")
        )
        row = cursor.fetchone()
        
        if row:
            # Create build_product task
            task_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO tasks (id, type, priority, payload, status, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, 'build_product', 8,
                json.dumps({
                    "project_id": row['id'],
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
                f"✅ PROJECT APPROVED via Slack: {row['title']} - Builder will start!",
                now
            ))
            conn.commit()
            
            conn.close()
            return f"✅ *Approved:* {row['title']}\n\nBuilder will start working on this project!"
        
        conn.close()
        return f"✅ Project `{project_id}` approved"
    except Exception as e:
        return f"Error: {e}"


def cmd_reject_project(project_id: str, reason: str) -> str:
    """Reject a project proposal."""
    import sqlite3
    import uuid
    from datetime import datetime
    
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        now = datetime.utcnow().isoformat()
        
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'rejected', reviewer_notes = ?, reviewed_at = ?
            WHERE (id = ? OR id LIKE ?) AND status IN ('pending', 'deferred')
        """, (reason, now, project_id, f"{project_id}%"))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return f"Project not found or already reviewed: `{project_id}`"
        
        # Get project title
        cursor = conn.execute(
            "SELECT title FROM project_proposals WHERE id = ? OR id LIKE ?",
            (project_id, f"{project_id}%")
        )
        row = cursor.fetchone()
        
        if row:
            # Post to discussion
            conn.execute("""
                INSERT INTO discussions (id, author, topic, content, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), 'human', 'projects',
                f"❌ PROJECT REJECTED via Slack: {row['title']} - Reason: {reason}",
                now
            ))
            conn.commit()
        
        conn.close()
        return f"❌ *Rejected:* {row['title'] if row else project_id}\n\nReason: {reason}"
    except Exception as e:
        return f"Error: {e}"


def cmd_defer_project(project_id: str) -> str:
    """Defer a project proposal to backlog."""
    import sqlite3
    import uuid
    from datetime import datetime
    
    try:
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        now = datetime.utcnow().isoformat()
        
        cursor = conn.execute("""
            UPDATE project_proposals 
            SET status = 'deferred', reviewer_notes = 'Deferred via Slack', reviewed_at = ?
            WHERE (id = ? OR id LIKE ?) AND status = 'pending'
        """, (now, project_id, f"{project_id}%"))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return f"Project not found or not pending: `{project_id}`"
        
        # Get project title
        cursor = conn.execute(
            "SELECT title FROM project_proposals WHERE id = ? OR id LIKE ?",
            (project_id, f"{project_id}%")
        )
        row = cursor.fetchone()
        
        if row:
            conn.execute("""
                INSERT INTO discussions (id, author, topic, content, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), 'human', 'projects',
                f"⏸️ PROJECT DEFERRED via Slack: {row['title']} - Moved to backlog",
                now
            ))
            conn.commit()
        
        conn.close()
        return f"⏸️ *Deferred:* {row['title'] if row else project_id}\n\nMoved to backlog. Review later with `/swarm projects deferred`"
    except Exception as e:
        return f"Error: {e}"


def cmd_logs(agent: str, lines: int = 20) -> str:
    """Get recent logs for an agent."""
    valid_agents = ["hunter", "critic", "pm", "builder", "reviewer", "tester", "publisher", "meta", "liaison", "support"]
    
    if agent not in valid_agents:
        return f"Unknown agent `{agent}`. Valid: {', '.join(valid_agents)}"
    
    log_file = Path(f"/auto-dev/logs/{agent}.log")
    if not log_file.exists():
        return f"No log file found for `{agent}`"
    
    try:
        # Read last N lines, filter out deprecation warnings
        import subprocess
        result = subprocess.run(
            ["tail", "-100", str(log_file)],
            capture_output=True, text=True, timeout=5
        )
        lines_list = [l for l in result.stdout.split('\n') if 'DeprecationWarning' not in l and l.strip()]
        recent = lines_list[-lines:] if len(lines_list) > lines else lines_list
        
        if not recent:
            return f"No recent activity for `{agent}`"
        
        # Format output
        output = f"*Recent logs for {agent}:*\n```\n"
        for line in recent:
            # Truncate long lines
            if len(line) > 100:
                line = line[:97] + "..."
            output += line + "\n"
        output += "```"
        return output
    except Exception as e:
        return f"Error reading logs: {e}"


def cmd_tokens() -> str:
    """Get token usage statistics."""
    orchestrator = get_orchestrator()
    
    try:
        usage = orchestrator.get_token_usage_summary(days=7)
        today = orchestrator.get_token_usage_today()
        
        lines = ["*Token Usage (Last 7 Days)*", ""]
        
        # Today's usage
        total_today = sum(a.get('total_tokens', 0) for a in today.values()) if isinstance(today, dict) else 0
        lines.append(f"*Today:* {total_today:,} tokens")
        lines.append("")
        
        # By agent
        lines.append("*By Agent:*")
        lines.append("```")
        if usage.get('by_agent'):
            for agent, data in sorted(usage['by_agent'].items(), key=lambda x: x[1].get('tokens', 0), reverse=True):
                tokens = data.get('tokens', 0)
                lines.append(f"{agent:<12} {tokens:>10,} tokens")
        else:
            lines.append("No usage data")
        lines.append("```")
        
        # Total
        lines.append(f"\n*7-Day Total:* {usage.get('total_tokens', 0):,} tokens")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error getting token usage: {e}"


def cmd_ask(question: str, response_url: str = None) -> str:
    """
    Answer natural language questions about the swarm.
    
    Handles common questions directly from DB, routes complex ones to liaison.
    """
    question_lower = question.lower().strip()
    orchestrator = get_orchestrator()
    
    # Gather context data
    try:
        stats = orchestrator.get_queue_stats()
        pending = stats.get('by_status', {}).get('pending', 0)
        claimed = stats.get('by_status', {}).get('claimed', 0)
        completed = stats.get('by_status', {}).get('completed', 0)
        failed = stats.get('by_status', {}).get('failed', 0)
        
        # Get agent info
        agents_running = 0
        agents_paused = 0
        status_dir = Path("/auto-dev/data")
        for f in status_dir.glob("watcher_status_*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("rate_limit", {}).get("limited"):
                    agents_paused += 1
                elif data.get("is_running"):
                    agents_running += 1
            except:
                pass
        
        # Get current tasks
        conn = sqlite3.connect("/auto-dev/data/orchestrator.db")
        conn.row_factory = sqlite3.Row
        
        # Currently working on
        cursor = conn.execute("""
            SELECT assigned_to, type, payload FROM tasks 
            WHERE status = 'claimed' 
            ORDER BY claimed_at DESC LIMIT 5
        """)
        current_tasks = []
        for row in cursor.fetchall():
            payload = json.loads(row['payload']) if row['payload'] else {}
            title = payload.get('title', payload.get('product_name', payload.get('product', 'N/A')))
            current_tasks.append(f"{row['assigned_to']}: {row['type']} - {title}")
        
        # Recent completions
        cursor = conn.execute("""
            SELECT assigned_to, type, payload, completed_at FROM tasks 
            WHERE status = 'completed' 
            ORDER BY completed_at DESC LIMIT 5
        """)
        recent_completed = []
        for row in cursor.fetchall():
            payload = json.loads(row['payload']) if row['payload'] else {}
            title = payload.get('title', payload.get('product_name', 'N/A'))
            recent_completed.append(f"{row['assigned_to']}: {title}")
        
        # Pending approvals
        approvals = orchestrator.get_pending_approvals()
        
        # Token usage today
        cursor = conn.execute("""
            SELECT SUM(total_tokens) as total FROM token_usage 
            WHERE date(recorded_at) = date('now')
        """)
        tokens_today = cursor.fetchone()['total'] or 0
        
        # Check for rate limit
        rate_limited = False
        rate_reset = None
        rate_file = Path("/auto-dev/data/.rate_limited")
        if rate_file.exists():
            try:
                rl_data = json.loads(rate_file.read_text())
                rate_reset = rl_data.get('reset_time')
                rate_limited = True
            except:
                pass
        
        conn.close()
        
    except Exception as e:
        logger.exception("Error gathering swarm context")
        return f"Sorry, I couldn't gather swarm data: {e}"
    
    # Pattern matching for common questions
    
    # Status questions
    if any(w in question_lower for w in ['status', 'how is', "how's", 'doing', 'going']):
        if rate_limited:
            return f"🔴 *The swarm is rate limited* until {rate_reset}.\n\n{agents_running} agents waiting to resume."
        elif agents_running > 0:
            working = "\n".join(f"  • {t}" for t in current_tasks) if current_tasks else "  _Idle_"
            return f"🟢 *The swarm is running!*\n\n*{agents_running} agents active*\n\n*Currently working on:*\n{working}"
        else:
            return "🔴 *The swarm appears to be stopped.* No agents are running."
    
    # What are they working on?
    if any(w in question_lower for w in ['working on', 'doing now', 'current task', 'right now']):
        if not current_tasks:
            return "No tasks currently in progress. The agents might be idle or rate limited."
        return "*Currently working on:*\n" + "\n".join(f"  • {t}" for t in current_tasks)
    
    # Recent completions
    if any(w in question_lower for w in ['completed', 'finished', 'done', 'built', 'created']):
        if not recent_completed:
            return "No recently completed tasks found."
        return "*Recently completed:*\n" + "\n".join(f"  • {t}" for t in recent_completed)
    
    # Pending/queue questions
    if any(w in question_lower for w in ['pending', 'queue', 'waiting', 'backlog']):
        return f"*Queue Status:*\n  • Pending: {pending}\n  • In Progress: {claimed}\n  • Completed: {completed}\n  • Failed: {failed}"
    
    # Approval questions
    if any(w in question_lower for w in ['approval', 'approve', 'review', 'publish']):
        if not approvals:
            return "No items waiting for approval."
        items = "\n".join(f"  • `{a.id[:8]}` {a.product_name} ({a.platform})" for a in approvals[:5])
        return f"*{len(approvals)} items awaiting approval:*\n{items}\n\nUse `/swarm approve <id>` to approve."
    
    # Token/cost questions
    if any(w in question_lower for w in ['token', 'cost', 'usage', 'spend']):
        return f"*Token usage today:* {tokens_today:,} tokens\n\nUse `/swarm tokens` for detailed breakdown."
    
    # Rate limit questions
    if any(w in question_lower for w in ['rate limit', 'limited', 'paused', 'stopped']):
        if rate_limited:
            return f"⏸️ *Yes, the swarm is rate limited.*\n\nResets at: {rate_reset}\n\nThis is Claude Max's daily limit, not our config."
        else:
            return "✅ *No rate limit currently active.* Agents are free to work."
    
    # Agent specific questions
    for agent in ['hunter', 'critic', 'pm', 'builder', 'reviewer', 'tester', 'publisher', 'meta', 'liaison', 'support']:
        if agent in question_lower:
            # Check if this agent has a current task
            agent_task = next((t for t in current_tasks if agent in t.lower()), None)
            if agent_task:
                return f"*{agent.title()}* is currently working on:\n  • {agent_task}"
            else:
                return f"*{agent.title()}* doesn't have an active task right now."
    
    # How many / count questions
    if any(w in question_lower for w in ['how many', 'count', 'number of']):
        return f"*Swarm Stats:*\n  • Agents running: {agents_running}\n  • Agents paused: {agents_paused}\n  • Tasks pending: {pending}\n  • Tasks in progress: {claimed}\n  • Completed today: {completed}\n  • Awaiting approval: {len(approvals)}"
    
    # If we can't answer directly, offer to route to liaison
    return (
        f"🤔 I'm not sure how to answer that directly.\n\n"
        f"*What I can tell you:*\n"
        f"  • {agents_running} agents running ({agents_paused} paused)\n"
        f"  • {pending} tasks pending, {claimed} in progress\n"
        f"  • {len(approvals)} items awaiting approval\n\n"
        f"Try `/swarm tell {question}` to send this to the liaison agent for a detailed response."
    )


def cmd_help() -> str:
    """Show help message."""
    return """*Swarm Control Commands:*

*Status & Info:*
• `/swarm status` - Overview of queue and agents
• `/swarm tasks` - List pending tasks
• `/swarm agents` - Detailed agent status
• `/swarm approvals` - Items awaiting publishing approval
• `/swarm logs <agent>` - Recent agent logs
• `/swarm tokens` - Token usage stats
• `/swarm ask <question>` - Ask anything about the swarm

*Project Approvals (BUILD decisions):*
• `/swarm projects [pending|deferred|approved|rejected]` - List project proposals
• `/swarm project <id>` - View project details with pitch, rating, cons
• `/swarm approve-project <id>` - Approve for building
• `/swarm reject-project <id> <reason>` - Reject project
• `/swarm defer-project <id>` - Move to backlog

*Publish Approvals:*
• `/swarm approve <id>` - Approve for publishing
• `/swarm reject <id> <reason>` - Reject item

*Actions:*
• `/swarm cancel <id>` - Cancel a task
• `/swarm priority <id> <1-10>` - Change priority
• `/swarm restart <agent>` - Restart an agent
• `/swarm tell <message>` - Send directive

Task/Project IDs can be partial (first 8 chars)."""


def process_command(text: str) -> str:
    """Process a slash command and return response."""
    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower() if parts else "help"
    args = parts[1:] if len(parts) > 1 else []
    
    try:
        if cmd in ("status", "s"):
            return cmd_status()
        elif cmd in ("tasks", "t", "queue"):
            return cmd_tasks()
        elif cmd in ("agents", "a"):
            return cmd_agents()
        elif cmd in ("approvals", "pending"):
            return cmd_approvals()
        
        # Project proposal commands
        elif cmd == "projects":
            status = args[0].lower() if args else "pending"
            if status not in ("pending", "deferred", "approved", "rejected"):
                status = "pending"
            return cmd_projects(status)
        elif cmd == "project":
            if not args:
                return "Usage: `/swarm project <project_id>`"
            return cmd_project_detail(args[0])
        elif cmd == "approve-project":
            if not args:
                return "Usage: `/swarm approve-project <project_id>`"
            return cmd_approve_project(args[0])
        elif cmd == "reject-project":
            if len(args) < 2:
                return "Usage: `/swarm reject-project <project_id> <reason>`"
            return cmd_reject_project(args[0], " ".join(args[1:]) if len(args) > 1 else args[1])
        elif cmd == "defer-project":
            if not args:
                return "Usage: `/swarm defer-project <project_id>`"
            return cmd_defer_project(args[0])
        
        elif cmd == "cancel":
            if not args:
                return "Usage: `/swarm cancel <task_id>`"
            return cmd_cancel(args[0])
        elif cmd in ("priority", "pri", "p"):
            if len(args) < 2:
                return "Usage: `/swarm priority <task_id> <1-10>`"
            return cmd_priority(args[0], int(args[1]))
        elif cmd == "restart":
            if not args:
                return "Usage: `/swarm restart <agent_name>`"
            return cmd_restart(args[0].lower())
        elif cmd == "approve":
            if not args:
                return "Usage: `/swarm approve <item_id>`"
            return cmd_approve(args[0])
        elif cmd == "reject":
            if len(args) < 2:
                return "Usage: `/swarm reject <item_id> <reason>`"
            return cmd_reject(args[0], " ".join(args[1:]) if len(args) > 1 else args[1])
        elif cmd == "tell":
            if not args:
                return "Usage: `/swarm tell <message>`"
            message = " ".join(args) if len(args) > 1 else args[0]
            return cmd_tell(message)
        elif cmd in ("logs", "log", "l"):
            if not args:
                return "Usage: `/swarm logs <agent_name>`"
            return cmd_logs(args[0].lower())
        elif cmd in ("tokens", "token", "usage"):
            return cmd_tokens()
        elif cmd in ("ask", "q", "?"):
            if not args:
                return "Usage: `/swarm ask <your question>`\n\nExample: `/swarm ask what is the builder working on?`"
            question = " ".join(args) if len(args) > 1 else args[0]
            return cmd_ask(question)
        elif cmd == "help":
            return cmd_help()
        else:
            # If no recognized command, treat the whole thing as a question
            full_text = " ".join([cmd] + args)
            return cmd_ask(full_text)
    except Exception as e:
        logger.exception(f"Error processing command: {cmd}")
        return f"Error: {str(e)}"


# ============================================================================
# FastAPI Endpoints
# ============================================================================

@app.post("/slack/commands")
async def handle_slash_command(request: Request):
    """Handle incoming Slack slash commands."""
    
    # Get raw body FIRST for signature verification
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    # Parse form data manually from body
    from urllib.parse import parse_qs
    form_data = parse_qs(body.decode('utf-8'))
    
    # Extract fields (parse_qs returns lists, so take first element)
    user_id = form_data.get('user_id', [''])[0]
    user_name = form_data.get('user_name', [''])[0]
    text = form_data.get('text', [''])[0]
    
    # Verify request is from Slack
    if not verify_slack_signature(body, timestamp, signature):
        logger.warning(f"Invalid signature from {user_name} ({user_id})")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Check user is allowed
    if not is_user_allowed(user_id):
        logger.warning(f"Unauthorized user: {user_name} ({user_id})")
        return format_error(f"User `{user_id}` is not authorized to use this bot.")
    
    logger.info(f"Command from {user_name}: /swarm {text}")
    
    # Process command
    response_text = process_command(text)
    
    return format_response(response_text)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "slack-bot"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Swarm Control Slack Bot",
        "endpoints": {
            "/slack/commands": "POST - Slack slash command handler",
            "/health": "GET - Health check"
        }
    }


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)

