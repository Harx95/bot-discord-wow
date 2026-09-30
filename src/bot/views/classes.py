"""Class buttons on the two board messages.

Each board carries one button per class, icon and name, all grey. Clicking a class
declares it; clicking it again takes it back. The board a button belongs to travels in its
custom_id alongside the class, so a restarted bot rebuilds every handler from the message
itself and keeps nothing in memory.

Buttons stay grey on purpose. A button's style belongs to the message, and a board message
is the same for everyone, so colouring the selection would show whoever clicked last
rather than the person looking. The live columns above the buttons are the feedback: a
name appears in a column, or leaves it.

A click answers with at most one short-lived ephemeral message — the role question, an
error, or a confirmation — and the role question turns into its own answer rather than
stacking a second one.
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Self, cast

import discord
from discord import ui

from bot.boards import ALTERNATES_BOARD_KEY, MAIN_BOARD_KEY
from bot.emojis import EmojiStore
from bot.roles import apply_class_role
from config import (
    ClassCatalog,
    ClassDefinition,
    RoleDefinition,
    Slot,
    build_class_button_custom_id,
    build_role_button_custom_id,
)
from db import ClassRepo, MemberRepo

if TYPE_CHECKING:
    from bot.client import GuildBot

_log = logging.getLogger(__name__)

MAIN_CLASS_TEMPLATE = re.compile(r"cls:m:(?P<klass>[a-z0-9_]+)")
ALTERNATE_CLASS_TEMPLATE = re.compile(r"cls:a:(?P<klass>[a-z0-9_]+)")
ROLE_TEMPLATE = re.compile(r"cls:r:(?P<slot>[ma]):(?P<klass>[a-z0-9_]+):(?P<role>[a-z0-9_]+)")

# How long a confirmation or an error stays before deleting itself.
EPHEMERAL_TTL = 30

GUILD_ONLY = "Cette sélection ne fonctionne que sur le serveur de la guilde."
UNKNOWN_CLASS = "Cette classe n'est plus proposée."
UNKNOWN_ROLE = "Ce rôle n'est plus proposé pour cette classe."
NO_CLASS_ROLE = (
    "Ton choix est enregistré, mais le rôle Discord correspondant n'existe pas encore. "
    "Un officier doit lancer `/roles-classes`."
)
PICK_ROLE = "**{klass}** — quel rôle comptes-tu jouer ?"

MAIN_SET = "✅ Classe principale : **{klass}** — {role}."
MAIN_REPLACED = " Elle remplace **{other}**."
MAIN_CLEARED = "✅ **{klass}** retirée. Tu n'as plus de classe principale, ni de couleur."

ALT_ADDED = "✅ **{klass}** — {role} ajoutée à tes classes envisagées."
ALT_REMOVED = "✅ **{klass}** retirée de tes classes envisagées."
ALT_IS_MAIN = "⚠️ **{klass}** est déjà ta classe principale. Choisis-en une autre."
ALT_FULL = (
    "⚠️ Tu as déjà **{max}** classes envisagées. Reclique sur l'une d'elles pour la retirer d'abord."
)

# Tasks are kept until they finish, otherwise the loop may collect them mid-sleep.
_expiring: set[asyncio.Task[None]] = set()


def _expire(interaction: discord.Interaction) -> None:
    """Delete an ephemeral answer after a while, so nobody accumulates them."""

    async def run() -> None:
        await asyncio.sleep(EPHEMERAL_TTL)
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            # Already dismissed, or the interaction token expired: nothing to clean up.
            pass

    task = asyncio.create_task(run())
    _expiring.add(task)
    task.add_done_callback(_expiring.discard)


async def _answer(interaction: discord.Interaction, message: str) -> None:
    """The single message a click on a board button sends."""
    await interaction.response.send_message(message, ephemeral=True)
    _expire(interaction)


async def _replace(interaction: discord.Interaction, message: str) -> None:
    """Turn the role question into its own answer, rather than stacking a second message."""
    await interaction.response.edit_message(content=message, view=None)
    _expire(interaction)


def _class_button(
    slot: Slot,
    class_key: str,
    label: str,
    emoji: discord.Emoji | str | None,
) -> ui.Button[ui.View]:
    """One class on a board. Grey for everyone: the style cannot depend on the viewer."""
    return ui.Button(
        label=label,
        emoji=emoji,
        style=discord.ButtonStyle.secondary,
        custom_id=build_class_button_custom_id(slot, class_key),
    )


class MainClassButton(ui.DynamicItem[ui.Button], template=MAIN_CLASS_TEMPLATE):
    """One class on the main-character board."""

    def __init__(
        self,
        class_key: str,
        *,
        label: str,
        emoji: discord.Emoji | str | None = None,
    ) -> None:
        super().__init__(_class_button(Slot.MAIN, class_key, label, emoji))
        self.class_key = class_key

    @classmethod
    def for_class(cls, klass: ClassDefinition, emoji: discord.Emoji | str | None) -> Self:
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
        """Declare this class as the main character, or take it back."""
        await _click_main(interaction, self.class_key)


class AlternateClassButton(ui.DynamicItem[ui.Button], template=ALTERNATE_CLASS_TEMPLATE):
    """One class on the alternates board."""

    def __init__(
        self,
        class_key: str,
        *,
        label: str,
        emoji: discord.Emoji | str | None = None,
    ) -> None:
        super().__init__(_class_button(Slot.ALTERNATE, class_key, label, emoji))
        self.class_key = class_key

    @classmethod
    def for_class(cls, klass: ClassDefinition, emoji: discord.Emoji | str | None) -> Self:
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
        """Rebuild from a click, including after a restart."""
        return cls(match["klass"], label=match["klass"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Add this class to the alternates, or take it back out."""
        await _click_alternate(interaction, self.class_key)


