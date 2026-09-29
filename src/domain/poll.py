"""Poll entities."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PollStatus(StrEnum):
    """Lifecycle of a poll. Stored as-is in the database."""

    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Poll:
    """A poll, optionally bound to the message that displays it."""

    id: int
    key: str
    title: str
    status: PollStatus
    channel_id: int | None
    message_id: int | None
    created_at: datetime
    closed_at: datetime | None

    @property
    def is_open(self) -> bool:
        """Whether the poll still accepts votes."""
        return self.status is PollStatus.OPEN


@dataclass(frozen=True, slots=True)
class PollOption:
    """A choice offered by a poll."""

    id: int
    poll_id: int
    key: str
    label: str
    position: int
    created_by: int | None
    created_at: datetime

    @property
    def is_member_proposal(self) -> bool:
        """Whether a member proposed this option rather than it coming from configuration."""
        return self.created_by is not None


@dataclass(frozen=True, slots=True)
class PollVote:
    """One member's current choice on a poll."""

    poll_id: int
    member_id: int
    option_id: int
    voted_at: datetime


@dataclass(frozen=True, slots=True)
class OptionTally:
    """Vote count for a single option, including options nobody picked."""

    option: PollOption
    votes: int
