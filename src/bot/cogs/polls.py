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
from bot.views.proposals import build_proposal_view, refresh_proposal_message
from config import PollDefinition
from db import MemberRepo, PollRepo
from domain import OptionTally, Poll

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
MISSING_MENU_PERMISSIONS = (
    "Il me manque une permission dans ce salon. Ce sondage se vote dans un menu sous le "
    "message, donc il me faut « Envoyer des messages », « Intégrer des liens » et "
    "« Voir les anciens messages » — la dernière me sert à retrouver le message pour le "
    "mettre à jour.\n"
    "Manquantes ici : {missing}."
)
CONFIRM_CLOSE = (
    "Clore **{title}** ? Les votes déjà enregistrés sont conservés et restent lisibles "
    "avec `/resultats`, mais plus personne ne pourra voter et le sondage ne pourra pas "
    "être rouvert."
)
OPENED = "Sondage ouvert."
OPENED_MENU = (
    "Sondage ouvert. Le menu de vote apparaîtra avec la première proposition : Discord "
    "refuse un menu vide, donc le message ne porte pour l'instant que le bouton."
)
REPOSTED = (
    "Sondage réaffiché. Les votes déjà enregistrés sont conservés, mais ils sont "
    "désormais portés par ce message : pense à supprimer l'ancien, dont les "
    "réactions ne comptent plus."
)
REPOSTED_MENU = (
    "Sondage réaffiché. Les voix déjà enregistrées sont conservées — elles vivent en base, "
    "pas sur le message. Supprime l'ancien message : son menu voterait encore, mais il ne "
    "se mettrait plus à jour."
)
UNKNOWN_PROPOSAL = "Cette proposition n'existe plus. Choisis-en une dans la liste."
CLOSED_PROPOSAL = (
    "Ce sondage est clos : retirer une proposition maintenant réécrirait son résultat."
)
PROPOSAL_REMOVED = "**{name}** est retiré du sondage{votes}. Le menu est à jour."
PROPOSAL_AUTHOR = "{name} — proposé par {author}"
PROPOSAL_UNKNOWN_AUTHOR = "quelqu'un qui a quitté le serveur"
PROPOSAL_FROM_CONFIG = "la configuration"
STILL_DISPLAYED = (
    "Ce sondage est déjà affiché et a reçu {votes}. Le réafficher les perdrait : un vote "
    "est une réaction, et les réactions restent sur l'ancien message.\n"
    "Va au message existant, ou supprime-le d'abord si tu veux repartir de zéro."
)

PERMISSION_LABELS = {
    "send_messages": "« Envoyer des messages »",
    "embed_links": "« Intégrer des liens »",
    "add_reactions": "« Ajouter des réactions »",
    "read_message_history": "« Voir les anciens messages »",
    "manage_messages": "« Gérer les messages »",
}

# Everything a poll message needs, in the order the refusal lists them. A menu poll asks
# for less: nothing posts a reaction on it, so nothing has to remove one either.
REQUIRED_PERMISSIONS = (
    "send_messages",
    "embed_links",
    "add_reactions",
    "read_message_history",
    "manage_messages",
)
REQUIRED_MENU_PERMISSIONS = ("send_messages", "embed_links", "read_message_history")


def _confirmation(definition: PollDefinition, *, reposted: bool) -> str:
    """What the officer who opened the poll is told, which depends on the ballot."""
    if definition.votes_by_reaction:
        return REPOSTED if reposted else OPENED
    return REPOSTED_MENU if reposted else OPENED_MENU


