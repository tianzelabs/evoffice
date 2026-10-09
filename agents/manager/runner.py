"""The manager's process. Two interchangeable brains, picked by MANAGER_BACKEND:

- `codex` (default): `codex exec` on the user's ChatGPT subscription -- no
  per-token cost, so the manager wakes more often and digs deeper. Its tools are
  the `office` command in its shell, and it may keep analysis scripts in a
  persistent workspace. It runs inside a container holding only the manager's
  token: Codex has a shell, and on the host that shell could read every token
  and the database -- the wall would be gone.
- `langchain`: a LangChain 1.x agent through the office's /llm gateway, paid
  per token under the $0.20/day budget. Kept as the fallback and for evals.

Both get the same briefing of what changed since the last wake, and both log
every turn to turns.jsonl for evals later.

    python -m agents.manager.runner                   # serve
    python -m agents.manager.runner --dry-run [MODEL] # one turn, writes recorded not taken
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.common.office_client import Office   # noqa: E402
from agents.manager import ops                    # noqa: E402

HERE = Path(__file__).parent
BACKEND = os.environ.get("MANAGER_BACKEND", "codex")
MODEL = os.environ.get("MANAGER_MODEL", "" if BACKEND == "codex" else "anthropic/claude-sonnet-5.5")
STATE = Path(os.path.expanduser(os.environ.get("MANAGER_STATE", "~/pixel-office/manager-state")))
HEARTBEAT_S = int(os.environ.get("MANAGER_HEARTBEAT_S", "3600" if BACKEND == "codex" else str(6 * 3600)))
MIN_GAP_S = int(os.environ.get("MANAGER_MIN_GAP_S", "300" if BACKEND == "codex" else "60"))
CODEX_TIMEOUT_S = 900
QUIET = {"agent_state", "spend"}
# what wakes the manager besides the boss and messages to it; only when tokens are free
TRADER_NEWS = {"evaluation", "close", "version", "fire"} if BACKEND == "codex" else set()

CODEX_ADDENDUM = """
Your tools: the `office` command in your shell -- run `office --help` first if
you are unsure. It is your only access to the office. Your working directory is
yours and persists between wake-ups: keep analysis scripts there (python3 with
numpy and pandas is installed), e.g. to check a trader's claims against
`office market`. Do not try to reach other services or read files outside it.
Finish with a one-line summary of what you did as your final message.
"""


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def briefing(office: Office, since: int, notes: str) -> str:
    evs = [e for e in ops.all_events(office, since) if e["kind"] not in QUIET]
    lines = []
    for e in evs[-120:]:
        p, t = e["payload"], e["ts"][11:19]
        if e["kind"] == "say":
            lines.append(f"{t} {e['actor']}{' -> ' + p['to'] if p.get('to') else ''}: {p['text']}")
        elif e["kind"] == "turn":
            lines.append(f"{t} {e['actor']} finished a turn: {p.get('summary') or p.get('error')}")
        elif e["kind"] == "wake":
            lines.append(f"{t} {e['actor']} woke: {'; '.join(p.get('reasons', []))}")
        else:
            lines.append(f"{t} {e['actor']} {e['kind']}: {json.dumps(p, ensure_ascii=False)[:400]}")
    return "\n".join([
        f"Office time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "", "WHAT HAPPENED SINCE YOUR LAST WAKE (oldest first):", *(lines or ["(nothing)"]),
        "", "LEADERBOARD: " + ops.leaderboard(office)[:3000],
        "BUDGETS TODAY: " + json.dumps(office.get("/budget")),
        "", "YOUR NOTES FROM LAST TIME: " + (notes or "(none)"),
    ])


class Manager:
    def __init__(self, model: str = MODEL):
        self.office = Office()
        self.me = self.office.me()["id"]
        STATE.mkdir(parents=True, exist_ok=True)
        st = json.loads((STATE / "runner.json").read_text()) if (STATE / "runner.json").exists() else {}
        self.last_seen = st.get("last_seen", 0)
        self.last_turn = st.get("last_turn", 0.0)     # persisted: a restart is not a reason to wake
        self.asleep_said = False
        self.model = model
        self.system = (HERE / "prompt.md").read_text()
        if BACKEND == "langchain":
            from langchain.agents import create_agent
            from langchain_openai import ChatOpenAI
            from agents.manager.tools import make_tools
            llm = ChatOpenAI(model=model, base_url=self.office.url + "/llm/v1", api_key=self.office.token,
                             max_tokens=2048, timeout=180, max_retries=1)
            self.agent = create_agent(llm, tools=make_tools(self.office), system_prompt=self.system)
        else:
            self.workspace = STATE / "workspace"
            self.workspace.mkdir(exist_ok=True)

    # ---------- the two brains ----------
    def _think_langchain(self, prompt: str) -> dict:
        out = self.agent.invoke({"messages": [{"role": "user", "content": prompt}]}, {"recursion_limit": 24})
        msgs = out["messages"]
        final = msgs[-1].content if msgs else ""
        return {"summary": final if isinstance(final, str) else json.dumps(final),
                "tool_calls": [c["name"] for m in msgs for c in (getattr(m, "tool_calls", None) or [])],
                "transcript": [m.model_dump() for m in msgs]}

    def _think_codex(self, prompt: str) -> dict:
        last = STATE / "last_message.txt"
        last.unlink(missing_ok=True)
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
               "-C", str(self.workspace), "-o", str(last)] + (["-m", self.model] if self.model else []) + ["-"]
        r = subprocess.run(cmd, input=self.system + CODEX_ADDENDUM + "\n\n" + prompt, capture_output=True,
                           text=True, timeout=CODEX_TIMEOUT_S)
        events, usage, commands = [], {}, []
        for line in r.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            events.append(ev)
            u = ev.get("usage") or (ev.get("msg") or {}).get("usage")
            if isinstance(u, dict):
                for k, v in u.items():
                    if isinstance(v, (int, float)):
                        usage[k] = usage.get(k, 0) + v
            item = ev.get("item") or {}
            if ev.get("type") == "item.completed" and item.get("type") == "command_execution":
                commands.append(str(item.get("command", ""))[:160])
        if r.returncode != 0 and not last.exists():
            raise RuntimeError(f"codex exited {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
        return {"summary": last.read_text().strip() if last.exists() else "", "tool_calls": commands,
                "usage": usage, "transcript": events}

    def turn(self, reason: str, report: bool = True) -> dict:
        self.last_turn = time.time()
        evs = ops.all_events(self.office, self.last_seen)
        mark = evs[-1]["id"] if evs else self.last_seen
        prompt = f"You were woken by: {reason}\n\n" + briefing(self.office, self.last_seen, ops.read_notes())
        if report:
            self.office.report("agent_state", {"state": "thinking"})
        t0 = time.perf_counter()
        err, out = None, {"summary": "", "tool_calls": [], "transcript": []}
        try:
            out = self._think_codex(prompt) if BACKEND == "codex" else self._think_langchain(prompt)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:400]}"
            traceback.print_exc()
        cost = sum(e["payload"].get("cost", 0.0) for e in ops.all_events(self.office, mark)
                   if e["kind"] == "spend" and e["actor"] == self.me)
        result = {"backend": BACKEND, "model": self.model or "codex default", "reason": reason,
                  "secs": round(time.perf_counter() - t0, 1), "cost": round(cost, 5), "usage": out.get("usage"),
                  "tool_calls": out["tool_calls"][:40], "summary": out["summary"][:800], "error": err}
        with open(STATE / "turns.jsonl", "a") as f:     # kept for evals (openevals) later
            f.write(json.dumps({**result, "prompt": prompt, "transcript": out["transcript"]},
                               ensure_ascii=False, default=str) + "\n")
        if report:
            self.office.report("turn", result)
            self.office.report("agent_state", {"state": "idle"})
            self.last_seen = mark
            (STATE / "runner.json").write_text(json.dumps({"last_seen": self.last_seen, "last_turn": self.last_turn}))
        return result

    def wake_reason(self) -> str | None:
        for e in ops.all_events(self.office, self.last_seen):
            if e["actor"] == self.me:
                continue
            if e["kind"] == "say" and (e["actor"] == "boss" or e["payload"].get("to") == self.me):
                return f"a message from {e['actor']}"
            if e["kind"] in TRADER_NEWS:
                return f"{e['actor']}: {e['kind']}"
        if time.time() - self.last_turn >= HEARTBEAT_S:
            return f"heartbeat (every {HEARTBEAT_S // 60} min)"
        return None

    def run(self):
        log(f"{self.me} up, backend {BACKEND}, model {self.model or 'codex default'}, heartbeat {HEARTBEAT_S}s")
        while True:
            time.sleep(60 - time.time() % 60 + 20)
            try:
                reason = self.wake_reason()
                if not reason or time.time() - self.last_turn < MIN_GAP_S:
                    continue
                if BACKEND == "langchain" and self.office.budget()["left_usd"] < 0.01:
                    # never silently: a message to the manager went unanswered for 40 min this way
                    if not self.asleep_said:
                        self.office.report("agent_state", {"state": "asleep", "why": f"model budget spent; missed: {reason}"})
                        self.asleep_said = True
                    continue
                self.asleep_said = False
                r = self.turn(reason)
                log(f"turn done in {r['secs']}s: {r['summary'][:150]!r} {r['error'] or ''}")
            except Exception as e:
                log("loop error:", type(e).__name__, str(e)[:300])
                traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        os.environ["OFFICE_DRY_RUN"] = "1"
        ops.DRY = True
        dry = STATE / "dry_actions.jsonl"
        dry.unlink(missing_ok=True)
        m = Manager(model=sys.argv[2] if len(sys.argv) > 2 else MODEL)
        r = m.turn("the harness is checking the manager (dry run): review the office as you normally would", report=False)
        taken = [json.loads(l) for l in dry.read_text().splitlines()] if dry.exists() else []
        print("RESULT " + json.dumps({**r, "taken": taken}, ensure_ascii=False))
    else:
        Manager().run()
