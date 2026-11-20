"""Read and write the profession directory mirrored from the Battle.net API.

Every table here is a cache of what Blizzard said, so the writers replace rather than merge:
a sync is the whole truth about a character, and a profession dropped in game must disappear
here too. The commands read these tables and never call the API.
"""

from collections.abc import Iterable, Sequence

import aiosqlite

from db.timestamps import from_iso, to_iso, utcnow
from domain import Artisan, CharacterProfession, DirectoryRow, Recipe, RosterCharacter, SyncReport
from domain.text import fold

# A select menu holds 25 options, and an embed 25 fields: no answer may exceed either.
ANSWER_LIMIT = 25


def _to_character(row: aiosqlite.Row) -> RosterCharacter:
    """Build a domain entity from a database row."""
    return RosterCharacter(
        slug=row["slug"],
        name=row["name"],
        surname=row["surname"],
        level=row["level"],
        character_id=row["character_id"],
        class_id=row["class_id"],
        rank=row["rank"],
    )


def _to_recipe(row: aiosqlite.Row) -> Recipe:
    return Recipe(
        recipe_id=row["recipe_id"],
        name_en=row["name_en"],
        name_fr=row["name_fr"],
        crafted_item_id=row["crafted_item_id"],
        crafted_name_en=row["crafted_name_en"],
        crafted_name_fr=row["crafted_name_fr"],
    )


def _display(row: aiosqlite.Row) -> str:
    """A character as members say it, built from the stored name and surname."""
    surname = row["surname"]
    return f"{row['name']}-{surname}" if surname else row["name"]


