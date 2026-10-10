"""A closed trade, reviewed by the numbers (the boss, 2026-10-10: trade freely on paper, and
review every trade when it ends). The office computes the objective part, so the manager's
review starts from facts and spends its thought on the lesson:

- the trade: side, entry/exit price, time, liquidity, fees, funding, net pnl and bps, hold;
- what happened DURING it: the best (MFE) and worst (MAE) point, in bps, from 1-minute bars;
- what came BEFORE the entry (15 minutes): return, realised volatility, taker flow imbalance,
  book imbalance, spread -- the same features the lookback reviews use;
- what happened AFTER the exit: the move 5/15/60 minutes later in the trade's direction
  (positive = we left money on the table), once those minutes have passed.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .store import Store


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T")).replace(tzinfo=timezone.utc) if "+" not in s else datetime.fromisoformat(s)


def review(store: Store, market, position_id: int) -> dict:
    rows = store.q("SELECT * FROM positions WHERE id = ?", (position_id,))
    if not rows:
        raise ValueError(f"no position {position_id}")
    p = rows[0]
    d = 1 if p["side"] == "long" else -1
    opened = datetime.fromisoformat(p["opened_ts"])
    closed = datetime.fromisoformat(p["closed_ts"]) if p["closed_ts"] else None
    now = datetime.now(timezone.utc)
    back = int((now - opened).total_seconds() // 60) + 20
    ctx = market.context(p["pair"], min(back, 7 * 24 * 60))
    bar_t = lambda b: _t(b["m"])
    before = [b for b in ctx if opened - timedelta(minutes=15) <= bar_t(b) < opened.replace(second=0, microsecond=0)]
    during = [b for b in ctx if opened.replace(second=0, microsecond=0) <= bar_t(b) <= (closed or now)]
    bps = lambda px: d * (px / p["entry_px"] - 1) * 1e4
    out = {"position": p["id"], "employee": p["employee_id"], "side": p["side"], "size": p["size"],
           "strategy_version": p["strategy_version"], "entry": {"ts": p["opened_ts"], "px": p["entry_px"], "liq": p["entry_liq"]},
           "exit": {"ts": p["closed_ts"], "px": p["exit_px"], "liq": p["exit_liq"], "reason": p["close_reason"]},
           "open": closed is None,
           "hold_min": round(((closed or now) - opened).total_seconds() / 60, 1),
           "fees": p["fees"], "funding": p["funding"], "pnl": p["pnl"],
           "pnl_bps": round(p["pnl"] / (p["size"] * p["entry_px"]) * 1e4, 2) if p["pnl"] is not None else None}
    if during:
        out["mfe_bps"] = round(max(bps(b["h"] if d > 0 else b["l"]) for b in during), 2)
        out["mae_bps"] = round(min(bps(b["l"] if d > 0 else b["h"]) for b in during), 2)
    if len(before) >= 2:
        rets = [math.log(b["c"] / a["c"]) for a, b in zip(before, before[1:])]
        mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        out["before_15m"] = {
            "ret_bps": round(d * (before[-1]["c"] / before[0]["o"] - 1) * 1e4, 2),        # in the trade's direction
            "rv_bps": round(math.sqrt(sum(r * r for r in rets)) * 1e4, 2),
            "flow_imb": mean([b["flow_imb"] for b in before if "flow_imb" in b]),
            "book_imb": mean([b["book_imb"] for b in before if b.get("book_imb") is not None]),
            "spread": mean([b["spread"] for b in before if b.get("spread") is not None]),
            "trades": sum(b.get("trades", 0) for b in before)}
    if closed and p["exit_px"]:
        after = {}
        for m in (5, 15, 60):
            hit = [b for b in ctx if bar_t(b) >= closed + timedelta(minutes=m - 1)]
            if hit and closed + timedelta(minutes=m) <= now:
                after[f"{m}m"] = round(d * (hit[0]["c"] / p["exit_px"] - 1) * 1e4, 2)
        out["after_exit_bps"] = after          # > 0: the move went on in our direction after we left
    return out
