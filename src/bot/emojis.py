"""Application emojis for class and role icons.

Icons are uploaded to the bot's application rather than to the guild: they cost none of
the 50 emoji slots a server has, and they work in every server the bot is invited to.
Until an icon is uploaded, the unicode fallback from classes.toml is used instead.
"""

import logging
from pathlib import Path

import discord

from config import ClassCatalog, emoji_name
from config.classes import EMOJI_CLASS_PREFIX, EMOJI_ROLE_PREFIX

_log = logging.getLogger(__name__)

# Discord refuses anything larger.
MAX_EMOJI_BYTES = 256 * 1024
ALLOWED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")

TOO_LARGE = "dépasse 256 Ko ({size} Ko)"
MISSING_FILE = "aucune image trouvée"


class EmojiStore:
    """The application emojis, fetched once at startup and kept by name."""

    def __init__(self, catalog: ClassCatalog) -> None:
        self._catalog = catalog
        self._by_name: dict[str, discord.Emoji] = {}

    async def refresh(self, client: discord.Client) -> None:
        """Re-read the emojis the application holds."""
        try:
            emojis = await client.fetch_application_emojis()
        except discord.HTTPException as error:
            _log.warning("Could not fetch application emojis: %s", error)
            return

        self._by_name = {emoji.name: emoji for emoji in emojis}
        _log.info("Loaded %d application emoji(s)", len(self._by_name))

    def get(self, name: str) -> discord.Emoji | None:
        """The uploaded emoji of that name, if there is one."""
        return self._by_name.get(name)

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
