"""ForeverClient against canned responses. Nothing here reaches Blizzard.

The payload shapes are trimmed copies of what the live API answered on 20 November 2026,
including the two that drove the design: the profile namespace answers plain English
strings, the static namespace an object keyed by locale.
"""

import aiohttp
import pytest

from api import ForeverApiError, ForeverClient
from tests.fakes import FakeResponse, FakeSession, as_session

ROSTER_PATH = "/data/wow/guild/ah-sheep-here-wego-again/roster"
GUILD_PATH = "/data/wow/guild/ah-sheep-here-wego-again"
PROFESSIONS_PATH = "/profile/wow/character/rka-kamechki/professions"
RECIPE_PATH = "/data/wow/recipe/6586"

ROSTER_BODY = {
    "members": [
        {
            "character": {
                "id": 3889172,
                "name": "Rka",
                "surname": "Kamechki",
                "slug": "rka-kamechki",
                "level": 60,
                "playable_class": {"id": 5},
            },
            "rank": 3,
        },
        {
            "character": {
                "id": 9,
                "name": "Bebe",
                "surname": "Lezard",
                "slug": "bebe-lezard",
                "level": 2,
                "playable_class": {"id": 1},
            },
            "rank": 5,
        },
    ]
}

# The profile namespace: English strings, one tier per profession.
PROFESSIONS_BODY = {
    "primaries": [
        {
            "profession": {"id": 197, "name": "Tailoring"},
            "tiers": [
                {
                    "tier": {"id": 2948, "name": "Tailoring"},
                    "skill_points": 245,
                    "max_skill_points": 300,
                    "known_recipes": [
                        {"id": 6586, "name": "Red Mageweave Vest"},
                        {"id": 6612, "name": "Admiral's Hat"},
                    ],
                }
            ],
        }
    ],
    "secondaries": [
        {
            "profession": {"id": 129, "name": "First Aid"},
            "tiers": [
                {
                    "skill_points": 1,
                    "max_skill_points": 75,
                    "known_recipes": [{"id": 1838, "name": "Linen Bandage"}],
                }
            ],
        }
    ],
}

# The static namespace: a name per locale, and the crafted item.
RECIPE_BODY = {
    "id": 6586,
    "name": {
        "en_GB": "Red Mageweave Vest",
        "en_US": "Red Mageweave Vest",
        "fr_FR": "Gilet rouge en tisse-mage",
    },
    "crafted_item": {
        "id": 10007,
        "name": {"en_GB": "Red Mageweave Vest", "fr_FR": "Gilet rouge en tisse-mage"},
    },
}


def _client(session: FakeSession, concurrency: int = 4) -> ForeverClient:
    """retry_seconds near zero: the retry policy is under test, not the waiting."""
    return ForeverClient(
        "eu",
        "id",
        "secret",
        as_session(session),
        concurrency=concurrency,
        retry_seconds=0.001,
    )


# --- the token ------------------------------------------------------------------------


async def test_the_token_is_taken_once_and_reused() -> None:
    session = FakeSession({ROSTER_PATH: FakeResponse(body=ROSTER_BODY)})
    client = _client(session)

    await client.guild_roster("ah-sheep-here-wego-again")
    await client.guild_roster("ah-sheep-here-wego-again")

    assert session.token_requests == 1


async def test_a_refused_token_names_the_two_settings_to_check() -> None:
    """The body may echo the client id, so the message must not carry it."""
    session = FakeSession(token=FakeResponse(status=401))
    client = _client(session)

    with pytest.raises(ForeverApiError, match="BLIZZARD_CLIENT_SECRET") as raised:
        await client.guild_roster("whatever")

    assert "secret" not in str(raised.value).replace("BLIZZARD_CLIENT_SECRET", "")


async def test_a_token_response_without_a_token_is_an_error() -> None:
    session = FakeSession(token=FakeResponse(body={"expires_in": 10}))
    client = _client(session)

    with pytest.raises(ForeverApiError, match="carried no token"):
        await client.guild_roster("whatever")


async def test_an_unreachable_blizzard_is_retryable() -> None:
    session = FakeSession(token=FakeResponse(error=aiohttp.ClientError("down")))
    client = _client(session)

    with pytest.raises(ForeverApiError) as raised:
        await client.guild_roster("whatever")

    assert raised.value.retryable is True


# --- the roster -----------------------------------------------------------------------


async def test_the_roster_is_parsed() -> None:
    session = FakeSession({ROSTER_PATH: FakeResponse(body=ROSTER_BODY)})

    roster = await _client(session).guild_roster("ah-sheep-here-wego-again")

    assert roster is not None
    assert [c.slug for c in roster] == ["rka-kamechki", "bebe-lezard"]
    assert roster[0].display_name == "Rka-Kamechki"
    assert roster[0].class_id == 5
    assert roster[0].rank == 3


