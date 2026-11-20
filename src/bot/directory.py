"""The profession directory: one message per profession, kept up to date in #métiers.

Nine messages rather than one, because a message per profession reads better in a channel
and because the 6000-character ceiling of an embed can then never be reached. They are
posted once and edited afterwards, so the channel keeps the same nine messages in the same
order for ever: their ids live in managed_messages, keyed by profession.
"""

import asyncio
import logging
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord

from bot.rendering import fit_lines
from config import ProfessionDefinition
from db import MessageRepo, ProfessionRepo
from domain import DirectoryRow, SyncReport

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

# managed_messages keys: "prof:alchemy", "prof:tailoring"... one per configured profession.
DIRECTORY_KEY_PREFIX = "prof"

# An embed description is capped at 4096 characters. Well out of reach at 25 characters a
# profession, but the guild is meant to grow.
DESCRIPTION_BUDGET = 3900

# Discord throttles edits at roughly 5 per 5 seconds per channel, and there are nine
# messages to rewrite. discord.py would wait out a 429 on its own; pacing the edits keeps
# the sync predictable and the logs quiet. Overridable so the tests do not wait.
EDIT_DELAY_SECONDS = 1.2

# Times are shown in the guild's own timezone, not UTC: the footer is read by members.
GUILD_TIMEZONE = ZoneInfo("Europe/Paris")

NOBODY = "_Personne pour l'instant._"
NEVER_SYNCED = "Jamais synchronisé."
TRUNCATED = "… et {count} de plus."


def directory_key(profession_key: str) -> str:
    """The managed_messages key of one profession's message."""
    return f"{DIRECTORY_KEY_PREFIX}:{profession_key}"


def _skill(row: DirectoryRow) -> str:
    """A skill as a fixed-width code span, so the numbers line up down the column.

    max_skill is the cap of the tier reached, not always 300: someone who has not bought
    the next rank is capped at 75, 150 or 225, and 212/225 is the honest figure.
    """
    return f"`{row.skill:>3}/{row.max_skill:<3}`"


def _footer(rows: list[DirectoryRow], hidden: int, last_sync: SyncReport | None) -> str:
    """How many artisans the message covers, and when it was last refreshed."""
    count = f"{len(rows)} artisan(s)"
    if hidden:
        count += f" · {hidden} non affiché(s)"
    if last_sync is None:
        return f"{count} · {NEVER_SYNCED}"
    local = last_sync.finished_at.astimezone(GUILD_TIMEZONE)
    return f"{count} · mis à jour le {local:%d/%m/%Y à %Hh%M}"


def directory_embed(
    definition: ProfessionDefinition,
    rows: list[DirectoryRow],
    last_sync: SyncReport | None = None,
) -> discord.Embed:
    """One profession's artisans, most skilled first.

    A profession nobody has is shown empty rather than skipped, so the nine messages never
    change place from one day to the next.
    """
    lines = [f"{_skill(row)}  {discord.utils.escape_markdown(row.character)}" for row in rows]
    shown, hidden = fit_lines(lines, DESCRIPTION_BUDGET)
    description = "\n".join(shown) or NOBODY
    if hidden:
        description += f"\n{TRUNCATED.format(count=hidden)}"

    embed = discord.Embed(
        title=definition.label,
        description=description,
        colour=discord.Colour.blurple() if rows else discord.Colour.greyple(),
    )
    embed.set_footer(text=_footer(rows, hidden, last_sync))
    return embed


async def _edit_or_none(
    channel: discord.TextChannel | discord.Thread,
    message_id: int,
    embed: discord.Embed,
) -> bool:
    """Edit one directory message. False when it is gone and should be forgotten."""
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(embed=embed)
    except discord.NotFound:
        return False
    except discord.HTTPException as error:
        # Logged and swallowed: one unreachable message must not stop the other eight.
        _log.warning("Could not edit directory message %d: %s", message_id, error)
    return True


async def _embeds(bot: "GuildBot") -> list[tuple[ProfessionDefinition, discord.Embed]]:
    """One embed per tracked profession, in the order professions.toml lists them.

    Read in one pass so the nine messages all describe the same sync.
    """
    professions = ProfessionRepo(bot.db)
    last_sync = await professions.last_sync()
    built: list[tuple[ProfessionDefinition, discord.Embed]] = []
    for definition in bot.professions.tracked:
        rows = await professions.directory(definition.blizzard_id)
        built.append((definition, directory_embed(definition, rows, last_sync)))
    return built


async def publish_directory(
    bot: "GuildBot",
    channel: discord.TextChannel | discord.Thread,
    delay: float = EDIT_DELAY_SECONDS,
) -> tuple[int, int]:
    """Make sure every tracked profession has its message in the channel, and is current.

    Returns (posted, edited). A message already remembered is edited rather than reposted,
    so running the command twice does not leave a trail of stale messages behind -- which
    is what re-running /classes does, and the one thing worth not repeating here.
    """
    messages = MessageRepo(bot.db)
    posted = edited = 0

    for index, (definition, embed) in enumerate(await _embeds(bot)):
        if index:
            await asyncio.sleep(delay)

        key = directory_key(definition.key)
        managed = await messages.get(key)
        if managed is not None and managed.channel_id == channel.id:
            if await _edit_or_none(channel, managed.message_id, embed):
                edited += 1
                continue
            _log.info("Directory message %r was deleted; posting a new one", key)
            await messages.forget(key)

        message = await channel.send(embed=embed)
        await messages.remember(key, channel.id, message.id)
        posted += 1

    return posted, edited


async def refresh_directory(bot: "GuildBot", delay: float = EDIT_DELAY_SECONDS) -> int:
    """Rewrite the directory messages that were posted. Returns how many were edited.

    Never raises: this runs at the end of a sync, and a deleted message or a missing
    permission must not turn a good sync into a failed one. A message that is gone is
    forgotten, so the next /annuaire-metiers posts it again.
    """
    messages = MessageRepo(bot.db)
    edited = 0

    for index, (definition, embed) in enumerate(await _embeds(bot)):
        key = directory_key(definition.key)
        managed = await messages.get(key)
        if managed is None:
            continue

        if index:
            await asyncio.sleep(delay)

        channel = bot.text_channel(managed.channel_id)
        if channel is None:
            _log.warning("Channel %d of directory %r is gone", managed.channel_id, key)
            await messages.forget(key)
            continue

        if await _edit_or_none(channel, managed.message_id, embed):
            edited += 1
        else:
            _log.info("Directory message %r was deleted; forgetting it", key)
            await messages.forget(key)

    return edited
