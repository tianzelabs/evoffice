"""The trading account: simulated capital under Kraken's margin rules (the boss, 2026-10-11).

"I put in $100; double it as fast as you can." So the office stops capping size by level and
stops forcing exits; what bounds the trader is what bounds a real Kraken account -- margin:

- Equity = starting capital + realised P&L since the account started (net of every fee and
  funding) + unrealised P&L of the open position at the mark, less its entry fee (already paid).
- Kraken EU retail (the "europa" schedule for PF_XBTUSD, read from Kraken's instruments API on
  2026-10-11; the boss trades from Budapest): INITIAL margin 10% of notional -- at most 10x --
  and MAINTENANCE margin 5%. A new position, or more of one, must fit the initial margin.
- When equity falls below the maintenance margin, the office liquidates at market (taker), as
  Kraken does. Kraken's own liquidation fee is NOT modelled (so this errs on the kind side).
- An account with (nearly) nothing left is BLOWN: no new positions until the boss starts a new one.
"""
from __future__ import annotations

import json
import os

from .store import Store, now

START_EQUITY = float(os.environ.get("OFFICE_START_EQUITY", "100"))
IM = float(os.environ.get("OFFICE_INITIAL_MARGIN", "0.10"))
MM = float(os.environ.get("OFFICE_MAINTENANCE_MARGIN", "0.05"))
BLOWN_BELOW = 1.0
GOAL_MULTIPLE = 2.0


def current(store: Store) -> dict:
    rows = store.q("SELECT ts, payload FROM events WHERE kind = 'account' ORDER BY id DESC")
    for r in rows:
        p = json.loads(r["payload"])
        if p.get("phase") == "start":
            return {"start_equity": p["start_equity"], "since": r["ts"], "goal": p.get("goal")}
    return {"start_equity": START_EQUITY, "since": None, "goal": START_EQUITY * GOAL_MULTIPLE}


def start(store: Store, equity: float, actor: str, reason: str) -> dict:
    if store.q("SELECT 1 FROM positions WHERE closed_ts IS NULL"):
        raise ValueError("close every open position before starting a new account")
    store.emit(actor, "account", {"phase": "start", "start_equity": equity, "goal": equity * GOAL_MULTIPLE,
                                  "reason": reason, "initial_margin": IM, "maintenance_margin": MM})
    return current(store)


def state(store: Store, mark: float | None) -> dict:
    acc = current(store)
    since = acc["since"] or "0000"
    realized = sum(r["pnl"] or 0 for r in store.q(
        "SELECT pnl FROM positions WHERE closed_ts IS NOT NULL AND closed_ts >= ? AND opened_ts >= ?", (since, since)))
    unreal, notional, net = 0.0, 0.0, 0.0
    for p in store.q("SELECT * FROM positions WHERE closed_ts IS NULL"):
        d = 1 if p["side"] == "long" else -1
        px = mark or p["entry_px"]
        unreal += d * (px - p["entry_px"]) * p["size"] + (p["funding"] or 0) - (p["entry_fee"] or 0)
        net += d * p["size"]
        notional += p["size"] * px
    equity = acc["start_equity"] + realized + unreal
    blown = any(json.loads(r["payload"]).get("phase") == "blown" for r in store.q(
        "SELECT payload FROM events WHERE kind = 'account' AND ts >= ?", (since,)))
    if blown:
        equity = max(equity, 0.0)       # a gap past liquidation: Kraken's insurance fund absorbs the deficit
    return {"start_equity": acc["start_equity"], "since": acc["since"], "goal": acc["goal"],
            "equity": round(equity, 4), "realized": round(realized, 4), "unrealized": round(unreal, 4),
            "net_btc": round(net, 6), "notional": round(notional, 2),
            "leverage": round(notional / equity, 2) if equity > 0 else None,
            "initial_margin_used": round(notional * IM, 2), "maintenance_margin": round(notional * MM, 2),
            "max_notional": round(max(equity, 0) / IM, 2), "progress_to_goal": round(equity / acc["goal"], 3),
            "rules": f"Kraken EU retail: initial margin {IM:.0%} (max {1 / IM:.0f}x), maintenance {MM:.0%}",
            "blown": blown}


def check(store: Store, net_after_btc: float, price: float):
    """Raise ValueError if a position of net_after_btc does not fit the initial margin."""
    s = state(store, price)
    if s["blown"]:
        raise ValueError("the account is blown; the boss must start a new one")
    need = abs(net_after_btc) * price * IM
    if need > s["equity"] + 1e-9:
        raise ValueError(f"margin: {abs(net_after_btc):.4f} BTC at {price:.0f} needs {need:.2f} USD initial margin "
                         f"({IM:.0%}, Kraken EU retail, max {1 / IM:.0f}x) but equity is {s['equity']:.2f} USD; "
                         f"the most you can hold now is {max(s['equity'], 0) / IM / price:.4f} BTC")


def liquidate_if_needed(store: Store, market) -> list[int]:
    """Kraken's liquidation: equity below maintenance margin -> the position is closed at market."""
    from . import positions
    if not store.q("SELECT 1 FROM positions WHERE closed_ts IS NULL"):
        return []
    try:
        q = market.quote(positions.PRODUCT)
    except Exception:
        return []
    s = state(store, q.mark)
    if s["equity"] >= s["maintenance_margin"]:
        return []
    closed = []
    for p in store.q("SELECT id FROM positions WHERE closed_ts IS NULL"):
        try:
            positions.close_position(store, market, p["id"], actor="office", reason="liquidation")
            closed.append(p["id"])
        except positions.Refused:
            pass
    after = state(store, q.mark)
    store.emit("office", "account", {"phase": "liquidation", "positions": closed, "equity_before": s["equity"],
                                     "maintenance_margin": s["maintenance_margin"], "equity_after": after["equity"],
                                     "at": now()})
    if after["equity"] < BLOWN_BELOW:
        store.emit("office", "account", {"phase": "blown", "equity": after["equity"], "at": now()})
    return closed
