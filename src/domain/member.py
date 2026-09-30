"""Guild member entity and the characters they intend to play."""

from dataclasses import dataclass
from datetime import datetime

FIRST_CHOICE = 1


@dataclass(frozen=True, slots=True)
class Member:
    """A Discord user known to the guild."""

    discord_id: int
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class MemberChoice:
    """One character a member intends to play, at a given rank of preference."""

    member_id: int
    rank: int
    class_key: str
    role_key: str
    created_at: datetime

    @property
    def is_first(self) -> bool:
        """Whether this is the main character, the one earning a Discord role."""
        return self.rank == FIRST_CHOICE


@dataclass(frozen=True, slots=True)
class MainUpdate:
    """The outcome of declaring a main character."""

    choice: MemberChoice
    # False when that exact class and role was already the main: nothing was written.
    changed: bool
    # True when the pair was an alternate and moved up to the main slot.
    promoted: bool
    # The class that was the main before, when a different one replaced it.
    replaced_class_key: str | None


@dataclass(frozen=True, slots=True)
class ClassRole:
    """The Discord role created for a class."""

    class_key: str
    role_id: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ManagedMessage:
    """A message the bot rewrites whenever the data behind it changes."""

    key: str
    channel_id: int
    message_id: int
    updated_at: datetime
