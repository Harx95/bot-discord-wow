"""/recettes: everything one character has learned in one profession.

Read off the database like /qui-métier, and for the same reason: the daily sync is the only
thing that talks to Blizzard. A tailor at 300 knows well over a hundred recipes, so the list
is spread over several embeds of one message -- Discord caps a description at 4096
characters and the whole message at 6000, whatever the number of embeds.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import discord

from bot.rendering import fit_lines
from config import ProfessionCatalog
from db import ProfessionRepo
from domain import CharacterProfession, Recipe

if TYPE_CHECKING:
    from bot.client import GuildBot

# A description holds 4096 characters, and every embed of one message 6000 between them.
# The rest of that budget pays for the title and the footer.
DESCRIPTION_BUDGET = 3900
TOTAL_BUDGET = 5200
TITLE_LIMIT = 256

TITLE = "{profession} · {character}"
NO_RECIPE = "_Aucune recette connue pour l'instant._"
UNKNOWN_CHARACTER = (
    "Personnage inconnu.\n\nChoisis-le dans la liste que la commande propose : l'annuaire "
    "ne connaît que les personnages de la guilde qui ont au moins un métier."
)
WITHOUT_PROFESSION = "**{character}** n'a pas ce métier."
FOOTER = "{count} recette(s) · compétence {skill}/{max_skill}"
FOOTER_TRIMMED = " · {count} non affichée(s)"


def _chunks(lines: Sequence[str], budget: int) -> list[list[str]]:
    """The lines cut into embed-sized pieces, each one whole line at a time."""
    chunks: list[list[str]] = []
    current: list[str] = []
    used = 0
    for line in lines:
        if current and used + len(line) + 1 > budget:
            chunks.append(current)
            current, used = [], 0
        current.append(line)
        used += len(line) + 1
    if current:
        chunks.append(current)
    return chunks


def refusal(description: str) -> discord.Embed:
    """A greyed-out answer, the way /qui-métier greys out the ones with nobody in them."""
    return discord.Embed(description=description, colour=discord.Colour.greyple())


def recipe_embeds(
    label: str,
    character: str,
    profession: CharacterProfession,
    recipes: Sequence[Recipe],
) -> list[discord.Embed]:
    """The recipes as one or more embeds, the first one carrying the title.

    French names, falling back to English for a recipe the static endpoint has not been
    asked about yet: a recipe is readable the moment the sync sees it.
    """
    lines = [discord.utils.escape_markdown(recipe.display_name) for recipe in recipes]
    shown, hidden = fit_lines(lines, TOTAL_BUDGET)
    chunks = _chunks(shown, DESCRIPTION_BUDGET) or [[NO_RECIPE]]

    title = TITLE.format(profession=label, character=character)[:TITLE_LIMIT]
    embeds = [
        discord.Embed(
            title=title if index == 0 else None,
            description="\n".join(chunk),
            colour=discord.Colour.blurple() if recipes else discord.Colour.greyple(),
        )
        for index, chunk in enumerate(chunks)
    ]

    footer = FOOTER.format(
        count=len(recipes),
        skill=profession.skill,
        max_skill=profession.max_skill,
    )
    if hidden:
        footer += FOOTER_TRIMMED.format(count=hidden)
    # On the last one: it is the end of the list the footer counts.
    embeds[-1].set_footer(text=footer)
    return embeds


async def recipes_of(bot: "GuildBot", slug: str, blizzard_id: int) -> list[discord.Embed]:
    """The whole answer to /recettes, or a greyed-out embed saying why there is none."""
    professions = ProfessionRepo(bot.db)
    character = await professions.character(slug)
    if character is None:
        return [refusal(UNKNOWN_CHARACTER)]

    held = await professions.professions_of(slug)
    profession = next((p for p in held if p.blizzard_id == blizzard_id), None)
    if profession is None:
        # Reachable without typing anything odd: the profession is picked second, so it can
        # be left on a choice offered for the character chosen before it.
        return [
            refusal(
                WITHOUT_PROFESSION.format(
                    character=discord.utils.escape_markdown(character.display_name)
                )
            )
        ]

    recipes = await professions.known_recipes(slug, blizzard_id)
    return recipe_embeds(
        _label(bot.professions, profession),
        discord.utils.escape_markdown(character.display_name),
        profession,
        recipes,
    )


def _label(catalog: ProfessionCatalog, profession: CharacterProfession) -> str:
    """The profession as a member reads it, falling back to the name the API gave."""
    definition = catalog.by_id(profession.blizzard_id)
    return definition.label if definition else profession.api_name
