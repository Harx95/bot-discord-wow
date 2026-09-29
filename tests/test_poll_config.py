"""Validation of the poll definitions."""

import pytest
from pydantic import ValidationError

from config import PollCatalog
from config.polls import (
    BUTTON_LABEL_LIMIT,
    CUSTOM_ID_LIMIT,
    PollDefinition,
    build_vote_custom_id,
)


def _poll(**overrides: object) -> dict[str, object]:
    """A valid definition, before the overrides under test."""
    return {
        "key": "faction",
        "title": "Quelle faction ?",
        "options": [{"key": "alliance", "label": "Alliance"}],
    } | overrides


def test_the_shipped_file_is_valid(catalog: PollCatalog) -> None:
    """Guards against a typo in polls.toml reaching startup."""
    assert catalog.keys == ["faction", "royaume", "skyborne"]


def test_the_shipped_file_covers_the_three_required_polls(catalog: PollCatalog) -> None:
    faction = catalog.get("faction")
    assert faction is not None
    assert [o.key for o in faction.options] == ["alliance", "horde", "peu_importe"]
    assert catalog.get("skyborne") is not None


def test_option_pairs_keep_the_configured_order() -> None:
    definition = PollDefinition.model_validate(
        _poll(options=[{"key": "b", "label": "B"}, {"key": "a", "label": "A"}])
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


def test_a_button_label_is_capped_at_the_discord_limit() -> None:
    """80 characters for a button, not the 100 of a select menu option."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A" * (BUTTON_LABEL_LIMIT + 1)}])
        )


def test_a_poll_needs_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=[]))


def test_a_poll_cannot_exceed_one_view_of_buttons() -> None:
    options = [{"key": f"o{i}", "label": f"Option {i}"} for i in range(26)]

    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=options))


def test_duplicate_option_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate option keys"):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A"}, {"key": "a", "label": "Autre"}])
        )


def test_duplicate_poll_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate poll keys"):
        PollCatalog.model_validate({"polls": [_poll(), _poll(title="Encore ?")]})


def test_unknown_fields_are_rejected() -> None:
    """A misspelled field would otherwise be silently ignored."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(titre="Quelle faction ?"))


def test_every_custom_id_fits_within_the_api_limit(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        for option in definition.options:
            assert len(build_vote_custom_id(definition.key, option.key)) <= CUSTOM_ID_LIMIT


def test_get_returns_none_for_an_unknown_key(catalog: PollCatalog) -> None:
    assert catalog.get("inconnu") is None