class RoleButton(ui.DynamicItem[ui.Button], template=ROLE_TEMPLATE):
    """One raid role, on the ephemeral question that a multi-role class opens."""

    def __init__(
        self,
        slot: Slot,
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
                custom_id=build_role_button_custom_id(slot, class_key, role_key),
            )
        )
        self.slot = slot
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
        return cls(Slot(match["slot"]), match["klass"], match["role"], label=match["role"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Record the pair and turn this question into its confirmation."""
        await _record(interaction, self.slot, self.class_key, self.role_key, from_question=True)


def build_main_view(catalog: ClassCatalog, emojis: EmojiStore) -> ui.View:
    """The main board's buttons. timeout=None keeps them alive across restarts."""
    view = ui.View(timeout=None)
    for klass in catalog.classes:
        view.add_item(MainClassButton.for_class(klass, emojis.for_class(klass.key)))
    return view


def build_alternates_view(catalog: ClassCatalog, emojis: EmojiStore) -> ui.View:
    """The alternates board's buttons."""
    view = ui.View(timeout=None)
    for klass in catalog.classes:
        view.add_item(AlternateClassButton.for_class(klass, emojis.for_class(klass.key)))
    return view


def _member_of(interaction: discord.Interaction) -> discord.Member | None:
    """The clicker as a guild member, or None when the click came from outside."""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return None
    return interaction.user


async def _click_main(interaction: discord.Interaction, class_key: str) -> None:
    """Main board: take the class back if it is already declared, else declare it."""
    member = _member_of(interaction)
    if member is None:
        await _answer(interaction, GUILD_ONLY)
        return

    client = cast("GuildBot", interaction.client)
    klass = client.classes.get(class_key)
    if klass is None:
        await _answer(interaction, UNKNOWN_CLASS)
        return

    classes = ClassRepo(client.db)
    current = await classes.main_of(member.id)
    if current is not None and current.class_key == class_key:
        # The role behind it does not matter: one click named the class, so it goes.
        await classes.clear_main(member.id)
        note = MAIN_CLEARED.format(klass=klass.name)

        problem = await _strip_class_role(member, classes)
        if problem is not None:
            note = f"{note}\n\n⚠️ {problem}"

        _log.info("%s cleared their main", member)
        await _answer(interaction, note)
        await client.refresh_board(MAIN_BOARD_KEY)
        return

    await _ask_role_or_record(interaction, Slot.MAIN, klass)


async def _click_alternate(interaction: discord.Interaction, class_key: str) -> None:
    """Alternates board: remove the class if listed, else add it once the checks pass."""
    member = _member_of(interaction)
    if member is None:
        await _answer(interaction, GUILD_ONLY)
        return

    client = cast("GuildBot", interaction.client)
    klass = client.classes.get(class_key)
    if klass is None:
        await _answer(interaction, UNKNOWN_CLASS)
        return

    classes = ClassRepo(client.db)
    if await classes.alternate_of(member.id, class_key) is not None:
        await classes.remove_alternate(member.id, class_key)
        _log.info("%s removed alternate %s", member, class_key)
        await _answer(interaction, ALT_REMOVED.format(klass=klass.name))
        await client.refresh_board(ALTERNATES_BOARD_KEY)
        return

    refusal = await _alternate_refusal(client, classes, member, klass)
    if refusal is not None:
        await _answer(interaction, refusal)
        return

    await _ask_role_or_record(interaction, Slot.ALTERNATE, klass)


async def _alternate_refusal(
    client: "GuildBot",
    classes: ClassRepo,
    member: discord.Member,
    klass: ClassDefinition,
) -> str | None:
    """Why this class cannot join the alternates, or None. Checked before asking the role."""
    main = await classes.main_of(member.id)
    if main is not None and main.class_key == klass.key:
        return ALT_IS_MAIN.format(klass=klass.name)

    if len(await classes.alternates_of(member.id)) >= client.classes.max_alternates:
        return ALT_FULL.format(max=client.classes.max_alternates)

    return None


async def _ask_role_or_record(
    interaction: discord.Interaction,
    slot: Slot,
    klass: ClassDefinition,
) -> None:
    """Ask which role, or record straight away when the class can only fill one."""
    client = cast("GuildBot", interaction.client)
    roles = client.classes.roles_of(klass.key)

    if len(roles) == 1:
        # Nothing to choose: a hunter is a DPS. Asking would be a message for nothing.
        await _record(interaction, slot, klass.key, roles[0].key, from_question=False)
        return

    view = ui.View(timeout=None)
    for role in roles:
        view.add_item(
            RoleButton(
                slot,
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


async def _record(
    interaction: discord.Interaction,
    slot: Slot,
    class_key: str,
    role_key: str,
    *,
    from_question: bool,
) -> None:
    """Write the choice down, answer once, then rewrite the boards that changed."""
    member = _member_of(interaction)
    if member is None or interaction.guild is None:
        await _answer(interaction, GUILD_ONLY)
        return

    client = cast("GuildBot", interaction.client)
    klass = client.classes.get(class_key)
    if klass is None:
        await _answer(interaction, UNKNOWN_CLASS)
        return

    role = client.classes.role(role_key)
    if role is None or role_key not in klass.roles:
        await _answer(interaction, UNKNOWN_ROLE)
        return

    # member_choices references members, so the member has to be recorded first.
    await MemberRepo(client.db).upsert(member.id, member.display_name)
    classes = ClassRepo(client.db)

    if slot is Slot.MAIN:
        note, keys = await _set_main(client, interaction.guild, member, klass, role, classes)
    else:
        note, keys = await _add_alternate(client, member, klass, role, classes)

    if from_question:
        await _replace(interaction, note)
    else:
        await _answer(interaction, note)

    await client.refresh_board(*keys)


async def _set_main(
    client: "GuildBot",
    guild: discord.Guild,
    member: discord.Member,
    klass: ClassDefinition,
    role: RoleDefinition,
    classes: ClassRepo,
) -> tuple[str, list[str]]:
    """Set the main character and move the Discord role along with it."""
    update = await classes.set_main(member.id, klass.key, role.key)

    note = MAIN_SET.format(klass=klass.name, role=role.label)
    replaced_key = update.replaced_class_key
    if replaced_key is not None and replaced_key != klass.key:
        replaced = client.classes.get(replaced_key)
        note += MAIN_REPLACED.format(other=replaced.name if replaced else replaced_key)

    problem = await _assign_class_role(guild, member, klass.key, classes)
    if problem is not None:
        note = f"{note}\n\n⚠️ {problem}"

    _log.info("%s mains %s %s", member, klass.key, role.key)

    # The class leaves the alternates board when it is promoted, so that one moves too.
    return note, [MAIN_BOARD_KEY, ALTERNATES_BOARD_KEY] if update.promoted else [MAIN_BOARD_KEY]


async def _add_alternate(
    client: "GuildBot",
    member: discord.Member,
    klass: ClassDefinition,
    role: RoleDefinition,
    classes: ClassRepo,
) -> tuple[str, list[str]]:
    """Add an alternate. Neither adding nor removing one touches the Discord roles."""
    # Checked again: the role question leaves time for the state to have moved.
    refusal = await _alternate_refusal(client, classes, member, klass)
    if refusal is not None:
        return refusal, []

    choice = await classes.add_alternate(
        member.id,
        klass.key,
        role.key,
        client.classes.max_choices,
    )
    if choice is None:
        return ALT_FULL.format(max=client.classes.max_alternates), []

    _log.info("%s added alternate %s %s", member, klass.key, role.key)
    return ALT_ADDED.format(klass=klass.name, role=role.label), [ALTERNATES_BOARD_KEY]


async def _assign_class_role(
    guild: discord.Guild,
    member: discord.Member,
    class_key: str,
    classes: ClassRepo,
) -> str | None:
    """Give the member their class role. Returns what went wrong, or None."""
    linked = await classes.role_ids()
    role_id = linked.get(class_key)
    if role_id is None:
        return NO_CLASS_ROLE

    role = guild.get_role(role_id)
    if role is None:
        # Deleted on Discord since it was linked.
        await classes.unlink_role(class_key)
        return NO_CLASS_ROLE

    return await apply_class_role(member, role, set(linked.values()))


async def _strip_class_role(member: discord.Member, classes: ClassRepo) -> str | None:
    """Take back whichever class role the member holds. Returns what went wrong, or None."""
    linked = await classes.role_ids()
    return await apply_class_role(member, None, set(linked.values()))
