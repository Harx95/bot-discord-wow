"""Slugs the Battle.net API addresses things by. Pure functions, no network.

Forever has no realms: a character is reached by name and surname alone, and a guild by its
name alone, both unique within a region.
"""

from urllib.parse import quote


def character_slug(name: str, surname: str | None = None) -> str:
    """A character's slug: "{name}-{surname}", lowercased.

    The roster endpoint supplies the slug itself, so this is for the cases where it does not:
    what a member typed into a command, or a character known only by name.

    lower() rather than casefold(): Blizzard folds case the way en-US does, which leaves a
    sharp s alone where casefold() would turn it into "ss".
    """
    parts = [part for part in (name.strip(), (surname or "").strip()) if part]
    return "-".join(parts).lower()


def guild_slug(name: str) -> str:
    """A guild's slug: lowercased, apostrophes dropped, whitespace collapsed to hyphens."""
    folded = name.strip().lower().replace("'", "").replace("\u2019", "")
    return "-".join(folded.split())


def encode_slug(slug: str) -> str:
    """A slug as it goes into a path.

    Forever names may hold letters outside ASCII, so the slug is percent-encoded, keeping
    the hyphen that separates the name from the surname.
    """
    return quote(slug, safe="-")
