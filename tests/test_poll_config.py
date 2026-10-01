"""Validation of the poll definitions."""

import pytest
from pydantic import ValidationError

from config import PollCatalog
from config.polls import (
    CUSTOM_ID_LIMIT,
    OPTION_LABEL_LIMIT,
    REACTIONS_PER_MESSAGE,
    SELECT_OPTIONS_LIMIT,
    PollDefinition,
    ProposalRejection,
    ProposalRules,
    build_close_custom_id,
    clean_name,
    slugify,
)


def _poll(**overrides: object) -> dict[str, object]:
    """A valid definition, before the overrides under test."""
    return {
        "key": "faction",
        "title": "Quelle faction ?",
        "options": [{"key": "alliance", "label": "Alliance", "emoji": "🔵"}],
    } | overrides


def test_the_shipped_file_is_valid(catalog: PollCatalog) -> None:
    """Guards against a typo in polls.toml reaching startup."""
    assert catalog.keys == ["faction", "royaume", "nom_guilde"]


def test_the_faction_poll_offers_the_two_factions_and_accepts_both(
    catalog: PollCatalog,
) -> None:
    """ "Peu importe" was dropped: backing both factions now says the same thing."""
    faction = catalog.get("faction")
    assert faction is not None
    assert [o.key for o in faction.options] == ["alliance", "horde"]
    assert faction.multiple


def test_the_realm_poll_offers_the_two_types_and_accepts_both(catalog: PollCatalog) -> None:
    """Built on the faction model: two sides, and backing both is an answer of its own."""
    realm = catalog.get("royaume")
    assert realm is not None
    assert [o.key for o in realm.options] == ["pve", "pvp"]
    assert realm.multiple


def test_every_structural_poll_accepts_several_answers(catalog: PollCatalog) -> None:
    """Every pre-launch poll asks which options suit a member, not which single one wins."""
    assert [p.key for p in catalog.polls if p.multiple] == catalog.keys


# --- the two ballots -----------------------------------------------------------------


def test_only_the_guild_name_poll_collects_its_options(catalog: PollCatalog) -> None:
    """Which is also what moves it off reactions: a proposed name has no emoji."""
    assert [p.key for p in catalog.polls if not p.votes_by_reaction] == ["nom_guilde"]

    names = catalog.get("nom_guilde")
    assert names is not None
    assert names.proposals is not None
    assert names.options == ()


def test_the_guild_name_poll_caps_how_many_names_one_member_backs(catalog: PollCatalog) -> None:
    names = catalog.get("nom_guilde")
    assert names is not None
    assert names.max_votes == 3


def test_only_reaction_polls_are_reconciled_on_restart(catalog: PollCatalog) -> None:
    """Reconciliation rebuilds votes from the reactions a message holds.

    A menu poll keeps its votes in the database and nowhere else, so running it through
    reconciliation would find no reaction and wipe every voice. bot.reactions.reconcile
    skips exactly these polls; this pins down which ones they are.
    """
    assert [p.key for p in catalog.polls if p.votes_by_reaction] == ["faction", "royaume"]


def test_a_reaction_poll_cannot_cap_votes() -> None:
    """Nothing stops a member adding one reaction too many; only a menu can hold a limit."""
    with pytest.raises(ValidationError, match="cannot cap votes"):
        PollDefinition.model_validate(_poll(multiple=True, max_votes=2))


def test_a_cap_needs_several_answers_to_be_allowed_at_all() -> None:
    with pytest.raises(ValidationError, match="is single"):
        PollDefinition.model_validate(_poll(options=[], proposals={}, max_votes=2, multiple=False))


def test_a_poll_collecting_options_must_not_configure_any() -> None:
    """One message cannot carry both ballots: reactions need emojis, names have none."""
    with pytest.raises(ValidationError, match="must not configure any"):
        PollDefinition.model_validate(_poll(proposals={}))


