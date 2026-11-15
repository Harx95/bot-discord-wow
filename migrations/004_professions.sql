-- Profession directory, filled from the Blizzard API by the daily sync.
--
-- Nothing here is typed in by members: every row mirrors what the game reports, and a sync
-- rewrites it. The profession list is not hardcoded either, it grows as the API names one.

-- The guild roster. WoW Forever has no realms, so the slug alone identifies a character.
CREATE TABLE guild_characters (
    slug      TEXT    NOT NULL PRIMARY KEY,
    name      TEXT    NOT NULL,
    surname   TEXT    NOT NULL,
    level     INTEGER NOT NULL CHECK (level >= 1),
    synced_at TEXT    NOT NULL
) STRICT;

-- Profession names in French. The character endpoint only answers in English, so each name
-- is looked up once in the static data and kept here.
CREATE TABLE professions (
    id         INTEGER NOT NULL PRIMARY KEY,
    name       TEXT    NOT NULL,
    fetched_at TEXT    NOT NULL
) STRICT;

-- Primary professions of each character. A character leaving the guild takes its rows along.
CREATE TABLE character_skills (
    character_slug TEXT    NOT NULL REFERENCES guild_characters (slug) ON DELETE CASCADE,
    profession_id  INTEGER NOT NULL REFERENCES professions (id),
    skill          INTEGER NOT NULL CHECK (skill >= 0),
    max_skill      INTEGER NOT NULL CHECK (max_skill >= 0),
    PRIMARY KEY (character_slug, profession_id)
) STRICT;

CREATE INDEX idx_character_skills_profession ON character_skills (profession_id);