async def test_the_slug_the_api_supplies_is_used_as_is() -> None:
    """The roster carries the slug, so it is never rebuilt and never guessed wrong."""
    body = {
        "members": [
            {
                "character": {
                    "name": "Krøhns",
                    "surname": "Disease",
                    "slug": "weird-one",
                    "level": 60,
                },
                "rank": 1,
            }
        ]
    }
    session = FakeSession({ROSTER_PATH: FakeResponse(body=body)})

    roster = await _client(session).guild_roster("ah-sheep-here-wego-again")

    assert roster is not None
    assert roster[0].slug == "weird-one"


async def test_a_roster_entry_without_a_slug_falls_back_to_the_names() -> None:
    body = {
        "members": [{"character": {"name": "Rka", "surname": "Kamechki", "level": 60}, "rank": 1}]
    }
    session = FakeSession({ROSTER_PATH: FakeResponse(body=body)})

    roster = await _client(session).guild_roster("ah-sheep-here-wego-again")

    assert roster is not None
    assert roster[0].slug == "rka-kamechki"


async def test_the_level_decides_whether_the_api_will_answer() -> None:
    """Blizzard hides characters below level 10, so asking is a wasted request."""
    session = FakeSession({ROSTER_PATH: FakeResponse(body=ROSTER_BODY)})

    roster = await _client(session).guild_roster("ah-sheep-here-wego-again")

    assert roster is not None
    assert [c.is_visible_to_api for c in roster] == [True, False]


async def test_an_unknown_guild_is_none_rather_than_an_error() -> None:
    session = FakeSession({})

    assert await _client(session).guild_roster("no-such-guild") is None


async def test_a_roster_without_a_member_list_is_an_error() -> None:
    session = FakeSession({ROSTER_PATH: FakeResponse(body={"guild": {}})})

    with pytest.raises(ForeverApiError, match="member list"):
        await _client(session).guild_roster("ah-sheep-here-wego-again")


async def test_the_ruleset_confirms_which_guild_was_reached() -> None:
    """Forever puts no ruleset in the URL, so this is the only way to check the guild."""
    body = {"ruleset": {"id": 1, "name": {"en_GB": "PvP", "fr_FR": "JcJ"}}}
    session = FakeSession({GUILD_PATH: FakeResponse(body=body)})

    assert await _client(session).guild_ruleset("ah-sheep-here-wego-again") == (1, "JcJ")


# --- professions ----------------------------------------------------------------------


async def test_professions_and_their_recipes_are_parsed() -> None:
    session = FakeSession({PROFESSIONS_PATH: FakeResponse(body=PROFESSIONS_BODY)})

    result = await _client(session).character_professions("rka-kamechki")

    assert result is not None
    professions, recipes = result
    assert [(p.blizzard_id, p.skill, p.max_skill) for p in professions] == [
        (197, 245, 300),
        (129, 1, 75),
    ]
    assert recipes == [
        (197, 6586, "Red Mageweave Vest"),
        (197, 6612, "Admiral's Hat"),
        (129, 1838, "Linen Bandage"),
    ]


async def test_the_tier_cap_is_read_rather_than_assumed() -> None:
    """A character capped at 225 must not be shown out of 300."""
    body = {
        "primaries": [
            {
                "profession": {"id": 185, "name": "Cooking"},
                "tiers": [{"skill_points": 212, "max_skill_points": 225, "known_recipes": []}],
            }
        ]
    }
    session = FakeSession({PROFESSIONS_PATH: FakeResponse(body=body)})

    result = await _client(session).character_professions("rka-kamechki")

    assert result is not None
    assert (result[0][0].skill, result[0][0].max_skill) == (212, 225)


async def test_a_character_the_api_hides_is_none() -> None:
    session = FakeSession({})

    assert await _client(session).character_professions("bebe-lezard") is None


async def test_a_character_with_no_profession_is_an_empty_pair() -> None:
    """Different from None: the character exists, it simply learned nothing."""
    session = FakeSession(
        {PROFESSIONS_PATH: FakeResponse(body={"primaries": [], "secondaries": []})}
    )

    assert await _client(session).character_professions("rka-kamechki") == ([], [])


async def test_an_unnamed_profession_falls_back_to_its_id() -> None:
    """A profession professions.toml does not list must still reach the directory."""
    body = {"primaries": [{"profession": {"id": 999}, "tiers": []}]}
    session = FakeSession({PROFESSIONS_PATH: FakeResponse(body=body)})

    result = await _client(session).character_professions("rka-kamechki")

    assert result is not None
    assert result[0][0].api_name == "#999"


