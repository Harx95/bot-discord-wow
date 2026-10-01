"""The ballot of the guild-name poll: its components, and how it renders."""

from datetime import UTC, datetime

import pytest
from discord import ui

from bot.emojis import EmojiStore
from bot.rendering import NO_PROPOSALS, NO_VOTES, poll_embed
from bot.views.poll import CANCEL_TEMPLATE, CLOSE_TEMPLATE
from bot.views.proposals import (
    CLEAR_TEMPLATE,
    PROPOSE_TEMPLATE,
    VOTE_TEMPLATE,
    ClearVotesButton,
    NameModal,
    ProposeButton,
    VoteSelect,
    _join,
    build_proposal_view,
)
from config import (
    PollCatalog,
    ProposalRules,
    build_clear_custom_id,
    build_close_custom_id,
    build_propose_custom_id,
    build_vote_custom_id,
)
from config.polls import PollDefinition
from domain import OptionTally, Poll, PollOption, PollStatus

NOW = datetime(2026, 9, 29, tzinfo=UTC)

NAMES = PollDefinition.model_validate(
    {
        "key": "nom_guilde",
        "title": "Quel nom pour la guilde ?",
        "description": "Propose le tien.",
        "multiple": True,
        "max_votes": 3,
        "proposals": {"max_per_member": 2, "min_length": 3, "max_length": 24},
    }
)

FACTION = PollDefinition.model_validate(
    {
        "key": "faction",
        "title": "Quelle faction ?",
        "multiple": True,
        "options": [
            {"key": "alliance", "label": "Alliance", "emoji": "🔵"},
            {"key": "horde", "label": "Horde", "emoji": "🔴"},
        ],
    }
)


def _poll(key: str = "nom_guilde", status: PollStatus = PollStatus.OPEN) -> Poll:
    return Poll(
        id=1,
        key=key,
        title="Quel nom pour la guilde ?",
        status=status,
        channel_id=None,
        message_id=None,
        created_at=NOW,
        closed_at=None if status is PollStatus.OPEN else NOW,
    )


def _tally(key: str, label: str, votes: int, position: int) -> OptionTally:
    return OptionTally(
        option=PollOption(
            id=position + 1,
            poll_id=1,
            key=key,
            label=label,
            position=position,
            created_by=100 + position,
            created_at=NOW,
        ),
        votes=votes,
    )


def _proposed(*names: tuple[str, int]) -> list[OptionTally]:
    """One tally per name, in the order they were proposed."""
    return [
        _tally(label.casefold().replace(" ", "_"), label, votes, position)
        for position, (label, votes) in enumerate(names)
    ]


def _select_of(view: ui.View) -> ui.Select:
    """The voting menu of a view, which must be there."""
    found = next((item for item in view.children if isinstance(item, VoteSelect)), None)
    assert found is not None
    return found.item


# --- custom_id round trip: what makes a component survive a restart ------------------


def test_every_component_is_rebuilt_from_its_own_custom_id() -> None:
    templates = {
        PROPOSE_TEMPLATE: build_propose_custom_id("nom_guilde"),
        VOTE_TEMPLATE: build_vote_custom_id("nom_guilde"),
        CLEAR_TEMPLATE: build_clear_custom_id("nom_guilde"),
    }

    for template, custom_id in templates.items():
        match = template.fullmatch(custom_id)
        assert match is not None
        assert match["poll"] == "nom_guilde"


@pytest.mark.parametrize(
    "template", [PROPOSE_TEMPLATE, VOTE_TEMPLATE, CLEAR_TEMPLATE, CLOSE_TEMPLATE, CANCEL_TEMPLATE]
)
def test_a_template_claims_only_its_own_component(template: object) -> None:
    """Four of these ids share the poll:… namespace; crossed wires would call the wrong one."""
    assert isinstance(template, type(PROPOSE_TEMPLATE))
    every_id = [
        build_propose_custom_id("nom_guilde"),
        build_vote_custom_id("nom_guilde"),
        build_clear_custom_id("nom_guilde"),
        build_close_custom_id("nom_guilde"),
        "poll:nc",
    ]

    assert sum(template.fullmatch(custom_id) is not None for custom_id in every_id) == 1


def test_the_components_of_the_shipped_poll_are_the_ones_registered(
    catalog: PollCatalog,
) -> None:
    """A component the client does not register is a silently dead button after a restart."""
    for definition in catalog.polls:
        if definition.votes_by_reaction:
            continue
        view = build_proposal_view(definition, _proposed(("Les Loups", 1)))
        for item in view.children:
            assert isinstance(item, VoteSelect | ProposeButton | ClearVotesButton)


# --- the ballot itself ----------------------------------------------------------------


def test_no_menu_is_sent_while_nothing_has_been_proposed() -> None:
    """Discord rejects a menu with no option, so the first message carries the button alone."""
    view = build_proposal_view(NAMES, [])

    assert [type(item) for item in view.children] == [ProposeButton, ClearVotesButton]


def test_the_menu_appears_with_the_first_name() -> None:
    view = build_proposal_view(NAMES, _proposed(("Les Loups", 0)))

    assert [type(item) for item in view.children] == [
        VoteSelect,
        ProposeButton,
        ClearVotesButton,
    ]


def test_the_menu_lists_the_names_most_backed_first() -> None:
    """The standings are the useful order: a proposal has no intended one."""
    view = build_proposal_view(NAMES, _proposed(("Les Loups", 1), ("L'Aube", 5), ("Garde-Fou", 3)))

    assert [option.label for option in _select_of(view).options] == [
        "L'Aube",
        "Garde-Fou",
        "Les Loups",
    ]


