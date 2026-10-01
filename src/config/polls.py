"""Poll definitions, read from TOML and validated by pydantic.

Nothing here is hardcoded in the code: the game is not out yet and every label is expected
to change. The limits below are Discord's own, enforced at load time so a typo in the
configuration fails at startup rather than when a command is run.
"""

import re
import tomllib
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Discord API limits.
OPTION_LABEL_LIMIT = 80
# Votes are cast by reacting, and a message holds 20 distinct reactions at most. This is
# lower than the 25 components a message could carry, and it is what caps a poll now.
REACTIONS_PER_MESSAGE = 20
# A select menu holds 25 options, which is what caps a poll voted on through a menu.
SELECT_OPTIONS_LIMIT = 25
CUSTOM_ID_LIMIT = 100
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096

KEY_PATTERN = r"^[a-z0-9_]+$"
KEY_MAX_LENGTH = 20

# Discord's own rule for a custom emoji name, which is how an option names its icon.
EMOJI_NAME_PATTERN = r"^[A-Za-z0-9_]{2,32}$"

# What a member-proposed name may contain by default: letters, including accented ones,
# plus the space, the apostrophe and the hyphen, and a letter to start. No digit, no
# punctuation — a guild name is read aloud. Overridable in polls.toml.
# The ranges skip \u00d7 and \u00f7, the multiplication and division signs, which sit
# among the accented letters in Latin-1.
_LETTER = r"A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff"
DEFAULT_NAME_PATTERN = rf"^[{_LETTER}][{_LETTER} '-]*$"

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


# The components of a poll whose options the members write themselves.
PROPOSE_CUSTOM_ID_PREFIX = "poll:add"
VOTE_CUSTOM_ID_PREFIX = "poll:pick"
CLEAR_CUSTOM_ID_PREFIX = "poll:clear"
MODAL_CUSTOM_ID_PREFIX = "poll:name"


def build_close_custom_id(poll_key: str) -> str:
    """The custom_id of the button confirming that a poll is closed for good."""
    return f"{CLOSE_CUSTOM_ID_PREFIX}:{poll_key}"


def build_propose_custom_id(poll_key: str) -> str:
    """The custom_id of the button opening the proposal modal."""
    return f"{PROPOSE_CUSTOM_ID_PREFIX}:{poll_key}"


def build_vote_custom_id(poll_key: str) -> str:
    """The custom_id of the menu a member votes with."""
    return f"{VOTE_CUSTOM_ID_PREFIX}:{poll_key}"


def build_clear_custom_id(poll_key: str) -> str:
    """The custom_id of the button taking every vote of a member back."""
    return f"{CLEAR_CUSTOM_ID_PREFIX}:{poll_key}"


def build_modal_custom_id(poll_key: str) -> str:
    """The custom_id of the proposal modal itself."""
    return f"{MODAL_CUSTOM_ID_PREFIX}:{poll_key}"


def clean_name(raw: str) -> str:
    """A proposal as it will be stored: trimmed, with its inner whitespace collapsed.

    Someone typing two spaces between two words means one, and the label is what the
    duplicate check and the menu both read.
    """
    return " ".join(raw.split())


def slugify(name: str) -> str:
    """The option key of a proposed name: lowercase, unaccented, punctuation folded away.

    Two names that differ only by case or by accents produce the same key, and the
    UNIQUE (poll_id, key) constraint of poll_options then refuses the duplicate. So
    "Les Loups" and "les loups" cannot both be proposed.
    """
    # NFKD splits an accented letter into its base letter and a combining mark, which the
    # ASCII encoding below then drops.
    folded = unicodedata.normalize("NFKD", name)
    stripped = folded.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", stripped)).strip("_")


class ProposalRejection(StrEnum):
    """Why a proposed name cannot be accepted.

    The cause, not the sentence: what a member reads is French and belongs to the view.
    """

    EMPTY = "empty"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    FORBIDDEN = "forbidden"
    UNUSABLE = "unusable"


