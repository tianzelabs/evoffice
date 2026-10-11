"""The office database: one SQLite file, one connection, one writer -- the server.

A single connection behind a lock is enough at this scale (a handful of agents
and one browser), and it makes "the server is the only writer" literally true.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA.read_text())
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        """Additive columns for databases created before them. Never drops or rewrites anything."""
        cols = {r["name"] for r in self.q("PRAGMA table_info(employees)")}
        if "name" not in cols:
            self.x("ALTER TABLE employees ADD COLUMN name TEXT")   # chosen by the agent itself
        pcols = {r["name"] for r in self.q("PRAGMA table_info(positions)")}
        for col, ddl in (("entry_liq", "TEXT"), ("exit_liq", "TEXT"), ("entry_fee", "REAL"), ("exit_fee", "REAL"),
                         ("funding", "REAL NOT NULL DEFAULT 0"), ("regime", "TEXT")):
            if col not in pcols:                       # Kraken futures fills (2026-10-10); old rows stay as they were
                self.x(f"ALTER TABLE positions ADD COLUMN {col} {ddl}")
        # 2026-10-11: the account can be LIQUIDATED, a close reason the original CHECK did not allow.
        # SQLite cannot alter a CHECK, so the table is rebuilt once -- every row copied, indexes recreated.
        sql = self.q("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'positions'")[0]["sql"]
        if "'liquidation'" not in sql:
            new = sql.replace("('self', 'max_hold', 'fired')", "('self', 'max_hold', 'fired', 'liquidation')")
            new = new.replace("CREATE TABLE IF NOT EXISTS positions", "CREATE TABLE positions_new", 1).replace(
                "CREATE TABLE positions (", "CREATE TABLE positions_new (", 1)
            assert "positions_new" in new and "'liquidation'" in new, "unexpected positions DDL"
            with self.lock:
                n = self.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
                self.conn.execute("BEGIN")
                self.conn.execute(new)
                self.conn.execute("INSERT INTO positions_new SELECT * FROM positions")
                assert self.conn.execute("SELECT COUNT(*) FROM positions_new").fetchone()[0] == n
                self.conn.execute("DROP TABLE positions")
                self.conn.execute("ALTER TABLE positions_new RENAME TO positions")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(closed_ts)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_employee ON positions(employee_id)")
                self.conn.execute("COMMIT")

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def emit(self, actor: str, kind: str, payload: dict) -> dict:
        """Append one event. Everything visible in the office is one of these."""
        ts = now()
        eid = self.x("INSERT INTO events (ts, actor, kind, payload) VALUES (?, ?, ?, ?)",
                     (ts, actor, kind, json.dumps(payload, ensure_ascii=False)))
        return {"id": eid, "ts": ts, "actor": actor, "kind": kind, "payload": payload}

    def events_since(self, since: int, limit: int = 500) -> list[dict]:
        rows = self.q("SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?", (since, limit))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def hire(self, employee_id: str, role: str, params: dict | None = None) -> None:
        """Idempotent: re-hiring an existing id is a no-op, so restarts are safe."""
        with self.lock:
            if self.q("SELECT 1 FROM employees WHERE id = ?", (employee_id,)):
                return
            self.x("INSERT INTO employees (id, role, hired_ts, params) VALUES (?, ?, ?, ?)",
                   (employee_id, role, now(), json.dumps(params or {})))
            self.emit("office", "hire", {"employee": employee_id, "role": role})

    def employee(self, employee_id: str) -> dict | None:
        rows = self.q("SELECT * FROM employees WHERE id = ?", (employee_id,))
        if not rows:
            return None
        rows[0]["params"] = json.loads(rows[0]["params"])
        return rows[0]
