#!/usr/bin/env python3
"""
Auto-Dev Agent Runner
=====================

Runs a single AI agent instance, managing LLM sessions, task processing,
and coordination with other agents via Redis and the orchestrator.

Usage:
  python -m watcher.agent_runner --agent pm          # Run PM agent
  python -m watcher.agent_runner --agent architect   # Run Architect agent
  python -m watcher.agent_runner --agent builder     # Run Builder agent
  python -m watcher.agent_runner --agent reviewer    # Run Reviewer agent
  python -m watcher.agent_runner --agent tester      # Run Tester agent
  python -m watcher.agent_runner --agent security    # Run Security agent
  python -m watcher.agent_runner --agent devops      # Run DevOps agent
  python -m watcher.agent_runner --agent bug_finder  # Run Bug Finder agent
"""

import subprocess
import time
import os
import sys
import signal
import json
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import threading
import yaml
try:
    import boto3
except ImportError:
    boto3 = None

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from watcher.memory import ShortTermMemoryDB, ShortTermMemory
from watcher.orchestrator_pg import (
    get_orchestrator, Orchestrator, Task, TaskType, MessageType
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/auto-dev/logs/watcher.log')
    ]
)
logger = logging.getLogger('watcher')

SSM_REGION = os.environ.get("AWS_REGION", "us-east-1")
APIFY_SSM_PARAM = "/auto-dev/apify/api_key"
OPENAI_SSM_PARAM = "/auto-dev/openai/api_key"


def _load_ssm_param(name: str, region: str = SSM_REGION) -> Optional[str]:
    """Best-effort SSM lookup for secrets; returns None if unavailable."""
    if boto3 is None:
        return None
    try:
        client = boto3.client("ssm", region_name=region)
        response = client.get_parameter(Name=name, WithDecryption=True)
        return response.get("Parameter", {}).get("Value")
    except Exception as exc:
        logger.debug(f"SSM param unavailable: {name}: {exc}")
        return None


@dataclass
class SessionStats:
    """Statistics for a single LLM session."""
    session_id: str
    start_time: datetime
    agent_id: str = "master"
    provider: str = "claude"
    end_time: Optional[datetime] = None
    tokens_used: int = 0
    actions_taken: int = 0
    income_generated: float = 0.0
    tasks_completed: int = 0
    exit_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class AgentState:
    """Current state of the agent runner."""
    agent_id: str = "master"
    is_running: bool = False
    current_session: Optional[SessionStats] = None
    current_task: Optional[Task] = None
    task_start_time: Optional[datetime] = None  # Track when current task started
    retry_task: Optional[Task] = None
    total_sessions: int = 0
    total_tokens_today: int = 0
    total_income_today: float = 0.0
    last_restart: Optional[datetime] = None
    consecutive_failures: int = 0
    daily_reset_time: datetime = field(default_factory=lambda: datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ))
    rate_limited: bool = False
    rate_limit_reset: Optional[datetime] = None


# Shared rate limit file - all agents check this
RATE_LIMIT_FILE = Path('/auto-dev/data/.rate_limited')


