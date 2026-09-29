"""Versioned SQL migrations.

Each file in the migrations directory is applied once, in filename order, and its name is
recorded. Restarting the bot therefore replays nothing.
"""

import logging
import sqlite3
from pathlib import Path

import aiosqlite

from db.timestamps import to_iso, utcnow

_log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_CREATE_REGISTRY = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT NOT NULL PRIMARY KEY,
    applied_at TEXT NOT NULL
) STRICT
"""


def split_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements.

    executescript() would be shorter, but it commits any pending transaction before running,
    so the DDL and the version record could not be written atomically. sqlite3.complete_statement
    is the same parser SQLite uses, so semicolons inside comments or string literals are safe.
    """
    statements: list[str] = []
    buffer = ""

    for line in script.splitlines(keepends=True):
        buffer += line
        if not sqlite3.complete_statement(buffer):
            continue
        statement = buffer.strip()
        buffer = ""
        if statement:
            statements.append(statement)

    trailing = buffer.strip()
    if trailing and not trailing.startswith("--"):
        raise ValueError(f"Unterminated SQL statement: {trailing[:60]!r}")

    return statements


async def _applied_versions(connection: aiosqlite.Connection) -> set[str]:
    """Versions already recorded in the database."""
    async with connection.execute("SELECT version FROM schema_migrations") as cursor:
        return {row["version"] for row in await cursor.fetchall()}


async def _apply(connection: aiosqlite.Connection, path: Path) -> None:
    """Apply one migration and record it, all or nothing."""
    statements = split_statements(path.read_text(encoding="utf-8"))

    await connection.execute("BEGIN")
    try:
        for statement in statements:
            await connection.execute(statement)
        await connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (path.stem, to_iso(utcnow())),
        )
    except Exception:
        await connection.rollback()
        raise
    await connection.commit()


async def apply_migrations(
    connection: aiosqlite.Connection,
    directory: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Apply every migration that is missing and return the versions applied."""
    await connection.execute(_CREATE_REGISTRY)
    await connection.commit()

    applied = await _applied_versions(connection)
    pending = [path for path in sorted(directory.glob("*.sql")) if path.stem not in applied]

    for path in pending:
        _log.info("Applying migration %s", path.stem)
        await _apply(connection, path)

    if not pending:
        _log.info("Schema up to date (%d migration(s) applied)", len(applied))

    return [path.stem for path in pending]
