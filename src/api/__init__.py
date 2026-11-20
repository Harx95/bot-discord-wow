"""Battle.net API client. The only package in the project that talks to the network."""

from api.forever import (
    PROFILE_NAMESPACE,
    STATIC_NAMESPACE,
    ForeverApiError,
    ForeverClient,
)
from api.slugs import character_slug, encode_slug, guild_slug

__all__ = [
    "PROFILE_NAMESPACE",
    "STATIC_NAMESPACE",
    "ForeverApiError",
    "ForeverClient",
    "character_slug",
    "encode_slug",
    "guild_slug",
]
