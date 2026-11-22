"""/recettes: one character's recipes in one profession, and the Discord limits around them."""

from typing import TYPE_CHECKING, cast

import aiosqlite
import discord

from bot.recipes import NO_RECIPE, recipes_of
from config import ProfessionCatalog
from db import ProfessionRepo
from domain import CharacterProfession, Recipe, RosterCharacter

if TYPE_CHECKING:
    from bot.client import GuildBot

TAILORING = 197
ENCHANTING = 333
# An id professions.toml does not list: Blizzard could add one tomorrow.
UNKNOWN_PROFESSION = 755

VEST = Recipe(
    recipe_id=6586,
    name_en="Red Mageweave Vest",
    name_fr="Gilet rouge en tisse-mage",
    crafted_item_id=10007,
    crafted_name_en="Red Mageweave Vest",
    crafted_name_fr="Gilet rouge en tisse-mage",
)
RKA = RosterCharacter(
    slug="rka-kamechki",
    name="Rka",
    surname="Kamechki",
    level=60,
    character_id=None,
    class_id=None,
    rank=4,
)


class StubBot:
    """The two things the answer asks of the bot."""

    def __init__(self, connection: aiosqlite.Connection, catalog: ProfessionCatalog) -> None:
        self.db = connection
        self.professions = catalog


def _bot(connection: aiosqlite.Connection, catalog: ProfessionCatalog) -> "GuildBot":
    return cast("GuildBot", StubBot(connection, catalog))


def _profession(blizzard_id: int, skill: int = 245, max_skill: int = 300) -> CharacterProfession:
    return CharacterProfession(
        slug=RKA.slug,
        blizzard_id=blizzard_id,
        api_name="Tailoring" if blizzard_id == TAILORING else "Gem Cutting",
        skill=skill,
        max_skill=max_skill,
    )


async def _seed(
    professions: ProfessionRepo,
    recipes: list[tuple[int, int, str]] | None = None,
    blizzard_id: int = TAILORING,
    skill: int = 245,
) -> None:
    """Rka, with one profession and the recipes given."""
    await professions.replace_roster([RKA])
    await professions.replace_character_professions(
        RKA.slug,
        [_profession(blizzard_id, skill)],
        recipes if recipes is not None else [(blizzard_id, VEST.recipe_id, VEST.name_en)],
    )


def _length(embeds: list[discord.Embed]) -> int:
    """What Discord counts against the 6000 characters of one message."""
    return sum(len(embed) for embed in embeds)


# --- the ordinary answer --------------------------------------------------------------


async def test_the_title_names_the_profession_in_french_and_the_character(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].title is not None
    assert "Couture" in embeds[0].title
    assert "Rka-Kamechki" in embeds[0].title


async def test_the_recipes_are_listed_in_french(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)
    await professions.localise_recipes([VEST])

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].description == "Gilet rouge en tisse-mage"


async def test_a_recipe_not_localised_yet_falls_back_to_english(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The English name arrives with the professions, so the list is never empty-handed."""
    await _seed(professions)

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].description == "Red Mageweave Vest"


async def test_the_footer_counts_the_recipes_and_gives_the_skill(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(
        professions,
        [(TAILORING, 1, "Alpha"), (TAILORING, 2, "Beta"), (TAILORING, 3, "Gamma")],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[-1].footer.text == "3 recette(s) · compétence 245/300"


async def test_the_tier_cap_is_shown_rather_than_always_300(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await professions.replace_roster([RKA])
    await professions.replace_character_professions(
        RKA.slug,
        [_profession(TAILORING, skill=212, max_skill=225)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[-1].footer.text is not None
    assert "212/225" in embeds[-1].footer.text


async def test_a_profession_the_file_does_not_list_keeps_the_api_name(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """A profession Blizzard adds must show up rather than break the answer."""
    await _seed(professions, blizzard_id=UNKNOWN_PROFESSION)

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, UNKNOWN_PROFESSION)

    assert embeds[0].title is not None
    assert "Gem Cutting" in embeds[0].title


async def test_a_name_with_markdown_in_it_is_escaped(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions, [(TAILORING, 1, "Gilet *rouge*")])

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].description == "Gilet \\*rouge\\*"


# --- the Discord limits ---------------------------------------------------------------


async def test_a_long_list_is_spread_over_several_embeds(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """A tailor at 300 knows well over a hundred recipes; a description holds 4096."""
    await _seed(
        professions,
        [(TAILORING, 1000 + index, f"Recette numéro {index:04d}") for index in range(200)],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert len(embeds) > 1
    assert all(embed.description is not None and len(embed.description) <= 4096 for embed in embeds)


async def test_the_whole_answer_stays_under_what_one_message_holds(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The 6000 characters are shared by every embed of the message, not one each."""
    await _seed(
        professions,
        [
            (TAILORING, 1000 + index, f"Recette interminable numéro {index:04d}")
            for index in range(400)
        ],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert _length(embeds) <= 6000


async def test_a_trimmed_list_says_how_much_is_missing(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(
        professions,
        [(TAILORING, 1000 + index, f"Recette numéro {index:04d}") for index in range(400)],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[-1].footer.text is not None
    assert "non affichée(s)" in embeds[-1].footer.text
    assert embeds[-1].footer.text.startswith("400 recette(s)")


async def test_only_the_first_embed_carries_the_title(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """Repeating it on every piece would read like several answers."""
    await _seed(
        professions,
        [(TAILORING, 1000 + index, f"Recette numéro {index:04d}") for index in range(200)],
    )

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].title is not None
    assert all(embed.title is None for embed in embeds[1:])


# --- nothing to list ------------------------------------------------------------------


async def test_an_unknown_character_is_told_to_use_the_list(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    embeds = await recipes_of(_bot(connection, professions_catalog), "personne-du-tout", TAILORING)

    assert len(embeds) == 1
    assert embeds[0].description is not None
    assert embeds[0].description.startswith("Personnage inconnu.")
    assert embeds[0].colour == discord.Colour.greyple()


async def test_a_character_without_that_profession_is_named(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The profession is picked after the character, so a stale choice is reachable."""
    await _seed(professions)

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, ENCHANTING)

    assert embeds[0].description == "**Rka-Kamechki** n'a pas ce métier."


async def test_a_profession_without_a_single_recipe_says_so(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions, [])

    embeds = await recipes_of(_bot(connection, professions_catalog), RKA.slug, TAILORING)

    assert embeds[0].description == NO_RECIPE
    assert embeds[0].footer.text == "0 recette(s) · compétence 245/300"
