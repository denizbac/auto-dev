#!/usr/bin/env python3
"""
Daily Summary Script for Autonomous Claude Swarm
================================================

Sends a daily summary to Slack with yesterday's activity.
Run via cron at 9am: 0 9 * * * /autonomous-claude/venv/bin/python /autonomous-claude/scripts/daily_summary.py

"""

import sys
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.slack_notifications import send_slack_message


def get_daily_stats():
    """Get statistics for the last 24 hours."""
    db_path = "/autonomous-claude/data/orchestrator.db"
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
    
    stats = {
        'tasks_completed': 0,
        'tasks_failed': 0,
        'tasks_created': 0,
        'tasks_pending': 0,
        'approvals_pending': 0,
        'by_agent': {},
        'by_type': {}
    }
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Tasks completed in last 24h
        cursor = conn.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE status = 'completed' AND completed_at > ?
        """, (yesterday,))
        stats['tasks_completed'] = cursor.fetchone()[0]
        
        # Tasks failed in last 24h
        cursor = conn.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE status = 'failed' AND completed_at > ?
        """, (yesterday,))
        stats['tasks_failed'] = cursor.fetchone()[0]
        
        # Tasks created in last 24h
        cursor = conn.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE created_at > ?
        """, (yesterday,))
        stats['tasks_created'] = cursor.fetchone()[0]
        
        # Current pending tasks
        cursor = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
        stats['tasks_pending'] = cursor.fetchone()[0]
        
        # Pending approvals
        cursor = conn.execute("SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'")
        stats['approvals_pending'] = cursor.fetchone()[0]
        
        # Completions by agent
        cursor = conn.execute("""
            SELECT assigned_to, COUNT(*) as count FROM tasks 
            WHERE status = 'completed' AND completed_at > ?
            GROUP BY assigned_to
        """, (yesterday,))
        for row in cursor.fetchall():
            if row['assigned_to']:
                stats['by_agent'][row['assigned_to']] = row['count']
        
        # Completions by type
        cursor = conn.execute("""
            SELECT type, COUNT(*) as count FROM tasks 
            WHERE status = 'completed' AND completed_at > ?
            GROUP BY type
        """, (yesterday,))
        for row in cursor.fetchall():
            stats['by_type'][row['type']] = row['count']
        
        conn.close()
    except Exception as e:
        print(f"Error getting stats: {e}")
    
    return stats


def format_summary(stats: dict) -> str:
    """Format the daily summary message."""
    today = datetime.utcnow().strftime('%A, %B %d')
    
    # Build agent activity string
    agent_lines = []
    for agent, count in sorted(stats['by_agent'].items(), key=lambda x: x[1], reverse=True)[:5]:
        agent_lines.append(f"  • {agent}: {count}")
    agent_str = "\n".join(agent_lines) if agent_lines else "  No activity"
    
    # Build task type breakdown
    type_lines = []
    for task_type, count in sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)[:5]:
        type_lines.append(f"  • {task_type}: {count}")
    type_str = "\n".join(type_lines) if type_lines else "  No tasks"
    
    message = f"""📊 *Daily Swarm Summary* - {today}

*Last 24 Hours:*
  ✅ Completed: {stats['tasks_completed']}
  ❌ Failed: {stats['tasks_failed']}
  📝 Created: {stats['tasks_created']}

*Current Queue:*
  ⏳ Pending: {stats['tasks_pending']}
  📋 Awaiting Approval: {stats['approvals_pending']}

*Top Agents:*
{agent_str}

*Task Types:*
{type_str}"""

    if stats['approvals_pending'] > 0:
        message += f"\n\n⚠️ *{stats['approvals_pending']} items need your approval!*\nUse `/swarm approvals` to review."
    
    return message


def main():
    print("Generating daily summary...")
    stats = get_daily_stats()
    message = format_summary(stats)
    
    print("Sending to Slack...")
    success = send_slack_message(message)
    
    if success:
        print("Daily summary sent!")
    else:
        print("Failed to send summary")
        sys.exit(1)


if __name__ == "__main__":
    main()

