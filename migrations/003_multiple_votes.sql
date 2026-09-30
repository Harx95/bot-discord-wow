-- Let a member back several options of the same poll.
--
-- Votes are cast by reacting, and a member can hold several reactions on one message, so
-- the old PRIMARY KEY (poll_id, member_id) could not represent what Discord already shows.
-- Whether a poll actually allows it is a property of the poll definition, not of the
-- schema: the repository enforces single choice for the polls configured that way.
--
-- SQLite cannot alter a primary key, hence the rebuild. Existing votes carry over as-is,
-- one row each, so nothing recorded before this migration is lost.

CREATE TABLE poll_votes_rebuilt (
    poll_id   INTEGER NOT NULL REFERENCES polls (id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members (discord_id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL,
    voted_at  TEXT    NOT NULL,
    -- One row per option backed, so a member may appear several times on a poll.
    PRIMARY KEY (poll_id, member_id, option_id),
    -- The chosen option must belong to the poll being voted on.
    FOREIGN KEY (poll_id, option_id)
        REFERENCES poll_options (poll_id, id) ON DELETE CASCADE
) STRICT;

INSERT INTO poll_votes_rebuilt (poll_id, member_id, option_id, voted_at)
SELECT poll_id, member_id, option_id, voted_at FROM poll_votes;

DROP TABLE poll_votes;

ALTER TABLE poll_votes_rebuilt RENAME TO poll_votes;

-- Dropping the old table dropped its index with it.
CREATE INDEX idx_poll_votes_option_id ON poll_votes (option_id);
