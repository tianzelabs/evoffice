"""Orders -- a Kraken Futures account's order types, filled the way Kraken fills them (2026-10-11).

The boss: "follow real Kraken exactly, no differences." So, against the captured order book
(agent-world futures_book: 10 levels a side, once a second) and the trade tape:

- limit: good-till-cancelled unless ttl_minutes is given. If it crosses on arrival it executes
  at once as TAKER against the book, up to its limit price, and any rest stays resting
  (post_only instead REJECTS an order that would cross, as Kraken does). A resting order joins
  the QUEUE at its price behind the size already displayed there; it fills as MAKER, partially
  or fully, as trades print at its price beyond that queue -- or completely when the market
  trades THROUGH its price. A price deeper than the captured levels has an unknown queue and
  fills only on a trade-through. Cancellations ahead of us are not seen, so the queue is if
  anything longer than real: fills are never invented.
- ioc: immediate-or-cancel -- what crosses now executes, the rest is cancelled.
- stop / take_profit: trigger orders, held 'untriggered' until the trigger signal (mark by
  default, or last or index) reaches or passes trigger_price: a stop sells at or below / buys at
  or above it, a take-profit the other way round. Then they execute as a market order, or as a
  limit order at `price` if one is given (the worst fill accepted).
- reduce_only (always on for intent 'close'): may only shrink the position, never flip it.
- oco: orders sharing an oco tag cancel each other when one fills or triggers -- Kraken's
  take-profit/stop-loss bracket.
- size in steps of 0.0001 BTC, price in ticks of 1 USD (Kraken's PF_XBTUSD precision).
"""
from __future__ import annotations

import time

from . import positions, progress
from .market import PRODUCT, Stale, walk
from .store import Store, now

TICK = 1.0
MAX_OPEN_ORDERS = 100
TYPES = ("limit", "ioc", "stop", "take_profit")
SIGNALS = ("mark", "last", "index")
JOIN = ("best", "bid", "ask")      # price resolved from the book at the moment of placing
EPS = 1e-9


class OrderRefused(Exception):
    pass


def _emit(store: Store, o: dict, what: str, extra: dict | None = None):
    store.emit(o["employee_id"], "order", {"order": o["id"], "status": what, "type": o.get("order_type"),
                                           "intent": o["intent"], "side": o["side"], "size": o["size"],
                                           "price": o["price"], "trigger": o.get("trigger_price"),
                                           "post_only": bool(o["post_only"]), "position": o.get("position_id"),
                                           **(extra or {})})


