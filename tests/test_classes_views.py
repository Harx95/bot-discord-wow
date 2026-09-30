"""Class buttons, role hierarchy checks and the boards built from them."""

from datetime import UTC, datetime
from typing import cast

import discord
import pytest

from bot.emojis import EmojiStore
from bot.rendering import (
    Declaration,
    alternates_board_embed,
    composition_embed,
    main_board_embed,
)
from bot.roles import MISSING_PERMISSION, apply_class_role, hierarchy_error, sync_class_roles
from bot.views.classes import (
    ALTERNATE_CLASS_TEMPLATE,
    MAIN_CLASS_TEMPLATE,
    ROLE_TEMPLATE,
    AlternateClassButton,
    MainClassButton,
    build_alternates_view,
    build_main_view,
)
from config import (
    ClassCatalog,
    Slot,
    build_class_button_custom_id,
    build_role_button_custom_id,
)
from db import ClassRepo
from domain import MemberChoice
from tests.fakes import FakeGuild, FakeMember, FakeRole, RecordingRepo, as_guild, as_member, as_role

NOW = datetime(2026, 9, 29, tzinfo=UTC)

EMBED_TOTAL_LIMIT = 6000
EMBED_FIELD_LIMIT = 1024
COMPONENTS_PER_MESSAGE = 25

TANK, HEAL, DPS = 0, 1, 2


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


def _row(name: str, member_id: int, rank: int, class_key: str, role_key: str) -> Declaration:
    """One declared character, as the repository hands it to the renderer."""
    return (name, _choice(member_id, rank, class_key, role_key))


def _values(embed: discord.Embed) -> list[str]:
    """The three column bodies, in role order."""
    return [field.value or "" for field in embed.fields]


# --- custom_id round trip ------------------------------------------------------------


def test_the_main_template_matches_every_configured_class(classes: ClassCatalog) -> None:
    """If these drifted apart, the buttons would go dead after a restart."""
    for klass in classes.classes:
        custom_id = build_class_button_custom_id(Slot.MAIN, klass.key)
        match = MAIN_CLASS_TEMPLATE.fullmatch(custom_id)

        assert match is not None
        assert match["klass"] == klass.key


def test_the_alternate_template_matches_every_configured_class(classes: ClassCatalog) -> None:
    for klass in classes.classes:
        custom_id = build_class_button_custom_id(Slot.ALTERNATE, klass.key)
        match = ALTERNATE_CLASS_TEMPLATE.fullmatch(custom_id)

        assert match is not None
        assert match["klass"] == klass.key


def test_the_role_template_carries_the_board_it_came_from(classes: ClassCatalog) -> None:
    for slot in Slot:
        for klass in classes.classes:
            for role in classes.roles_of(klass.key):
                custom_id = build_role_button_custom_id(slot, klass.key, role.key)
                match = ROLE_TEMPLATE.fullmatch(custom_id)

                assert match is not None
                assert Slot(match["slot"]) is slot
                assert (match["klass"], match["role"]) == (klass.key, role.key)


def test_the_two_board_templates_do_not_overlap() -> None:
    """A click on one board must never be handled as a click on the other."""
    main = build_class_button_custom_id(Slot.MAIN, "mage")
    alternate = build_class_button_custom_id(Slot.ALTERNATE, "mage")

    assert ALTERNATE_CLASS_TEMPLATE.fullmatch(main) is None
    assert MAIN_CLASS_TEMPLATE.fullmatch(alternate) is None


def test_a_class_custom_id_does_not_match_the_role_template() -> None:
    """The prefixes must not overlap, or the wrong handler would run."""
    assert ROLE_TEMPLATE.fullmatch(build_class_button_custom_id(Slot.MAIN, "mage")) is None
    assert ROLE_TEMPLATE.fullmatch(build_class_button_custom_id(Slot.ALTERNATE, "mage")) is None


def test_a_role_custom_id_does_not_match_a_class_template() -> None:
    custom_id = build_role_button_custom_id(Slot.MAIN, "mage", "dps")

    assert MAIN_CLASS_TEMPLATE.fullmatch(custom_id) is None
    assert ALTERNATE_CLASS_TEMPLATE.fullmatch(custom_id) is None


