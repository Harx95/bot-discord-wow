"""Who can craft what: the answer to /qui-métier, built from the database alone.

No call to Blizzard happens here. A member typing an item name reads the mirror the daily
sync wrote, which is what the cache was for: the answer is instant, and it is the same
answer after a restart.

The answer is grouped by recipe rather than listed flat, because one search often matches
several recipes -- "potion" matches a dozen -- and "who can craft this" is only meaningful
per recipe. A group is always whole: the artisans shown under a recipe are all of them, or
the line saying how many were left out.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bot.rendering import fit_lines
from config import ProfessionCatalog
from db import ProfessionRepo
from domain import Artisan, Recipe

if TYPE_CHECKING:
    from bot.client import GuildBot

# An embed holds 25 fields, so 25 recipes at most are detailed. Rows are fetched well past
# that: 25 recipes spread over every artisan who knows one of them is many more rows.
MAX_RECIPES = 25
ROW_LIMIT = 200

# A field value is capped at 1024 characters, so a recipe nearly everybody knows stops.
ARTISAN_BUDGET = 900

# An embed title is capped at 256 and a field name too, and both carry a name typed by a
# member, so both are cut rather than trusted.
TITLE_LIMIT = 256
FIELD_NAME_LIMIT = 256

TITLE = "Qui peut fabriquer « {query} » ?"
NOTHING_TITLE = "« {query} » : personne"
MORE_ARTISANS = "… et {count} de plus."
FOOTER = "{recipes} recette(s) · {artisans} artisan(s)"
FOOTER_TRIMMED = " · {count} recette(s) de plus, précise ta recherche"

NOBODY_KNOWS = (
    "Cette recette existe dans l'annuaire, mais plus personne ne la connaît : {recipes}.\n\n"
    "Soit la personne qui la connaissait a quitté la guilde, soit son métier n'est pas suivi."
)
NO_SUCH_RECIPE = (
    "Aucune recette ne porte ce nom.\n\n"
    "L'annuaire ne connaît que les recettes apprises par un personnage de la guilde. "
    "Essaie un morceau de nom plus court, en français ou en anglais : la recherche "
    "accepte les deux, sans tenir compte des accents ni des majuscules."
)
IGNORED_NOTE = "\n\nMétiers non suivis : {professions}."


def _skill(artisan: Artisan) -> str:
    """A skill as a fixed-width code span, so the numbers line up down the column."""
    return f"`{artisan.skill:>3}/{artisan.max_skill:<3}`"


@dataclass(slots=True)
class _Group:
    """One field of the answer: a recipe name, its profession, and who knows it.

    recipe_ids holds every recipe folded into this field, which the footer needs: the
    artisans are deduplicated, so counting recipes off them would under-count and the
    answer would claim it had trimmed something it showed.
    """

    head: Artisan
    artisans: dict[str, Artisan]
    recipe_ids: set[int]


def _groups(artisans: Sequence[Artisan]) -> list[_Group]:
    """The artisans grouped by profession and recipe name, in the order they arrived.

    Keyed on the name rather than the recipe id: the gathering professions carry one
    pseudo-recipe per rank, and Blizzard localises all of them to the same word, so
    searching "Herboristerie" produced seven identical fields on the live roster. Two
    recipes a member cannot tell apart are one answer, and an artisan who knows several of
    them is listed once, at their highest skill -- the rows arrive most skilled first.

    The profession is part of the key as well, so a field can name one profession without
    having to check that every artisan under it shares it.
    """
    grouped: dict[tuple[int, str], _Group] = {}
    for artisan in artisans:
        key = (artisan.blizzard_id, artisan.recipe_name)
        group = grouped.get(key)
        if group is None:
            group = grouped[key] = _Group(head=artisan, artisans={}, recipe_ids=set())
        group.artisans.setdefault(artisan.character, artisan)
        group.recipe_ids.add(artisan.recipe_id)
    return list(grouped.values())


def _field_name(head: Artisan, catalog: ProfessionCatalog) -> str:
    """The recipe, under the French name of its profession when the file knows it."""
    definition = catalog.by_id(head.blizzard_id)
    label = definition.label if definition else head.profession_name
    return f"{label} · {head.recipe_name}"[:FIELD_NAME_LIMIT]


def _field_value(group: Sequence[Artisan]) -> str:
    """One line per artisan, most skilled first, trimmed to what a field holds."""
    lines = [f"{_skill(a)}  {discord.utils.escape_markdown(a.character)}" for a in group]
    shown, hidden = fit_lines(lines, ARTISAN_BUDGET)
    value = "\n".join(shown)
    return f"{value}\n{MORE_ARTISANS.format(count=hidden)}" if hidden else value


def crafters_embed(
    query: str,
    artisans: Sequence[Artisan],
    total_recipes: int,
    catalog: ProfessionCatalog,
) -> discord.Embed:
    """Who can craft what was searched for, one field per recipe."""
    groups = _groups(artisans)[:MAX_RECIPES]

    embed = discord.Embed(
        title=TITLE.format(query=query)[:TITLE_LIMIT],
        colour=discord.Colour.blurple(),
    )
    for group in groups:
        # Full width: a column of skills and names is unreadable three to a row.
        embed.add_field(
            name=_field_name(group.head, catalog),
            value=_field_value(list(group.artisans.values())),
            inline=False,
        )

    shown = sum(len(group.artisans) for group in groups)
    footer = FOOTER.format(recipes=len(groups), artisans=shown)
    # Counted on the recipes the fields actually cover, which is not their number: one
    # field can hold several recipes that share a name. Covers both caps at once -- the 25
    # fields, and the rows the search stopped fetching at.
    covered = {recipe_id for group in groups for recipe_id in group.recipe_ids}
    trimmed = max(total_recipes - len(covered), 0)
    if trimmed:
        footer += FOOTER_TRIMMED.format(count=trimmed)
    embed.set_footer(text=footer)
    return embed


def nothing_embed(
    query: str,
    named: Sequence[Recipe],
    catalog: ProfessionCatalog,
) -> discord.Embed:
    """Nobody can craft it -- and why, which is not the same thing twice.

    A name the dictionary knows means the search worked and the guild lost the artisan; a
    name it does not know means the search found nothing to answer about.
    """
    if named:
        description = NOBODY_KNOWS.format(
            recipes=", ".join(f"**{recipe.display_name}**" for recipe in named)
        )
    else:
        description = NO_SUCH_RECIPE
        # Read from the catalog rather than written out here: the three left out today are
        # a configuration choice, and this sentence must not outlive it.
        ignored = [p.name for p in catalog.professions if p.ignored]
        if ignored:
            description += IGNORED_NOTE.format(professions=", ".join(ignored))

    return discord.Embed(
        title=NOTHING_TITLE.format(query=query)[:TITLE_LIMIT],
        description=description,
        colour=discord.Colour.greyple(),
    )


async def who_can_craft(bot: "GuildBot", query: str) -> discord.Embed:
    """The whole answer to /qui-métier, in one or two reads of the database."""
    professions = ProfessionRepo(bot.db)
    artisans = await professions.artisans_for(query, limit=ROW_LIMIT)
    if not artisans:
        return nothing_embed(query, await professions.named_recipes(query), bot.professions)

    # Counted separately: the rows above stop at ROW_LIMIT, so they cannot say how many
    # recipes matched in all, and an answer that trims must say so.
    total = await professions.recipe_matches(query)
    return crafters_embed(query, artisans, total, bot.professions)
