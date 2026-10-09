"""Opening and closing positions -- the only acts in the office that earn or lose.

A fill is the last trade on the feed, and only if it is fresh (market.Stale
otherwise): the office refuses to fill rather than fill at an old print. The
trader closes its own positions; max_hold_s is a backstop the server enforces.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import settlement
from .market import Stale
from .store import Store, now

DEFAULT_MAX_HOLD_S = 24 * 3600
MAX_SIZE_BTC = 0.05


class Refused(Exception):
    """The office will not do this. The message says why, for the agent to read."""


def open_position(store: Store, market, employee_id: str, pair: str, side: str, size: float,
                  strategy_version: str | None = None, max_hold_s: int | None = None) -> dict:
    emp = store.employee(employee_id)
    if not emp or emp["role"] != "trader" or emp["fired_ts"]:
        raise Refused("only an employed trader can open a position")
    if pair != "BTC/USD":
        raise Refused("v0 trades BTC/USD only")
    if side not in ("long", "short"):
        raise Refused("side must be 'long' or 'short'")
    cap = float(emp["params"].get("max_size", MAX_SIZE_BTC))
    if not 0 < size <= cap:
        raise Refused(f"size must be > 0 and <= {cap} BTC")
    hold = int(max_hold_s or emp["params"].get("max_hold_s", DEFAULT_MAX_HOLD_S))
    try:
        q = market.quote(pair)
    except Stale as e:
        raise Refused(f"no fresh price, not filling: {e}") from e
    ts = now()
    pid = store.x("INSERT INTO positions (employee_id, strategy_version, pair, side, size, opened_ts, entry_px, max_hold_s) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (employee_id, strategy_version, pair, side, size, ts, q.price, hold))
    store.emit(employee_id, "open", {"position": pid, "pair": pair, "side": side, "size": size,
                                     "entry_px": q.price, "strategy_version": strategy_version})
    return get(store, pid)


def close_position(store: Store, market, position_id: int, actor: str, reason: str = "self") -> dict:
    with store.lock:   # read-check-write as one step, so a position cannot close twice
        rows = store.q("SELECT * FROM positions WHERE id = ?", (position_id,))
        if not rows:
            raise Refused(f"no position {position_id}")
        p = rows[0]
        if reason == "self" and p["employee_id"] != actor:
            raise Refused("you can only close your own positions")
        if p["closed_ts"]:
            raise Refused(f"position {position_id} is already closed")
        try:
            q = market.quote(p["pair"])
        except Stale as e:
            raise Refused(f"no fresh price, not closing yet: {e}") from e
        r = settlement.settle(p["side"], p["size"], p["entry_px"], q.price)
        store.x("UPDATE positions SET closed_ts = ?, exit_px = ?, close_reason = ?, fees = ?, pnl = ? WHERE id = ?",
                (now(), q.price, reason, r.fees, r.pnl, position_id))
    store.emit(actor, "close", {"position": position_id, "employee": p["employee_id"], "reason": reason,
                                "exit_px": q.price, "gross": round(r.gross, 4), "fees": round(r.fees, 4),
                                "pnl": round(r.pnl, 4), "pnl_bps": round(r.pnl_bps, 2)})
    return get(store, position_id)


def enforce_max_hold(store: Store, market) -> list[int]:
    """Close every position past its backstop. A stale feed leaves it for the next pass."""
    closed = []
    t = datetime.now(timezone.utc)
    for p in store.q("SELECT id, opened_ts, max_hold_s FROM positions WHERE closed_ts IS NULL"):
        if (t - datetime.fromisoformat(p["opened_ts"])).total_seconds() >= p["max_hold_s"]:
            try:
                close_position(store, market, p["id"], actor="office", reason="max_hold")
                closed.append(p["id"])
            except Refused:
                pass
    return closed


def get(store: Store, position_id: int) -> dict:
    return store.q("SELECT * FROM positions WHERE id = ?", (position_id,))[0]


def listing(store: Store, employee_id: str | None = None, open_only: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM positions WHERE 1=1", []
    if employee_id:
        sql += " AND employee_id = ?"; args.append(employee_id)
    if open_only:
        sql += " AND closed_ts IS NULL"
    return store.q(sql + " ORDER BY id DESC LIMIT 500", tuple(args))
