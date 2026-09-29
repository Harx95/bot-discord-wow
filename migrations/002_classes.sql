-- Class and raid-role choices, ranked by preference.
--
-- class_key and role_key are not foreign keys: classes live in classes.toml, not in the
-- database. The configuration is the source of truth, the database only records choices.

-- Ranked choices. Rank 1 is the character the member intends to main, and the only one
-- that earns a Discord role: two class roles would make the nickname colour depend on
-- which one happens to sit higher in the hierarchy.
CREATE TABLE member_choices (
    member_id  INTEGER NOT NULL REFERENCES members (discord_id) ON DELETE CASCADE,
    rank       INTEGER NOT NULL CHECK (rank >= 1),
    class_key  TEXT    NOT NULL,
    role_key   TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    -- One choice per rank, and the same class/role pair never twice for one member.
    PRIMARY KEY (member_id, rank),
    UNIQUE (member_id, class_key, role_key)
) STRICT;

CREATE INDEX idx_member_choices_rank ON member_choices (rank);

-- Discord roles created for each class, stored by id: renaming a role must not break anything.
CREATE TABLE class_roles (
    class_key  TEXT    NOT NULL PRIMARY KEY,
    role_id    INTEGER NOT NULL UNIQUE,
    created_at TEXT    NOT NULL
) STRICT;

-- Messages the bot keeps up to date, such as the class directory. Keyed by purpose so the
-- profession directory of a later step can reuse the same table.
CREATE TABLE managed_messages (
    key        TEXT    NOT NULL PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    updated_at TEXT    NOT NULL
) STRICT;
