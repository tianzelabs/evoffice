-- The office's whole schema. Three tables: who works here, what they traded,
-- and everything that happened. Chat, the leaderboard and the animation are all
-- derived from these; nothing else stores them.

PRAGMA foreign_keys = ON;

-- A fired employee keeps its row and its record; a new hire is a new id.
CREATE TABLE IF NOT EXISTS employees (
    id        TEXT PRIMARY KEY,
    role      TEXT NOT NULL CHECK (role IN ('boss', 'manager', 'trader')),
    hired_ts  TEXT NOT NULL,
    fired_ts  TEXT,
    params    TEXT NOT NULL DEFAULT '{}'
);

-- A position is opened and closed by the trader itself. max_hold_s is only a
-- backstop. pnl is NET of both fees -- a move in the right direction can still lose.
CREATE TABLE IF NOT EXISTS positions (
    id               INTEGER PRIMARY KEY,
    employee_id      TEXT NOT NULL REFERENCES employees(id),
    strategy_version TEXT,
    pair             TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('long', 'short')),
    size             REAL NOT NULL CHECK (size > 0),
    opened_ts        TEXT NOT NULL,
    entry_px         REAL NOT NULL,
    max_hold_s       INTEGER NOT NULL,
    closed_ts        TEXT,
    exit_px          REAL,
    close_reason     TEXT CHECK (close_reason IN ('self', 'max_hold', 'fired')),
    fees             REAL,
    pnl              REAL
);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(closed_ts);
CREATE INDEX IF NOT EXISTS idx_positions_employee ON positions(employee_id);

-- Append-only. The SSE stream and the chat are reads of this table.
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
