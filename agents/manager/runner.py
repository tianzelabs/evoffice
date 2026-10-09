"""The manager's process: a LangChain agent woken by the boss, by messages to it,
and by a slow heartbeat.

Each wake builds a briefing of what changed since the last one -- chat, what the
traders did (turn summaries, strategy versions, evaluations, fills), the board,
budgets, its own notes -- and runs one agent invocation with the manager tools.
The model is reached through the office's /llm gateway with the manager's token;
the key and the $0.20/day budget live there.

    python -m agents.manager.runner                     # serve
    python -m agents.manager.runner --dry-run MODEL     # one turn, actions recorded not taken
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.common.office_client import Office            # noqa: E402
from agents.manager.tools import _all_events, make_tools  # noqa: E402

HERE = Path(__file__).parent
MODEL = os.environ.get("MANAGER_MODEL", "anthropic/claude-sonnet-5.5")
STATE = Path(os.path.expanduser(os.environ.get("MANAGER_STATE", "~/pixel-office/manager-state")))
HEARTBEAT_S = int(os.environ.get("MANAGER_HEARTBEAT_S", str(4 * 3600)))
MIN_GAP_S = 60
QUIET = {"agent_state", "spend"}


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def briefing(office: Office, since: int, notes: str) -> str:
    evs = [e for e in _all_events(office, since) if e["kind"] not in QUIET]
    lines = []
    for e in evs[-80:]:
        p, t = e["payload"], e["ts"][11:19]
        if e["kind"] == "say":
            lines.append(f"{t} {e['actor']}{' -> ' + p['to'] if p.get('to') else ''}: {p['text']}")
        elif e["kind"] == "turn":
            lines.append(f"{t} {e['actor']} finished a turn (${p.get('cost') or 0:.4f}): {p.get('summary') or p.get('error')}")
        elif e["kind"] == "wake":
            lines.append(f"{t} {e['actor']} woke: {'; '.join(p.get('reasons', []))}")
        else:
            lines.append(f"{t} {e['actor']} {e['kind']}: {json.dumps(p, ensure_ascii=False)[:400]}")
    board = office.get("/leaderboard")
    budgets = office.get("/budget")
    return "\n".join([
        f"Office time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "", "WHAT HAPPENED SINCE YOUR LAST WAKE (oldest first):", *(lines or ["(nothing)"]),
        "", "LEADERBOARD: " + json.dumps(board, ensure_ascii=False)[:3000],
        "BUDGETS TODAY: " + json.dumps(budgets),
        "", "YOUR NOTES FROM LAST TIME: " + (notes or "(none)"),
    ])


def dry_tools(real):
    """Same reads, recorded writes: for comparing models without three managers talking at once."""
    taken = []
    names = {"say", "set_trader_params", "fire_trader", "save_notes"}
    out = [t for t in real if t.name not in names]

    @tool
    def say(text: str, to: str | None = None) -> str:
        """Speak in the office's public chat. `to` names who it is addressed to, or None for everyone."""
        taken.append({"say": text, "to": to}); return "said"

    @tool
    def set_trader_params(trader: str, reason: str, heartbeat_min: int | None = None,
                          max_size: float | None = None, max_hold_min: int | None = None) -> str:
        """Change a trader's parameters: heartbeat_min (5-720), max_size in BTC (0.001-0.05), max_hold_min (1-1440)."""
        taken.append({"set_params": trader, "heartbeat_min": heartbeat_min, "max_size": max_size,
                      "max_hold_min": max_hold_min, "reason": reason}); return "ok"

    @tool
    def fire_trader(trader: str, reason: str) -> str:
        """Fire a trader. Its record stays; a new hire takes the seat."""
        taken.append({"fire": trader, "reason": reason}); return "ok"

    @tool
    def save_notes(text: str) -> str:
        """Replace your private notes for your next wake-up."""
        taken.append({"notes": text}); return "saved"
    return out + [say, set_trader_params, fire_trader, save_notes], taken


