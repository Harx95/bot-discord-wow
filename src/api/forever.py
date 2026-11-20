"""Client for the WoW: Forever endpoints of the Battle.net API.

Blizzard has not documented the forever namespaces (November 2026). Everything below was
read off the live API on 20 November 2026 against the guild's own roster, and the surprises
are worth stating because they drive the design:

- The **profile** namespace ignores `locale` entirely and always answers in English, even
  with `locale=fr_FR`. Profession and recipe names arrive as plain English strings.
- The **static** namespace does localise: `/data/wow/recipe/{id}` answers with `name` as an
  object keyed by locale, 12 of them, plus the crafted item. That is the only place French
  comes from, which is why a recipe is fetched twice over its life rather than once.
- Forever has no realms. A character is `{name}-{surname}`, a guild is its slug, both
  addressed with no realm segment at all.
- Characters below level 10, or who have never logged out, answer 404 everywhere.
- Concurrency has to stay low: at 8 parallel requests, 44 of 589 recipe lookups came back
  429. At 4, with Retry-After honoured, none did.

The session is injected so tests never reach the network.
"""

import asyncio
import base64
import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import aiohttp

from api.slugs import encode_slug
from domain import CharacterProfession, Recipe, RosterCharacter

_log = logging.getLogger(__name__)

# A decoded JSON object. Its values really are heterogeneous, and every one of them is
# narrowed with isinstance before it is used.
type Payload = dict[str, Any]

TOKEN_URL = "https://oauth.battle.net/token"
PROFILE_NAMESPACE = "profile-forever-{region}"
STATIC_NAMESPACE = "static-forever-{region}"

# Taken a minute before it really expires, so a request never carries a token that dies in
# flight. Blizzard issues them for 24 hours.
EXPIRY_MARGIN_SECONDS = 60
# Measured: 8 was too many, 4 was clean.
DEFAULT_CONCURRENCY = 4
# A 429 without a Retry-After header still deserves a pause.
DEFAULT_RETRY_SECONDS = 2.0
MAX_ATTEMPTS = 4
REQUEST_TIMEOUT_SECONDS = 30


