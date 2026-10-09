"""The manager's tools: what a LangChain agent can do in the office.

Each is a thin wrapper over an office route the manager's token may call. There
is deliberately no tool for anything the office does not let a manager do --
the absence of a route is the limit, not a sentence in the prompt.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain.tools import tool

from agents.common.office_client import Office, Refused


def _all_events(office: Office, since: int = 0) -> list[dict]:
    out = []
    while True:
        evs = office.events(since)
        if not evs:
            return out
        out += evs
        since = evs[-1]["id"]


def make_tools(office: Office, notes_path: Path):
    def safe(fn):
        try:
            return fn()
        except Refused as e:
            return {"error": str(e)}

    @tool
    def say(text: str, to: str | None = None) -> str:
        """Speak in the office's public chat. `to` names who it is addressed to (e.g. 'trader-1', 'boss'), or None for everyone."""
        r = safe(lambda: office.say(text[:2000], to))
        return "said" if "error" not in r else r["error"]

    @tool
    def read_recent_chat(n: int = 30) -> str:
        """The last n chat messages, oldest first."""
        says = [e for e in _all_events(office) if e["kind"] == "say"][-max(1, min(n, 100)):]
        return json.dumps([{"ts": e["ts"][:19], "from": e["actor"], "to": e["payload"].get("to"),
                            "text": e["payload"]["text"]} for e in says], ensure_ascii=False)

    @tool
    def leaderboard() -> str:
        """Standings per trader and per strategy version (net of fees)."""
        return json.dumps(safe(lambda: office.get("/leaderboard")), ensure_ascii=False)

    @tool
    def employees() -> str:
        """Everyone employed or fired, with each trader's current parameters."""
        return json.dumps(safe(lambda: office.get("/employees")), ensure_ascii=False)

    @tool
    def trader_activity(trader: str, n: int = 10) -> str:
        """A trader's recent turns (with its own summaries), strategy versions, held-out evaluations, and what woke it in the last 24 h."""
        evs = [e for e in _all_events(office) if e["actor"] == trader]
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        wakes = Counter(r.split(" (")[0] for e in evs if e["kind"] == "wake" and e["ts"] >= day_ago
                        for r in e["payload"].get("reasons", []))
        pick = lambda kind, k: [{"ts": e["ts"][:19], **e["payload"]} for e in evs if e["kind"] == kind][-k:]
        return json.dumps({"turns": pick("turn", n), "versions": pick("version", n), "evaluations": pick("evaluation", n),
                           "wake_reasons_last_24h": dict(wakes)}, ensure_ascii=False)[:12000]

    @tool
    def trader_positions(trader: str) -> str:
        """A trader's positions, newest first (open ones have no closed_ts)."""
        return json.dumps(safe(lambda: office.positions(trader))[:30], ensure_ascii=False)

    @tool
    def set_trader_params(trader: str, reason: str, heartbeat_min: int | None = None,
                          max_size: float | None = None, max_hold_min: int | None = None) -> str:
        """Change a trader's parameters: heartbeat_min (5-720), max_size in BTC (0.001-0.05), max_hold_min (1-1440). Give the reason; it is shown in the chat."""
        r = safe(lambda: office.post(f"/employees/{trader}/params", {"heartbeat_min": heartbeat_min, "max_size": max_size,
                                                                     "max_hold_min": max_hold_min, "reason": reason}))
        return json.dumps(r, ensure_ascii=False)

    @tool
    def fire_trader(trader: str, reason: str) -> str:
        """Fire a trader. Its record stays; a new hire with an empty mind takes the seat. Use rarely, and say why."""
        return json.dumps(safe(lambda: office.post(f"/employees/{trader}/fire", {"reason": reason})), ensure_ascii=False)

    @tool
    def save_notes(text: str) -> str:
        """Replace your private notes for your next wake-up (a few lines: what you are watching, what you asked for)."""
        notes_path.write_text(text[:4000])
        return "saved"

    return [say, read_recent_chat, leaderboard, employees, trader_activity, trader_positions,
            set_trader_params, fire_trader, save_notes]
