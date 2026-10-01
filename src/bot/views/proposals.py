"""The ballot of a poll whose options the members write themselves.

Reactions cannot carry this poll. A message holds 20 distinct reactions, a proposed name
has no emoji of its own, and nothing could stop someone from adding a 21st. So the vote
moves into the message's own components: a menu of the names proposed so far, a button to
add one, and a button to take one's voices back.

What that buys back, on top of the capacity: an interaction can be answered. A member who
votes, proposes or withdraws gets a private confirmation, where a reaction could only ever
be acknowledged by the counts moving.

Persistence works as everywhere else here: each component carries the poll key in its
custom_id, so a restarted bot rebuilds the handler from the message and keeps nothing in
memory. The menu is the interesting case — discord.py hands the selected values over in
the interaction payload, so a menu rebuilt from its custom_id still knows what was picked,
even though it was rebuilt with no options at all.

The modal is the one exception, and cannot be otherwise: it belongs to no message, so
nothing can rebuild it. The button that opens it is persistent; a modal left open across a
restart fails on submit, and costs a second click.
"""

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Self, cast

import discord
from discord import ui

from bot.reactions import fetch_poll_message
from bot.rendering import poll_embed
from config import (
    KEY_PATTERN,
    SELECT_OPTIONS_LIMIT,
    PollDefinition,
    ProposalRejection,
    ProposalRules,
    build_clear_custom_id,
    build_modal_custom_id,
    build_propose_custom_id,
    build_vote_custom_id,
    clean_name,
    slugify,
)
from config.polls import OPTION_LABEL_LIMIT
from db import MemberRepo, PollRepo
from domain import OptionTally, Poll

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

_KEY = KEY_PATTERN.strip("^$")
PROPOSE_TEMPLATE = re.compile(rf"poll:add:(?P<poll>{_KEY})")
VOTE_TEMPLATE = re.compile(rf"poll:pick:(?P<poll>{_KEY})")
CLEAR_TEMPLATE = re.compile(rf"poll:clear:(?P<poll>{_KEY})")

PROPOSE_LABEL = "Proposer un nom"
CLEAR_LABEL = "Retirer mes voix"
MODAL_TITLE = "Proposer un nom de guilde"
NAME_LABEL = "Nom de la guilde"
NAME_RULES = "Entre {min} et {max} caractères. Lettres, espaces, apostrophes et traits d'union."
NAME_PLACEHOLDER = "Les Loups de Pierre"

VOTE_PLACEHOLDER_ONE = "Choisis un nom"
VOTE_PLACEHOLDER_MANY = "Choisis jusqu'à {limit} noms"

GUILD_ONLY = "Ce vote ne fonctionne que sur le serveur de la guilde."
POLL_GONE = "Ce sondage n'existe plus. Un officier doit le réouvrir."
POLL_CLOSED = "Ce sondage est clos : les propositions et les votes n'ont plus d'effet."

REJECTIONS = {
    ProposalRejection.EMPTY: "Il faut écrire un nom.",
    ProposalRejection.TOO_SHORT: "**{name}** est trop court : {min} caractères au minimum.",
    ProposalRejection.TOO_LONG: "Trop long : {max} caractères au maximum.",
    ProposalRejection.FORBIDDEN: (
        "**{name}** ne va pas : un nom commence par une lettre et ne contient que des "
        "lettres, des espaces, des apostrophes et des traits d'union."
    ),
    ProposalRejection.UNUSABLE: "**{name}** ne contient aucune lettre.",
}

DUPLICATE = "**{name}** est déjà en lice. Vote pour lui dans le menu plutôt que de le doubler."
POLL_FULL = (
    "Le sondage porte déjà {max} noms, le maximum qu'un menu puisse afficher. Un officier "
    "doit en retirer un avec `/retirer-proposition` avant d'en ajouter."
)
MEMBER_FULL = (
    "Tu as déjà proposé {max} noms : {names}. C'est ta limite — demande à un officier de "
    "retirer l'un des deux si tu as changé d'avis."
)
PROPOSED = "✅ **{name}** est en lice. Pense à voter pour lui : proposer n'est pas voter."
VOTED = "✅ Tes voix vont à {names}."
CLEARED = "✅ Tes voix sont retirées. Le sondage ne compte plus rien de toi."
NOTHING_TO_CLEAR = "Tu n'avais pas encore voté."
OPTIONS_GONE = "Les noms que tu as choisis viennent d'être retirés. Le menu est à jour."


