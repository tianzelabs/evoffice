"""Experience, levels and badges -- earned by VALIDATED IMPROVEMENT, not by P&L.

The office's point is a trader that changes how it trades and can show whether
the change helped. So XP pays for testing and for improvement measured on data
the trader cannot see; a lucky trade earns almost nothing. Everything is
derived from events and positions (nothing to tamper with), and a level-up or a
new badge is announced as an event so the room and the manager can react.

XP
  +3   a held-out evaluation completed
  +15  a held-out result that beats the trader's previous best by >= 1 bps/trade
  +50  a held-out result whose 95% interval is entirely above zero (an edge)
  +10  a strategy version that got an evaluation or a live trade before it was replaced
  +2   a closed live paper trade (at most +10 a day)

Levels unlock a bigger position cap and, at the top, a little more budget.
A trader with no new version and no evaluation for 24 h is on probation.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .store import Store

LEVELS = [  # (min XP, title, max_size BTC, daily budget USD)
    (0, "Junior", 0.005, 0.30),
    (60, "Associate", 0.01, 0.30),
    (150, "Trader", 0.02, 0.30),
    (300, "Senior", 0.035, 0.35),
    (600, "Lead", 0.05, 0.40),
]
PROBATION_AFTER = timedelta(hours=24)
BADGES = {
    "named": "Chose a name",
    "first_trade": "First live trade",
    "first_test": "First held-out test",
    "first_green": "First profitable trade",
    "improver": "Beat own best held-out result",
    "edge": "Held-out interval above zero",
    "iterator": "Ten strategy versions",
    "experimenter": "Ten live trades",
}


def _events(store: Store, employee: str, kinds: tuple[str, ...]) -> list[dict]:
    q = ",".join("?" * len(kinds))
    rows = store.q(f"SELECT id, ts, kind, payload FROM events WHERE actor = ? AND kind IN ({q}) ORDER BY id", (employee, *kinds))
    for r in rows:
        r["payload"] = json.loads(r["payload"])
    return rows


def compute(store: Store, employee: str, since: str = "", until: str = "9999") -> dict:
    """since/until (ISO timestamps) restrict everything to a window -- a season scores only its own week."""
    inside = lambda ts: since <= (ts or "") < until
    evs = [e for e in _events(store, employee, ("evaluation", "version", "name")) if inside(e["ts"])]
    evals = [e for e in evs if e["kind"] == "evaluation" and e["payload"].get("net_bps_per_trade") is not None]
    versions = [e for e in evs if e["kind"] == "version"]
    trades = [t for t in store.q("SELECT closed_ts, pnl, strategy_version FROM positions WHERE employee_id = ? "
                                 "AND closed_ts IS NOT NULL ORDER BY closed_ts", (employee,)) if inside(t["closed_ts"])]
    xp, log, best = 0, [], None
    for e in evals:
        p = e["payload"]
        xp += 3
        if best is not None and p["net_bps_per_trade"] >= best + 1:
            xp += 15; log.append((e["ts"], 15, f"beat own best: {p['net_bps_per_trade']} vs {best} bps"))
        if (p.get("ci95_net_bps_per_trade") or [0])[0] > 0:
            xp += 50; log.append((e["ts"], 50, f"edge: interval {p['ci95_net_bps_per_trade']}"))
        best = p["net_bps_per_trade"] if best is None else max(best, p["net_bps_per_trade"])
    for i, v in enumerate(versions[:-1]):                      # a replaced version that was tested while current
        start, end = v["ts"], versions[i + 1]["ts"]
        tested = any(start <= e["ts"] < end for e in evals) or any(start <= (t["closed_ts"] or "") < end for t in trades)
        if tested:
            xp += 10; log.append((end, 10, f"tested version {v['payload'].get('version')}"))
    per_day: dict[str, int] = {}
    for t in trades:
        day = t["closed_ts"][:10]
        if per_day.get(day, 0) < 10:
            per_day[day] = per_day.get(day, 0) + 2
            xp += 2
    lvl = max(i for i, (need, *_rest) in enumerate(LEVELS) if xp >= need)
    need, title, cap, budget = LEVELS[lvl]
    nxt = LEVELS[lvl + 1][0] if lvl + 1 < len(LEVELS) else None
    last_work = max([e["ts"] for e in evals + versions] or [""])
    hired = (store.employee(employee) or {}).get("hired_ts", "")
    since = last_work or hired
    probation = bool(since) and datetime.now(timezone.utc) - datetime.fromisoformat(since) > PROBATION_AFTER
    badges = []
    if any(e["kind"] == "name" for e in evs): badges.append("named")
    if trades: badges.append("first_trade")
    if evals: badges.append("first_test")
    if any(t["pnl"] > 0 for t in trades): badges.append("first_green")
    if any(x[1] == 15 for x in log): badges.append("improver")
    if any(x[1] == 50 for x in log): badges.append("edge")
    if len(versions) >= 10: badges.append("iterator")
    if len(trades) >= 10: badges.append("experimenter")
    return {"employee": employee, "xp": xp, "level": lvl + 1, "title": title, "next_level_xp": nxt,
            "max_size": cap, "budget_usd": budget, "probation": probation, "badges": badges,
            "recent": [{"ts": t, "xp": x, "why": w} for t, x, w in log[-5:]]}


def announce(store: Store, employee: str) -> None:
    """Emit level-up and new-badge events once, comparing with what was already announced."""
    emp = store.employee(employee)
    if not emp or emp["role"] != "trader":
        return
    now = compute(store, employee)
    seen = _events(store, employee, ("level", "badge"))
    best_level = max([e["payload"]["level"] for e in seen if e["kind"] == "level"] or [1])
    if now["level"] > best_level:
        store.emit(employee, "level", {"employee": employee, "level": now["level"], "title": now["title"],
                                       "xp": now["xp"], "max_size": now["max_size"], "budget_usd": now["budget_usd"]})
    have = {e["payload"]["badge"] for e in seen if e["kind"] == "badge"}
    for b in now["badges"]:
        if b not in have:
            store.emit(employee, "badge", {"employee": employee, "badge": b, "title": BADGES[b]})


def all_progress(store: Store) -> dict:
    return {r["id"]: compute(store, r["id"]) for r in store.q("SELECT id FROM employees WHERE role = 'trader' AND fired_ts IS NULL")}
