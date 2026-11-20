"""Profession entities: who is in the guild, what they know, and what a recipe is called.

The API answers in English only, so a recipe name is carried in both languages: the English
one the professions endpoint gives, and the French one the static recipe endpoint gives.
"""

from dataclasses import dataclass, field
from datetime import datetime

from domain.text import fold


@dataclass(frozen=True, slots=True)
class RosterCharacter:
    """One guild member's character, as the roster endpoint describes it.

    The roster supplies the slug itself, so it is never rebuilt from the name here.
    """

    slug: str
    name: str
    surname: str | None
    level: int
    character_id: int | None
    class_id: int | None
    rank: int

    @property
    def display_name(self) -> str:
        """The character as a member of the guild says it: "Rka-Kamechki"."""
        return f"{self.name}-{self.surname}" if self.surname else self.name

    @property
    def is_visible_to_api(self) -> bool:
        """Whether the profile endpoints will answer for this character.

        Blizzard hides characters below level 10, and only publishes them once they have
        logged out, so asking about one is a wasted request rather than an error.
        """
        return self.level >= VISIBLE_LEVEL


# Below this, every profile endpoint answers 404.
VISIBLE_LEVEL = 10


@dataclass(frozen=True, slots=True)
class CharacterProfession:
    """A profession one character has, at the skill it has reached.

    max_skill is the cap of the tier reached, not 300: a character who has not bought the
    next rank yet is capped at 75, 150 or 225, and showing 212/225 is the honest figure.
    """

    slug: str
    blizzard_id: int
    api_name: str
    skill: int
    max_skill: int

    @property
    def is_capped(self) -> bool:
        """Whether this profession has nothing left to learn at its current rank."""
        return self.max_skill > 0 and self.skill >= self.max_skill


@dataclass(frozen=True, slots=True)
class Recipe:
    """A recipe, named in both languages, and the item it makes when it makes one.

    87 of the 589 recipes the guild knows craft no item: enchantments, and the pseudo-recipes
    of the gathering professions. Both names are searched, so either one finds it.
    """

    recipe_id: int
    name_en: str
    name_fr: str | None
    crafted_item_id: int | None
    crafted_name_en: str | None
    crafted_name_fr: str | None

    @property
    def display_name(self) -> str:
        """What the bot shows: French when Blizzard has it, English otherwise."""
        return self.name_fr or self.name_en

    @property
    def search_terms(self) -> list[str]:
        """Every folded form this recipe can be found by, without duplicates."""
        candidates = (
            self.name_en,
            self.name_fr,
            self.crafted_name_en,
            self.crafted_name_fr,
        )
        seen: dict[str, None] = {}
        for candidate in candidates:
            if candidate:
                seen.setdefault(fold(candidate), None)
        return list(seen)


@dataclass(frozen=True, slots=True)
class Artisan:
    """One answer to "who can craft this": a character, a profession, a recipe."""

    character: str
    blizzard_id: int
    profession_name: str
    skill: int
    max_skill: int
    recipe_id: int
    recipe_name: str


@dataclass(frozen=True, slots=True)
class DirectoryRow:
    """One line of the directory: a character and their skill in one profession."""

    character: str
    skill: int
    max_skill: int


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What one sync did, for the command that triggered it and for the directory footer."""

    started_at: datetime
    finished_at: datetime
    characters: int
    skipped: int
    professions: int
    recipe_links: int
    recipes_fetched: int
    failures: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()
