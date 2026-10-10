"""The manager's objective (the boss, 2026-10-10): turn the minus into a plus.

A ladder computed from the record, so nobody -- manager included -- grades itself:

  1. a candidate net-positive on BOTH research windows (train and recent backtests,
     each with at least MIN_BT_TRADES trades)
  2. a held-out evaluation net-positive per trade (current fee regime)
  3. a held-out evaluation whose 95% interval is entirely above zero
  4. at least MIN_LIVE closed live paper trades, net positive after fees and funding

Each rung reports its best number so far, so progress shows before a rung is reached.
Rung 4 is also the first item of the go-live checklist's live evidence (server/broker.py).
"""
from __future__ import annotations

import json

from . import fees
from .store import Store

MIN_BT_TRADES, MIN_LIVE = 20, 30


def compute(store: Store) -> dict:
    bts = [json.loads(p["payload"]) | {"actor": p["actor"], "ts": p["ts"]} for p in store.q(
        "SELECT actor, ts, payload FROM events WHERE kind = 'backtest' ORDER BY id")]
    by_cand: dict[str, dict] = {}
    for b in bts:
        if b.get("error") or (b.get("trades") or 0) < MIN_BT_TRADES or b.get("net_bps_per_trade") is None:
            continue
        c = by_cand.setdefault(b["candidate"], {})
        c[b["data"]] = max(c.get(b["data"], -1e9), b["net_bps_per_trade"])
    both = [(min(v["train"], v["recent"]), k, v) for k, v in by_cand.items() if "train" in v and "recent" in v]
    best_both = max(both, default=None)
    best_train = max((v["train"] for v in by_cand.values() if "train" in v), default=None)
    best_recent = max((v["recent"] for v in by_cand.values() if "recent" in v), default=None)

    evals = [json.loads(p["payload"]) for p in store.q("SELECT payload FROM events WHERE kind = 'evaluation'")]
    evals = [e for e in evals if e.get("regime") == fees.REGIME and e.get("net_bps_per_trade") is not None]
    best_eval = max((e["net_bps_per_trade"] for e in evals), default=None)
    best_low = max(((e.get("ci95_net_bps_per_trade") or [None])[0] for e in evals
                    if e.get("ci95_net_bps_per_trade")), default=None)

    live = store.q("SELECT pnl, size, entry_px FROM positions WHERE closed_ts IS NOT NULL AND regime = ? "
                   "ORDER BY closed_ts DESC LIMIT ?", (fees.REGIME, MIN_LIVE))
    live_n = len(live)
    live_pnl = round(sum(r["pnl"] for r in live), 4) if live else None
    live_bps = round(sum(r["pnl"] / (r["size"] * r["entry_px"]) * 1e4 for r in live) / live_n, 2) if live else None

    rungs = [
        {"rung": 1, "goal": "a candidate net-positive on both train and recent backtests",
         "reached": bool(best_both and best_both[0] > 0),
         "best": {"both_windows_min_bps": best_both[0] if best_both else None,
                  "candidate": best_both[1] if best_both else None,
                  "best_train_bps": best_train, "best_recent_bps": best_recent,
                  "candidates_tested": len(by_cand)}},
        {"rung": 2, "goal": "held-out net bps per trade above zero", "reached": best_eval is not None and best_eval > 0,
         "best": {"best_heldout_bps": best_eval, "evaluations": len(evals)}},
        {"rung": 3, "goal": "held-out 95% interval entirely above zero", "reached": best_low is not None and best_low > 0,
         "best": {"best_interval_low_bps": best_low}},
        {"rung": 4, "goal": f">= {MIN_LIVE} live paper trades, net positive", "reached":
            live_n >= MIN_LIVE and (live_pnl or 0) > 0,
         "best": {"last_trades": live_n, "net_usd": live_pnl, "avg_net_bps": live_bps}},
    ]
    top = 0
    for r in rungs:
        if not r["reached"]:
            break
        top = r["rung"]
    return {"regime": fees.REGIME, "rung": top, "rungs": rungs,
            "next": rungs[top]["goal"] if top < len(rungs) else "all four: the go-live checklist is next"}
