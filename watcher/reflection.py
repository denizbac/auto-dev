"""
Agent Reflection and Learning Framework

Enables agents to:
1. Reflect on completed tasks (successes/failures)
2. Extract learnings and patterns
3. Suggest prompt/skill improvements
4. Build a knowledge base for future reference

This creates a feedback loop where agents continuously improve.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ReflectionType(Enum):
    """Types of reflections agents can make."""
    TASK_COMPLETION = "task_completion"      # After finishing a task
    ERROR_ANALYSIS = "error_analysis"        # When something went wrong
    PATTERN_DISCOVERY = "pattern_discovery"  # Found a reusable pattern
    SKILL_GAP = "skill_gap"                  # Identified missing capability
    PROMPT_IMPROVEMENT = "prompt_improvement"  # Suggestion to improve prompts
    WORKFLOW_OPTIMIZATION = "workflow_optimization"  # Better way to do things


class LearningCategory(Enum):
    """Categories for learnings."""
    CODE_PATTERNS = "code_patterns"
    ERROR_HANDLING = "error_handling"
    TESTING_STRATEGIES = "testing_strategies"
    REVIEW_INSIGHTS = "review_insights"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PERFORMANCE = "performance"
    TOOLING = "tooling"
    COMMUNICATION = "communication"
    PROCESS = "process"


@dataclass
class Reflection:
    """A reflection entry from an agent."""
    id: str
    agent_id: str
    repo_id: str
    task_id: Optional[str]
    reflection_type: str
    category: str
    summary: str
    details: str
    learnings: List[str]
    suggestions: List[str]
    confidence: int  # 1-10 how confident the agent is
    created_at: str
    metadata: Dict[str, Any]


@dataclass
class Learning:
    """A validated learning that can be applied."""
    id: str
    source_reflection_id: str
    agent_id: str
    repo_id: Optional[str]  # None = applies to all repos
    category: str
    title: str
    description: str
    applicability: str  # When to apply this learning
    example: Optional[str]
    validated: bool
    validation_count: int  # How many times it proved useful
    created_at: str
    updated_at: str


@dataclass
class PromptSuggestion:
    """A suggestion to improve an agent's prompt."""
    id: str
    agent_id: str
    current_section: str  # Which part of the prompt to modify
    suggested_change: str
    rationale: str
    expected_improvement: str
    source_reflections: List[str]  # Reflection IDs that led to this
    status: str  # pending, approved, rejected, applied
    created_at: str


