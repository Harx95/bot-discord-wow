"""The daily sync: mirror the guild's professions from the Battle.net API into the database.

Nothing reads the API except this. The commands read the database, which is what makes them
instant and what lets them answer at all while Blizzard is down.

Shape of one run, and what it costs, measured on the real roster:

- one call for the roster (25 characters), then one per character of level 10 or more --
  below that every profile endpoint answers 404, so asking is a wasted request;
- then one call per recipe nobody has ever looked up. A recipe name never changes, so the
  dictionary is permanent: the first run fetched 499, every run after fetches almost none.
  That is what keeps a daily sync at 26 requests rather than 525.

A character whose call fails is recorded in the report and left as it was, rather than
emptied: yesterday's professions beat none at all. The roster failing is different -- there
is nothing to sync without it -- so that one is raised.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from api import ForeverApiError
from db import ProfessionRepo
from db.timestamps import utcnow
from domain import Recipe, SyncReport

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

NO_GUILD = (
    "Blizzard ne connaît aucune guilde nommée {slug!r}. Vérifie GUILD_NAME : le slug est "
    "construit à partir de lui."
)


async def sync_professions(bot: "GuildBot") -> SyncReport:
    """Mirror the roster, its professions and the recipes they know. Raises on a dead API."""
    started_at = utcnow()
    repo = ProfessionRepo(bot.db)
    client = bot.forever
    slug = bot.settings.guild_api_slug
    failures: list[str] = []

    roster = await client.guild_roster(slug)
    if roster is None:
        raise ForeverApiError(f"/data/wow/guild/{slug}/roster", 404, NO_GUILD.format(slug=slug))

    await repo.replace_roster(roster)
    visible = [character for character in roster if character.is_visible_to_api]
    skipped = len(roster) - len(visible)
    _log.info("Roster: %d character(s), %d below the level the API publishes", len(roster), skipped)

    # The client gates itself at a few calls in flight, so gathering the lot is safe.
    ignore = bot.professions.ignored_ids
    answers = await asyncio.gather(
        *(client.character_professions(c.slug, ignore=ignore) for c in visible),
        return_exceptions=True,
    )

    synced = professions = links = 0
    unknown: set[int] = set()
    known_ids = set(bot.professions.blizzard_ids)

    for character, answer in zip(visible, answers, strict=True):
        if isinstance(answer, BaseException):
            failures.append(f"{character.display_name} : {answer}")
            _log.warning("Professions of %s failed: %s", character.slug, answer)
            continue
        if answer is None:
            # Level 10 or above but not published yet: the character has never logged out.
            skipped += 1
            continue

        found, recipes = answer
        await repo.replace_character_professions(character.slug, found, recipes)
        synced += 1
        professions += len(found)
        links += len(recipes)
        unknown |= {p.blizzard_id for p in found} - known_ids

    if unknown:
        # Shown in the directory under the name the API gave it, rather than dropped.
        _log.warning(
            "Profession id(s) %s are not in professions.toml; add them to name them in French",
            sorted(unknown),
        )

    fetched = await _localise(repo, bot, failures)

    report = SyncReport(
        started_at=started_at,
        finished_at=utcnow(),
        characters=synced,
        skipped=skipped,
        professions=professions,
        recipe_links=links,
        recipes_fetched=fetched,
        failures=tuple(failures),
    )
    await repo.record_sync(report)
    _log.info(
        "Sync done in %.1fs: %d character(s), %d profession(s), %d recipe link(s), "
        "%d recipe(s) newly named, %d failure(s)",
        report.duration_seconds,
        report.characters,
        report.professions,
        report.recipe_links,
        report.recipes_fetched,
        len(report.failures),
    )
    return report


async def _localise(repo: ProfessionRepo, bot: "GuildBot", failures: list[str]) -> int:
    """Give a French name to every recipe that has never had one.

    Only the static namespace localises anything, so this is a second call per recipe --
    made once in a recipe's life. A failure here costs French, not the feature: the English
    name arrived with the professions and is already searchable.
    """
    pending = await repo.recipes_awaiting_translation()
    if not pending:
        return 0

    _log.info("Naming %d new recipe(s)", len(pending))
    answers = await asyncio.gather(
        *(bot.forever.recipe(recipe_id) for recipe_id in pending),
        return_exceptions=True,
    )

    found: list[Recipe] = []
    broken = 0
    for recipe_id, answer in zip(pending, answers, strict=True):
        if isinstance(answer, BaseException):
            broken += 1
            _log.warning("Recipe %d could not be named: %s", recipe_id, answer)
        elif answer is not None:
            found.append(answer)

    if broken:
        failures.append(
            f"{broken} recette(s) n'ont pas pu être nommées en français ; "
            "elles restent trouvables en anglais."
        )
    return await repo.localise_recipes(found)
