"""/qui-métier: the answer to "who can craft this", read off the mirrored roster.

The rows below are shaped like the live ones read on 20 November 2026: a tailor and an
enchanter, a recipe that crafts an item and one that crafts nothing.
"""

from typing import TYPE_CHECKING, cast

import aiosqlite
import discord

from bot.crafters import ARTISAN_BUDGET, MAX_RECIPES, who_can_craft
from config import ProfessionCatalog
from db import ProfessionRepo
from domain import CharacterProfession, Recipe, RosterCharacter

if TYPE_CHECKING:
    from bot.client import GuildBot

TAILORING = 197
ENCHANTING = 333
HERBALISM = 182

VEST = Recipe(
    recipe_id=6586,
    name_en="Red Mageweave Vest",
    name_fr="Gilet rouge en tisse-mage",
    crafted_item_id=10007,
    crafted_name_en="Red Mageweave Vest",
    crafted_name_fr="Gilet rouge en tisse-mage",
)
ENCHANT = Recipe(
    recipe_id=7523,
    name_en="Enchant Chest - Greater Intellect",
    name_fr="Ench. de plastron (Intelligence supérieure)",
    crafted_item_id=None,
    crafted_name_en=None,
    crafted_name_fr=None,
)


class StubBot:
    """The two things the search asks of the bot."""

    def __init__(self, connection: aiosqlite.Connection, catalog: ProfessionCatalog) -> None:
        self.db = connection
        self.professions = catalog


def _bot(connection: aiosqlite.Connection, catalog: ProfessionCatalog) -> "GuildBot":
    """Hand the stub to code typed for the real bot, the way tests/fakes.py does."""
    return cast("GuildBot", StubBot(connection, catalog))


def _character(name: str, surname: str | None = None, level: int = 60) -> RosterCharacter:
    slug = f"{name}-{surname}".lower() if surname else name.lower()
    return RosterCharacter(
        slug=slug,
        name=name,
        surname=surname,
        level=level,
        character_id=None,
        class_id=None,
        rank=4,
    )


def _profession(slug: str, blizzard_id: int, skill: int) -> CharacterProfession:
    return CharacterProfession(
        slug=slug,
        blizzard_id=blizzard_id,
        api_name={TAILORING: "Tailoring", ENCHANTING: "Enchanting"}.get(blizzard_id, "Herbalism"),
        skill=skill,
        max_skill=300,
    )


