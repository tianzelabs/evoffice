"""What a manager can do in the office, as plain functions.

Two front ends share these: LangChain tools (tools.py) and the `office` command
line that a Codex manager drives from its shell (office_cli.py). Each wraps a
route the manager's token may call; there is nothing here for what the office
does not let a manager do -- the missing route is the limit.

OFFICE_DRY_RUN=1 records writes to $MANAGER_STATE/dry_actions.jsonl instead of
taking them, so models can be compared without several managers talking at once.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.common.office_client import Office, Refused

DRY = os.environ.get("OFFICE_DRY_RUN") == "1"


def _state() -> Path:
    p = Path(os.path.expanduser(os.environ.get("MANAGER_STATE", "~/pixel-office/manager-state")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dry(action: dict) -> str:
    with open(_state() / "dry_actions.jsonl", "a") as f:
        f.write(json.dumps(action, ensure_ascii=False) + "\n")
    return "ok (dry run: recorded, not taken)"


def _safe(fn):
    try:
        return fn()
    except Refused as e:
        return {"error": str(e)}


def all_events(office: Office, since: int = 0) -> list[dict]:
    out = []
    while True:
        evs = office.events(since)
        if not evs:
            return out
        out += evs
        since = evs[-1]["id"]


def say(office: Office, text: str, to: str | None = None) -> str:
    if DRY:
        return _dry({"say": text, "to": to})
    r = _safe(lambda: office.say(text[:2000], to))
    return "said" if "error" not in r else r["error"]


def read_recent_chat(office: Office, n: int = 30) -> str:
    says = [e for e in all_events(office) if e["kind"] == "say"][-max(1, min(n, 200)):]
    return json.dumps([{"ts": e["ts"][:19], "from": e["actor"], "to": e["payload"].get("to"),
                        "text": e["payload"]["text"]} for e in says], ensure_ascii=False)


def leaderboard(office: Office) -> str:
    return json.dumps(_safe(lambda: office.get("/leaderboard")), ensure_ascii=False)


def employees(office: Office) -> str:
    return json.dumps(_safe(lambda: office.get("/employees")), ensure_ascii=False)


def trader_activity(office: Office, trader: str, n: int = 10) -> str:
    evs = [e for e in all_events(office) if e["actor"] == trader]
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    wakes = Counter(r.split(" (")[0] for e in evs if e["kind"] == "wake" and e["ts"] >= day_ago
                    for r in e["payload"].get("reasons", []))
    pick = lambda kind, k: [{"ts": e["ts"][:19], **e["payload"]} for e in evs if e["kind"] == kind][-k:]
    return json.dumps({"turns": pick("turn", n), "versions": pick("version", n), "evaluations": pick("evaluation", n),
                       "wake_reasons_last_24h": dict(wakes)}, ensure_ascii=False)[:20000]


def trader_positions(office: Office, trader: str) -> str:
    return json.dumps(_safe(lambda: office.positions(trader))[:50], ensure_ascii=False)


def market(office: Office, minutes: int = 120) -> str:
    """Recent BTC/USD 1-minute bars and the last price -- the manager can check a trader's claims."""
    return json.dumps({"price": _safe(office.price), "bars": _safe(lambda: office.bars(minutes))}, ensure_ascii=False)


def set_trader_params(office: Office, trader: str, reason: str, heartbeat_min: int | None = None,
                      max_size: float | None = None, max_hold_min: int | None = None) -> str:
    body = {"heartbeat_min": heartbeat_min, "max_size": max_size, "max_hold_min": max_hold_min, "reason": reason}
    if DRY:
        return _dry({"set_params": trader, **body})
    return json.dumps(_safe(lambda: office.post(f"/employees/{trader}/params", body)), ensure_ascii=False)


def fire_trader(office: Office, trader: str, reason: str) -> str:
    if DRY:
        return _dry({"fire": trader, "reason": reason})
    return json.dumps(_safe(lambda: office.post(f"/employees/{trader}/fire", {"reason": reason})), ensure_ascii=False)


def read_notes() -> str:
    p = _state() / "notes.txt"
    return p.read_text() if p.exists() else ""


def save_notes(text: str) -> str:
    if DRY:
        return _dry({"notes": text})
    (_state() / "notes.txt").write_text(text[:8000])
    return "saved"
