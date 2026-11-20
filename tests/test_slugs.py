"""The slugs the Battle.net API addresses things by."""

from api import character_slug, encode_slug, guild_slug


def test_a_character_is_its_name_and_surname_lowercased() -> None:
    assert character_slug("Rka", "Kamechki") == "rka-kamechki"


def test_a_character_without_a_surname_is_its_name_alone() -> None:
    assert character_slug("Rka") == "rka"


def test_surrounding_space_is_trimmed() -> None:
    assert character_slug("  Rka ", " Kamechki ") == "rka-kamechki"


def test_an_empty_surname_adds_no_hyphen() -> None:
    assert character_slug("Rka", "  ") == "rka"


def test_a_guild_loses_its_apostrophes_and_gains_hyphens() -> None:
    assert guild_slug("Ah sheep here wego again") == "ah-sheep-here-wego-again"


def test_both_apostrophes_are_dropped() -> None:
    """Members type the straight one, the game shows the curly one."""
    assert guild_slug("Les Loups d'Ony\u2019x") == "les-loups-donyx"


def test_repeated_whitespace_collapses_to_one_hyphen() -> None:
    assert guild_slug("  Ah   sheep  here ") == "ah-sheep-here"


def test_a_slug_keeps_its_hyphen_when_encoded() -> None:
    """The hyphen separates the name from the surname, so it must survive encoding."""
    assert encode_slug("rka-kamechki") == "rka-kamechki"


def test_a_letter_outside_ascii_is_percent_encoded() -> None:
    assert encode_slug("krøhns-disease") == "kr%C3%B8hns-disease"
