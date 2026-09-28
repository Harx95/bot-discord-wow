"""Console logging setup."""

import logging

import discord


def setup_logging(level_name: str) -> None:
    """Configure readable, timestamped console logging for the whole process.

    discord.py colourises the output when the stream is a terminal.
    """
    level = logging.getLevelNamesMapping().get(level_name.upper(), logging.INFO)
    discord.utils.setup_logging(level=level, root=True)
