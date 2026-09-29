"""Poll persistence. All SQL touching polls, options and votes lives here."""

from collections.abc import Sequence

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import OptionTally, Poll, PollOption, PollStatus, PollVote


def _to_poll(row: aiosqlite.Row) -> Poll:
    """Build a poll from a database row."""
    closed_at = row["closed_at"]
    return Poll(
        id=row["id"],
        key=row["key"],
        title=row["title"],
        status=PollStatus(row["status"]),
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        created_at=from_iso(row["created_at"]),
        closed_at=from_iso(closed_at) if closed_at is not None else None,
    )


def _to_option(row: aiosqlite.Row) -> PollOption:
    """Build a poll option from a database row."""
    return PollOption(
        id=row["id"],
        poll_id=row["poll_id"],
        key=row["key"],
        label=row["label"],
        position=row["position"],
        created_by=row["created_by"],
        created_at=from_iso(row["created_at"]),
    )


def _to_vote(row: aiosqlite.Row) -> PollVote:
    """Build a vote from a database row."""
    return PollVote(
        poll_id=row["poll_id"],
        member_id=row["member_id"],
        option_id=row["option_id"],
        voted_at=from_iso(row["voted_at"]),
    )


class PollRepo:
    """Read and write polls, their options and their votes."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    async def create(self, key: str, title: str, options: Sequence[tuple[str, str]] = ()) -> Poll:
        """Create a poll and its initial options, as one transaction.

        Options are given as (key, label) pairs and keep the order they are passed in.
        Raises aiosqlite.IntegrityError if the poll key already exists.
        """
        now = to_iso(utcnow())

        await self._db.execute("BEGIN")
        try:
            async with self._db.execute(
                "INSERT INTO polls (key, title, created_at) VALUES (?, ?, ?) RETURNING *",
                (key, title, now),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:  # pragma: no cover -- RETURNING always yields a row on success
                raise RuntimeError(f"Creation of poll {key!r} returned no row")

            poll = _to_poll(row)
            for position, (option_key, label) in enumerate(options):
                await self._db.execute(
                    """
                    INSERT INTO poll_options (poll_id, key, label, position, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (poll.id, option_key, label, position, now),
                )
        except Exception:
            await self._db.rollback()
            raise

        await self._db.commit()
        return poll

    async def get_by_key(self, key: str) -> Poll | None:
        """Fetch one poll by its configuration key."""
        async with self._db.execute("SELECT * FROM polls WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()

        return _to_poll(row) if row is not None else None

    async def list_open(self) -> list[Poll]:
        """Every poll still accepting votes, oldest first."""
        async with self._db.execute(
            "SELECT * FROM polls WHERE status = ? ORDER BY created_at",
            (PollStatus.OPEN.value,),
        ) as cursor:
            return [_to_poll(row) for row in await cursor.fetchall()]

    async def options(self, poll_id: int) -> list[PollOption]:
        """Options of a poll, in display order."""
        async with self._db.execute(
            "SELECT * FROM poll_options WHERE poll_id = ? ORDER BY position",
            (poll_id,),
        ) as cursor:
            return [_to_option(row) for row in await cursor.fetchall()]

    async def add_option(
        self,
        poll_id: int,
        key: str,
        label: str,
        created_by: int | None = None,
    ) -> PollOption:
        """Append an option at the end of the poll.

        created_by identifies the member who proposed it, or None for a configured option.
        """
        await self._db.execute("BEGIN")
        try:
            async with self._db.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) AS next FROM poll_options WHERE poll_id = ?",
                (poll_id,),
            ) as cursor:
                position_row = await cursor.fetchone()

            position = position_row["next"] if position_row is not None else 0
            async with self._db.execute(
                """
                INSERT INTO poll_options (poll_id, key, label, position, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING *
                """,
                (poll_id, key, label, position, created_by, to_iso(utcnow())),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:  # pragma: no cover -- RETURNING always yields a row on success
                raise RuntimeError(f"Insertion of option {key!r} returned no row")
        except Exception:
            await self._db.rollback()
            raise

        await self._db.commit()
        return _to_option(row)

    async def attach_message(self, poll_id: int, channel_id: int, message_id: int) -> None:
        """Remember which message displays the poll, so it can be edited later."""
        await self._db.execute(
            "UPDATE polls SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, poll_id),
        )
        await self._db.commit()

    async def close(self, key: str) -> Poll | None:
        """Close a poll. Returns None if it does not exist or was already closed."""
        async with self._db.execute(
            """
            UPDATE polls SET status = ?, closed_at = ?
            WHERE key = ? AND status = ?
            RETURNING *
            """,
            (PollStatus.CLOSED.value, to_iso(utcnow()), key, PollStatus.OPEN.value),
        ) as cursor:
            row = await cursor.fetchone()

        await self._db.commit()
        return _to_poll(row) if row is not None else None

    async def cast_vote(self, poll_id: int, member_id: int, option_id: int) -> PollVote:
        """Record a vote, replacing the member's previous choice on this poll.

        The primary key on (poll_id, member_id) makes one-vote-per-person a schema guarantee,
        so changing your mind is an upsert rather than a delete plus an insert.
        """
        async with self._db.execute(
            """
            INSERT INTO poll_votes (poll_id, member_id, option_id, voted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (poll_id, member_id) DO UPDATE SET
                option_id = excluded.option_id,
                voted_at = excluded.voted_at
            RETURNING *
            """,
            (poll_id, member_id, option_id, to_iso(utcnow())),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:  # pragma: no cover -- RETURNING always yields a row on success
            raise RuntimeError(f"Vote of member {member_id} returned no row")

        await self._db.commit()
        return _to_vote(row)

    async def vote_of(self, poll_id: int, member_id: int) -> PollVote | None:
        """The member's current choice on this poll, if they voted."""
        async with self._db.execute(
            "SELECT * FROM poll_votes WHERE poll_id = ? AND member_id = ?",
            (poll_id, member_id),
        ) as cursor:
            row = await cursor.fetchone()

        return _to_vote(row) if row is not None else None

    async def results(self, poll_id: int) -> list[OptionTally]:
        """Vote count per option, in display order, including options nobody picked."""
        async with self._db.execute(
            """
            SELECT o.*, COUNT(v.member_id) AS votes
            FROM poll_options AS o
            LEFT JOIN poll_votes AS v ON v.option_id = o.id
            WHERE o.poll_id = ?
            GROUP BY o.id
            ORDER BY o.position
            """,
            (poll_id,),
        ) as cursor:
            return [
                OptionTally(option=_to_option(row), votes=row["votes"])
                for row in await cursor.fetchall()
            ]
