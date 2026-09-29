"""Class buttons, role hierarchy checks and the embeds built from them."""

from datetime import UTC, datetime
from typing import cast

import discord
import pytest

from bot.emojis import EmojiStore
from bot.rendering import classes_embed, composition_embed, directory_embed, rank_mark
from bot.roles import MISSING_PERMISSION, apply_class_role, hierarchy_error, sync_class_roles
from bot.views.classes import (
    CLASS_TEMPLATE,
    RESET_TEMPLATE,
    ROLE_TEMPLATE,
    ClassButton,
    ResetButton,
    build_classes_view,
)
from config import (
    RESET_CUSTOM_ID,
    ClassCatalog,
    build_class_button_custom_id,
    build_role_button_custom_id,
)
from db import ClassRepo
from domain import MemberChoice
from tests.fakes import FakeGuild, FakeMember, FakeRole, RecordingRepo, as_guild, as_member, as_role

NOW = datetime(2026, 9, 29, tzinfo=UTC)

EMBED_TOTAL_LIMIT = 6000
EMBED_FIELD_LIMIT = 1024
EMBED_DESCRIPTION_LIMIT = 4096
COMPONENTS_PER_MESSAGE = 25
FIELDS_PER_EMBED = 25


@pytest.fixture
def emojis(classes: ClassCatalog) -> EmojiStore:
    """An empty store: nothing uploaded, so the unicode fallbacks are used."""
    return EmojiStore(classes)


def _choice(member_id: int, rank: int, class_key: str, role_key: str) -> MemberChoice:
    return MemberChoice(
        member_id=member_id,
        rank=rank,
        class_key=class_key,
        role_key=role_key,
        created_at=NOW,
    )


# --- custom_id round trip ------------------------------------------------------------


def test_the_class_template_matches_every_configured_class(classes: ClassCatalog) -> None:
    """If these drifted apart, the buttons would go dead after a restart."""
    for klass in classes.classes:
        match = CLASS_TEMPLATE.fullmatch(build_class_button_custom_id(klass.key))
        assert match is not None
        assert match["klass"] == klass.key


def test_the_role_template_matches_every_playable_pair(classes: ClassCatalog) -> None:
    for klass in classes.classes:
        for role in classes.roles_of(klass.key):
            custom_id = build_role_button_custom_id(klass.key, role.key)
            match = ROLE_TEMPLATE.fullmatch(custom_id)
            assert match is not None
            assert (match["klass"], match["role"]) == (klass.key, role.key)


def test_the_reset_template_matches_its_custom_id() -> None:
    assert RESET_TEMPLATE.fullmatch(RESET_CUSTOM_ID) is not None


def test_a_class_custom_id_does_not_match_the_role_template() -> None:
    """The two prefixes must not overlap, or the wrong handler would run."""
    assert ROLE_TEMPLATE.fullmatch(build_class_button_custom_id("mage")) is None


# --- the persistent view -------------------------------------------------------------