class ReflectionManager:
    """
    Manages agent reflections and learnings.

    This is the core of the learning system - it stores reflections,
    extracts patterns, and helps agents improve over time.
    """

    def __init__(self, db_connection, config: Optional[Dict] = None):
        """
        Initialize reflection manager.

        Args:
            db_connection: Database connection (PostgreSQL or SQLite)
            config: Optional configuration overrides
        """
        self.db = db_connection
        self.config = config or {}
        self._init_tables()

    def _init_tables(self):
        """Initialize database tables for reflection system."""
        cursor = self.db.cursor()

        # Reflections table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                repo_id TEXT,
                task_id TEXT,
                reflection_type TEXT NOT NULL,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT,
                learnings TEXT,  -- JSON array
                suggestions TEXT,  -- JSON array
                confidence INTEGER DEFAULT 5,
                created_at TEXT NOT NULL,
                metadata TEXT  -- JSON object
            )
        """)

        # Learnings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id TEXT PRIMARY KEY,
                source_reflection_id TEXT,
                agent_id TEXT NOT NULL,
                repo_id TEXT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                applicability TEXT,
                example TEXT,
                validated BOOLEAN DEFAULT FALSE,
                validation_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_reflection_id) REFERENCES reflections(id)
            )
        """)

        # Prompt suggestions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt_suggestions (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                current_section TEXT,
                suggested_change TEXT NOT NULL,
                rationale TEXT,
                expected_improvement TEXT,
                source_reflections TEXT,  -- JSON array of reflection IDs
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewer_notes TEXT
            )
        """)

        # Learning applications table (tracks when learnings are used)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_applications (
                id TEXT PRIMARY KEY,
                learning_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                successful BOOLEAN,
                notes TEXT,
                applied_at TEXT NOT NULL,
                FOREIGN KEY (learning_id) REFERENCES learnings(id)
            )
        """)

        self.db.commit()

    # ========== Reflection Operations ==========

    def add_reflection(
        self,
        agent_id: str,
        reflection_type: str,
        category: str,
        summary: str,
        details: str = "",
        learnings: List[str] = None,
        suggestions: List[str] = None,
        confidence: int = 5,
        repo_id: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Dict[str, Any] = None
    ) -> Reflection:
        """
        Add a new reflection from an agent.

        This is the primary way agents record their observations
        and learnings after completing tasks.
        """
        import uuid

        reflection = Reflection(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            repo_id=repo_id,
            task_id=task_id,
            reflection_type=reflection_type,
            category=category,
            summary=summary,
            details=details,
            learnings=learnings or [],
            suggestions=suggestions or [],
            confidence=confidence,
            created_at=datetime.utcnow().isoformat(),
            metadata=metadata or {}
        )

        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO reflections
            (id, agent_id, repo_id, task_id, reflection_type, category,
             summary, details, learnings, suggestions, confidence, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reflection.id,
            reflection.agent_id,
            reflection.repo_id,
            reflection.task_id,
            reflection.reflection_type,
            reflection.category,
            reflection.summary,
            reflection.details,
            json.dumps(reflection.learnings),
            json.dumps(reflection.suggestions),
            reflection.confidence,
            reflection.created_at,
            json.dumps(reflection.metadata)
        ))
        self.db.commit()

        logger.info(
            f"Added reflection {reflection.id} from {agent_id}: {summary[:50]}..."
        )

        # Auto-extract learnings if confidence is high
        if confidence >= 7 and learnings:
            self._auto_extract_learnings(reflection)

        return reflection

    def get_reflections(
        self,
        agent_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        reflection_type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Reflection]:
        """Get reflections with optional filters."""
        cursor = self.db.cursor()

        query = "SELECT * FROM reflections WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if repo_id:
            query += " AND (repo_id = ? OR repo_id IS NULL)"
            params.append(repo_id)
        if reflection_type:
            query += " AND reflection_type = ?"
            params.append(reflection_type)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_reflection(row) for row in rows]

    def _row_to_reflection(self, row) -> Reflection:
        """Convert database row to Reflection object."""
        return Reflection(
            id=row[0],
            agent_id=row[1],
            repo_id=row[2],
            task_id=row[3],
            reflection_type=row[4],
            category=row[5],
            summary=row[6],
            details=row[7],
            learnings=json.loads(row[8]) if row[8] else [],
            suggestions=json.loads(row[9]) if row[9] else [],
            confidence=row[10],
            created_at=row[11],
            metadata=json.loads(row[12]) if row[12] else {}
        )

    # ========== Learning Operations ==========

    def add_learning(
        self,
        agent_id: str,
        category: str,
        title: str,
        description: str,
        applicability: str = "",
        example: Optional[str] = None,
        repo_id: Optional[str] = None,
        source_reflection_id: Optional[str] = None
    ) -> Learning:
        """Add a validated learning."""
        import uuid

        now = datetime.utcnow().isoformat()
        learning = Learning(
            id=str(uuid.uuid4()),
            source_reflection_id=source_reflection_id,
            agent_id=agent_id,
            repo_id=repo_id,
            category=category,
            title=title,
            description=description,
            applicability=applicability,
            example=example,
            validated=False,
            validation_count=0,
            created_at=now,
            updated_at=now
        )

        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO learnings
            (id, source_reflection_id, agent_id, repo_id, category, title,
             description, applicability, example, validated, validation_count,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            learning.id,
            learning.source_reflection_id,
            learning.agent_id,
            learning.repo_id,
            learning.category,
            learning.title,
            learning.description,
            learning.applicability,
            learning.example,
            learning.validated,
            learning.validation_count,
            learning.created_at,
            learning.updated_at
        ))
        self.db.commit()

        return learning

    def get_learnings_for_task(
        self,
        agent_id: str,
        task_type: str,
        repo_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Learning]:
        """
        Get relevant learnings for a task.

        This is called before an agent starts a task to give them
        context from previous similar work.
        """
        cursor = self.db.cursor()

        # Get learnings for this agent or general learnings
        # Prioritize validated and frequently useful ones
        cursor.execute("""
            SELECT * FROM learnings
            WHERE (agent_id = ? OR agent_id = 'general')
            AND (repo_id = ? OR repo_id IS NULL)
            ORDER BY validated DESC, validation_count DESC, created_at DESC
            LIMIT ?
        """, (agent_id, repo_id, limit))

        rows = cursor.fetchall()
        return [self._row_to_learning(row) for row in rows]

    def validate_learning(self, learning_id: str, successful: bool = True):
        """Mark a learning as validated (or not)."""
        cursor = self.db.cursor()

        if successful:
            cursor.execute("""
                UPDATE learnings
                SET validated = TRUE,
                    validation_count = validation_count + 1,
                    updated_at = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), learning_id))
        else:
            cursor.execute("""
                UPDATE learnings
                SET validation_count = validation_count - 1,
                    updated_at = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), learning_id))

        self.db.commit()

    def record_learning_application(
        self,
        learning_id: str,
        task_id: str,
        agent_id: str,
        successful: bool,
        notes: str = ""
    ):
        """Record that a learning was applied to a task."""
        import uuid

        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO learning_applications
            (id, learning_id, task_id, agent_id, successful, notes, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            learning_id,
            task_id,
            agent_id,
            successful,
            notes,
            datetime.utcnow().isoformat()
        ))
        self.db.commit()

        # Update learning validation
        self.validate_learning(learning_id, successful)

    def _row_to_learning(self, row) -> Learning:
        """Convert database row to Learning object."""
        return Learning(
            id=row[0],
            source_reflection_id=row[1],
            agent_id=row[2],
            repo_id=row[3],
            category=row[4],
            title=row[5],
            description=row[6],
            applicability=row[7],
            example=row[8],
            validated=bool(row[9]),
            validation_count=row[10],
            created_at=row[11],
            updated_at=row[12]
        )

    def _auto_extract_learnings(self, reflection: Reflection):
        """Automatically extract learnings from high-confidence reflections."""
        for learning_text in reflection.learnings:
            # Create a learning entry for each item
            self.add_learning(
                agent_id=reflection.agent_id,
                category=reflection.category,
                title=learning_text[:100],
                description=learning_text,
                repo_id=reflection.repo_id,
                source_reflection_id=reflection.id
            )

    # ========== Prompt Suggestion Operations ==========

    def suggest_prompt_improvement(
        self,
        agent_id: str,
        suggested_change: str,
        rationale: str,
        expected_improvement: str,
        current_section: str = "",
        source_reflections: List[str] = None
    ) -> PromptSuggestion:
        """
        Suggest an improvement to an agent's prompt.

        These suggestions are reviewed by humans before being applied.
        """
        import uuid

        suggestion = PromptSuggestion(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            current_section=current_section,
            suggested_change=suggested_change,
            rationale=rationale,
            expected_improvement=expected_improvement,
            source_reflections=source_reflections or [],
            status='pending',
            created_at=datetime.utcnow().isoformat()
        )

        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO prompt_suggestions
            (id, agent_id, current_section, suggested_change, rationale,
             expected_improvement, source_reflections, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            suggestion.id,
            suggestion.agent_id,
            suggestion.current_section,
            suggestion.suggested_change,
            suggestion.rationale,
            suggestion.expected_improvement,
            json.dumps(suggestion.source_reflections),
            suggestion.status,
            suggestion.created_at
        ))
        self.db.commit()

        logger.info(
            f"Prompt suggestion {suggestion.id} for {agent_id}: "
            f"{suggested_change[:50]}..."
        )

        return suggestion

    def get_prompt_suggestions(
        self,
        agent_id: Optional[str] = None,
        status: str = 'pending',
        limit: int = 20
    ) -> List[PromptSuggestion]:
        """Get prompt suggestions for review."""
        cursor = self.db.cursor()

        query = "SELECT * FROM prompt_suggestions WHERE status = ?"
        params = [status]

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [PromptSuggestion(
            id=row[0],
            agent_id=row[1],
            current_section=row[2],
            suggested_change=row[3],
            rationale=row[4],
            expected_improvement=row[5],
            source_reflections=json.loads(row[6]) if row[6] else [],
            status=row[7],
            created_at=row[8]
        ) for row in rows]

    def review_prompt_suggestion(
        self,
        suggestion_id: str,
        status: str,  # 'approved', 'rejected', 'applied'
        reviewer_notes: str = ""
    ):
        """Review a prompt suggestion."""
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE prompt_suggestions
            SET status = ?,
                reviewed_at = ?,
                reviewer_notes = ?
            WHERE id = ?
        """, (status, datetime.utcnow().isoformat(), reviewer_notes, suggestion_id))
        self.db.commit()

    # ========== Analytics ==========

    def get_reflection_stats(
        self,
        agent_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get reflection statistics."""
        cursor = self.db.cursor()

        from_date = datetime.utcnow().isoformat()[:10]  # Simplified date calc

        base_query = "SELECT COUNT(*) FROM reflections WHERE created_at >= ?"
        params = [from_date]

        if agent_id:
            base_query += " AND agent_id = ?"
            params.append(agent_id)

        cursor.execute(base_query, params)
        total = cursor.fetchone()[0]

        # By type
        cursor.execute(f"""
            SELECT reflection_type, COUNT(*) as count
            FROM reflections
            WHERE created_at >= ?
            {f"AND agent_id = '{agent_id}'" if agent_id else ""}
            GROUP BY reflection_type
        """, [from_date])
        by_type = dict(cursor.fetchall())

        # By category
        cursor.execute(f"""
            SELECT category, COUNT(*) as count
            FROM reflections
            WHERE created_at >= ?
            {f"AND agent_id = '{agent_id}'" if agent_id else ""}
            GROUP BY category
        """, [from_date])
        by_category = dict(cursor.fetchall())

        return {
            'total_reflections': total,
            'by_type': by_type,
            'by_category': by_category,
            'period_days': days
        }

    def get_learning_effectiveness(self, learning_id: str) -> Dict[str, Any]:
        """Get effectiveness metrics for a learning."""
        cursor = self.db.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_applications,
                SUM(CASE WHEN successful THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN NOT successful THEN 1 ELSE 0 END) as failed
            FROM learning_applications
            WHERE learning_id = ?
        """, (learning_id,))

        row = cursor.fetchone()
        total = row[0] or 0
        successful = row[1] or 0
        failed = row[2] or 0

        return {
            'learning_id': learning_id,
            'total_applications': total,
            'successful': successful,
            'failed': failed,
            'success_rate': successful / total if total > 0 else 0
        }


# ========== Helper Functions for Agents ==========

def create_task_reflection_prompt(
    task_type: str,
    task_result: Dict[str, Any],
    duration_seconds: int,
    errors: List[str] = None
) -> str:
    """
    Generate a reflection prompt for agents to use after completing a task.

    This prompt guides agents to think about what they did and what they learned.
    """
    status = "succeeded" if not errors else "encountered issues"

    return f"""
