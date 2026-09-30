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
    assert await polls.votes_of(poll.id, 1) == [vote]


async def test_voting_again_replaces_the_previous_choice(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    """Single-answer polls are enforced here now that the schema allows several rows."""
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, horde = await polls.options(poll.id)

    await polls.cast_vote(poll.id, 1, alliance.id)
    await polls.cast_vote(poll.id, 1, horde.id)

    current = await polls.votes_of(poll.id, 1)
    assert [vote.option_id for vote in current] == [horde.id]
    assert sum(tally.votes for tally in await polls.results(poll.id)) == 1


async def test_add_vote_keeps_the_other_choices(members: MemberRepo, polls: PollRepo) -> None:
    """Backing both factions is the replacement for the old "Peu importe" option."""
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, horde = await polls.options(poll.id)

    await polls.add_vote(poll.id, 1, alliance.id)
    await polls.add_vote(poll.id, 1, horde.id)

    backed = {vote.option_id for vote in await polls.votes_of(poll.id, 1)}
    assert backed == {alliance.id, horde.id}
    assert sum(tally.votes for tally in await polls.results(poll.id)) == 2


async def test_backing_the_same_option_twice_is_harmless(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    """A reaction event can be replayed; it must not double a count."""
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance = (await polls.options(poll.id))[0]

    await polls.add_vote(poll.id, 1, alliance.id)
    await polls.add_vote(poll.id, 1, alliance.id)

    assert len(await polls.votes_of(poll.id, 1)) == 1


async def test_remove_vote_takes_back_one_option_only(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, horde = await polls.options(poll.id)
    await polls.add_vote(poll.id, 1, alliance.id)
    await polls.add_vote(poll.id, 1, horde.id)

    assert await polls.remove_vote(poll.id, 1, alliance.id)

    assert [vote.option_id for vote in await polls.votes_of(poll.id, 1)] == [horde.id]


async def test_removing_a_vote_that_is_not_there_says_so(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    """cast_vote already dropped it when the bot takes the matching reaction off."""
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance = (await polls.options(poll.id))[0]

    assert not await polls.remove_vote(poll.id, 1, alliance.id)


async def test_sync_votes_realigns_a_poll_on_what_it_is_given(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    """What the startup reconciliation does with the reactions read off the message."""
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance, horde = await polls.options(poll.id)
    await polls.add_vote(poll.id, 1, alliance.id)

    total = await polls.sync_votes(poll.id, [(1, horde.id), (2, horde.id)])

    assert total == 2
    assert [vote.option_id for vote in await polls.votes_of(poll.id, 1)] == [horde.id]
    counts = {tally.option.key: tally.votes for tally in await polls.results(poll.id)}
    assert counts == {"alliance": 0, "horde": 2}


async def test_sync_votes_on_an_empty_ballot_clears_the_poll(
    members: MemberRepo,
    polls: PollRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    alliance = (await polls.options(poll.id))[0]
    await polls.add_vote(poll.id, 1, alliance.id)

    assert await polls.sync_votes(poll.id, []) == 0
    assert await polls.votes_of(poll.id, 1) == []


async def test_get_by_message_finds_the_poll_a_reaction_lands_on(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    await polls.attach_message(poll.id, channel_id=10, message_id=20)

    found = await polls.get_by_message(20)

    assert found is not None
    assert found.key == "faction"


async def test_get_by_message_ignores_a_message_no_poll_points_at(polls: PollRepo) -> None:
    """A reaction on an older, reposted message must simply be ignored."""
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)
    await polls.attach_message(poll.id, channel_id=10, message_id=20)

    assert await polls.get_by_message(19) is None


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


async def test_votes_of_is_empty_when_the_member_has_not_voted(polls: PollRepo) -> None:
    poll = await polls.create("faction", "Quelle faction ?", FACTION_OPTIONS)

    assert await polls.votes_of(poll.id, 1) == []


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
