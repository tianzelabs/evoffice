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
from agents.common.hours import on_duty           # noqa: E402
from agents.manager import ops                    # noqa: E402

HERE = Path(__file__).parent
BACKEND = os.environ.get("MANAGER_BACKEND", "codex")
MODEL = os.environ.get("MANAGER_MODEL", "" if BACKEND == "codex" else "anthropic/claude-sonnet-5.5")
STATE = Path(os.path.expanduser(os.environ.get("MANAGER_STATE", "~/pixel-office/manager-state")))
HEARTBEAT_S = int(os.environ.get("MANAGER_HEARTBEAT_S", "3600" if BACKEND == "codex" else str(6 * 3600)))
MIN_GAP_S = int(os.environ.get("MANAGER_MIN_GAP_S", "300" if BACKEND == "codex" else "60"))
CODEX_TIMEOUT_S = 2700             # a wake may now run several trader tasks of a few minutes each
# Pacing on the user's ChatGPT plan. The limits are the ACCOUNT's -- shared with the user's own
# Codex use -- so the manager keeps the account's weekly use under WEEKLY_CEILING of the week
# elapsed so far, leaving the rest to the user, and steps back as the user uses more.
WEEKLY_CEILING = float(os.environ.get("MANAGER_WEEKLY_CEILING", "0.6"))
FAST_S, NORMAL_S, SLOW_S, CRAWL_S = 15 * 60, 60 * 60, 2 * 3600, 4 * 3600
FIVE_HOUR_PAUSE = 85.0
WEEKLY_FLOOR = 0.10                    # always allow the account's week to reach 10%
QUIET = {"agent_state", "spend", "backtest"}     # backtests are counted in the briefing, not listed
# what wakes the manager besides the boss and messages to it; only when tokens are free
# The trader only acts on the manager's tasks now, so its versions/evaluations no longer wake the manager
# (it caused them). What does: the trader's should_wake trigger, a backstop close, the boss, meetings, alerts.
TRADER_NEWS = {"trigger", "close", "fire", "say", "meeting", "alert"} if BACKEND == "codex" else {"meeting"}

CODEX_DUTIES = """
YOUR OBJECTIVE, set by the boss: TURN THE MINUS INTO A PLUS. Every number so far is
negative after fees. The office tracks a ladder, from the record, in your briefing and
in `office objective`:
  1. a candidate net-positive on BOTH train and recent backtests (>= 20 trades each)
  2. a held-out evaluation net-positive per trade
  3. a held-out 95% interval entirely above zero
  4. >= 30 live paper trades, net positive after fees and funding
Climb it in order; report which rung you are on and your best number on the next one
at every stand-up. Everything below is in service of this.

HOW THE OFFICE WORKS NOW (the boss's design, 2026-10-10): YOU are the strategist and the
only one who decides. There is one trader. It does not act on its own: it is your hands
and your laboratory -- an RLM agent on a cheap model with a persistent Python REPL that
keeps every object between tasks. You drive it with

    office task <trader-id> "<what to do>"

Each task is one turn of the trader in its REPL; the command waits and prints the result
(a few seconds to a few minutes -- let it finish). Find the trader's id with
`office employees`. The trader has $0.50/day of model budget; a task costs roughly
$0.003-0.03, so tens of tasks a day are fine, hundreds are not.

What to use it for:
- RESEARCH IN THE SHARED REPL: have it load data, fit and keep models, run backtest(code) on
  'train' and 'recent' data, and keep results as named objects you can build on in the
  next task. Its REPL is where the office's strategy lives (the strategy version is
  measured from it), so what you decide must end up defined there.
- THE EXAM: only the trader can submit evaluate(code) (60 held-out days, 5 tries a day,
  broken code refused without spending a try). Send the best candidate when it has
  survived backtests on both 'train' and 'recent'.
- TRADING: tell it exactly what to open, close or place. For a maker entry use
  place_order(..., price="best"): it joins the bid (buy) or ask (sell) as the book is when
  the order arrives. A price read earlier goes stale -- two of your first three entries
  were rejected that way. A resting order fills only when the market trades THROUGH it,
  so an order at the best price with a 15-minute TTL often expires unfilled. Small live paper trades are
  cheap experiments with virtual money and the only data nobody has seen -- use them.
- TRIGGERS: have it define should_wake(bars). The office runs it every minute without a
  model; when it fires, YOU are woken (a `trigger` event, at most every 30 min) and decide
  what the trader does.

ONE SHARED REPL (the boss's rule): the office has a single persistent Python REPL, and
you and the trader both work in it. `office repl -f script.py` (or `office repl "code"`)
runs your code there, free -- no model involved -- and prints its output; print() what you
want to see. It holds the trader's live facts (bars_1m, price_now, positions_open,
my_closed, my_evaluations, ...) and tools (backtest(code, data, days), place_order,
open_position, close_position, evaluate -- acting as the trader's seat). Put your data,
models, candidate strategies and results THERE, as named objects, so the trader's tasks
and your next wake build on the same state; the strategy version is measured from it.
Do not overwrite the trader's objects without saying so. Your Codex workspace is only
for scratch files. Do heavy computation yourself in the shared REPL; give the trader
tasks for what needs a model's judgement or many steps of exploration.

What the boss judges: whether the office keeps changing how it trades and can show
whether each change helped -- ideas tested per day, live trades, held-out results --
and whether anything starts to pay after fees (10 bps taker round trip, 4 bps
maker/maker). Not how carefully one idea was audited: do not spend tasks on process
proofs, timestamp reconciliations or control tests.

THE DAILY STAND-UP (a `meeting` event): give the boss, in the chat, 3-5 lines: what the
market is doing, what you tested and what it showed, what is live, what is next.
MARKET ALERTS (an `alert` event): decide whether the trader should act, and task it.

Office hours are 08:00-24:00 Budapest; you are not woken outside them except by the boss.
Chat (`office say`) is for the boss and the record; it does not wake the trader.
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
    every = ops.all_events(office, since)
    evs = [e for e in every if e["kind"] not in QUIET]
    tests: dict[str, int] = {}
    for e in every:
        if e["kind"] == "backtest":
            tests[e["actor"]] = tests.get(e["actor"], 0) + 1
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
        "", "YOUR OBJECTIVE (the boss's: minus -> plus), computed by the office: "
        + json.dumps(office.get("/objective"), ensure_ascii=False),
        "RESEARCH BACKTESTS SINCE YOUR LAST WAKE: " + (json.dumps(tests) if tests else "none"),
        "LEADERBOARD: " + ops.leaderboard(office)[:3000],
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
                if not on_duty() and not reason.startswith("a message from boss"):
                    continue                                 # office hours: only the boss gets an answer at night
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
