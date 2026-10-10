"""Positions -- the only things in the office that earn or lose.

Fills follow Kraken Futures for a new account (server/fees.py, server/market.py):
a market order buys at the best ask and sells at the best bid and pays the TAKER
fee; a limit order that rests and is later traded through pays the MAKER fee
(server/orders.py). Each leg's price, liquidity and fee are kept, and hourly
funding accumulates on the position (server/funding.py). A fill is refused when
the quote is stale -- the office never fills at an old print.

The trader closes its own positions; max_hold_s is a backstop the server enforces.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import fees, progress, settlement
from .market import PRODUCT, Stale
from .store import Store, now

DEFAULT_MAX_HOLD_S = 24 * 3600
MAX_SIZE_BTC = 0.05


class Refused(Exception):
    """The office will not do this. The message says why, for the agent to read."""


def check_open(store: Store, employee_id: str, pair: str, side: str, size: float) -> dict:
    emp = store.employee(employee_id)
    if not emp or emp["role"] != "trader" or emp["fired_ts"]:
        raise Refused("only an employed trader can open a position")
    if pair != PRODUCT:
        raise Refused(f"the office trades {PRODUCT} (Kraken BTC perpetual) only")
    if side not in ("long", "short"):
        raise Refused("side must be 'long' or 'short'")
    level = progress.compute(store, employee_id)
    cap = min(float(emp["params"].get("max_size", MAX_SIZE_BTC)), level["max_size"])
    if not 0 < size <= cap:
        raise Refused(f"size must be > 0 and <= {cap} BTC (level {level['level']} {level['title']} allows "
                      f"{level['max_size']}; earn XP by validated improvement to unlock more)")
    return emp


def fill_open(store: Store, emp: dict, pair: str, side: str, size: float, price: float, liquidity: str,
              strategy_version: str | None, max_hold_s: int | None, via: str) -> dict:
    hold = int(max_hold_s or emp["params"].get("max_hold_s", DEFAULT_MAX_HOLD_S))
    fee = settlement.leg_fee(size, price, liquidity)
    pid = store.x("INSERT INTO positions (employee_id, strategy_version, pair, side, size, opened_ts, entry_px, max_hold_s, "
                  "entry_liq, entry_fee, funding, regime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                  (emp["id"], strategy_version, pair, side, size, now(), price, hold, liquidity, fee, fees.REGIME))
    store.emit(emp["id"], "open", {"position": pid, "pair": pair, "side": side, "size": size, "entry_px": price,
                                   "liquidity": liquidity, "fee": round(fee, 6), "via": via,
                                   "strategy_version": strategy_version})
    return get(store, pid)


def open_position(store: Store, market, employee_id: str, pair: str, side: str, size: float,
                  strategy_version: str | None = None, max_hold_s: int | None = None) -> dict:
    """A market order: buys at the ask, sells at the bid, pays the taker fee."""
    emp = check_open(store, employee_id, pair, side, size)
    try:
        q = market.quote(pair)
    except Stale as e:
        raise Refused(f"no fresh price, not filling: {e}") from e
    price = q.ask if side == "long" else q.bid
    return fill_open(store, emp, pair, side, size, price, "taker", strategy_version, max_hold_s, "market")


def fill_close(store: Store, p: dict, price: float, liquidity: str, actor: str, reason: str, via: str) -> dict:
    """Close at `price`. Caller holds store.lock and has checked the position is open."""
    if p["regime"]:
        r = settlement.settle(p["side"], p["size"], p["entry_px"], price, p["entry_liq"] or "taker", liquidity,
                              p["funding"] or 0.0)
        exit_fee = settlement.leg_fee(p["size"], price, liquidity)
    else:                                   # a legacy spot-4bps row: priced the way it was opened
        gross = (1 if p["side"] == "long" else -1) * (price - p["entry_px"]) * p["size"]
        f = 0.0004 * p["size"] * (p["entry_px"] + price)
        r = settlement.Result(gross, f, 0.0, gross - f, (gross - f) / (p["size"] * p["entry_px"]) * 1e4)
        exit_fee = f / 2
    store.x("UPDATE positions SET closed_ts = ?, exit_px = ?, close_reason = ?, fees = ?, pnl = ?, exit_liq = ?, "
            "exit_fee = ? WHERE id = ?", (now(), price, reason, r.fees, r.pnl, liquidity, exit_fee, p["id"]))
    store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = 'position closed' "
            "WHERE position_id = ? AND status = 'open'", (now(), p["id"]))
    store.emit(actor, "close", {"position": p["id"], "employee": p["employee_id"], "reason": reason, "via": via,
                                "exit_px": price, "liquidity": liquidity, "gross": round(r.gross, 4),
                                "fees": round(r.fees, 4), "funding": round(r.funding, 6), "pnl": round(r.pnl, 4),
                                "pnl_bps": round(r.pnl_bps, 2)})
    return get(store, p["id"])


def close_position(store: Store, market, position_id: int, actor: str, reason: str = "self") -> dict:
    """A market close: a long sells at the bid, a short buys at the ask; taker fee."""
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
            q = market.quote(p["pair"] if p["pair"] == PRODUCT else PRODUCT)
        except Stale as e:
            raise Refused(f"no fresh price, not closing yet: {e}") from e
        price = q.bid if p["side"] == "long" else q.ask
        out = fill_close(store, p, price, "taker", actor, reason, "market")
    progress.announce(store, p["employee_id"])
    return out


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
