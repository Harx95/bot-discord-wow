"""Database connection handling."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


async def connect(path: Path) -> aiosqlite.Connection:
    """Open a connection with the pragmas the schema relies on.

    foreign_keys is off by default in SQLite and is a per-connection setting, so the
    composite key on poll_votes only protects anything if it is enabled here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = await aiosqlite.connect(path)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("PRAGMA journal_mode = WAL")
    return connection


@asynccontextmanager
async def open_database(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open a connection and close it when the block exits."""
    connection = await connect(path)
    try:
        yield connection
    finally:
        await connection.close()