def _missing_permissions(
    permissions: discord.Permissions,
    definition: PollDefinition,
) -> list[str]:
    """The permissions this poll's message needs and does not have, in French."""
    needed = REQUIRED_PERMISSIONS if definition.votes_by_reaction else REQUIRED_MENU_PERMISSIONS
    return [PERMISSION_LABELS[name] for name in needed if not getattr(permissions, name)]


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

    async def _may_repost(self, poll: Poll, definition: PollDefinition) -> bool:
        """Whether reposting this poll would throw votes away.

        On a reaction poll a vote *is* a reaction on the attached message, so a second
        message starts from an empty ballot box while the database still holds the old
        counts — and the next reconciliation would then wipe them. Reposting is therefore
        allowed only when there is nothing to lose: no vote recorded, or the message is
        gone anyway.

        A menu poll has nothing to lose: its votes are in the database, and the new message
        carries a menu that writes to the same place.
        """
        if not definition.votes_by_reaction:
            return True

        total = sum(tally.votes for tally in await PollRepo(self.bot.db).results(poll.id))
        if total == 0:
            return True

        return await fetch_poll_message(self.bot, poll) is None

    async def _standings(
        self,
        poll: Poll,
        definition: PollDefinition,
    ) -> tuple[list[OptionTally], int | None]:
        """The counts, and the turnout when the counts alone cannot tell it.

        A reaction poll shows its voters on the message itself. A menu poll does not, and
        it is also the one allowing several voices per person, so the number of people
        behind a total is worth stating.
        """
        polls = PollRepo(self.bot.db)
        tallies = await polls.results(poll.id)
        if definition.votes_by_reaction:
            return tallies, None
        return tallies, await polls.voter_count(poll.id)

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
        missing = _missing_permissions(channel.permissions_for(interaction.guild.me), definition)
        if missing:
            refusal = (
                MISSING_PERMISSIONS if definition.votes_by_reaction else MISSING_MENU_PERMISSIONS
            )
            await interaction.followup.send(
                refusal.format(missing=", ".join(missing)), ephemeral=True
            )
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(cle)

        if poll is not None and not poll.is_open:
            await interaction.followup.send(ALREADY_CLOSED, ephemeral=True)
            return

        reposted = poll is not None
        if poll is None:
            # A menu poll has no configured option: its own are written by the members.
            poll = await polls.create(cle, definition.title, definition.option_pairs)
        elif not await self._may_repost(poll, definition):
            total = sum(tally.votes for tally in await polls.results(poll.id))
            plural = "vote" if total <= 1 else "votes"
            await interaction.followup.send(
                STILL_DISPLAYED.format(votes=f"{total} {plural}"), ephemeral=True
            )
            return

        tallies, voters = await self._standings(poll, definition)
        embed = poll_embed(poll, definition, tallies, self.bot.emojis_store, voters)
        # The components are the ballot of a menu poll, and a reaction poll carries none —
        # which is why the view is left out entirely rather than sent as empty.
        if definition.votes_by_reaction:
            message = await channel.send(embed=embed)
        else:
            message = await channel.send(embed=embed, view=build_proposal_view(definition, tallies))
        # The newest message becomes the one the poll points at, and only that one counts:
        # a reaction on an older message finds no poll and is ignored.
        await polls.attach_message(poll.id, channel.id, message.id)
        if definition.votes_by_reaction:
            # The ballot itself. Posted after attaching, so the bot's own reactions already
            # resolve to this poll and are skipped rather than counted.
            await add_ballot_reactions(message, definition, self.bot.emojis_store)
        _log.info("Poll %r %s by %s", cle, "reposted" if reposted else "opened", interaction.user)

        await interaction.followup.send(
            _confirmation(definition, reposted=reposted), ephemeral=True
        )

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

        tallies, voters = await self._standings(poll, definition)
        await interaction.followup.send(
            CONFIRM_CLOSE.format(title=definition.title),
            embed=results_embed(poll, definition, tallies, self.bot.emojis_store, voters),
            view=build_close_confirmation_view(cle),
            ephemeral=True,
        )

    async def _proposals(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest the names in the running, each with who proposed it.

        The value carries the poll alongside the option, so two polls collecting names
        cannot be confused by a name they happen to share.
        """
        needle = current.casefold()
        polls = PollRepo(self.bot.db)
        members = MemberRepo(self.bot.db)
        collecting = [d for d in self.bot.catalog.polls if d.proposals is not None]

        choices: list[app_commands.Choice[str]] = []
        for definition in collecting:
            poll = await polls.get_by_key(definition.key)
            if poll is None:
                continue

            for option in await polls.options(poll.id):
                if needle and needle not in option.label.casefold():
                    continue

                author = PROPOSAL_FROM_CONFIG
                if option.created_by is not None:
                    stored = await members.get(option.created_by)
                    author = stored.display_name if stored is not None else PROPOSAL_UNKNOWN_AUTHOR

                name = PROPOSAL_AUTHOR.format(name=option.label, author=author)
                if len(collecting) > 1:
                    name = f"{definition.title} · {name}"
                choices.append(
                    app_commands.Choice(
                        name=name[:CHOICE_NAME_LIMIT],
                        value=f"{definition.key}:{option.key}",
                    )
                )

        return choices[:AUTOCOMPLETE_LIMIT]

    @app_commands.command(
        name="retirer-proposition",
        description="Retire une proposition d'un sondage, avec les voix qu'elle avait.",
    )
    @app_commands.describe(proposition="La proposition à retirer : choisis-la dans la liste.")
    @app_commands.autocomplete(proposition=_proposals)
    @staff_only
    async def remove_proposal(self, interaction: discord.Interaction, proposition: str) -> None:
        """Take one member proposal out of the running, votes included."""
        await interaction.response.defer(ephemeral=True)

        # The autocomplete builds this value, but nothing stops someone typing their own.
        poll_key, _, option_key = proposition.partition(":")
        definition = self.bot.catalog.get(poll_key)
        if definition is None or definition.proposals is None or not option_key:
            await interaction.followup.send(UNKNOWN_PROPOSAL, ephemeral=True)
            return

        polls = PollRepo(self.bot.db)
        poll = await polls.get_by_key(poll_key)
        if poll is None:
            await interaction.followup.send(NOT_OPENED.format(key=poll_key), ephemeral=True)
            return

        if not poll.is_open:
            await interaction.followup.send(CLOSED_PROPOSAL, ephemeral=True)
            return

        # Read before deleting: the votes go with the option, so this is the last chance to
        # say how many were lost.
        lost = next(
            (
                tally.votes
                for tally in await polls.results(poll.id)
                if tally.option.key == option_key
            ),
            None,
        )
        removed = await polls.delete_option(poll.id, option_key)
        if removed is None or lost is None:
            await interaction.followup.send(UNKNOWN_PROPOSAL, ephemeral=True)
            return

        _log.info(
            "Proposal %r removed from poll %r by %s", removed.label, poll.key, interaction.user
        )
        await refresh_proposal_message(self.bot, poll, definition)

        votes = f", avec les {lost} voix qu'il avait" if lost else ", il n'avait aucune voix"
        await interaction.followup.send(
            PROPOSAL_REMOVED.format(name=removed.label, votes=votes), ephemeral=True
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

        tallies, voters = await self._standings(poll, definition)
        await interaction.followup.send(
            embed=results_embed(poll, definition, tallies, self.bot.emojis_store, voters),
            ephemeral=True,
        )
