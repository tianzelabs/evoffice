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
    params    TEXT NOT NULL DEFAULT '{}',
    name      TEXT                      -- chosen by the agent itself (POST /me/name)
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
    pnl              REAL,
    entry_liq        TEXT,                 -- 'maker' | 'taker' (NULL: legacy spot-4bps rows)
    exit_liq         TEXT,
    entry_fee        REAL,
    exit_fee         REAL,
    funding          REAL NOT NULL DEFAULT 0,   -- paid (<0) or received (>0) while open, hourly
    regime           TEXT                  -- fee/market rules the row was priced under (server/fees.py)
);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(closed_ts);
CREATE INDEX IF NOT EXISTS idx_positions_employee ON positions(employee_id);

-- Limit orders: resting in the (simulated) book until the market trades THROUGH their price.
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY,
    employee_id      TEXT NOT NULL REFERENCES employees(id),
    intent           TEXT NOT NULL CHECK (intent IN ('open', 'close')),
    position_id      INTEGER,              -- for intent = 'close'
    pair             TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    position_side    TEXT CHECK (position_side IN ('long', 'short')),
    size             REAL NOT NULL CHECK (size > 0),
    price            REAL NOT NULL,
    post_only        INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL CHECK (status IN ('open', 'filled', 'cancelled', 'expired', 'rejected')),
    placed_ts        TEXT NOT NULL,
    placed_epoch     REAL NOT NULL,
    expires_epoch    REAL,
    checked_epoch    REAL NOT NULL,
    done_ts          TEXT,
    fill_price       REAL,
    liquidity        TEXT,
    strategy_version TEXT,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_open ON orders(status);

-- Append-only. The SSE stream and the chat are reads of this table.
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
