"""professions.toml, as it is actually shipped."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import ProfessionCatalog, ProfessionKind, load_professions

# Read off the live API on 20 November 2026, on the whole roster.
LIVE_IDS = {171, 164, 333, 202, 182, 165, 186, 393, 197, 185, 129, 356}


def test_the_twelve_vanilla_professions_are_configured(
    professions_catalog: ProfessionCatalog,
) -> None:
    assert len(professions_catalog.professions) == 12


def test_every_id_the_api_answered_with_is_known(
    professions_catalog: ProfessionCatalog,
) -> None:
    """The directory falls back to the API name for an unknown id, but should never need to."""
    assert set(professions_catalog.blizzard_ids) == LIVE_IDS


def test_the_three_secondaries_are_marked_as_such(
    professions_catalog: ProfessionCatalog,
) -> None:
    secondaries = [
        profession.key
        for profession in professions_catalog.professions
        if profession.kind is ProfessionKind.SECONDARY
    ]

    assert secondaries == ["cooking", "first_aid", "fishing"]


def test_lookup_by_key_and_by_api_id_agree(professions_catalog: ProfessionCatalog) -> None:
    by_key = professions_catalog.get("tailoring")
    by_id = professions_catalog.by_id(197)

    assert by_key is not None
    assert by_key == by_id
    assert by_key.name == "Couture"


def test_an_unknown_lookup_is_none(professions_catalog: ProfessionCatalog) -> None:
    assert professions_catalog.get("woodworking") is None
    assert professions_catalog.by_id(999) is None


def test_the_label_carries_the_emoji(professions_catalog: ProfessionCatalog) -> None:
    alchemy = professions_catalog.get("alchemy")

    assert alchemy is not None
    assert alchemy.label.endswith("Alchimie")
    assert alchemy.label != alchemy.name


def test_file_order_is_the_directory_order(professions_catalog: ProfessionCatalog) -> None:
    assert professions_catalog.order_of(171) == 0
    assert professions_catalog.order_of(356) == 11


def test_an_unknown_id_sorts_last(professions_catalog: ProfessionCatalog) -> None:
    """A profession Blizzard adds still appears, after the configured ones."""
    assert professions_catalog.order_of(999) == len(professions_catalog.professions)


def test_duplicate_keys_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate profession keys"):
        ProfessionCatalog.model_validate(
            {
                "professions": [
                    {"key": "a", "blizzard_id": 1, "name": "A", "kind": "primary"},
                    {"key": "a", "blizzard_id": 2, "name": "B", "kind": "primary"},
                ]
            }
        )


def test_duplicate_api_ids_are_refused() -> None:
    """Two professions on one id would make by_id() answer the wrong one."""
    with pytest.raises(ValidationError, match="duplicate blizzard ids"):
        ProfessionCatalog.model_validate(
            {
                "professions": [
                    {"key": "a", "blizzard_id": 1, "name": "A", "kind": "primary"},
                    {"key": "b", "blizzard_id": 1, "name": "B", "kind": "secondary"},
                ]
            }
        )


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProfessionCatalog.model_validate(
            {"professions": [{"key": "a", "blizzard_id": 1, "name": "A", "kind": "tertiary"}]}
        )


def test_an_unknown_field_is_refused() -> None:
    """extra="forbid", so a typo in the file fails at startup rather than being ignored."""
    with pytest.raises(ValidationError):
        ProfessionCatalog.model_validate(
            {
                "professions": [
                    {
                        "key": "a",
                        "blizzard_id": 1,
                        "name": "A",
                        "kind": "primary",
                        "colour": "#ffffff",
                    }
                ]
            }
        )


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_professions(tmp_path / "nope.toml")
