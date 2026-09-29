"""Stand-ins for the discord.py objects the role logic touches.

Only what the functions under test actually use: a position to compare, a permission flag,
and a record of the calls that would have gone to Discord.
"""

from typing import cast

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
