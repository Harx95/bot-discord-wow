"""General-purpose commands."""

import logging
import math

import discord
from discord import app_commands
from discord.ext import commands

_log = logging.getLogger(__name__)


class General(commands.Cog):
    """Health-check commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Vérifie que le bot répond.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Answer immediately: well under the 2 s interaction deadline, no defer needed."""
        _log.info("/ping invoked by %s", interaction.user)

        # Client.latency is NaN while the websocket is not established, and round(NaN) raises.
        latency = self.bot.latency
        suffix = f" ({round(latency * 1000)} ms)" if math.isfinite(latency) else ""

        await interaction.response.send_message(f"Pong !{suffix}", ephemeral=True)