def test_the_view_holds_one_button_per_class_plus_reset(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    view = build_classes_view(classes, emojis)

    assert view.timeout is None
    assert len(view.children) == len(classes.classes) + 1
    assert all(item.is_persistent() for item in view.children)


def test_the_view_fits_within_one_message(classes: ClassCatalog, emojis: EmojiStore) -> None:
    """25 components maximum; validation caps the classes so the reset button fits."""
    assert len(build_classes_view(classes, emojis).children) <= COMPONENTS_PER_MESSAGE


def test_the_buttons_carry_the_class_names_and_fallback_emojis(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    view = build_classes_view(classes, emojis)
    buttons = [item for item in view.children if isinstance(item, ClassButton)]

    assert [b.item.label for b in buttons] == [k.name for k in classes.classes]
    assert all(b.item.emoji is not None for b in buttons)


def test_the_reset_button_is_last_and_destructive_looking(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    view = build_classes_view(classes, emojis)
    last = view.children[-1]

    assert isinstance(last, ResetButton)
    assert last.item.style is discord.ButtonStyle.danger


# --- hierarchy -----------------------------------------------------------------------


def test_a_role_below_the_bot_is_assignable() -> None:
    assert hierarchy_error(as_guild(bot_position=10), as_role(FakeRole("Mage", 5))) is None


def test_a_role_above_the_bot_is_refused_with_an_explanation() -> None:
    error = hierarchy_error(as_guild(bot_position=2), as_role(FakeRole("Membre", 4)))

    assert error is not None
    assert "Membre" in error
    assert "Bot" in error


def test_a_role_at_the_same_position_as_the_bot_is_refused() -> None:
    """Discord requires strictly below, not below or equal."""
    assert hierarchy_error(as_guild(bot_position=5), as_role(FakeRole("Mage", 5))) is not None


def test_a_missing_manage_roles_permission_is_reported_first() -> None:
    guild = as_guild(manage_roles=False, bot_position=10)

    assert hierarchy_error(guild, as_role(FakeRole("Mage", 5))) == MISSING_PERMISSION


# --- assigning the class role --------------------------------------------------------


async def test_the_class_role_is_added() -> None:
    mage = FakeRole("Mage", 5, role_id=1)
    member = FakeMember(as_guild(), [])

    error = await apply_class_role(as_member(member), as_role(mage), {1, 2})

    assert error is None
    assert member.added == [mage]


async def test_a_new_first_choice_removes_the_previous_class_role() -> None:
    """Two class roles would make the nickname colour depend on their order."""
    mage = FakeRole("Mage", 5, role_id=1)
    druide = FakeRole("Druide", 6, role_id=2)
    member = FakeMember(as_guild(), [mage])

    error = await apply_class_role(as_member(member), as_role(druide), {1, 2})

    assert error is None
    assert member.removed == [mage]
    assert member.added == [druide]


async def test_resetting_takes_the_class_role_back() -> None:
    """The reset button passes None: the member ends up with no class colour."""
    mage = FakeRole("Mage", 5, role_id=1)
    member = FakeMember(as_guild(), [mage])

    error = await apply_class_role(as_member(member), None, {1, 2})

    assert error is None
    assert member.removed == [mage]
    assert member.added == []


async def test_roles_that_are_not_class_roles_are_left_alone() -> None:
    officier = FakeRole("Officier", 8, role_id=99)
    mage = FakeRole("Mage", 5, role_id=1)
    member = FakeMember(as_guild(), [officier])

    await apply_class_role(as_member(member), as_role(mage), {1, 2})

    assert member.removed == []


async def test_choosing_the_same_class_again_changes_nothing() -> None:
    mage = FakeRole("Mage", 5, role_id=1)
    member = FakeMember(as_guild(), [mage])

    error = await apply_class_role(as_member(member), as_role(mage), {1, 2})

    assert error is None
    assert member.added == []
    assert member.removed == []


async def test_nothing_is_touched_when_the_hierarchy_blocks_it() -> None:
    """A refusal must not leave the member half-way between two classes."""
    mage = FakeRole("Mage", 5, role_id=1)
    druide = FakeRole("Druide", 6, role_id=2)
    member = FakeMember(as_guild(bot_position=2), [mage])

    error = await apply_class_role(as_member(member), as_role(druide), {1, 2})

    assert error is not None
    assert member.added == []
    assert member.removed == []


# --- rendering -----------------------------------------------------------------------


def test_the_selection_embed_lists_every_class(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    embed = classes_embed(classes, emojis)

    assert len(embed.fields) == len(classes.classes)
    assert embed.description is not None
    assert str(classes.max_choices) in embed.description


def test_the_selection_embed_shows_the_roles_each_class_can_fill(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    fields = {field.name: field.value for field in classes_embed(classes, emojis).fields}
    mage = next(name for name in fields if name and "Mage" in name)

    assert "DPS" in (fields[mage] or "")
    assert "Tank" not in (fields[mage] or "")


def test_the_directory_lists_each_member_and_their_ranks(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    entries = [
        ("Kaeldin", [_choice(1, 1, "mage", "dps"), _choice(1, 2, "druide", "tank")]),
        ("Sylvara", [_choice(2, 1, "pretre", "heal")]),
    ]

    description = directory_embed(classes, emojis, entries).description or ""

    assert "Kaeldin" in description
    assert "Sylvara" in description
    assert rank_mark(1) in description
    assert rank_mark(2) in description
    assert "Mage" in description


def test_an_empty_directory_says_so(classes: ClassCatalog, emojis: EmojiStore) -> None:
    embed = directory_embed(classes, emojis, [])

    assert embed.description is not None
    assert "Personne" in embed.description


def test_a_large_directory_is_truncated_rather_than_rejected(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Discord refuses a description over 4096 characters outright."""
    entries = [
        (f"Joueur{i:03d}", [_choice(i, 1, "mage", "dps"), _choice(i, 2, "druide", "tank")])
        for i in range(400)
    ]

    embed = directory_embed(classes, emojis, entries)

    assert embed.description is not None
    assert len(embed.description) <= EMBED_DESCRIPTION_LIMIT
    assert embed.footer.text is not None
    assert "non affiché" in embed.footer.text


def test_composition_counts_first_choices_per_role(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    choices = [
        _choice(1, 1, "druide", "tank"),
        _choice(2, 1, "mage", "dps"),
        _choice(3, 1, "pretre", "heal"),
    ]

    roles = composition_embed(classes, emojis, choices).fields[0].value or ""

    assert "**Tank** — 1" in roles
    assert "**DPS** — 1" in roles


def test_composition_reports_later_choices_separately(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Two tanks with five tank second-choices is not the same guild as two tanks."""
    choices = [_choice(1, 1, "mage", "dps"), _choice(1, 2, "druide", "tank")]

    roles = composition_embed(classes, emojis, choices).fields[0].value or ""

    assert "**Tank** — 0" in roles
    assert "+1 en choix suivant" in roles


def test_composition_lists_only_the_classes_actually_mained(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    embed = composition_embed(classes, emojis, [_choice(1, 1, "mage", "dps")])
    played = embed.fields[1].value or ""

    assert "Mage" in played
    assert "Druide" not in played


def test_an_empty_composition_says_so(classes: ClassCatalog, emojis: EmojiStore) -> None:
    embed = composition_embed(classes, emojis, [])

    assert embed.footer.text is not None
    assert "Personne" in embed.footer.text


def test_the_embeds_stay_within_the_api_limits(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    choices = [_choice(i, 1, "druide", "tank") for i in range(200)]
    choices += [_choice(i, 2, "mage", "dps") for i in range(200)]

    composition = composition_embed(classes, emojis, choices)

    assert len(composition) <= EMBED_TOTAL_LIMIT
    assert all(len(field.value or "") <= EMBED_FIELD_LIMIT for field in composition.fields)

    selection = classes_embed(classes, emojis)
    assert len(selection) <= EMBED_TOTAL_LIMIT
    assert len(selection.fields) <= FIELDS_PER_EMBED


# --- creating the class roles --------------------------------------------------------


async def test_an_existing_role_of_the_same_name_is_adopted_not_duplicated(
    classes: ClassCatalog,
) -> None:
    """After a database reset the Discord roles are still there; recreating would duplicate."""
    guild = as_guild()
    existing = [
        FakeRole(klass.name, index + 1, role_id=index + 1)
        for index, klass in enumerate(classes.classes)
    ]
    cast(FakeGuild, guild).roles = existing
    repo = RecordingRepo()

    result = await sync_class_roles(guild, classes.classes, cast(ClassRepo, repo))

    assert result.created == []
    assert len(result.adopted) == len(classes.classes)
    assert repo.linked == {k.key: i + 1 for i, k in enumerate(classes.classes)}


async def test_a_class_with_no_matching_role_is_created(classes: ClassCatalog) -> None:
    guild = as_guild()
    cast(FakeGuild, guild).roles = []
    repo = RecordingRepo()

    result = await sync_class_roles(guild, classes.classes[:1], cast(ClassRepo, repo))

    assert result.adopted == []
    assert result.created == [classes.classes[0].name]
