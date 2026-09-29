"""Guild member entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Member:
    """A Discord user known to the guild."""

    discord_id: int
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime
