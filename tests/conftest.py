"""Shared fixtures: a migrated database on a temporary file, one per test."""

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from config import ClassCatalog, PollCatalog, load_catalog, load_classes
from db import ClassRepo, MemberRepo, PollRepo, apply_migrations, connect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_POLLS = PROJECT_ROOT / "polls.toml"
PROJECT_CLASSES = PROJECT_ROOT / "classes.toml"


@pytest.fixture
def catalog() -> PollCatalog:
    """The poll definitions actually shipped with the project."""
    return load_catalog(PROJECT_POLLS)


@pytest.fixture
def classes() -> ClassCatalog:
    """The class definitions actually shipped with the project."""
    return load_classes(PROJECT_CLASSES)


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


@pytest.fixture
def class_repo(connection: aiosqlite.Connection) -> ClassRepo:
    """Class repository bound to the temporary database."""
    return ClassRepo(connection)
