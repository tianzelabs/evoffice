"""Walk a strategy forward over bars it has never seen -- pure, no I/O.

Kraken Futures rules, the same as the live office (server/fees.py): a market
entry or exit pays the TAKER fee and half the spread; an entry may instead rest
as a limit order and pay the MAKER fee -- but only if a later bar trades THROUGH
its price (low strictly below a buy, high strictly above a sell) before it
expires. Hourly funding at Kraken's published rate is charged on every hour
boundary the position spans.

The trader's `decide(bars)` sees only the WINDOW bars before now and returns
  {"side": "long"|"short"|None, "hold_minutes": int,
   optional "entry": "limit", "offset_bps": float, "ttl_minutes": int,
   optional "take_profit_bps": float, "stop_loss_bps": float}
`hold_minutes` is the longest hold. A take-profit rests as a limit order from the
entry bar on and exits as MAKER at its price when a bar trades through it; a stop
exits as TAKER at its price less the half-spread, or at the bar's open if the bar
gapped past it. When one bar reaches both, the stop is assumed to come first.
Positions do not overlap. Only aggregates leave the evaluator: per-trade detail
would let a trader probe the held-out window until it had reconstructed it.
"""
from __future__ import annotations

import random
import statistics
from datetime import datetime, timezone

from server.settlement import settle

STEP, WINDOW, MAX_HOLD, MAX_TTL = 15, 1440, 1440, 240
HALF_SPREAD = 0.5          # PF_XBTUSD trades at a 1 USD spread almost always


def _epoch(m: str) -> int:
    return int(datetime.fromisoformat(m).replace(tzinfo=timezone.utc).timestamp())


def _funding(side: str, entry_px: float, t0: int, t1: int, rates: dict[int, float]) -> float:
    total, h = 0.0, (t0 // 3600 + 1) * 3600
    while h <= t1:
        r = rates.get(h, 0.0)
        total += (-r if side == "long" else r) * entry_px
        h += 3600
    return total


def simulate(bars: list[dict], decide, funding: dict[int, float] | None = None, step: int = STEP,
             window: int = WINDOW) -> dict:
    funding = funding or {}
    pnl_bps, trades, errors, makers, unfilled, i = [], [], 0, 0, 0, window
    first_error = None
    while i < len(bars):
        try:
            d = decide(bars[i - window:i]) or {}
            side, hold = d.get("side"), int(d.get("hold_minutes", 0))
            limit = d.get("entry") == "limit"
            offset, ttl = float(d.get("offset_bps", 0)), max(1, min(int(d.get("ttl_minutes", 60)), MAX_TTL))
            tp, sl = d.get("take_profit_bps"), d.get("stop_loss_bps")
            tp = float(tp) if tp is not None and float(tp) > 0 else None
            sl = float(sl) if sl is not None and float(sl) > 0 else None
        except Exception as e:                    # a crash is a decision not to trade, and is counted
            errors += 1
            first_error = first_error or f"{type(e).__name__}: {str(e)[:200]}"
            side, hold, limit = None, 0, False
        if side not in ("long", "short") or not 1 <= hold <= MAX_HOLD:
            i += step
            continue
        ref = bars[i - 1]["c"]
        if limit:
            px = round(ref * (1 - offset / 1e4)) if side == "long" else round(ref * (1 + offset / 1e4))
            j = next((k for k in range(i, min(i + ttl, len(bars)))
                      if (bars[k]["l"] < px if side == "long" else bars[k]["h"] > px)), None)
            if j is None:
                unfilled += 1
                i += max(ttl, step)
                continue
            entry, entry_liq, start = float(px), "maker", j
            makers += 1
        else:
            entry = ref + HALF_SPREAD if side == "long" else ref - HALF_SPREAD
            entry_liq, start = "taker", i - 1
        end = start + hold
        if end >= len(bars):
            break
        exit_ = bars[end]["c"] - HALF_SPREAD if side == "long" else bars[end]["c"] + HALF_SPREAD
        exit_liq, how = "taker", "time"
        if tp or sl:
            sgn = 1 if side == "long" else -1
            tp_px = round(entry * (1 + sgn * tp / 1e4)) if tp else None
            sl_px = entry * (1 - sgn * sl / 1e4) if sl else None
            for k in range(start + 1, end + 1):
                b = bars[k]
                if sl_px is not None and (b["l"] <= sl_px if side == "long" else b["h"] >= sl_px):
                    worst = min(sl_px, b["o"]) if side == "long" else max(sl_px, b["o"])
                    exit_, exit_liq, how, end = worst - sgn * HALF_SPREAD, "taker", "stop", k
                    break
                if tp_px is not None and (b["h"] > tp_px if side == "long" else b["l"] < tp_px):
                    exit_, exit_liq, how, end = float(tp_px), "maker", "take_profit", k
                    break
        fund = _funding(side, entry, _epoch(bars[start]["m"]), _epoch(bars[end]["m"]), funding)
        pnl_bps.append(settle(side, 1.0, entry, exit_, entry_liq, exit_liq, fund).pnl_bps)
        trades.append({"m": bars[start]["m"], "side": side, "entry": entry_liq, "exit": how, "hold": end - start,
                       "pnl_bps": round(pnl_bps[-1], 2)})
        i = end + 1
    return {"pnl_bps": pnl_bps, "trades": trades, "decide_errors": errors, "first_error": first_error,
            "maker_entries": makers, "unfilled_limit_entries": unfilled}


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
