"""Stand-ins for the objects the bot talks to: discord.py, and the Battle.net session.

Only what the functions under test actually use: a position to compare, a permission flag,
a record of the calls that would have gone to Discord, and canned HTTP responses.
"""

from dataclasses import dataclass, field
from typing import cast

import aiohttp
import discord


class FakeRole:
    """Enough of discord.Role for the hierarchy comparisons."""

    def __init__(
        self, name: str, position: int, role_id: int = 0, *, managed: bool = False
    ) -> None:
        self.name = name
        self.position = position
        self.id = role_id
        self.managed = managed

    def __ge__(self, other: "FakeRole") -> bool:
        return self.position >= other.position


class FakeMember:
    """Records what would have been sent to Discord."""

    def __init__(self, guild: "FakeGuild | discord.Guild", roles: list[FakeRole]) -> None:
        self.guild = guild
        self.roles = roles
        self.top_role = FakeRole("Bot", 0)
        self.guild_permissions = discord.Permissions()
        self.added: list[FakeRole] = []
        self.removed: list[FakeRole] = []

    async def add_roles(self, *roles: FakeRole, reason: str | None = None) -> None:
        self.added.extend(roles)

    async def remove_roles(self, *roles: FakeRole, reason: str | None = None) -> None:
        self.removed.extend(roles)


class FakeGuild:
    """A guild whose bot member sits at a chosen position in the hierarchy."""

    def __init__(self, *, manage_roles: bool = True, bot_position: int = 10) -> None:
        self.roles: list[FakeRole] = []
        self.me = FakeMember(self, [])
        self.me.top_role = FakeRole("Bot", bot_position)
        self.me.guild_permissions = discord.Permissions(manage_roles=manage_roles)
        self.created: list[str] = []

    async def create_role(
        self,
        *,
        name: str,
        colour: discord.Colour,
        hoist: bool = False,
        mentionable: bool = False,
        reason: str | None = None,
    ) -> FakeRole:
        """Mimic Discord: the new role lands at the bottom of the hierarchy."""
        self.created.append(name)
        role = FakeRole(name, position=1, role_id=1000 + len(self.created))
        self.roles.append(role)
        return role


class RecordingRepo:
    """A ClassRepo stand-in that records the links made, without a database."""

    def __init__(self, linked: dict[str, int] | None = None) -> None:
        self.linked = dict(linked or {})
        self.unlinked: list[str] = []

    async def role_ids(self) -> dict[str, int]:
        return dict(self.linked)

    async def link_role(self, class_key: str, role_id: int) -> None:
        self.linked[class_key] = role_id

    async def unlink_role(self, class_key: str) -> bool:
        self.unlinked.append(class_key)
        return self.linked.pop(class_key, None) is not None


def as_guild(*, manage_roles: bool = True, bot_position: int = 10) -> discord.Guild:
    """A stand-in guild, typed as the real one for the functions under test."""
    return cast(discord.Guild, FakeGuild(manage_roles=manage_roles, bot_position=bot_position))


def as_member(member: FakeMember) -> discord.Member:
    """A stand-in member, typed as the real one."""
    return cast(discord.Member, member)


def as_role(role: FakeRole) -> discord.Role:
    """A stand-in role, typed as the real one."""
    return cast(discord.Role, role)


# --- the Battle.net API ---------------------------------------------------------------
#
# A stand-in for aiohttp.ClientSession, so the client is exercised without Blizzard. Only
# the two methods ForeverClient calls are implemented: get() and post().


@dataclass
class FakeResponse:
    """One canned HTTP response."""

    status: int = 200
    body: object = None
    headers: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None

    async def json(self) -> object:
        return self.body

    async def __aenter__(self) -> "FakeResponse":
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeSession:
    """Answers each path from a queue, and records what was asked.

    A path mapped to a list answers its entries in turn, so a retry can be given a
    different outcome from the first attempt.
    """

    def __init__(
        self,
        responses: dict[str, FakeResponse | list[FakeResponse]] | None = None,
        token: FakeResponse | list[FakeResponse] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._token = token or FakeResponse(body={"access_token": "t0ken", "expires_in": 86400})
        self.requests: list[str] = []
        self.token_requests = 0

    @staticmethod
    def _next(
        entry: FakeResponse | list[FakeResponse],
    ) -> FakeResponse:
        if isinstance(entry, list):
            return entry.pop(0) if len(entry) > 1 else entry[0]
        return entry

    def post(self, url: str, **_: object) -> FakeResponse:
        self.token_requests += 1
        return self._next(self._token)

    def get(self, url: str, **_: object) -> FakeResponse:
        path = url.split(".blizzard.com", 1)[-1]
        self.requests.append(path)
        entry = self._responses.get(path)
        if entry is None:
            return FakeResponse(status=404)
        return self._next(entry)


def as_session(session: FakeSession) -> aiohttp.ClientSession:
    """Hand a fake session to code that is typed for the real one."""
    return cast("aiohttp.ClientSession", session)


# --- Discord channels and messages ----------------------------------------------------
#
# Enough of a text channel for the directory: it posts, it fetches, it edits, and it has
# to cope with a message an officer deleted.


@dataclass
class FakeHttpResponse:
    """The two attributes discord.HTTPException reads off a response."""

    status: int = 404
    reason: str = "Not Found"


def not_found() -> discord.NotFound:
    """The error Discord raises for a message that is no longer there."""
    return discord.NotFound(cast("aiohttp.ClientResponse", FakeHttpResponse()), "Unknown Message")


class FakeMessage:
    """A message that reports its edits back to the channel holding it."""

    def __init__(self, message_id: int, channel: "FakeChannel") -> None:
        self.id = message_id
        self._channel = channel

    async def edit(self, *, embed: discord.Embed) -> None:
        self._channel.edited.append((self.id, embed))


class FakeChannel:
    """A text channel that records what was posted and refuses the ids it was told to.

    An id it has never posted is still fetched successfully: that is the ordinary case of a
    message remembered from an earlier run. The ids in `deleted` are the ones an officer
    removed, and they raise NotFound.
    """

    def __init__(self, channel_id: int = 500, deleted: set[int] | None = None) -> None:
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.sent: list[tuple[int, discord.Embed]] = []
        self.edited: list[tuple[int, discord.Embed]] = []
        self.fetched: list[int] = []
        self.deleted = deleted or set()
        self._next_id = 1000

    async def send(self, *, embed: discord.Embed) -> FakeMessage:
        self._next_id += 1
        self.sent.append((self._next_id, embed))
        return FakeMessage(self._next_id, self)

    async def fetch_message(self, message_id: int) -> FakeMessage:
        self.fetched.append(message_id)
        if message_id in self.deleted:
            raise not_found()
        return FakeMessage(message_id, self)


def as_channel(channel: FakeChannel) -> discord.TextChannel:
    """Hand a fake channel to code that is typed for the real one."""
    return cast("discord.TextChannel", channel)
