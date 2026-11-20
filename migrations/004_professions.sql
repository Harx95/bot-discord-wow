-- The profession directory, mirrored from the Battle.net API.
--
-- Everything here is a cache of what Blizzard says, rebuilt by the daily sync: it is never
-- edited by a member, and losing it costs one sync rather than any data. That is also why
-- the commands never call the API -- they read these tables and nothing else.
--
-- blizzard_id is the skill line id the profile API answers with. It is not a foreign key:
-- professions live in professions.toml, which stays the source of truth for their French
-- name and their order, exactly as classes.toml does for the classes.

-- One row per character the guild roster lists, whatever its level. Characters below level
-- 10 are kept here even though the API refuses to describe them, so the directory can say
-- how many characters it could not look at.
CREATE TABLE roster_characters (
    slug         TEXT    NOT NULL PRIMARY KEY,
    name         TEXT    NOT NULL,
    surname      TEXT,
    level        INTEGER NOT NULL CHECK (level >= 1),
    character_id INTEGER,
    class_id     INTEGER,
    rank         INTEGER NOT NULL,
    synced_at    TEXT    NOT NULL
) STRICT;

-- api_name is the English name the API gave, kept as the fallback label for a profession
-- professions.toml does not list yet.
CREATE TABLE character_professions (
    slug        TEXT    NOT NULL REFERENCES roster_characters (slug) ON DELETE CASCADE,
    blizzard_id INTEGER NOT NULL,
    api_name    TEXT    NOT NULL,
    skill       INTEGER NOT NULL CHECK (skill >= 0),
    max_skill   INTEGER NOT NULL CHECK (max_skill >= 0),
    PRIMARY KEY (slug, blizzard_id)
) STRICT;

-- A permanent dictionary, not part of a character's data: a recipe name never changes, so a
-- recipe is fetched once and kept for good. The daily sync only looks up ids it has never
-- seen, which is why it costs 26 requests rather than 600 after the first run.
--
-- name_en arrives with the character's professions, so it is always known. name_fr and the
-- crafted item come from a second call to the static namespace, which is the only place
-- Blizzard localises anything: when that call has not happened yet, or failed, the row is
-- still usable and the English search still finds it.
CREATE TABLE recipes (
    recipe_id       INTEGER NOT NULL PRIMARY KEY,
    name_en         TEXT    NOT NULL,
    name_fr         TEXT,
    crafted_item_id INTEGER,
    crafted_name_en TEXT,
    crafted_name_fr TEXT,
    localised_at    TEXT
) STRICT;

-- Every folded form a recipe can be searched by: its own name in both languages, and the
-- crafted item's when it crafts one. A row per term rather than two columns of text, so the
-- lookup is one indexed join instead of four LIKE comparisons.
CREATE TABLE recipe_terms (
    recipe_id INTEGER NOT NULL REFERENCES recipes (recipe_id) ON DELETE CASCADE,
    term      TEXT    NOT NULL,
    PRIMARY KEY (recipe_id, term)
) STRICT;

CREATE INDEX idx_recipe_terms_term ON recipe_terms (term);

-- Who knows what. The profession is carried alongside the recipe so /recettes can filter on
-- it without joining back through the recipe.
CREATE TABLE character_recipes (
    slug        TEXT    NOT NULL,
    blizzard_id INTEGER NOT NULL,
    recipe_id   INTEGER NOT NULL REFERENCES recipes (recipe_id),
    PRIMARY KEY (slug, recipe_id),
    FOREIGN KEY (slug, blizzard_id)
        REFERENCES character_professions (slug, blizzard_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX idx_character_recipes_recipe ON character_recipes (recipe_id);

-- The last sync, one row, for the directory footer and for /synchro-metiers to report on.
-- failures holds one message per line; empty means the sync was clean.
CREATE TABLE profession_sync (
    id              INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    started_at      TEXT    NOT NULL,
    finished_at     TEXT    NOT NULL,
    characters      INTEGER NOT NULL,
    skipped         INTEGER NOT NULL,
    professions     INTEGER NOT NULL,
    recipe_links    INTEGER NOT NULL,
    recipes_fetched INTEGER NOT NULL,
    failures        TEXT    NOT NULL
) STRICT;