def get(store: Store, order_id: int) -> dict:
    rows = store.q("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        raise OrderRefused(f"no order {order_id}")
    return rows[0]


def _on_tick(x: float) -> bool:
    return abs(x / TICK - round(x / TICK)) < 1e-9 and x > 0


def place(store: Store, market, who: dict, intent: str, size: float | None, price: float | str | None,
          side: str | None = None, position_id: int | None = None, post_only: bool = True,
          ttl_min: int | None = None, strategy_version: str | None = None, order_type: str = "limit",
          trigger_price: float | None = None, trigger_signal: str = "mark", reduce_only: bool = False,
          oco: str | None = None) -> dict:
    if who["role"] != "trader":
        raise OrderRefused("only traders place orders")
    if order_type not in TYPES:
        raise OrderRefused(f"order_type must be one of {TYPES}")
    trigger = order_type in ("stop", "take_profit")
    if trigger:
        if trigger_signal not in SIGNALS:
            raise OrderRefused(f"trigger_signal must be one of {SIGNALS}")
        if trigger_price is None or not _on_tick(float(trigger_price)):
            raise OrderRefused(f"a {order_type} order needs trigger_price on the {TICK} USD tick")
        post_only = False                       # a triggered order executes; it is not a maker-only order
    join = price if isinstance(price, str) else None
    if join is not None and join not in JOIN:
        raise OrderRefused(f"price must be a number or one of {JOIN}")
    if price is None and not trigger:
        raise OrderRefused("a limit or ioc order needs a price (a number, or 'best')")
    if join is None and price is not None and not _on_tick(float(price)):
        raise OrderRefused(f"price must be a positive multiple of the tick ({TICK} USD)")
    if ttl_min is not None and not 1 <= int(ttl_min) <= 525_600:
        raise OrderRefused("ttl_minutes, if given, must be 1..525600 (orders are good-till-cancelled otherwise)")
    mine = store.q("SELECT COUNT(*) AS n FROM orders WHERE employee_id = ? AND status IN ('open', 'untriggered')",
                   (who["id"],))[0]["n"]
    if mine >= MAX_OPEN_ORDERS:
        raise OrderRefused(f"you already have {mine} open orders (max {MAX_OPEN_ORDERS})")
    try:
        book = market.book(PRODUCT)
    except Stale as e:
        raise OrderRefused(f"no fresh book, not placing: {e}") from e
    best_bid, best_ask = book.bids[0][0], book.asks[0][0]

    if intent == "open":
        if side not in ("long", "short"):
            raise OrderRefused("an opening order needs side 'long' or 'short'")
        book_side, pos_side, size = ("buy" if side == "long" else "sell"), side, float(size or 0)
    elif intent == "close":
        rows = store.q("SELECT * FROM positions WHERE id = ?", (position_id,))
        if not rows or rows[0]["employee_id"] != who["id"] or rows[0]["closed_ts"]:
            raise OrderRefused(f"position {position_id} is not one of your open positions")
        p = rows[0]
        book_side, pos_side = ("sell" if p["side"] == "long" else "buy"), p["side"]
        size = float(size) if size else p["size"]
        reduce_only = True
    else:
        raise OrderRefused("intent must be 'open' or 'close'")
    if size <= 0 or abs(size / positions.SIZE_STEP - round(size / positions.SIZE_STEP)) > 1e-6:
        raise OrderRefused(f"size must be a positive multiple of {positions.SIZE_STEP} BTC")
    if join is not None:
        price = {"bid": best_bid, "ask": best_ask, "best": best_bid if book_side == "buy" else best_ask}[join]
    ref = float(price) if price is not None else (best_ask if book_side == "buy" else best_bid)
    if intent == "open" and not reduce_only:
        pending = store.q("SELECT COALESCE(SUM(size - filled), 0) AS s FROM orders WHERE employee_id = ? "
                          "AND status IN ('open', 'untriggered') AND intent = 'open' AND reduce_only = 0 AND side = ?",
                          (who["id"], book_side))[0]["s"]
        try:
            positions.check_open(store, who["id"], PRODUCT, side, size, pending, price=ref)
        except positions.Refused as e:
            raise OrderRefused(str(e)) from e

    t = time.time()
    oid = store.x("INSERT INTO orders (employee_id, intent, position_id, pair, side, position_side, size, filled, price, "
                  "order_type, trigger_price, trigger_signal, reduce_only, post_only, oco, status, placed_ts, "
                  "placed_epoch, expires_epoch, checked_epoch, strategy_version) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (who["id"], intent, position_id, PRODUCT, book_side, pos_side, size, price, order_type,
                   trigger_price, trigger_signal if trigger else None, int(bool(reduce_only)), int(bool(post_only)),
                   oco, "untriggered" if trigger else "open", now(), t,
                   t + int(ttl_min) * 60 if ttl_min is not None else None, t, strategy_version))
    o = get(store, oid)
    if trigger:
        _emit(store, o, "placed", {"bid": best_bid, "ask": best_ask, "signal": trigger_signal})
        return o
    return _arrive(store, market, o, book)


