"""Text folding, shared by the poll option keys and the recipe search.

Lives in the domain because every layer compares text: the repositories build their search
columns with it, the cogs fold what a member typed, and the configuration derives option keys
from it. It depends on nothing.
"""

import re
import unicodedata

_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase, unaccented, single-spaced words.

    NFKD splits an accented letter into its base letter and a combining mark, which the ASCII
    encoding then drops, so "Flacon de Force" and "flacon de force" fold to the same thing and
    a member can search without accents. Punctuation becomes a separator rather than vanishing,
    so "Enchant Chest - Intellect" keeps its words apart.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(_NOT_ALPHANUMERIC.sub(" ", ascii_only).split())
