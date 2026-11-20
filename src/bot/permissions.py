"""Permission checks: who may run a command, and what the bot may do in a channel."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.client import GuildBot

STAFF_DENIED = "Cette commande est réservée aux GM et aux officiers."
GUILD_ONLY = "Cette commande ne fonctionne que sur le serveur de la guilde."

# Named in French because a refusal quotes them straight out of the Discord settings,
# where an officer has to go and tick them.
PERMISSION_LABELS = {
    "send_messages": "« Envoyer des messages »",
    "embed_links": "« Intégrer des liens »",
    "add_reactions": "« Ajouter des réactions »",
    "read_message_history": "« Voir les anciens messages »",
    "manage_messages": "« Gérer les messages »",
}


def missing_permissions(
    permissions: discord.Permissions,
    needed: Sequence[str],
) -> list[str]:
    """The named permissions that are missing, in French, in the order asked for."""
    return [PERMISSION_LABELS[name] for name in needed if not getattr(permissions, name)]


class NotStaff(app_commands.CheckFailure):
    """Raised when a member without the GM or officer role runs a staff command."""


class OutsideGuild(app_commands.CheckFailure):
    """Raised when a guild command is run outside the guild."""


def is_staff(member: discord.Member, staff_role_ids: frozenset[int]) -> bool:
    """Whether the member holds the GM or the officer role.

    Nobody holds two guild roles at once, so this tests membership in GM or Officer rather
    than the absence of the Member role.
    """
    return any(role.id in staff_role_ids for role in member.roles)


def staff_predicate(interaction: discord.Interaction) -> bool:
    """Allow only GM and officers, inside the guild."""
    # interaction.user is User | Member; only a Member carries roles.
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        raise OutsideGuild(GUILD_ONLY)

    client = cast("GuildBot", interaction.client)
    if not is_staff(interaction.user, client.settings.staff_role_ids):
        raise NotStaff(STAFF_DENIED)

    return True


staff_only = app_commands.check(staff_predicate)
"""Decorator restricting a command to GM and officers."""
