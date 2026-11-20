"""Profession definitions, read from TOML and validated by pydantic.

The API only ever answers in English, so the French labels and the display order live here.
Nothing about a profession is hardcoded in the code: an id this file does not know is still
shown, under the name the API gave it.
"""

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.polls import KEY_MAX_LENGTH, KEY_PATTERN

NAME_LIMIT = 100
# One directory message per profession, each posted in the same channel.
MAX_PROFESSIONS = 25


class ProfessionDefinition(BaseModel):
    """One profession, as the directory shows it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, max_length=KEY_MAX_LENGTH)
    # The skill line id the profile API answers with.
    blizzard_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=NAME_LIMIT)
    # Kept out of the directory, the database and every search. Still listed here, so the
    # sync knows it is a deliberate omission rather than an id nobody configured.
    ignored: bool = False
    emoji: str | None = None

    @property
    def label(self) -> str:
        """The profession as a member reads it: its emoji, when it has one, then its name."""
        return f"{self.emoji} {self.name}" if self.emoji else self.name


class ProfessionCatalog(BaseModel):
    """Every configured profession, in file order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    professions: tuple[ProfessionDefinition, ...] = Field(
        min_length=1,
        max_length=MAX_PROFESSIONS,
    )

    @model_validator(mode="after")
    def _unique(self) -> Self:
        """Keys and Blizzard ids must both be unique: each one is used as a lookup."""
        keys = [profession.key for profession in self.professions]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate profession keys: {sorted(keys)}")

        ids = [profession.blizzard_id for profession in self.professions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate blizzard ids: {sorted(ids)}")

        return self

    @property
    def tracked(self) -> list[ProfessionDefinition]:
        """The professions the directory shows, in file order."""
        return [profession for profession in self.professions if not profession.ignored]

    @property
    def ignored_ids(self) -> frozenset[int]:
        """The API ids to drop on sight, so nothing about them is ever stored."""
        return frozenset(p.blizzard_id for p in self.professions if p.ignored)

    def get(self, key: str) -> ProfessionDefinition | None:
        """Look up one profession by its configured key."""
        return next((p for p in self.professions if p.key == key), None)

    def by_id(self, blizzard_id: int) -> ProfessionDefinition | None:
        """Look up one profession by the id the API answers with."""
        return next((p for p in self.professions if p.blizzard_id == blizzard_id), None)

    @property
    def keys(self) -> list[str]:
        """Every configured key, in file order."""
        return [profession.key for profession in self.professions]

    @property
    def blizzard_ids(self) -> list[int]:
        """Every configured Blizzard id, in file order, ignored ones included."""
        return [profession.blizzard_id for profession in self.professions]

    def order_of(self, blizzard_id: int) -> int:
        """Where a profession sits in the directory.

        An id this file does not list still reaches the directory, after the tracked ones:
        a profession Blizzard adds should show up rather than vanish.
        """
        ids = [profession.blizzard_id for profession in self.tracked]
        return ids.index(blizzard_id) if blizzard_id in ids else len(ids)


def load_professions(path: Path) -> ProfessionCatalog:
    """Read and validate the profession definitions."""
    with path.open("rb") as handle:
        return ProfessionCatalog.model_validate(tomllib.load(handle))