class ProfessionRepo:
    """The guild roster, its professions, and the recipe dictionary."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    # --- writing, during a sync ------------------------------------------------------

    async def replace_roster(self, characters: Sequence[RosterCharacter]) -> None:
        """Make the stored roster exactly the one given.

        Characters who left are deleted, which cascades their professions and recipes away.
        One transaction: a half-written roster would make the directory lie.
        """
        now = to_iso(utcnow())
        await self._db.execute("BEGIN")
        try:
            if characters:
                slugs = [character.slug for character in characters]
                placeholders = ",".join("?" * len(slugs))
                await self._db.execute(
                    f"DELETE FROM roster_characters WHERE slug NOT IN ({placeholders})",
                    slugs,
                )
            else:
                await self._db.execute("DELETE FROM roster_characters")

            await self._db.executemany(
                """
                INSERT INTO roster_characters
                    (slug, name, surname, level, character_id, class_id, rank, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (slug) DO UPDATE SET
                    name         = excluded.name,
                    surname      = excluded.surname,
                    level        = excluded.level,
                    character_id = excluded.character_id,
                    class_id     = excluded.class_id,
                    rank         = excluded.rank,
                    synced_at    = excluded.synced_at
                """,
                [
                    (
                        character.slug,
                        character.name,
                        character.surname,
                        character.level,
                        character.character_id,
                        character.class_id,
                        character.rank,
                        now,
                    )
                    for character in characters
                ],
            )
        except Exception:
            await self._db.rollback()
            raise
        await self._db.commit()

    async def replace_character_professions(
        self,
        slug: str,
        professions: Sequence[CharacterProfession],
        recipes: Sequence[tuple[int, int, str]],
    ) -> None:
        """Replace one character's professions and the recipes they know.

        recipes is (blizzard_id, recipe_id, english_name): the professions endpoint carries
        the English name, so a recipe is recorded the moment it is seen and stays searchable
        even if its French name is never fetched.

        One transaction per character rather than one for the whole sync: a character whose
        call failed halfway leaves the others correct, and the next sync fixes that one.
        """
        await self._db.execute("BEGIN")
        try:
            await self._db.execute("DELETE FROM character_professions WHERE slug = ?", (slug,))
            await self._db.executemany(
                """
                INSERT INTO character_professions
                    (slug, blizzard_id, api_name, skill, max_skill)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(slug, p.blizzard_id, p.api_name, p.skill, p.max_skill) for p in professions],
            )

            # The dictionary only gains rows: an English name already stored is left alone,
            # so a localised row is never knocked back to English by a later sync.
            await self._db.executemany(
                """
                INSERT INTO recipes (recipe_id, name_en)
                VALUES (?, ?)
                ON CONFLICT (recipe_id) DO NOTHING
                """,
                [(recipe_id, name) for _, recipe_id, name in recipes],
            )
            await self._db.executemany(
                """
                INSERT INTO recipe_terms (recipe_id, term)
                VALUES (?, ?)
                ON CONFLICT (recipe_id, term) DO NOTHING
                """,
                [(recipe_id, fold(name)) for _, recipe_id, name in recipes if fold(name)],
            )
            await self._db.executemany(
                """
                INSERT INTO character_recipes (slug, blizzard_id, recipe_id)
                VALUES (?, ?, ?)
                ON CONFLICT (slug, recipe_id) DO UPDATE SET blizzard_id = excluded.blizzard_id
                """,
                [(slug, blizzard_id, recipe_id) for blizzard_id, recipe_id, _ in recipes],
            )
        except Exception:
            await self._db.rollback()
            raise
        await self._db.commit()

    async def recipes_awaiting_translation(self) -> list[int]:
        """Recipe ids whose French name has never been fetched, oldest id first."""
        async with self._db.execute(
            "SELECT recipe_id FROM recipes WHERE localised_at IS NULL ORDER BY recipe_id"
        ) as cursor:
            return [row["recipe_id"] for row in await cursor.fetchall()]

    async def localise_recipes(self, recipes: Iterable[Recipe]) -> int:
        """Fill in the French names and the crafted item, and rebuild the search terms."""
        entries = list(recipes)
        if not entries:
            return 0

        now = to_iso(utcnow())
        await self._db.execute("BEGIN")
        try:
            await self._db.executemany(
                """
                UPDATE recipes SET
                    name_en         = ?,
                    name_fr         = ?,
                    crafted_item_id = ?,
                    crafted_name_en = ?,
                    crafted_name_fr = ?,
                    localised_at    = ?
                WHERE recipe_id = ?
                """,
                [
                    (
                        recipe.name_en,
                        recipe.name_fr,
                        recipe.crafted_item_id,
                        recipe.crafted_name_en,
                        recipe.crafted_name_fr,
                        now,
                        recipe.recipe_id,
                    )
                    for recipe in entries
                ],
            )
            # Rebuilt, not appended to: a corrected name must stop matching its old spelling.
            await self._db.executemany(
                "DELETE FROM recipe_terms WHERE recipe_id = ?",
                [(recipe.recipe_id,) for recipe in entries],
            )
            await self._db.executemany(
                "INSERT INTO recipe_terms (recipe_id, term) VALUES (?, ?)",
                [(recipe.recipe_id, term) for recipe in entries for term in recipe.search_terms],
            )
        except Exception:
            await self._db.rollback()
            raise
        await self._db.commit()
        return len(entries)

    async def record_sync(self, report: SyncReport) -> None:
        """Keep the outcome of the last sync, replacing the previous one."""
        await self._db.execute(
            """
            INSERT INTO profession_sync (
                id, started_at, finished_at, characters, skipped,
                professions, recipe_links, recipes_fetched, failures
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                started_at      = excluded.started_at,
                finished_at     = excluded.finished_at,
                characters      = excluded.characters,
                skipped         = excluded.skipped,
                professions     = excluded.professions,
                recipe_links    = excluded.recipe_links,
                recipes_fetched = excluded.recipes_fetched,
                failures        = excluded.failures
            """,
            (
                to_iso(report.started_at),
                to_iso(report.finished_at),
                report.characters,
                report.skipped,
                report.professions,
                report.recipe_links,
                report.recipes_fetched,
                "\n".join(report.failures),
            ),
        )
        await self._db.commit()

    async def last_sync(self) -> SyncReport | None:
        """The outcome of the last sync, or None if none has run yet."""
        async with self._db.execute("SELECT * FROM profession_sync WHERE id = 1") as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None
        return SyncReport(
            started_at=from_iso(row["started_at"]),
            finished_at=from_iso(row["finished_at"]),
            characters=row["characters"],
            skipped=row["skipped"],
            professions=row["professions"],
            recipe_links=row["recipe_links"],
            recipes_fetched=row["recipes_fetched"],
            failures=tuple(line for line in row["failures"].splitlines() if line),
        )

    # --- reading, for the directory and the commands ---------------------------------

    async def roster(self) -> list[RosterCharacter]:
        """Every stored character, highest level first, then by name."""
        async with self._db.execute(
            "SELECT * FROM roster_characters ORDER BY level DESC, name COLLATE NOCASE"
        ) as cursor:
            return [_to_character(row) for row in await cursor.fetchall()]

    async def directory(self, blizzard_id: int) -> list[DirectoryRow]:
        """The artisans of one profession, most skilled first."""
        async with self._db.execute(
            """
            SELECT c.name, c.surname, p.skill, p.max_skill
            FROM character_professions p
            JOIN roster_characters c ON c.slug = p.slug
            WHERE p.blizzard_id = ?
            ORDER BY p.skill DESC, c.name COLLATE NOCASE
            """,
            (blizzard_id,),
        ) as cursor:
            return [
                DirectoryRow(
                    character=_display(row),
                    skill=row["skill"],
                    max_skill=row["max_skill"],
                )
                for row in await cursor.fetchall()
            ]

    async def artisans_for(self, query: str, limit: int = ANSWER_LIMIT) -> list[Artisan]:
        """Who can craft what a member typed, most skilled first.

        The term is folded the same way the stored terms were, so case and accents do not
        matter, and matched as a substring so "force de titan" finds the full name.
        """
        term = fold(query)
        if not term:
            return []

        async with self._db.execute(
            """
            SELECT DISTINCT
                c.name, c.surname, p.blizzard_id, p.api_name, p.skill, p.max_skill,
                r.recipe_id, r.name_en, r.name_fr
            FROM recipe_terms t
            JOIN recipes r ON r.recipe_id = t.recipe_id
            JOIN character_recipes cr ON cr.recipe_id = r.recipe_id
            JOIN character_professions p
                ON p.slug = cr.slug AND p.blizzard_id = cr.blizzard_id
            JOIN roster_characters c ON c.slug = cr.slug
            WHERE t.term LIKE '%' || ? || '%'
            ORDER BY p.skill DESC, c.name COLLATE NOCASE
            LIMIT ?
            """,
            (term, limit),
        ) as cursor:
            return [
                Artisan(
                    character=_display(row),
                    blizzard_id=row["blizzard_id"],
                    profession_name=row["api_name"],
                    skill=row["skill"],
                    max_skill=row["max_skill"],
                    recipe_id=row["recipe_id"],
                    recipe_name=row["name_fr"] or row["name_en"],
                )
                for row in await cursor.fetchall()
            ]

    async def recipe_matches(self, query: str) -> int:
        """How many distinct recipes match and are known by somebody.

        Counted through character_recipes rather than off the dictionary: a recipe stays in
        the dictionary for ever, so one whose profession the guild stopped tracking, or whose
        only owner left, would otherwise be counted while artisans_for() answered nobody.
        """
        term = fold(query)
        if not term:
            return 0
        async with self._db.execute(
            """
            SELECT COUNT(DISTINCT t.recipe_id) AS n
            FROM recipe_terms t
            JOIN character_recipes cr ON cr.recipe_id = t.recipe_id
            WHERE t.term LIKE '%' || ? || '%'
            """,
            (term,),
        ) as cursor:
            row = await cursor.fetchone()
        return row["n"] if row else 0

    async def known_recipes(self, slug: str, blizzard_id: int) -> list[Recipe]:
        """Every recipe one character knows in one profession, French name first."""
        async with self._db.execute(
            """
            SELECT r.*
            FROM character_recipes cr
            JOIN recipes r ON r.recipe_id = cr.recipe_id
            WHERE cr.slug = ? AND cr.blizzard_id = ?
            ORDER BY COALESCE(r.name_fr, r.name_en) COLLATE NOCASE
            """,
            (slug, blizzard_id),
        ) as cursor:
            return [_to_recipe(row) for row in await cursor.fetchall()]

    async def professions_of(self, slug: str) -> list[CharacterProfession]:
        """One character's professions, as stored."""
        async with self._db.execute(
            "SELECT * FROM character_professions WHERE slug = ? ORDER BY blizzard_id",
            (slug,),
        ) as cursor:
            return [
                CharacterProfession(
                    slug=row["slug"],
                    blizzard_id=row["blizzard_id"],
                    api_name=row["api_name"],
                    skill=row["skill"],
                    max_skill=row["max_skill"],
                )
                for row in await cursor.fetchall()
            ]

    async def characters_like(self, prefix: str, limit: int = ANSWER_LIMIT) -> list[str]:
        """Character slugs for autocompletion, only those that have a profession."""
        term = fold(prefix)
        async with self._db.execute(
            """
            SELECT DISTINCT c.slug, c.name, c.surname
            FROM roster_characters c
            JOIN character_professions p ON p.slug = c.slug
            WHERE ? = '' OR c.slug LIKE '%' || ? || '%'
            ORDER BY c.name COLLATE NOCASE
            LIMIT ?
            """,
            (term, term.replace(" ", "-"), limit),
        ) as cursor:
            return [row["slug"] for row in await cursor.fetchall()]

    async def counts(self) -> tuple[int, int, int, int]:
        """Characters, professions, recipe links and distinct recipes currently stored."""
        async with self._db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM roster_characters)      AS characters,
                (SELECT COUNT(*) FROM character_professions)  AS professions,
                (SELECT COUNT(*) FROM character_recipes)      AS links,
                (SELECT COUNT(*) FROM recipes)                AS recipes
            """
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:  # pragma: no cover -- a scalar subquery always yields a row
            raise RuntimeError("Counting the profession tables returned no row")
        return row["characters"], row["professions"], row["links"], row["recipes"]
