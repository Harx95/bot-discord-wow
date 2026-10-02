"""Embed rendering for polls and class boards."""

from collections import Counter
from collections.abc import Sequence

import discord

from bot.emojis import EmojiStore
from config import ClassCatalog, PollDefinition
from domain import MemberChoice, OptionTally, Poll

BAR_WIDTH = 12
BAR_FILLED = "▰"
BAR_EMPTY = "▱"

SINGLE_FOOTER = "Réagis pour voter — un seul choix, modifiable à tout moment."
MULTIPLE_FOOTER = "Réagis pour voter — plusieurs choix possibles, retire ta réaction pour revenir."
MENU_FOOTER = "Vote dans le menu — {limit} au maximum, modifiables à tout moment."
MENU_SINGLE_FOOTER = "Vote dans le menu — un seul choix, modifiable à tout moment."
CLOSED_FOOTER = "Sondage clos."
NO_VOTES = "_Aucun vote pour l'instant._"
NO_PROPOSALS = (
    "_Aucun nom proposé pour l'instant. Clique sur « Proposer un nom » pour ouvrir le vote._"
)


def _bar(votes: int, total: int) -> str:
    """A proportional bar. Empty when nobody voted, rather than a division by zero."""
    filled = round(BAR_WIDTH * votes / total) if total else 0
    return BAR_FILLED * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def _line(
    tally: OptionTally,
    total: int,
    definition: PollDefinition,
    emojis: EmojiStore,
) -> str:
    """One option: its ballot emoji, label, count, share and bar."""
    option = definition.option(tally.option.key)
    prefix = f"{emojis.rendered_option(option)} " if option is not None else ""
    share = f"{round(100 * tally.votes / total)} %" if total else "0 %"

    return f"{prefix}**{tally.option.label}** — {tally.votes} ({share})\n{_bar(tally.votes, total)}"


def _body(
    tallies: Sequence[OptionTally],
    definition: PollDefinition,
    emojis: EmojiStore,
) -> str:
    """The tally block, or a placeholder while the poll is empty.

    A poll whose options the members wrote has no option at all until someone proposes one,
    which is a different kind of empty from a poll nobody has voted on yet.
    """
    if not definition.votes_by_reaction and not tallies:
        return NO_PROPOSALS

    total = sum(tally.votes for tally in tallies)
    if total == 0:
        return NO_VOTES
    return "\n".join(_line(tally, total, definition, emojis) for tally in tallies)


def _ordered(tallies: Sequence[OptionTally], definition: PollDefinition) -> Sequence[OptionTally]:
    """Configured polls keep their order; proposals are ranked, most-backed first.

    A configured ballot reads in the order it was written, and its emojis sit in that same
    order on the message. Proposals have no intended order, so the standings are the
    useful one — ties fall back on who was proposed first.
    """
    if definition.votes_by_reaction:
        return tallies
    return sorted(tallies, key=lambda tally: (-tally.votes, tally.option.position))


def _open_footer(definition: PollDefinition) -> str:
    """How to vote, which differs by ballot and by how many answers are allowed."""
    if definition.votes_by_reaction:
        return MULTIPLE_FOOTER if definition.multiple else SINGLE_FOOTER
    if not definition.multiple:
        return MENU_SINGLE_FOOTER

    limit = definition.max_votes
    return MENU_FOOTER.format(limit=f"{limit} noms" if limit is not None else "autant que tu veux")


def _vote_count(total: int, voters: int | None) -> str:
    """How many votes were cast, and how many people cast them when that can differ.

    With several votes per person a bare total says nothing about turnout, which is the
    number an officer actually wants before closing.
    """
    if voters is None:
        return f"{total} {'vote' if total <= 1 else 'votes'}"
    # "voix" does not take an s, which is convenient: only the participants need agreeing.
    return f"{total} voix de {voters} participant(s)"


def poll_embed(
    poll: Poll,
    definition: PollDefinition,
    tallies: Sequence[OptionTally],
    emojis: EmojiStore,
    voters: int | None = None,
) -> discord.Embed:
    """The live poll message: question, running counts and how to vote.

    `voters` is how many people have voted, which only a poll allowing several votes per
    person needs to state separately. Left out, the footer counts votes alone.
    """
    total = sum(tally.votes for tally in tallies)
    ordered = _ordered(tallies, definition)
    parts = [definition.description, _body(ordered, definition, emojis)]

    embed = discord.Embed(
        title=definition.title,
        description="\n\n".join(part for part in parts if part),
        colour=discord.Colour.blurple() if poll.is_open else discord.Colour.dark_grey(),
    )
    footer = _open_footer(definition) if poll.is_open else CLOSED_FOOTER
    embed.set_footer(text=f"{_vote_count(total, voters)} · {footer}")
    return embed


def results_embed(
    poll: Poll,
    definition: PollDefinition,
    tallies: Sequence[OptionTally],
    emojis: EmojiStore,
    voters: int | None = None,
) -> discord.Embed:
    """Results, ranked, for the staff-only command."""
    total = sum(tally.votes for tally in tallies)
    ranked = sorted(tallies, key=lambda tally: tally.votes, reverse=True)

    embed = discord.Embed(
        title=f"Résultats — {definition.title}",
        description=_body(ranked, definition, emojis),
        colour=discord.Colour.blurple() if poll.is_open else discord.Colour.dark_grey(),
    )
    state = "en cours" if poll.is_open else "clos"
    embed.set_footer(text=f"{_vote_count(total, voters)} · Sondage {state}")
    return embed


# --- class boards --------------------------------------------------------------------

