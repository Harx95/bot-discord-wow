"""ClassRepo behaviour: main characters, alternates, class roles and managed messages."""

import aiosqlite

from db import ClassRepo, MemberRepo

MAX = 3


async def _member(members: MemberRepo, member_id: int = 1, name: str = "Kaeldin") -> None:
    """member_choices references members, so one has to exist first."""
    await members.upsert(member_id, name)


# --- the main character ---------------------------------------------------------------


async def test_the_main_character_lands_at_rank_one(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)

    update = await class_repo.set_main(1, "mage", "dps")

    assert update.changed
    assert update.choice.rank == 1
    assert update.choice.is_first


async def test_a_new_main_replaces_the_previous_one(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """The old main is dropped, not demoted: the member said they changed their mind."""
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    update = await class_repo.set_main(1, "paladin", "tank")

    assert update.replaced_class_key == "mage"
    assert [c.class_key for c in await class_repo.choices_of(1)] == ["paladin"]


async def test_declaring_the_same_main_twice_changes_nothing(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    update = await class_repo.set_main(1, "mage", "dps")

    assert not update.changed
    assert update.replaced_class_key is None
    assert len(await class_repo.choices_of(1)) == 1


async def test_an_alternate_promoted_to_main_is_not_duplicated(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """UNIQUE (member, class, role) forbids holding the pair twice."""
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.add_alternate(1, "druide", "tank", MAX)

    update = await class_repo.set_main(1, "druide", "tank")

    assert update.promoted
    assert [(c.rank, c.class_key) for c in await class_repo.choices_of(1)] == [(1, "druide")]


async def test_a_main_declared_from_nothing_is_not_a_promotion(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)

    update = await class_repo.set_main(1, "mage", "dps")

    assert not update.promoted


async def test_the_same_class_in_another_role_replaces_the_main(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Switching from druid tank to druid healer is still one main character."""
    await _member(members)
    await class_repo.set_main(1, "druide", "tank")

    await class_repo.set_main(1, "druide", "heal")

    choices = await class_repo.choices_of(1)
    assert [(c.class_key, c.role_key) for c in choices] == [("druide", "heal")]


# --- taking the main character back ---------------------------------------------------


async def test_clear_main_returns_what_it_removed(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Clicking the declared class again is how a member drops it."""
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    removed = await class_repo.clear_main(1)

    assert removed is not None
    assert removed.class_key == "mage"
    assert await class_repo.main_of(1) is None


async def test_clearing_a_main_that_was_never_set_is_harmless(class_repo: ClassRepo) -> None:
    assert await class_repo.clear_main(1) is None


async def test_clearing_the_main_leaves_the_alternates_alone(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.add_alternate(1, "druide", "tank", MAX)

    await class_repo.clear_main(1)

    assert [c.class_key for c in await class_repo.alternates_of(1)] == ["druide"]


async def test_a_main_can_be_declared_again_after_being_cleared(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Rank 1 has to be free again, or the primary key would collide."""
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.clear_main(1)

    update = await class_repo.set_main(1, "pretre", "heal")

    assert update.choice.rank == 1
    assert update.replaced_class_key is None


# --- the alternates -------------------------------------------------------------------


async def test_alternates_start_after_the_main_rank(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    assert await class_repo.add_alternate(1, "druide", "tank", MAX) is not None
    assert await class_repo.add_alternate(1, "pretre", "heal", MAX) is not None
    assert [c.rank for c in await class_repo.choices_of(1)] == [1, 2, 3]


async def test_a_third_alternate_is_refused(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.add_alternate(1, "druide", "tank", MAX)
    await class_repo.add_alternate(1, "pretre", "heal", MAX)

    assert await class_repo.add_alternate(1, "voleur", "dps", MAX) is None
    assert len(await class_repo.alternates_of(1)) == 2


async def test_alternates_without_a_main_leave_rank_one_free(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Declaring alternates first must not steal the rank the main character owns."""
    await _member(members)

    await class_repo.add_alternate(1, "druide", "tank", MAX)

    assert [c.rank for c in await class_repo.choices_of(1)] == [2]
    assert await class_repo.main_of(1) is None


async def test_an_alternate_is_found_by_class_whatever_its_role(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """A button names a class; it cannot say which role was picked behind it."""
    await _member(members)
    await class_repo.add_alternate(1, "druide", "heal", MAX)

    found = await class_repo.alternate_of(1, "druide")

    assert found is not None
    assert found.role_key == "heal"


async def test_the_main_character_is_not_found_among_the_alternates(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    assert await class_repo.alternate_of(1, "mage") is None
    assert await class_repo.alternates_of(1) == []


async def test_remove_alternate_reports_what_it_removed(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.add_alternate(1, "druide", "tank", MAX)

    removed = await class_repo.remove_alternate(1, "druide")

    assert removed is not None
    assert removed.class_key == "druide"
    assert await class_repo.alternates_of(1) == []


async def test_removing_an_alternate_that_is_not_listed_is_harmless(
    class_repo: ClassRepo,
) -> None:
    assert await class_repo.remove_alternate(1, "druide") is None


async def test_removing_an_alternate_never_touches_the_main(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    assert await class_repo.remove_alternate(1, "mage") is None
    assert await class_repo.main_of(1) is not None


async def test_a_freed_alternate_rank_is_reused(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    """Otherwise the primary key would collide once every rank had been used."""
    await _member(members)
    await class_repo.add_alternate(1, "druide", "tank", MAX)
    await class_repo.add_alternate(1, "pretre", "heal", MAX)
    await class_repo.remove_alternate(1, "druide")

    assert await class_repo.add_alternate(1, "voleur", "dps", MAX) is not None
    choices = await class_repo.choices_of(1)
    assert [(c.rank, c.class_key) for c in choices] == [(2, "voleur"), (3, "pretre")]


async def test_choices_are_scoped_to_their_member(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members, 1, "Kaeldin")
    await _member(members, 2, "Sylvara")
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.set_main(2, "druide", "tank")

    assert [c.class_key for c in await class_repo.choices_of(1)] == ["mage"]
    assert len(await class_repo.all_choices()) == 2


async def test_clear_choices_reports_how_many_were_removed(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.add_alternate(1, "druide", "tank", MAX)

    assert await class_repo.clear_choices(1) == 2
    assert await class_repo.clear_choices(1) == 0


async def test_deleting_a_member_takes_their_choices_along(
    connection: aiosqlite.Connection,
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members)
    await class_repo.set_main(1, "mage", "dps")

    await connection.execute("DELETE FROM members WHERE discord_id = 1")
    await connection.commit()

    assert await class_repo.all_choices() == []


# --- declarations ---------------------------------------------------------------------


async def test_declarations_give_one_row_per_character(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members, 1, "Kaeldin")
    await _member(members, 2, "Sylvara")
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.add_alternate(1, "druide", "tank", MAX)
    await class_repo.set_main(2, "pretre", "heal")

    rows = await class_repo.declarations()

    assert [(name, choice.class_key) for name, choice in rows] == [
        ("Kaeldin", "mage"),
        ("Kaeldin", "druide"),
        ("Sylvara", "pretre"),
    ]


async def test_declarations_ignore_members_who_declared_nothing(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members, 1, "Kaeldin")
    await _member(members, 2, "Sylvara")
    await class_repo.set_main(1, "mage", "dps")

    assert [name for name, _ in await class_repo.declarations()] == ["Kaeldin"]


async def test_declarations_sort_names_regardless_of_case(
    members: MemberRepo,
    class_repo: ClassRepo,
) -> None:
    await _member(members, 1, "zorg")
    await _member(members, 2, "Aelis")
    await class_repo.set_main(1, "mage", "dps")
    await class_repo.set_main(2, "druide", "tank")

    assert [name for name, _ in await class_repo.declarations()] == ["Aelis", "zorg"]


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
    await class_repo.remember_message("board", 10, 20)

    managed = await class_repo.managed_message("board")

    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (10, 20)


async def test_two_boards_are_remembered_separately(class_repo: ClassRepo) -> None:
    """The two messages are edited independently, so neither may overwrite the other."""
    await class_repo.remember_message("board_main", 10, 20)
    await class_repo.remember_message("board_alt", 10, 21)

    main = await class_repo.managed_message("board_main")
    alternates = await class_repo.managed_message("board_alt")

    assert main is not None and alternates is not None
    assert main.message_id != alternates.message_id


async def test_reposting_replaces_the_remembered_message(class_repo: ClassRepo) -> None:
    await class_repo.remember_message("board", 10, 20)

    await class_repo.remember_message("board", 11, 21)

    managed = await class_repo.managed_message("board")
    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (11, 21)


async def test_an_unknown_managed_message_is_none(class_repo: ClassRepo) -> None:
    assert await class_repo.managed_message("inconnu") is None


async def test_forget_message_reports_whether_it_existed(class_repo: ClassRepo) -> None:
    await class_repo.remember_message("board", 10, 20)

    assert await class_repo.forget_message("board") is True
    assert await class_repo.forget_message("board") is False
