"""Bot client: intents, cog loading and command syncing."""

import logging

import aiosqlite
import discord
from discord.ext import commands

from bot.cogs.general import General
from bot.tree import GuildCommandTree
from config import Settings
from db import apply_migrations, connect

_log = logging.getLogger(__name__)


def build_intents() -> discord.Intents:
    """Minimal intents: guilds for the command tree, members for role management.

    message_content is deliberately left off: the bot only uses slash commands and views.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    return intents


class GuildBot(commands.Bot):
    """The guild bot. Commands are synced to a single guild for instant availability."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            help_command=None,
            intents=build_intents(),
            tree_cls=GuildCommandTree,
        )
        self.settings = settings
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        """The open database connection. Only valid once setup_hook has run."""
        if self._db is None:
            raise RuntimeError("Database not connected yet")
        return self._db

    @property
    def guild_object(self) -> discord.Object:
        """The configured guild, as a lightweight snowflake reference."""
        return discord.Object(id=self.settings.guild_id)

    async def setup_hook(self) -> None:
        """Open the database, migrate it, load the cogs and push the command tree."""
        self._db = await connect(self.settings.database_path)
        applied = await apply_migrations(self._db)
        if applied:
            _log.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))

        await self.add_cog(General(self))

        guild = self.guild_object
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        _log.info("Synced %d command(s) to guild %d", len(synced), guild.id)

    async def close(self) -> None:
        """Close the database alongside the Discord connection."""
        try:
            await super().close()
        finally:
            if self._db is not None:
                await self._db.close()
                self._db = None

    async def on_ready(self) -> None:
        """Log the identity the bot connected with."""
        if self.user is None:
            return
        _log.info("Connected as %s (id=%d)", self.user, self.user.id)
