"""The office's clock: the daily stand-up and market alerts, emitted as events.

Stand-up: every day at MEETING_UTC the office calls everyone to the meeting
table (`meeting` start); MEETING_MINUTES later it ends. Agents are woken by it:
traders report what they changed and the evidence, the manager opens with the
market and closes with a summary for the boss.

Market alert: a sudden move wakes everyone. Calibrated on 7 days of BTC bars
(2026-10-10): |5-minute move| >= 40 bps is the 99.5th percentile (~7 minutes a
day, clustered), a 1-minute range >= 30 bps about the 99.7th; a 45-minute
cooldown keeps it to a few alerts a day so it does not drain the traders' budgets.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from .market import Stale
from .store import Store

MEETING_UTC = os.environ.get("OFFICE_MEETING_UTC", "07:30")
# The boss's method (2026-10-10): trade normally, and every so often look BACK at the moves we missed and
# what the market looked like before them. Local office time (Europe/Budapest); the last one is the day's.
REVIEW_TZ = os.environ.get("OFFICE_TZ", "Europe/Budapest")
REVIEW_TIMES = os.environ.get("OFFICE_REVIEW_TIMES", "12:00,16:00,20:00,23:30")
MEETING_MINUTES = 20
ALERT_MOVE_5M_BPS = 40.0
ALERT_RANGE_1M_BPS = 30.0
ALERT_COOLDOWN = timedelta(minutes=45)


def _last(store: Store, kind: str) -> dict | None:
    rows = store.q("SELECT ts, payload FROM events WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,))
    if not rows:
        return None
    p = json.loads(rows[0]["payload"])
    # the scheduler's own clock ("at"), so decisions are consistent in tests and in production alike
    return {**p, "ts": datetime.fromisoformat(p.get("at") or rows[0]["ts"])}


def meeting_tick(store: Store, now: datetime) -> str | None:
    hh, mm = map(int, MEETING_UTC.split(":"))
    start_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    last = _last(store, "meeting")
    if last and last.get("phase") == "start" and now - last["ts"] >= timedelta(minutes=MEETING_MINUTES):
        store.emit("office", "meeting", {"phase": "end", "at": now.isoformat()})
        return "end"
    started_today = last and last["ts"] >= start_at
    if start_at <= now < start_at + timedelta(minutes=10) and not started_today:
        store.emit("office", "meeting", {"phase": "start", "minutes": MEETING_MINUTES, "at": now.isoformat(),
                                         "agenda": "daily stand-up: the manager opens with the market and its models; "
                                                   "each trader reports what it changed since yesterday and the evidence; "
                                                   "the manager closes with a summary for the boss"})
        return "start"
    return None


def review_tick(store: Store, now: datetime) -> dict | None:
    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo(REVIEW_TZ))
    times = [t.strip() for t in REVIEW_TIMES.split(",") if t.strip()]
    last = _last(store, "review")
    for i, t in enumerate(times):
        hh, mm = map(int, t.split(":"))
        at = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not at <= local < at + timedelta(minutes=10):
            continue
        if last and last["ts"] >= at.astimezone(timezone.utc):
            return None
        since = last["ts"].isoformat() if last else (at - timedelta(hours=4)).astimezone(timezone.utc).isoformat()
        daily = i == len(times) - 1
        p = {"since": since, "until": now.isoformat(), "daily": daily, "at": now.isoformat(),
             "agenda": ("END-OF-DAY review of the whole day" if daily else "lookback review since the last one")
                       + ": find the moves we missed (and the trades that went wrong), describe the market state "
                         "BEFORE each with market_context, compare it with ordinary times, add them to the "
                         "opportunity journal in the shared REPL, and turn what recurs into hypotheses to test"}
        store.emit("office", "review", p)
        return p
    return None


def alert_tick(store: Store, market, now: datetime) -> dict | None:
    last = _last(store, "alert")
    if last and now - last["ts"] < ALERT_COOLDOWN:
        return None
    try:
        from .market import PRODUCT
        bars = market.bars(PRODUCT, 8)
    except (Stale, ValueError):
        return None
    if len(bars) < 6:
        return None
    c = [b["c"] for b in bars]
    move = (c[-1] / c[-6] - 1) * 1e4
    rng = (bars[-1]["h"] - bars[-1]["l"]) / bars[-1]["c"] * 1e4
    if abs(move) < ALERT_MOVE_5M_BPS and rng < ALERT_RANGE_1M_BPS:
        return None
    payload = {"at": now.isoformat(), "move_5m_bps": round(move, 1), "range_1m_bps": round(rng, 1), "price": c[-1],
               "text": f"BTC {'+' if move >= 0 else ''}{move:.0f} bps in 5 min (1-min range {rng:.0f} bps)"}
    store.emit("office", "alert", payload)
    return payload


def tick(store: Store, market, now: datetime | None = None) -> None:
    from . import funding, seasons
    now = now or datetime.now(timezone.utc)
    meeting_tick(store, now)
    review_tick(store, now)
    seasons.tick(store, now)
    if now.minute < 10:                   # funding settles on the hour; apply it once, early in the hour
        funding.apply(store, market, now)
    alert_tick(store, market, now)
