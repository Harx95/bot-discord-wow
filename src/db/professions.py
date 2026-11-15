"""Guild roster, profession names and skills from the Blizzard API. All their SQL lives here."""

from collections.abc import Mapping, Sequence

import aiosqlite

from db.timestamps import to_iso, utcnow
from domain import CharacterSkill, DirectoryLine, GuildCharacter, Profession


def _to_line(row: aiosqlite.Row) -> DirectoryLine:
    """Build a directory line from a joined database row."""
    return DirectoryLine(
        profession=Profession(id=row["profession_id"], name=row["profession_name"]),
        character_name=row["character_name"],
        skill=row["skill"],
        max_skill=row["max_skill"],
    )


class ProfessionRepo:
    """Read and write the profession directory.

    The tables mirror the game: a sync replaces what it fetched, and nothing else writes
    to them.
    """

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._db = connection

    # --- profession names -------------------------------------------------------------

    async def known_profession_ids(self) -> set[int]:
        """Professions whose French name is already stored."""
        async with self._db.execute("SELECT id FROM professions") as cursor:
            return {row["id"] for row in await cursor.fetchall()}

    async def save_profession(self, profession: Profession) -> None:
        """Store the French name of a profession, replacing a previous one."""
        await self._db.execute(
            """
            INSERT INTO professions (id, name, fetched_at) VALUES (?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                fetched_at = excluded.fetched_at
            """,
            (profession.id, profession.name, to_iso(utcnow())),
        )
        await self._db.commit()

    # --- sync -------------------------------------------------------------------------

    async def apply_sync(
        self,
        roster: Sequence[GuildCharacter],
        skills: Mapping[str, Sequence[CharacterSkill]],
    ) -> bool:
        """Mirror the roster and the skills fetched, all or nothing. Returns whether the
        directory changed.

        Characters off the roster are dropped with their skills. A character on the roster
        but missing from `skills` keeps the skills of the previous sync: the API hides
        characters below level 10 and those who never logged out, which says nothing about
        what they know.

        Every profession named in `skills` must already be stored.
        """
        now = to_iso(utcnow())
        slugs = [character.slug for character in roster]

        await self._db.execute("BEGIN")
        try:
            before = await self.directory()

            placeholders = ", ".join("?" for _ in slugs)
            await self._db.execute(
                f"DELETE FROM guild_characters WHERE slug NOT IN ({placeholders})",
                slugs,
            )
            await self._db.executemany(
                """
                INSERT INTO guild_characters (slug, name, surname, level, synced_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (slug) DO UPDATE SET
                    name = excluded.name,
                    surname = excluded.surname,
                    level = excluded.level,
                    synced_at = excluded.synced_at
                """,
                [(c.slug, c.name, c.surname, c.level, now) for c in roster],
            )

            on_roster = set(slugs)
            for slug, character_skills in skills.items():
                if slug not in on_roster:
                    continue
                await self._db.execute(
                    "DELETE FROM character_skills WHERE character_slug = ?",
                    (slug,),
                )
                await self._db.executemany(
                    """
                    INSERT INTO character_skills
                        (character_slug, profession_id, skill, max_skill)
                    VALUES (?, ?, ?, ?)
                    """,
                    [(slug, s.profession_id, s.skill, s.max_skill) for s in character_skills],
                )

            after = await self.directory()
        except Exception:
            await self._db.rollback()
            raise

        await self._db.commit()
        return before != after

    # --- reading ----------------------------------------------------------------------

    async def directory(self) -> list[DirectoryLine]:
        """Every character under every profession, best skill first within a profession."""
        async with self._db.execute(
            """
            SELECT
                p.id AS profession_id,
                p.name AS profession_name,
                c.name || ' ' || c.surname AS character_name,
                s.skill,
                s.max_skill
            FROM character_skills AS s
            JOIN professions AS p ON p.id = s.profession_id
            JOIN guild_characters AS c ON c.slug = s.character_slug
            ORDER BY p.name, s.skill DESC, character_name COLLATE NOCASE
            """
        ) as cursor:
            return [_to_line(row) for row in await cursor.fetchall()]

    async def character_count(self) -> int:
        """How many characters the last sync found on the roster."""
        async with self._db.execute("SELECT COUNT(*) AS n FROM guild_characters") as cursor:
            row = await cursor.fetchone()
        return row["n"] if row is not None else 0
