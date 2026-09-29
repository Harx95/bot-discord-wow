"""Creating class roles on Discord and assigning them safely.

Discord's hierarchy rule is not covered by the administrator permission: a bot can only
manage roles strictly below its own highest role. Every assignment is checked first so a
misconfigured hierarchy produces a clear message instead of an opaque Forbidden.
"""

import logging
from dataclasses import dataclass

import discord

from config import ClassDefinition
from db import ClassRepo

_log = logging.getLogger(__name__)

MISSING_PERMISSION = (
    "Il me manque la permission « Gérer les rôles ». "
    "Ajoute-la au rôle du bot dans les paramètres du serveur."
)
TOO_HIGH = (
    "Le rôle **{role}** est au-dessus du mien dans la hiérarchie, je ne peux pas l'attribuer. "
    "Remonte le rôle **{me}** au-dessus de **{role}** dans les paramètres du serveur, "
    "onglet Rôles."
)


@dataclass(frozen=True, slots=True)
class RoleSyncResult:
    """What a class-role synchronisation actually did."""

    created: list[str]
    reused: list[str]
    adopted: list[str]
    failed: list[tuple[str, str]]

    @property
    def changed(self) -> bool:
        """Whether anything was created."""
        return bool(self.created)


def hierarchy_error(guild: discord.Guild, role: discord.Role) -> str | None:
    """Why the bot cannot assign this role, or None if it can."""
    me = guild.me
    if not me.guild_permissions.manage_roles:
        return MISSING_PERMISSION
    if role >= me.top_role:
        return TOO_HIGH.format(role=role.name, me=me.top_role.name)
    return None


async def sync_class_roles(
    guild: discord.Guild,
    classes: tuple[ClassDefinition, ...],
    repo: ClassRepo,
) -> RoleSyncResult:
    """Create the Discord role of every class that has none yet.

    Roles are created at the bottom of the hierarchy, below the bot's own role, which is
    what makes them assignable. hoist=False keeps the member list ungrouped.
    """
    linked = await repo.role_ids()
    existing = {role.id: role for role in guild.roles}
    by_name = {role.name: role for role in guild.roles if not role.managed}

    created: list[str] = []
    reused: list[str] = []
    adopted: list[str] = []
    failed: list[tuple[str, str]] = []

    for definition in classes:
        role_id = linked.get(definition.key)
        if role_id is not None and role_id in existing:
            reused.append(definition.name)
            continue

        if role_id is not None:
            # Linked to a role that was deleted on Discord; drop the stale link.
            _log.info("Class role %r no longer exists, recreating", definition.name)
            await repo.unlink_role(definition.key)

        # A role of that name may already exist: created by a previous run whose link was
        # lost, or added by hand. Adopting it avoids piling up duplicates.
        twin = by_name.get(definition.name)
        if twin is not None:
            await repo.link_role(definition.key, twin.id)
            adopted.append(definition.name)
            _log.info("Adopted existing role %r (id=%d)", twin.name, twin.id)
            continue

        try:
            role = await guild.create_role(
                name=definition.name,
                colour=discord.Colour(definition.colour_value),
                hoist=False,
                mentionable=True,
                reason="Rôle de classe créé par le bot de guilde",
            )
        except discord.Forbidden:
            failed.append((definition.name, MISSING_PERMISSION))
            continue
        except discord.HTTPException as error:
            failed.append((definition.name, f"Discord a refusé la création : {error.text}"))
            continue

        await repo.link_role(definition.key, role.id)
        created.append(definition.name)
        _log.info("Created class role %r (id=%d)", role.name, role.id)

    return RoleSyncResult(created=created, reused=reused, adopted=adopted, failed=failed)


async def apply_class_role(
    member: discord.Member,
    new_role: discord.Role | None,
    class_role_ids: set[int],
) -> str | None:
    """Give the member their main class role and take away any other one.

    Only the main character gets a Discord role: two class roles would make the nickname
    colour depend on which role happens to sit higher. Returns an error message, or None
    on success.
    """
    guild = member.guild

    if new_role is not None:
        error = hierarchy_error(guild, new_role)
        if error is not None:
            return error

    stale = [
        role
        for role in member.roles
        if role.id in class_role_ids and (new_role is None or role.id != new_role.id)
    ]
    for role in stale:
        error = hierarchy_error(guild, role)
        if error is not None:
            return error

    try:
        if stale:
            await member.remove_roles(*stale, reason="Changement de classe principale")
        if new_role is not None and new_role not in member.roles:
            await member.add_roles(new_role, reason="Classe principale déclarée")
    except discord.Forbidden:
        return MISSING_PERMISSION
    except discord.HTTPException as error:
        return f"Discord a refusé la modification des rôles : {error.text}"

    return None