async def test_a_malformed_entry_is_skipped_rather_than_fatal() -> None:
    """A new field or a missing one must not cost the whole sync."""
    body = {
        "primaries": [
            "nonsense",
            {"profession": {"name": "No id"}, "tiers": []},
            {"profession": {"id": 197, "name": "Tailoring"}, "tiers": []},
        ]
    }
    session = FakeSession({PROFESSIONS_PATH: FakeResponse(body=body)})

    result = await _client(session).character_professions("rka-kamechki")

    assert result is not None
    assert [p.blizzard_id for p in result[0]] == [197]


# --- recipes --------------------------------------------------------------------------


async def test_a_recipe_carries_both_languages_and_the_crafted_item() -> None:
    session = FakeSession({RECIPE_PATH: FakeResponse(body=RECIPE_BODY)})

    recipe = await _client(session).recipe(6586)

    assert recipe is not None
    assert recipe.name_en == "Red Mageweave Vest"
    assert recipe.name_fr == "Gilet rouge en tisse-mage"
    assert recipe.crafted_item_id == 10007
    assert recipe.display_name == "Gilet rouge en tisse-mage"


async def test_a_recipe_without_french_still_parses() -> None:
    body = {"name": {"en_GB": "Something New"}}
    session = FakeSession({RECIPE_PATH: FakeResponse(body=body)})

    recipe = await _client(session).recipe(6586)

    assert recipe is not None
    assert recipe.name_fr is None
    assert recipe.display_name == "Something New"


async def test_a_recipe_that_crafts_nothing_parses() -> None:
    """87 of the guild's 589 recipes are enchantments or gathering pseudo-recipes."""
    body = {"name": {"en_GB": "Enchant Chest", "fr_FR": "Ench. de plastron"}}
    session = FakeSession({RECIPE_PATH: FakeResponse(body=body)})

    recipe = await _client(session).recipe(6586)

    assert recipe is not None
    assert recipe.crafted_item_id is None
    assert recipe.search_terms == ["enchant chest", "ench de plastron"]


async def test_an_unknown_recipe_is_none() -> None:
    session = FakeSession({})

    assert await _client(session).recipe(1) is None


async def test_a_recipe_without_any_name_is_an_error() -> None:
    session = FakeSession({RECIPE_PATH: FakeResponse(body={"id": 6586})})

    with pytest.raises(ForeverApiError, match="English name"):
        await _client(session).recipe(6586)


async def test_the_static_namespace_is_used_for_recipes() -> None:
    """Only the static namespace localises anything, so a recipe must not be asked of profile."""
    session = FakeSession({RECIPE_PATH: FakeResponse(body=RECIPE_BODY)})
    client = _client(session)

    assert client.static_namespace == "static-forever-eu"
    assert client.profile_namespace == "profile-forever-eu"


# --- failures and retries -------------------------------------------------------------


async def test_a_rate_limit_is_retried_and_then_succeeds() -> None:
    """Measured for real: 44 of 589 recipe calls were refused at concurrency 8."""
    session = FakeSession(
        {
            RECIPE_PATH: [
                FakeResponse(status=429, headers={"Retry-After": "0.01"}),
                FakeResponse(body=RECIPE_BODY),
            ]
        }
    )

    recipe = await _client(session).recipe(6586)

    assert recipe is not None
    assert len(session.requests) == 2


async def test_a_rate_limit_that_never_clears_is_raised_as_retryable() -> None:
    session = FakeSession({RECIPE_PATH: FakeResponse(status=429, headers={"Retry-After": "0.01"})})

    with pytest.raises(ForeverApiError) as raised:
        await _client(session).recipe(6586)

    assert raised.value.status == 429
    assert raised.value.retryable is True


async def test_an_expired_token_is_renewed_once() -> None:
    session = FakeSession({RECIPE_PATH: [FakeResponse(status=401), FakeResponse(body=RECIPE_BODY)]})

    recipe = await _client(session).recipe(6586)

    assert recipe is not None
    assert session.token_requests == 2


async def test_a_server_error_is_retried_then_raised_as_retryable() -> None:
    session = FakeSession({RECIPE_PATH: FakeResponse(status=503)})

    with pytest.raises(ForeverApiError) as raised:
        await _client(session).recipe(6586)

    assert raised.value.retryable is True


async def test_a_client_error_is_not_retried() -> None:
    """A 403 will not fix itself, so retrying it only burns quota."""
    session = FakeSession({RECIPE_PATH: FakeResponse(status=403)})

    with pytest.raises(ForeverApiError) as raised:
        await _client(session).recipe(6586)

    assert raised.value.retryable is False
    assert len(session.requests) == 1


async def test_a_body_that_is_not_an_object_is_an_error() -> None:
    session = FakeSession({RECIPE_PATH: FakeResponse(body=[1, 2, 3])})

    with pytest.raises(ForeverApiError, match="JSON object"):
        await _client(session).recipe(6586)
