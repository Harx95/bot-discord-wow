"""Application settings, loaded from the environment and the .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. No secret is ever hardcoded: everything comes from .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: SecretStr = Field(description="Bot token issued by the Discord developer portal")
    guild_id: int = Field(description="Guild the application commands are synced to")
    gm_role_id: int = Field(description="Role allowed to run staff commands, alongside officers")
    officer_role_id: int = Field(description="Officer role, allowed to run staff commands")

    guild_name: str = Field(
        default="Ah sheep here wego again",
        description="Guild name, spelled the way the game spells it",
    )
    guild_tag: str = Field(
        default="ASHWGA",
        description="Short form of the guild name, for titles and footers",
    )

    blizzard_client_id: str = Field(
        description="Battle.net API client, created on develop.battle.net",
    )
    blizzard_client_secret: SecretStr = Field(description="Secret of that Battle.net client")
    blizzard_region: Literal["us", "eu", "kr", "tw"] = Field(
        default="eu",
        description="Battle.net region. Forever has no realms, so this alone locates the guild",
    )
    professions_channel_id: int = Field(
        default=1551292696784535712,
        description="Channel holding the profession directory and answering its commands",
    )
    profession_sync_hour: int = Field(
        default=5,
        ge=0,
        le=23,
        description="Hour, Europe/Paris, at which the roster is synced every day",
    )

    log_level: str = Field(default="INFO", description="Root logging level")
    polls_file: Path = Field(
        default=Path("polls.toml"),
        description="Poll definitions, read at startup",
    )
    classes_file: Path = Field(
        default=Path("classes.toml"),
        description="Class and raid-role definitions, read at startup",
    )
    assets_dir: Path = Field(
        default=Path("assets"),
        description="Icons uploaded as application emojis by /emojis",
    )
    database_path: Path = Field(
        default=Path("data/bot.db"),
        description="SQLite file; the parent directory is created on startup",
    )
    professions_file: Path = Field(
        default=Path("professions.toml"),
        description="Profession definitions, read at startup",
    )

    @property
    def guild_api_slug(self) -> str:
        """The guild name the way the Battle.net API addresses it.

        Blizzard lowercases the name, drops apostrophes and collapses whitespace into single
        hyphens, so "Ah sheep here wego again" is reached as "ah-sheep-here-wego-again".
        lower() rather than casefold(): Blizzard folds case the way en-US does, which leaves
        a sharp s alone where casefold() would turn it into "ss".
        """
        folded = self.guild_name.strip().lower().replace("'", "").replace("\u2019", "")
        return "-".join(folded.split())

    @property
    def staff_role_ids(self) -> frozenset[int]:
        """Roles allowed to run staff commands.

        Nobody holds two of the guild roles at once, so a staff check tests membership in
        GM or Officer rather than the absence of the Member role.
        """
        return frozenset({self.gm_role_id, self.officer_role_id})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings, parsed once per process."""
    return Settings()  # pyright: ignore[reportCallIssue] -- fields are filled from the env
