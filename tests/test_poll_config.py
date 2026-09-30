"""Validation of the poll definitions."""

import pytest
from pydantic import ValidationError

from config import PollCatalog
from config.polls import (
    CUSTOM_ID_LIMIT,
    OPTION_LABEL_LIMIT,
    REACTIONS_PER_MESSAGE,
    PollDefinition,
    build_close_custom_id,
)


def _poll(**overrides: object) -> dict[str, object]:
    """A valid definition, before the overrides under test."""
    return {
        "key": "faction",
        "title": "Quelle faction ?",
        "options": [{"key": "alliance", "label": "Alliance", "emoji": "🔵"}],
    } | overrides


def test_the_shipped_file_is_valid(catalog: PollCatalog) -> None:
    """Guards against a typo in polls.toml reaching startup."""
    assert catalog.keys == ["faction", "royaume", "skyborne"]


def test_the_faction_poll_offers_the_two_factions_and_accepts_both(
    catalog: PollCatalog,
) -> None:
    """ "Peu importe" was dropped: backing both factions now says the same thing."""
    faction = catalog.get("faction")
    assert faction is not None
    assert [o.key for o in faction.options] == ["alliance", "horde"]
    assert faction.multiple


def test_only_the_faction_poll_accepts_several_answers(catalog: PollCatalog) -> None:
    """A realm type or a Skyborne answer is a single choice; nothing else should drift."""
    assert [p.key for p in catalog.polls if p.multiple] == ["faction"]


def test_option_pairs_keep_the_configured_order() -> None:
    definition = PollDefinition.model_validate(
        _poll(
            options=[
                {"key": "b", "label": "B", "emoji": "🅱️"},
                {"key": "a", "label": "A", "emoji": "🅰️"},
            ]
        )
    )

    assert definition.option_pairs == [("b", "B"), ("a", "A")]


def test_description_loses_its_trailing_newline() -> None:
    definition = PollDefinition.model_validate(_poll(description="Texte.\n"))

    assert definition.description == "Texte."


@pytest.mark.parametrize("key", ["Faction", "la clé", "faction!", ""])
def test_a_key_must_be_a_slug(key: str) -> None:
    """Keys end up in custom_ids matched by a regex; anything else breaks dispatch."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(key=key))


def test_an_option_label_is_capped_at_the_discord_limit() -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A" * (OPTION_LABEL_LIMIT + 1), "emoji": "🔵"}])
        )


def test_a_poll_needs_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=[]))


def test_a_poll_cannot_exceed_the_reaction_limit_of_a_message() -> None:
    """A message holds 20 distinct reactions, and a reaction is how a vote is cast."""
    options = [
        {"key": f"o{i}", "label": f"Option {i}", "emoji": f"{i}"}
        for i in range(REACTIONS_PER_MESSAGE + 1)
    ]

    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=options))


def test_duplicate_option_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate option keys"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵"},
                    {"key": "a", "label": "Autre", "emoji": "🔴"},
                ]
            )
        )


def test_two_options_cannot_share_an_emoji() -> None:
    """The emoji is the ballot: sharing one makes a reaction impossible to attribute."""
    with pytest.raises(ValidationError, match="duplicate emojis"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵"},
                    {"key": "b", "label": "B", "emoji": "🔵"},
                ]
            )
        )


def test_two_options_cannot_share_an_icon() -> None:
    with pytest.raises(ValidationError, match="duplicate emojis"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵", "icon": "alliance"},
                    {"key": "b", "label": "B", "emoji": "🔴", "icon": "alliance"},
                ]
            )
        )


def test_an_option_without_an_emoji_is_rejected() -> None:
    """Without one there is nothing to react with, so the option could never be picked."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=[{"key": "a", "label": "A"}]))


@pytest.mark.parametrize("icon", ["a", "trop-de-tirets", "a" * 33, "accentué"])
def test_an_icon_must_be_a_valid_discord_emoji_name(icon: str) -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A", "emoji": "🔵", "icon": icon}])
        )


def test_duplicate_poll_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate poll keys"):
        PollCatalog.model_validate({"polls": [_poll(), _poll(title="Encore ?")]})


def test_unknown_fields_are_rejected() -> None:
    """A misspelled field would otherwise be silently ignored."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(titre="Quelle faction ?"))


def test_every_closing_custom_id_fits_within_the_api_limit(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        assert len(build_close_custom_id(definition.key)) <= CUSTOM_ID_LIMIT


def test_get_returns_none_for_an_unknown_key(catalog: PollCatalog) -> None:
    assert catalog.get("inconnu") is None
