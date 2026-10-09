"""Walk a strategy forward over bars it has never seen -- pure, no I/O.

The trader's `decide(bars)` is called every STEP minutes with the WINDOW bars
before that moment (never a bar after it), and returns
{"side": "long" | "short" | None, "hold_minutes": int}. A position is entered
at the last close it saw, exited HOLD minutes later, and charged both fees with
the same arithmetic as live settlement. Positions do not overlap.

Only aggregates leave the evaluator. Per-trade detail would let a trader probe
the held-out window until it had reconstructed it -- which would make it data
it has seen, the exact thing this exists to prevent (spike 4).
"""
from __future__ import annotations

import random
import statistics

from server.settlement import settle

STEP, WINDOW, MAX_HOLD = 15, 1440, 1440


def simulate(bars: list[dict], decide, step: int = STEP, window: int = WINDOW) -> dict:
    pnl_bps, errors, i = [], 0, window
    first_error = None
    while i < len(bars):
        try:
            d = decide(bars[i - window:i]) or {}
            side = d.get("side")
            hold = int(d.get("hold_minutes", 0))
        except Exception as e:                    # a crash is a decision not to trade, and is counted
            errors += 1
            first_error = first_error or f"{type(e).__name__}: {str(e)[:200]}"
            side, hold = None, 0
        if side in ("long", "short") and 1 <= hold <= MAX_HOLD and i - 1 + hold < len(bars):
            entry, exit_ = bars[i - 1]["c"], bars[i - 1 + hold]["c"]
            pnl_bps.append(settle(side, 1.0, entry, exit_).pnl_bps)
            i += max(hold, step)
        else:
            i += step
    return {"pnl_bps": pnl_bps, "decide_errors": errors, "first_error": first_error}


def aggregate(pnl_bps: list[float], seed: int = 0) -> dict:
    n = len(pnl_bps)
    if n == 0:
        return {"trades": 0}
    out = {"trades": n, "net_bps_per_trade": round(statistics.mean(pnl_bps), 2),
           "hit_rate": round(sum(p > 0 for p in pnl_bps) / n, 3), "total_net_bps": round(sum(pnl_bps), 1)}
    if n >= 5:
        rng = random.Random(seed)
        means = sorted(statistics.mean(rng.choice(pnl_bps) for _ in pnl_bps) for _ in range(2000))
        out["ci95_net_bps_per_trade"] = [round(means[50], 2), round(means[1950], 2)]
    return out
