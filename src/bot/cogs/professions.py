"""The profession directory: the daily sync, and the two staff commands that drive it."""

import datetime
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from api import ForeverApiError
from bot.autocomplete import choices
from bot.crafters import who_can_craft
from bot.directory import GUILD_TIMEZONE, publish_directory, refresh_directory
from bot.permissions import missing_permissions, staff_only
from bot.recipes import recipes_of
from db import ProfessionRepo
from domain import fold

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

# Everything the nine directory messages need. Nothing reacts to them, so nothing has to
# remove a reaction either.
REQUIRED_PERMISSIONS = ("send_messages", "embed_links", "read_message_history")

# A message is capped at 2000 characters, and a long list of incidents could reach it.
MESSAGE_LIMIT = 2000

# A one-letter search would match most of the dictionary, so Discord refuses it for us.
QUERY_MIN = 2
QUERY_MAX = 100

NO_CHANNEL = (
    "Le salon des métiers est introuvable. Vérifie PROFESSIONS_CHANNEL_ID : il vaut "
    "actuellement {channel_id}."
)
MISSING_PERMISSIONS = "Il me manque des permissions dans {channel}. Manquantes : {missing}."
WRONG_CHANNEL = "Cette commande ne fonctionne que dans {channel}."
PUBLISHED = "Annuaire à jour dans {channel} : {posted} message(s) posté(s), {edited} mis à jour."
SYNC_FAILED = "La synchronisation a échoué : {reason}"
SYNCED = (
    "Synchronisation terminée en {seconds:.1f} s.\n"
    "**{characters}** personnage(s), **{professions}** métier(s), "
    "**{links}** recette(s) connue(s), **{fetched}** nouvellement nommée(s) en français."
)
SYNC_SKIPPED = "\n{skipped} personnage(s) ignoré(s) : l'API ne les publie pas encore."
SYNC_FAILURES = "\n\n**Incidents :**\n{failures}"
DIRECTORY_REFRESHED = "\n{edited} message(s) d'annuaire réécrit(s)."
DIRECTORY_MISSING = "\nAucun message d'annuaire à réécrire : lance `/annuaire-métiers`."

# A placeholder the decorator needs at class-definition time. The real hour comes from the
# settings in cog_load, which is the only moment both the loop and the settings exist.
PLACEHOLDER_TIME = datetime.time(hour=5, tzinfo=GUILD_TIMEZONE)


