"""Bot client: intents, cog loading and command syncing."""

import logging

import aiosqlite
import discord
from discord.ext import commands

from bot.cogs.classes import DIRECTORY_KEY, Classes
from bot.cogs.general import General
from bot.cogs.polls import Polls
from bot.emojis import EmojiStore
from bot.rendering import directory_embed
from bot.tree import GuildCommandTree
from bot.views.classes import ClassButton, ResetButton, RoleButton
from bot.views.poll import VoteButton
from config import ClassCatalog, PollCatalog, Settings, load_catalog, load_classes
from db import ClassRepo, apply_migrations, connect

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
        # Loaded eagerly: a malformed polls.toml must fail at startup, not on a command.
        self.catalog: PollCatalog = load_catalog(settings.polls_file)
        self.classes: ClassCatalog = load_classes(settings.classes_file)
        self.emojis_store = EmojiStore(self.classes)
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

        # Registered once, for every poll: discord.py rebuilds each button from the
        # custom_id stored on the message, so nothing has to be re-registered per poll.
        self.add_dynamic_items(VoteButton, ClassButton, RoleButton, ResetButton)

        await self.add_cog(General(self))
        await self.add_cog(Polls(self))
        await self.add_cog(Classes(self))

        await self.emojis_store.refresh(self)

        guild = self.guild_object
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        _log.info("Synced %d command(s) to guild %d", len(synced), guild.id)

    async def directory_embed(self) -> discord.Embed:
        """The directory as it stands right now."""
        entries = await ClassRepo(self.db).directory()
        return directory_embed(self.classes, self.emojis_store, entries)

    async def refresh_directory(self) -> None:
        """Rewrite the directory message, if one was posted.

        Failures are logged and swallowed: a member declaring their class must not see an
        error because an officer deleted the directory message.
        """
        classes = ClassRepo(self.db)
        managed = await classes.managed_message(DIRECTORY_KEY)
        if managed is None:
            return

        channel = self.get_channel(managed.channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            _log.warning("Directory channel %d is gone", managed.channel_id)
            await classes.forget_message(DIRECTORY_KEY)
            return

        try:
            message = await channel.fetch_message(managed.message_id)
            await message.edit(embed=await self.directory_embed())
        except discord.NotFound:
            _log.info("Directory message was deleted; forgetting it")
            await classes.forget_message(DIRECTORY_KEY)
        except discord.HTTPException as error:
            _log.warning("Could not refresh the directory: %s", error)

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
