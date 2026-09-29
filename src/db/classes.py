"""Ranked class choices, class roles and managed messages. All their SQL lives here."""

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import FIRST_CHOICE, ClassRole, ManagedMessage, MemberChoice


def _to_choice(row: aiosqlite.Row) -> MemberChoice:
    """Build a ranked choice from a database row."""
    return MemberChoice(
        member_id=row["member_id"],
        rank=row["rank"],
        class_key=row["class_key"],
        role_key=row["role_key"],
        created_at=from_iso(row["created_at"]),
    )


def _to_class_role(row: aiosqlite.Row) -> ClassRole:
    """Build a class-to-Discord-role link from a database row."""
    return ClassRole(
        class_key=row["class_key"],
        role_id=row["role_id"],
        created_at=from_iso(row["created_at"]),
    )


def _to_managed_message(row: aiosqlite.Row) -> ManagedMessage:
    """Build a managed message from a database row."""
    return ManagedMessage(
        key=row["key"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        updated_at=from_iso(row["updated_at"]),
    )


class ClassRepo:
    """Read and write ranked choices, class roles and the messages showing them."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    # --- ranked choices ---------------------------------------------------------------

    async def append_choice(
        self,
        member_id: int,
        class_key: str,
        role_key: str,
        max_choices: int,
    ) -> MemberChoice | None:
        """Add a choice at the next free rank.

        Returns None when the member already used every rank, so the caller can tell them
        to start over rather than silently dropping the choice. Re-picking a pair they
        already declared moves nothing and returns the existing entry.
        """
        await self._db.execute("BEGIN")
        try:
            async with self._db.execute(
                "SELECT * FROM member_choices WHERE member_id = ? AND class_key = ? "
                "AND role_key = ?",
                (member_id, class_key, role_key),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is not None:
                await self._db.commit()
                return _to_choice(existing)

            async with self._db.execute(
                "SELECT COUNT(*) AS taken FROM member_choices WHERE member_id = ?",
                (member_id,),
            ) as cursor:
                count_row = await cursor.fetchone()

            taken = count_row["taken"] if count_row is not None else 0
            if taken >= max_choices:
                await self._db.commit()
                return None

            async with self._db.execute(
                """
                INSERT INTO member_choices (member_id, rank, class_key, role_key, created_at)
                VALUES (?, ?, ?, ?, ?)
                RETURNING *
                """,
                (member_id, taken + 1, class_key, role_key, to_iso(utcnow())),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:  # pragma: no cover -- RETURNING always yields a row on success
                raise RuntimeError(f"Choice of member {member_id} returned no row")
        except Exception:
            await self._db.rollback()
            raise

        await self._db.commit()
        return _to_choice(row)

    async def clear_choices(self, member_id: int) -> int:
        """Drop every choice of a member. Returns how many were removed."""
        cursor = await self._db.execute(
            "DELETE FROM member_choices WHERE member_id = ?",
            (member_id,),
        )
        await self._db.commit()
        return cursor.rowcount

    async def choices_of(self, member_id: int) -> list[MemberChoice]:
        """One member's choices, best first."""
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? ORDER BY rank",
            (member_id,),
        ) as cursor:
            return [_to_choice(row) for row in await cursor.fetchall()]

    async def first_choice_of(self, member_id: int) -> MemberChoice | None:
        """The member's main character, if they declared one."""
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? AND rank = ?",
            (member_id, FIRST_CHOICE),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_choice(row) if row is not None else None

    async def all_choices(self) -> list[MemberChoice]:
        """Every choice declared in the guild, grouped by member and ordered by rank."""
        async with self._db.execute(
            "SELECT * FROM member_choices ORDER BY member_id, rank"
        ) as cursor:
            return [_to_choice(row) for row in await cursor.fetchall()]

    async def directory(self) -> list[tuple[str, list[MemberChoice]]]:
        """Every member who declared something, with their choices, by display name."""
        async with self._db.execute(
            """
            SELECT m.display_name, c.*
            FROM member_choices AS c
            JOIN members AS m ON m.discord_id = c.member_id
            ORDER BY m.display_name COLLATE NOCASE, c.rank
            """
        ) as cursor:
            rows = await cursor.fetchall()

        grouped: dict[int, tuple[str, list[MemberChoice]]] = {}
        for row in rows:
            entry = grouped.setdefault(row["member_id"], (row["display_name"], []))
            entry[1].append(_to_choice(row))
        return list(grouped.values())

    # --- Discord roles ----------------------------------------------------------------

    async def link_role(self, class_key: str, role_id: int) -> ClassRole:
        """Remember which Discord role stands for a class."""
        async with self._db.execute(
            """
            INSERT INTO class_roles (class_key, role_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT (class_key) DO UPDATE SET role_id = excluded.role_id
            RETURNING *
            """,
            (class_key, role_id, to_iso(utcnow())),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:  # pragma: no cover -- RETURNING always yields a row on success
            raise RuntimeError(f"Link of class {class_key!r} returned no row")

        await self._db.commit()
        return _to_class_role(row)

    async def unlink_role(self, class_key: str) -> bool:
        """Forget a class role, after it was deleted on Discord."""
        cursor = await self._db.execute(
            "DELETE FROM class_roles WHERE class_key = ?",
            (class_key,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def role_ids(self) -> dict[str, int]:
        """Every class-to-role link, keyed by class."""
        async with self._db.execute("SELECT * FROM class_roles") as cursor:
            return {row["class_key"]: row["role_id"] for row in await cursor.fetchall()}

    # --- managed messages -------------------------------------------------------------

    async def remember_message(self, key: str, channel_id: int, message_id: int) -> None:
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

    async def managed_message(self, key: str) -> ManagedMessage | None:
        """Look up a managed message."""
        async with self._db.execute(
            "SELECT * FROM managed_messages WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_managed_message(row) if row is not None else None

    async def forget_message(self, key: str) -> bool:
        """Drop a managed message, after it was deleted on Discord."""
        cursor = await self._db.execute("DELETE FROM managed_messages WHERE key = ?", (key,))
        await self._db.commit()
        return cursor.rowcount > 0
