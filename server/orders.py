"""Limit orders -- the maker side of a Kraken Futures account, simulated honestly.

A resting order pays the MAKER fee (tier 1: 0.02% vs 0.05% taker), so a
maker/maker round trip costs 4 bps instead of 10. The price of that discount is
that a fill is not guaranteed, and the simulation must not pretend otherwise:

- post_only (the default): if the order would execute on arrival -- a buy at or
  above the ask, a sell at or below the bid -- it is REJECTED, as Kraken does.
- a non-post-only limit that crosses executes at once as a TAKER at the best
  price (ask/bid), never worse than its limit.
- a resting order fills only when the market trades THROUGH its price -- a
  trade strictly below a buy, strictly above a sell -- and then at its own price.
  A trade AT the price is not enough: real queues have others ahead of you.
  This undercounts fills rather than inventing them.
- price must be a multiple of the tick (1 USD for PF_XBTUSD), as on Kraken.

kraken-cli's own paper engine charges the taker rate on every fill, cancels a
resting post-only order when the price reaches it, and checks fills only when a
command runs -- three reasons this office simulates fills itself.
"""
from __future__ import annotations

import time

from . import positions, progress
from .market import PRODUCT, Stale
from .store import Store, now

TICK = 1.0
MAX_OPEN_ORDERS = 4
DEFAULT_TTL_MIN, MAX_TTL_MIN = 60, 24 * 60


class OrderRefused(Exception):
    pass


def _emit(store: Store, o: dict, what: str, extra: dict | None = None):
    store.emit(o["employee_id"], "order", {"order": o["id"], "status": what, "intent": o["intent"], "side": o["side"],
                                           "size": o["size"], "price": o["price"], "post_only": bool(o["post_only"]),
                                           "position": o.get("position_id"), **(extra or {})})


