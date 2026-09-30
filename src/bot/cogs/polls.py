"""Poll commands, reserved to GM and officers."""

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.permissions import staff_only
from bot.rendering import poll_embed, results_embed
from bot.views.poll import build_close_confirmation_view, build_poll_view
from db import PollRepo

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

CHOICE_NAME_LIMIT = 100
AUTOCOMPLETE_LIMIT = 25

UNKNOWN_POLL = "Sondage inconnu. Vérifie la clé dans `polls.toml`."
NOT_OPENED = "Ce sondage n'a pas encore été ouvert. Lance `/sondage {key}` d'abord."
ALREADY_CLOSED = "Ce sondage est clos. Ses résultats restent consultables avec `/resultats`."
WRONG_CHANNEL = "Lance cette commande dans un salon textuel du serveur."
MISSING_PERMISSIONS = (
    "Il me manque une permission dans ce salon : « Envoyer des messages » "
    "et « Intégrer des liens » sont nécessaires."
)
CONFIRM_CLOSE = (
    "Clore **{title}** ? Les votes déjà enregistrés sont conservés et restent lisibles "
    "avec `/resultats`, mais plus personne ne pourra voter et le sondage ne pourra pas "
    "être rouvert."
)


class Polls(commands.Cog):
    """Open polls and read their results."""

    def __init__(self, bot: "GuildBot") -> None:
        self.bot = bot

    async def _poll_keys(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest configured poll keys, filtered on what has been typed."""
        needle = current.casefold()
        matches = [
            definition
            for definition in self.bot.catalog.polls
            if needle in definition.key.casefold() or needle in definition.title.casefold()
        ]
        return [
            app_commands.Choice(name=d.title[:CHOICE_NAME_LIMIT], value=d.key)
            for d in matches[:AUTOCOMPLETE_LIMIT]
        ]

    @app_commands.command(name="sondage", description="Ouvre un sondage dans ce salon.")
    # The Python identifier stays ASCII; only what Discord displays carries the accent.
    @app_commands.rename(cle="clé")
    @app_commands.describe(cle="Le sondage à ouvrir : choisis-le dans la liste.")
    @app_commands.autocomplete(cle=_poll_keys)
    @staff_only
    async def open_poll(self, interaction: discord.Interaction, cle: str) -> None:
        """Create the poll if needed, then post its message with the voting buttons."""
        await interaction.response.defer(ephemeral=True)

        definition = self.bot.catalog.get(cle)
        if definition is None:
            await interaction.followup.send(UNKNOWN_POLL, ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.followup.send(WRONG_CHANNEL, ephemeral=True)
            return

        # interaction.channel covers DMs and categories too; only a text channel or a
        # thread can carry a poll message.
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            await interaction.followup.send(WRONG_CHANNEL, ephemeral=True)
            return

        # Checked before writing anything, so a missing permission cannot leave a poll
        # recorded with no message to vote on.
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.send_messages and permissions.embed_links):
            await interaction.followup.send(MISSING_PERMISSIONS, ephemeral=True)
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(cle)

        if poll is not None and not poll.is_open:
            await interaction.followup.send(ALREADY_CLOSED, ephemeral=True)
            return

        reposted = poll is not None
        if poll is None:
            poll = await polls.create(cle, definition.title, definition.option_pairs)

        tallies = await polls.results(poll.id)
        message = await channel.send(
            embed=poll_embed(poll, definition, tallies),
            view=build_poll_view(definition),
        )
        # The newest message becomes the one the poll points at.
        await polls.attach_message(poll.id, channel.id, message.id)
        _log.info("Poll %r %s by %s", cle, "reposted" if reposted else "opened", interaction.user)

        confirmation = (
            "Sondage réaffiché. Les votes déjà enregistrés sont conservés, et les boutons "
            "de l'ancien message restent valides."
            if reposted
            else "Sondage ouvert."
        )
        await interaction.followup.send(confirmation, ephemeral=True)

    @app_commands.command(name="clore", description="Clôt un sondage, après confirmation.")
    @app_commands.rename(cle="clé")
    @app_commands.describe(cle="Le sondage à clore : choisis-le dans la liste.")
    @app_commands.autocomplete(cle=_poll_keys)
    @staff_only
    async def close_poll(self, interaction: discord.Interaction, cle: str) -> None:
        """Show what is about to be frozen, and ask before freezing it."""
        await interaction.response.defer(ephemeral=True)

        definition = self.bot.catalog.get(cle)
        if definition is None:
            await interaction.followup.send(UNKNOWN_POLL, ephemeral=True)
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(cle)
        if poll is None:
            await interaction.followup.send(NOT_OPENED.format(key=cle), ephemeral=True)
            return

        if not poll.is_open:
            await interaction.followup.send(ALREADY_CLOSED, ephemeral=True)
            return

        tallies = await polls.results(poll.id)
        await interaction.followup.send(
            CONFIRM_CLOSE.format(title=definition.title),
            embed=results_embed(poll, definition, tallies),
            view=build_close_confirmation_view(cle),
            ephemeral=True,
        )

    @app_commands.command(name="resultats", description="Affiche les résultats d'un sondage.")
    @app_commands.rename(cle="clé")
    @app_commands.describe(cle="Le sondage à consulter : choisis-le dans la liste.")
    @app_commands.autocomplete(cle=_poll_keys)
    @staff_only
    async def results(self, interaction: discord.Interaction, cle: str) -> None:
        """Send the ranked tallies, visible only to the person who asked."""
        await interaction.response.defer(ephemeral=True)

        definition = self.bot.catalog.get(cle)
        if definition is None:
            await interaction.followup.send(UNKNOWN_POLL, ephemeral=True)
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(cle)
        if poll is None:
            await interaction.followup.send(NOT_OPENED.format(key=cle), ephemeral=True)
            return

        tallies = await polls.results(poll.id)
        await interaction.followup.send(
            embed=results_embed(poll, definition, tallies),
            ephemeral=True,
        )
