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

from bot.permissions import is_staff
from bot.rendering import poll_embed
from config import (
    CANCEL_CLOSE_CUSTOM_ID,
    KEY_PATTERN,
    OptionDefinition,
    PollDefinition,
    build_close_custom_id,
    build_vote_custom_id,
)
from db import MemberRepo, PollRepo
from domain import OptionTally, Poll

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

_KEY = KEY_PATTERN.strip("^$")
VOTE_TEMPLATE = re.compile(rf"poll:v:(?P<poll>{_KEY}):(?P<option>{_KEY})")
CLOSE_TEMPLATE = re.compile(rf"poll:close:(?P<poll>{_KEY})")
CANCEL_TEMPLATE = re.compile(r"poll:nc")

UNKNOWN_POLL = "Ce sondage n'existe plus."
UNKNOWN_OPTION = "Ce choix n'existe plus."
POLL_CLOSED = "Ce sondage est clos, les votes ne sont plus pris en compte."
GUILD_ONLY = "Ce vote ne fonctionne que sur le serveur de la guilde."

CLOSE_DENIED = "Seuls les GM et les officiers peuvent clore un sondage."
CLOSE_ALREADY = "Ce sondage était déjà clos. Ses résultats restent lisibles avec `/resultats`."
CLOSE_CANCELLED = "Annulé. Le sondage reste ouvert."
CLOSE_DONE = "Sondage **{title}** clos, sur {votes}. Plus personne ne peut voter."
CLOSE_MESSAGE_GONE = (
    "\n\n⚠️ Son message n'a pas pu être réécrit : il a été supprimé, ou je n'y ai plus "
    "accès. Les votes sont refusés quand même, y compris sur les anciens messages."
)


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


class CloseConfirmButton(ui.DynamicItem[ui.Button], template=CLOSE_TEMPLATE):
    """Confirms closing a poll, on the ephemeral answer to /clore."""

    def __init__(self, poll_key: str) -> None:
        super().__init__(
            ui.Button(
                label="Clore définitivement",
                emoji="🔒",
                style=discord.ButtonStyle.danger,
                custom_id=build_close_custom_id(poll_key),
            )
        )
        self.poll_key = poll_key

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a click, including after a restart."""
        return cls(match["poll"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Close the poll for good."""
        await handle_close(interaction, self.poll_key)


class CloseCancelButton(ui.DynamicItem[ui.Button], template=CANCEL_TEMPLATE):
    """Puts the confirmation away without touching the poll."""

    def __init__(self) -> None:
        super().__init__(
            ui.Button(
                label="Annuler",
                style=discord.ButtonStyle.secondary,
                custom_id=CANCEL_CLOSE_CUSTOM_ID,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a click. The button carries no state."""
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        """Nothing was written, so nothing has to be undone."""
        await interaction.response.edit_message(content=CLOSE_CANCELLED, embed=None, view=None)


def build_close_confirmation_view(poll_key: str) -> ui.View:
    """The two buttons of the confirmation. Persistent, like every other view here."""
    view = ui.View(timeout=None)
    view.add_item(CloseConfirmButton(poll_key))
    view.add_item(CloseCancelButton())
    return view


async def handle_close(interaction: discord.Interaction, poll_key: str) -> None:
    """Close the poll, then freeze the message that shows it."""
    # Fetching and editing the poll message can outlast the three seconds Discord allows.
    await interaction.response.defer()

    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.edit_original_response(content=GUILD_ONLY, embed=None, view=None)
        return

    client = cast("GuildBot", interaction.client)
    # Only the officer who ran /clore sees this button, but roles may have changed since.
    if not is_staff(interaction.user, client.settings.staff_role_ids):
        await interaction.edit_original_response(content=CLOSE_DENIED, embed=None, view=None)
        return

    polls = PollRepo(client.db)
    closed = await polls.close(poll_key)
    if closed is None:
        await interaction.edit_original_response(content=CLOSE_ALREADY, embed=None, view=None)
        return

    _log.info("Poll %r closed by %s", poll_key, interaction.user)

    tallies = await polls.results(closed.id)
    total = sum(tally.votes for tally in tallies)
    note = CLOSE_DONE.format(title=closed.title, votes=f"{total} vote{'s' if total > 1 else ''}")

    definition = client.catalog.get(poll_key)
    if definition is None or not await _freeze_message(client, closed, definition, tallies):
        note += CLOSE_MESSAGE_GONE

    await interaction.edit_original_response(content=note, embed=None, view=None)


async def _freeze_message(
    client: "GuildBot",
    poll: Poll,
    definition: PollDefinition,
    tallies: list[OptionTally],
) -> bool:
    """Redraw the poll message as closed and take its buttons away.

    Returns whether it worked. A failure is cosmetic: handle_vote already refuses every
    vote on a closed poll, so the buttons left on an unreachable message are inert.
    """
    if poll.channel_id is None or poll.message_id is None:
        return False

    channel = client.get_channel(poll.channel_id)
    if not isinstance(channel, discord.TextChannel | discord.Thread):
        return False

    try:
        message = await channel.fetch_message(poll.message_id)
        await message.edit(embed=poll_embed(poll, definition, tallies), view=None)
    except discord.HTTPException as error:
        _log.warning("Could not freeze the message of poll %r: %s", poll.key, error)
        return False

    return True


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