def test_a_poll_with_neither_options_nor_proposals_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no option and no proposals"):
        PollDefinition.model_validate(_poll(options=[]))


def test_a_cap_cannot_exceed_the_number_of_names_the_poll_holds() -> None:
    with pytest.raises(ValidationError, match="more than the"):
        PollDefinition.model_validate(
            _poll(options=[], multiple=True, max_votes=5, proposals={"max_options": 4})
        )


def test_the_vote_limit_never_exceeds_what_the_menu_shows() -> None:
    """A menu refuses a max_values above its own option count, so the cap is clamped."""
    definition = PollDefinition.model_validate(
        _poll(options=[], multiple=True, max_votes=3, proposals={})
    )

    assert [definition.vote_limit(count) for count in (0, 1, 2, 3, 10)] == [1, 1, 2, 3, 3]


def test_a_single_answer_poll_always_allows_one_pick() -> None:
    definition = PollDefinition.model_validate(_poll())

    assert definition.vote_limit(5) == 1


def test_every_component_of_a_poll_fits_in_a_custom_id(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        for custom_id in definition.custom_ids:
            assert len(custom_id) <= CUSTOM_ID_LIMIT


# --- what a proposed name may be -----------------------------------------------------


def test_the_shipped_rules_are_the_ones_announced(catalog: PollCatalog) -> None:
    names = catalog.get("nom_guilde")
    assert names is not None and names.proposals is not None
    assert names.proposals.max_per_member == 2
    assert names.proposals.max_options == SELECT_OPTIONS_LIMIT
    assert (names.proposals.min_length, names.proposals.max_length) == (3, 24)


@pytest.mark.parametrize(
    "name",
    ["Les Loups de Pierre", "L'Aube Écarlate", "Garde-Fou", "Ordre", "Épée de Bois"],
)
def test_a_plausible_guild_name_is_accepted(name: str) -> None:
    assert ProposalRules().rejection(name) is None


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("", ProposalRejection.EMPTY),
        ("Ab", ProposalRejection.TOO_SHORT),
        ("A" * 25, ProposalRejection.TOO_LONG),
        ("Les Loups 2", ProposalRejection.FORBIDDEN),
        ("xX_sniper_Xx", ProposalRejection.FORBIDDEN),
        ("<@everyone>", ProposalRejection.FORBIDDEN),
        ("- Les Loups", ProposalRejection.FORBIDDEN),
    ],
)
def test_what_a_name_may_not_be(name: str, reason: ProposalRejection) -> None:
    assert ProposalRules().rejection(name) is reason


def test_a_name_made_only_of_punctuation_has_no_key_to_be_stored_under() -> None:
    """Caught as unusable rather than reaching the database with an empty key."""
    assert slugify("...") == ""
    assert ProposalRules(pattern=".*").rejection("...") is ProposalRejection.UNUSABLE


def test_the_length_range_must_make_sense() -> None:
    with pytest.raises(ValidationError, match="exceeds max_length"):
        ProposalRules.model_validate({"min_length": 10, "max_length": 4})


def test_an_invalid_pattern_fails_at_load_rather_than_on_a_proposal() -> None:
    with pytest.raises(ValidationError, match="invalid proposal pattern"):
        ProposalRules.model_validate({"pattern": "[unclosed"})


def test_a_configured_pattern_replaces_the_default() -> None:
    """The game is not out: the rules on guild names may still turn out to be different."""
    rules = ProposalRules.model_validate({"pattern": r"^[A-Z]+$"})

    assert rules.rejection("ABCD") is None
    assert rules.rejection("Abcd") is ProposalRejection.FORBIDDEN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Les Loups  ", "Les Loups"),
        ("Les  Loups", "Les Loups"),
        ("Les\tLoups", "Les Loups"),
        ("Les\nLoups", "Les Loups"),
    ],
)
def test_a_name_is_stored_with_its_whitespace_collapsed(raw: str, expected: str) -> None:
    """Two spaces between two words mean one, and the label is what everyone then reads."""
    assert clean_name(raw) == expected


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Les Loups", "les_loups"),
        ("les loups", "les_loups"),
        ("LES LOUPS", "les_loups"),
        ("Lès Loups", "les_loups"),
        ("L'Aube Écarlate", "l_aube_ecarlate"),
        ("Garde-Fou", "garde_fou"),
    ],
)
def test_names_that_differ_only_by_case_or_accent_share_one_key(name: str, key: str) -> None:
    """The key is the duplicate check: UNIQUE (poll_id, key) refuses the second one."""
    assert slugify(name) == key


