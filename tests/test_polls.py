"""PollRepo behaviour."""

import aiosqlite
import pytest

from db import MemberRepo, PollRepo
from domain import PollStatus

FACTION_OPTIONS = [("alliance", "Alliance"), ("horde", "Horde")]


async def test_create_stores_the_poll_open_with_its_options(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    assert poll.status is PollStatus.OPEN
    assert poll.is_open
    assert poll.closed_at is None
    assert [o.key for o in await polls.options(poll.id)] == ["alliance", "horde"]


async def test_create_rejects_a_duplicate_key(polls: PollRepo) -> None:
    await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.create("faction", "Encore ?", FACTION_OPTIONS)


async def test_a_failed_create_leaves_nothing_behind(polls: PollRepo) -> None:
    """The poll and its options are one transaction: a rejected option rolls the poll back."""
    too_long = [("a", "A"), ("b", "B" * 101)]

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.create("royaume", "Type de royaume ?", too_long)

    assert await polls.get_by_key("royaume") is None


async def test_get_by_key_returns_none_when_absent(polls: PollRepo) -> None:
    assert await polls.get_by_key("inconnu") is None


async def test_list_open_excludes_closed_polls(polls: PollRepo) -> None:
    await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    await polls.create("royaume", "Type de royaume ?", [("pve", "Normal")])
    await polls.close("faction")

    assert [p.key for p in await polls.list_open()] == ["royaume"]


async def test_close_records_the_date_and_is_not_repeatable(polls: PollRepo) -> None:
    await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    closed = await polls.close("faction")

    assert closed is not None
    assert closed.status is PollStatus.CLOSED
    assert closed.closed_at is not None
    assert await polls.close("faction") is None


async def test_add_option_appends_at_the_end(members: MemberRepo, polls: PollRepo) -> None:
    await members.upsert(42, "Kaeldin")
    poll = await polls.create("nom", "Nom de guilde ?", [("a", "Aube")])

    added = await polls.add_option(poll.id, "b", "Brise", created_by=42)

    assert added.position == 1
    assert added.is_member_proposal
    assert [o.key for o in await polls.options(poll.id)] == ["a", "b"]


async def test_add_option_requires_a_known_proposer(polls: PollRepo) -> None:
    """A proposal must be attributable: the member has to be recorded first."""
    poll = await polls.create("nom", "Nom de guilde ?")

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.add_option(poll.id, "b", "Brise", created_by=999)


async def test_add_option_rejects_a_label_over_the_discord_limit(polls: PollRepo) -> None:
    poll = await polls.create("nom", "Nom de guilde ?")

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.add_option(poll.id, "long", "N" * 101)


async def test_attach_message_is_stored(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    await polls.attach_message(poll.id, channel_id=10, message_id=20)

    stored = await polls.get_by_key("faction")
    assert stored is not None
    assert (stored.channel_id, stored.message_id) == (10, 20)


async def test_cast_vote_records_a_choice(members: MemberRepo, polls: PollRepo) -> None:
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance = (await polls.options(poll.id))[0]

    vote = await polls.cast_vote(poll.id, 1, alliance.id)

    assert vote.option_id == alliance.id
    assert await polls.vote_of(poll.id, 1) == vote


async def test_voting_again_replaces_the_previous_choice(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, horde = await polls.options(poll.id)

    await polls.cast_vote(poll.id, 1, alliance.id)
    await polls.cast_vote(poll.id, 1, horde.id)

    current = await polls.vote_of(poll.id, 1)
    assert current is not None
    assert current.option_id == horde.id
    assert sum(tally.votes for tally in await polls.results(poll.id)) == 1


async def test_a_vote_cannot_point_at_another_polls_option(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    """The composite foreign key is what stops a button from a different poll being reused."""
    await members.upsert(1, "Kaeldin")
    faction = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    realm = await polls.create("royaume", "Type de royaume ?", [("pve", "Normal")])
    foreign_option = (await polls.options(realm.id))[0]

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.cast_vote(faction.id, 1, foreign_option.id)


async def test_a_vote_requires_a_known_member(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance = (await polls.options(poll.id))[0]

    with pytest.raises(aiosqlite.IntegrityError):
        await polls.cast_vote(poll.id, 999, alliance.id)


async def test_vote_of_returns_none_when_the_member_has_not_voted(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    assert await polls.vote_of(poll.id, 1) is None


async def test_results_count_votes_and_keep_empty_options(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, _horde = await polls.options(poll.id)

    await polls.cast_vote(poll.id, 1, alliance.id)
    await polls.cast_vote(poll.id, 2, alliance.id)

    tallies = await polls.results(poll.id)

    assert [(t.option.key, t.votes) for t in tallies] == [("alliance", 2), ("horde", 0)]


async def test_results_ignore_votes_from_other_polls(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    faction = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    realm = await polls.create("royaume", "Type de royaume ?", [("pve", "Normal")])
    await polls.cast_vote(realm.id, 1, (await polls.options(realm.id))[0].id)

    assert [t.votes for t in await polls.results(faction.id)] == [0, 0]
