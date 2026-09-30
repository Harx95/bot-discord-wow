"""Poll definitions, read from TOML and validated by pydantic.

Nothing here is hardcoded in the code: the game is not out yet and every label is expected
to change. The limits below are Discord's own, enforced at load time so a typo in the
configuration fails at startup rather than when a command is run.
"""

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Discord API limits.
BUTTON_LABEL_LIMIT = 80
BUTTONS_PER_VIEW = 25
CUSTOM_ID_LIMIT = 100
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096

KEY_PATTERN = r"^[a-z0-9_]+$"
KEY_MAX_LENGTH = 20

# Shared with the buttons so the length checks below match what is actually sent.
VOTE_CUSTOM_ID_PREFIX = "poll:v"
CLOSE_CUSTOM_ID_PREFIX = "poll:close"
# The cancel button carries no state: it only puts the confirmation away.
CANCEL_CLOSE_CUSTOM_ID = "poll:nc"


def build_vote_custom_id(poll_key: str, option_key: str) -> str:
    """The custom_id carrying a vote. All the state a restarted bot needs."""
    return f"{VOTE_CUSTOM_ID_PREFIX}:{poll_key}:{option_key}"


def build_close_custom_id(poll_key: str) -> str:
    """The custom_id of the button confirming that a poll is closed for good."""
    return f"{CLOSE_CUSTOM_ID_PREFIX}:{poll_key}"


class OptionDefinition(BaseModel):
    """One choice offered by a poll."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    label: str = Field(min_length=1, max_length=BUTTON_LABEL_LIMIT)
    emoji: str | None = None


class PollDefinition(BaseModel):
    """A poll as configured, before it exists in the database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    title: str = Field(min_length=1, max_length=EMBED_TITLE_LIMIT)
    description: str = Field(default="", max_length=EMBED_DESCRIPTION_LIMIT)
    options: tuple[OptionDefinition, ...] = Field(min_length=1, max_length=BUTTONS_PER_VIEW)

    @field_validator("description")
    @classmethod
    def _strip(cls, value: str) -> str:
        """TOML multi-line strings keep their trailing newline."""
        return value.strip()

    @model_validator(mode="after")
    def _check_options(self) -> Self:
        """Option keys must be unique, and every custom_id must fit within the API limit."""
        keys = [option.key for option in self.options]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"duplicate option keys in poll {self.key!r}: {sorted(duplicates)}")

        for key in keys:
            custom_id = build_vote_custom_id(self.key, key)
            if len(custom_id) > CUSTOM_ID_LIMIT:
                raise ValueError(f"custom_id too long ({len(custom_id)} > {CUSTOM_ID_LIMIT})")

        closing = build_close_custom_id(self.key)
        if len(closing) > CUSTOM_ID_LIMIT:
            raise ValueError(f"custom_id too long ({len(closing)} > {CUSTOM_ID_LIMIT})")

        return self

    def option(self, key: str) -> OptionDefinition | None:
        """Look up one option by key."""
        return next((option for option in self.options if option.key == key), None)

    @property
    def option_pairs(self) -> list[tuple[str, str]]:
        """(key, label) pairs, in configured order, as PollRepo.create expects them."""
        return [(option.key, option.label) for option in self.options]


class PollCatalog(BaseModel):
    """Every configured poll."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    polls: tuple[PollDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_keys(self) -> Self:
        """Poll keys address polls from commands and from the database; they must be unique."""
        keys = [poll.key for poll in self.polls]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"duplicate poll keys: {sorted(duplicates)}")
        return self

    def get(self, key: str) -> PollDefinition | None:
        """Look up one poll by key."""
        return next((poll for poll in self.polls if poll.key == key), None)

    @property
    def keys(self) -> list[str]:
        """Every configured key, in file order."""
        return [poll.key for poll in self.polls]


def load_catalog(path: Path) -> PollCatalog:
    """Read and validate the poll definitions."""
    with path.open("rb") as handle:
        return PollCatalog.model_validate(tomllib.load(handle))
