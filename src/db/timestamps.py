"""Conversion between datetimes and the ISO-8601 strings stored by SQLite."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    """Serialise a datetime for storage, normalised to UTC."""
    return value.astimezone(UTC).isoformat()


def from_iso(value: str) -> datetime:
    """Parse a stored timestamp back into an aware datetime."""
    return datetime.fromisoformat(value)
