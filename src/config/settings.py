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

    blizzard_client_id: str = Field(description="Client id issued by develop.battle.net")
    blizzard_client_secret: SecretStr = Field(description="Secret of the Blizzard API client")
    blizzard_region: Literal["eu", "us", "kr", "tw"] = Field(
        default="eu",
        description="API region the guild's characters live in",
    )
    blizzard_guild_slug: str = Field(
        description="Guild slug in the API, as shown in a character's profile",
    )
    professions_file: Path = Field(
        default=Path("professions.toml"),
        description="Profession icons, read at startup",
    )
    timezone: str = Field(
        default="Europe/Paris",
        description="Time zone the daily profession sync is scheduled in",
    )
    directory_sync_hour: int = Field(
        default=5,
        ge=0,
        le=23,
        description="Hour of the daily profession sync, in the configured time zone",
    )

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
