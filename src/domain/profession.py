"""Guild characters and the professions they practise, as the Blizzard API reports them."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuildCharacter:
    """A character on the guild roster.

    WoW Forever has no realms: the slug, `{name}-{surname}` lowercased, identifies a
    character on its own.
    """

    slug: str
    name: str
    surname: str
    level: int

    @property
    def full_name(self) -> str:
        """First name and surname. First names alone are not unique in Forever."""
        return f"{self.name} {self.surname}".strip()


@dataclass(frozen=True, slots=True)
class Profession:
    """A profession with its display name, in French."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class CharacterSkill:
    """One primary profession of a character and how far it was trained."""

    profession_id: int
    skill: int
    # The cap of the tier the character trained up to, not the game's maximum.
    max_skill: int


@dataclass(frozen=True, slots=True)
class DirectoryLine:
    """One character under one profession, as the directory lists them."""

    profession: Profession
    character_name: str
    skill: int
    max_skill: int
