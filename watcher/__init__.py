"""
Autonomous Claude Watcher Package
=================================

Provides the supervisor and memory systems for the autonomous agent.
"""

from .memory import (
    ShortTermMemory,
    LongTermMemory,
    IncomeEntry,
    ShortTermMemoryDB,
    LongTermMemoryDB,
    create_memory_systems
)

from .supervisor import (
    AutonomousClaudeWatcher,
    ClaudeWorkerProcess,
    SessionStats,
    WatcherState
)

__all__ = [
    'ShortTermMemory',
    'LongTermMemory', 
    'IncomeEntry',
    'ShortTermMemoryDB',
    'LongTermMemoryDB',
    'create_memory_systems',
    'AutonomousClaudeWatcher',
    'ClaudeWorkerProcess',
    'SessionStats',
    'WatcherState'
]

