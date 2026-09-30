"""Reaction voting.

A vote is a reaction on the poll message, so Discord itself holds the ballot box and the
database mirrors it. That buys persistence for free — a reaction survives a restart where a
button click would simply have failed — and costs two things the buttons gave us:

- a reaction carries no interaction, so nothing can be answered to the voter. The counts in
  the embed are the only acknowledgement;
- a reaction can be added while the bot is offline, and Discord never replays that event.
  `reconcile` reads the reactions back at startup for exactly this reason.

Anyone can react with anything, so every reaction that is not on the ballot is taken off
the message, which needs the « Gérer les messages » permission.
"""

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.emojis import EmojiStore
from bot.rendering import poll_embed
from config import OptionDefinition, PollDefinition
from config.polls import normalise_ballot
from db import MemberRepo, PollRepo
from domain import Poll, PollOption

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

# Reaction emoji as discord.py hands it over: a str for unicode, an object otherwise.
ReactionEmoji = discord.PartialEmoji | discord.Emoji | str


def ballot_of(emoji: ReactionEmoji) -> str:
    """What a reaction stands for: a custom emoji's name, or the unicode character.

    discord.py fills PartialEmoji.name with the character itself for unicode emojis, so the
    two cases collapse into one lookup.
    """
    if isinstance(emoji, str):
        return emoji
    return emoji.name or ""


