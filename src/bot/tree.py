"""Command tree with a global error handler."""

import logging

import discord
from discord import app_commands

_log = logging.getLogger(__name__)

ERROR_MESSAGE = "Une erreur est survenue. Réessaie dans un instant."


class GuildCommandTree(app_commands.CommandTree):
    """Command tree that never lets an exception surface as a silent timeout.

    Without this, an unhandled exception leaves the interaction unacknowledged and Discord
    shows "L'application ne répond pas", with no clue as to the cause.
    """

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Log the failure and always answer the user, ephemerally."""
        command = interaction.command.name if interaction.command else "?"
        _log.exception("Command /%s failed", command, exc_info=error)

        # The handler may have answered or deferred before failing.
        if interaction.response.is_done():
            await interaction.followup.send(ERROR_MESSAGE, ephemeral=True)
        else:
            await interaction.response.send_message(ERROR_MESSAGE, ephemeral=True)
