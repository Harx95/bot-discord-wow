"""Migration runner behaviour."""

from pathlib import Path

import aiosqlite
import pytest

from db import apply_migrations, connect
from db.migrations import MIGRATIONS_DIR, split_statements

# Derived from the directory so adding a migration does not require editing these tests.
ALL_VERSIONS = sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))


async def _table_names(connection: aiosqlite.Connection) -> set[str]:
    """Names of the tables present in the database."""
    async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        return {row["name"] for row in await cursor.fetchall()}


async def test_creates_the_expected_tables(connection: aiosqlite.Connection) -> None:
    names = await _table_names(connection)
    assert {"members", "polls", "poll_options", "poll_votes"} <= names


async def test_records_the_applied_version(connection: aiosqlite.Connection) -> None:
    async with connection.execute("SELECT version FROM schema_migrations") as cursor:
        versions = [row["version"] for row in await cursor.fetchall()]

    assert sorted(versions) == ALL_VERSIONS


async def test_second_run_applies_nothing(connection: aiosqlite.Connection) -> None:
    """This is the guarantee that restarting the bot does not replay migrations."""
    assert await apply_migrations(connection) == []


async def test_reopening_the_file_applies_nothing(tmp_path: Path) -> None:
    """Same guarantee, across a real restart rather than a reused connection."""
    path = tmp_path / "restart.db"

    first = await connect(path)
    assert await apply_migrations(first) == ALL_VERSIONS
    await first.close()

    second = await connect(path)
    assert await apply_migrations(second) == []
    await second.close()


async def test_foreign_keys_are_enforced(connection: aiosqlite.Connection) -> None:
    """The pragma is per-connection, so its absence would silently disable every FK."""
    with pytest.raises(aiosqlite.IntegrityError):
        await connection.execute(
            "INSERT INTO poll_options (poll_id, key, label, position, created_at)"
            " VALUES (999, 'x', 'X', 0, '2026-01-01T00:00:00+00:00')"
        )


def test_split_statements_ignores_semicolons_in_comments_and_strings() -> None:
    script = """
    -- a comment; with a semicolon
    CREATE TABLE t (a TEXT);
    INSERT INTO t (a) VALUES ('a; b');
    """
    statements = split_statements(script)

    assert len(statements) == 2
    assert statements[1].endswith("VALUES ('a; b');")


def test_split_statements_rejects_an_unterminated_statement() -> None:
    with pytest.raises(ValueError, match="Unterminated"):
        split_statements("CREATE TABLE t (a TEXT)")


async def test_003_carries_existing_votes_over_and_lifts_the_one_vote_rule(
    tmp_path: Path,
) -> None:
    """The upgrade path with data in it, which a fresh database never exercises.

    A vote recorded under the old PRIMARY KEY (poll_id, member_id) must survive the rebuild,
    and backing a second option must become possible afterwards.
    """
    path = tmp_path / "upgrade.db"
    earlier = [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.stem < "003"]

    connection = await connect(path)
    try:
        # The state the database was in before this migration existed: the earlier ones
        # applied and recorded, so the runner only has 003 left to do.
        await connection.executescript(
            "CREATE TABLE schema_migrations (version TEXT NOT NULL PRIMARY KEY, "
            "applied_at TEXT NOT NULL) STRICT"
        )
        for migration in earlier:
            await connection.executescript(migration.read_text(encoding="utf-8"))
            await connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (migration.stem, "2026-09-01T00:00:00+00:00"),
            )
        await connection.executescript(
            """
            INSERT INTO members (discord_id, display_name, first_seen_at, last_seen_at)
            VALUES (1, 'Kaeldin', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00');
            INSERT INTO polls (id, key, title, created_at)
            VALUES (1, 'faction', 'Quelle faction ?', '2026-09-01T00:00:00+00:00');
            INSERT INTO poll_options (id, poll_id, key, label, position, created_at)
            VALUES (1, 1, 'alliance', 'Alliance', 0, '2026-09-01T00:00:00+00:00'),
                   (2, 1, 'horde', 'Horde', 1, '2026-09-01T00:00:00+00:00');
            INSERT INTO poll_votes (poll_id, member_id, option_id, voted_at)
            VALUES (1, 1, 1, '2026-09-01T00:00:00+00:00');
            """
        )
        await connection.commit()

        applied = await apply_migrations(connection)
        assert "003_multiple_votes" in applied

        # The vote cast before the rebuild is still there.
        async with connection.execute("SELECT option_id FROM poll_votes") as cursor:
            assert [row["option_id"] for row in await cursor.fetchall()] == [1]

        # And the member can now back the other option as well.
        await connection.execute(
            "INSERT INTO poll_votes (poll_id, member_id, option_id, voted_at) VALUES (?,?,?,?)",
            (1, 1, 2, "2026-09-02T00:00:00+00:00"),
        )
        await connection.commit()

        async with connection.execute("SELECT COUNT(*) AS n FROM poll_votes") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row["n"] == 2
    finally:
        await connection.close()


async def test_a_member_cannot_back_the_same_option_twice(
    connection: aiosqlite.Connection,
) -> None:
    """The rebuilt primary key still stops a reaction event from being counted twice."""
    await connection.executescript(
        """
        INSERT INTO members (discord_id, display_name, first_seen_at, last_seen_at)
        VALUES (1, 'Kaeldin', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00');
        INSERT INTO polls (id, key, title, created_at)
        VALUES (1, 'faction', 'Quelle faction ?', '2026-09-01T00:00:00+00:00');
        INSERT INTO poll_options (id, poll_id, key, label, position, created_at)
        VALUES (1, 1, 'alliance', 'Alliance', 0, '2026-09-01T00:00:00+00:00');
        INSERT INTO poll_votes (poll_id, member_id, option_id, voted_at)
        VALUES (1, 1, 1, '2026-09-01T00:00:00+00:00');
        """
    )
    await connection.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await connection.execute(
            "INSERT INTO poll_votes (poll_id, member_id, option_id, voted_at) VALUES (?,?,?,?)",
            (1, 1, 1, "2026-09-02T00:00:00+00:00"),
        )
