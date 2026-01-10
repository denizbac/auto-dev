"""
Memory Systems for Autonomous Claude Agent
===========================================

Provides both short-term (SQLite) and long-term (Qdrant) memory capabilities.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass
class ShortTermMemory:
    """Represents a short-term memory entry."""
    id: Optional[int]
    timestamp: str
    type: str  # action|observation|thought|goal|income
    content: str
    tokens_used: int = 0


@dataclass
class IncomeEntry:
    """Represents an income log entry."""
    id: Optional[int]
    timestamp: str
    source: str
    amount: float
    currency: str
    description: str


@dataclass
class LongTermMemory:
    """Represents a long-term memory entry."""
    id: str
    timestamp: str
    type: str  # fact|skill|preference|lesson|discovery|strategy
    tags: List[str]
    content: str
    importance: int  # 1-10
    income_potential: float = 0.0


class ShortTermMemoryDB:
    """SQLite-based short-term memory system."""
    
    def __init__(self, db_path: str, max_entries: int = 50):
        """
        Initialize short-term memory database.
        
        Args:
            db_path: Path to SQLite database file
            max_entries: Maximum number of entries to retain
        """
        self.db_path = Path(db_path)
        self.max_entries = max_entries
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens_used INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS income_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    description TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_income_timestamp ON income_log(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_timestamp ON token_usage(timestamp)")
            
            conn.commit()
    
    def add_memory(self, memory: ShortTermMemory) -> int:
        """
        Add a new memory entry.
        
        Args:
            memory: ShortTermMemory object to store
            
        Returns:
            ID of the inserted memory
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories (timestamp, type, content, tokens_used)
                VALUES (?, ?, ?, ?)
                """,
                (memory.timestamp, memory.type, memory.content, memory.tokens_used)
            )
            memory_id = cursor.lastrowid
            conn.commit()
            
            # Prune old entries
            self._prune_old_entries(conn)
            
            return memory_id
    
    def _prune_old_entries(self, conn: sqlite3.Connection) -> None:
        """Remove entries beyond max_entries limit."""
        conn.execute(
            """
            DELETE FROM memories WHERE id NOT IN (
                SELECT id FROM memories ORDER BY id DESC LIMIT ?
            )
            """,
            (self.max_entries,)
        )
        conn.commit()
    
    def get_recent(self, limit: int = 50) -> List[ShortTermMemory]:
        """
        Get recent memory entries.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of ShortTermMemory objects
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM memories ORDER BY id DESC LIMIT ?
                """,
                (limit,)
            )
            return [
                ShortTermMemory(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    type=row['type'],
                    content=row['content'],
                    tokens_used=row['tokens_used']
                )
                for row in cursor.fetchall()
            ]
    
    def get_by_type(self, memory_type: str, limit: int = 20) -> List[ShortTermMemory]:
        """Get memories filtered by type."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM memories WHERE type = ? ORDER BY id DESC LIMIT ?
                """,
                (memory_type, limit)
            )
            return [
                ShortTermMemory(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    type=row['type'],
                    content=row['content'],
                    tokens_used=row['tokens_used']
                )
                for row in cursor.fetchall()
            ]
    
    def log_income(self, entry: IncomeEntry) -> int:
        """Log an income entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO income_log (timestamp, source, amount, currency, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entry.timestamp, entry.source, entry.amount, entry.currency, entry.description)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_income_summary(self, days: int = 30) -> Dict[str, float]:
        """Get income summary by source for the last N days."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT source, currency, SUM(amount) as total
                FROM income_log
                WHERE timestamp >= datetime('now', ? || ' days')
                GROUP BY source, currency
                """,
                (-days,)
            )
            summary = {}
            for row in cursor.fetchall():
                key = f"{row[0]}_{row[1]}"
                summary[key] = row[2]
            return summary
    
    def log_token_usage(self, session_id: str, tokens_input: int, 
                        tokens_output: int, cost_usd: float) -> None:
        """Log token usage for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO token_usage (timestamp, session_id, tokens_input, tokens_output, cost_usd)
                VALUES (?, ?, ?, ?, ?)
                """,
                (datetime.utcnow().isoformat(), session_id, tokens_input, tokens_output, cost_usd)
            )
            conn.commit()
    
    def get_token_stats(self, days: int = 1) -> Dict[str, Any]:
        """Get token usage statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT 
                    SUM(tokens_input) as total_input,
                    SUM(tokens_output) as total_output,
                    SUM(cost_usd) as total_cost,
                    COUNT(DISTINCT session_id) as sessions
                FROM token_usage
                WHERE timestamp >= datetime('now', ? || ' days')
                """,
                (-days,)
            )
            row = cursor.fetchone()
            return {
                'total_input': row[0] or 0,
                'total_output': row[1] or 0,
                'total_tokens': (row[0] or 0) + (row[1] or 0),
                'total_cost': row[2] or 0.0,
                'sessions': row[3] or 0
            }
    
    def clear_all(self) -> None:
        """Clear all memories (use with caution)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM memories")
            conn.commit()


class LongTermMemoryDB:
    """Qdrant-based long-term memory system with semantic search."""
    
    def __init__(self, host: str = "localhost", port: int = 6333,
                 collection_name: str = "claude_memory",
                 embedding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialize long-term memory with Qdrant.
        
        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Name of the vector collection
            embedding_model: Sentence transformer model for embeddings
        """
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.encoder = SentenceTransformer(embedding_model)
        self.vector_size = self.encoder.get_sentence_embedding_dimension()
        self._ensure_collection()
    
    def _ensure_collection(self) -> None:
        """Ensure the collection exists."""
        collections = self.client.get_collections().collections
        if not any(c.name == self.collection_name for c in collections):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE
                )
            )
            logger.info(f"Created collection: {self.collection_name}")
    
    def store(self, memory: LongTermMemory) -> str:
        """
        Store a long-term memory.
        
        Args:
            memory: LongTermMemory object to store
            
        Returns:
            ID of the stored memory
        """
        # Generate embedding
        embedding = self.encoder.encode(memory.content).tolist()
        
        # Generate ID if not provided
        memory_id = memory.id or str(uuid.uuid4())
        
        # Store in Qdrant
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=memory_id,
                    vector=embedding,
                    payload={
                        "timestamp": memory.timestamp,
                        "type": memory.type,
                        "tags": memory.tags,
                        "content": memory.content,
                        "importance": memory.importance,
                        "income_potential": memory.income_potential
                    }
                )
            ]
        )
        
        logger.info(f"Stored long-term memory: {memory_id}")
        return memory_id
    
    def search(self, query: str, limit: int = 5, 
               min_importance: int = 0,
               type_filter: Optional[str] = None) -> List[LongTermMemory]:
        """
        Semantic search for relevant memories.
        
        Args:
            query: Search query
            limit: Maximum results
            min_importance: Minimum importance score
            type_filter: Optional filter by memory type
            
        Returns:
            List of matching LongTermMemory objects
        """
        # Generate query embedding
        query_embedding = self.encoder.encode(query).tolist()
        
        # Build filter
        must_conditions = []
        if min_importance > 0:
            must_conditions.append(
                models.FieldCondition(
                    key="importance",
                    range=models.Range(gte=min_importance)
                )
            )
        if type_filter:
            must_conditions.append(
                models.FieldCondition(
                    key="type",
                    match=models.MatchValue(value=type_filter)
                )
            )
        
        query_filter = models.Filter(must=must_conditions) if must_conditions else None
        
        # Search
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter
        )
        
        return [
            LongTermMemory(
                id=str(r.id),
                timestamp=r.payload['timestamp'],
                type=r.payload['type'],
                tags=r.payload['tags'],
                content=r.payload['content'],
                importance=r.payload['importance'],
                income_potential=r.payload.get('income_potential', 0.0)
            )
            for r in results
        ]
    
    def get_by_tags(self, tags: List[str], limit: int = 10) -> List[LongTermMemory]:
        """Get memories by tags."""
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                should=[
                    models.FieldCondition(
                        key="tags",
                        match=models.MatchValue(value=tag)
                    )
                    for tag in tags
                ]
            ),
            limit=limit
        )
        
        return [
            LongTermMemory(
                id=str(r.id),
                timestamp=r.payload['timestamp'],
                type=r.payload['type'],
                tags=r.payload['tags'],
                content=r.payload['content'],
                importance=r.payload['importance'],
                income_potential=r.payload.get('income_potential', 0.0)
            )
            for r in results[0]
        ]
    
    def get_top_strategies(self, limit: int = 5) -> List[LongTermMemory]:
        """Get top income-generating strategies."""
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="type",
                        match=models.MatchValue(value="strategy")
                    )
                ]
            ),
            limit=limit,
            order_by=models.OrderBy(
                key="income_potential",
                direction="desc"
            )
        )
        
        return [
            LongTermMemory(
                id=str(r.id),
                timestamp=r.payload['timestamp'],
                type=r.payload['type'],
                tags=r.payload['tags'],
                content=r.payload['content'],
                importance=r.payload['importance'],
                income_potential=r.payload.get('income_potential', 0.0)
            )
            for r in results[0]
        ]
    
    def count(self) -> int:
        """Get total number of memories."""
        info = self.client.get_collection(self.collection_name)
        return info.points_count
    
    def delete(self, memory_id: str) -> None:
        """Delete a memory by ID."""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[memory_id])
        )


def create_memory_systems(config: Dict[str, Any]) -> tuple:
    """
    Factory function to create memory systems from config.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Tuple of (ShortTermMemoryDB, LongTermMemoryDB)
    """
    short_term = ShortTermMemoryDB(
        db_path=config['memory']['short_term']['database_path'],
        max_entries=config['memory']['short_term']['max_entries']
    )
    
    long_term = LongTermMemoryDB(
        host=config['memory']['long_term']['host'],
        port=config['memory']['long_term']['port'],
        collection_name=config['memory']['long_term']['collection_name'],
        embedding_model=config['memory']['long_term']['embedding_model']
    )
    
    return short_term, long_term