def _join(labels: Sequence[str]) -> str:
    """Names as a French enumeration: « A », « A et B », « A, B et C »."""
    bold = [f"**{discord.utils.escape_markdown(label)}**" for label in labels]
    if len(bold) <= 1:
        return "".join(bold)
    return f"{', '.join(bold[:-1])} et {bold[-1]}"


def _votes_label(votes: int) -> str:
    """The vote count of one name, as it reads under it in the menu."""
    return "Aucune voix" if votes == 0 else f"{votes} voix"


async def _answer(interaction: discord.Interaction, message: str, *, deferred: bool) -> None:
    """The one ephemeral answer a click gets, whichever way the interaction was opened."""
    if deferred:
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _open_poll(
    interaction: discord.Interaction,
    poll_key: str,
    *,
    deferred: bool,
) -> tuple["GuildBot", Poll, PollDefinition, ProposalRules, discord.Member] | None:
    """Everything a click needs, provided the poll is still open and still takes proposals.

    Answers the member and returns None otherwise: these components outlive the poll they
    were posted for, so every one of these cases is reachable from an old message.
    """
    client = cast("GuildBot", interaction.client)

    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await _answer(interaction, GUILD_ONLY, deferred=deferred)
        return None

    definition = client.catalog.get(poll_key)
    poll = await PollRepo(client.db).get_by_key(poll_key)
    if definition is None or definition.proposals is None or poll is None:
        await _answer(interaction, POLL_GONE, deferred=deferred)
        return None

    if not poll.is_open:
        await _answer(interaction, POLL_CLOSED, deferred=deferred)
        return None

    return client, poll, definition, definition.proposals, interaction.user


