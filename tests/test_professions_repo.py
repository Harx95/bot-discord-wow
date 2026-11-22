"""ProfessionRepo: the mirrored roster, its professions, and the recipe dictionary.

The fixtures below are real rows read off the live API on 20 November 2026, trimmed down.
"""

from dataclasses import replace

from db import ProfessionRepo
from db.timestamps import utcnow
from domain import CharacterProfession, Recipe, RosterCharacter, SyncReport

RKA = RosterCharacter(
    slug="rka-kamechki",
    name="Rka",
    surname="Kamechki",
    level=60,
    character_id=3889172,
    class_id=5,
    rank=3,
)
MHAS = RosterCharacter(
    slug="mhas-lananas",
    name="Mhas",
    surname="Lananas",
    level=60,
    character_id=4,
    class_id=8,
    rank=3,
)
ROOKIE = RosterCharacter(
    slug="bebe-lezard",
    name="Bebe",
    surname="Lezard",
    level=2,
    character_id=9,
    class_id=1,
    rank=5,
)

TAILORING = 197
ENCHANTING = 333

VEST = Recipe(
    recipe_id=6586,
    name_en="Red Mageweave Vest",
    name_fr="Gilet rouge en tisse-mage",
    crafted_item_id=10007,
    crafted_name_en="Red Mageweave Vest",
    crafted_name_fr="Gilet rouge en tisse-mage",
)
# An enchantment crafts no item: 87 of the guild's 589 recipes are like this.
ENCHANT = Recipe(
    recipe_id=7523,
    name_en="Enchant Chest - Greater Intellect",
    name_fr="Ench. de plastron (Intelligence supérieure)",
    crafted_item_id=None,
    crafted_name_en=None,
    crafted_name_fr=None,
)


def _profession(slug: str, blizzard_id: int, skill: int, max_skill: int) -> CharacterProfession:
    return CharacterProfession(
        slug=slug,
        blizzard_id=blizzard_id,
        api_name="Tailoring" if blizzard_id == TAILORING else "Enchanting",
        skill=skill,
        max_skill=max_skill,
    )


