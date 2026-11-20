"""The profession directory: the nine embeds, and the messages holding them."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import aiosqlite
import discord
import pytest

from bot.directory import (
    NEVER_SYNCED,
    NOBODY,
    directory_embed,
    directory_key,
    publish_directory,
    refresh_directory,
)
from config import ProfessionCatalog, ProfessionDefinition
from db import MessageRepo, ProfessionRepo
from domain import CharacterProfession, DirectoryRow, RosterCharacter, SyncReport
from tests.fakes import FakeChannel, as_channel

if TYPE_CHECKING:
    from bot.client import GuildBot

NO_WAIT = 0.0

TAILORING = ProfessionDefinition(
    key="tailoring", blizzard_id=197, name="Couture", emoji="\U0001f9f5"
)
SYNCED_AT = datetime(2026, 11, 20, 4, 3, 0, tzinfo=UTC)
REPORT = SyncReport(SYNCED_AT, SYNCED_AT, 25, 0, 48, 1123, 499, ())


class StubBot:
    """The three things the directory asks of the bot, and nothing else."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        catalog: ProfessionCatalog,
        channels: dict[int, FakeChannel] | None = None,
    ) -> None:
        self.db = connection
        self.professions = catalog
        self._channels = channels or {}

    def text_channel(self, channel_id: int) -> discord.TextChannel | None:
        found = self._channels.get(channel_id)
        return as_channel(found) if found is not None else None


def _bot(
    connection: aiosqlite.Connection,
    catalog: ProfessionCatalog,
    channels: dict[int, FakeChannel] | None = None,
) -> "GuildBot":
    """Hand the stub to code typed for the real bot, the way tests/fakes.py does."""
    return cast("GuildBot", StubBot(connection, catalog, channels))


# --- the embed ------------------------------------------------------------------------


def test_the_title_carries_the_emoji_and_the_french_name() -> None:
    embed = directory_embed(TAILORING, [], REPORT)

    assert embed.title == "\U0001f9f5 Couture"


def test_artisans_are_listed_with_their_skill() -> None:
    rows = [DirectoryRow("Mhas-Lananas", 258, 300), DirectoryRow("Rka-Kamechki", 245, 300)]

    embed = directory_embed(TAILORING, rows, REPORT)

    assert embed.description is not None
    assert "`258/300`  Mhas-Lananas" in embed.description
    assert embed.description.index("Mhas") < embed.description.index("Rka")


def test_the_skill_column_is_padded_so_the_numbers_line_up() -> None:
    """A two-digit skill must not shift the name left of the one above it."""
    rows = [DirectoryRow("Haut", 300, 300), DirectoryRow("Bas", 42, 75)]

    embed = directory_embed(TAILORING, rows, REPORT)

    assert embed.description is not None
    first, second = embed.description.splitlines()
    assert first.index("Haut") == second.index("Bas")


def test_the_tier_cap_is_shown_rather_than_always_300() -> None:
    """Someone who has not bought the next rank is capped at 75, 150 or 225."""
    embed = directory_embed(TAILORING, [DirectoryRow("Kiyoshi-Khan", 207, 225)], REPORT)

    assert embed.description is not None
    assert "207/225" in embed.description


def test_a_profession_nobody_has_says_so_rather_than_being_hidden() -> None:
    """The nine messages must not change place from one day to the next."""
    embed = directory_embed(TAILORING, [], REPORT)

    assert embed.description == NOBODY
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("0 artisan(s)")


def test_an_empty_profession_is_greyed_out() -> None:
    assert (
        directory_embed(TAILORING, [], REPORT).colour
        != directory_embed(TAILORING, [DirectoryRow("Quelquun", 1, 75)], REPORT).colour
    )


def test_the_footer_counts_the_artisans_and_dates_the_sync() -> None:
    rows = [DirectoryRow("A", 1, 75), DirectoryRow("B", 2, 75)]

    embed = directory_embed(TAILORING, rows, REPORT)

    assert embed.footer.text is not None
    assert embed.footer.text.startswith("2 artisan(s) · mis à jour le 20/11/2026")


def test_the_footer_shows_the_guild_timezone_not_utc() -> None:
    """04:03 UTC on 20 November is 05:03 in Paris, which is what a member should read."""
    embed = directory_embed(TAILORING, [], REPORT)

    assert embed.footer.text is not None
    assert "05h03" in embed.footer.text


def test_the_footer_says_when_no_sync_has_run() -> None:
    embed = directory_embed(TAILORING, [], None)

    assert embed.footer.text is not None
    assert embed.footer.text.endswith(NEVER_SYNCED)


def test_a_name_with_markdown_in_it_is_escaped() -> None:
    """An asterisk in a character name would otherwise italicise the rest of the column."""
    embed = directory_embed(TAILORING, [DirectoryRow("Gros*minet", 1, 75)], REPORT)

    assert embed.description is not None
    assert "Gros\\*minet" in embed.description