class ProposalRules(BaseModel):
    """What a poll accepts when its options are written by the members.

    Its presence on a poll is what switches the vote from reactions to a menu: a proposed
    name has no emoji of its own, so it could not be a ballot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # How many names one member may propose.
    max_per_member: int = Field(default=2, ge=1, le=SELECT_OPTIONS_LIMIT)
    # How many names the poll holds at most. A menu cannot show more than 25 options, and
    # paginating would hide a fresh proposal from the people meant to vote on it, so the
    # limit is enforced when proposing instead.
    max_options: int = Field(default=SELECT_OPTIONS_LIMIT, ge=1, le=SELECT_OPTIONS_LIMIT)
    min_length: int = Field(default=3, ge=1, le=OPTION_LABEL_LIMIT)
    max_length: int = Field(default=24, ge=1, le=OPTION_LABEL_LIMIT)
    # What a name may contain, matched against the whole of it. Configurable because the
    # game is not out: the rules on guild names are not known for certain yet.
    pattern: str = DEFAULT_NAME_PATTERN

    @model_validator(mode="after")
    def _check_rules(self) -> Self:
        """The length range must make sense, and the pattern must compile."""
        if self.min_length > self.max_length:
            raise ValueError(
                f"min_length ({self.min_length}) exceeds max_length ({self.max_length})"
            )

        try:
            re.compile(self.pattern)
        except re.error as error:
            raise ValueError(f"invalid proposal pattern: {error}") from error

        return self

    def rejection(self, name: str) -> ProposalRejection | None:
        """Why this name cannot be proposed, or None when it can.

        `name` is expected to have been through clean_name already.
        """
        if not name:
            return ProposalRejection.EMPTY
        if len(name) < self.min_length:
            return ProposalRejection.TOO_SHORT
        if len(name) > self.max_length:
            return ProposalRejection.TOO_LONG
        # re caches compiled patterns, so this does not recompile on every proposal.
        if re.fullmatch(self.pattern, name) is None:
            return ProposalRejection.FORBIDDEN
        # A name made only of characters the slug drops would have no key to be stored under.
        if not slugify(name):
            return ProposalRejection.UNUSABLE
        return None


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
    # When true a member may back several options at once.
    multiple: bool = False
    # How many options one member may back. None means as many as they like, which is the
    # only thing reactions can promise. A cap needs a menu, which enforces it client-side.
    max_votes: int | None = Field(default=None, ge=2, le=SELECT_OPTIONS_LIMIT)
    # Set when the members write the options themselves; the poll then votes by menu and
    # carries no configured option at all.
    proposals: ProposalRules | None = None
    options: tuple[OptionDefinition, ...] = Field(default=(), max_length=REACTIONS_PER_MESSAGE)

    @field_validator("description")
    @classmethod
    def _strip(cls, value: str) -> str:
        """TOML multi-line strings keep their trailing newline."""
        return value.strip()

    @model_validator(mode="after")
    def _check_mode(self) -> Self:
        """A poll either offers configured options or collects them from the members.

        The two cannot be mixed: a configured option needs an emoji to be reacted with, and
        a proposed name has none, so one message cannot carry both ways of voting.
        """
        if self.proposals is None:
            if not self.options:
                raise ValueError(f"poll {self.key!r} has no option and no proposals block")
            if self.max_votes is not None:
                raise ValueError(
                    f"poll {self.key!r} votes by reaction, which cannot cap votes at "
                    f"{self.max_votes}: a reaction can only be removed after the fact"
                )
        else:
            if self.options:
                raise ValueError(
                    f"poll {self.key!r} collects its options from the members, so it must "
                    "not configure any"
                )
            if self.max_votes is not None and self.max_votes > self.proposals.max_options:
                raise ValueError(
                    f"poll {self.key!r} caps votes at {self.max_votes}, more than the "
                    f"{self.proposals.max_options} options it can hold"
                )

        if self.max_votes is not None and not self.multiple:
            raise ValueError(f"poll {self.key!r} caps votes at {self.max_votes} but is single")

        return self

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

        for custom_id in self.custom_ids:
            if len(custom_id) > CUSTOM_ID_LIMIT:
                raise ValueError(f"custom_id too long ({len(custom_id)} > {CUSTOM_ID_LIMIT})")

        return self

    @property
    def custom_ids(self) -> list[str]:
        """Every custom_id this poll's components are built with."""
        return [
            build_close_custom_id(self.key),
            build_propose_custom_id(self.key),
            build_vote_custom_id(self.key),
            build_clear_custom_id(self.key),
            build_modal_custom_id(self.key),
        ]

    @property
    def votes_by_reaction(self) -> bool:
        """Whether the ballot is a reaction on the message rather than a menu under it."""
        return self.proposals is None

    def vote_limit(self, option_count: int) -> int:
        """How many options a member may pick at once, given how many the poll holds now.

        A menu refuses a max_values above the number of options it shows, so the configured
        cap is clamped rather than sent as-is.
        """
        if not self.multiple:
            return 1
        allowed = self.max_votes if self.max_votes is not None else option_count
        return max(1, min(allowed, option_count))

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