class VoteSelect(ui.DynamicItem[ui.Select], template=VOTE_TEMPLATE):
    """The menu of the names proposed so far.

    Rebuilt with no options when a click comes in: the names are only needed to *send* the
    menu, never to read a vote back from it.
    """

    def __init__(
        self,
        poll_key: str,
        *,
        options: Sequence[discord.SelectOption] = (),
        limit: int = 1,
    ) -> None:
        placeholder = (
            VOTE_PLACEHOLDER_ONE if limit == 1 else VOTE_PLACEHOLDER_MANY.format(limit=limit)
        )
        super().__init__(
            ui.Select(
                custom_id=build_vote_custom_id(poll_key),
                placeholder=placeholder,
                min_values=1,
                max_values=limit,
                options=list(options),
            )
        )
        self.poll_key = poll_key

    @classmethod
    def for_poll(cls, definition: PollDefinition, tallies: Sequence[OptionTally]) -> Self:
        """The menu as it is sent: one option per name, ranked, with its count under it."""
        ranked = _ranked(tallies)[:SELECT_OPTIONS_LIMIT]
        options = [
            discord.SelectOption(
                label=tally.option.label[:OPTION_LABEL_LIMIT],
                value=tally.option.key,
                description=_votes_label(tally.votes),
            )
            for tally in ranked
        ]
        return cls(
            definition.key,
            options=options,
            limit=definition.vote_limit(len(options)),
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a submission. The options are irrelevant: the payload carries them."""
        return cls(match["poll"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Record the whole selection as this member's answer."""
        await _handle_vote(interaction, self.poll_key, self.item.values)


class ProposeButton(ui.DynamicItem[ui.Button], template=PROPOSE_TEMPLATE):
    """Opens the modal where a member writes the name they propose."""

    def __init__(self, poll_key: str) -> None:
        super().__init__(
            ui.Button(
                label=PROPOSE_LABEL,
                emoji="✍️",
                style=discord.ButtonStyle.primary,
                custom_id=build_propose_custom_id(poll_key),
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
        """Check what can be checked before the modal, then open it."""
        await _handle_propose(interaction, self.poll_key)


class ClearVotesButton(ui.DynamicItem[ui.Button], template=CLEAR_TEMPLATE):
    """Takes every voice of one member back.

    The menu cannot do it: it always submits at least one name, so there is no way to
    answer « none of them » through it.
    """

    def __init__(self, poll_key: str) -> None:
        super().__init__(
            ui.Button(
                label=CLEAR_LABEL,
                style=discord.ButtonStyle.secondary,
                custom_id=build_clear_custom_id(poll_key),
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
        """Rebuild from a click. Only the poll key matters."""
        return cls(match["poll"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Drop this member's votes, if they had any."""
        await _handle_clear(interaction, self.poll_key)


class NameModal(ui.Modal):
    """Where a member writes the name they propose.

    Deliberately not persistent, and not able to be: a modal belongs to no message, so
    discord.py has nothing to rebuild it from after a restart.
    """

    def __init__(self, definition: PollDefinition, rules: ProposalRules) -> None:
        super().__init__(title=MODAL_TITLE, custom_id=build_modal_custom_id(definition.key))
        self.poll_key = definition.key
        # Discord enforces the length client-side, which turns the commonest mistake into a
        # field that simply will not submit. The rules are checked again on arrival anyway.
        self.name: ui.TextInput[Self] = ui.TextInput(
            placeholder=NAME_PLACEHOLDER,
            min_length=rules.min_length,
            max_length=rules.max_length,
            required=True,
        )
        # The field is wrapped in a Label rather than carrying one: TextInput.label is
        # deprecated since discord.py 2.6, and a Label also states the rules under the
        # field, where they are read before the mistake rather than after it.
        self.label: ui.Label[Self] = ui.Label(
            text=NAME_LABEL,
            description=NAME_RULES.format(min=rules.min_length, max=rules.max_length),
            component=self.name,
        )
        self.add_item(self.label)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate the name, store it, and redraw the ballot."""
        await _handle_proposal(interaction, self.poll_key, self.name.value)


def _ranked(tallies: Sequence[OptionTally]) -> list[OptionTally]:
    """Names in standings order, ties broken by who was proposed first."""
    return sorted(tallies, key=lambda tally: (-tally.votes, tally.option.position))


def build_proposal_view(definition: PollDefinition, tallies: Sequence[OptionTally]) -> ui.View:
    """The ballot under the poll message: the menu of names, then the two buttons.

    The menu is left out while nothing has been proposed — Discord rejects a menu with no
    option — so the first message carries the proposal button alone.
    """
    view = ui.View(timeout=None)
    if tallies:
        view.add_item(VoteSelect.for_poll(definition, tallies))
    view.add_item(ProposeButton(definition.key))
    view.add_item(ClearVotesButton(definition.key))
    return view


async def refresh_proposal_message(
    bot: "GuildBot",
    poll: Poll,
    definition: PollDefinition,
) -> None:
    """Redraw the message, components included.

    Unlike a reaction poll, the ballot is part of the message: a new name has to appear in
    the menu, and the cap on how many names can be picked moves with the count. A failure
    here is cosmetic — what was voted is already stored.
    """
    message = await fetch_poll_message(bot, poll)
    if message is None:
        return

    polls = PollRepo(bot.db)
    tallies = await polls.results(poll.id)
    voters = await polls.voter_count(poll.id)
    try:
        await message.edit(
            embed=poll_embed(poll, definition, tallies, bot.emojis_store, voters),
            view=build_proposal_view(definition, tallies),
        )
    except discord.HTTPException as error:
        _log.warning("Could not redraw the ballot of poll %r: %s", poll.key, error)


async def _handle_vote(interaction: discord.Interaction, poll_key: str, picked: list[str]) -> None:
    """Replace this member's voices with what the menu submitted."""
    await interaction.response.defer(ephemeral=True)

    found = await _open_poll(interaction, poll_key, deferred=True)
    if found is None:
        return
    client, poll, definition, _, member = found

    polls = PollRepo(client.db)
    stored = {option.key: option for option in await polls.options(poll.id)}
    chosen = [stored[key] for key in picked if key in stored]

    if not chosen:
        # Every name picked was removed between the menu being drawn and this click.
        await interaction.followup.send(OPTIONS_GONE, ephemeral=True)
        await refresh_proposal_message(client, poll, definition)
        return

    # Discord holds the member to max_values, so this only catches a crafted payload.
    chosen = chosen[: definition.vote_limit(len(stored))]

    await MemberRepo(client.db).upsert(member.id, member.display_name)
    await polls.set_votes(poll.id, member.id, [option.id for option in chosen])

    _log.info("%s backed %s on poll %r", member, [option.key for option in chosen], poll.key)
    await refresh_proposal_message(client, poll, definition)
    await interaction.followup.send(
        VOTED.format(names=_join([option.label for option in chosen])), ephemeral=True
    )


async def _handle_propose(interaction: discord.Interaction, poll_key: str) -> None:
    """Refuse what can be refused before opening the modal, then open it.

    No defer here: a modal must be the first answer to an interaction, so the checks below
    are database reads only.
    """
    found = await _open_poll(interaction, poll_key, deferred=False)
    if found is None:
        return
    client, poll, definition, rules, member = found

    polls = PollRepo(client.db)
    if len(await polls.options(poll.id)) >= rules.max_options:
        await interaction.response.send_message(
            POLL_FULL.format(max=rules.max_options), ephemeral=True
        )
        return

    mine = await polls.proposals_of(poll.id, member.id)
    if len(mine) >= rules.max_per_member:
        await interaction.response.send_message(
            MEMBER_FULL.format(
                max=rules.max_per_member, names=_join([option.label for option in mine])
            ),
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(NameModal(definition, rules))


async def _handle_proposal(interaction: discord.Interaction, poll_key: str, raw: str) -> None:
    """Validate a submitted name and put it in the running."""
    await interaction.response.defer(ephemeral=True)

    found = await _open_poll(interaction, poll_key, deferred=True)
    if found is None:
        return
    client, poll, definition, rules, member = found

    name = clean_name(raw)
    rejection = rules.rejection(name)
    if rejection is not None:
        await interaction.followup.send(
            REJECTIONS[rejection].format(
                name=discord.utils.escape_markdown(name),
                min=rules.min_length,
                max=rules.max_length,
            ),
            ephemeral=True,
        )
        return

    polls = PollRepo(client.db)
    options = await polls.options(poll.id)

    # Both caps are checked again: the modal may have stayed open a long while, and
    # someone else's proposal may have filled the last slot in the meantime.
    if len(options) >= rules.max_options:
        await interaction.followup.send(POLL_FULL.format(max=rules.max_options), ephemeral=True)
        return

    mine = [option for option in options if option.created_by == member.id]
    if len(mine) >= rules.max_per_member:
        await interaction.followup.send(
            MEMBER_FULL.format(
                max=rules.max_per_member, names=_join([option.label for option in mine])
            ),
            ephemeral=True,
        )
        return

    await MemberRepo(client.db).upsert(member.id, member.display_name)
    proposed = await polls.propose_option(poll.id, slugify(name), name, member.id)
    if proposed is None:
        # The key was taken, by a name that may be spelled differently from this one.
        existing = await polls.option_by_key(poll.id, slugify(name))
        await interaction.followup.send(
            DUPLICATE.format(name=existing.label if existing is not None else name),
            ephemeral=True,
        )
        return

    _log.info("%s proposed %r on poll %r", member, proposed.label, poll.key)
    await refresh_proposal_message(client, poll, definition)
    await interaction.followup.send(PROPOSED.format(name=proposed.label), ephemeral=True)


async def _handle_clear(interaction: discord.Interaction, poll_key: str) -> None:
    """Take every voice of this member back."""
    await interaction.response.defer(ephemeral=True)

    found = await _open_poll(interaction, poll_key, deferred=True)
    if found is None:
        return
    client, poll, definition, _, member = found

    dropped = await PollRepo(client.db).clear_votes(poll.id, member.id)
    if not dropped:
        await interaction.followup.send(NOTHING_TO_CLEAR, ephemeral=True)
        return

    _log.info("%s took back %d voice(s) on poll %r", member, dropped, poll.key)
    await refresh_proposal_message(client, poll, definition)
    await interaction.followup.send(CLEARED, ephemeral=True)
