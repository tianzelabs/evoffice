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


MIN_GAP_TO_TRADER_S = 3600


def say(office: Office, text: str, to: str | None = None, urgent: bool = False) -> str:
    """Each message to a trader wakes it and spends ITS budget, so the manager may message the same
    trader at most once an hour unless urgent (the manager runs on a subscription; the traders pay)."""
    if to and to.startswith("trader") and not urgent:
        import json as _j
        import time as _t
        sent = _state() / "last_message_to.json"
        last = _j.loads(sent.read_text()) if sent.exists() else {}
        ago = _t.time() - last.get(to, 0)
        if ago < MIN_GAP_TO_TRADER_S:
            return (f"not sent: you messaged {to} {int(ago // 60)} min ago. Batch it into your next message "
                    f"(in {int((MIN_GAP_TO_TRADER_S - ago) // 60)} min), or resend with urgent if it cannot wait.")
    if DRY:
        return _dry({"say": text, "to": to, "urgent": urgent})
    r = _safe(lambda: office.say(text[:2000], to))
    if "error" in r:
        return r["error"]
    if to and to.startswith("trader"):
        import json as _j
        import time as _t
        sent = _state() / "last_message_to.json"
        last = _j.loads(sent.read_text()) if sent.exists() else {}
        last[to] = _t.time()
        sent.write_text(_j.dumps(last))
    return "said"


def set_name(office: Office, name: str) -> str:
    if DRY:
        return _dry({"name": name})
    return json.dumps(_safe(lambda: office.post("/me/name", {"name": name})), ensure_ascii=False)


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


def progress(office: Office) -> str:
    """Each trader's XP, level, perks, probation and badges (earned by validated improvement)."""
    return json.dumps(_safe(lambda: office.get("/progress")), ensure_ascii=False)


def backtest(office: Office, code: str, data: str = "train", days: float = 30) -> str:
    return json.dumps(_safe(lambda: office.backtest(code, data, days)), ensure_ascii=False)


def golive(office: Office, trader: str) -> str:
    return json.dumps(_safe(lambda: office.get(f"/golive/{trader}")), ensure_ascii=False)


def trader_orders(office: Office, trader: str) -> str:
    return json.dumps(_safe(lambda: office.orders(trader))[:30], ensure_ascii=False)


def trader_positions(office: Office, trader: str) -> str:
    return json.dumps(_safe(lambda: office.positions(trader))[:50], ensure_ascii=False)


def market(office: Office, minutes: int = 120) -> str:
    """Recent PF_XBTUSD 1-minute bars and the quote (bid/ask/mark/funding) -- to check a trader's claims."""
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