def _arrive(store: Store, market, o: dict, book) -> dict:
    """A limit/ioc order reaching the book: execute what crosses, then rest (limit) or cancel (ioc)."""
    crosses = o["price"] >= book.asks[0][0] if o["side"] == "buy" else o["price"] <= book.bids[0][0]
    if crosses and o["post_only"]:
        store.x("UPDATE orders SET status = 'rejected', done_ts = ?, note = ? WHERE id = ?",
                (now(), f"post-only would have taken liquidity (bid {book.bids[0][0]}, ask {book.asks[0][0]})", o["id"]))
        _emit(store, o, "rejected", {"why": f"post-only: {o['side']} at {o['price']} would cross "
                                            f"(bid {book.bids[0][0]} / ask {book.asks[0][0]})"})
        return get(store, o["id"])
    if crosses:
        want = _executable(store, o)
        qty, vwap = walk(book.side(o["side"]), want, o["price"], o["side"])
        if qty > EPS:
            _execute(store, o, qty, vwap, "taker")
            o = get(store, o["id"])
    if o["status"] != "open":
        return o
    if o["order_type"] == "ioc":
        store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = 'ioc: rest cancelled' WHERE id = ?",
                (now(), o["id"]))
        _emit(store, o, "cancelled", {"why": "ioc remainder"})
        return get(store, o["id"])
    queue = book.queue_at(o["side"], o["price"])
    store.x("UPDATE orders SET queue_ahead = ?, queue_seen = 0, checked_epoch = ? WHERE id = ?",
            (queue, book.ts, o["id"]))
    _emit(store, o, "placed", {"bid": book.bids[0][0], "ask": book.asks[0][0], "queue_ahead": queue,
                               "filled": o["filled"]})
    return get(store, o["id"])


def _executable(store: Store, o: dict) -> float:
    """How much of the order may execute now; reduce-only orders never exceed the position."""
    left = o["size"] - o["filled"]
    if not o["reduce_only"]:
        return left
    net = positions.net_size(store, o["employee_id"])
    reducing = -net if o["side"] == "buy" else net          # a buy reduces a short, a sell a long
    return max(0.0, min(left, reducing))


def _execute(store: Store, o: dict, qty: float, price: float, liquidity: str, reason: str = "self"):
    """Apply qty of the order at price to the net position; complete it when nothing is left."""
    with store.lock:
        o = get(store, o["id"])
        if o["status"] not in ("open", "untriggered"):
            return
        qty = min(qty, _executable(store, o))
        if qty <= EPS:
            store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = 'reduce-only: no position left to reduce' "
                    "WHERE id = ?", (now(), o["id"]))
            _emit(store, o, "cancelled", {"why": "reduce-only with no position to reduce"})
            return
        emp = store.employee(o["employee_id"])
        positions.fill(store, emp, PRODUCT, "long" if o["side"] == "buy" else "short", round(qty, 8), price, liquidity,
                       o["strategy_version"], None, f"{o['order_type']} #{o['id']}", reason)
        done = o["filled"] + qty
        avg = ((o["fill_price"] or 0) * o["filled"] + price * qty) / done
        status = "filled" if done >= o["size"] - EPS else o["status"]
        store.x("UPDATE orders SET filled = ?, fill_price = ?, liquidity = ?, status = ?, done_ts = ? WHERE id = ?",
                (done, avg, liquidity, status, now() if status == "filled" else None, o["id"]))
        _emit(store, o, "filled" if status == "filled" else "partial",
              {"fill_price": round(price, 2), "qty": round(qty, 8), "filled": round(done, 8), "liquidity": liquidity})
        if o["oco"]:
            _cancel_oco(store, o)
    progress.announce(store, o["employee_id"])


def _cancel_oco(store: Store, o: dict):
    for other in store.q("SELECT * FROM orders WHERE oco = ? AND employee_id = ? AND id != ? AND status IN "
                         "('open', 'untriggered')", (o["oco"], o["employee_id"], o["id"])):
        store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = ? WHERE id = ?",
                (now(), f"oco: #{o['id']} executed", other["id"]))
        _emit(store, other, "cancelled", {"why": f"oco with #{o['id']}"})


def cancel(store: Store, who: dict, order_id: int) -> dict:
    with store.lock:
        o = get(store, order_id)
        if o["employee_id"] != who["id"]:
            raise OrderRefused("you can only cancel your own orders")
        if o["status"] not in ("open", "untriggered"):
            raise OrderRefused(f"order {order_id} is {o['status']}")
        store.x("UPDATE orders SET status = 'cancelled', done_ts = ? WHERE id = ?", (now(), order_id))
    _emit(store, o, "cancelled")
    return get(store, order_id)


def _triggered(o: dict, values: list[float]) -> bool:
    up = (o["order_type"] == "stop") == (o["side"] == "buy")     # stop-buy and take-profit-sell fire on a rise
    return any((v >= o["trigger_price"]) if up else (v <= o["trigger_price"]) for v in values)


