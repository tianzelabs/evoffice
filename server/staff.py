"""The manager's authority over traders, as routes: set parameters, fire.

Full authority over the trader, none over the office: these change a trader's
heartbeat, size cap and backstop, or replace it -- never fees, settlement,
prices, budgets or the ledger, for which no route exists. The boss can do
anything the manager can.

Firing: the employee keeps its id and its record on the leaderboard; the seat
gets a successor with a new id (trader-1 -> trader-1.2), and the seat's token is
re-pointed at it. The trader's runner sees its id change, wipes its REPL and
objects, and starts again as a new hire.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import positions
from .store import Store, now

LIMITS = {"heartbeat_min": (5, 720), "max_size": (0.001, positions.MAX_SIZE_BTC), "max_hold_min": (1, 1440)}


class StaffRefused(Exception):
    pass


def _target(store: Store, who: dict, employee_id: str) -> dict:
    if who["role"] not in ("manager", "boss"):
        raise StaffRefused("only the manager or the boss can do this")
    emp = store.employee(employee_id)
    if not emp or emp["role"] != "trader":
        raise StaffRefused(f"no trader {employee_id!r}")
    if emp["fired_ts"]:
        raise StaffRefused(f"{employee_id} has already been fired")
    return emp


def set_params(store: Store, who: dict, employee_id: str, changes: dict, reason: str = "") -> dict:
    emp = _target(store, who, employee_id)
    clean = {}
    for k, v in changes.items():
        if v is None:
            continue
        if k not in LIMITS:
            raise StaffRefused(f"unknown parameter {k!r}; allowed: {sorted(LIMITS)}")
        lo, hi = LIMITS[k]
        if not lo <= float(v) <= hi:
            raise StaffRefused(f"{k} must be between {lo} and {hi}")
        clean[k] = float(v) if k == "max_size" else int(v)
    if not clean:
        raise StaffRefused("nothing to change")
    params = {**emp["params"], **clean}
    if "max_hold_min" in clean:
        params["max_hold_s"] = clean["max_hold_min"] * 60      # the field positions.py reads
    store.x("UPDATE employees SET params = ? WHERE id = ?", (json.dumps(params), employee_id))
    store.emit(who["id"], "command", {"employee": employee_id, "changes": clean, "reason": reason[:500]})
    return store.employee(employee_id)


def fire(store: Store, market, who: dict, employee_id: str, reason: str,
         tokens: dict, tokens_path: Path | None, replace: bool = True) -> dict:
    """replace=False closes the seat instead of refilling it -- an office-size decision, so the boss's only."""
    _target(store, who, employee_id)
    if not replace and who["role"] != "boss":
        raise StaffRefused("only the boss can close a seat; the manager's firing always hires a successor")
    with store.lock:
        store.x("UPDATE employees SET fired_ts = ? WHERE id = ?", (now(), employee_id))
        unclosed = []
        for p in positions.listing(store, employee_id, open_only=True):
            try:
                positions.close_position(store, market, p["id"], actor="office", reason="fired")
            except positions.Refused:
                unclosed.append(p["id"])          # stale feed: the max_hold backstop closes it later
        seat = employee_id.split(".")[0]
        successor = None
        if replace:
            gen = len(store.q("SELECT id FROM employees WHERE id = ? OR id LIKE ?", (seat, seat + ".%"))) + 1
            successor = f"{seat}.{gen}"
            store.hire(successor, "trader")
        for t, w in list(tokens.items()):
            if w["id"] == employee_id:
                if successor:
                    tokens[t] = {"id": successor, "role": "trader"}
                else:
                    del tokens[t]
        if tokens_path:
            tokens_path.write_text(json.dumps(tokens, indent=1))
    store.emit(who["id"], "fire", {"employee": employee_id, "successor": successor, "reason": reason[:500],
                                   "positions_left_open": unclosed})
    return {"fired": employee_id, "successor": successor, "positions_left_open": unclosed}