def test_a_roster_too_long_for_one_embed_is_trimmed_and_says_so() -> None:
    rows = [DirectoryRow(f"Personnage{index:04d}", 300, 300) for index in range(300)]

    embed = directory_embed(TAILORING, rows, REPORT)

    assert embed.description is not None
    assert len(embed.description) <= 4096
    assert "de plus" in embed.description
    assert embed.footer.text is not None
    assert "non affiché(s)" in embed.footer.text


def test_the_managed_message_key_is_prefixed_per_profession() -> None:
    assert directory_key("tailoring") == "prof:tailoring"
    assert directory_key("alchemy") != directory_key("tailoring")


# --- posting and refreshing -----------------------------------------------------------


@pytest.fixture
async def seeded(
    professions: ProfessionRepo,
) -> None:
    """One tailor, so at least one message has a line in it."""
    await professions.replace_roster(
        [RosterCharacter("rka-kamechki", "Rka", "Kamechki", 60, 1, 5, 3)]
    )
    await professions.replace_character_professions(
        "rka-kamechki",
        [CharacterProfession("rka-kamechki", 197, "Tailoring", 245, 300)],
        [],
    )


async def test_publishing_posts_one_message_per_tracked_profession(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    seeded: None,
) -> None:
    channel = FakeChannel()

    posted, edited = await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )

    assert (posted, edited) == (9, 0)
    assert len(channel.sent) == 9


async def test_the_ignored_professions_get_no_message(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """Cooking, first aid and fishing are not tracked, so the directory is nine not twelve."""
    channel = FakeChannel()

    await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )

    titles = [embed.title for _, embed in channel.sent]
    assert len(titles) == 9
    assert not any(title is not None and "Cuisine" in title for title in titles)


async def test_publishing_twice_edits_rather_than_reposting(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """Re-running /classes leaves stale boards behind; the directory must not."""
    channel = FakeChannel()
    bot = _bot(connection, professions_catalog)
    await publish_directory(bot, as_channel(channel), delay=NO_WAIT)

    posted, edited = await publish_directory(bot, as_channel(channel), delay=NO_WAIT)

    assert (posted, edited) == (0, 9)
    assert len(channel.sent) == 9


async def test_a_deleted_message_is_posted_again(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    channel = FakeChannel()
    bot = _bot(connection, professions_catalog)
    await publish_directory(bot, as_channel(channel), delay=NO_WAIT)
    channel.deleted = {channel.sent[0][0]}

    posted, edited = await publish_directory(bot, as_channel(channel), delay=NO_WAIT)

    assert (posted, edited) == (1, 8)
    assert len(channel.sent) == 10


async def test_moving_the_channel_reposts_rather_than_editing_elsewhere(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """PROFESSIONS_CHANNEL_ID changed: the nine messages belong in the new channel."""
    bot = _bot(connection, professions_catalog)
    await publish_directory(bot, as_channel(FakeChannel(500)), delay=NO_WAIT)
    moved = FakeChannel(600)

    posted, edited = await publish_directory(bot, as_channel(moved), delay=NO_WAIT)

    assert (posted, edited) == (9, 0)


async def test_the_messages_are_remembered_so_a_restart_finds_them(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    channel = FakeChannel()

    await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )

    keys = await MessageRepo(connection).keys_starting_with("prof:")
    assert len(keys) == 9


async def test_refreshing_edits_every_posted_message(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    channel = FakeChannel()
    bot = _bot(connection, professions_catalog)
    await publish_directory(bot, as_channel(channel), delay=NO_WAIT)
    bot = _bot(connection, professions_catalog, {channel.id: channel})

    assert await refresh_directory(bot, delay=NO_WAIT) == 9
    assert len(channel.edited) == 9


async def test_refreshing_before_anything_was_posted_does_nothing(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """The daily sync runs whether or not an officer ever ran /annuaire-métiers."""
    bot = _bot(connection, professions_catalog, {})

    assert await refresh_directory(bot, delay=NO_WAIT) == 0


async def test_refreshing_forgets_a_message_someone_deleted(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """Forgotten rather than retried for ever, so /annuaire-métiers posts it again."""
    channel = FakeChannel()
    await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )
    channel.deleted = {channel.sent[0][0]}
    bot = _bot(connection, professions_catalog, {channel.id: channel})

    assert await refresh_directory(bot, delay=NO_WAIT) == 8
    assert len(await MessageRepo(connection).keys_starting_with("prof:")) == 8


async def test_refreshing_forgets_a_message_whose_channel_is_gone(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    channel = FakeChannel()
    await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )
    bot = _bot(connection, professions_catalog, {})

    assert await refresh_directory(bot, delay=NO_WAIT) == 0
    assert await MessageRepo(connection).keys_starting_with("prof:") == []


async def test_a_refresh_shows_the_latest_sync(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    channel = FakeChannel()
    await publish_directory(
        _bot(connection, professions_catalog), as_channel(channel), delay=NO_WAIT
    )
    await professions.record_sync(REPORT)
    bot = _bot(connection, professions_catalog, {channel.id: channel})

    await refresh_directory(bot, delay=NO_WAIT)

    footers = [embed.footer.text for _, embed in channel.edited]
    assert all(footer is not None and "20/11/2026" in footer for footer in footers)
