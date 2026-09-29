"""Persistent class buttons.

The message in #rôles carries one button per class plus a reset button. Clicking a class
answers with an ephemeral row of role buttons, and picking a role stores the pair at the
next free rank. The class and role travel in the custom_id, so a restarted bot rebuilds
every handler from the message itself and keeps nothing in memory.
"""

import logging
import re
from typing import TYPE_CHECKING, Any, Self, cast

import discord
from discord import ui

from bot.emojis import EmojiStore
from bot.roles import apply_class_role
from config import (
    RESET_CUSTOM_ID,
    ClassCatalog,
    ClassDefinition,
    build_class_button_custom_id,
    build_role_button_custom_id,
)
from db import ClassRepo, MemberRepo
from domain import FIRST_CHOICE

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

CLASS_TEMPLATE = re.compile(r"cls:p:(?P<klass>[a-z0-9_]+)")
ROLE_TEMPLATE = re.compile(r"cls:r:(?P<klass>[a-z0-9_]+):(?P<role>[a-z0-9_]+)")
RESET_TEMPLATE = re.compile(r"cls:reset")

GUILD_ONLY = "Cette sélection ne fonctionne que sur le serveur de la guilde."
UNKNOWN_CLASS = "Cette classe n'est plus proposée."
UNKNOWN_ROLE = "Ce rôle n'est plus proposé pour cette classe."
NO_CLASS_ROLE = (
    "Ton choix est enregistré, mais le rôle Discord correspondant n'existe pas encore. "
    "Un officier doit lancer `/roles-classes`."
)
ALL_TAKEN = "Tu as déjà fait tes **{max}** choix. Utilise **Recommencer** pour les refaire."
ALREADY_PICKED = "Tu avais déjà choisi **{klass} {role}** en choix n° {rank}."
CHOICE_DONE = "Choix n° {rank} enregistré : **{klass}** — {role}."
FIRST_CHOICE_NOTE = "\nC'est ton personnage principal : il détermine ta couleur de pseudo."
RESET_DONE = "Tes choix sont effacés. Tu peux recommencer."
RESET_EMPTY = "Tu n'avais aucun choix enregistré."
PICK_ROLE = "**{klass}** — quel rôle comptes-tu jouer ?"


class ClassButton(ui.DynamicItem[ui.Button], template=CLASS_TEMPLATE):
    """One class, as a persistent button on the public message."""

    def __init__(
        self,
        class_key: str,
        *,
        label: str,
        emoji: discord.Emoji | str | None = None,
    ) -> None:
        super().__init__(
            ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=build_class_button_custom_id(class_key),
            )
        )
        self.class_key = class_key

    @classmethod
    def for_class(
        cls,
        klass: ClassDefinition,
        emoji: discord.Emoji | str | None,
    ) -> Self:
        """Build the button as it is first sent."""
        return cls(klass.key, label=klass.name, emoji=emoji)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a click. The label is irrelevant: only the callback runs."""
        return cls(match["klass"], label=match["klass"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Answer with the role buttons this class can fill."""
        client = cast("GuildBot", interaction.client)
        klass = client.classes.get(self.class_key)
        if klass is None:
            await interaction.response.send_message(UNKNOWN_CLASS, ephemeral=True)
            return

        view = ui.View(timeout=None)
        for role in client.classes.roles_of(klass.key):
            view.add_item(
                RoleButton(
                    klass.key,
                    role.key,
                    label=role.label,
                    emoji=client.emojis_store.for_role(role.key),
                )
            )

        await interaction.response.send_message(
            PICK_ROLE.format(klass=klass.name),
            view=view,
            ephemeral=True,
        )


class RoleButton(ui.DynamicItem[ui.Button], template=ROLE_TEMPLATE):
    """One raid role of one class, on the ephemeral follow-up."""

    def __init__(
        self,
        class_key: str,
        role_key: str,
        *,
        label: str,
        emoji: discord.Emoji | str | None = None,
    ) -> None:
        super().__init__(
            ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.primary,
                custom_id=build_role_button_custom_id(class_key, role_key),
            )
        )
        self.class_key = class_key
        self.role_key = role_key

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a click, including after a restart."""
        return cls(match["klass"], match["role"], label=match["role"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Store the pair at the next free rank."""
        await handle_choice(interaction, self.class_key, self.role_key)


