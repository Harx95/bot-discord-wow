"""The messages the bot keeps up to date, whatever they show.

Extracted from ClassRepo once the profession directory needed the same table: the key names
the purpose, so the class boards and the twelve directory messages share one store without
sharing any SQL. migrations/002_classes.sql already said the table was meant for this.
"""

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import ManagedMessage


def _to_managed_message(row: aiosqlite.Row) -> ManagedMessage:
    """Build a managed message from a database row."""
    return ManagedMessage(
        key=row["key"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        updated_at=from_iso(row["updated_at"]),
    )


class MessageRepo:
    """Which message the bot edits for a given purpose."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    async def remember(self, key: str, channel_id: int, message_id: int) -> None:
        """Record which message the bot keeps up to date for a given purpose."""
        await self._db.execute(
            """
            INSERT INTO managed_messages (key, channel_id, message_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id,
                updated_at = excluded.updated_at
            """,
            (key, channel_id, message_id, to_iso(utcnow())),
        )
        await self._db.commit()

    async def get(self, key: str) -> ManagedMessage | None:
        """Look up a managed message."""
        async with self._db.execute(
            "SELECT * FROM managed_messages WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_managed_message(row) if row is not None else None

    async def forget(self, key: str) -> bool:
        """Drop a managed message, after it was deleted on Discord."""
        cursor = await self._db.execute("DELETE FROM managed_messages WHERE key = ?", (key,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def keys_starting_with(self, prefix: str) -> list[str]:
        """Every remembered key under one prefix, so a family of messages can be swept."""
        async with self._db.execute(
            "SELECT key FROM managed_messages WHERE key LIKE ? || '%' ORDER BY key",
            (prefix,),
        ) as cursor:
            return [row["key"] for row in await cursor.fetchall()]
