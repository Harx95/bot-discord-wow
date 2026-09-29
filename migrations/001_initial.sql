-- Initial schema: guild members and polls.
-- Timestamps are ISO-8601 UTC strings; SQLite has no native date type.

CREATE TABLE members (
    discord_id    INTEGER PRIMARY KEY,
    display_name  TEXT    NOT NULL,
    first_seen_at TEXT    NOT NULL,
    last_seen_at  TEXT    NOT NULL
) STRICT;

CREATE TABLE polls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    channel_id INTEGER,
    message_id INTEGER,
    created_at TEXT    NOT NULL,
    closed_at  TEXT,
    -- A closed poll always records when it was closed, and an open one never does.
    CHECK ((status = 'closed') = (closed_at IS NOT NULL))
) STRICT;

CREATE TABLE poll_options (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id    INTEGER NOT NULL REFERENCES polls (id) ON DELETE CASCADE,
    key        TEXT    NOT NULL,
    -- Discord caps a select option label at 100 characters.
    label      TEXT    NOT NULL CHECK (length(label) <= 100),
    position   INTEGER NOT NULL,
    -- Set when a member proposed the option, NULL when it comes from configuration.
    created_by INTEGER REFERENCES members (discord_id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL,
    UNIQUE (poll_id, key),
    UNIQUE (poll_id, position)
) STRICT;

-- Lets poll_votes reference an option together with its poll.
CREATE UNIQUE INDEX idx_poll_options_poll_id_id ON poll_options (poll_id, id);

CREATE TABLE poll_votes (
    poll_id   INTEGER NOT NULL REFERENCES polls (id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members (discord_id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL,
    voted_at  TEXT    NOT NULL,
    -- One vote per member per poll; changing your mind is an upsert.
    PRIMARY KEY (poll_id, member_id),
    -- The chosen option must belong to the poll being voted on.
    FOREIGN KEY (poll_id, option_id)
        REFERENCES poll_options (poll_id, id) ON DELETE CASCADE
) STRICT;

CREATE INDEX idx_poll_votes_option_id ON poll_votes (option_id);
