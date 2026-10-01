"""The persistent buttons of the closing confirmation.

Voting itself is not here: it happens by reacting to the poll message, in bot.reactions.
What remains is /clore, which is an interaction and therefore still a view — its two
buttons carry the poll key in their custom_id, so a restarted bot rebuilds the handler from
the message itself and nothing is kept in memory.
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
    PollDefinition,
    build_close_custom_id,
)
from db import PollRepo
from domain import OptionTally, Poll

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

_KEY = KEY_PATTERN.strip("^$")
CLOSE_TEMPLATE = re.compile(rf"poll:close:(?P<poll>{_KEY})")
CANCEL_TEMPLATE = re.compile(r"poll:nc")

GUILD_ONLY = "Ce vote ne fonctionne que sur le serveur de la guilde."

CLOSE_DENIED = "Seuls les GM et les officiers peuvent clore un sondage."
CLOSE_ALREADY = "Ce sondage était déjà clos. Ses résultats restent lisibles avec `/resultats`."
CLOSE_CANCELLED = "Annulé. Le sondage reste ouvert."
CLOSE_DONE = "Sondage **{title}** clos, sur {votes}. Plus personne ne peut voter."
CLOSE_MESSAGE_GONE = (
    "\n\n⚠️ Son message n'a pas pu être réécrit : il a été supprimé, ou je n'y ai plus "
    "accès. Les réactions qui y restent ne comptent plus, elles seront retirées au clic."
)


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
    """Redraw the poll message as closed and take the ballot off it.

    Whatever the ballot was: the reactions of a reaction poll, the menu and buttons of a
    menu poll. Either way the poll becomes visibly unvotable. Returns whether it worked; a
    failure is cosmetic, since both handlers refuse a closed poll anyway.
    """
    if poll.channel_id is None or poll.message_id is None:
        return False

    channel = client.get_channel(poll.channel_id)
    if not isinstance(channel, discord.TextChannel | discord.Thread):
        return False

    try:
        message = await channel.fetch_message(poll.message_id)
        # view=None drops the components of a menu poll, and costs nothing on a poll that
        # never had any.
        await message.edit(
            embed=poll_embed(poll, definition, tallies, client.emojis_store),
            view=None,
        )
        # Only a reaction poll has reactions to clear, and only it asked for the permission
        # that clearing them needs.
        if definition.votes_by_reaction:
            await message.clear_reactions()
    except discord.HTTPException as error:
        _log.warning("Could not freeze the message of poll %r: %s", poll.key, error)
        return False

    return True
