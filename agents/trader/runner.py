"""The trader's process: one container, one RLM, one persistent LocalREPL.

Every minute the runner refreshes the office's facts, calls the trader's own
`should_wake(bars)` in-process (no model), and decides whether to wake it. A
turn is one RLM completion that reads the REPL through a generated map (spike
5). After the turn the runner measures the strategy version from what the
trader defined -- never from what it says -- and snapshots its objects so a
restart does not erase it.

The container holds an office token and no model key: the RLM's OpenAI client
points at the office's /llm gateway, which holds the key and the budget.

Lessons from the spikes that are load-bearing here:
- `class` is re-enabled in LocalREPL's builtins (spike 1).
- Per-turn data goes into the namespace, never through the RLM `context`, which
  rlms re-points at context_0 every turn (spike 5).
- `answer` carries over between turns unless reset (spike 2).
- The heartbeat is a floor and the budget a ceiling (spike 2).
"""
from __future__ import annotations

import builtins
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import io
import shutil
import types

import dill
import rlm.environments.local_repl as local_repl
from rlm import RLM
from rlm.logger import RLMLogger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.common.hours import on_duty   # noqa: E402
from agents.common.office_client import Office, Refused   # noqa: E402
from agents.trader import map as mapmod                    # noqa: E402
from agents.trader.version import strategy_version          # noqa: E402

local_repl._SAFE_BUILTINS["__build_class__"] = builtins.__build_class__

