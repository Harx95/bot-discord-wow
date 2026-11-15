"""Client for the Blizzard Battle.net API, WoW Forever flavour.

Forever has its own namespaces (`profile-forever-eu`, `static-forever-eu`) and no realms: a
character is addressed by its `{name}-{surname}` slug alone.

aiohttp comes with discord.py, so it costs no extra dependency.
"""

import logging
import time
from typing import Any

import aiohttp

from domain import CharacterSkill, GuildCharacter, Profession

_log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth.battle.net/token"
LOCALE = "fr_FR"
FLAVOUR = "forever"

# A token lives 24 hours; renewing it a minute early avoids racing its expiry.
TOKEN_MARGIN_SECONDS = 60
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

type Json = dict[str, Any]


class BlizzardError(Exception):
    """The API answered with an error, or not at all."""


def parse_roster(payload: Json) -> list[GuildCharacter]:
    """The characters of a guild roster response."""
    characters: list[GuildCharacter] = []
    for member in payload.get("members", []):
        character = member["character"]
        characters.append(
            GuildCharacter(
                slug=character["slug"],
                name=character["name"],
                surname=character.get("surname", ""),
                level=character["level"],
            )
        )
    return characters


def parse_primary_skills(payload: Json) -> list[CharacterSkill]:
    """The primary professions of a character professions response.

    The API files Cooking, Fishing and First Aid under `secondaries`, so reading `primaries`
    alone is what keeps them out, without any list of professions in the code. A profession
    spans one tier in Forever; should several appear, the most advanced one is kept.
    """
    skills: list[CharacterSkill] = []
    for primary in payload.get("primaries", []):
        tiers = primary.get("tiers", [])
        if not tiers:
            continue
        best = max(tiers, key=lambda tier: tier["skill_points"])
        skills.append(
            CharacterSkill(
                profession_id=primary["profession"]["id"],
                skill=best["skill_points"],
                max_skill=best["max_skill_points"],
            )
        )
    return skills


class BlizzardClient:
    """Fetches the guild roster and what its characters practise.

    Holds one HTTP session and one access token, renewed when it expires. Call close()
    once done.
    """

    def __init__(self, client_id: str, client_secret: str, region: str) -> None:
        self._auth = aiohttp.BasicAuth(client_id, client_secret)
        self._region = region
        self._base = f"https://{region}.api.blizzard.com"
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def _profile_namespace(self) -> str:
        return f"profile-{FLAVOUR}-{self._region}"

    @property
    def _static_namespace(self) -> str:
        return f"static-{FLAVOUR}-{self._region}"

    def _http(self) -> aiohttp.ClientSession:
        """The session, created on first use so that it binds to the running loop."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _access_token(self) -> str:
        """A valid token, requested anew only when the previous one is about to expire."""
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token

        try:
            async with self._http().post(
                TOKEN_URL,
                auth=self._auth,
                data={"grant_type": "client_credentials"},
            ) as response:
                if response.status != 200:
                    raise BlizzardError(f"Token refused: HTTP {response.status}")
                payload = await response.json()
        except aiohttp.ClientError as error:
            raise BlizzardError(f"Token request failed: {error}") from error

        self._token = str(payload["access_token"])
        lifetime = int(payload.get("expires_in", 0))
        self._token_expires_at = time.monotonic() + max(0, lifetime - TOKEN_MARGIN_SECONDS)
        return self._token

    async def _get(self, path: str, namespace: str) -> Json | None:
        """GET an API path. None on 404, which the API uses for "not visible"."""
        token = await self._access_token()
        try:
            async with self._http().get(
                f"{self._base}{path}",
                params={"namespace": namespace, "locale": LOCALE},
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status == 404:
                    return None
                if response.status != 200:
                    raise BlizzardError(f"GET {path}: HTTP {response.status}")
                return await response.json()
        except aiohttp.ClientError as error:
            raise BlizzardError(f"GET {path} failed: {error}") from error

    async def guild_roster(self, guild_slug: str) -> list[GuildCharacter]:
        """Every character of the guild. Raises if the guild cannot be found."""
        payload = await self._get(f"/data/wow/guild/{guild_slug}/roster", self._profile_namespace)
        if payload is None:
            raise BlizzardError(f"Guild {guild_slug!r} not found")
        return parse_roster(payload)

    async def primary_skills(self, character_slug: str) -> list[CharacterSkill] | None:
        """The primary professions of a character, or None while the API does not show it.

        A character appears from level 10, and only once logged out after reaching it.
        """
        payload = await self._get(
            f"/profile/wow/character/{character_slug}/professions",
            self._profile_namespace,
        )
        if payload is None:
            return None
        return parse_primary_skills(payload)

    async def profession(self, profession_id: int) -> Profession:
        """A profession with its French name, from the static game data.

        The character endpoint names professions in English whatever the locale; the static
        data honours it.
        """
        payload = await self._get(f"/data/wow/profession/{profession_id}", self._static_namespace)
        if payload is None or not payload.get("name"):
            raise BlizzardError(f"Profession {profession_id} has no name")
        return Profession(id=profession_id, name=str(payload["name"]))
