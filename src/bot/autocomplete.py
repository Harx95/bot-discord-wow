"""Autocomplete choices, inside the two limits Discord puts on them.

Shared rather than written out per cog: both limits are API facts, and a choice list that
breaks either one makes the whole suggestion box fail silently while the member types.
"""

from collections.abc import Iterable

from discord import app_commands

# A choice name is capped at 100 characters, and a reply at 25 choices.
CHOICE_NAME_LIMIT = 100
AUTOCOMPLETE_LIMIT = 25


def choices[T: (str, int, float)](
    items: Iterable[tuple[str, T]],
) -> list[app_commands.Choice[T]]:
    """(label, value) pairs as choices: at most 25, each label cut to 100 characters."""
    return [
        app_commands.Choice(name=label[:CHOICE_NAME_LIMIT], value=value)
        for label, value in list(items)[:AUTOCOMPLETE_LIMIT]
    ]
