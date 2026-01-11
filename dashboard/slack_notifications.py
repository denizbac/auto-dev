"""
Slack Notifications for Autonomous Claude Swarm
================================================

Sends proactive notifications to Slack for important events:
- Rate limit hit
- Product ready for approval
- Task failures
- Daily summary

Usage:
    from dashboard.slack_notifications import notify_rate_limit, notify_approval_ready, etc.
"""

import subprocess
import logging
import json
from typing import Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

_config_cache = {}

def get_ssm_parameter(name: str) -> Optional[str]:
    """Fetch parameter from AWS SSM Parameter Store."""
    if name in _config_cache:
        return _config_cache[name]
    
    try:
        result = subprocess.run(
            ["aws", "ssm", "get-parameter", "--name", name, "--with-decryption", 
             "--query", "Parameter.Value", "--output", "text"],
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


def get_bot_token() -> str:
    return get_ssm_parameter("/auto-dev/slack/bot_token") or ""


def get_notification_channel() -> str:
    """Get the channel to post notifications to."""
    # Try SSM first, fall back to default
    channel = get_ssm_parameter("/auto-dev/slack/notification_channel")
    if channel:
        return channel
    # Default to general or the first channel the bot is in
    return "#general"


# ============================================================================
# Slack API
# ============================================================================

def send_slack_message(
    text: str,
    channel: Optional[str] = None,
    blocks: Optional[list] = None,
    thread_ts: Optional[str] = None
) -> bool:
    """
    Send a message to Slack.
    
    Args:
        text: Message text (also used as fallback for blocks)
        channel: Channel to post to (default: notification channel from SSM)
        blocks: Optional Block Kit blocks for rich formatting
        thread_ts: Optional thread timestamp to reply in thread
        
    Returns:
        True if message sent successfully
    """
    import httpx
    
    bot_token = get_bot_token()
    if not bot_token:
        logger.error("No Slack bot token configured")
        return False
    
    channel = channel or get_notification_channel()
    
    payload = {
        "channel": channel,
        "text": text,
    }
    
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    
    try:
        response = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json=payload,
            timeout=10
        )
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Slack API error: {result.get('error')}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return False


# ============================================================================
# Notification Functions
# ============================================================================

def notify_rate_limit(agent: str, reset_time: str) -> bool:
    """Notify when an agent hits rate limit."""
    text = f"⏸️ *Rate Limit Hit*\n\nAgent `{agent}` hit rate limit.\nResumes: {reset_time}\n\nAll agents paused until reset."
    return send_slack_message(text)


def notify_approval_ready(product_name: str, product_type: str, platform: str, item_id: str) -> bool:
    """Notify when a product is ready for publishing approval."""
    text = (
        f"📋 *New Publishing Approval Request*\n\n"
        f"*Product:* {product_name}\n"
        f"*Type:* {product_type}\n"
        f"*Platform:* {platform}\n\n"
        f"Use `/swarm approve {item_id[:8]}` to approve\n"
        f"Use `/swarm reject {item_id[:8]} <reason>` to reject"
    )
    return send_slack_message(text)


def notify_project_proposal(proposal) -> bool:
    """
    Notify when a new project proposal is ready for review.
    
    Args:
        proposal: ProjectProposal dataclass or dict with rich context
    """
    # Handle both dataclass and dict
    if hasattr(proposal, 'title'):
        title = proposal.title
        hunter_pitch = proposal.hunter_pitch
        hunter_rating = proposal.hunter_rating
        critic_rating = proposal.critic_rating
        max_revenue = proposal.max_revenue_estimate
        effort = proposal.effort_estimate
        market_size = proposal.market_size
        proposal_id = proposal.id
    else:
        title = proposal.get('title', 'Unknown')
        hunter_pitch = proposal.get('hunter_pitch', '')
        hunter_rating = proposal.get('hunter_rating', 0)
        critic_rating = proposal.get('critic_rating', 0)
        max_revenue = proposal.get('max_revenue_estimate', 'N/A')
        effort = proposal.get('effort_estimate', 'N/A')
        market_size = proposal.get('market_size', 'N/A')
        proposal_id = proposal.get('id', 'unknown')
    
    avg_rating = (hunter_rating + critic_rating) / 2
    rating_emoji = "🟢" if avg_rating >= 7 else "🟡" if avg_rating >= 5 else "🔴"
    
    # Truncate pitch if too long
    pitch_preview = hunter_pitch[:100] + "..." if len(hunter_pitch) > 100 else hunter_pitch
    
    text = (
        f"📋 *New Project Proposal*\n\n"
        f"*{title}* {rating_emoji} {avg_rating:.1f}/10\n\n"
        f"> _{pitch_preview}_\n\n"
        f"💰 Max: *{max_revenue}* | ⏱️ *{effort}* | 📁 *{market_size}*\n\n"
        f"*Actions:*\n"
        f"• `/swarm project {proposal_id[:8]}` - View full details\n"
        f"• `/swarm approve-project {proposal_id[:8]}` - Approve for building\n"
        f"• `/swarm reject-project {proposal_id[:8]} <reason>` - Reject\n"
        f"• `/swarm defer-project {proposal_id[:8]}` - Defer to backlog"
    )
    return send_slack_message(text)


