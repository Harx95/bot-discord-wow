"""MemberRepo behaviour."""

from db import MemberRepo


async def test_upsert_creates_a_member(members: MemberRepo) -> None:
    member = await members.upsert(1, "Kaeldin")

    assert member.discord_id == 1
    assert member.display_name == "Kaeldin"
    assert member.first_seen_at == member.last_seen_at


async def test_upsert_refreshes_the_name_and_keeps_the_first_seen_date(
    members: MemberRepo,
) -> None:
    created = await members.upsert(1, "Kaeldin")
    updated = await members.upsert(1, "Kaeldin-Renommé")

    assert updated.display_name == "Kaeldin-Renommé"
    assert updated.first_seen_at == created.first_seen_at
    assert updated.last_seen_at >= created.last_seen_at


async def test_get_returns_none_for_an_unknown_member(members: MemberRepo) -> None:
    assert await members.get(404) is None


async def test_get_returns_a_stored_member(members: MemberRepo) -> None:
    await members.upsert(1, "Kaeldin")

    fetched = await members.get(1)

    assert fetched is not None
    assert fetched.display_name == "Kaeldin"


async def test_timestamps_survive_the_round_trip_as_aware_datetimes(
    members: MemberRepo,
) -> None:
    created = await members.upsert(1, "Kaeldin")

    fetched = await members.get(1)

    assert fetched is not None
    assert fetched.first_seen_at == created.first_seen_at
    assert fetched.first_seen_at.tzinfo is not None


async def test_list_all_returns_every_member(members: MemberRepo) -> None:
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")

    assert [m.discord_id for m in await members.list_all()] == [1, 2]