class Manager:
    def __init__(self, model: str = MODEL, dry_run: bool = False):
        self.office = Office()
        self.me = self.office.me()["id"]
        STATE.mkdir(parents=True, exist_ok=True)
        self.notes_path = STATE / "notes.txt"
        st = json.loads((STATE / "runner.json").read_text()) if (STATE / "runner.json").exists() else {}
        self.last_seen = st.get("last_seen", 0)
        self.last_turn = 0.0
        tools = make_tools(self.office, self.notes_path)
        self.taken = None
        if dry_run:
            tools, self.taken = dry_tools(tools)
        llm = ChatOpenAI(model=model, base_url=self.office.url + "/llm/v1", api_key=self.office.token,
                         max_tokens=2048, timeout=180, max_retries=1)
        self.model = model
        self.agent = create_agent(llm, tools=tools, system_prompt=(HERE / "prompt.md").read_text())

    def spent_since(self, event_id: int) -> float:
        return sum(e["payload"].get("cost", 0.0) for e in _all_events(self.office, event_id)
                   if e["kind"] == "spend" and e["actor"] == self.me)

    def turn(self, reason: str, report: bool = True) -> dict:
        self.last_turn = time.time()
        mark = (_all_events(self.office, self.last_seen) or [{"id": self.last_seen}])[-1]["id"]
        notes = self.notes_path.read_text() if self.notes_path.exists() else ""
        brief = briefing(self.office, self.last_seen, notes)
        if report:
            self.office.report("agent_state", {"state": "thinking"})
        t0 = time.perf_counter()
        err, final, msgs = None, "", []
        try:
            out = self.agent.invoke({"messages": [{"role": "user", "content": f"You were woken by: {reason}\n\n{brief}"}]},
                                    {"recursion_limit": 24})
            msgs = out["messages"]
            final = msgs[-1].content if msgs else ""
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:300]}"
            traceback.print_exc()
        cost = self.spent_since(mark)
        result = {"model": self.model, "reason": reason, "secs": round(time.perf_counter() - t0, 1), "cost": round(cost, 5),
                  "tool_calls": [c["name"] for m in msgs for c in (getattr(m, "tool_calls", None) or [])],
                  "summary": (final if isinstance(final, str) else json.dumps(final))[:600], "error": err}
        with open(STATE / "turns.jsonl", "a") as f:     # kept for evals (openevals) later
            f.write(json.dumps({**result, "briefing": brief, "taken": self.taken,
                                "messages": [m.model_dump() for m in msgs]}, ensure_ascii=False, default=str) + "\n")
        if report:
            self.office.report("turn", result)
            self.office.report("agent_state", {"state": "idle"})
            self.last_seen = mark
            (STATE / "runner.json").write_text(json.dumps({"last_seen": self.last_seen}))
        return result

    def wake_reason(self) -> str | None:
        evs = _all_events(self.office, self.last_seen)
        for e in evs:
            if e["kind"] == "say" and e["actor"] != self.me and (e["actor"] == "boss" or e["payload"].get("to") == self.me):
                return f"a message from {e['actor']}"
        if time.time() - self.last_turn >= HEARTBEAT_S:
            return f"heartbeat (every {HEARTBEAT_S // 3600} h)"
        return None

    def run(self):
        log(f"{self.me} up, model {self.model}, heartbeat {HEARTBEAT_S}s")
        while True:
            time.sleep(60 - time.time() % 60 + 20)
            try:
                reason = self.wake_reason()
                if not reason or time.time() - self.last_turn < MIN_GAP_S:
                    continue
                if self.office.budget()["left_usd"] < 0.01:
                    continue
                r = self.turn(reason)
                log(f"turn done in {r['secs']}s ${r['cost']}: {r['summary'][:150]!r}")
            except Exception as e:
                log("loop error:", type(e).__name__, str(e)[:300])
                traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--dry-run":
        m = Manager(model=sys.argv[2], dry_run=True)
        r = m.turn("the harness is comparing manager models (dry run): review the office as you normally would",
                   report=False)
        print("RESULT " + json.dumps({**r, "taken": m.taken}, ensure_ascii=False))
    else:
        Manager().run()
