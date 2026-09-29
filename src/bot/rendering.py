"""Embed rendering for polls and class composition."""

from collections import Counter
from collections.abc import Sequence

import discord

from bot.emojis import EmojiStore
from config import ClassCatalog, PollDefinition
from domain import MemberChoice, OptionTally, Poll

BAR_WIDTH = 12
BAR_FILLED = "▰"
BAR_EMPTY = "▱"

OPEN_FOOTER = "Un seul vote par personne — tu peux en changer à tout moment."
CLOSED_FOOTER = "Sondage clos."
NO_VOTES = "_Aucun vote pour l'instant._"

# Discord caps an embed description at 4096 characters.
EMBED_DESCRIPTION_BUDGET = 4000


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


# --- classes -------------------------------------------------------------------------

RANK_MARKS = ("①", "②", "③", "④", "⑤")
DIRECTORY_EMPTY = "_Personne n'a encore déclaré de personnage._"
COMPOSITION_EMPTY = "_Personne n'a encore déclaré de personnage principal._"


def rank_mark(rank: int) -> str:
    """A compact marker for a rank, falling back to a plain number past the marks."""
    return RANK_MARKS[rank - 1] if rank <= len(RANK_MARKS) else f"{rank}."


def _choice_text(catalog: ClassCatalog, emojis: EmojiStore, choice: MemberChoice) -> str:
    """One choice as `icon Classe · icon Rôle`, with names for anyone without emoji."""
    klass = catalog.get(choice.class_key)
    role = catalog.role(choice.role_key)
    class_name = klass.name if klass else choice.class_key
    role_name = role.label if role else choice.role_key

    return (
        f"{emojis.rendered_class(choice.class_key)} {class_name}"
        f" · {emojis.rendered_role(choice.role_key)} {role_name}"
    )


def classes_embed(catalog: ClassCatalog, emojis: EmojiStore) -> discord.Embed:
    """The persistent message inviting members to rank the characters they will play."""
    roles_line = " · ".join(
        f"{emojis.rendered_role(role.key)} {role.label}" for role in catalog.roles
    )

    embed = discord.Embed(
        title="Quelles classes joueras-tu ?",
        description=(
            f"Choisis jusqu'à **{catalog.max_choices} personnages**, "
            "du plus voulu au moins voulu.\n"
            f"Le **choix {rank_mark(1)}** te donne le rôle Discord de la classe "
            "et colore ton pseudo ; les suivants servent à équilibrer la composition.\n\n"
            f"{roles_line}"
        ),
        colour=discord.Colour.blurple(),
    )

    for klass in catalog.classes:
        playable = " ".join(
            f"{emojis.rendered_role(role.key)} {role.label}" for role in catalog.roles_of(klass.key)
        )
        embed.add_field(
            name=f"{emojis.rendered_class(klass.key)} {klass.name}",
            value=playable or "—",
            inline=True,
        )

    embed.set_footer(text="Clique sur une classe, puis sur un rôle. « Recommencer » efface tout.")
    return embed


def directory_embed(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    entries: Sequence[tuple[str, list[MemberChoice]]],
) -> discord.Embed:
    """Who plays what, one line per member, kept within the embed limits."""
    embed = discord.Embed(
        title="Annuaire des personnages",
        colour=discord.Colour.blurple(),
    )

    if not entries:
        embed.description = DIRECTORY_EMPTY
        return embed

    lines: list[str] = []
    for name, choices in entries:
        ranked = " • ".join(
            f"{rank_mark(choice.rank)} {_choice_text(catalog, emojis, choice)}"
            for choice in choices
        )
        lines.append(f"**{name}** — {ranked}")

    shown, hidden = _fit(lines, EMBED_DESCRIPTION_BUDGET)
    embed.description = "\n".join(shown)

    suffix = f" · {hidden} de plus non affiché(s)" if hidden else ""
    embed.set_footer(text=f"{len(entries)} personne(s){suffix}")
    return embed


def _fit(lines: list[str], budget: int) -> tuple[list[str], int]:
    """As many lines as fit in the budget, and how many were left out.

    An embed description is capped at 4096 characters: past a certain guild size the
    directory has to stop somewhere rather than be rejected by Discord.
    """
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if used + len(line) + 1 > budget:
            return kept, len(lines) - index
        kept.append(line)
        used += len(line) + 1
    return kept, 0


def composition_embed(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    choices: Sequence[MemberChoice],
) -> discord.Embed:
    """Raid composition: first choices per role, and what the later ones would cover."""
    firsts = [choice for choice in choices if choice.is_first]
    backups = [choice for choice in choices if not choice.is_first]

    role_counts = Counter(choice.role_key for choice in firsts)
    backup_counts = Counter(choice.role_key for choice in backups)
    class_counts = Counter(choice.class_key for choice in firsts)

    embed = discord.Embed(title="Composition de la guilde", colour=discord.Colour.blurple())

    role_lines = [
        f"{emojis.rendered_role(role.key)} **{role.label}** — {role_counts.get(role.key, 0)}"
        + (
            f"  _(+{backup_counts[role.key]} en choix suivant)_"
            if backup_counts.get(role.key)
            else ""
        )
        for role in catalog.roles
    ]
    embed.add_field(
        name=f"Rôles · {len(firsts)} personne(s)",
        value="\n".join(role_lines) or COMPOSITION_EMPTY,
        inline=False,
    )

    class_lines = [
        f"{emojis.rendered_class(klass.key)} **{klass.name}** — {class_counts[klass.key]}"
        for klass in catalog.classes
        if class_counts.get(klass.key)
    ]
    embed.add_field(
        name="Classes principales",
        value="\n".join(class_lines) or COMPOSITION_EMPTY,
        inline=False,
    )

    if not firsts:
        embed.set_footer(text="Personne n'a encore déclaré de personnage principal.")
    return embed
