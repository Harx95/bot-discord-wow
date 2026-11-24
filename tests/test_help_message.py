"""The help message pinned in the professions channel is pasted into Discord by hand.

Nothing reads it at runtime, so the one thing worth guarding is the only way it can
fail: a message over 2000 characters is refused outright, and the paste is lost.
"""

from pathlib import Path

MESSAGE_LIMIT = 2000
HELP = Path(__file__).resolve().parents[1] / "docs" / "aide-metiers.md"


def test_the_help_message_fits_in_one_discord_message() -> None:
    assert len(HELP.read_text(encoding="utf-8")) <= MESSAGE_LIMIT


def test_the_help_message_names_both_commands() -> None:
    text = HELP.read_text(encoding="utf-8")

    assert "/qui-métier" in text
    assert "/recettes" in text