class AgentWorkerProcess:
    """Manages a single LLM worker process."""
    
    def __init__(
        self,
        prompt_path: str,
        working_dir: str,
        agent_id: str = "master",
        task_context: Optional[str] = None,
        provider: str = "claude",
        provider_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None
    ):
        """
        Initialize worker process manager.
        
        Args:
            prompt_path: Path to the agent's prompt file
            working_dir: Working directory for Claude Code
            agent_id: Identifier for this agent
            task_context: Optional task-specific context to prepend
        """
        self.prompt_path = Path(prompt_path)
        self.working_dir = Path(working_dir)
        self.agent_id = agent_id
        self.task_context = task_context
        self.provider = provider
        self.provider_config = provider_config or {}
        self.model = model
        self.process: Optional[subprocess.Popen] = None
        self.session_id: Optional[str] = None
        
    def start(self) -> str:
        """
        Start a new LLM session.

        Returns:
            Session ID
        """
        self.session_id = f"{self.agent_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # Ensure working directory exists
        self.working_dir.mkdir(parents=True, exist_ok=True)

        # Read agent prompt
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"Agent prompt not found: {self.prompt_path}")
        
        agent_prompt = self.prompt_path.read_text()
        
        # Prepend task context if provided
        if self.task_context:
            full_prompt = f"""## Current Task Context

{self.task_context}

---

{agent_prompt}"""
        else:
            full_prompt = agent_prompt
        
        # Prepare environment
        env = os.environ.copy()
        env['SWARM_SESSION_ID'] = self.session_id
        env['SWARM_AGENT_ID'] = self.agent_id
        env['CLAUDE_SESSION_ID'] = self.session_id
        env['CLAUDE_AGENT_ID'] = self.agent_id

        # Inject Apify token from SSM if present (keeps agents ready for Apify builds/publishing).
        apify_token = _load_ssm_param(APIFY_SSM_PARAM)
        if apify_token:
            env.setdefault("APIFY_TOKEN", apify_token)
            env.setdefault("APIFY_API_TOKEN", apify_token)
            env.setdefault("APIFY_API_KEY", apify_token)

        if self.provider == "codex":
            # Try multiple sources for OpenAI API key
            openai_key = (
                os.environ.get("OPENAI_API_KEY") or
                os.environ.get("CODEX_API_KEY") or
                _load_ssm_param(OPENAI_SSM_PARAM)
            )
            if openai_key:
                env["OPENAI_API_KEY"] = openai_key
        
        # Build command - provider-driven CLI invocation
        command = self.provider_config.get("command", "claude")
        args = list(self.provider_config.get("args", []))
        if self.provider == "claude" and not args:
            args = [
                "--dangerously-skip-permissions",
                "--print",
                "--tools", "default",
                "--output-format", "json",
            ]
        prompt_flag = self.provider_config.get("prompt_flag", "-p")

        cmd = [command] + args
        if self.model:
            cmd.extend(["--model", self.model])
        if prompt_flag:
            cmd.extend([prompt_flag, full_prompt])
        else:
            cmd.append(full_prompt)

        model_info = self.model or "default"
        logger.info(
            f"Starting {self.provider} session: {self.session_id} "
            f"(agent: {self.agent_id}, model: {model_info})"
        )
        
        # Start process
        self.process = subprocess.Popen(
            cmd,
            cwd=self.working_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        return self.session_id
    
    def is_alive(self) -> bool:
        """Check if the worker process is still running."""
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def get_output(self) -> tuple:
        """Get stdout and stderr from the process."""
        if self.process is None:
            return "", ""
        try:
            stdout, stderr = self.process.communicate(timeout=1)
            return stdout, stderr
        except subprocess.TimeoutExpired:
            return "", ""
    
    def stop(self, timeout: int = 10) -> int:
        """
        Stop the worker process gracefully.
        
        Args:
            timeout: Seconds to wait before force kill
            
        Returns:
            Exit code
        """
        if self.process is None:
            return 0
        
        logger.info(f"Stopping session: {self.session_id}")
        
        # Try graceful termination first
        self.process.terminate()
        
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not terminate, killing...")
            self.process.kill()
            self.process.wait()
        
        exit_code = self.process.returncode
        self.process = None
        
        return exit_code


class AgentRunner:
    """
    Runs a single AI agent, managing LLM sessions and task processing.
    
    Responsibilities:
    - Spawn and monitor Claude Code worker processes
    - Claim and process tasks from the queue (multi-agent mode)
    - Coordinate with other agents via orchestrator
    - Restart on crashes or hangs
    - Enforce token budgets
    - Log all activity
    - Track income and performance
    """
    
    # Agent type to task type mapping
    # Maps agent types to the task types they handle (from settings.yaml)
    # Note: 'directive' and 'human_directive' are universal - any agent can receive human instructions
    AGENT_TASK_TYPES = {
        'pm': ['analyze_repo', 'create_epic', 'break_down_epic', 'create_user_story', 'prioritize_backlog', 'triage_issue', 'directive', 'human_directive'],
        'architect': ['evaluate_feasibility', 'write_spec', 'create_implementation_issue', 'directive', 'human_directive'],
        'builder': ['implement_feature', 'implement_fix', 'implement_refactor', 'address_review_feedback', 'directive', 'human_directive'],
        'reviewer': ['review_mr', 'directive', 'human_directive'],
        'tester': ['write_tests', 'run_tests', 'validate_feature', 'analyze_coverage', 'directive', 'human_directive'],
        'security': ['security_scan', 'dependency_audit', 'compliance_check', 'directive', 'human_directive'],
        'devops': ['manage_pipeline', 'deploy', 'rollback', 'fix_build', 'directive', 'human_directive'],
        'bug_finder': ['static_analysis', 'bug_hunt', 'directive', 'human_directive'],
        'master': None  # Master handles all task types (fallback)
    }
    
    def __init__(
        self,
        config_path: str = '/auto-dev/config/settings.yaml',
        agent_id: str = 'master'
    ):
        """
        Initialize the watcher.
        
        Args:
            config_path: Path to configuration file
            agent_id: Agent type (master, hunter, builder, publisher)
        """
        self.config = self._load_config(config_path)
        self.agent_id = agent_id
        self.state = AgentState(agent_id=agent_id)
        self.worker: Optional[AgentWorkerProcess] = None
        self.shutdown_requested = False
        
        # Get agent-specific configuration
        self.agent_config = self._get_agent_config()
        
        # Initialize memory
        self.memory = ShortTermMemoryDB(
            db_path=self.config['memory']['short_term']['database_path'],
            max_entries=self.config['memory']['short_term']['max_entries']
        )
        
        # Initialize orchestrator for multi-agent coordination
        orchestrator_config = self.config.get('orchestrator', {})
        # Prefer REDIS_URL from environment (for Docker), fall back to config
        redis_url = os.environ.get('REDIS_URL') or orchestrator_config.get('redis_url')
        self.orchestrator = get_orchestrator(
            db_path=orchestrator_config.get('database_path', '/auto-dev/data/orchestrator.db'),
            redis_url=redis_url
        )
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        logger.info(f"Watcher initialized for agent: {agent_id}")

        # Initialize Redis connection for agent control
        self._redis = None
        redis_url = os.environ.get('REDIS_URL') or orchestrator_config.get('redis_url')
        if redis_lib and redis_url:
            try:
                self._redis = redis_lib.from_url(redis_url)
                logger.info(f"Redis connected for agent control: {redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")

    def _is_agent_enabled(self) -> bool:
        """Check if this agent is enabled via Redis."""
        if not self._redis:
            return True  # Default to enabled if Redis not available

        try:
            enabled = self._redis.get(f"agent:{self.agent_id}:enabled")
            # If key doesn't exist (None), default to enabled
            return enabled is None or enabled == b"1"
        except Exception as e:
            logger.warning(f"Redis check failed, defaulting to enabled: {e}")
            return True

    def _get_llm_config(self) -> Dict[str, Any]:
        """Return LLM provider config block."""
        return self.config.get('llm', {})

    def _get_provider_config(self, provider: str) -> Dict[str, Any]:
        """Return provider-specific CLI config."""
        providers = self._get_llm_config().get('providers', {})
        return providers.get(provider, {})

    def _get_manual_provider_override(self) -> Optional[str]:
        """Return manual provider override from environment, if set."""
        llm_config = self._get_llm_config()
        env_name = llm_config.get('manual_override_env', 'SWARM_LLM_PROVIDER')
        override = os.environ.get(env_name)
        if not override:
            return None
        return override.strip().lower()

    def _get_rate_limit_status(self) -> Optional[Dict[str, Any]]:
        """Return active rate limit status with provider and reset time."""
        if RATE_LIMIT_FILE.exists():
            try:
                data = json.loads(RATE_LIMIT_FILE.read_text())
                reset_time = datetime.fromisoformat(data.get('reset_time', ''))
                provider = data.get('provider', 'claude')
                if datetime.utcnow() < reset_time:
                    return {'provider': provider, 'reset_time': reset_time}
                RATE_LIMIT_FILE.unlink()
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _should_fallback_on_rate_limit(self, provider: str) -> bool:
        """Return True if we should auto-fallback when provider is rate limited."""
        llm_config = self._get_llm_config()
        if not llm_config.get('auto_fallback_on_rate_limit'):
            return False
        fallback = llm_config.get('fallback_provider')
        default_provider = llm_config.get('default_provider', 'claude')
        return bool(fallback and provider == default_provider)

    def _select_provider(self) -> str:
        """Select provider with manual override, per-agent override, and rate-limit fallback."""
        override = self._get_manual_provider_override()
        if override:
            return override

        agent_override = self.agent_config.get('provider')
        if agent_override:
            return str(agent_override).strip().lower()

        llm_config = self._get_llm_config()
        default_provider = llm_config.get('default_provider', 'claude')
        rate_limit = self._get_rate_limit_status()
        if rate_limit and self._should_fallback_on_rate_limit(rate_limit['provider']):
            return llm_config.get('fallback_provider', default_provider)

        return default_provider

    def _resolve_model_for_provider(self, provider: str) -> Optional[str]:
        """Resolve the model name for a provider using optional model_map."""
        model = self.agent_config.get('model')
        provider_config = self._get_provider_config(provider)
        # Check if model_map key exists in config
        if 'model_map' in provider_config:
            model_map = provider_config['model_map']
            # Empty model_map means don't pass any model (e.g., Codex with ChatGPT)
            if not model_map:
                return None
            # Use mapping if available
            if model in model_map:
                return model_map[model]
        return model
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        with open(config_path) as f:
            return yaml.safe_load(f)
    
    def _get_agent_config(self) -> Dict[str, Any]:
        """Get configuration for this specific agent."""
        agents_config = self.config.get('agents', {})
        
        if self.agent_id in agents_config:
            return agents_config[self.agent_id]
        
        # Default config for master agent
        return {
            'name': 'Master',
            'prompt_file': '/auto-dev/config/master_prompt.md',
            'task_types': None,
            'session_max_tokens': self.config['tokens'].get('session_max', 200000),
            'description': 'General-purpose autonomous agent'
        }
    
    def _get_prompt_path(self) -> str:
        """Get the prompt file path for this agent."""
        return self.agent_config.get(
            'prompt_file',
            '/auto-dev/config/master_prompt.md'
        )
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_requested = True
        
        # Update status to offline
        self.orchestrator.update_agent_status(self.agent_id, 'offline')
        
        if self.worker and self.worker.is_alive():
            self.worker.stop()
    
    def _check_token_budget(self) -> bool:
        """
        Check if we're within token budget.
        
        Returns:
            True if within budget, False if exceeded
        """
        # Reset daily counters if needed
        now = datetime.utcnow()
        if now.date() > self.state.daily_reset_time.date():
            logger.info("Resetting daily token counter")
            self.state.total_tokens_today = 0
            self.state.total_income_today = 0.0
            self.state.daily_reset_time = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        
        daily_budget = self.config['tokens']['daily_budget']
        
        # 0 means unlimited (Claude Max)
        if daily_budget == 0:
            return True
        
        warning_threshold = self.config['tokens']['warning_threshold']
        usage_ratio = self.state.total_tokens_today / daily_budget
        
        if usage_ratio >= 1.0:
            logger.warning("Daily token budget exceeded!")
            return False
        
        if usage_ratio >= warning_threshold:
            logger.warning(f"Token usage at {usage_ratio*100:.1f}% of daily budget")
        
        return True
    
    def _check_session_duration(self) -> bool:
        """
        Check if current session has exceeded max duration.
        
        Returns:
            True if within limits, False if should restart
        """
        if self.state.current_session is None:
            return True
        
        max_duration = self.config['watcher']['max_session_duration']
        elapsed = (datetime.utcnow() - self.state.current_session.start_time).total_seconds()
        
        if elapsed > max_duration:
            logger.info(f"Session exceeded max duration ({max_duration}s)")
            return False
        
        return True
    
    def _check_messages(self) -> None:
        """Check for messages from other agents."""
        messages = self.orchestrator.get_messages(self.agent_id, unread_only=True)
        
        for msg in messages:
            logger.info(f"Received message from {msg.from_agent}: {msg.message_type}")
            
            if msg.message_type == MessageType.HANDOFF.value:
                # Create a task from the handoff
                payload = msg.payload
                self.orchestrator.create_task(
                    task_type=payload.get('task_type', TaskType.BUILD_PRODUCT.value),
                    payload=payload.get('task_payload', {}),
                    priority=payload.get('priority', 5),
                    created_by=msg.from_agent
                )
            
            # Mark as read
            self.orchestrator.mark_read(msg.id, self.agent_id)
    
    def _claim_next_task(self) -> Optional[Task]:
        """Claim the next available task for this agent."""
        task_types = self.AGENT_TASK_TYPES.get(self.agent_id)
        return self.orchestrator.claim_task(self.agent_id, task_types=task_types)
    
    def _build_task_context(self, task: Task) -> str:
        """Build context string for a task."""
        return f"""You have been assigned a task:

**Task ID**: {task.id}
**Type**: {task.type}
**Priority**: {task.priority}/10
**Created by**: {task.created_by or 'System'}

**Task Details**:
```json
{json.dumps(task.payload, indent=2)}
```

Complete this task efficiently. When done, your output should clearly indicate:
1. What was accomplished
2. Any assets created (files, URLs, etc.)
3. Recommended next steps
4. Any issues encountered

If this task should be handed off to another agent, indicate that clearly with the target agent (hunter, builder, or publisher).
"""
    
    def _log_session_start(self, session_id: str) -> None:
        """Log session start to memory."""
        self.memory.add_memory(ShortTermMemory(
            id=None,
            timestamp=datetime.utcnow().isoformat(),
            type='action',
            content=f"[{self.agent_id}] Started new session: {session_id}",
            tokens_used=0
        ))
    
    def _log_session_end(self, session: SessionStats) -> None:
        """Log session end to memory."""
        duration = (session.end_time - session.start_time).total_seconds() if session.end_time else 0
        
        self.memory.add_memory(ShortTermMemory(
            id=None,
            timestamp=datetime.utcnow().isoformat(),
            type='observation',
            content=f"[{self.agent_id}] Session {session.session_id} ended. "
                   f"Duration: {duration:.0f}s, Exit code: {session.exit_code}, "
                   f"Tasks: {session.tasks_completed}",
            tokens_used=session.tokens_used
        ))
    
    def _start_new_session(self, task: Optional[Task] = None) -> bool:
        """
        Start a new Claude Code session.
        
        Args:
            task: Optional task to work on
            
        Returns:
            True if started successfully, False otherwise
        """
        try:
            # Build task context if we have a task
            task_context = None
            # Always reset current_task to avoid completing stale tasks
            self.state.current_task = None
            self.state.task_start_time = None
            if task:
                task_context = self._build_task_context(task)
                self.state.current_task = task
                self.state.task_start_time = datetime.utcnow()  # Track start time for duration
            
            provider = self._select_provider()
            provider_config = self._get_provider_config(provider)
            model = self._resolve_model_for_provider(provider)

            self.worker = AgentWorkerProcess(
                prompt_path=self._get_prompt_path(),
                working_dir='/auto-dev/data/projects',
                agent_id=self.agent_id,
                task_context=task_context,
                provider=provider,
                provider_config=provider_config,
                model=model
            )
            
            session_id = self.worker.start()
            
            self.state.current_session = SessionStats(
                session_id=session_id,
                start_time=datetime.utcnow(),
                agent_id=self.agent_id,
                provider=provider
            )
            self.state.total_sessions += 1
            self.state.last_restart = datetime.utcnow()
            self.state.consecutive_failures = 0
            
            # Update orchestrator status
            self.orchestrator.update_agent_status(
                self.agent_id,
                'working',
                current_task_id=task.id if task else None
            )
            
            self._log_session_start(session_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start session: {e}")
            self.state.consecutive_failures += 1
            return False
    
    def _capture_process_output(self) -> tuple:
        """Safely capture stdout/stderr from completed process. Can only be called once."""
        if not self.worker or not self.worker.process:
            return "", ""
        
        try:
            if self.worker.process.poll() is None:
                return "", ""  # Process still running
            stdout, stderr = self.worker.process.communicate(timeout=5)
            return stdout or "", stderr or ""
        except Exception as e:
            logger.debug(f"Failed to capture process output: {e}")
            return "", ""
    
    def _handle_session_end(self, exit_code: int) -> None:
        """Handle the end of a session."""
        # Capture output ONCE before processing (communicate() can only be called once)
        stdout, stderr = self._capture_process_output()
        output = stdout + stderr
        
        # Check for rate limit
        rate_limit_reset = None
        rate_limit_provider = self.worker.provider if self.worker else "claude"
        if exit_code != 0:
            rate_limit_reset = self._detect_rate_limit_from_output(output, rate_limit_provider)
            if rate_limit_reset:
                self._set_rate_limit(rate_limit_reset, rate_limit_provider)
        
        if self.state.current_session:
            self.state.current_session.end_time = datetime.utcnow()
            self.state.current_session.exit_code = exit_code
            
            # Try to parse token usage from Claude's JSON output
            tokens_used = self._parse_token_usage(stdout)
            self.state.current_session.tokens_used = tokens_used.get('total', 0)
            
            # Record token usage in orchestrator
            if tokens_used.get('total', 0) > 0:
                self.orchestrator.record_token_usage(
                    agent_id=self.agent_id,
                    input_tokens=tokens_used.get('input', 0),
                    output_tokens=tokens_used.get('output', 0),
                    session_id=self.state.current_session.session_id
                )
            
            # Update totals
            self.state.total_tokens_today += self.state.current_session.tokens_used
            self.state.total_income_today += self.state.current_session.income_generated
            
            self._log_session_end(self.state.current_session)
            
            if exit_code != 0 and not rate_limit_reset:
                # Only count as failure if not rate limited
                self.state.consecutive_failures += 1
                logger.warning(f"Session exited with code {exit_code}")
            
            self.state.current_session = None
        
        retry_task = False
        if rate_limit_reset and self._should_fallback_on_rate_limit(rate_limit_provider):
            retry_task = True
            logger.info(
                f"Rate limit for {rate_limit_provider}; will retry task with fallback provider."
            )
        elif rate_limit_reset:
            self._wait_for_rate_limit_reset(rate_limit_reset)
        
        # Complete current task if any
        if self.state.current_task:
            task = self.state.current_task
            task_start = self.state.task_start_time
            self.state.current_task = None
            self.state.task_start_time = None
            if retry_task:
                self.state.retry_task = task
            else:
                success = exit_code == 0
                self.orchestrator.complete_task(
                    task.id,
                    self.agent_id,
                    result={'exit_code': exit_code} if success else None,
                    error=f"Session exited with code {exit_code}" if not success else None
                )
                if success:
                    self.orchestrator.increment_completed(self.agent_id)

                # Record outcome for learning system
                duration_seconds = None
                if task_start:
                    duration_seconds = int((datetime.utcnow() - task_start).total_seconds())
                try:
                    self.orchestrator.record_outcome(
                        task_id=task.id,
                        repo_id=task.repo_id,
                        agent_id=self.agent_id,
                        task_type=task.type,
                        outcome='success' if success else 'failure',
                        duration_seconds=duration_seconds,
                        error_summary=f"Exit code {exit_code}" if not success else None,
                        context_summary=task.payload.get('instruction', '')[:200] if isinstance(task.payload, dict) else None
                    )
                except Exception as e:
                    logger.warning(f"Failed to record outcome: {e}")

        # Update status
        self.orchestrator.update_agent_status(self.agent_id, 'idle')
    
    def _check_rate_limit(self, provider: Optional[str] = None) -> Optional[datetime]:
        """
        Check if we're rate limited by checking shared file.

        Args:
            provider: Optional provider filter.

        Returns:
            Reset time if rate limited, None otherwise
        """
        status = self._get_rate_limit_status()
        if not status:
            return None
        if provider and status['provider'] != provider:
            return None
        return status['reset_time']
    
    def _set_rate_limit(self, reset_time: datetime, provider: str) -> None:
        """Set the shared rate limit file so all agents can react (atomic operation)."""
        import tempfile
        try:
            # Use atomic write: write to temp file, then rename
            # This prevents race conditions where multiple agents write simultaneously
            data = json.dumps({
                'provider': provider,
                'reset_time': reset_time.isoformat(),
                'set_by': self.agent_id,
                'set_at': datetime.utcnow().isoformat()
            })

            # Create temp file in same directory (required for atomic rename)
            temp_fd, temp_path = tempfile.mkstemp(
                dir=RATE_LIMIT_FILE.parent,
                prefix='.rate_limit_',
                suffix='.tmp'
            )
            try:
                os.write(temp_fd, data.encode('utf-8'))
                os.fsync(temp_fd)  # Ensure data is flushed to disk
            finally:
                os.close(temp_fd)

            # Atomic rename (on POSIX systems)
            os.replace(temp_path, RATE_LIMIT_FILE)

            logger.warning(f"Rate limit set for {provider} until {reset_time.isoformat()}")

            # Send Slack notification
            try:
                from dashboard.slack_notifications import notify_rate_limit
                notify_rate_limit(self.agent_id, reset_time.isoformat())
            except Exception as e:
                logger.warning(f"Failed to send Slack rate limit notification: {e}")

        except Exception as e:
            logger.error(f"Failed to set rate limit file: {e}")
            # Clean up temp file if it exists
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    
    def _detect_rate_limit_from_output(self, output: str, provider: str) -> Optional[datetime]:
        """
        Check CLI output for rate limit messages.

        Example Claude CLI output: "You've hit your limit · resets 5pm (UTC)"
        
        Args:
            output: Combined stdout+stderr from the process
        """
        if not output:
            return None
        
        try:
            
            # Look for rate limit message
            lower_output = output.lower()
            if "hit your limit" in lower_output or "rate limit" in lower_output or "429" in lower_output:
                # Try to parse reset time like "resets 5pm (UTC)"
                import re
                match = re.search(r'resets?\s+(\d{1,2})(am|pm)\s*\(?\s*UTC\s*\)?', output, re.IGNORECASE)
                if match:
                    hour = int(match.group(1))
                    ampm = match.group(2).lower()
                    if ampm == 'pm' and hour != 12:
                        hour += 12
                    elif ampm == 'am' and hour == 12:
                        hour = 0
                    
                    now = datetime.utcnow()
                    reset = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                    
                    # If reset time is in the past, it's tomorrow
                    if reset <= now:
                        reset = reset + timedelta(days=1)
                    
                    return reset
                else:
                    # Default: assume reset in 1 hour if we can't parse
                    return datetime.utcnow() + timedelta(hours=1)
            
        except Exception as e:
            logger.debug(f"Error checking for rate limit: {e}")
        
        return None
    
    def _wait_for_rate_limit_reset(self, reset_time: datetime) -> None:
        """Wait until rate limit resets, updating status periodically."""
        self.state.rate_limited = True
        self.state.rate_limit_reset = reset_time
        self.orchestrator.update_agent_status(self.agent_id, 'rate_limited')
        
        logger.info(f"Rate limited until {reset_time.isoformat()}. Pausing...")
        
        while datetime.utcnow() < reset_time and not self.shutdown_requested:
            remaining = (reset_time - datetime.utcnow()).total_seconds()
            if remaining > 0:
                # Update status file with wait time
                self._write_status_file()
                # Sleep in chunks so we can respond to shutdown
                time.sleep(min(60, remaining))
        
        # Clear rate limit
        self.state.rate_limited = False
        self.state.rate_limit_reset = None
        if RATE_LIMIT_FILE.exists():
            try:
                RATE_LIMIT_FILE.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete rate limit file: {e}")
        
        self.orchestrator.update_agent_status(self.agent_id, 'idle')
        logger.info("Rate limit reset. Resuming...")
    
    def _parse_token_usage(self, stdout: str) -> Dict[str, int]:
        """
        Parse token usage from Claude's JSON output.
        
        Claude CLI with --output-format json returns usage info like:
        {"result": "...", "usage": {"input_tokens": 1234, "output_tokens": 567}}
        
        Args:
            stdout: stdout from the process (passed from _handle_session_end)
        """
        if not stdout:
            return {'input': 0, 'output': 0, 'total': 0}
        
        try:
            # Try to parse JSON output
            # Claude may output multiple JSON objects (one per turn)
            total_input = 0
            total_output = 0
            
            for line in stdout.strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if 'usage' in data:
                        usage = data['usage']
                        total_input += usage.get('input_tokens', usage.get('prompt_tokens', 0))
                        total_output += usage.get('output_tokens', usage.get('completion_tokens', 0))
                    # Also check for top-level tokens (some formats)
                    elif 'input_tokens' in data or 'prompt_tokens' in data:
                        total_input += data.get('input_tokens', data.get('prompt_tokens', 0))
                        total_output += data.get('output_tokens', data.get('completion_tokens', 0))
                except json.JSONDecodeError:
                    continue
            
            return {
                'input': total_input,
                'output': total_output,
                'total': total_input + total_output
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse token usage: {e}")
            return {'input': 0, 'output': 0, 'total': 0}
    
    def _get_restart_delay(self) -> int:
        """Get restart delay with exponential backoff for failures."""
        base_delay = self.config['watcher']['restart_delay']
        
        if self.state.consecutive_failures > 0:
            # Exponential backoff: 10s, 20s, 40s, 80s, max 300s
            delay = min(base_delay * (2 ** self.state.consecutive_failures), 300)
            logger.info(f"Using backoff delay: {delay}s (failures: {self.state.consecutive_failures})")
            return delay
        
        return base_delay
    
    def _get_session_throttle_delay(self) -> int:
        """
        Get randomized delay between sessions to prevent hitting rate limits.
        
        Returns:
            Delay in seconds (between session_delay_min and session_delay_max)
        """
        import random
        min_delay = self.config['watcher'].get('session_delay_min', 30)
        max_delay = self.config['watcher'].get('session_delay_max', 60)
        return random.randint(min_delay, max_delay)
    
    def _check_concurrent_limit(self) -> bool:
        """
        Check if we've hit the concurrent agent limit.
        
        Only counts agents that are actively processing tasks (have both session and task).
        This prevents deadlocks where agents are waiting but counted as "working".
        
        Returns:
            True if we can start, False if we should wait
        """
        max_concurrent = self.config.get('orchestrator', {}).get('max_concurrent_agents', 10)
        
        # Count currently working agents from status files
        status_dir = Path('/auto-dev/data')
        working_count = 0
        
        for status_file in status_dir.glob('watcher_status_*.json'):
            if status_file.name == f'watcher_status_{self.agent_id}.json':
                continue  # Don't count ourselves
            try:
                data = json.loads(status_file.read_text())
                # Only count agents that are actively processing a task
                # Must have: running session + current task + not rate limited
                has_session = data.get('is_running') and (data.get('current_session') or {}).get('id')
                has_task = (data.get('current_task') or {}).get('id')
                not_rate_limited = not (data.get('rate_limit') or {}).get('limited')

                if has_session and has_task and not_rate_limited:
                    working_count += 1
            except (json.JSONDecodeError, OSError, KeyError) as e:
                # Skip malformed or inaccessible status files
                logger.debug(f"Skipping status file {status_file}: {e}")
                continue
        
        if working_count >= max_concurrent:
            logger.info(f"Concurrent limit reached ({working_count}/{max_concurrent}), waiting...")
            return False
        
        return True
    
    def run(self) -> None:
        """Main watcher loop."""
        logger.info(f"Starting Agent Runner (agent: {self.agent_id})")
        self.state.is_running = True
        
        # Register with orchestrator
        self.orchestrator.update_agent_status(self.agent_id, 'online')
        
        while not self.shutdown_requested:
            try:
                # Check if agent is enabled via Redis
                if not self._is_agent_enabled():
                    self.orchestrator.update_agent_status(self.agent_id, 'disabled')
                    logger.info(f"Agent {self.agent_id} is disabled, waiting...")
                    time.sleep(10)  # Check again in 10 seconds
                    continue

                # Check for shared rate limit (set by any agent)
                rate_limit = self._get_rate_limit_status()
                if rate_limit:
                    provider = self._select_provider()
                    if provider == rate_limit['provider']:
                        logger.info(
                            f"Provider {provider} rate limited. Pausing until "
                            f"{rate_limit['reset_time'].isoformat()}"
                        )
                        self._wait_for_rate_limit_reset(rate_limit['reset_time'])
                        continue
                    logger.info(
                        f"Provider {rate_limit['provider']} rate limited. "
                        f"Using fallback provider {provider}."
                    )
                
                # Check token budget
                if not self._check_token_budget():
                    logger.info("Token budget exceeded, waiting for reset...")
                    self.orchestrator.update_agent_status(self.agent_id, 'budget_exceeded')
                    time.sleep(3600)  # Wait an hour
                    continue
                
                # Check for messages from other agents
                self._check_messages()
                
                # Start new session if needed
                if self.worker is None or not self.worker.is_alive():
                    if self.worker is not None:
                        exit_code = self.worker.process.returncode if self.worker.process else 0
                        self._handle_session_end(exit_code)
                    
                    # Check concurrent agent limit
                    if not self._check_concurrent_limit():
                        self.orchestrator.update_agent_status(self.agent_id, 'waiting')
                        time.sleep(30)  # Wait and retry
                        continue
                    
                    # Get restart delay (with exponential backoff for failures)
                    delay = self._get_restart_delay()
                    if delay > self.config['watcher']['restart_delay']:
                        logger.info(f"Waiting {delay}s before restart (backoff)...")
                        time.sleep(delay)
                    
                    # Add session throttle delay (prevents Anthropic rate limits)
                    throttle_delay = self._get_session_throttle_delay()
                    logger.info(f"Session throttle: waiting {throttle_delay}s before starting...")
                    time.sleep(throttle_delay)
                    
                    # Try to claim a task from the queue (or retry previous on rate limit fallback)
                    task = None
                    if self.state.retry_task:
                        task = self.state.retry_task
                        self.state.retry_task = None
                    else:
                        task = self._claim_next_task()
                    
                    if not self._start_new_session(task):
                        logger.error("Failed to start session, retrying...")
                        time.sleep(self._get_restart_delay())
                        continue
                
                # Check session duration
                if not self._check_session_duration():
                    logger.info("Restarting session due to duration limit...")
                    if self.worker:
                        exit_code = self.worker.stop()
                        self._handle_session_end(exit_code)
                    continue
                
                # Write status file for dashboard
                self._write_status_file()
                
                # Health check interval
                time.sleep(self.config['watcher']['health_check_interval'])
                
            except Exception as e:
                logger.exception(f"Error in watcher loop: {e}")
                time.sleep(10)
        
        # Cleanup
        if self.worker and self.worker.is_alive():
            self.worker.stop()
        
        self.state.is_running = False
        self.orchestrator.update_agent_status(self.agent_id, 'offline')
        logger.info("Watcher stopped")
    
    def _write_status_file(self) -> None:
        """Write current status to file for dashboard."""
        status = self.get_status()
        status_path = Path(f'/auto-dev/data/watcher_status_{self.agent_id}.json')
        try:
            status_path.write_text(json.dumps(status, default=str))
        except Exception as e:
            logger.error(f"Failed to write status file: {e}")
        
        # Also write combined status for backward compatibility
        if self.agent_id == 'master':
            combined_path = Path('/auto-dev/data/watcher_status.json')
            try:
                combined_path.write_text(json.dumps(status, default=str))
            except Exception:
                pass
    
    def get_status(self) -> Dict[str, Any]:
        """Get current watcher status for the dashboard."""
        # Calculate rate limit wait time if applicable
        rate_limit_wait = None
        if self.state.rate_limited and self.state.rate_limit_reset:
            remaining = (self.state.rate_limit_reset - datetime.utcnow()).total_seconds()
            rate_limit_wait = max(0, remaining)
        
        return {
            'agent_id': self.agent_id,
            'agent_name': self.agent_config.get('name', self.agent_id),
            'is_running': self.state.is_running,
            'current_session': {
                'id': self.state.current_session.session_id if self.state.current_session else None,
                'start_time': self.state.current_session.start_time.isoformat() if self.state.current_session else None,
                'provider': self.state.current_session.provider if self.state.current_session else None,
                'duration': (datetime.utcnow() - self.state.current_session.start_time).total_seconds() 
                           if self.state.current_session else 0
            },
            'current_task': {
                'id': self.state.current_task.id if self.state.current_task else None,
                'type': self.state.current_task.type if self.state.current_task else None,
                'priority': self.state.current_task.priority if self.state.current_task else None
            } if self.state.current_task else None,
            'total_sessions': self.state.total_sessions,
            'total_tokens_today': self.state.total_tokens_today,
            'total_income_today': self.state.total_income_today,
            'consecutive_failures': self.state.consecutive_failures,
            'last_restart': self.state.last_restart.isoformat() if self.state.last_restart else None,
            'rate_limit': {
                'limited': self.state.rate_limited,
                'reset_time': self.state.rate_limit_reset.isoformat() if self.state.rate_limit_reset else None,
                'wait_seconds': rate_limit_wait
            },
            'token_budget': {
                'daily_limit': self.config['tokens']['daily_budget'],
                'used': self.state.total_tokens_today,
                'remaining': max(0, self.config['tokens']['daily_budget'] - self.state.total_tokens_today)
                            if self.config['tokens']['daily_budget'] > 0 else 'unlimited'
            }
        }


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Auto-Dev Agent Runner - runs a single AI agent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Agent Types:
  pm          Product Manager - defines what to build
  architect   Designs solutions, writes specs
  builder     Implements features and fixes
  reviewer    Reviews merge requests
  tester      Writes and runs tests
  security    Security scanning and audits
  devops      CI/CD and deployments
  bug_finder  Proactive bug detection

Examples:
  python -m watcher.agent_runner --agent pm
  python -m watcher.agent_runner --agent builder
  python -m watcher.agent_runner --agent reviewer
"""
    )
    parser.add_argument(
        '--agent', '-a',
        choices=['pm', 'architect', 'builder', 'reviewer', 'tester', 'security', 'devops', 'bug_finder', 'master'],
        default='pm',
        help='Agent type to run as (default: master)'
    )
    parser.add_argument(
        '--config', '-c',
        default='/auto-dev/config/settings.yaml',
        help='Path to configuration file'
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    runner = AgentRunner(
        config_path=args.config,
        agent_id=args.agent
    )
    runner.run()


if __name__ == '__main__':
    main()
