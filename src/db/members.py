"""Member persistence. All SQL touching members lives here."""

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import Member


def row_to_member(row: aiosqlite.Row) -> Member:
    """Build a domain entity from a database row."""
    return Member(
        discord_id=row["discord_id"],
        display_name=row["display_name"],
        first_seen_at=from_iso(row["first_seen_at"]),
        last_seen_at=from_iso(row["last_seen_at"]),
    )


class MemberRepo:
    """Read and write guild members."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    async def upsert(self, discord_id: int, display_name: str) -> Member:
        """Record a member, or refresh the name and last-seen date of a known one.

        first_seen_at is never overwritten: it is the date the member was first recorded.
        """
        now = to_iso(utcnow())
        async with self._db.execute(
            """
            INSERT INTO members (discord_id, display_name, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (discord_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at
            RETURNING *
            """,
            (discord_id, display_name, now, now),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:  # pragma: no cover -- RETURNING always yields a row on success
            raise RuntimeError(f"Upsert of member {discord_id} returned no row")

        await self._db.commit()
        return row_to_member(row)

    async def get(self, discord_id: int) -> Member | None:
        """Fetch one member, or None if unknown."""
        async with self._db.execute(
            "SELECT * FROM members WHERE discord_id = ?",
            (discord_id,),
        ) as cursor:
            row = await cursor.fetchone()

        return row_to_member(row) if row is not None else None

    async def list_all(self) -> list[Member]:
        """Every known member, oldest first. discord_id breaks ties within the same instant."""
        async with self._db.execute(
            "SELECT * FROM members ORDER BY first_seen_at, discord_id"
        ) as cursor:
            return [row_to_member(row) for row in await cursor.fetchall()]
