"""Profession directory: API parsing, storage, sync and the message drawn from it."""

from pathlib import Path

import aiosqlite
import pytest

from blizzard import BlizzardError, parse_primary_skills, parse_roster
from bot.directory import (
    EMBED_FIELDS_LIMIT,
    EMBED_TOTAL_LIMIT,
    FIELD_VALUE_LIMIT,
    directory_embed,
    sync_directory,
)
from config import ProfessionCatalog, load_professions
from db import ProfessionRepo
from domain import CharacterSkill, DirectoryLine, GuildCharacter, Profession

PROJECT_PROFESSIONS = Path(__file__).resolve().parents[1] / "professions.toml"

LEATHER = Profession(id=165, name="Travail du cuir")
SKINNING = Profession(id=393, name="Dépeçage")
COOKING_ID = 185

HARX = GuildCharacter(slug="harx-windharrow", name="Harx", surname="Windharrow", level=33)
RINE = GuildCharacter(slug="rine-kamechki", name="Rine", surname="Kamechki", level=35)
VOUZ = GuildCharacter(slug="vouz-kamechki", name="Vouz", surname="Kamechki", level=8)


def _skill(profession: Profession, skill: int, max_skill: int = 150) -> CharacterSkill:
    return CharacterSkill(profession_id=profession.id, skill=skill, max_skill=max_skill)


@pytest.fixture
def professions() -> ProfessionCatalog:
    """The profession icons actually shipped with the project."""
    return load_professions(PROJECT_PROFESSIONS)


@pytest.fixture
def repo(connection: aiosqlite.Connection) -> ProfessionRepo:
    """Profession repository bound to the temporary database."""
    return ProfessionRepo(connection)