## Task Reflection

You just completed a **{task_type}** task that **{status}**.

**Duration**: {duration_seconds} seconds
**Errors**: {len(errors or [])}

Please reflect on this task by answering:

1. **What went well?**
   - What approaches or techniques worked effectively?
   - What patterns did you follow that were helpful?

2. **What could be improved?**
   - Were there any inefficiencies in your approach?
   - Did you encounter any unexpected challenges?

3. **Key Learnings** (list 1-3 specific learnings)
   - What would you do differently next time?
   - What insights could help with similar tasks?

4. **Suggestions** (optional)
   - Do you have any suggestions to improve your prompts or skills?
   - Are there tools or capabilities that would have helped?

Format your reflection as JSON:
```json
{{
    "summary": "Brief 1-2 sentence summary",
    "went_well": ["item1", "item2"],
    "improvements": ["item1", "item2"],
    "learnings": ["learning1", "learning2"],
    "suggestions": ["suggestion1"],
    "confidence": 7
}}
```
"""


def format_learnings_for_context(learnings: List[Learning]) -> str:
    """
    Format learnings as context to inject into agent prompts.

    This gives agents access to their previous learnings before starting a task.
    """
    if not learnings:
        return ""

    lines = ["## Relevant Learnings from Previous Work\n"]

    for learning in learnings[:5]:  # Limit to 5 most relevant
        lines.append(f"### {learning.title}")
        lines.append(f"{learning.description}")
        if learning.applicability:
            lines.append(f"*Apply when*: {learning.applicability}")
        if learning.example:
            lines.append(f"*Example*: {learning.example}")
        lines.append("")

    return "\n".join(lines)
