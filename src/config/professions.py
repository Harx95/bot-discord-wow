"""Profession icons, read from TOML and validated by pydantic.

The professions themselves are not configured: they come from the Blizzard API. This file
only decorates them.
"""

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfessionIcon(BaseModel):
    """The emoji shown in front of one profession, keyed by its API id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0)
    emoji: str = Field(min_length=1)


class ProfessionCatalog(BaseModel):
    """Every configured profession icon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_emoji: str = Field(min_length=1)
    skill_cap: int = Field(gt=0)
    professions: tuple[ProfessionIcon, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Self:
        """An id listed twice would make the second emoji silently win."""
        ids = [icon.id for icon in self.professions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate profession ids: {sorted(ids)}")
        return self

    def emoji_of(self, profession_id: int) -> str:
        """The configured emoji of a profession, else the default one."""
        return next(
            (icon.emoji for icon in self.professions if icon.id == profession_id),
            self.default_emoji,
        )


def load_professions(path: Path) -> ProfessionCatalog:
    """Read and validate the profession icons."""
    with path.open("rb") as handle:
        return ProfessionCatalog.model_validate(tomllib.load(handle))
