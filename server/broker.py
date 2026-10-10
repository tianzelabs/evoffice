"""From paper to a real Kraken account -- the gate, and the switch that stays off.

Today every order goes to the office's own simulator (server/positions.py,
server/orders.py), whose market fills match Kraken's paper engine tick for tick
(ops/kraken_parity.py) and whose limit fills are stricter than it. When a trader
can actually make money, the user means to move it to a real account. This
module is that path, built but OFF:

1. `checklist()` -- readable by anyone (GET /golive/{trader}) -- says, item by
   item, whether a trader has earned it. The gate mirrors Kraken's own
   paper-to-live guidance (one frozen strategy, held-out evidence AND live
   paper evidence, explicit approval) and this office's spike 4 (a p=0.044
   validation result lost 22.5 bps a trade on unseen data):
     - a strategy version whose held-out 95% interval is entirely above zero,
       under the CURRENT fee regime;
     - at least MIN_LIVE_TRADES closed live paper trades of that same version,
       net positive after fees and funding;
     - the boss's approval file, written by the boss by hand;
     - kraken-cli installed and credentials configured BY THE USER (trade-only,
       no withdrawal permission) -- the office never holds them.
2. `KrakenLive` would send the same orders through `kraken futures` without the
   `paper` subcommand. It refuses unless every item passes AND OFFICE_LIVE_TRADING
   is set to the exact phrase below. Nothing routes orders to it yet: wiring it in
   is a code change the user makes deliberately, never a flag an agent can flip.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
from pathlib import Path

from . import fees
from .store import Store

MIN_LIVE_TRADES = 30
APPROVAL = Path(os.path.expanduser("~/pixel-office/LIVE_APPROVED.json"))   # {"trader": ..., "version": ..., "max_size": ...}
PHRASE = "real-money-I-approve"
KRAKEN = os.path.expanduser("~/.cargo/bin/kraken")


class LiveDisabled(Exception):
    pass


def checklist(store: Store, employee: str) -> dict:
    evals = [json.loads(r["payload"]) for r in store.q(
        "SELECT payload FROM events WHERE kind = 'evaluation' AND actor = ? ORDER BY id", (employee,))]
    edge = [e for e in evals if e.get("regime") == fees.REGIME and (e.get("ci95_net_bps_per_trade") or [0])[0] > 0]
    version = edge[-1].get("version") if edge else None
    trades = store.q("SELECT pnl FROM positions WHERE employee_id = ? AND strategy_version = ? AND closed_ts IS NOT NULL "
                     "AND regime = ?", (employee, version, fees.REGIME)) if version else []
    pnl = [t["pnl"] for t in trades]
    approval = json.loads(APPROVAL.read_text()) if APPROVAL.exists() else {}
    items = [
        {"item": "held-out edge under current fees", "ok": bool(edge),
         "detail": f"version {version}, interval {edge[-1].get('ci95_net_bps_per_trade')}" if edge else f"none in {fees.REGIME}"},
        {"item": f">= {MIN_LIVE_TRADES} live paper trades of that version, net positive", "ok":
            len(pnl) >= MIN_LIVE_TRADES and statistics.mean(pnl) > 0 if pnl else False,
         "detail": f"{len(pnl)} trades, mean {round(statistics.mean(pnl), 4) if pnl else '-'}"},
        {"item": "boss approval file", "ok": approval.get("trader") == employee and approval.get("version") == version,
         "detail": str(APPROVAL)},
        {"item": "kraken-cli installed", "ok": bool(shutil.which(KRAKEN) or Path(KRAKEN).exists()), "detail": KRAKEN},
        {"item": "live switch", "ok": os.environ.get("OFFICE_LIVE_TRADING") == PHRASE,
         "detail": "OFFICE_LIVE_TRADING must be set by the user in the server's unit"},
    ]
    return {"employee": employee, "regime": fees.REGIME, "ready": all(i["ok"] for i in items), "items": items}


class KrakenLive:
    """The real-account path. Refuses unless the checklist passes in full."""

    def __init__(self, store: Store):
        self.store = store

    def submit(self, employee: str, side: str, size: float, order_type: str = "market", price: float | None = None):
        c = checklist(self.store, employee)
        if not c["ready"]:
            missing = [i["item"] for i in c["items"] if not i["ok"]]
            raise LiveDisabled(f"live trading is off for {employee}: missing {missing}")
        cap = float(json.loads(APPROVAL.read_text()).get("max_size", 0))
        if size > cap:
            raise LiveDisabled(f"size {size} exceeds the boss-approved max_size {cap}")
        args = [KRAKEN, "futures", "buy" if side == "buy" else "sell", "PF_XBTUSD", str(size), "--type", order_type]
        if order_type != "market":
            args += ["--price", str(price)]
        raise LiveDisabled("not wired: the user connects this path to the order routes deliberately, "
                           f"after reviewing the command it would run: {' '.join(args)}")
