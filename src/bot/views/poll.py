"""Persistent voting buttons.

Every button carries its poll and option in its custom_id, so a restarted bot rebuilds the
handler from the message itself. Nothing is kept in memory and no view is re-registered at
startup: discord.py matches the custom_id against the template below and instantiates the
item on demand.
"""

import logging
import re
from typing import TYPE_CHECKING, Any, Self, cast

import discord
from discord import ui

from bot.rendering import poll_embed
from config import KEY_PATTERN, OptionDefinition, PollDefinition, build_vote_custom_id
from db import MemberRepo, PollRepo

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

_KEY = KEY_PATTERN.strip("^$")
VOTE_TEMPLATE = re.compile(rf"poll:v:(?P<poll>{_KEY}):(?P<option>{_KEY})")

UNKNOWN_POLL = "Ce sondage n'existe plus."
UNKNOWN_OPTION = "Ce choix n'existe plus."
POLL_CLOSED = "Ce sondage est clos, les votes ne sont plus pris en compte."
GUILD_ONLY = "Ce vote ne fonctionne que sur le serveur de la guilde."


class VoteButton(ui.DynamicItem[ui.Button], template=VOTE_TEMPLATE):
    """One option of a poll, as a persistent button."""

    def __init__(
        self,
        poll_key: str,
        option_key: str,
        *,
        label: str,
        emoji: str | None = None,
    ) -> None:
        super().__init__(
            ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=build_vote_custom_id(poll_key, option_key),
            )
        )
        self.poll_key = poll_key
        self.option_key = option_key

    @classmethod
    def for_option(cls, poll_key: str, option: OptionDefinition) -> Self:
        """Build the button as it is first sent."""
        return cls(poll_key, option.key, label=option.label, emoji=option.emoji)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild the button from a click on an existing message.

        The label is irrelevant here: this instance only dispatches the callback, it is
        never sent back to Discord.
        """
        return cls(match["poll"], match["option"], label=match["option"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Record the vote and refresh the message."""
        await handle_vote(interaction, self.poll_key, self.option_key)


def build_poll_view(definition: PollDefinition) -> ui.View:
    """The button row(s) of a poll. timeout=None keeps it alive across restarts."""
    view = ui.View(timeout=None)
    for option in definition.options:
        view.add_item(VoteButton.for_option(definition.key, option))
    return view


async def _reject(interaction: discord.Interaction, message: str) -> None:
    """Answer an impossible vote without touching the poll message."""
    await interaction.response.send_message(message, ephemeral=True)


async def handle_vote(interaction: discord.Interaction, poll_key: str, option_key: str) -> None:
    """Store one member's choice, then edit the message in place with the new counts."""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await _reject(interaction, GUILD_ONLY)
        return

    client = cast("GuildBot", interaction.client)
    definition = client.catalog.get(poll_key)
    if definition is None:
        await _reject(interaction, UNKNOWN_POLL)
        return

    polls = PollRepo(client.db)
    poll = await polls.get_by_key(poll_key)
    if poll is None:
        await _reject(interaction, UNKNOWN_POLL)
        return

    if not poll.is_open:
        await _reject(interaction, POLL_CLOSED)
        return

    options = await polls.options(poll.id)
    chosen = next((option for option in options if option.key == option_key), None)
    if chosen is None:
        await _reject(interaction, UNKNOWN_OPTION)
        return

    # poll_votes.member_id references members, so the voter has to be recorded first.
    await MemberRepo(client.db).upsert(interaction.user.id, interaction.user.display_name)
    await polls.cast_vote(poll.id, interaction.user.id, chosen.id)
    _log.info("%s voted %r on poll %r", interaction.user, chosen.key, poll_key)

    tallies = await polls.results(poll.id)
    # Editing the message also acknowledges the interaction; the view is left untouched.
    await interaction.response.edit_message(embed=poll_embed(poll, definition, tallies))
    await interaction.followup.send(f"Vote enregistré : **{chosen.label}**", ephemeral=True)