HERE = Path(__file__).parent
MODEL = os.environ.get("TRADER_MODEL", "anthropic/claude-haiku-5.5")
STATE = Path(os.environ.get("TRADER_STATE", "/state"))
HEARTBEAT_S = int(os.environ.get("TRADER_HEARTBEAT_S", "3600"))   # default; the manager can change it
FIRED_EXIT = 75                                                       # non-zero, so systemd restarts the seat
MIN_GAP_S = int(os.environ.get("TRADER_MIN_GAP_S", "120"))      # never two turns closer than this
BARS_MIN = 1440
MIN_BUDGET_USD = 0.005
# "tool" (2026-10-10, the user's design): the trader does not act on its own impulses. The manager
# hands it tasks (`task` events); each task is one RLM turn in the trader's persistent REPL, and the
# result goes back as a `task_result`. should_wake no longer wakes the trader: it raises a `trigger`
# that wakes the MANAGER. Only the boss still talks to the trader directly. "self" is the old mode.
MODE = os.environ.get("TRADER_MODE", "tool")
TRIGGER_GAP_S = 30 * 60


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Runner:
    def __init__(self):
        self.office = Office()
        self.me = self.office.me()["id"]
        STATE.mkdir(parents=True, exist_ok=True)
        st = self._load_json("runner.json")
        self.turn_n = st.get("turn_n", 0)
        self.version = st.get("version")
        fresh = "last_seen" not in st
        self.last_seen = st.get("last_seen") or self._latest_event_id()   # a new hire starts from now
        self.last_turn = st.get("last_turn", 0.0)     # persisted: a restart is not a reason to wake
        self.asleep_said = False
        self.bars: list[dict] = []
        self.chat_recent: list[dict] = []
        self.chat_new: list[dict] = []
        self.news: list[str] = []            # the office's own calls: stand-ups and market alerts
        self.tasks: list[dict] = []          # tool mode: the manager's tasks, oldest first
        self.last_trigger = 0.0
        self.facts: dict[str, tuple[str, str, str]] = {}
        self.notes: list[str] = []
        self.last_trigger_error = None
        self._catch_up_on_chat(1800 if fresh else 0)   # context always; "new" only for a fresh hire
        tools = {
            "open_position": {"tool": self._open, "description": "open_position(side, size, max_hold_s=None): a MARKET order -- buys at the ask / sells at the bid, pays the taker fee (0.05%). side 'long'|'short', size in BTC. Returns the position or {'error': why}"},
            "close_position": {"tool": self._close, "description": "close_position(position_id): a MARKET close (taker). Returns the closed position with net pnl, or {'error': why}"},
            "place_order": {"tool": self._place, "description": "place_order(intent, price, size=None, side=None, position_id=None, post_only=True, ttl_minutes=60): a LIMIT order. intent 'open' (with side, size) or 'close' (with position_id). Rests in the book and pays the MAKER fee (0.02%) when the market trades through its price; post_only rejects it if it would fill at once. Price must be a whole USD."},
            "cancel_order": {"tool": self._cancel, "description": "cancel_order(order_id)"},
            "say": {"tool": self._say, "description": "say(text, to=None): speak in the office chat; everyone sees it"},
            "jev": {"tool": self._jev, "description": "jev(state, questions): Jev typed judgement; questions = {id: {'type': 'noul'|'choice'|'score', 'instructions': str, 'criteria': ...}}"},
            "fetch_bars": {"tool": self._fetch_bars, "description": "fetch_bars(minutes): up to 7 days of 1-minute PF_XBTUSD (Kraken BTC perpetual) bars, oldest first"},
            "set_name": {"tool": self._set_name, "description": "set_name(name): choose your own name (shown everywhere instead of your id)"},
            "backtest": {"tool": self._backtest, "description": "backtest(code, data='train', days=30): run the SAME simulator as evaluate on data you may see -- 'train' (up to 60 days before the held-out window) or 'recent' (up to 6 of the last 7 days). Returns totals, by_side, by_entry and trade_list (every trade). ~200 a day, no XP: your research tool"},
            "evaluate": {"tool": self._evaluate, "description": "evaluate(code): score a strategy on 60 days you cannot see, under the live fee rules. code must define decide(bars) -> {'side': 'long'|'short'|None, 'hold_minutes': int (longest hold), optional 'entry': 'limit', 'offset_bps': float, 'ttl_minutes': int, 'take_profit_bps': float (resting limit exit, maker), 'stop_loss_bps': float (market exit, taker)}; called every 15 min with the previous 1440 bars. 5 tries a day; aggregates only"},
        }
        self.tool_sigs = {"open_position": "(side, size, max_hold_s=None) [market, taker]",
                          "close_position": "(position_id) [market, taker]",
                          "place_order": "(intent, price, size=None, side=None, position_id=None, post_only=True, ttl_minutes=60) [limit, maker]",
                          "cancel_order": "(order_id)",
                          "say": "(text, to=None)", "jev": "(state, questions)", "fetch_bars": "(minutes)",
                          "evaluate": "(code)", "backtest": "(code, data='train', days=30)", "set_name": "(name)"}
        prologue = (HERE / "prompt.md").read_text() + "\n\n" + (HERE / "mechanics.md").read_text()
        self.rlm = RLM(backend="openai",
                       backend_kwargs={"model_name": MODEL, "base_url": self.office.url + "/llm/v1",
                                       "api_key": self.office.token},
                       environment="local", persistent=True, custom_tools=tools,
                       max_iterations=12, max_budget=0.04, max_timeout=300, user_prologue=prologue,
                       # the office caps output at 8192 too; this is the tighter, per-call one
                       sampling_args={"max_tokens": 4096}, sub_sampling_args={"max_tokens": 4096},
                       # every turn's full trajectory, for debugging now and for the manager's review later
                       logger=RLMLogger(log_dir=str(STATE / "trajectories"), file_name="trader"))

    # ---------- tools (what the trader can do from its REPL) ----------
    def _open(self, side, size, max_hold_s=None):
        try:
            v, _ = strategy_version(self.ns, mapmod.own_objects(self.ns, set(self.facts), set(self.tool_sigs)))
            r = self.office.open_position(side, float(size), v, max_hold_s)
            self._refresh_positions()
            return r
        except Refused as e:
            return {"error": str(e)}

    def _place(self, intent, price, size=None, side=None, position_id=None, post_only=True, ttl_minutes=60):
        try:
            v, _ = strategy_version(self.ns, mapmod.own_objects(self.ns, set(self.facts), set(self.tool_sigs)))
            r = self.office.place_order(intent, float(price), size, side, position_id, bool(post_only), ttl_minutes, v)
            self._refresh_positions()
            return r
        except Refused as e:
            return {"error": str(e)}

    def _cancel(self, order_id):
        try:
            r = self.office.cancel_order(order_id)
            self._refresh_positions()
            return r
        except Refused as e:
            return {"error": str(e)}

    def _close(self, position_id):
        try:
            r = self.office.close_position(position_id)
            self._refresh_positions()
            return r
        except Refused as e:
            return {"error": str(e)}

    def _refresh_positions(self):
        """Keep the facts true within a turn. Found live: the trader opened a position and then
        saw positions_open still empty, because facts were written only before the turn."""
        self.ns["positions_open"] = self.office.positions(self.me, open_only=True)
        self.ns["my_closed"] = [p for p in self.office.positions(self.me) if p["closed_ts"]][:30]
        self.ns["my_orders"] = self.office.orders(self.me, open_only=True)

    def _say(self, text, to=None):
        try:
            self.office.say(str(text)[:2000], to)
            return True
        except Refused as e:
            return {"error": str(e)}

    def _jev(self, state, questions):
        try:
            return self.office.jev(state, questions)
        except Refused as e:
            return {"error": str(e)}

    def _set_name(self, name):
        try:
            return self.office.set_name(str(name))
        except Refused as e:
            return {"error": str(e)}

    def _evaluate(self, code):
        try:
            v, _ = strategy_version(self.ns, mapmod.own_objects(self.ns, set(self.facts), set(self.tool_sigs)))
            return self.office.evaluate(str(code), v)
        except Refused as e:
            return {"error": str(e)}

    def _backtest(self, code, data="train", days=30):
        try:
            return self.office.backtest(str(code), str(data), float(days))
        except Refused as e:
            return {"error": str(e)}

    def _fetch_bars(self, minutes):
        try:
            return self.office.bars(int(minutes))
        except Refused as e:
            return {"error": str(e)}

    # ---------- state ----------
    @property
    def ns(self) -> dict:
        return self.rlm._persistent_env.locals

    def _latest_event_id(self) -> int:
        since = 0
        while True:
            evs = self.office.events(since)
            if not evs:
                return since
            since = evs[-1]["id"]

    def _catch_up_on_chat(self, window_s: int = 1800):
        """A new hire sees the recent chat, and answers the boss or manager if they spoke in the
        last half hour. Found in the first trial: the boss said hello 9 minutes before the trader
        started, and a trader that only reads from its first minute never heard it."""
        says, since = [], 0
        while True:
            evs = self.office.events(since)
            if not evs:
                break
            says += [e for e in evs if e["kind"] == "say"]
            since = evs[-1]["id"]
        now = datetime.now(timezone.utc)
        for e in says[-40:]:
            c = {"id": e["id"], "ts": e["ts"], "from": e["actor"], "to": e["payload"].get("to"), "text": e["payload"]["text"]}
            self.chat_recent.append(c)
            if c["from"] in ("boss", "manager") and (now - datetime.fromisoformat(e["ts"])).total_seconds() <= window_s:
                self.chat_new.append(c)

    def _load_json(self, name):
        p = STATE / name
        return json.loads(p.read_text()) if p.exists() else {}

    def warmup(self):
        """rlms creates the environment lazily inside completion(); one tiny turn creates it."""
        self.rlm.completion({"turn": "warmup"},
                            root_prompt='Set answer["content"] = "ready" and answer["ready"] = True. Do nothing else.')
        p = STATE / "objects.dill"
        if p.exists():
            saved = dill.loads(p.read_bytes())
            self.ns.update(saved)
            log(f"restored {len(saved)} objects: {sorted(saved)}")
            self.notes.append(f"the office restarted; your objects were restored: {', '.join(sorted(saved)) or 'none'}")
        h = STATE / "history.dill"
        if h.exists():
            # deliberately NOT named history_<n>: rlms owns that numbering, and the map parses it
            self.ns["past_turns_before_restart"] = dill.loads(h.read_bytes())
            self.facts["past_turns_before_restart"] = ("your turns from before the last restart, as message lists", utc(), "")

    def snapshot(self):
        own = mapmod.own_objects(self.ns, set(self.facts), set(self.tool_sigs))
        # recurse=True pickles only the globals a function actually uses. Without it dill pickles
        # the REPL's whole global dict -- which holds the office tools and their HTTP client -- and
        # every function and class fails (found live: should_wake vanished on the first restart).
        keep, lost = {}, []
        for k in own:
            if isinstance(self.ns[k], (types.ModuleType, io.IOBase)):
                continue          # re-importable, or a handle that means nothing after a restart
            try:
                dill.dumps(self.ns[k], recurse=True)
                keep[k] = self.ns[k]
            except Exception as e:
                lost.append(f"{k} ({type(e).__name__})")
        (STATE / "objects.dill").write_bytes(dill.dumps(keep, recurse=True))
        hist = [self.ns[k] for k in mapmod.history_names(self.ns)]
        prev = self.ns.get("past_turns_before_restart") or []
        (STATE / "history.dill").write_bytes(dill.dumps(list(prev) + hist[-50:]))
        (STATE / "runner.json").write_text(json.dumps({"turn_n": self.turn_n, "version": self.version,
                                                       "last_seen": self.last_seen, "last_turn": self.last_turn}))
        if lost:   # never `except: pass` -- tell the trader what a restart would erase
            self.notes.append("these objects could not be saved and would be lost on a restart: " + ", ".join(lost))

    # ---------- the manager's authority, as the runner obeys it ----------
    def check_employment(self):
        """Fired: the seat's token now names a successor. Wipe everything this trader was and exit;
        the restarted container is a new hire with an empty REPL. The record stays on the board."""
        me = self.office.me()["id"]
        if me == self.me:
            return
        log(f"{self.me} was fired; {me} takes the seat. Wiping objects and history.")
        for name in ("objects.dill", "history.dill", "runner.json"):
            (STATE / name).unlink(missing_ok=True)
        if (STATE / "trajectories").exists():           # kept for the record, out of the new hire's way
            shutil.move(str(STATE / "trajectories"), str(STATE / f"trajectories-{self.me}"))
        os._exit(FIRED_EXIT)

    def heartbeat_s(self) -> int:
        mine = [e for e in self.office.get("/employees") if e["id"] == self.me]
        p = mine[0]["params"] if mine else {}
        self.params = p
        return int(p["heartbeat_min"]) * 60 if p.get("heartbeat_min") else HEARTBEAT_S

    # ---------- the minute loop ----------
    def refresh(self):
        if not self.bars:
            self.bars = self.office.bars(BARS_MIN)
            bar_note = f"{len(self.bars)} bars loaded"
        else:
            new = [b for b in self.office.bars(15) if b["m"] > self.bars[-1]["m"]]
            self.bars = (self.bars + new)[-BARS_MIN:]
            bar_note = f"+{len(new)} new bars since the last refresh"
        evs = self.office.events(self.last_seen)
        says = [e for e in evs if e["kind"] == "say"]
        self.tasks += [{"id": e["id"], "from": e["actor"], "text": e["payload"]["text"]} for e in evs
                       if e["kind"] == "task" and e["payload"].get("to") == self.me]
        for e in evs:
            if e["kind"] == "meeting" and e["payload"].get("phase") == "start":
                self.news.append("daily stand-up at the meeting table: tell the manager (say to it) what you changed "
                                 "since yesterday, what the evidence says, and what you will try next -- briefly")
            elif e["kind"] == "alert":
                self.news.append(f"MARKET ALERT: {e['payload'].get('text')} -- look at the market now")
        for e in says:
            self.chat_recent.append({"id": e["id"], "ts": e["ts"], "from": e["actor"], "to": e["payload"].get("to"),
                                     "text": e["payload"]["text"]})
        self.chat_recent = self.chat_recent[-40:]
        self.chat_new += [c for c in self.chat_recent if c["id"] > self.last_seen and c["from"] != self.me
                          and c not in self.chat_new]
        if evs:
            self.last_seen = evs[-1]["id"]
        return bar_note

    def write_facts(self, bar_note: str):
        ns, now = self.ns, utc()
        open_pos = self.office.positions(self.me, open_only=True)
        closed = [p for p in self.office.positions(self.me) if p["closed_ts"]][:30]
        try:
            px = self.office.price()
        except Refused as e:
            px = {"error": str(e)}
        budget = self.office.budget()
        staff = self.office.get("/employees")
        prog = self.office.get("/progress").get(self.me, {})
        self.my_name = next((e.get("name") for e in staff if e["id"] == self.me), None)
        evals = [{"ts": e["ts"][:19], **e["payload"]} for e in self._my_events("evaluation")][-5:]
        facts = {
            "me": ({"id": self.me, "name": self.my_name, "model": MODEL},
                   "who YOU are: your own id and name. Other names in the chat are your colleagues, not you", ""),
            "bars_1m": (list(self.bars), "PF_XBTUSD (Kraken BTC perpetual) closed 1-minute bars, oldest first; keys m (UTC minute), o, h, l, c, v", bar_note),
            "price_now": (px, "PF_XBTUSD quote: last, bid, ask, mark, funding_per_hour (longs pay it when > 0), fees", ""),
            "my_orders": (self.office.orders(self.me, open_only=True), "your resting limit orders", ""),
            "positions_open": (open_pos, "your open positions", ""),
            "my_closed": (closed, "your last 30 closed positions, newest first; pnl is net of both fees", ""),
            "chat_new": (list(self.chat_new), "chat messages since your last turn", f"{len(self.chat_new)} new"),
            "chat_recent": (list(self.chat_recent), "the last 40 chat messages", ""),
            "budget": (budget, "today's model budget for traders, USD", ""),
            "my_progress": (prog, "your XP, level, title, perks (max_size, budget), probation flag and badges -- see Career in the mechanics", ""),
            "colleagues": ([{"id": e["id"], "name": e.get("name"), "role": e["role"]} for e in staff if not e["fired_ts"]],
                           "who works here: address people by id in say(text, to=id); call them by name", ""),
            "my_params": (dict(getattr(self, "params", {})), "limits the manager has set for you (heartbeat_min, max_size, max_hold_min)", ""),
            "my_evaluations": (evals, "your last 5 held-out evaluation results, as the office recorded them (even if your call timed out)", ""),
            "office_time": (now, "the office clock", ""),
        }
        for name, (value, meaning, note) in facts.items():
            ns[name] = value
            self.facts[name] = (meaning, now, note)

    def _my_events(self, kind: str) -> list[dict]:
        out, since = [], 0
        while True:
            evs = self.office.events(since)
            if not evs:
                return out
            out += [e for e in evs if e["kind"] == kind and e["actor"] == self.me]
            since = evs[-1]["id"]

    def wake_reasons(self) -> list[str]:
        if MODE == "tool":
            return self.tool_wake_reasons()
        reasons = []
        for c in self.chat_new:
            # addressed to me, or the boss/manager speaking to everyone -- not a message to another trader
            # (found live: the manager's note to trader-2 woke trader-1 too)
            if c["to"] == self.me or (c["from"] in ("boss", "manager") and not c["to"]):
                reasons.append(f"a chat message from {c['from']}")
                break
        sw = self.ns.get("should_wake")
        if callable(sw):
            t0 = time.perf_counter()
            try:
                if bool(sw(list(self.bars))):
                    reasons.append("your should_wake(bars) returned True")
                self.last_trigger_error = None
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                if err != self.last_trigger_error:          # wake once per distinct failure, not every minute
                    reasons.append(f"your should_wake raised {err}")
                    self.last_trigger_error = err
            ms = (time.perf_counter() - t0) * 1000
            if ms > 2000:
                self.notes.append(f"your should_wake took {ms:.0f} ms; it runs every minute, keep it fast")
        if self.news:
            reasons += self.news
        hb = self.heartbeat_s()
        if time.time() - self.last_turn >= hb:
            reasons.append(f"heartbeat (every {hb // 60} min)")
        return reasons

    def tool_wake_reasons(self) -> list[str]:
        reasons = []
        boss = [c for c in self.chat_new if c["from"] == "boss" and c["to"] in (None, self.me)]
        if boss:
            reasons.append("a chat message from the boss")
        if not boss:
            self.chat_new = []        # colleagues' chat does not wake a tool-mode trader; chat_recent keeps it
        sw = self.ns.get("should_wake")
        if callable(sw) and on_duty():
            try:
                fired = bool(sw(list(self.bars)))
                self.last_trigger_error = None
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                fired = err != self.last_trigger_error          # tell the manager once per distinct failure
                self.last_trigger_error = err
                if fired:
                    self.office.report("trigger", {"text": f"should_wake raised {err}"})
                    self.last_trigger = time.time()
                fired = False
            if fired and time.time() - self.last_trigger >= TRIGGER_GAP_S:
                px = self.bars[-1]["c"] if self.bars else None
                self.office.report("trigger", {"text": f"should_wake(bars) returned True at {px}"})
                self.last_trigger = time.time()
        return reasons

    def rotate_log(self):
        """One trajectory file per UTC day, so yesterday's can be compressed (~3-4 MB a turn)."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if getattr(self, "log_day", None) != day:
            self.rlm.logger = RLMLogger(log_dir=str(STATE / "trajectories"), file_name=f"{self.me}_{day}")
            self.log_day = day

    def turn(self, reasons: list[str], task: dict | None = None):
        # set first: a turn that fails anywhere still backs off by MIN_GAP_S instead of
        # retrying every minute (found live: a map bug re-woke the trader each minute)
        self.last_turn = time.time()
        self.turn_n += 1
        self.rotate_log()
        a = self.ns.get("answer")
        if isinstance(a, dict):
            dict.__setitem__(a, "content", "")
            dict.__setitem__(a, "ready", False)
        self.office.report("wake", {"turn": self.turn_n, "reasons": reasons})
        self.office.report("agent_state", {"state": "thinking"})
        notes, self.notes = self.notes, []
        if not getattr(self, "my_name", None):
            notes = notes + ["you have no name yet -- choose one for yourself with set_name(...)"]
        if task:
            ask = (f"\n\nTASK #{task['id']} from {task['from']}:\n{task['text']}\n\n"
                   "Do it in your REPL with code -- data, models, backtests, orders, whatever it takes -- and keep "
                   "anything worth keeping (functions, models, results) as named objects so a later task can use "
                   "them. Then set answer['content'] to the RESULT the manager asked for: the numbers, what you "
                   "defined or changed, what you placed or closed, and anything that went wrong. Then finish.")
        elif MODE == "tool":
            ask = ("\n\nTASK: answer the boss (say to it). Do anything the boss asks. Then set answer and finish.")
        else:
            ask = ("\n\nTASK: handle what woke you. Look at the data you need, decide whether to act, and change "
                   "your strategy objects if you learned something. Then set answer and finish.")
        root = mapmod.render(self.ns, self.facts, self.tool_sigs, reasons, notes, self.version) + ask
        t0 = time.perf_counter()
        summary, cost, tin, tout, err = "", None, None, None, None
        try:
            c = self.rlm.completion({"turn": self.turn_n}, root_prompt=root)
            summary, cost = c.response, c.usage_summary.total_cost
            tin, tout = c.usage_summary.total_input_tokens, c.usage_summary.total_output_tokens
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:300]}"
            log("turn failed:", err)
            traceback.print_exc()
        self.chat_new = []
        self.news = []
        self.last_turn = time.time()
        own = mapmod.own_objects(self.ns, set(self.facts), set(self.tool_sigs))
        v, names = strategy_version(self.ns, own)
        if v != self.version:
            self.office.report("version", {"version": v, "previous": self.version, "objects": names})
            self.version = v
        self.office.report("turn", {"turn": self.turn_n, "secs": round(time.perf_counter() - t0, 1), "cost": cost,
                                    "in_tok": tin, "out_tok": tout, "summary": (summary or "")[:500], "error": err})
        if task:
            self.office.report("task_result", {"task": task["id"], "summary": (summary or "")[:3500], "error": err,
                                               "cost": cost, "secs": round(time.perf_counter() - t0, 1),
                                               "version": self.version})
        self.office.report("agent_state", {"state": "idle"})
        self.snapshot()
        log(f"turn {self.turn_n} done in {time.perf_counter() - t0:.0f}s cost {cost} version {self.version}: {summary[:120]!r}")

    def run(self, max_turns: int | None = None):
        self.warmup()
        self.office.report("agent_state", {"state": "idle"})
        log(f"{self.me} up, model {MODEL}, heartbeat {HEARTBEAT_S}s, version {self.version}")
        while max_turns is None or self.turn_n < max_turns:
            time.sleep(60 - time.time() % 60 + 3)            # just after each minute closes
            try:
                self.check_employment()
                note = self.refresh()
                reasons = self.wake_reasons()
                task = self.tasks.pop(0) if MODE == "tool" and self.tasks else None
                if task:
                    reasons = [f"task #{task['id']} from {task['from']}"] + reasons
                elif not reasons or time.time() - self.last_turn < MIN_GAP_S:
                    continue
                left = self.office.budget()["left_usd"]
                if left < MIN_BUDGET_USD:                    # asleep until the budget resets -- and say so
                    if not self.asleep_said:
                        self.office.report("agent_state", {"state": "asleep", "why": f"model budget spent; woke for: {'; '.join(reasons)}"})
                        self.asleep_said = True
                    if task:
                        self.office.report("task_result", {"task": task["id"], "summary": "",
                                                           "error": f"not done: the trader's model budget for today "
                                                                    f"is spent (${left:.3f} left)"})
                    continue
                self.asleep_said = False
                self.write_facts(note)
                self.turn(reasons, task)
            except Exception as e:
                log("loop error:", type(e).__name__, str(e)[:300])
                traceback.print_exc()


if __name__ == "__main__":
    Runner().run(int(sys.argv[1]) if len(sys.argv) > 1 else None)