class ForeverApiError(RuntimeError):
    """A call that neither succeeded nor simply found nothing.

    A missing character is not an error: those answer None. This is raised for a refused
    token, a server-side failure, a body that is not the shape expected, or a 429 that
    outlived its retries.
    """

    def __init__(self, path: str, status: int | None, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.status = status

    @property
    def retryable(self) -> bool:
        """Whether the same call could work later."""
        return self.status is None or self.status == 429 or self.status >= 500


def _localised(value: object, locale: str) -> str | None:
    """One locale out of a name, whichever shape the namespace answered with.

    The profile namespace gives a plain string, the static one an object keyed by locale.
    Both occur in the same sync, so both are accepted here rather than at each call site.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        found = value.get(locale)
        return found if isinstance(found, str) and found else None
    return None


def _english(value: object) -> str | None:
    """A name in English, taking either British or American spelling."""
    if isinstance(value, str):
        return value or None
    return _localised(value, "en_GB") or _localised(value, "en_US")


class ForeverClient:
    """Reads the guild roster, a character's professions, and a recipe's names."""

    def __init__(
        self,
        region: str,
        client_id: str,
        client_secret: str,
        session: aiohttp.ClientSession,
        concurrency: int = DEFAULT_CONCURRENCY,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
    ) -> None:
        self._region = region
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._gate = asyncio.Semaphore(concurrency)
        # How long to wait when Blizzard does not say; the tests set it near zero.
        self._retry_seconds = retry_seconds
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def base_url(self) -> str:
        return f"https://{self._region}.api.blizzard.com"

    @property
    def profile_namespace(self) -> str:
        return PROFILE_NAMESPACE.format(region=self._region)

    @property
    def static_namespace(self) -> str:
        return STATIC_NAMESPACE.format(region=self._region)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    # --- plumbing ------------------------------------------------------------------

    async def _access_token(self, force: bool = False) -> str:
        """A client-credentials token, kept until just before it expires."""
        loop = asyncio.get_running_loop()
        if not force and self._token is not None and loop.time() < self._token_expires_at:
            return self._token

        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        try:
            async with self._session.post(
                TOKEN_URL,
                headers={"Authorization": f"Basic {basic}"},
                data={"grant_type": "client_credentials"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status != 200:
                    # The body may echo the client id, so it is never logged or re-raised.
                    raise ForeverApiError(
                        "/token",
                        response.status,
                        f"Blizzard refused the token request "
                        f"({response.status}). Check BLIZZARD_CLIENT_ID and "
                        f"BLIZZARD_CLIENT_SECRET.",
                    )
                payload = await response.json()
        except aiohttp.ClientError as error:
            raise ForeverApiError("/token", None, f"Could not reach Blizzard: {error}") from error

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ForeverApiError("/token", 200, "Blizzard's token response carried no token")

        lifetime = payload.get("expires_in")
        seconds = lifetime if isinstance(lifetime, int | float) and lifetime > 0 else 3600
        self._token = token
        self._token_expires_at = loop.time() + max(seconds - EXPIRY_MARGIN_SECONDS, 1)
        return token

    async def _get(self, path: str, namespace: str) -> Payload | None:
        """One GET, retried on 429 and on a dropped connection. None for a 404."""
        last: ForeverApiError | None = None
        # A 401 means the token died early, so the next attempt takes a fresh one.
        renew = False

        for attempt in range(MAX_ATTEMPTS):
            async with self._gate:
                token = await self._access_token(force=renew)
                renew = False
                try:
                    async with self._session.get(
                        f"{self.base_url}{path}",
                        params={"namespace": namespace},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                    ) as response:
                        if response.status == 404:
                            return None
                        if response.status == 200:
                            self._log_quota(response.headers)
                            body = await response.json()
                            if not isinstance(body, dict):
                                raise ForeverApiError(path, 200, f"{path}: expected a JSON object")
                            return body

                        if response.status == 429:
                            last = ForeverApiError(path, 429, f"{path}: rate limited")
                            delay = self._retry_after(response.headers, self._retry_seconds)
                        elif response.status == 401:
                            last = ForeverApiError(path, 401, f"{path}: token rejected")
                            renew = True
                            delay = 0.0
                        elif response.status >= 500:
                            last = ForeverApiError(
                                path,
                                response.status,
                                f"{path}: Blizzard answered {response.status}",
                            )
                            delay = self._retry_seconds
                        else:
                            raise ForeverApiError(
                                path,
                                response.status,
                                f"{path}: Blizzard answered {response.status}",
                            )
                except aiohttp.ClientError as error:
                    last = ForeverApiError(path, None, f"{path}: {error}")
                    delay = self._retry_seconds

            if attempt < MAX_ATTEMPTS - 1:
                _log.debug("Retrying %s in %.1fs (%s)", path, delay, last)
                await asyncio.sleep(delay)

        raise last or ForeverApiError(path, None, f"{path}: gave up")

    @staticmethod
    def _retry_after(headers: Mapping[str, str], fallback: float) -> float:
        """How long Blizzard asked us to wait, or the configured fallback."""
        raw = headers.get("Retry-After")
        try:
            return max(float(raw), 0.0) if raw is not None else fallback
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _log_quota(headers: Mapping[str, str]) -> None:
        """Note how much of the hourly plan is spent, when Blizzard says."""
        current = headers.get("x-plan-quota-current")
        allotted = headers.get("x-plan-quota-allotted")
        if current or allotted:
            _log.debug("Blizzard quota %s/%s", current, allotted)

    # --- endpoints -----------------------------------------------------------------

    async def guild_roster(self, slug: str) -> list[RosterCharacter] | None:
        """Every character in the guild. None when the slug names no guild."""
        payload = await self._get(
            f"/data/wow/guild/{encode_slug(slug)}/roster", self.profile_namespace
        )
        if payload is None:
            return None

        members = payload.get("members")
        if not isinstance(members, list):
            raise ForeverApiError(
                f"/data/wow/guild/{slug}/roster", 200, "the roster carried no member list"
            )

        characters: list[RosterCharacter] = []
        for member in members:
            character = member.get("character") if isinstance(member, dict) else None
            if not isinstance(character, dict):
                continue
            name = character.get("name")
            if not isinstance(name, str) or not name:
                continue
            surname = character.get("surname")
            surname = surname if isinstance(surname, str) and surname else None
            stored = character.get("slug")
            characters.append(
                RosterCharacter(
                    slug=stored
                    if isinstance(stored, str) and stored
                    else "-".join(p for p in (name, surname) if p).lower(),
                    name=name,
                    surname=surname,
                    level=int(character.get("level") or 0),
                    character_id=character.get("id"),
                    class_id=(character.get("playable_class") or {}).get("id"),
                    rank=int(member.get("rank") or 0),
                )
            )
        return characters

    async def guild_ruleset(self, slug: str) -> tuple[int | None, str | None] | None:
        """The guild's ruleset, as (id, French name). Forever's stand-in for a realm."""
        payload = await self._get(f"/data/wow/guild/{encode_slug(slug)}", self.profile_namespace)
        if payload is None:
            return None
        ruleset = payload.get("ruleset") or {}
        return ruleset.get("id"), _localised(ruleset.get("name"), "fr_FR")

    async def character_professions(
        self, slug: str
    ) -> tuple[list[CharacterProfession], list[tuple[int, int, str]]] | None:
        """One character's professions, and the recipes they know.

        The recipes come back as (blizzard_id, recipe_id, English name): the professions
        endpoint carries the English name, so nothing has to be fetched before a recipe is
        searchable. None when the character is not published -- below level 10, or never
        logged out.
        """
        payload = await self._get(
            f"/profile/wow/character/{encode_slug(slug)}/professions", self.profile_namespace
        )
        if payload is None:
            return None

        professions: list[CharacterProfession] = []
        recipes: list[tuple[int, int, str]] = []

        for bucket in ("primaries", "secondaries"):
            entries = payload.get(bucket)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                profession = entry.get("profession") or {}
                blizzard_id = profession.get("id")
                if not isinstance(blizzard_id, int):
                    continue
                api_name = _english(profession.get("name")) or f"#{blizzard_id}"

                # One tier per profession in Forever, but the shape allows several and
                # taking the best-skilled one is right either way.
                skill = 0
                max_skill = 0
                for tier in entry.get("tiers") or []:
                    if not isinstance(tier, dict):
                        continue
                    tier_skill = int(tier.get("skill_points") or 0)
                    if tier_skill >= skill:
                        skill = tier_skill
                        max_skill = int(tier.get("max_skill_points") or 0)
                    for known in tier.get("known_recipes") or []:
                        if not isinstance(known, dict):
                            continue
                        recipe_id = known.get("id")
                        name = _english(known.get("name"))
                        if isinstance(recipe_id, int) and name:
                            recipes.append((blizzard_id, recipe_id, name))

                professions.append(
                    CharacterProfession(
                        slug=slug,
                        blizzard_id=blizzard_id,
                        api_name=api_name,
                        skill=skill,
                        max_skill=max_skill,
                    )
                )

        return professions, recipes

    async def recipe(self, recipe_id: int) -> Recipe | None:
        """A recipe's names in both languages, and the item it crafts.

        This is the static namespace, the only one that localises. 87 of the 589 recipes the
        guild knows craft no item -- enchantments, and the gathering pseudo-recipes -- so a
        missing crafted item is normal rather than a failure.
        """
        payload = await self._get(f"/data/wow/recipe/{recipe_id}", self.static_namespace)
        if payload is None:
            return None

        name = payload.get("name")
        name_en = _english(name)
        if not name_en:
            raise ForeverApiError(
                f"/data/wow/recipe/{recipe_id}", 200, "the recipe carried no English name"
            )

        crafted = payload.get("crafted_item") or {}
        return Recipe(
            recipe_id=recipe_id,
            name_en=name_en,
            name_fr=_localised(name, "fr_FR"),
            crafted_item_id=crafted.get("id"),
            crafted_name_en=_english(crafted.get("name")),
            crafted_name_fr=_localised(crafted.get("name"), "fr_FR"),
        )