def test_option_pairs_keep_the_configured_order() -> None:
    definition = PollDefinition.model_validate(
        _poll(
            options=[
                {"key": "b", "label": "B", "emoji": "🅱️"},
                {"key": "a", "label": "A", "emoji": "🅰️"},
            ]
        )
    )

    assert definition.option_pairs == [("b", "B"), ("a", "A")]


def test_description_loses_its_trailing_newline() -> None:
    definition = PollDefinition.model_validate(_poll(description="Texte.\n"))

    assert definition.description == "Texte."


@pytest.mark.parametrize("key", ["Faction", "la clé", "faction!", ""])
def test_a_key_must_be_a_slug(key: str) -> None:
    """Keys end up in custom_ids matched by a regex; anything else breaks dispatch."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(key=key))


def test_an_option_label_is_capped_at_the_discord_limit() -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A" * (OPTION_LABEL_LIMIT + 1), "emoji": "🔵"}])
        )


def test_a_poll_needs_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=[]))


def test_a_poll_cannot_exceed_the_reaction_limit_of_a_message() -> None:
    """A message holds 20 distinct reactions, and a reaction is how a vote is cast."""
    options = [
        {"key": f"o{i}", "label": f"Option {i}", "emoji": f"{i}"}
        for i in range(REACTIONS_PER_MESSAGE + 1)
    ]

    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=options))


def test_duplicate_option_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate option keys"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵"},
                    {"key": "a", "label": "Autre", "emoji": "🔴"},
                ]
            )
        )


def test_two_options_cannot_share_an_emoji() -> None:
    """The emoji is the ballot: sharing one makes a reaction impossible to attribute."""
    with pytest.raises(ValidationError, match="duplicate emojis"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵"},
                    {"key": "b", "label": "B", "emoji": "🔵"},
                ]
            )
        )


def test_two_options_cannot_share_an_icon() -> None:
    with pytest.raises(ValidationError, match="duplicate emojis"):
        PollDefinition.model_validate(
            _poll(
                options=[
                    {"key": "a", "label": "A", "emoji": "🔵", "icon": "alliance"},
                    {"key": "b", "label": "B", "emoji": "🔴", "icon": "alliance"},
                ]
            )
        )


def test_an_option_without_an_emoji_is_rejected() -> None:
    """Without one there is nothing to react with, so the option could never be picked."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(options=[{"key": "a", "label": "A"}]))


@pytest.mark.parametrize("icon", ["a", "trop-de-tirets", "a" * 33, "accentué"])
def test_an_icon_must_be_a_valid_discord_emoji_name(icon: str) -> None:
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(
            _poll(options=[{"key": "a", "label": "A", "emoji": "🔵", "icon": icon}])
        )


def test_duplicate_poll_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate poll keys"):
        PollCatalog.model_validate({"polls": [_poll(), _poll(title="Encore ?")]})


def test_unknown_fields_are_rejected() -> None:
    """A misspelled field would otherwise be silently ignored."""
    with pytest.raises(ValidationError):
        PollDefinition.model_validate(_poll(titre="Quelle faction ?"))


def test_every_closing_custom_id_fits_within_the_api_limit(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        assert len(build_close_custom_id(definition.key)) <= CUSTOM_ID_LIMIT


def test_get_returns_none_for_an_unknown_key(catalog: PollCatalog) -> None:
    assert catalog.get("inconnu") is None