async def _seed(professions: ProfessionRepo) -> None:
    """Two tailors and one enchanter, with the vest and the enchantment localised."""
    await professions.replace_roster([RKA, MHAS, ROOKIE])
    await professions.replace_character_professions(
        RKA.slug,
        [_profession(RKA.slug, TAILORING, 245, 300), _profession(RKA.slug, ENCHANTING, 275, 300)],
        [
            (TAILORING, VEST.recipe_id, VEST.name_en),
            (ENCHANTING, ENCHANT.recipe_id, ENCHANT.name_en),
        ],
    )
    await professions.replace_character_professions(
        MHAS.slug,
        [_profession(MHAS.slug, TAILORING, 258, 300)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )
    await professions.localise_recipes([VEST, ENCHANT])


# --- the roster -----------------------------------------------------------------------


async def test_the_roster_is_stored_highest_level_first(professions: ProfessionRepo) -> None:
    await professions.replace_roster([ROOKIE, RKA])

    assert [c.slug for c in await professions.roster()] == [RKA.slug, ROOKIE.slug]


async def test_a_character_who_left_the_guild_disappears(professions: ProfessionRepo) -> None:
    await professions.replace_roster([RKA, MHAS])

    await professions.replace_roster([RKA])

    assert [c.slug for c in await professions.roster()] == [RKA.slug]


async def test_losing_a_character_takes_their_professions_with_them(
    professions: ProfessionRepo,
) -> None:
    """ON DELETE CASCADE, so a departure cannot leave the directory listing a stranger."""
    await _seed(professions)

    await professions.replace_roster([MHAS])

    assert await professions.professions_of(RKA.slug) == []
    assert [row.character for row in await professions.directory(TAILORING)] == ["Mhas-Lananas"]


async def test_an_empty_roster_clears_everything(professions: ProfessionRepo) -> None:
    await _seed(professions)

    await professions.replace_roster([])

    assert await professions.roster() == []


async def test_a_resynced_character_is_updated_not_duplicated(
    professions: ProfessionRepo,
) -> None:
    await professions.replace_roster([RKA])

    await professions.replace_roster([replace(RKA, rank=1)])

    roster = await professions.roster()
    assert len(roster) == 1
    assert roster[0].rank == 1


# --- professions ----------------------------------------------------------------------


async def test_a_dropped_profession_disappears_on_the_next_sync(
    professions: ProfessionRepo,
) -> None:
    """Replace, not merge: a profession unlearned in game must not linger here."""
    await _seed(professions)

    await professions.replace_character_professions(
        RKA.slug, [_profession(RKA.slug, TAILORING, 245, 300)], []
    )

    assert [p.blizzard_id for p in await professions.professions_of(RKA.slug)] == [TAILORING]


async def test_the_directory_ranks_by_skill(professions: ProfessionRepo) -> None:
    await _seed(professions)

    rows = await professions.directory(TAILORING)

    assert [(row.character, row.skill) for row in rows] == [
        ("Mhas-Lananas", 258),
        ("Rka-Kamechki", 245),
    ]


async def test_the_directory_of_a_profession_nobody_has_is_empty(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    assert await professions.directory(164) == []


async def test_the_tier_cap_is_kept_rather_than_assumed_to_be_300(
    professions: ProfessionRepo,
) -> None:
    """A character who has not bought the next rank is capped at 75, 150 or 225."""
    await professions.replace_roster([RKA])
    await professions.replace_character_professions(
        RKA.slug, [_profession(RKA.slug, TAILORING, 212, 225)], []
    )

    rows = await professions.directory(TAILORING)
    assert (rows[0].skill, rows[0].max_skill) == (212, 225)


# --- the recipe dictionary ------------------------------------------------------------


async def test_a_recipe_is_searchable_in_english_before_it_is_localised(
    professions: ProfessionRepo,
) -> None:
    """The English name arrives with the professions, so the static call is never blocking."""
    await professions.replace_roster([RKA])
    await professions.replace_character_professions(
        RKA.slug,
        [_profession(RKA.slug, TAILORING, 245, 300)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )

    assert len(await professions.artisans_for("Red Mageweave Vest")) == 1
    assert await professions.artisans_for("Gilet rouge") == []


async def test_localising_adds_the_french_name_without_losing_the_english_one(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    assert len(await professions.artisans_for("Gilet rouge en tisse-mage")) == 2
    assert len(await professions.artisans_for("Red Mageweave Vest")) == 2


async def test_a_second_sync_does_not_undo_a_translation(professions: ProfessionRepo) -> None:
    """The dictionary only gains rows, so a daily sync must not knock French back to English."""
    await _seed(professions)

    await professions.replace_character_professions(
        RKA.slug,
        [_profession(RKA.slug, TAILORING, 250, 300)],
        [(TAILORING, VEST.recipe_id, VEST.name_en)],
    )

    assert len(await professions.artisans_for("Gilet rouge")) >= 1
    assert await professions.recipes_awaiting_translation() == []


async def test_only_unseen_recipes_are_fetched(professions: ProfessionRepo) -> None:
    """This is what makes a daily sync cost 26 requests instead of 600."""
    await _seed(professions)

    assert await professions.recipes_awaiting_translation() == []


async def test_a_new_recipe_shows_up_as_awaiting_translation(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)
    await professions.replace_character_professions(
        MHAS.slug,
        [_profession(MHAS.slug, TAILORING, 258, 300)],
        [
            (TAILORING, VEST.recipe_id, VEST.name_en),
            (TAILORING, 6612, "Admiral's Hat"),
        ],
    )

    assert await professions.recipes_awaiting_translation() == [6612]


async def test_localising_nothing_is_allowed(professions: ProfessionRepo) -> None:
    assert await professions.localise_recipes([]) == 0


# --- searching ------------------------------------------------------------------------


async def test_the_search_ignores_case_and_accents(professions: ProfessionRepo) -> None:
    await _seed(professions)

    for query in (
        "Gilet rouge en tisse-mage",
        "gilet rouge en tisse-mage",
        "GILET ROUGE EN TISSE MAGE",
        "gilet rouge en tisse mage",
    ):
        assert len(await professions.artisans_for(query)) == 2, query


async def test_a_partial_name_matches(professions: ProfessionRepo) -> None:
    assert len(await professions.artisans_for("mageweave")) == 0
    await _seed(professions)

    assert len(await professions.artisans_for("mageweave")) == 2


async def test_the_search_ranks_the_most_skilled_first(professions: ProfessionRepo) -> None:
    await _seed(professions)

    found = await professions.artisans_for("gilet rouge")

    assert [artisan.character for artisan in found] == ["Mhas-Lananas", "Rka-Kamechki"]


async def test_a_recipe_that_crafts_nothing_is_still_found_by_its_own_name(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    found = await professions.artisans_for("intelligence superieure")

    assert [artisan.character for artisan in found] == ["Rka-Kamechki"]


async def test_an_unknown_item_finds_nobody(professions: ProfessionRepo) -> None:
    await _seed(professions)

    assert await professions.artisans_for("Flask of the Titans") == []
    assert await professions.recipe_matches("Flask of the Titans") == 0


async def test_an_empty_query_finds_nobody_rather_than_everybody(
    professions: ProfessionRepo,
) -> None:
    """LIKE '%%' would match every recipe, so a blank search is refused outright."""
    await _seed(professions)

    assert await professions.artisans_for("   ") == []
    assert await professions.recipe_matches("") == 0


async def test_the_answer_is_capped(professions: ProfessionRepo) -> None:
    """An embed holds 25 fields, and 18 people knew Linen Bandage on the real roster."""
    await _seed(professions)

    assert len(await professions.artisans_for("gilet rouge", limit=1)) == 1


async def test_matches_counts_recipes_not_artisans(professions: ProfessionRepo) -> None:
    """One recipe known by two people is one match, so the answer can say what it trimmed."""
    await _seed(professions)

    assert await professions.recipe_matches("gilet rouge en tisse-mage") == 1
    assert len(await professions.artisans_for("gilet rouge en tisse-mage")) == 2


async def test_a_recipe_nobody_knows_any_more_is_not_counted(
    professions: ProfessionRepo,
) -> None:
    """The dictionary keeps rows for ever, so counting it directly would promise an artisan
    that artisans_for() cannot produce -- after a departure, or a profession left untracked.
    """
    await _seed(professions)

    await professions.replace_roster([MHAS])
    await professions.replace_character_professions(MHAS.slug, [], [])

    assert await professions.artisans_for("gilet rouge") == []
    assert await professions.recipe_matches("gilet rouge") == 0


async def test_the_search_reports_the_profession_and_the_skill(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    artisan = (await professions.artisans_for("gilet rouge"))[0]

    assert artisan.blizzard_id == TAILORING
    assert (artisan.skill, artisan.max_skill) == (258, 300)
    assert artisan.recipe_name == "Gilet rouge en tisse-mage"


async def test_the_dictionary_can_be_searched_apart_from_the_artisans(
    professions: ProfessionRepo,
) -> None:
    """What tells "nobody knows it any more" apart from "no recipe is called that"."""
    await _seed(professions)
    await professions.replace_roster([])

    assert await professions.artisans_for("gilet rouge") == []
    named = await professions.named_recipes("gilet rouge")
    assert [recipe.display_name for recipe in named] == ["Gilet rouge en tisse-mage"]


async def test_the_dictionary_search_ignores_case_and_accents_too(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    assert len(await professions.named_recipes("GILET ROUGE EN TISSE MAGE")) == 1


async def test_an_unknown_name_is_not_in_the_dictionary_either(professions: ProfessionRepo) -> None:
    await _seed(professions)

    assert await professions.named_recipes("Flask of the Titans") == []
    assert await professions.named_recipes("  ") == []


# --- /recettes ------------------------------------------------------------------------


async def test_known_recipes_are_listed_per_profession(professions: ProfessionRepo) -> None:
    await _seed(professions)

    assert [r.recipe_id for r in await professions.known_recipes(RKA.slug, TAILORING)] == [
        VEST.recipe_id
    ]
    assert [r.recipe_id for r in await professions.known_recipes(RKA.slug, ENCHANTING)] == [
        ENCHANT.recipe_id
    ]


async def test_known_recipes_are_sorted_by_the_displayed_name(
    professions: ProfessionRepo,
) -> None:
    await professions.replace_roster([RKA])
    await professions.replace_character_professions(
        RKA.slug,
        [_profession(RKA.slug, TAILORING, 300, 300)],
        [(TAILORING, 1, "Zebra"), (TAILORING, 2, "Alpha")],
    )

    assert [r.name_en for r in await professions.known_recipes(RKA.slug, TAILORING)] == [
        "Alpha",
        "Zebra",
    ]


async def test_a_character_without_that_profession_knows_nothing(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    assert await professions.known_recipes(MHAS.slug, ENCHANTING) == []


# --- autocompletion -------------------------------------------------------------------


async def test_autocompletion_offers_only_characters_with_a_profession(
    professions: ProfessionRepo,
) -> None:
    """A level 2 character has nothing to show, so offering it would waste a choice."""
    await _seed(professions)

    found = await professions.characters_like("")
    assert [character.slug for character in found] == [MHAS.slug, RKA.slug]


async def test_autocompletion_matches_a_fragment_of_either_name(
    professions: ProfessionRepo,
) -> None:
    await _seed(professions)

    assert [c.slug for c in await professions.characters_like("kamech")] == [RKA.slug]
    assert [c.slug for c in await professions.characters_like("MHAS")] == [MHAS.slug]


async def test_autocompletion_folds_what_was_typed(professions: ProfessionRepo) -> None:
    """A member typing "Rka Kamechki" with a space must still find rka-kamechki."""
    await _seed(professions)

    assert [c.slug for c in await professions.characters_like("Rka Kamechki")] == [RKA.slug]


async def test_autocompletion_carries_the_name_members_say(
    professions: ProfessionRepo,
) -> None:
    """A choice reads "Rka-Kamechki" and sends back the slug the API uses."""
    await _seed(professions)

    found = await professions.characters_like("rka")

    assert [(c.display_name, c.slug) for c in found] == [("Rka-Kamechki", "rka-kamechki")]


async def test_one_character_can_be_looked_up_by_slug(professions: ProfessionRepo) -> None:
    await _seed(professions)

    found = await professions.character(RKA.slug)

    assert found is not None
    assert found.display_name == "Rka-Kamechki"
    assert await professions.character("personne-du-tout") is None


# --- the sync record ------------------------------------------------------------------


async def test_no_sync_has_run_yet(professions: ProfessionRepo) -> None:
    assert await professions.last_sync() is None


async def test_the_last_sync_is_kept_and_replaced(professions: ProfessionRepo) -> None:
    now = utcnow()
    first = SyncReport(now, now, 25, 0, 104, 1628, 589, ())

    await professions.record_sync(first)
    await professions.record_sync(SyncReport(now, now, 26, 1, 110, 1700, 3, ("boom",)))

    stored = await professions.last_sync()
    assert stored is not None
    assert stored.characters == 26
    assert stored.failures == ("boom",)
    assert stored.ok is False


async def test_a_clean_sync_reports_no_failure(professions: ProfessionRepo) -> None:
    now = utcnow()

    await professions.record_sync(SyncReport(now, now, 25, 0, 104, 1628, 589, ()))

    stored = await professions.last_sync()
    assert stored is not None
    assert stored.failures == ()
    assert stored.ok is True


async def test_counts_describe_what_is_stored(professions: ProfessionRepo) -> None:
    await _seed(professions)

    assert await professions.counts() == (3, 3, 3, 2)
