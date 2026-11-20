"""The daily sync, from canned API responses all the way into the database.

Exercises the client, the sync and the repository together: the three only make sense as a
whole, and the shapes below are trimmed copies of what the live API answered.
"""

from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest

from api import ForeverApiError, ForeverClient
from bot.professions import sync_professions
from config import ProfessionCatalog, Settings
from db import ProfessionRepo
from tests.fakes import FakeResponse, FakeSession, as_session

if TYPE_CHECKING:
    from bot.client import GuildBot

GUILD_SLUG = "ah-sheep-here-wego-again"
ROSTER_PATH = f"/data/wow/guild/{GUILD_SLUG}/roster"


def _character(name: str, surname: str, level: int, rank: int = 3) -> dict[str, object]:
    return {
        "character": {
            "id": abs(hash(name)) % 100000,
            "name": name,
            "surname": surname,
            "slug": f"{name}-{surname}".lower(),
            "level": level,
            "playable_class": {"id": 5},
        },
        "rank": rank,
    }


def _professions(*entries: tuple[int, str, int, int, list[tuple[int, str]]]) -> dict[str, object]:
    """A professions payload: (id, name, skill, cap, [(recipe id, English name)])."""
    return {
        "primaries": [
            {
                "profession": {"id": blizzard_id, "name": name},
                "tiers": [
                    {
                        "skill_points": skill,
                        "max_skill_points": cap,
                        "known_recipes": [{"id": rid, "name": rname} for rid, rname in recipes],
                    }
                ],
            }
            for blizzard_id, name, skill, cap, recipes in entries
        ],
        "secondaries": [],
    }


def _recipe(name_en: str, name_fr: str) -> dict[str, object]:
    return {"name": {"en_GB": name_en, "fr_FR": name_fr}}


class StubBot:
    """What sync_professions asks of the bot, and nothing else."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        catalog: ProfessionCatalog,
        session: FakeSession,
    ) -> None:
        self.db = connection
        self.professions = catalog
        self.settings = Settings.model_validate(
            {
                "discord_token": "t",
                "guild_id": 1,
                "gm_role_id": 2,
                "officer_role_id": 3,
                "blizzard_client_id": "id",
                "blizzard_client_secret": "secret",
            }
        )
        self.forever = ForeverClient(
            "eu", "id", "secret", as_session(session), retry_seconds=0.001
        )


def _bot(
    connection: aiosqlite.Connection,
    catalog: ProfessionCatalog,
    session: FakeSession,
) -> "GuildBot":
    return cast("GuildBot", StubBot(connection, catalog, session))


@pytest.fixture
def session() -> FakeSession:
    """One tailor at 245/300 knowing one recipe, plus a level 2 nobody can see."""
    return FakeSession(
        {
            ROSTER_PATH: FakeResponse(
                body={
                    "members": [
                        _character("Rka", "Kamechki", 60),
                        _character("Bebe", "Lezard", 2, rank=5),
                    ]
                }
            ),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions((197, "Tailoring", 245, 300, [(6586, "Red Mageweave Vest")]))
            ),
            "/data/wow/recipe/6586": FakeResponse(
                body=_recipe("Red Mageweave Vest", "Gilet rouge en tisse-mage")
            ),
        }
    )


# --- the happy path -------------------------------------------------------------------


async def test_a_sync_mirrors_the_roster_its_professions_and_its_recipes(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    session: FakeSession,
) -> None:
    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert (report.characters, report.professions, report.recipe_links) == (1, 1, 1)
    assert report.recipes_fetched == 1
    assert report.ok
    assert await professions.counts() == (2, 1, 1, 1)


async def test_the_sync_is_recorded_so_the_directory_can_date_itself(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    session: FakeSession,
) -> None:
    await sync_professions(_bot(connection, professions_catalog, session))

    stored = await professions.last_sync()
    assert stored is not None
    assert stored.characters == 1


async def test_recipes_are_searchable_in_french_after_a_sync(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    session: FakeSession,
) -> None:
    await sync_professions(_bot(connection, professions_catalog, session))

    found = await professions.artisans_for("gilet rouge")

    assert [artisan.character for artisan in found] == ["Rka-Kamechki"]


# --- what the API will not answer -----------------------------------------------------


async def test_a_character_below_level_ten_is_never_asked_about(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    session: FakeSession,
) -> None:
    """Every profile endpoint answers 404 below level 10, so asking only burns quota."""
    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert report.skipped == 1
    assert "/profile/wow/character/bebe-lezard/professions" not in session.requests


async def test_a_character_the_api_does_not_publish_yet_is_skipped(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    """Level 60 but never logged out: a 404 is normal, not a failure."""
    session = FakeSession(
        {ROSTER_PATH: FakeResponse(body={"members": [_character("Neuf", "Venu", 60)]})}
    )

    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert (report.characters, report.skipped) == (0, 1)
    assert report.ok


async def test_an_unknown_guild_names_the_setting_to_fix(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    session = FakeSession({})

    with pytest.raises(ForeverApiError, match="GUILD_NAME"):
        await sync_professions(_bot(connection, professions_catalog, session))


async def test_a_character_whose_call_fails_is_reported_not_emptied(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    session: FakeSession,
) -> None:
    """Yesterday's professions beat none at all, so a failure leaves the rows alone."""
    await sync_professions(_bot(connection, professions_catalog, session))
    broken = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(status=500),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, broken))

    assert report.characters == 0
    assert len(report.failures) == 1
    assert "Rka-Kamechki" in report.failures[0]
    assert len(await professions.professions_of("rka-kamechki")) == 1


