"""Reaction dispatch, closing buttons, staff checks and embed rendering."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import discord
import pytest

from bot.emojis import EmojiStore
from bot.permissions import is_staff
from bot.reactions import ReactionEmoji, ballot_of
from bot.rendering import NO_VOTES, poll_embed, results_embed
from bot.views.poll import (
    CANCEL_TEMPLATE,
    CLOSE_TEMPLATE,
    CloseCancelButton,
    CloseConfirmButton,
    build_close_confirmation_view,
)
from config import CANCEL_CLOSE_CUSTOM_ID, PollCatalog, build_close_custom_id
from config.polls import PollDefinition
from domain import OptionTally, Poll, PollOption, PollStatus

NOW = datetime(2026, 9, 29, tzinfo=UTC)

DEFINITION = PollDefinition.model_validate(
    {
        "key": "faction",
        "title": "Quelle faction ?",
        "description": "Vote décisif.",
        "multiple": True,
        "options": [
            {"key": "alliance", "label": "Alliance", "emoji": "🔵", "icon": "alliance"},
            {"key": "horde", "label": "Horde", "emoji": "🔴", "icon": "horde"},
        ],
    }
)

# No shipped poll is single-choice any more, both structural ones accept several answers.
# This sample keeps that mode, and the unicode fallback, under test.
SINGLE = PollDefinition.model_validate(
    {
        "key": "exemple",
        "title": "Un sondage à choix unique",
        "options": [
            {"key": "oui", "label": "Oui", "emoji": "✔️"},
            {"key": "non", "label": "Non", "emoji": "✖️"},
        ],
    }
)


def _poll(status: PollStatus = PollStatus.OPEN) -> Poll:
    return Poll(
        id=1,
        key="faction",
        title="Quelle faction ?",
        status=status,
        channel_id=None,
        message_id=None,
        created_at=NOW,
        closed_at=None if status is PollStatus.OPEN else NOW,
    )


def _tallies(*counts: int) -> list[OptionTally]:
    return [
        OptionTally(
            option=PollOption(
                id=index,
                poll_id=1,
                key=option.key,
                label=option.label,
                position=index,
                created_by=None,
                created_at=NOW,
            ),
            votes=votes,
        )
        for index, (option, votes) in enumerate(zip(DEFINITION.options, counts, strict=True))
    ]


# --- ballot round trip: this is what makes a reaction land on the right option --------


def test_a_unicode_reaction_reads_as_its_character() -> None:
    assert ballot_of(discord.PartialEmoji(name="🔵")) == "🔵"


def test_a_custom_reaction_reads_as_its_name() -> None:
    """Matched by name, not by id, so re-uploading an icon keeps the votes attached."""
    assert ballot_of(discord.PartialEmoji(name="alliance", id=123)) == "alliance"


def test_a_reaction_given_as_a_plain_string_reads_as_itself() -> None:
    """Message.reactions hands unicode emojis over as str rather than PartialEmoji."""
    assert ballot_of(cast(ReactionEmoji, "🔴")) == "🔴"


def test_every_configured_option_is_found_back_from_its_ballot(catalog: PollCatalog) -> None:
    """The reaction equivalent of the old custom_id round trip: no option may go dead."""
    for definition in catalog.polls:
        for option in definition.options:
            assert definition.option_for_ballot(option.ballot) is option


def test_an_icon_wins_over_the_unicode_fallback_as_a_ballot() -> None:
    alliance = DEFINITION.options[0]

    assert alliance.ballot == "alliance"
    assert DEFINITION.option_for_ballot("alliance") is alliance


def test_the_unicode_fallback_is_the_ballot_when_no_icon_is_configured() -> None:
    assert SINGLE.options[0].ballot == "✔"


@pytest.mark.parametrize("reacted", ["✔️", "✔"])
def test_a_variation_selector_does_not_change_which_option_is_meant(reacted: str) -> None:
    """Discord does not always echo U+FE0F back, so both forms must resolve."""
    option = SINGLE.option_for_ballot(reacted)

    assert option is not None
    assert option.key == "oui"


def test_an_emoji_nobody_offered_resolves_to_nothing() -> None:
    """That is what tells the handler to take the reaction off the message."""
    assert DEFINITION.option_for_ballot("🍕") is None
    assert DEFINITION.option_for_ballot("horde_bis") is None


# --- closing a poll ------------------------------------------------------------------


def test_the_close_template_matches_every_configured_poll(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        match = CLOSE_TEMPLATE.fullmatch(build_close_custom_id(definition.key))

        assert match is not None
        assert match["poll"] == definition.key


def test_the_cancel_template_matches_its_custom_id() -> None:
    assert CANCEL_TEMPLATE.fullmatch(CANCEL_CLOSE_CUSTOM_ID) is not None


def test_every_poll_custom_id_matches_exactly_one_template(catalog: PollCatalog) -> None:
    """Two matches would make the handler depend on registration order; none would be dead."""
    templates = (CLOSE_TEMPLATE, CANCEL_TEMPLATE)

    sent = [CANCEL_CLOSE_CUSTOM_ID]
    sent.extend(build_close_custom_id(definition.key) for definition in catalog.polls)

    for custom_id in sent:
        matching = [t for t in templates if t.fullmatch(custom_id) is not None]
        assert len(matching) == 1, f"{custom_id} matched {len(matching)} templates"


async def test_from_custom_id_restores_the_poll_being_closed() -> None:
    """After a restart the confirmation has to know which poll it was about."""
    match = CLOSE_TEMPLATE.fullmatch(build_close_custom_id("faction"))
    assert match is not None

    button = await CloseConfirmButton.from_custom_id(
        cast(discord.Interaction, None),
        cast(discord.ui.Item[discord.ui.View], None),
        match,
    )

    assert button.poll_key == "faction"


def test_the_confirmation_offers_a_way_out_and_looks_destructive() -> None:
    view = build_close_confirmation_view("faction")

    assert view.timeout is None
    assert len(view.children) == 2
    assert all(item.is_persistent() for item in view.children)

    confirm, cancel = view.children
    assert isinstance(confirm, CloseConfirmButton)
    assert isinstance(cancel, CloseCancelButton)
    assert confirm.item.style is discord.ButtonStyle.danger
    assert cancel.item.style is discord.ButtonStyle.secondary


# --- staff check ---------------------------------------------------------------------


def _member_with(*role_ids: int) -> discord.Member:
    roles = [SimpleNamespace(id=role_id) for role_id in role_ids]
    return cast(discord.Member, SimpleNamespace(roles=roles))


def test_a_gm_is_staff() -> None:
    assert is_staff(_member_with(1, 10), frozenset({10, 20}))


def test_an_officer_is_staff() -> None:
    assert is_staff(_member_with(20), frozenset({10, 20}))


def test_a_plain_member_is_not_staff() -> None:
    """Members hold exactly one guild role, so this is a positive test, never an absence."""
    assert not is_staff(_member_with(30), frozenset({10, 20}))


def test_someone_with_no_role_is_not_staff() -> None:
    assert not is_staff(_member_with(), frozenset({10, 20}))


# --- rendering -----------------------------------------------------------------------


def test_an_empty_poll_shows_a_placeholder_rather_than_zeroes(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(0, 0), emojis)

    assert embed.description is not None
    assert NO_VOTES in embed.description
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("0 vote ")


def test_counts_and_shares_are_rendered(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(3, 1), emojis)

    assert embed.description is not None
    assert "**Alliance** — 3 (75 %)" in embed.description
    assert "**Horde** — 1 (25 %)" in embed.description
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("4 votes ")


def test_a_missing_icon_falls_back_to_the_unicode_emoji(emojis: EmojiStore) -> None:
    """The store fetched nothing here, which is the state before the icons are uploaded."""
    embed = poll_embed(_poll(), DEFINITION, _tallies(1, 0), emojis)

    assert embed.description is not None
    assert "🔵 **Alliance**" in embed.description


def test_a_poll_accepting_several_answers_says_so(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(1, 1), emojis)

    assert embed.footer.text is not None
    assert "plusieurs choix" in embed.footer.text


def test_a_single_answer_poll_says_so_instead(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), SINGLE, _tallies(1, 1), emojis)

    assert embed.footer.text is not None
    assert "un seul choix" in embed.footer.text


def test_a_closed_poll_says_so(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(PollStatus.CLOSED), DEFINITION, _tallies(1, 0), emojis)

    assert embed.footer.text is not None
    assert "clos" in embed.footer.text


def test_results_are_ranked_by_vote_count(emojis: EmojiStore) -> None:
    embed = results_embed(_poll(), DEFINITION, _tallies(1, 5), emojis)

    assert embed.description is not None
    assert embed.description.index("Horde") < embed.description.index("Alliance")


def test_a_poll_embed_stays_within_the_api_limits(emojis: EmojiStore) -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(3, 1), emojis)

    assert len(embed) <= 6000
