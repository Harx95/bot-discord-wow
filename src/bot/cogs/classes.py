"""Class and raid-role commands, reserved to GM and officers."""

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.boards import ALTERNATES_BOARD_KEY, MAIN_BOARD_KEY
from bot.emojis import upload_missing_icons
from bot.permissions import staff_only
from bot.rendering import composition_embed
from bot.roles import sync_class_roles
from bot.views.classes import build_alternates_view, build_main_view
from db import ClassRepo

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

WRONG_CHANNEL = "Lance cette commande dans un salon textuel du serveur."
MISSING_PERMISSIONS = (
    "Il me manque une permission dans ce salon : « Envoyer des messages » "
    "et « Intégrer des liens » sont nécessaires."
)
NO_ROLES_YET = (
    "Aucun rôle de classe n'existe encore. Lance `/roles-classes` avant de poster "
    "les messages, sinon les membres ne recevront pas leur couleur."
)
NOTHING_TO_DO = "Rien à faire."
BOARDS_POSTED = (
    "Les deux messages sont postés. Ils se mettent à jour à chaque déclaration.\n"
    "Si tu relances cette commande, pense à supprimer les anciens : "
    "leurs boutons marchent encore mais leur tableau reste figé."
)


class Classes(commands.Cog):
    """Upload the icons, create the class roles, post the boards, read the composition."""

    def __init__(self, bot: "GuildBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="emojis",
        description="Envoie les icônes de classe et de rôle comme emojis du bot.",
    )
    @staff_only
    async def upload_emojis(self, interaction: discord.Interaction) -> None:
        """Upload the icons found in assets/ that the application does not have yet."""
        await interaction.response.defer(ephemeral=True)

        uploaded, present, failed = await upload_missing_icons(
            self.bot,
            self.bot.classes,
            self.bot.emojis_store,
            self.bot.settings.assets_dir,
        )

        parts: list[str] = []
        if uploaded:
            parts.append(f"**Envoyées** ({len(uploaded)}) : {', '.join(uploaded)}")
        if present:
            parts.append(f"**Déjà en place** : {len(present)}")
        if failed:
            details = "\n".join(f"• `{name}` — {reason}" for name, reason in failed)
            parts.append(f"**Manquantes** ({len(failed)}) :\n{details}")
        if not parts:
            parts.append(NOTHING_TO_DO)

        parts.append(
            "\nLes icônes absentes sont remplacées par l'emoji de repli de `classes.toml`. "
            "Reposte les messages avec `/classes` pour appliquer les nouvelles."
        )
        await interaction.followup.send("\n".join(parts), ephemeral=True)

    @app_commands.command(
        name="roles-classes",
        description="Crée les rôles Discord de classe qui manquent.",
    )
    @staff_only
    async def create_roles(self, interaction: discord.Interaction) -> None:
        """Create one coloured, non-hoisted Discord role per configured class."""
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(WRONG_CHANNEL, ephemeral=True)
            return

        result = await sync_class_roles(
            interaction.guild,
            self.bot.classes.classes,
            ClassRepo(self.bot.db),
        )

        parts: list[str] = []
        if result.created:
            parts.append(f"**Créés** ({len(result.created)}) : {', '.join(result.created)}")
        if result.adopted:
            names = ", ".join(result.adopted)
            parts.append(f"**Récupérés** ({len(result.adopted)}) : {names}")
        if result.reused:
            parts.append(f"**Déjà en place** ({len(result.reused)}) : {', '.join(result.reused)}")
        for name, reason in result.failed:
            parts.append(f"⚠️ **{name}** : {reason}")
        if not parts:
            parts.append(NOTHING_TO_DO)

        await interaction.followup.send("\n".join(parts), ephemeral=True)

    @app_commands.command(
        name="classes",
        description="Poste les deux messages de déclaration de classe dans ce salon.",
    )
    @staff_only
    async def post_boards(self, interaction: discord.Interaction) -> None:
        """Post both boards and remember them, so every click rewrites the right one."""
        await interaction.response.defer(ephemeral=True)

        channel = await self._writable_channel(interaction)
        if channel is None:
            return

        classes = ClassRepo(self.bot.db)
        warning = "" if await classes.role_ids() else f"\n\n⚠️ {NO_ROLES_YET}"

        main, alternates = await self.bot.board_embeds()
        catalog, emojis = self.bot.classes, self.bot.emojis_store

        posted = [
            (MAIN_BOARD_KEY, await channel.send(embed=main, view=build_main_view(catalog, emojis))),
            (
                ALTERNATES_BOARD_KEY,
                await channel.send(
                    embed=alternates,
                    view=build_alternates_view(catalog, emojis),
                ),
            ),
        ]
        for key, message in posted:
            await classes.remember_message(key, channel.id, message.id)

        _log.info("Class boards posted by %s in #%s", interaction.user, channel)
        await interaction.followup.send(f"{BOARDS_POSTED}{warning}", ephemeral=True)

    @app_commands.command(
        name="composition",
        description="Répartition des tanks, soigneurs et DPS.",
    )
    @staff_only
    async def composition(self, interaction: discord.Interaction) -> None:
        """Show how the main characters spread across raid roles."""
        await interaction.response.defer(ephemeral=True)

        choices = await ClassRepo(self.bot.db).all_choices()
        await interaction.followup.send(
            embed=composition_embed(self.bot.classes, self.bot.emojis_store, choices),
            ephemeral=True,
        )

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
