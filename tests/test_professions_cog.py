"""The daily loop's schedule. The first discord.ext.tasks loop in the project.

The commands themselves are not covered here: they are a defer, a permission check and a
followup around publish_directory and sync_professions, which have their own tests.
"""

import asyncio
from datetime import time
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import pytest

from bot.cogs.professions import GUILD_TIMEZONE, Professions

if TYPE_CHECKING:
    from bot.client import GuildBot


class StubBot:
    """Only what cog_load reads."""

    def __init__(self, hour: int) -> None:
        self.settings = cast("object", _StubSettings(hour))


class _StubSettings:
    def __init__(self, hour: int) -> None:
        self.profession_sync_hour = hour


def _cog(hour: int = 5) -> Professions:
    return Professions(cast("GuildBot", StubBot(hour)))


@pytest.fixture
def cog() -> Professions:
    return _cog()


async def test_the_loop_runs_at_the_configured_hour(cog: Professions) -> None:
    await cog.cog_load()
    try:
        assert cog.daily_sync.time == [time(hour=5, tzinfo=GUILD_TIMEZONE)]
    finally:
        await cog.cog_unload()


async def test_the_hour_comes_from_the_settings_not_the_decorator() -> None:
    """The decorator is evaluated at class definition, so it cannot read the settings."""
    cog = _cog(hour=3)

    await cog.cog_load()
    try:
        assert cog.daily_sync.time == [time(hour=3, tzinfo=GUILD_TIMEZONE)]
    finally:
        await cog.cog_unload()


async def test_the_loop_is_scheduled_in_the_guild_timezone_not_utc(cog: Professions) -> None:
    """05:00 Paris, so the sync lands before anyone is awake, summer time included."""
    assert GUILD_TIMEZONE == ZoneInfo("Europe/Paris")

    await cog.cog_load()
    try:
        scheduled = cog.daily_sync.time
        assert scheduled is not None
        assert scheduled[0].tzinfo == ZoneInfo("Europe/Paris")
    finally:
        await cog.cog_unload()


async def test_the_loop_starts_on_load_and_stops_on_unload(cog: Professions) -> None:
    """A reload must not leave two loops syncing the same roster."""
    await cog.cog_load()
    assert cog.daily_sync.is_running()

    await cog.cog_unload()
    # cancel() asks the task to stop; it is only done once the loop has run it.
    await asyncio.sleep(0)

    assert not cog.daily_sync.is_running()
