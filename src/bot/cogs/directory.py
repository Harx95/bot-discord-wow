"""Profession directory commands and the daily sync, reserved to GM and officers."""

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from blizzard import BlizzardClient, BlizzardError
from bot.directory import DIRECTORY_KEY, SyncReport, directory_embed, sync_directory
from bot.permissions import staff_only
from config import ProfessionCatalog, load_professions
from db import ClassRepo, ProfessionRepo

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

WRONG_CHANNEL = "Lance cette commande dans un salon textuel du serveur."
MISSING_PERMISSIONS = (
    "Il me manque une permission dans ce salon : « Envoyer des messages » "
    "et « Intégrer des liens » sont nécessaires."
)
ALREADY_POSTED = (
    "L'annuaire est déjà affiché ici : {url}\n"
    "Il se met à jour tout seul. Supprime-le d'abord si tu veux le reposter ailleurs."
)
POSTED = "Annuaire posté. Il se mettra à jour après chaque synchro, sans nouveau message."
SYNC_FAILED = (
    "La synchro a échoué : l'API Blizzard ne répond pas ou ne trouve pas la guilde. "
    "L'annuaire n'a pas changé. Le détail est dans le journal du bot."
)
SYNC_BUSY = "Une synchro est déjà en cours, réessaie dans un instant."
NOT_POSTED = "\nAucun message d'annuaire n'est affiché : lance `/annuaire` dans #métiers."


def _report_text(report: SyncReport) -> str:
    """What a sync found, in a few lines for the officer who asked for it."""
    parts = [
        f"**{report.fetched}** personnage(s) lus sur **{report.roster_size}** dans la guilde.",
        "L'annuaire a changé." if report.changed else "Rien n'a changé depuis la dernière synchro.",
    ]
    if report.hidden:
        parts.append(
            f"Pas encore visibles dans l'Armurerie ({len(report.hidden)}), niveau 10 requis "
            f"et une déconnexion depuis : {', '.join(report.hidden)}"
        )
    if report.failed:
        parts.append(
            f"⚠️ Erreur de l'API, métiers précédents conservés ({len(report.failed)}) : "
            f"{', '.join(report.failed)}"
        )
    return "\n".join(parts)