# A member's display name paired with one character they declared.
Declaration = tuple[str, MemberChoice]

MAIN_BOARD_TITLE = "Ta classe au lancement"
ALTERNATES_BOARD_TITLE = "Autres classes envisagées au lancement"

MAIN_BOARD_INTRO = (
    "Le personnage que tu comptes jouer au lancement : il te donne le rôle Discord de la "
    "classe et colore ton pseudo.\n"
    "Clique sur ta classe, reclique dessus pour la retirer."
)
ALTERNATES_BOARD_INTRO = (
    "Les autres classes auxquelles tu réfléchis pour ton personnage principal, sans avoir "
    "encore tranché — **{max} au maximum**.\n"
    "Clique pour en ajouter une, reclique dessus pour la retirer."
)

MAIN_BOARD_EMPTY = "Personne n'a encore déclaré de personnage principal."
ALTERNATES_BOARD_EMPTY = "Personne n'a encore déclaré d'autre classe."
COMPOSITION_EMPTY = "Personne n'a encore déclaré de personnage principal."

EMPTY_COLUMN = "—"

# Discord caps an embed field value at 1024 characters; the margin absorbs the newlines.
EMBED_FIELD_BUDGET = 1000


def _fit(lines: list[str], budget: int) -> tuple[list[str], int]:
    """As many lines as fit in the budget, and how many were left out.

    A field value is capped at 1024 characters: past a certain guild size a column has to
    stop somewhere rather than have the whole embed rejected by Discord.
    """
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if used + len(line) + 1 > budget:
            return kept, len(lines) - index
        kept.append(line)
        used += len(line) + 1
    return kept, 0


def _column_lines(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    rows: Sequence[Declaration],
) -> list[str]:
    """One line per character: the class icon, then who declared it.

    Sorted by class as configured, then by name, so the same class groups together. Names
    are escaped: a pseudo holding an asterisk would otherwise italicise the column.
    """
    order = {key: index for index, key in enumerate(catalog.class_keys)}
    ordered = sorted(
        rows,
        key=lambda row: (order.get(row[1].class_key, len(order)), row[0].casefold()),
    )
    return [
        f"{emojis.rendered_class(choice.class_key)} {discord.utils.escape_markdown(name)}"
        for name, choice in ordered
    ]


def _add_role_columns(
    embed: discord.Embed,
    catalog: ClassCatalog,
    emojis: EmojiStore,
    rows: Sequence[Declaration],
) -> int:
    """One inline field per raid role, side by side. Returns how many lines were dropped."""
    hidden = 0
    for role in catalog.roles:
        lines = _column_lines(catalog, emojis, [row for row in rows if row[1].role_key == role.key])
        shown, dropped = _fit(lines, EMBED_FIELD_BUDGET)
        hidden += dropped
        embed.add_field(
            name=f"{emojis.rendered_role(role.key)} {role.label} · {len(lines)}",
            value="\n".join(shown) or EMPTY_COLUMN,
            inline=True,
        )
    return hidden


def _set_board_footer(
    embed: discord.Embed,
    rows: Sequence[Declaration],
    hidden: int,
    empty: str,
) -> None:
    """How many people the board covers, or why it is bare."""
    people = len({choice.member_id for _, choice in rows})
    if people == 0:
        embed.set_footer(text=empty)
        return

    suffix = f" · {hidden} de plus non affiché(s)" if hidden else ""
    embed.set_footer(text=f"{people} personne(s){suffix}")


def main_board_embed(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    declarations: Sequence[Declaration],
) -> discord.Embed:
    """The main characters, laid out in tank, healer and damage columns."""
    rows = [row for row in declarations if row[1].is_first]

    embed = discord.Embed(
        title=MAIN_BOARD_TITLE,
        description=MAIN_BOARD_INTRO,
        colour=discord.Colour.blurple(),
    )
    hidden = _add_role_columns(embed, catalog, emojis, rows)
    _set_board_footer(embed, rows, hidden, MAIN_BOARD_EMPTY)
    return embed


def alternates_board_embed(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    declarations: Sequence[Declaration],
) -> discord.Embed:
    """The alternates, same columns. Ranks are not shown: they carry no meaning here."""
    rows = [row for row in declarations if not row[1].is_first]

    embed = discord.Embed(
        title=ALTERNATES_BOARD_TITLE,
        description=ALTERNATES_BOARD_INTRO.format(max=catalog.max_alternates),
        colour=discord.Colour.greyple(),
    )
    hidden = _add_role_columns(embed, catalog, emojis, rows)
    _set_board_footer(embed, rows, hidden, ALTERNATES_BOARD_EMPTY)
    return embed


def composition_embed(
    catalog: ClassCatalog,
    emojis: EmojiStore,
    choices: Sequence[MemberChoice],
) -> discord.Embed:
    """Raid composition: main characters per role, and what the alternates would cover."""
    firsts = [choice for choice in choices if choice.is_first]
    backups = [choice for choice in choices if not choice.is_first]

    role_counts = Counter(choice.role_key for choice in firsts)
    backup_counts = Counter(choice.role_key for choice in backups)
    class_counts = Counter(choice.class_key for choice in firsts)

    embed = discord.Embed(title="Composition de la guilde", colour=discord.Colour.blurple())

    role_lines = [
        f"{emojis.rendered_role(role.key)} **{role.label}** — {role_counts.get(role.key, 0)}"
        + (
            f"  _(+{backup_counts[role.key]} en classe envisagée)_"
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
        embed.set_footer(text=COMPOSITION_EMPTY)
    return embed