async def _seed(professions: ProfessionRepo) -> None:
    """Two tailors who both know the vest, one of them also an enchanter."""
    mhas = _character("Mhas", "Lananas")
    rka = _character("Rka", "Kamechki")
    await professions.replace_roster([mhas, rka])
    await professions.replace_character_professions(
        mhas.slug,
        [_profession(mhas.slug, TAILORING, 258)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )
    await professions.replace_character_professions(
        rka.slug,
        [_profession(rka.slug, TAILORING, 245), _profession(rka.slug, ENCHANTING, 275)],
        [
            (TAILORING, VEST.recipe_id, VEST.name_en),
            (ENCHANTING, ENCHANT.recipe_id, ENCHANT.name_en),
        ],
    )
    await professions.localise_recipes([VEST, ENCHANT])


def _field(embed: discord.Embed, index: int = 0) -> tuple[str, str]:
    """One field's name and value, both asserted to be there."""
    field = embed.fields[index]
    assert field.name is not None
    assert field.value is not None
    return field.name, field.value


# --- the ordinary answer --------------------------------------------------------------


async def test_the_artisans_are_grouped_under_their_recipe(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet rouge")

    assert len(embed.fields) == 1
    _, value = _field(embed)
    assert "Mhas-Lananas" in value
    assert "Rka-Kamechki" in value


async def test_the_most_skilled_artisan_is_listed_first(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet rouge")

    _, value = _field(embed)
    assert value.index("Mhas") < value.index("Rka")
    assert "`258/300`" in value


async def test_the_field_names_the_profession_in_french(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The API only ever says "Tailoring"; a member reads "Couture"."""
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet rouge")

    name, _ = _field(embed)
    assert "Couture" in name
    assert "Gilet rouge en tisse-mage" in name


async def test_both_languages_find_the_same_people(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The whole point of localising the dictionary: either name works."""
    await _seed(professions)
    bot = _bot(connection, professions_catalog)

    french = await who_can_craft(bot, "Gilet rouge en tisse-mage")
    english = await who_can_craft(bot, "Red Mageweave Vest")

    assert _field(french)[1] == _field(english)[1]


async def test_a_recipe_that_crafts_nothing_is_found_by_its_own_name(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """87 of the 589 recipes craft no item: enchantments, and the gathering pseudo-recipes."""
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "intelligence superieure")

    name, value = _field(embed)
    assert "Enchantement" in name
    assert "Rka-Kamechki" in value


async def test_several_recipes_make_several_fields(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """A vague search matches more than one recipe, and each keeps its own artisans."""
    await _seed(professions)
    bot = _bot(connection, professions_catalog)

    embed = await who_can_craft(bot, "e")

    assert len(embed.fields) == 2


async def test_the_footer_counts_the_recipes_and_the_artisans(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet rouge")

    assert embed.footer.text == "1 recette(s) · 2 artisan(s)"


async def test_a_name_with_markdown_in_it_is_escaped(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """An asterisk in a character name would otherwise italicise the rest of the field."""
    gros = _character("Gros*minet")
    await professions.replace_roster([gros])
    await professions.replace_character_professions(
        gros.slug,
        [_profession(gros.slug, TAILORING, 300)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )

    embed = await who_can_craft(_bot(connection, professions_catalog), "mageweave")

    assert "Gros\\*minet" in _field(embed)[1]


async def test_recipes_that_share_a_name_make_one_field(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The gathering professions carry one pseudo-recipe per rank, all named the same.

    On the live roster "Herboristerie" matched seven of them, which produced seven
    identical fields listing the same people over and over.
    """
    flo = _character("Flo", "Lefraiseur")
    chewa = _character("Chewa", "Zaag")
    await professions.replace_roster([flo, chewa])
    ranks = [(HERBALISM, 2366 + step, "Herbalism") for step in range(3)]
    await professions.replace_character_professions(
        flo.slug, [_profession(flo.slug, HERBALISM, 264)], ranks
    )
    await professions.replace_character_professions(
        chewa.slug, [_profession(chewa.slug, HERBALISM, 204)], ranks[:2]
    )

    embed = await who_can_craft(_bot(connection, professions_catalog), "herbalism")

    assert len(embed.fields) == 1
    value = _field(embed)[1]
    assert value.count("Flo-Lefraiseur") == 1
    assert value.count("Chewa-Zaag") == 1
    assert embed.footer.text == "1 recette(s) · 2 artisan(s)"


async def test_the_highest_skill_is_kept_when_a_name_is_merged(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """Merging must not drop the skill column to whichever rank came last."""
    flo = _character("Flo", "Lefraiseur")
    await professions.replace_roster([flo])
    await professions.replace_character_professions(
        flo.slug,
        [_profession(flo.slug, HERBALISM, 264)],
        [(HERBALISM, 2366 + step, "Herbalism") for step in range(3)],
    )

    embed = await who_can_craft(_bot(connection, professions_catalog), "herbalism")

    assert "`264/300`" in _field(embed)[1]


# --- the caps -------------------------------------------------------------------------


async def test_the_answer_stops_at_the_embed_field_limit_and_says_so(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """Thirty recipes match "potion": an embed holds 25 fields, so five are announced."""
    rka = _character("Rka", "Kamechki")
    await professions.replace_roster([rka])
    await professions.replace_character_professions(
        rka.slug,
        [_profession(rka.slug, TAILORING, 300)],
        [(TAILORING, 1000 + index, f"Potion {index:02d}") for index in range(30)],
    )

    embed = await who_can_craft(_bot(connection, professions_catalog), "potion")

    assert len(embed.fields) == MAX_RECIPES
    assert embed.footer.text is not None
    assert "5 recette(s) de plus" in embed.footer.text


async def test_a_recipe_half_the_guild_knows_is_trimmed_inside_its_field(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """A field value is capped at 1024 characters, so the column has to stop somewhere."""
    roster = [_character(f"Personnage{index:03d}") for index in range(60)]
    await professions.replace_roster(roster)
    for character in roster:
        await professions.replace_character_professions(
            character.slug,
            [_profession(character.slug, TAILORING, 300)],
            [(TAILORING, VEST.recipe_id, VEST.name_en)],
        )

    embed = await who_can_craft(_bot(connection, professions_catalog), "mageweave")

    _, value = _field(embed)
    assert len(value) <= ARTISAN_BUDGET + len("… et 99 de plus.") + 1
    assert "de plus" in value


async def test_a_very_long_search_does_not_overflow_the_title(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The title carries what a member typed, and Discord rejects an embed past 256."""
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet " * 60)

    assert embed.title is not None
    assert len(embed.title) <= 256


# --- nobody can craft it --------------------------------------------------------------


async def test_a_name_no_recipe_carries_says_exactly_that(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    embed = await who_can_craft(_bot(connection, professions_catalog), "Flask of the Titans")

    assert embed.description is not None
    assert embed.description.startswith("Aucune recette ne porte ce nom.")
    assert not embed.fields


async def test_the_untracked_professions_are_named_so_the_refusal_is_actionable(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """Read from professions.toml, so the sentence cannot outlive the choice it describes."""
    embed = await who_can_craft(_bot(connection, professions_catalog), "bandage en lin")

    assert embed.description is not None
    assert "Cuisine, Secourisme, Pêche" in embed.description


async def test_a_recipe_whose_artisan_left_is_told_apart_from_an_unknown_name(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The dictionary keeps the name for ever, so the answer can say which it is."""
    await _seed(professions)
    await professions.replace_roster([])

    embed = await who_can_craft(_bot(connection, professions_catalog), "gilet rouge")

    assert embed.description is not None
    assert "plus personne ne la connaît" in embed.description
    assert "Gilet rouge en tisse-mage" in embed.description


async def test_an_answer_with_nobody_in_it_is_greyed_out(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)
    bot = _bot(connection, professions_catalog)

    found = await who_can_craft(bot, "gilet rouge")
    missing = await who_can_craft(bot, "Flask of the Titans")

    assert found.colour != missing.colour
