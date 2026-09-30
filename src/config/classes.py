"""Class and raid-role definitions, read from TOML and validated by pydantic."""

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.polls import CUSTOM_ID_LIMIT, KEY_MAX_LENGTH, KEY_PATTERN

# Discord API limits.
SELECT_OPTIONS_LIMIT = 25
SELECT_LABEL_LIMIT = 100
ROLE_NAME_LIMIT = 100

COLOUR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

# A board message carries one button per class and nothing else, so the whole component
# budget of a message is available: 25 buttons over 5 rows.
BUTTONS_PER_VIEW = 25
BUTTONS_PER_ROW = 5

# One main character, plus at least one alternate: below two the second board would have
# nothing to hold.
MIN_CHOICES = 2
MAX_CHOICES_LIMIT = 5

CLASS_BUTTON_PREFIX = "cls"
ROLE_BUTTON_PREFIX = "cls:r"

# Emoji names the bot uploads to its application, one per class and per role.
EMOJI_CLASS_PREFIX = "classe"
EMOJI_ROLE_PREFIX = "role"


class Slot(StrEnum):
    """Which of the two boards a button belongs to.

    The slot travels in the custom_id: the same class appears on both boards, so a click
    alone does not say whether it means "this is my main" or "I might also play this".
    """

    MAIN = "m"
    ALTERNATE = "a"


def build_class_button_custom_id(slot: Slot, class_key: str) -> str:
    """custom_id of a class button on one of the two board messages."""
    return f"{CLASS_BUTTON_PREFIX}:{slot}:{class_key}"


def build_role_button_custom_id(slot: Slot, class_key: str, role_key: str) -> str:
    """custom_id of a role button, shown after a class with several roles was picked."""
    return f"{ROLE_BUTTON_PREFIX}:{slot}:{class_key}:{role_key}"


def emoji_name(kind: str, key: str) -> str:
    """Application emoji name for a class or role icon."""
    return f"{kind}_{key}"


class RoleDefinition(BaseModel):
    """A raid role: tank, healer or damage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    label: str = Field(min_length=1, max_length=SELECT_LABEL_LIMIT)
    # Shown until the matching icon is uploaded as an application emoji.
    emoji: str | None = None

    @property
    def icon_name(self) -> str:
        """Name of the application emoji holding this role's icon."""
        return emoji_name(EMOJI_ROLE_PREFIX, self.key)


class ClassDefinition(BaseModel):
    """A playable class and the roles it can fill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    name: str = Field(min_length=1, max_length=ROLE_NAME_LIMIT)
    colour: str = Field(pattern=COLOUR_PATTERN)
    roles: tuple[str, ...] = Field(min_length=1)
    # Shown until the matching icon is uploaded as an application emoji.
    emoji: str | None = None

    @property
    def icon_name(self) -> str:
        """Name of the application emoji holding this class's icon."""
        return emoji_name(EMOJI_CLASS_PREFIX, self.key)

    @field_validator("roles")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate roles: {value}")
        return value

    @property
    def colour_value(self) -> int:
        """The colour as the integer Discord expects."""
        return int(self.colour.removeprefix("#"), 16)


class ClassCatalog(BaseModel):
    """Every configured class and raid role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    roles: tuple[RoleDefinition, ...] = Field(min_length=1, max_length=SELECT_OPTIONS_LIMIT)
    # One button per class on each board message, which holds nothing else.
    classes: tuple[ClassDefinition, ...] = Field(min_length=1, max_length=BUTTONS_PER_VIEW)
    # Counting the main character: 3 means one main plus two alternates.
    max_choices: int = Field(default=3, ge=MIN_CHOICES, le=MAX_CHOICES_LIMIT)

    @model_validator(mode="after")
    def _check(self) -> Self:
        """Keys must be unique, roles must exist, and custom_ids must fit."""
        role_keys = [role.key for role in self.roles]
        if len(set(role_keys)) != len(role_keys):
            raise ValueError(f"duplicate role keys: {sorted(role_keys)}")

        class_keys = [klass.key for klass in self.classes]
        if len(set(class_keys)) != len(class_keys):
            raise ValueError(f"duplicate class keys: {sorted(class_keys)}")

        known = set(role_keys)
        for klass in self.classes:
            unknown = set(klass.roles) - known
            if unknown:
                raise ValueError(f"class {klass.key!r} references unknown roles: {sorted(unknown)}")

            for slot in Slot:
                for role_key in klass.roles:
                    custom_id = build_role_button_custom_id(slot, klass.key, role_key)
                    if len(custom_id) > CUSTOM_ID_LIMIT:
                        raise ValueError(
                            f"custom_id too long ({len(custom_id)} > {CUSTOM_ID_LIMIT})"
                        )

        return self

    @property
    def max_alternates(self) -> int:
        """How many classes a member may list besides their main character."""
        return self.max_choices - 1

    def get(self, key: str) -> ClassDefinition | None:
        """Look up one class by key."""
        return next((klass for klass in self.classes if klass.key == key), None)

    def role(self, key: str) -> RoleDefinition | None:
        """Look up one raid role by key."""
        return next((role for role in self.roles if role.key == key), None)

    def roles_of(self, class_key: str) -> list[RoleDefinition]:
        """The raid roles a class can fill, in configured order."""
        klass = self.get(class_key)
        if klass is None:
            return []
        return [role for role in self.roles if role.key in klass.roles]

    @property
    def class_keys(self) -> list[str]:
        """Every configured class key, in file order."""
        return [klass.key for klass in self.classes]


def load_classes(path: Path) -> ClassCatalog:
    """Read and validate the class definitions."""
    with path.open("rb") as handle:
        return ClassCatalog.model_validate(tomllib.load(handle))
