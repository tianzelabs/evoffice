"""The trading account: simulated capital under Kraken's margin rules (the boss, 2026-10-11).

"I put in $100; double it as fast as you can." So the office stops capping size by level and
stops forcing exits; what bounds the trader is what bounds a real Kraken account -- margin:

- Equity = starting capital + realised P&L since the account started (net of every fee and
  funding) + unrealised P&L of the open position at the mark, less its entry fee (already paid).
- Kraken EU retail (the "europa" schedule for PF_XBTUSD, read from Kraken's instruments API on
  2026-10-11; the boss trades from Budapest): INITIAL margin 10% of notional -- at most 10x --
  and MAINTENANCE margin 5%. A new position, or more of one, must fit the initial margin.
- Below maintenance margin: Kraken's Equity Protection Process -- partial liquidation in 10% steps,
  then full liquidation with its fee (see liquidate_if_needed).
- An account with (nearly) nothing left is BLOWN: no new positions until the boss starts a new one.
"""
from __future__ import annotations

import json
import os

from . import fees
from .store import Store, now
import math

START_EQUITY = float(os.environ.get("OFFICE_START_EQUITY", "100"))
IM = float(os.environ.get("OFFICE_INITIAL_MARGIN", "0.10"))
MM = float(os.environ.get("OFFICE_MAINTENANCE_MARGIN", "0.05"))
BLOWN_BELOW = 1.0
LIQ_RATIO = 0.7          # liquidation margin = 70% of maintenance (Kraken Liquidation FAQ)
FULL_LIQ_FEE = 0.005     # half of PF_XBTUSD's minimum maintenance margin (1%), per Kraken's EPP
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
    """Kraken's Equity Protection Process for multi-collateral perpetuals (support.kraken.com, "Equity
    Protection Process" and the EEA derivatives fee page, partial liquidation live since 2026-03-26):

    1. equity below MAINTENANCE margin but at or above the LIQUIDATION margin (LIQ_RATIO x maintenance):
       PARTIAL liquidation -- the position is cut in 10% steps at market (taker fee) until equity is back
       above maintenance. Each step also pays the partial-liquidation fee: (fill price capped at the
       mark - the zero-equity price) x quantity.
    2. equity below the liquidation margin: FULL liquidation at market (taker fee) plus the full
       liquidation fee, half the contract's minimum maintenance margin -- 0.5% of notional for
       PF_XBTUSD -- never more than what is left: the trader keeps any excess.
    3. a fill beyond the zero-equity price leaves nothing; the deficit is the insurance fund's (equity 0).
    """
    from . import positions
    rows = store.q("SELECT * FROM positions WHERE closed_ts IS NULL")
    if not rows:
        return []
    try:
        mark = market.quote(positions.PRODUCT).mark
    except Exception:
        return []
    emp = store.employee(rows[0]["employee_id"])
    acted, steps = [], 0
    # Kraken continues "until equity is restored above maintenance or the position is fully closed"; the
    # 10% slices shrink geometrically, so this ends. NOTE: by Kraken's partial-liquidation fee formula a
    # slice's fee is its share of the remaining equity, so equity/notional does not improve and a small,
    # flat-margin account is in effect wound down step by step. Being liquidated costs nearly everything.
    while steps < 500:
        s = state(store, mark)
        net = s["net_btc"]
        if abs(net) < 1e-9 or s["equity"] >= s["maintenance_margin"]:
            break
        d = 1 if net > 0 else -1
        size = abs(net)
        zep = mark - d * s["equity"] / size                   # where equity would be exactly zero
        full = s["equity"] < LIQ_RATIO * s["maintenance_margin"]
        qty = size if full else max(positions.SIZE_STEP, math.floor(size * 0.10 / positions.SIZE_STEP) * positions.SIZE_STEP)
        qty = min(qty, size)
        taking = "sell" if d > 0 else "buy"
        try:
            fill_px = positions.market_price(market, taking, qty)
        except positions.Refused:
            break                                              # no book: try again on the next pass
        taker = qty * fill_px * fees.TAKER
        if full:
            left = s["equity"] + d * (fill_px - mark) * size - taker
            fee = min(FULL_LIQ_FEE * qty * fill_px, max(left, 0.0))
        else:
            capped = min(fill_px, mark) if d > 0 else max(fill_px, mark)
            fee = max(0.0, d * (capped - zep)) * qty
        positions.fill(store, emp, positions.PRODUCT, "short" if d > 0 else "long", round(qty, 8), fill_px, "taker",
                       None, None, "full liquidation" if full else "partial liquidation", "liquidation", fee)
        after = state(store, mark)
        store.emit("office", "account", {"phase": "liquidation", "kind": "full" if full else "partial",
                                         "qty": round(qty, 8), "fill_px": round(fill_px, 2), "fee": round(fee, 4),
                                         "zero_equity_px": round(zep, 2), "equity_before": s["equity"],
                                         "maintenance_margin": s["maintenance_margin"],
                                         "equity_after": after["equity"], "at": now()})
        acted.append(steps)
        steps += 1
        if full:
            break
    if acted and state(store, mark)["equity"] < BLOWN_BELOW and abs(state(store, mark)["net_btc"]) < 1e-9:
        store.emit("office", "account", {"phase": "blown", "equity": state(store, mark)["equity"], "at": now()})
    return acted