async def fetch_poll_message(bot: "GuildBot", poll: Poll) -> discord.Message | None:
    """The message a poll is displayed on, or None when it is gone or unreachable."""
    if poll.channel_id is None or poll.message_id is None:
        return None

    channel = bot.get_channel(poll.channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(poll.channel_id)
        except discord.HTTPException:
            return None

    if not isinstance(channel, discord.TextChannel | discord.Thread):
        return None

    try:
        return await channel.fetch_message(poll.message_id)
    except discord.HTTPException:
        return None


async def refresh_message(bot: "GuildBot", poll: Poll, definition: PollDefinition) -> None:
    """Redraw the poll message with the counts as they now stand.

    A failure here is cosmetic: the vote is already recorded, and the next reaction redraws
    the message anyway.
    """
    message = await fetch_poll_message(bot, poll)
    if message is None:
        return

    tallies = await PollRepo(bot.db).results(poll.id)
    try:
        await message.edit(embed=poll_embed(poll, definition, tallies, bot.emojis_store))
    except discord.HTTPException as error:
        _log.warning("Could not redraw the message of poll %r: %s", poll.key, error)


async def add_ballot_reactions(
    message: discord.Message,
    definition: PollDefinition,
    emojis: EmojiStore,
) -> None:
    """Put one reaction per option on the message, in configured order.

    These are the ballot: members vote by clicking the ones already there.
    """
    for option in definition.options:
        await message.add_reaction(emojis.for_option(option))


async def _remove_reaction(message: discord.Message, emoji: ReactionEmoji, user_id: int) -> None:
    """Take one person's reaction off, leaving everyone else's in place."""
    try:
        await message.remove_reaction(emoji, discord.Object(id=user_id))
    except discord.HTTPException as error:
        _log.warning("Could not remove a reaction from message %d: %s", message.id, error)


class ReactionVotes(commands.Cog):
    """Turns reactions on a poll message into votes."""

    def __init__(self, bot: "GuildBot") -> None:
        self.bot = bot

    async def _poll_of(self, message_id: int) -> tuple[Poll, PollDefinition] | None:
        """The poll a message displays, together with its configuration."""
        poll = await PollRepo(self.bot.db).get_by_message(message_id)
        if poll is None:
            return None

        definition = self.bot.catalog.get(poll.key)
        if definition is None:
            _log.warning("Poll %r is in the database but no longer configured", poll.key)
            return None

        return poll, definition

    async def _option_id(self, poll: Poll, option_key: str) -> int | None:
        """The stored id of an option, which is what a vote references."""
        options = await PollRepo(self.bot.db).options(poll.id)
        stored = next((option for option in options if option.key == option_key), None)
        return stored.id if stored is not None else None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Record a vote, or take the reaction back off the message."""
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return

        found = await self._poll_of(payload.message_id)
        if found is None:
            return
        poll, definition = found

        option = definition.option_for_ballot(ballot_of(payload.emoji))

        # A closed poll and an emoji nobody offered are both answered the same way: the
        # reaction comes off, since there is no interaction to refuse.
        if not poll.is_open or option is None:
            message = await fetch_poll_message(self.bot, poll)
            if message is not None:
                await _remove_reaction(message, payload.emoji, payload.user_id)
            return

        polls = PollRepo(self.bot.db)
        stored = {option.key: option for option in await polls.options(poll.id)}
        chosen = stored.get(option.key)
        if chosen is None:
            return

        await MemberRepo(self.bot.db).upsert(payload.user_id, payload.member.display_name)

        if definition.multiple:
            await polls.add_vote(poll.id, payload.user_id, chosen.id)
        else:
            # Read before writing: cast_vote is about to drop these, and they are also the
            # reactions that have to come off the message for it to tell the truth.
            superseded = await self._superseded_keys(poll, payload.user_id, stored, option)
            await polls.cast_vote(poll.id, payload.user_id, chosen.id)
            await self._drop_reactions(poll, definition, superseded, payload.user_id)

        _log.info("%s backed %r on poll %r", payload.member, option.key, poll.key)
        await refresh_message(self.bot, poll, definition)

    async def _superseded_keys(
        self,
        poll: Poll,
        user_id: int,
        stored: dict[str, PollOption],
        kept: OptionDefinition,
    ) -> list[str]:
        """The options this member backed until now, minus the one they just picked."""
        by_id = {option.id: key for key, option in stored.items()}
        votes = await PollRepo(self.bot.db).votes_of(poll.id, user_id)

        return [
            key
            for vote in votes
            if (key := by_id.get(vote.option_id)) is not None and key != kept.key
        ]

    async def _drop_reactions(
        self,
        poll: Poll,
        definition: PollDefinition,
        option_keys: list[str],
        user_id: int,
    ) -> None:
        """Take the member's own reactions off the options they no longer back.

        The database is already right at this point; this only makes the message agree with
        it. Each removal fires a remove event whose vote is gone, which remove_vote reports
        as a no-op rather than undoing the new choice.
        """
        if not option_keys:
            return

        message = await fetch_poll_message(self.bot, poll)
        if message is None:
            return

        for key in option_keys:
            option = definition.option(key)
            if option is not None:
                emoji = self.bot.emojis_store.for_option(option)
                await _remove_reaction(message, emoji, user_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """Take a vote back when its reaction goes away."""
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return

        found = await self._poll_of(payload.message_id)
        if found is None:
            return
        poll, definition = found

        # Nothing to undo on a closed poll: its votes are frozen on purpose.
        if not poll.is_open:
            return

        option = definition.option_for_ballot(ballot_of(payload.emoji))
        if option is None:
            return

        option_id = await self._option_id(poll, option.key)
        if option_id is None:
            return

        removed = await PollRepo(self.bot.db).remove_vote(poll.id, payload.user_id, option_id)
        if not removed:
            return

        _log.info("Member %d took back %r on poll %r", payload.user_id, option.key, poll.key)
        await refresh_message(self.bot, poll, definition)


async def _voters_of(
    reaction: discord.Reaction,
) -> list[tuple[int, str]]:
    """The (id, display name) of everyone holding a reaction, bots excluded."""
    voters: list[tuple[int, str]] = []
    async for user in reaction.users():
        if not user.bot:
            voters.append((user.id, user.display_name))
    return voters


async def reconcile(bot: "GuildBot") -> None:
    """Rebuild the votes of every open poll from the reactions its message actually holds.

    Discord never replays reaction events, so anything added or removed while the bot was
    down would otherwise be invisible for good. The message is the source of truth here,
    and the database is realigned on it.
    """
    polls = PollRepo(bot.db)
    members = MemberRepo(bot.db)

    for poll in await polls.list_open():
        definition = bot.catalog.get(poll.key)
        if definition is None:
            continue

        message = await fetch_poll_message(bot, poll)
        if message is None:
            continue

        stored = {option.key: option for option in await polls.options(poll.id)}
        pairs, seen = await _pairs_from_reactions(message, definition, stored, members)

        total = await polls.sync_votes(poll.id, pairs)
        _log.info("Poll %r reconciled on %d vote(s) from %d member(s)", poll.key, total, len(seen))
        await refresh_message(bot, poll, definition)


async def _pairs_from_reactions(
    message: discord.Message,
    definition: PollDefinition,
    stored: dict[str, PollOption],
    members: MemberRepo,
) -> tuple[list[tuple[int, int]], set[int]]:
    """Read the message's reactions into (member id, option id) pairs.

    Members are recorded as they are found, because a vote references one. On a
    single-answer poll only the first ballot in configured order is kept, and the member's
    other reactions are taken off so the message stops claiming otherwise.
    """
    pairs: list[tuple[int, int]] = []
    seen: set[int] = set()
    already_voted: set[int] = set()

    # Configured order, so "first ballot wins" is deterministic rather than whatever order
    # the reactions happen to come back in.
    by_ballot = {
        normalise_ballot(ballot_of(reaction.emoji)): reaction for reaction in message.reactions
    }

    for option in definition.options:
        reaction = by_ballot.get(option.ballot)
        if reaction is None or option.key not in stored:
            continue

        for user_id, display_name in await _voters_of(reaction):
            if not definition.multiple and user_id in already_voted:
                await _remove_reaction(message, reaction.emoji, user_id)
                continue

            if user_id not in seen:
                await members.upsert(user_id, display_name)
                seen.add(user_id)

            pairs.append((user_id, stored[option.key].id))
            already_voted.add(user_id)

    return pairs, seen