def notify_task_failed(task_type: str, task_title: str, error: str, agent: str) -> bool:
    """Notify when a task fails."""
    text = (
        f"❌ *Task Failed*\n\n"
        f"*Type:* {task_type}\n"
        f"*Title:* {task_title}\n"
        f"*Agent:* {agent}\n"
        f"*Error:* {error[:200]}"
    )
    return send_slack_message(text)


def notify_task_completed(task_type: str, task_title: str, agent: str) -> bool:
    """Notify when an important task completes (optional - can be noisy)."""
    text = f"✅ *Task Completed*\n\n`{agent}` finished {task_type}: {task_title}"
    return send_slack_message(text)


def notify_agent_restart(agent: str, reason: str = "manual") -> bool:
    """Notify when an agent restarts."""
    text = f"🔄 Agent `{agent}` restarted ({reason})"
    return send_slack_message(text)


def notify_swarm_started() -> bool:
    """Notify when the swarm starts up."""
    text = "🚀 *Swarm Started*\n\nAll agents are coming online."
    return send_slack_message(text)


def notify_daily_summary(
    tasks_completed: int,
    tasks_failed: int,
    tasks_pending: int,
    products_built: int,
    approvals_pending: int
) -> bool:
    """Send daily summary notification."""
    text = (
        f"📊 *Daily Summary* - {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"*Tasks:*\n"
        f"  • Completed: {tasks_completed}\n"
        f"  • Failed: {tasks_failed}\n"
        f"  • Pending: {tasks_pending}\n\n"
        f"*Products Built:* {products_built}\n"
        f"*Awaiting Approval:* {approvals_pending}"
    )
    return send_slack_message(text)


def notify_custom(message: str, emoji: str = "ℹ️") -> bool:
    """Send a custom notification."""
    text = f"{emoji} {message}"
    return send_slack_message(text)


# ============================================================================
# Integration Helper
# ============================================================================

class SlackNotifier:
    """
    Context manager / helper for integrating notifications into existing code.
    
    Usage:
        notifier = SlackNotifier()
        notifier.rate_limit("builder", "2025-12-29T01:00:00")
    """
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def rate_limit(self, agent: str, reset_time: str):
        if self.enabled:
            notify_rate_limit(agent, reset_time)
    
    def approval_ready(self, product_name: str, product_type: str, platform: str, item_id: str):
        if self.enabled:
            notify_approval_ready(product_name, product_type, platform, item_id)
    
    def project_proposal(self, proposal):
        if self.enabled:
            notify_project_proposal(proposal)
    
    def task_failed(self, task_type: str, task_title: str, error: str, agent: str):
        if self.enabled:
            notify_task_failed(task_type, task_title, error, agent)
    
    def task_completed(self, task_type: str, task_title: str, agent: str):
        if self.enabled:
            notify_task_completed(task_type, task_title, agent)


# Global notifier instance
notifier = SlackNotifier()


# ============================================================================
# CLI for testing
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python slack_notifications.py <test|rate_limit|approval|daily>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "test":
        success = notify_custom("Test notification from Swarm Control", "🧪")
        print("Sent!" if success else "Failed!")
    elif cmd == "rate_limit":
        notify_rate_limit("builder", "2025-12-29T01:00:00")
    elif cmd == "approval":
        notify_approval_ready("test-product", "npm-package", "npm", "abc123")
    elif cmd == "daily":
        notify_daily_summary(45, 3, 12, 2, 1)
    else:
        print(f"Unknown command: {cmd}")

