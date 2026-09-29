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
