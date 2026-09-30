"""Ranked class choices, class roles and managed messages. All their SQL lives here."""

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import FIRST_CHOICE, ClassRole, MainUpdate, ManagedMessage, MemberChoice

INSERT_CHOICE = """
INSERT INTO member_choices (member_id, rank, class_key, role_key, created_at)
VALUES (?, ?, ?, ?, ?)
"""


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
    """Read and write ranked choices, class roles and the messages showing them.

    Rank 1 is the main character, the only one earning a Discord role. Ranks 2 and above
    are the alternates, which the second board shows without their rank: removing one
    leaves a hole in the sequence, and that is deliberate.
    """

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    # --- ranked choices ---------------------------------------------------------------

    async def set_main(self, member_id: int, class_key: str, role_key: str) -> MainUpdate:
        """Declare the member's main character, replacing whatever held rank 1.

        A pair already listed as an alternate is promoted rather than duplicated: the
        UNIQUE constraint on (member, class, role) forbids holding it twice.
        """
        await self._db.execute("BEGIN")
        try:
            async with self._db.execute(
                "SELECT * FROM member_choices WHERE member_id = ? AND class_key = ? "
                "AND role_key = ?",
                (member_id, class_key, role_key),
            ) as cursor:
                same_pair = await cursor.fetchone()

            if same_pair is not None and same_pair["rank"] == FIRST_CHOICE:
                await self._db.commit()
                return MainUpdate(
                    choice=_to_choice(same_pair),
                    changed=False,
                    promoted=False,
                    replaced_class_key=None,
                )

            async with self._db.execute(
                "SELECT * FROM member_choices WHERE member_id = ? AND rank = ?",
                (member_id, FIRST_CHOICE),
            ) as cursor:
                previous = await cursor.fetchone()

            promoted = same_pair is not None
            if same_pair is not None:
                # Frees the UNIQUE pair so it can be reinserted at rank 1.
                await self._db.execute(
                    "DELETE FROM member_choices WHERE member_id = ? AND rank = ?",
                    (member_id, same_pair["rank"]),
                )
            if previous is not None:
                await self._db.execute(
                    "DELETE FROM member_choices WHERE member_id = ? AND rank = ?",
                    (member_id, FIRST_CHOICE),
                )

            async with self._db.execute(
                f"{INSERT_CHOICE} RETURNING *",
                (member_id, FIRST_CHOICE, class_key, role_key, to_iso(utcnow())),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:  # pragma: no cover -- RETURNING always yields a row on success
                raise RuntimeError(f"Main of member {member_id} returned no row")
        except Exception:
            await self._db.rollback()
            raise

        await self._db.commit()
        replaced = previous["class_key"] if previous is not None else None
        return MainUpdate(
            choice=_to_choice(row),
            changed=True,
            promoted=promoted,
            replaced_class_key=replaced,
        )

    async def clear_main(self, member_id: int) -> MemberChoice | None:
        """Drop the main character. Returns what was removed, or None if there was none.

        Clicking the class that is already the main is how a member takes it back, so this
        is the only way a declared character leaves rank 1 without another taking its place.
        """
        async with self._db.execute(
            "DELETE FROM member_choices WHERE member_id = ? AND rank = ? RETURNING *",
            (member_id, FIRST_CHOICE),
        ) as cursor:
            row = await cursor.fetchone()

        await self._db.commit()
        return _to_choice(row) if row is not None else None

    async def main_of(self, member_id: int) -> MemberChoice | None:
        """The member's main character, if they declared one."""
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? AND rank = ?",
            (member_id, FIRST_CHOICE),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_choice(row) if row is not None else None

    async def alternates_of(self, member_id: int) -> list[MemberChoice]:
        """Every class the member listed besides their main character."""
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? AND rank > ? ORDER BY rank",
            (member_id, FIRST_CHOICE),
        ) as cursor:
            return [_to_choice(row) for row in await cursor.fetchall()]

    async def alternate_of(self, member_id: int, class_key: str) -> MemberChoice | None:
        """That class among the member's alternates, whatever role it was declared for.

        Matching on the class alone, not on the class and role: a member clicking a button
        names a class, and the button cannot say which role they had picked behind it.
        """
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? AND rank > ? AND class_key = ? "
            "ORDER BY rank",
            (member_id, FIRST_CHOICE, class_key),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_choice(row) if row is not None else None

    async def remove_alternate(self, member_id: int, class_key: str) -> MemberChoice | None:
        """Drop that class from the member's alternates. Returns what was removed."""
        async with self._db.execute(
            "DELETE FROM member_choices WHERE member_id = ? AND rank > ? AND class_key = ? "
            "RETURNING *",
            (member_id, FIRST_CHOICE, class_key),
        ) as cursor:
            row = await cursor.fetchone()

        await self._db.commit()
        return _to_choice(row) if row is not None else None

    async def add_alternate(
        self,
        member_id: int,
        class_key: str,
        role_key: str,
        max_choices: int,
    ) -> MemberChoice | None:
        """Add an alternate at the lowest free rank. Returns None when every rank is taken.

        Removing an alternate leaves a hole in the ranks, which this fills: the ranks of
        alternates carry no meaning, only the fact of being above the main character's.
        """
        await self._db.execute("BEGIN")
        try:
            async with self._db.execute(
                "SELECT rank FROM member_choices WHERE member_id = ? AND rank > ?",
                (member_id, FIRST_CHOICE),
            ) as cursor:
                taken = {row["rank"] for row in await cursor.fetchall()}

            free = next(
                (rank for rank in range(FIRST_CHOICE + 1, max_choices + 1) if rank not in taken),
                None,
            )
            if free is None:
                await self._db.commit()
                return None

            async with self._db.execute(
                f"{INSERT_CHOICE} RETURNING *",
                (member_id, free, class_key, role_key, to_iso(utcnow())),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:  # pragma: no cover -- RETURNING always yields a row on success
                raise RuntimeError(f"Alternate of member {member_id} returned no row")
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
        """One member's choices, main first."""
        async with self._db.execute(
            "SELECT * FROM member_choices WHERE member_id = ? ORDER BY rank",
            (member_id,),
        ) as cursor:
            return [_to_choice(row) for row in await cursor.fetchall()]

    async def all_choices(self) -> list[MemberChoice]:
        """Every choice declared in the guild, grouped by member and ordered by rank."""
        async with self._db.execute(
            "SELECT * FROM member_choices ORDER BY member_id, rank"
        ) as cursor:
            return [_to_choice(row) for row in await cursor.fetchall()]

    async def declarations(self) -> list[tuple[str, MemberChoice]]:
        """Every declared character, with the display name of whoever declared it.

        One row per character rather than one per member: the boards lay characters out in
        role columns, so the grouping by member would only have to be undone.
        """
        async with self._db.execute(
            """
            SELECT m.display_name, c.*
            FROM member_choices AS c
            JOIN members AS m ON m.discord_id = c.member_id
            ORDER BY m.display_name COLLATE NOCASE, c.rank
            """
        ) as cursor:
            rows = await cursor.fetchall()

        return [(row["display_name"], _to_choice(row)) for row in rows]

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
