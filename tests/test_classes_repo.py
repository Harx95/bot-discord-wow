"""ClassRepo behaviour: ranked choices, class roles and managed messages."""

import aiosqlite

from db import ClassRepo, MemberRepo

MAX = 3


async def test_the_first_choice_lands_at_rank_one(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")

    choice = await class_repo.append_choice(1, "mage", "dps", MAX)

    assert choice is not None
    assert choice.rank == 1
    assert choice.is_first


async def test_choices_stack_in_the_order_they_are_made(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")

    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(1, "druide", "tank", MAX)
    third = await class_repo.append_choice(1, "pretre", "heal", MAX)

    assert third is not None
    assert third.rank == 3
    assert [c.class_key for c in await class_repo.choices_of(1)] == ["mage", "druide", "pretre"]


async def test_a_fourth_choice_is_refused_rather_than_dropped(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Returning None lets the caller explain, instead of silently ignoring the click."""
    await members.upsert(1, "Kaeldin")
    for klass, role in (("mage", "dps"), ("druide", "tank"), ("pretre", "heal")):
        await class_repo.append_choice(1, klass, role, MAX)

    assert await class_repo.append_choice(1, "voleur", "dps", MAX) is None
    assert len(await class_repo.choices_of(1)) == MAX


async def test_picking_the_same_pair_twice_does_not_take_a_second_rank(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    first = await class_repo.append_choice(1, "mage", "dps", MAX)

    again = await class_repo.append_choice(1, "mage", "dps", MAX)

    assert again is not None and first is not None
    assert again.rank == first.rank
    assert len(await class_repo.choices_of(1)) == 1


async def test_the_same_class_in_another_role_is_a_separate_choice(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Druide tank and druide heal are two different characters to plan for."""
    await members.upsert(1, "Kaeldin")
    await class_repo.append_choice(1, "druide", "tank", MAX)

    second = await class_repo.append_choice(1, "druide", "heal", MAX)

    assert second is not None
    assert second.rank == 2


async def test_first_choice_of_returns_the_main(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(1, "druide", "tank", MAX)

    first = await class_repo.first_choice_of(1)

    assert first is not None
    assert first.class_key == "mage"


async def test_first_choice_of_is_none_before_anything_is_declared(
    class_repo: ClassRepo,
) -> None:
    assert await class_repo.first_choice_of(1) is None


async def test_clear_choices_reports_how_many_were_removed(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(1, "druide", "tank", MAX)

    assert await class_repo.clear_choices(1) == 2
    assert await class_repo.clear_choices(1) == 0


async def test_ranks_restart_at_one_after_a_reset(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Otherwise the primary key would collide on the second pass."""
    await members.upsert(1, "Kaeldin")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.clear_choices(1)

    choice = await class_repo.append_choice(1, "druide", "tank", MAX)

    assert choice is not None
    assert choice.rank == 1


async def test_choices_are_scoped_to_their_member(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(2, "druide", "tank", MAX)

    assert [c.class_key for c in await class_repo.choices_of(1)] == ["mage"]
    assert len(await class_repo.all_choices()) == 2


async def test_deleting_a_member_takes_their_choices_along(
    connection: aiosqlite.Connection,
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await class_repo.append_choice(1, "mage", "dps", MAX)

    await connection.execute("DELETE FROM members WHERE discord_id = 1")
    await connection.commit()

    assert await class_repo.all_choices() == []


# --- directory -----------------------------------------------------------------------


async def test_the_directory_groups_choices_by_member(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(1, "druide", "tank", MAX)
    await class_repo.append_choice(2, "pretre", "heal", MAX)

    entries = await class_repo.directory()

    assert [name for name, _ in entries] == ["Kaeldin", "Sylvara"]
    assert [c.rank for c in entries[0][1]] == [1, 2]


async def test_the_directory_ignores_members_who_declared_nothing(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "Kaeldin")
    await members.upsert(2, "Sylvara")
    await class_repo.append_choice(1, "mage", "dps", MAX)

    assert [name for name, _ in await class_repo.directory()] == ["Kaeldin"]


async def test_the_directory_sorts_names_regardless_of_case(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await members.upsert(1, "zorg")
    await members.upsert(2, "Aelis")
    await class_repo.append_choice(1, "mage", "dps", MAX)
    await class_repo.append_choice(2, "druide", "tank", MAX)

    assert [name for name, _ in await class_repo.directory()] == ["Aelis", "zorg"]


# --- class roles ---------------------------------------------------------------------


async def test_link_role_stores_the_discord_role_id(class_repo: ClassRepo) -> None:
    await class_repo.link_role("mage", 42)

    assert await class_repo.role_ids() == {"mage": 42}


async def test_linking_a_class_again_replaces_the_role_id(class_repo: ClassRepo) -> None:
    """Happens when the role was deleted on Discord and recreated."""
    await class_repo.link_role("mage", 42)

    await class_repo.link_role("mage", 43)

    assert await class_repo.role_ids() == {"mage": 43}


async def test_unlink_role_reports_whether_it_existed(class_repo: ClassRepo) -> None:
    await class_repo.link_role("mage", 42)

    assert await class_repo.unlink_role("mage") is True
    assert await class_repo.unlink_role("mage") is False


# --- managed messages ----------------------------------------------------------------


async def test_a_managed_message_is_remembered(class_repo: ClassRepo) -> None:
    await class_repo.remember_message("annuaire", 10, 20)

    managed = await class_repo.managed_message("annuaire")

    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (10, 20)


async def test_reposting_replaces_the_remembered_message(class_repo: ClassRepo) -> None:
    await class_repo.remember_message("annuaire", 10, 20)

    await class_repo.remember_message("annuaire", 11, 21)

    managed = await class_repo.managed_message("annuaire")
    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (11, 21)


async def test_an_unknown_managed_message_is_none(class_repo: ClassRepo) -> None:
    assert await class_repo.managed_message("inconnu") is None


async def test_forget_message_reports_whether_it_existed(class_repo: ClassRepo) -> None:
    await class_repo.remember_message("annuaire", 10, 20)

    assert await class_repo.forget_message("annuaire") is True
    assert await class_repo.forget_message("annuaire") is False
