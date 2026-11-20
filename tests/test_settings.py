"""Settings behaviour, and the guild slug the Battle.net API is addressed with."""

from config import Settings

# The fields that have no default, so the real .env is never read in these tests.
REQUIRED = {"discord_token": "token", "guild_id": 1, "gm_role_id": 2, "officer_role_id": 3}


def _settings(guild_name: str | None = None) -> Settings:
    """Settings built from a plain mapping, which keeps the required fields in one place."""
    values = dict(REQUIRED)
    if guild_name is not None:
        values["guild_name"] = guild_name
    return Settings.model_validate(values)


def test_the_guild_is_named_and_tagged_without_any_env_var() -> None:
    settings = _settings()

    assert settings.guild_name == "Ah sheep here wego again"
    assert settings.guild_tag == "ASHWGA"


def test_the_api_slug_lowercases_the_name_and_hyphenates_the_spaces() -> None:
    assert _settings().guild_api_slug == "ah-sheep-here-wego-again"


def test_the_api_slug_drops_apostrophes_and_collapses_whitespace() -> None:
    """Blizzard builds slugs that way, and both apostrophes turn up in guild names."""
    settings = _settings("  Les  Loups d'Ony\u2019x  ")

    assert settings.guild_api_slug == "les-loups-donyx"


def test_the_api_slug_follows_a_renamed_guild() -> None:
    assert _settings("Ah Sheep Here Wego Again").guild_api_slug == "ah-sheep-here-wego-again"


def test_staff_is_the_two_roles() -> None:
    assert _settings().staff_role_ids == frozenset({2, 3})
