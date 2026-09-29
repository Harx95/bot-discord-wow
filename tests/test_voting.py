"""Vote button dispatch, staff checks and embed rendering."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import discord
import pytest

from bot.permissions import is_staff
from bot.rendering import NO_VOTES, poll_embed, results_embed
from bot.views.poll import VOTE_TEMPLATE, VoteButton, build_poll_view
from config import PollCatalog, build_vote_custom_id
from config.polls import PollDefinition
from domain import OptionTally, Poll, PollOption, PollStatus

NOW = datetime(2026, 9, 29, tzinfo=UTC)

DEFINITION = PollDefinition.model_validate(
    {
        "key": "faction",
        "title": "Quelle faction ?",
        "description": "Vote décisif.",
        "options": [
            {"key": "alliance", "label": "Alliance", "emoji": "🔵"},
            {"key": "horde", "label": "Horde", "emoji": "🔴"},
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


# --- custom_id round trip: this is what makes a restart survivable -------------------


@pytest.mark.parametrize("poll_key,option_key", [("faction", "alliance"), ("royaume", "jcj")])
def test_the_template_matches_a_generated_custom_id(poll_key: str, option_key: str) -> None:
    """If these two drifted apart, buttons would go dead after a restart."""
    match = VOTE_TEMPLATE.fullmatch(build_vote_custom_id(poll_key, option_key))

    assert match is not None
    assert match["poll"] == poll_key
    assert match["option"] == option_key


def test_the_template_matches_every_configured_option(catalog: PollCatalog) -> None:
    for definition in catalog.polls:
        for option in definition.options:
            custom_id = build_vote_custom_id(definition.key, option.key)
            assert VOTE_TEMPLATE.fullmatch(custom_id) is not None


async def test_from_custom_id_restores_the_keys() -> None:
    """Rebuilding the handler from the message is what a restarted bot does."""
    custom_id = build_vote_custom_id("faction", "horde")
    match = VOTE_TEMPLATE.fullmatch(custom_id)
    assert match is not None

    interaction = cast(discord.Interaction, SimpleNamespace())
    button = VoteButton("faction", "horde", label="Horde")

    restored = await VoteButton.from_custom_id(interaction, button.item, match)

    assert (restored.poll_key, restored.option_key) == ("faction", "horde")


def test_the_view_is_persistent_and_carries_one_button_per_option() -> None:
    view = build_poll_view(DEFINITION)

    assert view.timeout is None
    assert [cast(VoteButton, item).option_key for item in view.children] == ["alliance", "horde"]
    assert all(item.is_persistent() for item in view.children)


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


def test_an_empty_poll_shows_a_placeholder_rather_than_zeroes() -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(0, 0))

    assert embed.description is not None
    assert NO_VOTES in embed.description
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("0 vote ")


def test_counts_and_shares_are_rendered() -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(3, 1))

    assert embed.description is not None
    assert "**Alliance** — 3 (75 %)" in embed.description
    assert "**Horde** — 1 (25 %)" in embed.description
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("4 votes ")


def test_a_closed_poll_says_so() -> None:
    embed = poll_embed(_poll(PollStatus.CLOSED), DEFINITION, _tallies(1, 0))

    assert embed.footer.text is not None
    assert "clos" in embed.footer.text


def test_results_are_ranked_by_vote_count() -> None:
    embed = results_embed(_poll(), DEFINITION, _tallies(1, 5))

    assert embed.description is not None
    assert embed.description.index("Horde") < embed.description.index("Alliance")


def test_a_poll_embed_stays_within_the_api_limits() -> None:
    embed = poll_embed(_poll(), DEFINITION, _tallies(3, 1))

    assert len(embed) <= 6000
