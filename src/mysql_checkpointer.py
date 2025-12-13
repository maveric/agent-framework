"""
MySQL Checkpointer for LangGraph
================================
Custom async MySQL checkpoint saver implementing the LangGraph checkpointer interface.
This provides full async support on Windows where asyncpg has limitations.
"""

import json
import logging
from typing import Any, Dict, Iterator, Optional, Sequence, Tuple
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# Optional aiomysql import
try:
    import aiomysql
    AIOMYSQL_AVAILABLE = True
except ImportError:
    AIOMYSQL_AVAILABLE = False
    aiomysql = None


class AsyncMySQLSaver(BaseCheckpointSaver):
    """
    Async MySQL checkpoint saver for LangGraph.

    Provides full async database operations using aiomysql,
    which works correctly on Windows unlike asyncpg.

    Usage:
        # Using connection string
        async with AsyncMySQLSaver.from_conn_string("mysql://user:pass@localhost/db") as saver:
            # Use saver with LangGraph

        # Using individual parameters
        async with AsyncMySQLSaver.from_params(
            host="localhost", port=3306, user="root", password="", database="orchestrator"
        ) as saver:
            # Use saver with LangGraph
    """

    serde: SerializerProtocol = JsonPlusSerializer()

    def __init__(
        self,
        pool: "aiomysql.Pool",
        serde: Optional[SerializerProtocol] = None,
    ):
        super().__init__(serde=serde)
        if not AIOMYSQL_AVAILABLE:
            raise ImportError("aiomysql is required for AsyncMySQLSaver. Install with: pip install aiomysql")
        self.pool = pool

    @classmethod
    @asynccontextmanager
    async def from_conn_string(
        cls,
        conn_string: str,
        *,
        serde: Optional[SerializerProtocol] = None,
    ):
        """
        Create a MySQL saver from a connection string.

        Args:
            conn_string: MySQL connection string (mysql://user:pass@host:port/database)
            serde: Optional serializer

        Yields:
            AsyncMySQLSaver instance
        """
        if not AIOMYSQL_AVAILABLE:
            raise ImportError("aiomysql is required for AsyncMySQLSaver. Install with: pip install aiomysql")

        from urllib.parse import urlparse
        parsed = urlparse(conn_string)

        pool = await aiomysql.create_pool(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            db=parsed.path.lstrip("/") or "orchestrator",
            autocommit=True,
            minsize=1,
            maxsize=10,
        )

        try:
            saver = cls(pool=pool, serde=serde)
            yield saver
        finally:
            pool.close()
            await pool.wait_closed()

    @classmethod
    @asynccontextmanager
    async def from_params(
        cls,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "orchestrator",
        *,
        serde: Optional[SerializerProtocol] = None,
    ):
        """
        Create a MySQL saver from individual parameters.

        Args:
            host: MySQL host
            port: MySQL port
            user: MySQL user
            password: MySQL password
            database: Database name
            serde: Optional serializer

        Yields:
            AsyncMySQLSaver instance
        """
        if not AIOMYSQL_AVAILABLE:
            raise ImportError("aiomysql is required for AsyncMySQLSaver. Install with: pip install aiomysql")

        pool = await aiomysql.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=database,
            autocommit=True,
            minsize=1,
            maxsize=10,
        )

        try:
            saver = cls(pool=pool, serde=serde)
            yield saver
        finally:
            pool.close()
            await pool.wait_closed()

    async def setup(self) -> None:
        """Create the checkpoints table if it doesn't exist."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Create checkpoints table
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        parent_checkpoint_id VARCHAR(255),
                        type VARCHAR(255),
                        checkpoint LONGTEXT NOT NULL,
                        metadata LONGTEXT NOT NULL DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                    )
                """)

                # Create writes table for pending writes
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoint_writes (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        task_id VARCHAR(255) NOT NULL,
                        idx INT NOT NULL,
                        channel VARCHAR(255) NOT NULL,
                        type VARCHAR(255),
                        value LONGTEXT,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    )
                """)

        logger.info("✅ MySQL checkpoint tables initialized")

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Sync version - not implemented, use aget."""
        raise NotImplementedError("Use aget() for async operations")

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """Sync version - not implemented, use alist."""
        raise NotImplementedError("Use alist() for async operations")

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict] = None,
    ) -> RunnableConfig:
        """Sync version - not implemented, use aput."""
        raise NotImplementedError("Use aput() for async operations")

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Sync version - not implemented, use aput_writes."""
        raise NotImplementedError("Use aput_writes() for async operations")

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple from the database."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                if checkpoint_id:
                    # Get specific checkpoint
                    await cursor.execute(
                        """
                        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                               type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s
                        """,
                        (thread_id, checkpoint_ns, checkpoint_id),
                    )
                else:
                    # Get latest checkpoint
                    await cursor.execute(
                        """
                        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                               type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = %s AND checkpoint_ns = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (thread_id, checkpoint_ns),
                    )

                row = await cursor.fetchone()
                if not row:
                    return None

                # Get pending writes
                await cursor.execute(
                    """
                    SELECT task_id, channel, type, value
                    FROM checkpoint_writes
                    WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s
                    ORDER BY task_id, idx
                    """,
                    (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"]),
                )
                writes_rows = await cursor.fetchall()

                # Deserialize checkpoint and metadata
                checkpoint = self.serde.loads(row["checkpoint"])
                metadata = self.serde.loads(row["metadata"]) if row["metadata"] else {}

                # Deserialize pending writes
                pending_writes = []
                for write_row in writes_rows:
                    pending_writes.append((
                        write_row["task_id"],
                        write_row["channel"],
                        self.serde.loads(write_row["value"]) if write_row["value"] else None,
                    ))

                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": row["thread_id"],
                            "checkpoint_ns": row["checkpoint_ns"],
                            "checkpoint_id": row["checkpoint_id"],
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config={
                        "configurable": {
                            "thread_id": row["thread_id"],
                            "checkpoint_ns": row["checkpoint_ns"],
                            "checkpoint_id": row["parent_checkpoint_id"],
                        }
                    } if row["parent_checkpoint_id"] else None,
                    pending_writes=pending_writes,
                )

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        """List checkpoints from the database."""
        thread_id = config["configurable"]["thread_id"] if config else None
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "") if config else ""

        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                           type, checkpoint, metadata
                    FROM checkpoints
                    WHERE 1=1
                """
                params = []

                if thread_id:
                    query += " AND thread_id = %s"
                    params.append(thread_id)

                if checkpoint_ns:
                    query += " AND checkpoint_ns = %s"
                    params.append(checkpoint_ns)

                if before:
                    before_id = before["configurable"].get("checkpoint_id")
                    if before_id:
                        query += " AND checkpoint_id < %s"
                        params.append(before_id)

                query += " ORDER BY created_at DESC"

                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                await cursor.execute(query, params)
                rows = await cursor.fetchall()

                for row in rows:
                    checkpoint = self.serde.loads(row["checkpoint"])
                    metadata = self.serde.loads(row["metadata"]) if row["metadata"] else {}

                    yield CheckpointTuple(
                        config={
                            "configurable": {
                                "thread_id": row["thread_id"],
                                "checkpoint_ns": row["checkpoint_ns"],
                                "checkpoint_id": row["checkpoint_id"],
                            }
                        },
                        checkpoint=checkpoint,
                        metadata=metadata,
                        parent_config={
                            "configurable": {
                                "thread_id": row["thread_id"],
                                "checkpoint_ns": row["checkpoint_ns"],
                                "checkpoint_id": row["parent_checkpoint_id"],
                            }
                        } if row["parent_checkpoint_id"] else None,
                    )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict] = None,
    ) -> RunnableConfig:
        """Save a checkpoint to the database."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        # Serialize checkpoint and metadata
        checkpoint_bytes = self.serde.dumps(checkpoint)
        metadata_bytes = self.serde.dumps(metadata)

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        parent_checkpoint_id = VALUES(parent_checkpoint_id),
                        type = VALUES(type),
                        checkpoint = VALUES(checkpoint),
                        metadata = VALUES(metadata)
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        parent_checkpoint_id,
                        "checkpoint",
                        checkpoint_bytes,
                        metadata_bytes,
                    ),
                )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Save pending writes to the database."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for idx, (channel, value) in enumerate(writes):
                    value_bytes = self.serde.dumps(value) if value is not None else None
                    await cursor.execute(
                        """
                        INSERT INTO checkpoint_writes
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            channel = VALUES(channel),
                            type = VALUES(type),
                            value = VALUES(value)
                        """,
                        (
                            thread_id,
                            checkpoint_ns,
                            checkpoint_id,
                            task_id,
                            idx,
                            channel,
                            type(value).__name__ if value is not None else None,
                            value_bytes,
                        ),
                    )
