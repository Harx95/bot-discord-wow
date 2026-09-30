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
OPTION_LABEL_LIMIT = 80
# Votes are cast by reacting, and a message holds 20 distinct reactions at most. This is
# lower than the 25 components a message could carry, and it is what caps a poll now.
REACTIONS_PER_MESSAGE = 20
CUSTOM_ID_LIMIT = 100
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096

KEY_PATTERN = r"^[a-z0-9_]+$"
KEY_MAX_LENGTH = 20

# Discord's own rule for a custom emoji name, which is how an option names its icon.
EMOJI_NAME_PATTERN = r"^[A-Za-z0-9_]{2,32}$"

# U+FE0F asks for the coloured rendering of a character that also has a text form, as in
# "🛡️". Discord does not always echo it back on a reaction, so it is dropped on both sides
# of every comparison rather than trusted.
VARIATION_SELECTOR = "️"


def normalise_ballot(ballot: str) -> str:
    """The comparable form of a ballot: a custom emoji name, or a bare unicode character."""
    return ballot.replace(VARIATION_SELECTOR, "")


CLOSE_CUSTOM_ID_PREFIX = "poll:close"
# The cancel button carries no state: it only puts the confirmation away.
CANCEL_CLOSE_CUSTOM_ID = "poll:nc"


def build_close_custom_id(poll_key: str) -> str:
    """The custom_id of the button confirming that a poll is closed for good."""
    return f"{CLOSE_CUSTOM_ID_PREFIX}:{poll_key}"


class OptionDefinition(BaseModel):
    """One choice offered by a poll.

    The emoji is the ballot, not decoration: it is what members react with, so every option
    needs one and no two options of a poll may share it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    label: str = Field(min_length=1, max_length=OPTION_LABEL_LIMIT)
    # A unicode emoji, used as the ballot on its own when no icon is configured.
    emoji: str = Field(min_length=1)
    # Name of a server emoji to use instead. Falls back to the unicode one until it exists.
    icon: str | None = Field(default=None, pattern=EMOJI_NAME_PATTERN)

    @property
    def ballot(self) -> str:
        """What identifies this option among the reactions: icon name, else unicode emoji.

        Custom emojis are matched by name rather than by id, so re-uploading one to the
        server keeps every recorded vote attached to its option.
        """
        return normalise_ballot(self.icon or self.emoji)


class PollDefinition(BaseModel):
    """A poll as configured, before it exists in the database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    title: str = Field(min_length=1, max_length=EMBED_TITLE_LIMIT)
    description: str = Field(default="", max_length=EMBED_DESCRIPTION_LIMIT)
    # When true a member may back several options at once, by reacting to each of them.
    multiple: bool = False
    options: tuple[OptionDefinition, ...] = Field(min_length=1, max_length=REACTIONS_PER_MESSAGE)

    @field_validator("description")
    @classmethod
    def _strip(cls, value: str) -> str:
        """TOML multi-line strings keep their trailing newline."""
        return value.strip()

    @model_validator(mode="after")
    def _check_options(self) -> Self:
        """Option keys and ballots must be unique, and the close custom_id must fit."""
        keys = [option.key for option in self.options]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"duplicate option keys in poll {self.key!r}: {sorted(duplicates)}")

        # Two options sharing an emoji would make a reaction impossible to attribute.
        ballots = [option.ballot for option in self.options]
        shared = {ballot for ballot in ballots if ballots.count(ballot) > 1}
        if shared:
            raise ValueError(f"duplicate emojis in poll {self.key!r}: {sorted(shared)}")

        closing = build_close_custom_id(self.key)
        if len(closing) > CUSTOM_ID_LIMIT:
            raise ValueError(f"custom_id too long ({len(closing)} > {CUSTOM_ID_LIMIT})")

        return self

    def option(self, key: str) -> OptionDefinition | None:
        """Look up one option by key."""
        return next((option for option in self.options if option.key == key), None)

    def option_for_ballot(self, ballot: str) -> OptionDefinition | None:
        """The option a reaction stands for, or None when the emoji is not on the ballot.

        `ballot` is the custom emoji's name, or the unicode character itself.
        """
        wanted = normalise_ballot(ballot)
        return next((option for option in self.options if option.ballot == wanted), None)

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
