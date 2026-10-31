CREATE TABLE IF NOT EXISTS conferences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL CHECK (category IN ('ai', 'tech', 'finance')),
    start_date  TEXT    NOT NULL,
    end_date    TEXT    NOT NULL,
    city        TEXT,
    state       TEXT,
    county      TEXT,
    is_virtual  INTEGER NOT NULL DEFAULT 0,
    venue       TEXT,
    url         TEXT,
    description TEXT,
    source      TEXT    NOT NULL DEFAULT 'gemini',
    dedupe_key  TEXT    NOT NULL UNIQUE,
    first_seen  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL,
    hidden      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_conferences_end_date ON conferences (end_date);