async def test_one_failure_does_not_stop_the_others(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    session = FakeSession(
        {
            ROSTER_PATH: FakeResponse(
                body={
                    "members": [
                        _character("Bon", "Perso", 60),
                        _character("Casse", "Perso", 60),
                    ]
                }
            ),
            "/profile/wow/character/bon-perso/professions": FakeResponse(
                body=_professions((197, "Tailoring", 300, 300, []))
            ),
            "/profile/wow/character/casse-perso/professions": FakeResponse(status=500),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert report.characters == 1
    assert len(report.failures) == 1


# --- departures, ignored professions, unknown ids -------------------------------------


async def test_a_character_who_left_the_guild_is_dropped(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    session: FakeSession,
) -> None:
    await sync_professions(_bot(connection, professions_catalog, session))
    smaller = FakeSession(
        {ROSTER_PATH: FakeResponse(body={"members": [_character("Bebe", "Lezard", 2, rank=5)]})}
    )

    await sync_professions(_bot(connection, professions_catalog, smaller))

    assert [c.slug for c in await professions.roster()] == ["bebe-lezard"]
    assert await professions.artisans_for("gilet rouge") == []


async def test_an_ignored_profession_is_never_stored(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """First aid is in the payload; the guild does not track it."""
    session = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions(
                    (197, "Tailoring", 245, 300, []),
                    (129, "First Aid", 300, 300, [(1838, "Linen Bandage")]),
                )
            ),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert report.professions == 1
    assert [p.blizzard_id for p in await professions.professions_of("rka-kamechki")] == [197]
    assert await professions.artisans_for("Linen Bandage") == []


async def test_a_profession_nobody_configured_is_still_stored(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A profession Blizzard adds must reach the directory under its API name, and be logged."""
    session = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions((999, "Jewelcrafting", 150, 150, []))
            ),
        }
    )

    await sync_professions(_bot(connection, professions_catalog, session))

    stored = await professions.professions_of("rka-kamechki")
    assert [(p.blizzard_id, p.api_name) for p in stored] == [(999, "Jewelcrafting")]
    assert "999" in caplog.text


# --- the recipe dictionary ------------------------------------------------------------


async def test_a_second_sync_fetches_no_recipe_again(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    session: FakeSession,
) -> None:
    """This is what keeps a daily sync at 26 requests instead of 525."""
    await sync_professions(_bot(connection, professions_catalog, session))
    again = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions((197, "Tailoring", 245, 300, [(6586, "Red Mageweave Vest")]))
            ),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, again))

    assert report.recipes_fetched == 0
    assert not any(path.startswith("/data/wow/recipe/") for path in again.requests)


async def test_a_recipe_that_cannot_be_named_stays_searchable_in_english(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
    professions: ProfessionRepo,
) -> None:
    """The static call is the only source of French; losing it must not lose the feature."""
    session = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions((197, "Tailoring", 245, 300, [(6586, "Red Mageweave Vest")]))
            ),
            "/data/wow/recipe/6586": FakeResponse(status=500),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert report.recipes_fetched == 0
    assert len(report.failures) == 1
    assert "anglais" in report.failures[0]
    assert len(await professions.artisans_for("Red Mageweave Vest")) == 1


async def test_a_recipe_the_static_namespace_does_not_know_is_not_a_failure(
    connection: aiosqlite.Connection,
    professions_catalog: ProfessionCatalog,
) -> None:
    session = FakeSession(
        {
            ROSTER_PATH: FakeResponse(body={"members": [_character("Rka", "Kamechki", 60)]}),
            "/profile/wow/character/rka-kamechki/professions": FakeResponse(
                body=_professions((197, "Tailoring", 245, 300, [(42, "Brand New Thing")]))
            ),
        }
    )

    report = await sync_professions(_bot(connection, professions_catalog, session))

    assert report.recipes_fetched == 0
    assert report.ok
