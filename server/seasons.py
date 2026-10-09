"""Weekly seasons and their awards -- the office's trophies.

A season is an ISO week (UTC). When it ends, the office hands out four awards,
each to one trader and only if someone actually earned it:

  iterator      most XP gained in the week (validated improvement -- the point of the office)
  best_heldout  the highest lower bound of a held-out 95% interval
  experimenter  the most held-out evaluations plus live trades
  top_pnl       the best net P&L of the week's closed trades (luck counts here, and only here)

Awards are events, so they are permanent, visible in the chat, and become trophies
on the winner's desk.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import progress
from .store import Store

AWARDS = {"iterator": "Iterator of the week", "best_heldout": "Best held-out result",
          "experimenter": "Most experiments", "top_pnl": "Top P&L of the week"}


def season_of(t: datetime) -> str:
    y, w, _ = t.isocalendar()
    return f"{y}-W{w:02d}"


def bounds(season: str) -> tuple[datetime, datetime]:
    y, w = season.split("-W")
    start = datetime.fromisocalendar(int(y), int(w), 1).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def standings(store: Store, season: str) -> list[dict]:
    a, b = (t.isoformat() for t in bounds(season))
    rows = []
    for e in store.q("SELECT id, name FROM employees WHERE role = 'trader'"):
        p = progress.compute(store, e["id"], a, b)
        evals = [json.loads(r["payload"]) for r in store.q(
            "SELECT payload FROM events WHERE kind = 'evaluation' AND actor = ? AND ts >= ? AND ts < ?", (e["id"], a, b))]
        lows = [x["ci95_net_bps_per_trade"][0] for x in evals if x.get("ci95_net_bps_per_trade")]
        tr = store.q("SELECT COUNT(*) AS n, COALESCE(SUM(pnl), 0) AS pnl FROM positions WHERE employee_id = ? "
                     "AND closed_ts >= ? AND closed_ts < ?", (e["id"], a, b))[0]
        rows.append({"employee": e["id"], "name": e["name"], "xp": p["xp"], "evaluations": len(evals),
                     "trades": tr["n"], "pnl": round(tr["pnl"], 4), "best_low": max(lows) if lows else None})
    return sorted(rows, key=lambda r: -r["xp"])


def award(store: Store, season: str) -> list[dict]:
    """Hand out a finished season's awards, once."""
    done = store.q("SELECT 1 FROM events WHERE kind = 'award' AND json_extract(payload, '$.season') = ?", (season,))
    if done:
        return []
    rows = standings(store, season)
    picks = {
        "iterator": max((r for r in rows if r["xp"] > 0), key=lambda r: r["xp"], default=None),
        "best_heldout": max((r for r in rows if r["best_low"] is not None), key=lambda r: r["best_low"], default=None),
        "experimenter": max((r for r in rows if r["evaluations"] + r["trades"] > 0),
                            key=lambda r: r["evaluations"] + r["trades"], default=None),
        "top_pnl": max((r for r in rows if r["trades"] > 0), key=lambda r: r["pnl"], default=None),
    }
    out = []
    for key, r in picks.items():
        if r:
            out.append(store.emit(r["employee"], "award", {"season": season, "award": key, "title": AWARDS[key],
                                                          "employee": r["employee"], "standing": r}))
    if not out:
        store.emit("office", "award", {"season": season, "award": None, "title": "no awards: nobody earned one"})
    return out


def tick(store: Store, now: datetime) -> None:
    """After a season ends (from Monday 00:05 UTC), award it."""
    if now.isoweekday() == 1 and now.hour == 0 and now.minute < 5:
        return
    award(store, season_of(now - timedelta(days=7)))


def summary(store: Store, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    season = season_of(now)
    trophies: dict[str, list] = {}
    for r in store.q("SELECT actor, payload FROM events WHERE kind = 'award' AND actor != 'office' ORDER BY id"):
        p = json.loads(r["payload"])
        trophies.setdefault(r["actor"], []).append({"season": p["season"], "award": p["award"], "title": p["title"]})
    return {"season": season, "ends": bounds(season)[1].isoformat(), "standings": standings(store, season), "trophies": trophies}