def match(store: Store, market) -> list[int]:
    """One pass over every live order: fire triggers, fill resting orders from the tape, expire."""
    done = []
    t = time.time()
    live = store.q("SELECT * FROM orders WHERE status IN ('open', 'untriggered') ORDER BY id")
    if not live:
        return done
    since = min(o["checked_epoch"] for o in live)
    try:
        tape = market.trades_since(PRODUCT, since)
        signals = market.signals_since(PRODUCT, since)
    except Stale:
        return done
    for o in live:
        o = get(store, o["id"])
        if o["status"] not in ("open", "untriggered"):
            continue
        mine = [x for x in tape if x[0] > o["checked_epoch"]]
        if o["status"] == "untriggered":
            if o["trigger_signal"] == "last":
                values = [x[1] for x in mine]
            else:
                col = 1 if o["trigger_signal"] == "mark" else 2
                values = [s[col] for s in signals if s[0] > o["checked_epoch"]]
            if values and _triggered(o, values):
                _fire(store, market, o)
                done.append(o["id"])
                continue
            last = max([x[0] for x in mine] + [s[0] for s in signals if s[0] > o["checked_epoch"]] + [o["checked_epoch"]])
        else:
            px = o["price"]
            through = [x for x in mine if (x[1] < px if o["side"] == "buy" else x[1] > px)]
            if through:
                _execute(store, o, _executable(store, o), px, "maker")
                done.append(o["id"])
                continue
            if o["queue_ahead"] is not None:
                taker = "sell" if o["side"] == "buy" else "buy"     # who trades INTO a resting buy is a seller
                at_px = sum(x[2] for x in mine if abs(x[1] - px) < 1e-9 and x[3] in (taker, ""))
                if at_px > 0:
                    seen = o["queue_seen"] + at_px
                    store.x("UPDATE orders SET queue_seen = ? WHERE id = ?", (seen, o["id"]))
                    avail = seen - o["queue_ahead"] - o["filled"]
                    if avail > EPS:
                        _execute(store, o, min(avail, _executable(store, o)), px, "maker")
                        done.append(o["id"])
            last = max([x[0] for x in mine] or [o["checked_epoch"]])
        o = get(store, o["id"])
        if o["status"] in ("open", "untriggered") and o["expires_epoch"] is not None and t >= o["expires_epoch"]:
            store.x("UPDATE orders SET status = 'expired', done_ts = ? WHERE id = ?", (now(), o["id"]))
            _emit(store, o, "expired", {"filled": o["filled"]})
            continue
        store.x("UPDATE orders SET checked_epoch = ? WHERE id = ? AND status IN ('open', 'untriggered')", (last, o["id"]))
    return done


def _fire(store: Store, market, o: dict):
    """A stop / take-profit has triggered: execute at market, or become a limit at its price."""
    _emit(store, o, "triggered")
    if o["oco"]:
        _cancel_oco(store, o)
    if o["price"] is None:
        want = _executable(store, o)
        if want <= EPS:
            _execute(store, o, 0, 0, "taker")                     # cancels with the reduce-only reason
            return
        try:
            px = positions.market_price(market, o["side"], want)
        except positions.Refused as e:
            store.x("UPDATE orders SET status = 'cancelled', done_ts = ?, note = ? WHERE id = ?",
                    (now(), f"triggered but not filled: {e}"[:300], o["id"]))
            _emit(store, o, "cancelled", {"why": str(e)[:300]})
            return
        _execute(store, o, want, px, "taker")
        return
    store.x("UPDATE orders SET status = 'open', order_type = 'limit', post_only = 0 WHERE id = ?", (o["id"],))
    try:
        book = market.book(PRODUCT)
    except Stale:
        return                                                    # rests as a limit; filled from the tape later
    _arrive(store, market, get(store, o["id"]), book)


def listing(store: Store, employee_id: str | None = None, open_only: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM orders WHERE 1=1", []
    if employee_id:
        sql += " AND employee_id = ?"; args.append(employee_id)
    if open_only:
        sql += " AND status IN ('open', 'untriggered')"
    return store.q(sql + " ORDER BY id DESC LIMIT 200", tuple(args))
