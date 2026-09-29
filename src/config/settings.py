"""Application settings, loaded from the environment and the .env file."""

from functools import lru_cache
from pathlib import Path

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
    database_path: Path = Field(
        default=Path("data/bot.db"),
        description="SQLite file; the parent directory is created on startup",
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