def test_every_custom_id_matches_exactly_one_template(classes: ClassCatalog) -> None:
    """The decisive property for persistence.

    After a restart discord.py rebuilds a handler by matching the custom_id stored in the
    message against each registered template. Two matches would make the handler depend on
    registration order; none would leave the button dead.
    """
    templates = (MAIN_CLASS_TEMPLATE, ALTERNATE_CLASS_TEMPLATE, ROLE_TEMPLATE)

    sent: list[str] = []
    for slot in Slot:
        for klass in classes.classes:
            sent.append(build_class_button_custom_id(slot, klass.key))
            for role in classes.roles_of(klass.key):
                sent.append(build_role_button_custom_id(slot, klass.key, role.key))

    for custom_id in sent:
        matching = [t for t in templates if t.fullmatch(custom_id) is not None]
        assert len(matching) == 1, f"{custom_id} matched {len(matching)} templates"


# --- the persistent views ------------------------------------------------------------


def test_each_board_holds_exactly_one_button_per_class(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """No reset button: a second click on a class is what undoes it."""
    for view in (build_main_view(classes, emojis), build_alternates_view(classes, emojis)):
        assert view.timeout is None
        assert len(view.children) == len(classes.classes)
        assert all(item.is_persistent() for item in view.children)


def test_each_board_fits_within_one_message(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """25 components maximum per message, which is why the boards are split in two."""
    assert len(build_main_view(classes, emojis).children) <= COMPONENTS_PER_MESSAGE
    assert len(build_alternates_view(classes, emojis).children) <= COMPONENTS_PER_MESSAGE


def test_the_buttons_show_the_icon_and_the_class_name(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    buttons = [
        item
        for item in build_main_view(classes, emojis).children
        if isinstance(item, MainClassButton)
    ]

    assert [button.item.label for button in buttons] == [k.name for k in classes.classes]
    assert all(button.item.emoji is not None for button in buttons)


def test_every_button_stays_grey_on_both_boards(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """A style belongs to the message, so a coloured one would show the last clicker."""
    for view in (build_main_view(classes, emojis), build_alternates_view(classes, emojis)):
        assert all(
            cast(discord.ui.Button[discord.ui.View], item.item).style
            is discord.ButtonStyle.secondary
            for item in view.children
            if isinstance(item, MainClassButton | AlternateClassButton)
        )


def test_the_board_decides_which_buttons_it_holds(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Otherwise a click on one board would be recorded on the other."""
    main = build_main_view(classes, emojis)
    alternates = build_alternates_view(classes, emojis)

    assert all(isinstance(item, MainClassButton) for item in main.children)
    assert all(isinstance(item, AlternateClassButton) for item in alternates.children)


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


async def test_a_new_main_removes_the_previous_class_role() -> None:
    """Two class roles would make the nickname colour depend on their order."""
    mage = FakeRole("Mage", 5, role_id=1)
    druide = FakeRole("Druide", 6, role_id=2)
    member = FakeMember(as_guild(), [mage])

    error = await apply_class_role(as_member(member), as_role(druide), {1, 2})

    assert error is None
    assert member.removed == [mage]
    assert member.added == [druide]


async def test_passing_no_role_strips_the_class_colour() -> None:
    """How a member ends up with no class colour, once something clears their choices."""
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


# --- the main board ------------------------------------------------------------------


def test_the_main_board_sorts_people_into_role_columns(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [
        _row("Kaeldin", 1, 1, "mage", "dps"),
        _row("Sylvara", 2, 1, "pretre", "heal"),
        _row("Bran", 3, 1, "druide", "tank"),
    ]

    columns = _values(main_board_embed(classes, emojis, rows))

    assert "Bran" in columns[TANK]
    assert "Sylvara" in columns[HEAL]
    assert "Kaeldin" in columns[DPS]
    assert "Kaeldin" not in columns[TANK]


def test_the_main_board_shows_the_class_icon_beside_the_name(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Without uploaded icons the unicode fallback stands in, so the line is never bare."""
    mage = classes.get("mage")
    assert mage is not None and mage.emoji is not None

    columns = _values(main_board_embed(classes, emojis, [_row("Kaeldin", 1, 1, "mage", "dps")]))

    assert f"{mage.emoji} Kaeldin" in columns[DPS]


def test_the_column_headers_carry_the_role_and_its_count(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row("Kaeldin", 1, 1, "mage", "dps"), _row("Sylvara", 2, 1, "voleur", "dps")]

    names = [field.name or "" for field in main_board_embed(classes, emojis, rows).fields]

    assert "Tank · 0" in names[TANK]
    assert "DPS · 2" in names[DPS]


def test_the_main_board_leaves_out_the_alternates(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row("Kaeldin", 1, 1, "mage", "dps"), _row("Kaeldin", 1, 2, "druide", "tank")]

    columns = _values(main_board_embed(classes, emojis, rows))

    assert "Kaeldin" in columns[DPS]
    assert columns[TANK] == "—"


def test_an_empty_main_board_says_so(classes: ClassCatalog, emojis: EmojiStore) -> None:
    embed = main_board_embed(classes, emojis, [])

    assert _values(embed) == ["—", "—", "—"]
    assert embed.footer.text is not None
    assert "Personne" in embed.footer.text


def test_the_main_board_counts_the_people_it_covers(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row("Kaeldin", 1, 1, "mage", "dps"), _row("Sylvara", 2, 1, "druide", "tank")]

    footer = main_board_embed(classes, emojis, rows).footer.text

    assert footer is not None
    assert footer.startswith("2 personne(s)")


# --- the alternates board ------------------------------------------------------------


def test_the_alternates_board_leaves_out_the_main_character(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row("Kaeldin", 1, 1, "mage", "dps"), _row("Kaeldin", 1, 2, "druide", "tank")]

    columns = _values(alternates_board_embed(classes, emojis, rows))

    assert "Kaeldin" in columns[TANK]
    assert columns[DPS] == "—"


def test_the_alternates_board_does_not_distinguish_the_ranks(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Rank 2 and rank 3 sit in the same list: the order carries no meaning."""
    rows = [_row("Kaeldin", 1, 2, "druide", "tank"), _row("Sylvara", 2, 3, "guerrier", "tank")]

    columns = _values(alternates_board_embed(classes, emojis, rows))

    assert "Kaeldin" in columns[TANK]
    assert "Sylvara" in columns[TANK]
    assert "①" not in columns[TANK]
    assert "②" not in columns[TANK]


def test_someone_appears_twice_when_they_listed_two_alternates(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row("Kaeldin", 1, 2, "druide", "tank"), _row("Kaeldin", 1, 3, "pretre", "heal")]

    embed = alternates_board_embed(classes, emojis, rows)
    columns = _values(embed)

    assert "Kaeldin" in columns[TANK]
    assert "Kaeldin" in columns[HEAL]
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("1 personne(s)")


def test_the_alternates_board_states_how_many_are_allowed(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    description = alternates_board_embed(classes, emojis, []).description or ""

    assert str(classes.max_alternates) in description


def test_an_empty_alternates_board_says_so(classes: ClassCatalog, emojis: EmojiStore) -> None:
    embed = alternates_board_embed(classes, emojis, [])

    assert embed.footer.text is not None
    assert "Personne" in embed.footer.text


# --- board limits --------------------------------------------------------------------


def test_a_name_holding_markdown_is_escaped(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """An asterisk in a pseudo would otherwise italicise the rest of the column."""
    columns = _values(main_board_embed(classes, emojis, [_row("Ka*el*din", 1, 1, "mage", "dps")]))

    assert r"Ka\*el\*din" in columns[DPS]


def test_a_crowded_column_is_truncated_rather_than_rejected(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Discord refuses a field value over 1024 characters outright."""
    rows = [_row(f"Joueur{index:03d}", index, 1, "mage", "dps") for index in range(400)]

    embed = main_board_embed(classes, emojis, rows)

    assert len(_values(embed)[DPS]) <= EMBED_FIELD_LIMIT
    assert embed.footer.text is not None
    assert "non affiché" in embed.footer.text


def test_the_boards_stay_within_the_api_limits(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    rows = [_row(f"Joueur{index:03d}", index, 1, "druide", "tank") for index in range(200)]
    rows += [_row(f"Joueur{index:03d}", index, 2, "mage", "dps") for index in range(200)]

    for embed in (
        main_board_embed(classes, emojis, rows),
        alternates_board_embed(classes, emojis, rows),
    ):
        assert len(embed) <= EMBED_TOTAL_LIMIT
        assert all(len(value) <= EMBED_FIELD_LIMIT for value in _values(embed))


# --- composition ---------------------------------------------------------------------


def test_composition_counts_main_characters_per_role(
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


def test_composition_reports_the_alternates_separately(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    """Two tanks with five tank alternates is not the same guild as two tanks."""
    choices = [_choice(1, 1, "mage", "dps"), _choice(1, 2, "druide", "tank")]

    roles = composition_embed(classes, emojis, choices).fields[0].value or ""

    assert "**Tank** — 0" in roles
    assert "+1 en classe envisagée" in roles


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


def test_the_composition_stays_within_the_api_limits(
    classes: ClassCatalog,
    emojis: EmojiStore,
) -> None:
    choices = [_choice(index, 1, "druide", "tank") for index in range(200)]
    choices += [_choice(index, 2, "mage", "dps") for index in range(200)]

    embed = composition_embed(classes, emojis, choices)

    assert len(embed) <= EMBED_TOTAL_LIMIT
    assert all(len(field.value or "") <= EMBED_FIELD_LIMIT for field in embed.fields)


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
