"""Embed rendering for polls."""

from collections.abc import Sequence

import discord

from config import PollDefinition
from domain import OptionTally, Poll

BAR_WIDTH = 12
BAR_FILLED = "▰"
BAR_EMPTY = "▱"

OPEN_FOOTER = "Un seul vote par personne — tu peux en changer à tout moment."
CLOSED_FOOTER = "Sondage clos."
NO_VOTES = "_Aucun vote pour l'instant._"


def _bar(votes: int, total: int) -> str:
    """A proportional bar. Empty when nobody voted, rather than a division by zero."""
    filled = round(BAR_WIDTH * votes / total) if total else 0
    return BAR_FILLED * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def _line(tally: OptionTally, total: int, definition: PollDefinition) -> str:
    """One option: emoji, label, count, share and bar."""
    option = definition.option(tally.option.key)
    prefix = f"{option.emoji} " if option is not None and option.emoji else ""
    share = f"{round(100 * tally.votes / total)} %" if total else "0 %"

    return f"{prefix}**{tally.option.label}** — {tally.votes} ({share})\n{_bar(tally.votes, total)}"


def _body(tallies: Sequence[OptionTally], definition: PollDefinition) -> str:
    """The tally block, or a placeholder while the poll is empty."""
    total = sum(tally.votes for tally in tallies)
    if total == 0:
        return NO_VOTES
    return "\n".join(_line(tally, total, definition) for tally in tallies)


def poll_embed(
    poll: Poll,
    definition: PollDefinition,
    tallies: Sequence[OptionTally],
) -> discord.Embed:
    """The live poll message: question, running counts and how to vote."""
    total = sum(tally.votes for tally in tallies)
    parts = [definition.description, _body(tallies, definition)]

    embed = discord.Embed(
        title=definition.title,
        description="\n\n".join(part for part in parts if part),
        colour=discord.Colour.blurple() if poll.is_open else discord.Colour.dark_grey(),
    )
    votes = "vote" if total <= 1 else "votes"
    embed.set_footer(text=f"{total} {votes} · {OPEN_FOOTER if poll.is_open else CLOSED_FOOTER}")
    return embed


def results_embed(
    poll: Poll,
    definition: PollDefinition,
    tallies: Sequence[OptionTally],
) -> discord.Embed:
    """Results, ranked, for the staff-only command."""
    total = sum(tally.votes for tally in tallies)
    ranked = sorted(tallies, key=lambda tally: tally.votes, reverse=True)

    embed = discord.Embed(
        title=f"Résultats — {definition.title}",
        description=_body(ranked, definition),
        colour=discord.Colour.blurple() if poll.is_open else discord.Colour.dark_grey(),
    )
    state = "en cours" if poll.is_open else "clos"
    votes = "vote" if total <= 1 else "votes"
    embed.set_footer(text=f"{total} {votes} · Sondage {state}")
    return embed
