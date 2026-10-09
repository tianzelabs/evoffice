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
# Pacing on the user's ChatGPT plan. The limits are the ACCOUNT's -- shared with the user's own
# Codex use -- so the manager keeps the account's weekly use under WEEKLY_CEILING of the week
# elapsed so far, leaving the rest to the user, and steps back as the user uses more.
WEEKLY_CEILING = float(os.environ.get("MANAGER_WEEKLY_CEILING", "0.6"))
FAST_S, NORMAL_S, SLOW_S, CRAWL_S = 15 * 60, 60 * 60, 2 * 3600, 4 * 3600
FIVE_HOUR_PAUSE = 85.0
WEEKLY_FLOOR = 0.10                    # always allow the account's week to reach 10%
QUIET = {"agent_state", "spend"}
# what wakes the manager besides the boss and messages to it; only when tokens are free
TRADER_NEWS = {"evaluation", "close", "version", "fire", "say", "meeting", "alert", "level"} if BACKEND == "codex" else {"meeting"}

CODEX_DUTIES = """
How the boss wants you to spend your time (it is cheap now -- use it):
1. WATCH THE MARKET. Every wake, pull data (`office market 10080` = the last 7 days of
   1-minute BTC bars, JSON) into your workspace and look at what the market is doing
   now: volatility regime, trend, time of day, anything unusual.
2. BUILD MATHEMATICAL MODELS. Keep your own models in your workspace and improve them
   over time -- e.g. a volatility forecast (HAR-RV / GARCH-style), regime detection,
   the expected move net of the 8 bps round trip by horizon and time of day, simple
   direction tests done properly (walk-forward, costs in). python3 with numpy, pandas
   and scikit-learn is installed. Save scripts and results; record what you learned in
   your notes so the next wake builds on it.
3. TALK STRATEGY WITH THE TRADERS. Bring them what your models show -- hypotheses worth
   testing, a horizon or exit rule they have not tried, a regime that matters -- and
   discuss theirs. Be a colleague with ideas and data, not a referee asking for
   timestamps. Disagree with numbers when they are wrong.
4. KEEP THEM TRADING SMALL. A frozen hypothesis tested with a few small live paper
   trades (0.005 BTC) produces evidence nothing else can: the future is data nobody has
   seen. Encourage that over endless argument on visible data.
5. THE DAILY STAND-UP (a `meeting` event): you chair it at the meeting table. Open it
   with the market picture from your models (say it to everyone); when the traders have
   reported, close with a 3-5 line summary addressed to the boss: what the market is
   doing, what your models say, what each trader changed and what the evidence shows.
6. MARKET ALERTS (an `alert` event): look at the move with your models and tell the
   traders, in one message to everyone, what it means and what is worth watching.

Each message to a trader wakes it and spends its own budget ($0.30/day). Put
everything for one trader into one message; the office lets you message the same
trader at most once an hour (add --urgent only when it truly cannot wait).
If you have no name yet, choose one: `office name "<your name>"`.
"""

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
        "CAREERS (XP from validated improvement): " + ops.progress(office)[:2000],
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
        r = subprocess.run(cmd, input=self.system + CODEX_DUTIES + CODEX_ADDENDUM + "\n\n" + prompt, capture_output=True,
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
                  "limits": self.codex_limits() if BACKEND == "codex" else None,
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

    # ---------- pacing on the plan's limits ----------
    def codex_limits(self) -> dict | None:
        """The newest rate_limits Codex wrote into its session files (exec --json does not report them)."""
        home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "sessions"
        files = sorted(home.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime) if home.exists() else []
        for f in reversed(files[-5:]):
            last = None
            for line in f.read_text().splitlines():
                if '"rate_limits"' in line:
                    last = line
            if last:
                def find(o):
                    if isinstance(o, dict):
                        if "rate_limits" in o and isinstance(o["rate_limits"], dict):
                            return o["rate_limits"]
                        for v in o.values():
                            r = find(v)
                            if r:
                                return r
                    return None
                return find(json.loads(last))
        return None

    def pace(self) -> tuple[int, str]:
        """Seconds until the next heartbeat, and why. Messages and trader news still wake it sooner."""
        lim = self.codex_limits() if BACKEND == "codex" else None
        if not lim:
            return HEARTBEAT_S, "no limit data: default heartbeat"
        p, w = lim.get("primary") or {}, lim.get("secondary") or {}
        if p.get("used_percent", 0) >= FIVE_HOUR_PAUSE:
            wait = max(600, int(p.get("resets_at", time.time() + 3600) - time.time()))
            return wait, f"5-hour window {p['used_percent']}% used: pausing until it resets"
        mins = w.get("window_minutes") or 10080
        elapsed = 1 - max(0.0, w.get("resets_at", time.time()) - time.time()) / (mins * 60)
        # pro-rata, with a floor: just after a weekly reset the pro-rata pace would be ~0 and starve the manager
        allowed = 100 * max(WEEKLY_CEILING * elapsed, WEEKLY_FLOOR)
        used = w.get("used_percent", 0.0)
        if used < 0.5 * allowed:
            return FAST_S, f"weekly {used}% used, pace allows {allowed:.0f}%: working often"
        if used < allowed:
            return NORMAL_S, f"weekly {used}% used of a {allowed:.0f}% pace: normal"
        if used < 1.2 * allowed:
            return SLOW_S, f"weekly {used}% used, over a {allowed:.0f}% pace: slowing"
        return CRAWL_S, f"weekly {used}% used, well over a {allowed:.0f}% pace: leaving the plan to the boss"

    def wake_reason(self) -> str | None:
        for e in ops.all_events(self.office, self.last_seen):
            if e["actor"] == self.me:
                continue
            if e["kind"] == "say" and (e["actor"] == "boss" or e["payload"].get("to") == self.me):
                return f"a message from {e['actor']}"
            if e["kind"] in TRADER_NEWS and not (e["kind"] == "meeting" and e["payload"].get("phase") == "end"):
                detail = e["payload"].get("text") or e["payload"].get("phase") or ""
                return f"{e['actor']}: {e['kind']} {detail}".strip()
        hb, why = self.pace()
        self.pace_note = why
        if time.time() - self.last_turn >= hb:
            return f"heartbeat (every {hb // 60} min; {why})"
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