class Professions(commands.Cog):
    """Sync the guild's professions every morning and keep the directory current."""

    def __init__(self, bot: "GuildBot") -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Point the loop at the configured hour, then start it."""
        hour = self.bot.settings.profession_sync_hour
        # change_interval only touches a running loop, so this is settled before start().
        self.daily_sync.change_interval(time=datetime.time(hour=hour, tzinfo=GUILD_TIMEZONE))
        self.daily_sync.start()
        _log.info("Daily profession sync scheduled for %02dh00 %s", hour, GUILD_TIMEZONE.key)

    async def cog_unload(self) -> None:
        """Stop the loop, so a reload does not leave two of them running."""
        self.daily_sync.cancel()

    @tasks.loop(time=PLACEHOLDER_TIME)
    async def daily_sync(self) -> None:
        """Sync, then rewrite the directory. Never raises: the loop has to survive."""
        try:
            await self.bot.sync_professions()
            await refresh_directory(self.bot)
        except ForeverApiError as error:
            _log.error("Daily profession sync failed: %s", error)
        except Exception:
            _log.exception("Daily profession sync failed unexpectedly")

    @daily_sync.before_loop
    async def _wait_until_ready(self) -> None:
        """The sync edits messages, so it cannot start before the gateway is up."""
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="annuaire-métiers",
        description="Poste ou met à jour l'annuaire des métiers dans le salon dédié.",
    )
    @staff_only
    async def post_directory(self, interaction: discord.Interaction) -> None:
        """Make sure the nine directory messages exist and show the latest sync."""
        await interaction.response.defer(ephemeral=True)

        channel = self.bot.text_channel(self.bot.settings.professions_channel_id)
        if channel is None:
            await interaction.followup.send(
                NO_CHANNEL.format(channel_id=self.bot.settings.professions_channel_id),
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            return
        missing = missing_permissions(
            channel.permissions_for(interaction.guild.me), REQUIRED_PERMISSIONS
        )
        if missing:
            await interaction.followup.send(
                MISSING_PERMISSIONS.format(channel=channel.mention, missing=", ".join(missing)),
                ephemeral=True,
            )
            return

        posted, edited = await publish_directory(self.bot, channel)
        await interaction.followup.send(
            PUBLISHED.format(channel=channel.mention, posted=posted, edited=edited),
            ephemeral=True,
        )

    @app_commands.command(
        name="synchro-métiers",
        description="Relit les métiers de la guilde depuis l'API et met l'annuaire à jour.",
    )
    @staff_only
    async def force_sync(self, interaction: discord.Interaction) -> None:
        """Run the sync now, rather than waiting for the morning."""
        # Twenty-six calls to Blizzard, plus any new recipe: well past the 3-second window.
        await interaction.response.defer(ephemeral=True)

        try:
            report = await self.bot.sync_professions()
        except ForeverApiError as error:
            await interaction.followup.send(SYNC_FAILED.format(reason=error), ephemeral=True)
            return

        answer = SYNCED.format(
            seconds=report.duration_seconds,
            characters=report.characters,
            professions=report.professions,
            links=report.recipe_links,
            fetched=report.recipes_fetched,
        )
        if report.skipped:
            answer += SYNC_SKIPPED.format(skipped=report.skipped)

        edited = await refresh_directory(self.bot)
        answer += DIRECTORY_REFRESHED.format(edited=edited) if edited else DIRECTORY_MISSING

        if report.failures:
            answer += SYNC_FAILURES.format(
                failures="\n".join(f"- {failure}" for failure in report.failures)
            )

        await interaction.followup.send(answer[:MESSAGE_LIMIT], ephemeral=True)

    # --- member commands ----------------------------------------------------------------

    async def _outside_channel(self, interaction: discord.Interaction) -> bool:
        """True when the command was run elsewhere, having already said so.

        Named by mention rather than fetched: the refusal has to work even when the channel
        is not in the cache, and a mention renders as a link either way.
        """
        channel_id = self.bot.settings.professions_channel_id
        if interaction.channel_id == channel_id:
            return False

        await interaction.response.send_message(
            WRONG_CHANNEL.format(channel=f"<#{channel_id}>"),
            ephemeral=True,
        )
        return True

    @app_commands.command(
        name="qui-métier",
        description="Trouve qui, dans la guilde, peut fabriquer un objet.",
    )
    @app_commands.describe(objet="Nom de l'objet ou de la recette, en français ou en anglais")
    async def who_crafts(
        self,
        interaction: discord.Interaction,
        objet: app_commands.Range[str, QUERY_MIN, QUERY_MAX],
    ) -> None:
        """Answer from the database only, and only to the member who asked."""
        if await self._outside_channel(interaction):
            return

        # Ephemeral throughout: that alone is what keeps one member's searches to
        # themselves. Nothing takes the answer back, and nothing needs to: an ephemeral
        # message is not stored in the channel, it lives in the member's client, where it
        # carries a dismiss button and leaves on its own when Discord reloads.
        await interaction.response.defer(ephemeral=True)
        embed = await who_can_craft(self.bot, objet)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _characters(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest characters that have at least one profession, on what has been typed."""
        found = await ProfessionRepo(self.bot.db).characters_like(current)
        return choices((character.display_name, character.slug) for character in found)

    async def _professions(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        """Suggest the professions of the character already picked, when one is.

        interaction.namespace carries the options filled in so far, under the names Discord
        knows them by. Before a character is chosen there is nothing to narrow, so the
        whole tracked list is offered rather than an empty box.
        """
        slug = getattr(interaction.namespace, "personnage", "") or ""
        held = await ProfessionRepo(self.bot.db).professions_of(slug) if slug else []
        if held:
            catalog = self.bot.professions
            offered = [
                (
                    definition.label if definition else profession.api_name,
                    profession.blizzard_id,
                )
                for profession in held
                if (definition := catalog.by_id(profession.blizzard_id)) is None
                or not definition.ignored
            ]
        else:
            offered = [(d.label, d.blizzard_id) for d in self.bot.professions.tracked]

        needle = fold(current)
        return choices((label, value) for label, value in offered if needle in fold(label))

    @app_commands.command(
        name="recettes",
        description="Liste les recettes apprises par un personnage dans un métier.",
    )
    # The Python identifier stays ASCII; only what Discord displays carries the accent.
    @app_commands.rename(metier="métier")
    @app_commands.describe(
        personnage="Le personnage, à choisir dans la liste",
        metier="Le métier, à choisir dans la liste",
    )
    # One decorator per parameter: a single call ties both to the same choice type, and
    # these two do not agree -- a character is a slug, a profession an id.
    @app_commands.autocomplete(personnage=_characters)
    @app_commands.autocomplete(metier=_professions)
    async def recipes(
        self,
        interaction: discord.Interaction,
        personnage: str,
        metier: int,
    ) -> None:
        """Answer from the database only, and only to the member who asked."""
        if await self._outside_channel(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        embeds = await recipes_of(self.bot, personnage, metier)
        await interaction.followup.send(embeds=embeds, ephemeral=True)