def test_names_with_the_same_score_keep_the_order_they_were_proposed_in() -> None:
    view = build_proposal_view(NAMES, _proposed(("Premier", 2), ("Second", 2)))

    assert [option.label for option in _select_of(view).options] == ["Premier", "Second"]


def test_each_name_carries_its_key_and_its_count() -> None:
    """The value is the key: that is what the callback looks the option up by."""
    view = build_proposal_view(NAMES, _proposed(("Les Loups", 2), ("L'Aube", 0)))
    options = _select_of(view).options

    assert [option.value for option in options] == ["les_loups", "l'aube"]
    assert [option.description for option in options] == ["2 voix", "Aucune voix"]


def test_the_menu_holds_the_member_to_the_configured_cap() -> None:
    view = build_proposal_view(NAMES, _proposed(*[(f"Nom {i}", 0) for i in range(5)]))
    select = _select_of(view)

    assert (select.min_values, select.max_values) == (1, 3)


def test_the_cap_cannot_exceed_the_number_of_names_on_offer() -> None:
    """A menu is refused outright when max_values is above its option count."""
    view = build_proposal_view(NAMES, _proposed(("Les Loups", 0), ("L'Aube", 0)))

    assert _select_of(view).max_values == 2


def test_the_menu_never_exceeds_the_twenty_five_options_discord_allows() -> None:
    """The cap on proposals makes this unreachable; the clamp is the backstop anyway."""
    view = build_proposal_view(NAMES, _proposed(*[(f"Nom {i}", 0) for i in range(30)]))

    assert len(_select_of(view).options) == 25


def test_the_menu_is_persistent_and_keeps_no_state() -> None:
    """Rebuilt from a click with no options at all: the payload carries what was picked."""
    rebuilt = VoteSelect("nom_guilde")

    assert rebuilt.item.options == []
    assert rebuilt.item.custom_id == build_vote_custom_id("nom_guilde")
    assert build_proposal_view(NAMES, []).timeout is None


# --- the modal ------------------------------------------------------------------------


def test_the_modal_carries_the_length_rules_into_discord() -> None:
    """The commonest mistake then becomes a field that simply will not submit."""
    rules = ProposalRules(min_length=4, max_length=12)
    modal = NameModal(NAMES, rules)

    assert (modal.name.min_length, modal.name.max_length) == (4, 12)


def test_the_modal_fits_what_discord_accepts() -> None:
    modal = NameModal(NAMES, ProposalRules())

    assert len(modal.title) <= 45
    assert len(modal.label.text) <= 45
    assert modal.label.description is not None
    assert len(modal.label.description) <= 100


def test_the_modal_states_the_rules_under_the_field() -> None:
    """Read before the mistake, rather than as a refusal after it."""
    modal = NameModal(NAMES, ProposalRules(min_length=4, max_length=12))

    assert modal.label.description is not None
    assert "4" in modal.label.description
    assert "12" in modal.label.description


def test_the_field_submits_its_value_through_its_label() -> None:
    """A Label-wrapped input is reached by walk_children, which is how a modal reads it."""
    modal = NameModal(NAMES, ProposalRules())

    assert modal.name in list(modal.walk_children())


# --- what a member is told ------------------------------------------------------------


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["A"], "**A**"),
        (["A", "B"], "**A** et **B**"),
        (["A", "B", "C"], "**A**, **B** et **C**"),
    ],
)
def test_names_are_read_back_as_a_french_enumeration(labels: list[str], expected: str) -> None:
    assert _join(labels) == expected


def test_a_name_holding_markdown_cannot_style_the_answer() -> None:
    assert _join(["*Les Loups*"]) == "**\\*Les Loups\\***"


# --- the embed ------------------------------------------------------------------------


def test_an_empty_poll_says_how_to_start_it(emojis: EmojiStore) -> None:
    """A poll with no option at all is a different kind of empty from one with no vote."""
    embed = poll_embed(_poll(), NAMES, [], emojis, voters=0)

    assert embed.description is not None
    assert NO_PROPOSALS in embed.description


def test_names_with_no_vote_yet_read_as_an_unvoted_poll(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), NAMES, _proposed(("Les Loups", 0)), emojis, voters=0)

    assert embed.description is not None
    assert NO_VOTES in embed.description


def test_the_embed_ranks_the_names(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), NAMES, _proposed(("Les Loups", 1), ("L'Aube", 5)), emojis, voters=3)

    assert embed.description is not None
    assert embed.description.index("L'Aube") < embed.description.index("Les Loups")


def test_the_footer_tells_the_turnout_and_the_cap(emojis: EmojiStore) -> None:
    """Six voices from two people is the shape a capped multi-vote poll needs stated."""
    embed = poll_embed(_poll(), NAMES, _proposed(("Les Loups", 4), ("L'Aube", 2)), emojis, voters=2)

    assert embed.footer.text is not None
    assert "6 voix de 2 participant(s)" in embed.footer.text
    assert "3 noms" in embed.footer.text
    assert "menu" in embed.footer.text


def test_a_reaction_poll_still_counts_votes_alone(emojis: EmojiStore) -> None:
    """Its voters are visible on the message itself, so the footer does not repeat them."""
    embed = poll_embed(_poll("faction"), FACTION, _proposed(("Alliance", 1)), emojis)

    assert embed.footer.text is not None
    assert embed.footer.text.startswith("1 vote ")
    assert "Réagis" in embed.footer.text


def test_a_closed_menu_poll_says_so(emojis: EmojiStore) -> None:
    embed = poll_embed(
        _poll(status=PollStatus.CLOSED), NAMES, _proposed(("Les Loups", 1)), emojis, voters=1
    )

    assert embed.footer.text is not None
    assert "clos" in embed.footer.text
    assert "menu" not in embed.footer.text
