"""professions.toml, as it is actually shipped."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import ProfessionCatalog, load_professions

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


def test_the_three_professions_the_guild_does_not_track_are_ignored(
    professions_catalog: ProfessionCatalog,
) -> None:
    """Nearly everyone has them, so they buried the real answers."""
    ignored = [p.key for p in professions_catalog.professions if p.ignored]

    assert ignored == ["cooking", "first_aid", "fishing"]
    assert professions_catalog.ignored_ids == frozenset({185, 129, 356})


def test_the_directory_shows_the_nine_tracked_professions(
    professions_catalog: ProfessionCatalog,
) -> None:
    tracked = professions_catalog.tracked

    assert len(tracked) == 9
    assert not any(profession.ignored for profession in tracked)


def test_an_ignored_profession_is_still_listed_so_it_is_not_taken_for_an_unknown_id(
    professions_catalog: ProfessionCatalog,
) -> None:
    cooking = professions_catalog.by_id(185)

    assert cooking is not None
    assert cooking.name == "Cuisine"


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
    assert professions_catalog.order_of(393) == 8


def test_an_unknown_id_sorts_after_the_tracked_ones(
    professions_catalog: ProfessionCatalog,
) -> None:
    """A profession Blizzard adds still appears, after the ones the guild tracks."""
    assert professions_catalog.order_of(999) == len(professions_catalog.tracked)


def test_duplicate_keys_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate profession keys"):
        ProfessionCatalog.model_validate(
            {
                "professions": [
                    {"key": "a", "blizzard_id": 1, "name": "A"},
                    {"key": "a", "blizzard_id": 2, "name": "B"},
                ]
            }
        )


def test_duplicate_api_ids_are_refused() -> None:
    """Two professions on one id would make by_id() answer the wrong one."""
    with pytest.raises(ValidationError, match="duplicate blizzard ids"):
        ProfessionCatalog.model_validate(
            {
                "professions": [
                    {"key": "a", "blizzard_id": 1, "name": "A"},
                    {"key": "b", "blizzard_id": 1, "name": "B"},
                ]
            }
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
                        "colour": "#ffffff",
                    }
                ]
            }
        )


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_professions(tmp_path / "nope.toml")
