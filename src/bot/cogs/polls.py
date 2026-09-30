"""Poll commands, reserved to GM and officers."""

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.permissions import staff_only
from bot.reactions import add_ballot_reactions, fetch_poll_message
from bot.rendering import poll_embed, results_embed
from bot.views.poll import build_close_confirmation_view
from db import PollRepo
from domain import Poll

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
    "Il me manque une permission dans ce salon. Un sondage se vote en réagissant, "
    "donc il me faut « Envoyer des messages », « Intégrer des liens », "
    "« Ajouter des réactions », « Voir les anciens messages » et « Gérer les messages » "
    "— la dernière me sert à retirer les réactions qui ne sont pas au menu.\n"
    "Manquantes ici : {missing}."
)
CONFIRM_CLOSE = (
    "Clore **{title}** ? Les votes déjà enregistrés sont conservés et restent lisibles "
    "avec `/resultats`, mais plus personne ne pourra voter et le sondage ne pourra pas "
    "être rouvert."
)
STILL_DISPLAYED = (
    "Ce sondage est déjà affiché et a reçu {votes}. Le réafficher les perdrait : un vote "
    "est une réaction, et les réactions restent sur l'ancien message.\n"
    "Va au message existant, ou supprime-le d'abord si tu veux repartir de zéro."
)

# Everything a poll message needs, in the order the refusal lists them.
REQUIRED_PERMISSIONS = {
    "send_messages": "« Envoyer des messages »",
    "embed_links": "« Intégrer des liens »",
    "add_reactions": "« Ajouter des réactions »",
    "read_message_history": "« Voir les anciens messages »",
    "manage_messages": "« Gérer les messages »",
}


def _missing_permissions(permissions: discord.Permissions) -> list[str]:
    """The permissions a poll message needs and does not have, in French."""
    return [label for name, label in REQUIRED_PERMISSIONS.items() if not getattr(permissions, name)]


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

    async def _may_repost(self, poll: Poll) -> bool:
        """Whether reposting this poll would throw votes away.

        A vote is a reaction on the attached message, so a second message starts from an
        empty ballot box while the database still holds the old counts — and the next
        reconciliation would then wipe them. Reposting is therefore allowed only when there
        is nothing to lose: no vote recorded, or the message is gone anyway.
        """
        total = sum(tally.votes for tally in await PollRepo(self.bot.db).results(poll.id))
        if total == 0:
            return True

        return await fetch_poll_message(self.bot, poll) is None

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
        missing = _missing_permissions(channel.permissions_for(interaction.guild.me))
        if missing:
            await interaction.followup.send(
                MISSING_PERMISSIONS.format(missing=", ".join(missing)), ephemeral=True
            )
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(cle)

        if poll is not None and not poll.is_open:
            await interaction.followup.send(ALREADY_CLOSED, ephemeral=True)
            return

        reposted = poll is not None
        if poll is None:
            poll = await polls.create(cle, definition.title, definition.option_pairs)
        elif not await self._may_repost(poll):
            total = sum(tally.votes for tally in await polls.results(poll.id))
            plural = "vote" if total <= 1 else "votes"
            await interaction.followup.send(
                STILL_DISPLAYED.format(votes=f"{total} {plural}"), ephemeral=True
            )
            return

        tallies = await polls.results(poll.id)
        message = await channel.send(
            embed=poll_embed(poll, definition, tallies, self.bot.emojis_store)
        )
        # The newest message becomes the one the poll points at, and only that one counts:
        # a reaction on an older message finds no poll and is ignored.
        await polls.attach_message(poll.id, channel.id, message.id)
        # The ballot itself. Posted after attaching, so the bot's own reactions already
        # resolve to this poll and are skipped rather than counted.
        await add_ballot_reactions(message, definition, self.bot.emojis_store)
        _log.info("Poll %r %s by %s", cle, "reposted" if reposted else "opened", interaction.user)

        confirmation = (
            "Sondage réaffiché. Les votes déjà enregistrés sont conservés, mais ils sont "
            "désormais portés par ce message : pense à supprimer l'ancien, dont les "
            "réactions ne comptent plus."
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
            embed=results_embed(poll, definition, tallies, self.bot.emojis_store),
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
            embed=results_embed(poll, definition, tallies, self.bot.emojis_store),
            ephemeral=True,
        )
