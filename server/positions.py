"""Positions -- the only things in the office that earn or lose.

Fills follow Kraken Futures for a new account (server/fees.py, server/market.py):
a market order buys at the best ask and sells at the best bid and pays the TAKER
fee; a limit order that rests and is later traded through pays the MAKER fee
(server/orders.py). Each leg's price, liquidity and fee are kept, and hourly
funding accumulates on the position (server/funding.py). A fill is refused when
the quote is stale -- the office never fills at an old print.

The trader closes its own positions; max_hold_s is a backstop the server enforces.

ONE NET POSITION per trader, as on Kraken Futures (2026-10-10): a fill in the
direction you already hold adds to the position at a size-weighted average entry;
a fill against it reduces it -- oldest first, a partial reduction splitting off a
closed row for the part that closed -- and whatever is left over flips you to the
other side. Found before this rule: the office let one trader hold a long and a
short at once, paying fees on both legs for no exposure, and the size cap applied
per order rather than to the position. The cap now applies to the net position,
counting resting orders that would add to it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import account, fees, progress, settlement
from .market import PRODUCT, Stale
from .store import Store, now

DEFAULT_MAX_HOLD_S = 365 * 24 * 3600     # no forced exit by default (the boss, 2026-10-11); a manager may set one
MAX_SIZE_BTC = 1200.0                    # Kraken's maxPositionSize for PF_XBTUSD; margin binds long before


class Refused(Exception):
    """The office will not do this. The message says why, for the agent to read."""


EPS = 1e-9


def _sign(side: str) -> int:
    return 1 if side == "long" else -1


def net_size(store: Store, employee_id: str) -> float:
    """Signed BTC: + long, - short."""
    return sum(_sign(p["side"]) * p["size"] for p in store.q(
        "SELECT side, size FROM positions WHERE employee_id = ? AND closed_ts IS NULL", (employee_id,)))


def check_open(store: Store, employee_id: str, pair: str, side: str, size: float, pending: float = 0.0,
               price: float | None = None) -> dict:
    """`pending`: BTC already resting in open orders on the same side, which could fill too.
    Since 2026-10-11 size is bounded by the account's margin (server/account.py), not by level."""
    emp = store.employee(employee_id)
    if not emp or emp["role"] != "trader" or emp["fired_ts"]:
        raise Refused("only an employed trader can open a position")
    if pair != PRODUCT:
        raise Refused(f"the office trades {PRODUCT} (Kraken BTC perpetual) only")
    if side not in ("long", "short"):
        raise Refused("side must be 'long' or 'short'")
    if size <= 0:
        raise Refused("size must be > 0")
    net = net_size(store, employee_id)
    after = net + _sign(side) * (size + pending)
    if abs(after) <= abs(net) + EPS:
        return emp                                   # reducing is always allowed
    own = emp["params"].get("max_size")             # a limit the manager chose for itself, if any
    if own and abs(after) > float(own) + EPS:
        raise Refused(f"this would take the net position to {round(after, 6)} BTC; the manager's own limit is {own} BTC")
    if abs(after) > MAX_SIZE_BTC:
        raise Refused(f"Kraken's maximum position is {MAX_SIZE_BTC} BTC")
    if price:
        try:
            account.check(store, after, price)
        except ValueError as e:
            raise Refused(str(e) + (f" (now {round(net, 6)} BTC, plus {pending} BTC resting on that side)" if pending else ""))
    return emp


def fill(store: Store, emp: dict, pair: str, side: str, size: float, price: float, liquidity: str,
         strategy_version: str | None, max_hold_s: int | None, via: str) -> dict:
    """Apply a fill to the trader's net position. Returns the open position afterwards (or, if the
    fill left the trader flat, the last row it closed), with `netting` saying what happened."""
    with store.lock:
        left, closed = size, []
        for p in store.q("SELECT * FROM positions WHERE employee_id = ? AND closed_ts IS NULL AND side != ? "
                         "ORDER BY id", (emp["id"], side)):
            if left <= EPS:
                break
            q = min(left, p["size"])
            if q < p["size"] - EPS:
                p = _split(store, p, q)
            closed.append(fill_close(store, p, price, liquidity, emp["id"], "self", f"netted by {via}"))
            left -= q
        out = None
        if left > EPS:
            same = store.q("SELECT * FROM positions WHERE employee_id = ? AND closed_ts IS NULL AND side = ? "
                           "ORDER BY id LIMIT 1", (emp["id"], side))
            if same:
                out = _add(store, same[0], left, price, liquidity, via, strategy_version)
            else:
                out = _open(store, emp, pair, side, left, price, liquidity, strategy_version, max_hold_s, via)
        res = dict(out or (closed[-1] if closed else {}))
        res["netting"] = {"filled": size, "price": price, "liquidity": liquidity,
                          "closed_positions": [c["id"] for c in closed], "added_or_opened": round(left, 9) if left > EPS else 0,
                          "net_after": round(net_size(store, emp["id"]), 9)}
        return res


