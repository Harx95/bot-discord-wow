"""The two messages the bot keeps up to date for the class declarations.

Their keys live here rather than in the cog: the views refresh the boards after a click,
and the cog posts them, so a shared module keeps the two from importing each other.
"""

from collections.abc import Callable, Sequence

import discord

from bot.emojis import EmojiStore
from bot.rendering import Declaration, alternates_board_embed, main_board_embed
from config import ClassCatalog

MAIN_BOARD_KEY = "class_board_main"
ALTERNATES_BOARD_KEY = "class_board_alt"

BoardBuilder = Callable[[ClassCatalog, EmojiStore, Sequence[Declaration]], discord.Embed]

BOARD_BUILDERS: dict[str, BoardBuilder] = {
    MAIN_BOARD_KEY: main_board_embed,
    ALTERNATES_BOARD_KEY: alternates_board_embed,
}
