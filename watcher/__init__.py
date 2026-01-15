"""
Autonomous Claude Watcher Package
=================================

Provides the agent runner and memory systems for the autonomous agents.
"""

from .memory import (
    ShortTermMemory,
    LongTermMemory,
    IncomeEntry,
    ShortTermMemoryDB,
    LongTermMemoryDB,
    create_memory_systems
)

from .agent_runner import (
    AgentRunner,
    AgentWorkerProcess,
    SessionStats,
    AgentState
)

# Backwards compatibility aliases
AutonomousClaudeWatcher = AgentRunner
ClaudeWorkerProcess = AgentWorkerProcess
WatcherState = AgentState

__all__ = [
    'ShortTermMemory',
    'LongTermMemory',
    'IncomeEntry',
    'ShortTermMemoryDB',
    'LongTermMemoryDB',
    'create_memory_systems',
    'AgentRunner',
    'AgentWorkerProcess',
    'SessionStats',
    'AgentState',
    # Backwards compatibility
    'AutonomousClaudeWatcher',
    'ClaudeWorkerProcess',
    'WatcherState'
]