def get(store: Store, order_id: int) -> dict:
    rows = store.q("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        raise OrderRefused(f"no order {order_id}")
    return rows[0]


def place(store: Store, market, who: dict, intent: str, size: float | None, price: float, side: str | None = None,
          position_id: int | None = None, post_only: bool = True, ttl_min: int | None = None,
          strategy_version: str | None = None) -> dict:
    if who["role"] != "trader":
        raise OrderRefused("only traders place orders")
    if abs(price / TICK - round(price / TICK)) > 1e-9 or price <= 0:
        raise OrderRefused(f"price must be a positive multiple of the tick ({TICK} USD)")
    ttl = int(ttl_min or DEFAULT_TTL_MIN)
    if not 1 <= ttl <= MAX_TTL_MIN:
        raise OrderRefused(f"ttl_minutes must be 1..{MAX_TTL_MIN}")
    mine = store.q("SELECT COUNT(*) AS n FROM orders WHERE employee_id = ? AND status = 'open'", (who["id"],))[0]["n"]
    if mine >= MAX_OPEN_ORDERS:
        raise OrderRefused(f"you already have {mine} open orders (max {MAX_OPEN_ORDERS}); cancel one first")
    if intent == "open":
        if side not in ("long", "short"):
            raise OrderRefused("an opening order needs side 'long' or 'short'")
        try:
            positions.check_open(store, who["id"], PRODUCT, side, float(size or 0))
        except positions.Refused as e:
            raise OrderRefused(str(e)) from e
        book_side, pos_side, size = ("buy" if side == "long" else "sell"), side, float(size)
    elif intent == "close":
        rows = store.q("SELECT * FROM positions WHERE id = ?", (position_id,))
        if not rows or rows[0]["employee_id"] != who["id"] or rows[0]["closed_ts"]:
            raise OrderRefused(f"position {position_id} is not one of your open positions")
        if store.q("SELECT 1 FROM orders WHERE position_id = ? AND status = 'open'", (position_id,)):
            raise OrderRefused(f"position {position_id} already has an open closing order; cancel it first")
        p = rows[0]
        book_side, pos_side, size = ("sell" if p["side"] == "long" else "buy"), p["side"], p["size"]
    else:
        raise OrderRefused("intent must be 'open' or 'close'")
    try:
        q = market.quote(PRODUCT)
    except Stale as e:
        raise OrderRefused(f"no fresh book, not placing: {e}") from e
    crosses = price >= q.ask if book_side == "buy" else price <= q.bid
    t = time.time()
    oid = store.x("INSERT INTO orders (employee_id, intent, position_id, pair, side, position_side, size, price, "
                  "post_only, status, placed_ts, placed_epoch, expires_epoch, checked_epoch, strategy_version) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)",
                  (who["id"], intent, position_id, PRODUCT, book_side, pos_side, size, price, int(post_only), now(),
                   t, t + ttl * 60, t, strategy_version))
    o = get(store, oid)
    if crosses and post_only:
        store.x("UPDATE orders SET status = 'rejected', done_ts = ?, note = ? WHERE id = ?",
                (now(), f"post-only would have taken liquidity (bid {q.bid}, ask {q.ask})", oid))
        _emit(store, o, "rejected", {"why": f"post-only: {book_side} at {price} would cross (bid {q.bid} / ask {q.ask})"})
        return get(store, oid)
    if crosses:                                            # an ordinary limit that crosses: taker, at the best price
        fill_px = q.ask if book_side == "buy" else q.bid
        _fill(store, o, fill_px, "taker")
        return get(store, oid)
    _emit(store, o, "placed", {"bid": q.bid, "ask": q.ask, "ttl_minutes": ttl})
    return o


def cancel(store: Store, who: dict, order_id: int) -> dict:
    with store.lock:
        o = get(store, order_id)
        if o["employee_id"] != who["id"]:
            raise OrderRefused("you can only cancel your own orders")
        if o["status"] != "open":
            raise OrderRefused(f"order {order_id} is {o['status']}")
        store.x("UPDATE orders SET status = 'cancelled', done_ts = ? WHERE id = ?", (now(), order_id))
    _emit(store, o, "cancelled")
    return get(store, order_id)


def _fill(store: Store, o: dict, price: float, liquidity: str):
    with store.lock:
        cur = get(store, o["id"])
        if cur["status"] != "open":
            return
        if o["intent"] == "open":
            emp = store.employee(o["employee_id"])
            store.x("UPDATE orders SET status = 'filled', done_ts = ?, fill_price = ?, liquidity = ? WHERE id = ?",
                    (now(), price, liquidity, o["id"]))
            _emit(store, o, "filled", {"fill_price": price, "liquidity": liquidity})
            positions.fill_open(store, emp, PRODUCT, o["position_side"], o["size"], price, liquidity,
                                o["strategy_version"], None, f"limit #{o['id']}")
        else:
            rows = store.q("SELECT * FROM positions WHERE id = ?", (o["position_id"],))
            if not rows or rows[0]["closed_ts"]:
                store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = 'position already closed' "
                        "WHERE id = ?", (now(), o["id"]))
                return
            store.x("UPDATE orders SET status = 'filled', done_ts = ?, fill_price = ?, liquidity = ? WHERE id = ?",
                    (now(), price, liquidity, o["id"]))
            _emit(store, o, "filled", {"fill_price": price, "liquidity": liquidity})
            positions.fill_close(store, rows[0], price, liquidity, o["employee_id"], "self", f"limit #{o['id']}")
    progress.announce(store, o["employee_id"])


def match(store: Store, market) -> list[int]:
    """Fill resting orders the market has traded through since they were last checked; expire old ones."""
    filled = []
    t = time.time()
    for o in store.q("SELECT * FROM orders WHERE status = 'open' ORDER BY id"):
        tape = market.trades_since(PRODUCT, o["checked_epoch"])
        through = [px for ts, px in tape if (px < o["price"] if o["side"] == "buy" else px > o["price"])]
        if through:
            _fill(store, o, o["price"], "maker")
            filled.append(o["id"])
            continue
        if o["expires_epoch"] is not None and t >= o["expires_epoch"]:
            store.x("UPDATE orders SET status = 'expired', done_ts = ? WHERE id = ?", (now(), o["id"]))
            _emit(store, o, "expired")
            continue
        last = max([ts for ts, _ in tape] or [o["checked_epoch"]])
        store.x("UPDATE orders SET checked_epoch = ? WHERE id = ?", (last, o["id"]))
    return filled


def listing(store: Store, employee_id: str | None = None, open_only: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM orders WHERE 1=1", []
    if employee_id:
        sql += " AND employee_id = ?"; args.append(employee_id)
    if open_only:
        sql += " AND status = 'open'"
    return store.q(sql + " ORDER BY id DESC LIMIT 200", tuple(args))
