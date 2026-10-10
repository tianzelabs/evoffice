"""Hourly funding on open perpetual positions, at the rate Kraken published.

PF_XBTUSD settles funding every hour. When the relative rate is positive,
longs pay shorts that fraction of their notional (at the mark price); when it
is negative, shorts pay longs. The office applies each hour once, to every
position open at that hour, using the rate from Kraken's historical funding
feed (agent-world/ingestion/futures_backfill.py), or the live ticker's rate if
the hour has not been published yet.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .market import PRODUCT, Stale
from .store import Store


def apply(store: Store, market, now: datetime) -> list[dict]:
    hour = now.replace(minute=0, second=0, microsecond=0)
    hour_s = int(hour.timestamp())
    done = store.q("SELECT 1 FROM events WHERE kind = 'funding' AND json_extract(payload, '$.hour') = ? LIMIT 1", (hour_s,))
    if done:
        return []
    try:
        q = market.quote(PRODUCT)
    except Stale:
        return []                         # try again next tick; never guess a mark
    rate = market.funding_history(PRODUCT, hour_s, hour_s + 1).get(hour_s, q.funding_per_hour)
    out = []
    for p in store.q("SELECT * FROM positions WHERE closed_ts IS NULL AND regime IS NOT NULL AND opened_ts < ?",
                     (hour.isoformat(),)):
        notional = p["size"] * (q.mark or q.price)
        amount = -rate * notional if p["side"] == "long" else rate * notional
        store.x("UPDATE positions SET funding = funding + ? WHERE id = ?", (amount, p["id"]))
        out.append(store.emit(p["employee_id"], "funding", {"hour": hour_s, "position": p["id"], "rate": rate,
                                                            "notional": round(notional, 2), "amount": round(amount, 6)}))
    if not out:                           # mark the hour as done even with nothing open
        store.emit("office", "funding", {"hour": hour_s, "rate": rate, "positions": 0})
    return out
