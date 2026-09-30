"""Custom emojis for class, role and poll icons.

Two sources, looked up in this order:

- the guild's own emojis, which is where the icons were put by hand;
- the bot's application emojis, which /emojis uploads and which cost none of the 50 slots
  a server has.

The unicode fallback from classes.toml or polls.toml is used until one of the two holds
the icon, so a missing image degrades the display and never breaks a command.
"""

import logging
from pathlib import Path

import discord

from config import ClassCatalog, OptionDefinition, emoji_name
from config.classes import EMOJI_CLASS_PREFIX, EMOJI_ROLE_PREFIX

_log = logging.getLogger(__name__)

# Discord refuses anything larger.
MAX_EMOJI_BYTES = 256 * 1024
ALLOWED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")

TOO_LARGE = "dépasse 256 Ko ({size} Ko)"
MISSING_FILE = "aucune image trouvée"


class EmojiStore:
    """The custom emojis the bot can use, fetched once at startup and kept by name."""

    def __init__(self, catalog: ClassCatalog, guild_id: int) -> None:
        self._catalog = catalog
        self._guild_id = guild_id
        self._guild: dict[str, discord.Emoji] = {}
        self._application: dict[str, discord.Emoji] = {}

    async def refresh(self, client: discord.Client) -> None:
        """Re-read both sources. A source that fails leaves the other one usable."""
        self._guild = await self._fetch_guild_emojis(client)
        self._application = await self._fetch_application_emojis(client)
        _log.info(
            "Loaded %d guild emoji(s) and %d application emoji(s)",
            len(self._guild),
            len(self._application),
        )

    async def _fetch_guild_emojis(self, client: discord.Client) -> dict[str, discord.Emoji]:
        """The guild's emojis, over HTTP.

        Fetched rather than read from the cache: refresh runs in setup_hook, before the
        guild cache is populated, and fetching needs no extra intent.
        """
        try:
            guild = await client.fetch_guild(self._guild_id)
            emojis = await guild.fetch_emojis()
        except discord.HTTPException as error:
            _log.warning("Could not fetch the guild emojis: %s", error)
            return {}

        return {emoji.name: emoji for emoji in emojis}

    async def _fetch_application_emojis(self, client: discord.Client) -> dict[str, discord.Emoji]:
        """The emojis /emojis uploaded to the application."""
        try:
            emojis = await client.fetch_application_emojis()
        except discord.HTTPException as error:
            _log.warning("Could not fetch the application emojis: %s", error)
            return {}

        return {emoji.name: emoji for emoji in emojis}

    def get(self, name: str) -> discord.Emoji | None:
        """The emoji of that name, the guild's taking precedence over the application's."""
        return self._guild.get(name) or self._application.get(name)

    def for_class(self, class_key: str) -> discord.Emoji | str | None:
        """Icon of a class: the uploaded one, else the configured fallback."""
        uploaded = self.get(emoji_name(EMOJI_CLASS_PREFIX, class_key))
        if uploaded is not None:
            return uploaded
        klass = self._catalog.get(class_key)
        return klass.emoji if klass is not None else None

    def for_role(self, role_key: str) -> discord.Emoji | str | None:
        """Icon of a raid role: the uploaded one, else the configured fallback."""
        uploaded = self.get(emoji_name(EMOJI_ROLE_PREFIX, role_key))
        if uploaded is not None:
            return uploaded
        role = self._catalog.role(role_key)
        return role.emoji if role is not None else None

    def for_option(self, option: OptionDefinition) -> discord.Emoji | str:
        """The ballot of a poll option: the custom icon, else the configured unicode emoji.

        Never None: an option always has a unicode emoji, so a poll can always be voted on
        even when its icons are missing from the server.
        """
        if option.icon is None:
            return option.emoji
        return self.get(option.icon) or option.emoji

    def rendered_option(self, option: OptionDefinition) -> str:
        """Ballot of a poll option as it appears inside an embed."""
        return _rendered(self.for_option(option))

    def rendered_class(self, class_key: str) -> str:
        """Icon of a class as it appears inside an embed, or an empty string."""
        return _rendered(self.for_class(class_key))

    def rendered_role(self, role_key: str) -> str:
        """Icon of a raid role as it appears inside an embed, or an empty string."""
        return _rendered(self.for_role(role_key))


def _rendered(icon: discord.Emoji | str | None) -> str:
    """An icon as embed markup. Custom emojis need their full <:name:id> form."""
    if icon is None:
        return ""
    return str(icon)


def icon_path(directory: Path, key: str) -> Path | None:
    """The image of an icon, whatever extension it was saved with."""
    for suffix in ALLOWED_SUFFIXES:
        candidate = directory / f"{key}{suffix}"
        if candidate.is_file():
            return candidate
    return None


async def upload_missing_icons(
    client: discord.Client,
    catalog: ClassCatalog,
    store: EmojiStore,
    assets: Path,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Upload every icon the application does not have yet.

    Returns the names uploaded, those already present, and the ones that failed with why.
    Idempotent: running it again only sends what is still missing.
    """
    wanted = [(klass.icon_name, assets / "classes", klass.key) for klass in catalog.classes] + [
        (role.icon_name, assets / "roles", role.key) for role in catalog.roles
    ]

    uploaded: list[str] = []
    present: list[str] = []
    failed: list[tuple[str, str]] = []

    for name, directory, key in wanted:
        if store.get(name) is not None:
            present.append(name)
            continue

        path = icon_path(directory, key)
        if path is None:
            failed.append((name, MISSING_FILE))
            continue

        image = path.read_bytes()
        if len(image) > MAX_EMOJI_BYTES:
            failed.append((name, TOO_LARGE.format(size=len(image) // 1024)))
            continue

        try:
            await client.create_application_emoji(name=name, image=image)
        except discord.HTTPException as error:
            failed.append((name, f"Discord a refusé l'envoi : {error.text}"))
            continue

        uploaded.append(name)
        _log.info("Uploaded application emoji %r from %s", name, path)

    if uploaded:
        await store.refresh(client)

    return uploaded, present, failed