def _split(store: Store, p: dict, q: float) -> dict:
    """Split q BTC off an open position into its own row (to be closed); the rest stays open."""
    frac = q / p["size"]
    pid = store.x("INSERT INTO positions (employee_id, strategy_version, pair, side, size, opened_ts, entry_px, max_hold_s, "
                  "entry_liq, entry_fee, funding, regime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (p["employee_id"], p["strategy_version"], p["pair"], p["side"], q, p["opened_ts"], p["entry_px"],
                   p["max_hold_s"], p["entry_liq"], (p["entry_fee"] or 0) * frac, (p["funding"] or 0) * frac, p["regime"]))
    store.x("UPDATE positions SET size = ?, entry_fee = ?, funding = ? WHERE id = ?",
            (p["size"] - q, (p["entry_fee"] or 0) * (1 - frac), (p["funding"] or 0) * (1 - frac), p["id"]))
    return get(store, pid)


def _add(store: Store, p: dict, q: float, price: float, liquidity: str, via: str, strategy_version) -> dict:
    size = p["size"] + q
    entry = (p["size"] * p["entry_px"] + q * price) / size
    fee = settlement.leg_fee(q, price, liquidity)
    liq = p["entry_liq"] if p["entry_liq"] == liquidity else "mixed"
    store.x("UPDATE positions SET size = ?, entry_px = ?, entry_fee = ?, entry_liq = ? WHERE id = ?",
            (size, entry, (p["entry_fee"] or 0) + fee, liq, p["id"]))
    store.emit(p["employee_id"], "open", {"position": p["id"], "pair": p["pair"], "side": p["side"], "size": q,
                                          "entry_px": price, "liquidity": liquidity, "fee": round(fee, 6), "via": via,
                                          "added_to": True, "size_after": round(size, 9), "avg_entry": round(entry, 2),
                                          "strategy_version": strategy_version})
    return get(store, p["id"])


def fill_open(store: Store, emp: dict, pair: str, side: str, size: float, price: float, liquidity: str,
              strategy_version: str | None, max_hold_s: int | None, via: str) -> dict:
    return fill(store, emp, pair, side, size, price, liquidity, strategy_version, max_hold_s, via)


def _open(store: Store, emp: dict, pair: str, side: str, size: float, price: float, liquidity: str,
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
    try:
        q = market.quote(pair if pair == PRODUCT else PRODUCT)
    except Stale as e:
        raise Refused(f"no fresh price, not filling: {e}") from e
    emp = check_open(store, employee_id, pair, side, size, price=q.ask if side == "long" else q.bid)
    price = q.ask if side == "long" else q.bid
    out = fill(store, emp, pair, side, size, price, "taker", strategy_version, max_hold_s, "market")
    if out["netting"]["closed_positions"]:
        progress.announce(store, employee_id)
    return out


def fill_close(store: Store, p: dict, price: float, liquidity: str, actor: str, reason: str, via: str) -> dict:
    """Close at `price`. Caller holds store.lock and has checked the position is open."""
    if p["regime"]:
        # from the fees actually paid: a position built from several fills has a mixed entry
        exit_fee = settlement.leg_fee(p["size"], price, liquidity)
        gross = _sign(p["side"]) * (price - p["entry_px"]) * p["size"]
        f = (p["entry_fee"] or 0.0) + exit_fee
        pnl = gross - f + (p["funding"] or 0.0)
        r = settlement.Result(gross, f, p["funding"] or 0.0, pnl, pnl / (p["size"] * p["entry_px"]) * 1e4)
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
