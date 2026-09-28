"""Application settings, loaded from the environment and the .env file."""

from functools import lru_cache

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
    log_level: str = Field(default="INFO", description="Root logging level")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings, parsed once per process."""
    return Settings()  # pyright: ignore[reportCallIssue] -- fields are filled from the env
