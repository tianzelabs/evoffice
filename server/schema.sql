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
    close_reason     TEXT CHECK (close_reason IN ('self', 'max_hold', 'fired', 'liquidation')),
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

-- Orders, Kraken Futures order types (2026-10-11; see server/orders.py). The v1 table (limit only,
-- trade-through fills) is kept as orders_v1 by the migration in store.py.
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY,
    employee_id      TEXT NOT NULL REFERENCES employees(id),
    intent           TEXT NOT NULL CHECK (intent IN ('open', 'close')),
    position_id      INTEGER,              -- for intent = 'close'
    pair             TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    position_side    TEXT CHECK (position_side IN ('long', 'short')),
    size             REAL NOT NULL CHECK (size > 0),
    filled           REAL NOT NULL DEFAULT 0,
    price            REAL,                 -- limit price; NULL for a stop/take-profit that executes at market
    order_type       TEXT NOT NULL DEFAULT 'limit' CHECK (order_type IN ('limit', 'ioc', 'stop', 'take_profit')),
    trigger_price    REAL,
    trigger_signal   TEXT CHECK (trigger_signal IN ('mark', 'last', 'index')),
    reduce_only      INTEGER NOT NULL DEFAULT 0,
    post_only        INTEGER NOT NULL DEFAULT 1,
    oco              TEXT,
    queue_ahead      REAL,                 -- size displayed ahead of us at our price when we joined; NULL = unknown
    queue_seen       REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL CHECK (status IN ('open', 'untriggered', 'filled', 'cancelled', 'expired', 'rejected')),
    placed_ts        TEXT NOT NULL,
    placed_epoch     REAL NOT NULL,
    expires_epoch    REAL,                 -- NULL: good till cancelled
    checked_epoch    REAL NOT NULL,
    done_ts          TEXT,
    fill_price       REAL,                 -- average over partial fills
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
