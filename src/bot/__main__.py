"""Entry point: python -m bot."""

import asyncio
import logging

from bot.client import GuildBot
from bot.logging import setup_logging
from config import get_settings

_log = logging.getLogger(__name__)


async def run() -> None:
    """Start the bot and keep it running until it is interrupted."""
    settings = get_settings()
    setup_logging(settings.log_level)

    bot = GuildBot(settings)
    async with bot:
        await bot.start(settings.discord_token.get_secret_value())


def main() -> None:
    """Run the bot, exiting quietly on Ctrl-C."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        _log.info("Shutting down")


if __name__ == "__main__":
    main()
