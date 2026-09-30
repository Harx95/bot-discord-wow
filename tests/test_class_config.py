"""Validation of the class definitions."""

import pytest
from pydantic import ValidationError

from config import ClassCatalog, Slot
from config.classes import (
    ClassDefinition,
    build_class_button_custom_id,
    build_role_button_custom_id,
)
from config.polls import CUSTOM_ID_LIMIT

EXPECTED_CLASSES = 9


def _catalog(**overrides: object) -> dict[str, object]:
    """A valid catalog, before the overrides under test."""
    return {
        "roles": [{"key": "tank", "label": "Tank"}, {"key": "dps", "label": "DPS"}],
        "classes": [{"key": "mage", "name": "Mage", "colour": "#69CCF0", "roles": ["dps"]}],
    } | overrides


def test_the_shipped_file_is_valid(classes: ClassCatalog) -> None:
    """Guards against a typo in classes.toml reaching startup."""
    assert len(classes.classes) == EXPECTED_CLASSES
    assert [role.key for role in classes.roles] == ["tank", "heal", "dps"]


def test_mage_is_light_blue(classes: ClassCatalog) -> None:
    """The acceptance criterion of the step: voting mage turns the nickname light blue."""
    mage = classes.get("mage")

    assert mage is not None
    assert mage.colour_value == 0x69CCF0


def test_roles_are_filtered_per_class(classes: ClassCatalog) -> None:
    assert [r.key for r in classes.roles_of("mage")] == ["dps"]
    assert [r.key for r in classes.roles_of("druide")] == ["tank", "heal", "dps"]


def test_roles_of_keeps_the_catalog_order_not_the_class_order(classes: ClassCatalog) -> None:
    """Tank, heal then DPS everywhere, whatever order a class lists them in."""
    assert [r.key for r in classes.roles_of("pretre")] == ["heal", "dps"]


def test_roles_of_an_unknown_class_is_empty(classes: ClassCatalog) -> None:
    assert classes.roles_of("inconnu") == []


def test_every_class_can_fill_at_least_one_role(classes: ClassCatalog) -> None:
    for klass in classes.classes:
        assert classes.roles_of(klass.key), f"{klass.key} has no usable role"


@pytest.mark.parametrize("colour", ["69CCF0", "#69CCF", "#GGGGGG", "bleu", "#69ccf0ff"])
def test_a_colour_must_be_a_six_digit_hex(colour: str) -> None:
    with pytest.raises(ValidationError):
        ClassDefinition.model_validate(
            {"key": "mage", "name": "Mage", "colour": colour, "roles": ["dps"]}
        )


def test_lowercase_hex_is_accepted() -> None:
    klass = ClassDefinition.model_validate(
        {"key": "mage", "name": "Mage", "colour": "#69ccf0", "roles": ["dps"]}
    )

    assert klass.colour_value == 0x69CCF0


def test_a_class_referencing_an_unknown_role_is_rejected() -> None:
    """Catches a role renamed in one place and not the other."""
    with pytest.raises(ValidationError, match="unknown roles"):
        ClassCatalog.model_validate(
            _catalog(
                classes=[{"key": "mage", "name": "Mage", "colour": "#69CCF0", "roles": ["heal"]}]
            )
        )


def test_a_class_needs_at_least_one_role() -> None:
    with pytest.raises(ValidationError):
        ClassDefinition.model_validate(
            {"key": "mage", "name": "Mage", "colour": "#69CCF0", "roles": []}
        )


def test_duplicate_roles_within_a_class_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate roles"):
        ClassDefinition.model_validate(
            {"key": "mage", "name": "Mage", "colour": "#69CCF0", "roles": ["dps", "dps"]}
        )


def test_duplicate_class_keys_are_rejected() -> None:
    twice = [
        {"key": "mage", "name": "Mage", "colour": "#69CCF0", "roles": ["dps"]},
        {"key": "mage", "name": "Mage rouge", "colour": "#FF0000", "roles": ["dps"]},
    ]
    with pytest.raises(ValidationError, match="duplicate class keys"):
        ClassCatalog.model_validate(_catalog(classes=twice))


def test_more_classes_than_a_board_message_holds_is_rejected() -> None:
    """One button per class on a board message: 25 components maximum."""
    many = [
        {"key": f"c{i}", "name": f"Classe {i}", "colour": "#FFFFFF", "roles": ["dps"]}
        for i in range(26)
    ]
    with pytest.raises(ValidationError):
        ClassCatalog.model_validate(_catalog(classes=many))


def test_every_custom_id_fits_within_the_api_limit(classes: ClassCatalog) -> None:
    for slot in Slot:
        for klass in classes.classes:
            assert len(build_class_button_custom_id(slot, klass.key)) <= CUSTOM_ID_LIMIT
            for role in classes.roles_of(klass.key):
                custom_id = build_role_button_custom_id(slot, klass.key, role.key)
                assert len(custom_id) <= CUSTOM_ID_LIMIT


def test_the_two_slots_produce_different_custom_ids() -> None:
    """Otherwise a click on one board would be handled as a click on the other."""
    main = build_class_button_custom_id(Slot.MAIN, "mage")
    alternate = build_class_button_custom_id(Slot.ALTERNATE, "mage")

    assert main != alternate


def test_max_alternates_leaves_room_for_the_main_character(classes: ClassCatalog) -> None:
    assert classes.max_alternates == classes.max_choices - 1
    assert classes.max_alternates == 2


def test_max_choices_defaults_to_three(classes: ClassCatalog) -> None:
    assert classes.max_choices == 3


def test_every_class_and_role_has_a_fallback_emoji(classes: ClassCatalog) -> None:
    """Shown until the real icons are uploaded, so the message is never bare."""
    assert all(klass.emoji for klass in classes.classes)
    assert all(role.emoji for role in classes.roles)


def test_icon_names_are_derived_from_the_keys(classes: ClassCatalog) -> None:
    mage = classes.get("mage")

    assert mage is not None
    assert mage.icon_name == "classe_mage"
    assert classes.roles[0].icon_name == "role_tank"


@pytest.mark.parametrize("value", [0, 1, 6])
def test_max_choices_outside_the_allowed_range_is_rejected(value: int) -> None:
    """One is refused too: the alternates board would have nothing to hold."""
    with pytest.raises(ValidationError):
        ClassCatalog.model_validate(_catalog(max_choices=value))
