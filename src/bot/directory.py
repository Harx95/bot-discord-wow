"""The profession directory: syncing it from the Blizzard API and drawing its message."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import groupby
from typing import Protocol

import discord

from blizzard import BlizzardError
from config import ProfessionCatalog
from db import ProfessionRepo
from domain import CharacterSkill, DirectoryLine, GuildCharacter, Profession

_log = logging.getLogger(__name__)

DIRECTORY_KEY = "profession_directory"

# Characters fetched at once. Far under the API's 100 requests per second, and gentle
# enough that a sync of the whole guild still takes only a few seconds.
CONCURRENT_FETCHES = 5

# Discord API limits.
EMBED_TOTAL_LIMIT = 6000
EMBED_FIELDS_LIMIT = 25
FIELD_VALUE_LIMIT = 1024

BAR_WIDTH = 10
BAR_FILLED = "▰"
BAR_EMPTY = "▱"

TITLE = "📜 Annuaire des métiers"
DESCRIPTION = "Métiers principaux des membres de la guilde, d'après l'Armurerie du jeu."
EMPTY = "_Aucun métier connu pour l'instant._"
CONTINUED = "{name} (suite)"
FOOTER = "{count} personnages dans la guilde · Synchronisé chaque jour à {hour} h"
TRUNCATED = " · {hidden} ligne(s) non affichée(s), faute de place"


class DirectorySource(Protocol):
    """What a sync needs from the Blizzard API."""

    async def guild_roster(self, guild_slug: str) -> list[GuildCharacter]: ...

    async def primary_skills(self, character_slug: str) -> list[CharacterSkill] | None: ...

    async def profession(self, profession_id: int) -> Profession: ...


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What a sync found, for the officer who asked for it and for the logs."""

    roster_size: int
    fetched: int
    changed: bool
    # Characters the API does not show yet: below level 10, or never logged out since.
    hidden: list[str] = field(default_factory=list[str])
    # Characters whose request failed. They keep the skills of the previous sync.
    failed: list[str] = field(default_factory=list[str])


async def sync_directory(
    source: DirectorySource,
    repo: ProfessionRepo,
    guild_slug: str,
) -> SyncReport:
    """Fetch the roster and every member's primary professions, then store them.

    Raises BlizzardError when the roster or a profession name cannot be fetched: without
    them the directory cannot be trusted, and the previous one is kept as it was.
    """
    roster = await source.guild_roster(guild_slug)
    if not roster:
        # An empty roster would wipe the whole directory; a real guild never has one.
        raise BlizzardError(f"Guild {guild_slug!r} came back with an empty roster")

    semaphore = asyncio.Semaphore(CONCURRENT_FETCHES)

    async def fetch(character: GuildCharacter) -> list[CharacterSkill] | BlizzardError | None:
        async with semaphore:
            try:
                return await source.primary_skills(character.slug)
            except BlizzardError as error:
                _log.warning("Could not fetch the professions of %s: %s", character.slug, error)
                return error

    results = await asyncio.gather(*(fetch(character) for character in roster))

    skills: dict[str, list[CharacterSkill]] = {}
    hidden: list[str] = []
    failed: list[str] = []
    for character, result in zip(roster, results, strict=True):
        if isinstance(result, BlizzardError):
            failed.append(character.full_name)
        elif result is None:
            hidden.append(character.full_name)
        else:
            skills[character.slug] = result

    known = await repo.known_profession_ids()
    wanted = {skill.profession_id for found in skills.values() for skill in found}
    for profession_id in sorted(wanted - known):
        profession = await source.profession(profession_id)
        await repo.save_profession(profession)
        _log.info("Learned profession %d: %s", profession.id, profession.name)

    changed = await repo.apply_sync(roster, skills)
    return SyncReport(
        roster_size=len(roster),
        fetched=len(skills),
        changed=changed,
        hidden=sorted(hidden),
        failed=sorted(failed),
    )


def _bar(skill: int, cap: int) -> str:
    """Progress towards the game's highest skill."""
    filled = min(BAR_WIDTH, round(BAR_WIDTH * skill / cap)) if cap else 0
    return BAR_FILLED * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def _line(line: DirectoryLine, cap: int) -> str:
    """One character under a profession: bar, skill, name."""
    return f"{_bar(line.skill, cap)} **{line.skill}** · {line.character_name}"


def _chunks(lines: Sequence[str]) -> list[str]:
    """Pack lines into field values that fit Discord's 1024 characters each."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > FIELD_VALUE_LIMIT and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def directory_embed(
    lines: Sequence[DirectoryLine],
    catalog: ProfessionCatalog,
    character_count: int,
    sync_hour: int,
) -> discord.Embed:
    """The directory message: one block per profession, best skill first.

    A profession too long for one field continues in a second one. Should the whole
    directory outgrow an embed, the last lines are dropped and the footer says how many.
    """
    embed = discord.Embed(title=TITLE, description=DESCRIPTION, colour=discord.Colour.dark_gold())
    footer = FOOTER.format(count=character_count, hour=sync_hour)

    if not lines:
        embed.description = f"{DESCRIPTION}\n\n{EMPTY}"
        embed.set_footer(text=footer)
        return embed

    # Room kept for the truncation notice, so adding it can never break the total.
    budget = EMBED_TOTAL_LIMIT - len(TITLE) - len(DESCRIPTION) - len(footer) - len(TRUNCATED) - 10
    shown = 0
    for _, group in groupby(lines, key=lambda line: line.profession.id):
        entries = list(group)
        profession = entries[0].profession
        name = f"{catalog.emoji_of(profession.id)} {profession.name}"

        for index, chunk in enumerate(
            _chunks([_line(entry, catalog.skill_cap) for entry in entries])
        ):
            title = name if index == 0 else CONTINUED.format(name=name)
            if len(embed.fields) >= EMBED_FIELDS_LIMIT or len(title) + len(chunk) > budget:
                break
            embed.add_field(name=title, value=chunk, inline=False)
            budget -= len(title) + len(chunk)
            shown += chunk.count("\n") + 1

    if shown < len(lines):
        footer += TRUNCATED.format(hidden=len(lines) - shown)
    embed.set_footer(text=footer)
    return embed