class FakeSource:
    """Answers like the API, from canned data."""

    def __init__(
        self,
        roster: list[GuildCharacter],
        skills: dict[str, list[CharacterSkill] | None],
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self.roster = roster
        self.skills = skills
        self.failing = failing
        self.profession_lookups: list[int] = []

    async def guild_roster(self, guild_slug: str) -> list[GuildCharacter]:
        return self.roster

    async def primary_skills(self, character_slug: str) -> list[CharacterSkill] | None:
        if character_slug in self.failing:
            raise BlizzardError("HTTP 503")
        return self.skills.get(character_slug)

    async def profession(self, profession_id: int) -> Profession:
        self.profession_lookups.append(profession_id)
        return {LEATHER.id: LEATHER, SKINNING.id: SKINNING}[profession_id]


# --- parsing ------------------------------------------------------------------------------


def test_roster_is_parsed_into_characters() -> None:
    payload = {
        "members": [
            {
                "character": {
                    "name": "Harx",
                    "surname": "Windharrow",
                    "slug": "harx-windharrow",
                    "level": 33,
                    "id": 2634357,
                },
                "rank": 3,
            }
        ]
    }
    assert parse_roster(payload) == [HARX]


def test_only_primary_professions_are_kept() -> None:
    payload = {
        "primaries": [
            {
                "profession": {"id": 165, "name": "Leatherworking"},
                "tiers": [{"skill_points": 122, "max_skill_points": 150, "known_recipes": []}],
            }
        ],
        "secondaries": [
            {
                "profession": {"id": COOKING_ID, "name": "Cooking"},
                "tiers": [{"skill_points": 104, "max_skill_points": 150}],
            }
        ],
    }
    assert parse_primary_skills(payload) == [_skill(LEATHER, 122)]


def test_a_profession_without_tiers_is_skipped() -> None:
    payload = {"primaries": [{"profession": {"id": 165, "name": "Leatherworking"}, "tiers": []}]}
    assert parse_primary_skills(payload) == []


# --- repository ---------------------------------------------------------------------------


async def test_sync_stores_skills_best_first(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)

    changed = await repo.apply_sync(
        [HARX, RINE],
        {HARX.slug: [_skill(LEATHER, 122)], RINE.slug: [_skill(LEATHER, 140, 225)]},
    )

    assert changed
    assert await repo.directory() == [
        DirectoryLine(LEATHER, "Rine Kamechki", 140, 225),
        DirectoryLine(LEATHER, "Harx Windharrow", 122, 150),
    ]
    assert await repo.character_count() == 2


async def test_identical_sync_reports_no_change(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)
    skills = {HARX.slug: [_skill(LEATHER, 122)]}

    await repo.apply_sync([HARX], skills)

    assert not await repo.apply_sync([HARX], skills)


async def test_a_character_leaving_the_guild_leaves_the_directory(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)
    await repo.apply_sync(
        [HARX, RINE],
        {HARX.slug: [_skill(LEATHER, 122)], RINE.slug: [_skill(LEATHER, 140)]},
    )

    changed = await repo.apply_sync([HARX], {HARX.slug: [_skill(LEATHER, 122)]})

    assert changed
    assert [line.character_name for line in await repo.directory()] == ["Harx Windharrow"]
    assert await repo.character_count() == 1


async def test_a_character_not_fetched_keeps_its_skills(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)
    await repo.apply_sync([HARX], {HARX.slug: [_skill(LEATHER, 122)]})

    changed = await repo.apply_sync([HARX], {})

    assert not changed
    assert len(await repo.directory()) == 1


async def test_a_dropped_profession_disappears(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)
    await repo.save_profession(SKINNING)
    await repo.apply_sync([HARX], {HARX.slug: [_skill(LEATHER, 122), _skill(SKINNING, 208)]})

    await repo.apply_sync([HARX], {HARX.slug: [_skill(SKINNING, 208)]})

    assert [line.profession for line in await repo.directory()] == [SKINNING]


# --- sync ---------------------------------------------------------------------------------


async def test_sync_reports_hidden_and_failed_characters(repo: ProfessionRepo) -> None:
    source = FakeSource(
        [HARX, RINE, VOUZ],
        {HARX.slug: [_skill(LEATHER, 122)], VOUZ.slug: None},
        failing=frozenset({RINE.slug}),
    )

    report = await sync_directory(source, repo, "guild")

    assert report.roster_size == 3
    assert report.fetched == 1
    assert report.hidden == ["Vouz Kamechki"]
    assert report.failed == ["Rine Kamechki"]
    assert report.changed


async def test_profession_names_are_looked_up_once(repo: ProfessionRepo) -> None:
    source = FakeSource([HARX], {HARX.slug: [_skill(LEATHER, 122)]})

    await sync_directory(source, repo, "guild")
    await sync_directory(source, repo, "guild")

    assert source.profession_lookups == [LEATHER.id]
    assert (await repo.directory())[0].profession.name == "Travail du cuir"


async def test_an_empty_roster_is_refused(repo: ProfessionRepo) -> None:
    await repo.save_profession(LEATHER)
    await repo.apply_sync([HARX], {HARX.slug: [_skill(LEATHER, 122)]})

    with pytest.raises(BlizzardError):
        await sync_directory(FakeSource([], {}), repo, "guild")

    assert len(await repo.directory()) == 1


# --- rendering ----------------------------------------------------------------------------


def test_each_profession_gets_its_emoji_and_block(professions: ProfessionCatalog) -> None:
    lines = [
        DirectoryLine(SKINNING, "Harx Windharrow", 208, 225),
        DirectoryLine(LEATHER, "Rine Kamechki", 140, 225),
        DirectoryLine(LEATHER, "Harx Windharrow", 122, 150),
    ]

    embed = directory_embed(lines, professions, character_count=28, sync_hour=5)

    assert [field.name for field in embed.fields] == [
        f"{professions.emoji_of(SKINNING.id)} Dépeçage",
        f"{professions.emoji_of(LEATHER.id)} Travail du cuir",
    ]
    leather = embed.fields[1].value or ""
    assert leather.index("Rine") < leather.index("Harx")
    assert "**140**" in leather
    assert embed.footer.text is not None and "28 personnages" in embed.footer.text


def test_an_unconfigured_profession_falls_back_to_the_default_emoji(
    professions: ProfessionCatalog,
) -> None:
    unknown = Profession(id=999_999, name="Archéologie")
    embed = directory_embed([DirectoryLine(unknown, "Harx Windharrow", 10, 75)], professions, 1, 5)
    assert embed.fields[0].name == f"{professions.default_emoji} Archéologie"


def test_an_empty_directory_says_so(professions: ProfessionCatalog) -> None:
    embed = directory_embed([], professions, 0, 5)
    assert not embed.fields
    assert "Aucun métier" in (embed.description or "")


def test_a_long_profession_continues_in_a_second_field(professions: ProfessionCatalog) -> None:
    lines = [
        DirectoryLine(LEATHER, f"Personnage{index:03d} Nomdefamillelong", 300 - index, 300)
        for index in range(40)
    ]

    embed = directory_embed(lines, professions, 40, 5)

    assert len(embed.fields) >= 2
    assert all(len(field.value or "") <= FIELD_VALUE_LIMIT for field in embed.fields)
    assert (embed.fields[1].name or "").endswith("(suite)")
    shown = sum((field.value or "").count("\n") + 1 for field in embed.fields)
    assert shown == 40


def test_an_oversized_directory_stays_within_discord_limits(
    professions: ProfessionCatalog,
) -> None:
    lines = [
        DirectoryLine(
            Profession(id=1000 + index % 30, name=f"Métier {index % 30:02d}"),
            f"Personnage{index:04d} Nomdefamilletreslong",
            150,
            300,
        )
        for index in range(600)
    ]
    lines.sort(key=lambda line: line.profession.id)

    embed = directory_embed(lines, professions, 600, 5)

    assert len(embed.fields) <= EMBED_FIELDS_LIMIT
    assert len(embed) <= EMBED_TOTAL_LIMIT
    assert embed.footer.text is not None and "non affichée" in embed.footer.text


def test_duplicate_profession_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ProfessionCatalog.model_validate(
            {
                "default_emoji": "🛠️",
                "skill_cap": 300,
                "professions": [{"id": 1, "emoji": "a"}, {"id": 1, "emoji": "b"}],
            }
        )