class Directory(commands.Cog):
    """Keep the profession directory in step with the game, and post its message."""

    def __init__(self, bot: "GuildBot") -> None:
        self.bot = bot
        settings = bot.settings
        # Loaded eagerly: a malformed professions.toml must fail at startup, not at 5 am.
        self.catalog: ProfessionCatalog = load_professions(settings.professions_file)
        self.api = BlizzardClient(
            settings.blizzard_client_id,
            settings.blizzard_client_secret.get_secret_value(),
            settings.blizzard_region,
        )
        # The daily run and /annuaire-synchro must not interleave their writes.
        self._sync_lock = asyncio.Lock()
        self.daily_sync.change_interval(
            time=datetime.time(
                hour=settings.directory_sync_hour, tzinfo=ZoneInfo(settings.timezone)
            )
        )

    async def cog_load(self) -> None:
        """Start the daily sync."""
        self.daily_sync.start()

    async def cog_unload(self) -> None:
        """Stop the daily sync and close the API session."""
        self.daily_sync.cancel()
        await self.api.close()

    # --- sync -------------------------------------------------------------------------

    async def run_sync(self, *, force_redraw: bool) -> SyncReport:
        """Sync the directory, then redraw its message if anything changed.

        force_redraw rewrites the message even when the data did not change, so that a
        new emoji or a fixed layout shows without waiting for a member to level up.
        """
        async with self._sync_lock:
            report = await sync_directory(
                self.api,
                ProfessionRepo(self.bot.db),
                self.bot.settings.blizzard_guild_slug,
            )
        _log.info(
            "Directory synced: %d/%d characters read, %d hidden, %d failed, changed=%s",
            report.fetched,
            report.roster_size,
            len(report.hidden),
            len(report.failed),
            report.changed,
        )
        if report.changed or force_redraw:
            await self.redraw()
        return report

    @tasks.loop(time=datetime.time(hour=5))
    async def daily_sync(self) -> None:
        """The scheduled sync. Its time is set from the settings in __init__."""
        try:
            await self.run_sync(force_redraw=False)
        except BlizzardError as error:
            _log.warning("Daily directory sync failed: %s", error)
        except Exception:
            # An exception escaping a tasks.loop stops it for good; tomorrow must still run.
            _log.exception("Daily directory sync crashed")

    @daily_sync.before_loop
    async def _wait_until_ready(self) -> None:
        """Editing the message needs the connection to be up."""
        await self.bot.wait_until_ready()

    # --- message ----------------------------------------------------------------------

    async def _embed(self) -> discord.Embed:
        """The directory as stored right now."""
        repo = ProfessionRepo(self.bot.db)
        return directory_embed(
            await repo.directory(),
            self.catalog,
            await repo.character_count(),
            self.bot.settings.directory_sync_hour,
        )

    async def _posted_message(self) -> discord.Message | None:
        """The directory message, or None when it was never posted or has been deleted."""
        messages = ClassRepo(self.bot.db)
        managed = await messages.managed_message(DIRECTORY_KEY)
        if managed is None:
            return None

        channel = self.bot.get_channel(managed.channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            _log.warning("Channel %d of the directory is gone", managed.channel_id)
            await messages.forget_message(DIRECTORY_KEY)
            return None

        try:
            return await channel.fetch_message(managed.message_id)
        except discord.NotFound:
            _log.info("Directory message was deleted; forgetting it")
            await messages.forget_message(DIRECTORY_KEY)
            return None

    async def redraw(self) -> bool:
        """Rewrite the directory message in place. Returns whether there was one to rewrite.

        Failures are logged and swallowed: a sync is not undone because Discord would not
        take an edit.
        """
        try:
            message = await self._posted_message()
            if message is None:
                return False
            await message.edit(embed=await self._embed())
        except discord.HTTPException as error:
            _log.warning("Could not redraw the directory: %s", error)
        return True

    # --- commands ---------------------------------------------------------------------

    @app_commands.command(
        name="annuaire",
        description="Poste l'annuaire des métiers dans ce salon.",
    )
    @staff_only
    async def post_directory(self, interaction: discord.Interaction) -> None:
        """Post the directory once; every later sync edits that same message."""
        await interaction.response.defer(ephemeral=True)

        channel = await self._writable_channel(interaction)
        if channel is None:
            return

        existing = await self._posted_message()
        if existing is not None:
            await interaction.followup.send(
                ALREADY_POSTED.format(url=existing.jump_url), ephemeral=True
            )
            return

        message = await channel.send(embed=await self._embed())
        await ClassRepo(self.bot.db).remember_message(DIRECTORY_KEY, channel.id, message.id)
        _log.info("Directory posted by %s in #%s", interaction.user, channel)
        await interaction.followup.send(POSTED, ephemeral=True)

    @app_commands.command(
        name="annuaire-synchro",
        description="Relit les métiers des membres dans l'Armurerie, sans attendre 5 h.",
    )
    @staff_only
    async def sync_now(self, interaction: discord.Interaction) -> None:
        """Run the sync on demand and say what it found."""
        await interaction.response.defer(ephemeral=True)

        if self._sync_lock.locked():
            await interaction.followup.send(SYNC_BUSY, ephemeral=True)
            return

        try:
            report = await self.run_sync(force_redraw=True)
        except BlizzardError as error:
            _log.warning("Directory sync requested by %s failed: %s", interaction.user, error)
            await interaction.followup.send(SYNC_FAILED, ephemeral=True)
            return

        text = _report_text(report)
        if await self._posted_message() is None:
            text += NOT_POSTED
        await interaction.followup.send(text, ephemeral=True)

    async def _writable_channel(
        self,
        interaction: discord.Interaction,
    ) -> discord.TextChannel | discord.Thread | None:
        """The channel to post in, or None after answering why it cannot be used."""
        if interaction.guild is None:
            await interaction.followup.send(WRONG_CHANNEL, ephemeral=True)
            return None

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            await interaction.followup.send(WRONG_CHANNEL, ephemeral=True)
            return None

        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.send_messages and permissions.embed_links):
            await interaction.followup.send(MISSING_PERMISSIONS, ephemeral=True)
            return None

        return channel
