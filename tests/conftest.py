"""Shared fixtures: a migrated database on a temporary file, one per test."""

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from db import MemberRepo, PollRepo, apply_migrations, connect


@pytest.fixture
async def connection(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """A connection to a fresh, fully migrated database."""
    db = await connect(tmp_path / "test.db")
    await apply_migrations(db)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def members(connection: aiosqlite.Connection) -> MemberRepo:
    """Member repository bound to the temporary database."""
    return MemberRepo(connection)


@pytest.fixture
def polls(connection: aiosqlite.Connection) -> PollRepo:
    """Poll repository bound to the temporary database."""
    return PollRepo(connection)