class ResetButton(ui.DynamicItem[ui.Button], template=RESET_TEMPLATE):
    """Clears every choice so the member can rank them again."""

    def __init__(self) -> None:
        super().__init__(
            ui.Button(
                label="Recommencer",
                emoji="♻️",
                style=discord.ButtonStyle.danger,
                custom_id=RESET_CUSTOM_ID,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild from a click. The button carries no state."""
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        """Forget the member's choices and take back their class role."""
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(GUILD_ONLY, ephemeral=True)
            return

        client = cast("GuildBot", interaction.client)
        classes = ClassRepo(client.db)
        removed = await classes.clear_choices(interaction.user.id)

        if removed:
            linked = await classes.role_ids()
            await apply_class_role(interaction.user, None, set(linked.values()))
            _log.info("%s cleared their choices", interaction.user)

        await interaction.response.send_message(
            RESET_DONE if removed else RESET_EMPTY,
            ephemeral=True,
        )
        if removed:
            await client.refresh_directory()


def build_classes_view(catalog: ClassCatalog, emojis: EmojiStore) -> ui.View:
    """One button per class, plus the reset button. timeout=None keeps them alive."""
    view = ui.View(timeout=None)
    for klass in catalog.classes:
        view.add_item(ClassButton.for_class(klass, emojis.for_class(klass.key)))
    view.add_item(ResetButton())
    return view


async def handle_choice(interaction: discord.Interaction, class_key: str, role_key: str) -> None:
    """Record a ranked choice, then reconcile the member's Discord roles."""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(GUILD_ONLY, ephemeral=True)
        return

    client = cast("GuildBot", interaction.client)
    klass = client.classes.get(class_key)
    if klass is None:
        await interaction.response.send_message(UNKNOWN_CLASS, ephemeral=True)
        return

    role = client.classes.role(role_key)
    if role is None or role_key not in klass.roles:
        await interaction.response.send_message(UNKNOWN_ROLE, ephemeral=True)
        return

    member = interaction.user
    # member_choices references members, so the member has to be recorded first.
    await MemberRepo(client.db).upsert(member.id, member.display_name)
    classes = ClassRepo(client.db)

    before = await classes.choices_of(member.id)
    choice = await classes.append_choice(member.id, class_key, role_key, client.classes.max_choices)

    if choice is None:
        await interaction.response.send_message(
            ALL_TAKEN.format(max=client.classes.max_choices),
            ephemeral=True,
        )
        return

    if any(existing.rank == choice.rank for existing in before):
        await interaction.response.send_message(
            ALREADY_PICKED.format(klass=klass.name, role=role.label, rank=choice.rank),
            ephemeral=True,
        )
        return

    _log.info("%s picked %s %s at rank %d", member, class_key, role_key, choice.rank)
    message = CHOICE_DONE.format(rank=choice.rank, klass=klass.name, role=role.label)

    if choice.rank == FIRST_CHOICE:
        message += FIRST_CHOICE_NOTE
        problem = await _assign_role(interaction.guild, member, class_key, classes)
        if problem is not None:
            message = f"{message}\n\n⚠️ {problem}"

    await interaction.response.send_message(message, ephemeral=True)
    await client.refresh_directory()


async def _assign_role(
    guild: discord.Guild,
    member: discord.Member,
    class_key: str,
    classes: ClassRepo,
) -> str | None:
    """Give the member their class role. Returns what went wrong, or None."""
    linked = await classes.role_ids()
    class_role_ids = set(linked.values())

    role_id = linked.get(class_key)
    if role_id is None:
        return NO_CLASS_ROLE

    role = guild.get_role(role_id)
    if role is None:
        # Deleted on Discord since it was linked.
        await classes.unlink_role(class_key)
        return NO_CLASS_ROLE

    return await apply_class_role(member, role, class_role_ids)
