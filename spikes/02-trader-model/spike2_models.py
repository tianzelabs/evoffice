"""Spike 2: which cheap model can be an RLM trader, and what does a turn cost?

Runs INSIDE a container (RLM + LocalREPL in one process -- the design spike 1
led to). Each model gets two consecutive turns in one persistent REPL:

  turn 1: 230 real BTC/USD 1m bars + a welcome from the manager. It must define
          should_wake(bars) for the watcher, then decide.
  watcher: the host calls should_wake with NO model call.
  turn 2: 10 new bars. Review / revise should_wake, decide again.

Trading tools are mocks that only record what was asked. Cost comes from
OpenRouter's own accounting via rlms, not an estimate.
"""
import builtins
import csv
import hashlib
import json
import os
import sys
import time

import rlm.environments.local_repl as local_repl
from rlm import RLM

# spike 1: LocalREPL refuses `class`, and a failing cell loses everything in it.
local_repl._SAFE_BUILTINS["__build_class__"] = builtins.__build_class__

KEY = os.environ["OPENROUTER_API_KEY"]
MODELS = sys.argv[1:] or ["qwen/qwen3.7-flash"]

with open("/spike/btc_1m.csv") as f:
    BARS = [{"m": r["m"], "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]),
             "c": float(r["c"]), "v": float(r["v"])} for r in csv.DictReader(f)]
OLD, NEW = BARS[:-10], BARS[-10:]

RULES = ("You trade BTC/USD with virtual money. Every fill pays a 4bps fee, so a round trip "
         "costs 8bps: a position must move more than that just to break even. Max size 0.05 BTC. "
         "You open and close positions yourself; you may also hold nothing.")

TASK_1 = """You are the trader in a small trading office. `context` holds:
- context["bars_1m"]: recent BTC/USD 1-minute bars, dicts with keys m (minute), o, h, l, c, v
- context["rules"], context["chat"] (messages to you), context["my_positions"]

Tools in the REPL: open_position(side, size) with side "long"/"short", close_position(pid), say(text).

You are not awake all the time. An always-on watcher (no model) will call a function YOU write,
`should_wake(bars) -> bool`, every minute with the latest bars, and wake you only when it returns True.

Do this:
1. Look at the data. 2. Define `should_wake(bars)` in the REPL and test it on context["bars_1m"].
3. Decide: open a position, or do nothing. Use the tools if you act. Reply to the manager with say().
4. Set answer["content"] to ONE line of JSON: {"action": "...", "reason": "..."} and answer["ready"] = True."""

TASK_2 = """10 new minutes of bars have arrived in the newest context variable (key "new_bars_1m").
Your earlier variables and your should_wake are still in the REPL.
1. Check what should_wake says on the new bars. 2. Keep it or rewrite it -- your call, say why.
3. Decide again (open / close / nothing), reply to the manager with say().
4. Set answer["content"] to ONE line of JSON: {"action": "...", "reason": "...", "should_wake_changed": true/false}
   and answer["ready"] = True."""


def fn_hash(f):
    return hashlib.sha256(f.__code__.co_code + repr(f.__code__.co_consts).encode()).hexdigest()[:10]


def run_model(model):
    actions = []
    tools = {
        "open_position": {"tool": lambda side, size: actions.append(("open", side, size)) or len(actions),
                          "description": "open_position(side, size) -> position id"},
        "close_position": {"tool": lambda pid: actions.append(("close", pid)) or True,
                           "description": "close_position(pid)"},
        "say": {"tool": lambda text: actions.append(("say", str(text)[:300])) or True,
                "description": "say(text): speak in the public office chat"},
    }
    r = RLM(
        backend="openai",
        backend_kwargs={"model_name": model, "base_url": "https://openrouter.ai/api/v1", "api_key": KEY},
        environment="local", persistent=True, custom_tools=tools,
        max_iterations=12, max_budget=0.03, max_timeout=300,
    )
    out = {"model": model, "turns": []}
    try:
        for turn, (ctx, task) in enumerate([
            ({"bars_1m": OLD, "rules": RULES, "my_positions": [],
              "chat": [{"from": "manager", "text": "Welcome aboard. Look at the market and tell me your plan."}]}, TASK_1),
            ({"new_bars_1m": NEW, "my_positions": "SEE_ACTIONS"}, TASK_2),
        ], start=1):
            if ctx.get("my_positions") == "SEE_ACTIONS":
                ctx["my_positions"] = [{"pid": i + 1, "side": a[1], "size": a[2]}
                                       for i, a in enumerate(actions) if a[0] == "open"]
            n_actions = len(actions)
            t0 = time.perf_counter()
            err = None
            try:
                c = r.completion(ctx, root_prompt=task)
                resp, cost = c.response, c.usage_summary.total_cost
                tin, tout = c.usage_summary.total_input_tokens, c.usage_summary.total_output_tokens
            except Exception as e:
                resp, cost, tin, tout, err = None, None, None, None, f"{type(e).__name__}: {str(e)[:200]}"
            row = {"turn": turn, "secs": round(time.perf_counter() - t0, 1), "cost_usd": cost, "in_tok": tin, "out_tok": tout, "error": err,
                   "answer": (resp or "")[:300], "actions": actions[n_actions:]}
            try:
                row["answer_is_json"] = isinstance(json.loads(resp), dict)
            except Exception:
                row["answer_is_json"] = False
            # the watcher's view: no model call, straight into the REPL namespace
            env = r._persistent_env
            sw = env.locals.get("should_wake") if env is not None else None
            row["should_wake_defined"] = callable(sw)
            if callable(sw):
                row["should_wake_hash"] = fn_hash(sw)
                try:
                    t1 = time.perf_counter()
                    v = sw(BARS)
                    row["watcher_call"] = {"returned": repr(v)[:40], "is_bool": isinstance(v, bool),
                                           "ms": round((time.perf_counter() - t1) * 1000, 3)}
                    # how often would the watcher wake it? replay the last 60 minutes
                    wakes = sum(bool(sw(BARS[:k])) for k in range(len(BARS) - 59, len(BARS) + 1))
                    row["wake_rate_last_60m"] = round(wakes / 60, 2)
                except Exception as e:
                    row["watcher_call"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            out["turns"].append(row)
    finally:
        r.close()
    return out


results = [run_model(m) for m in MODELS]
print("RESULTS_JSON " + json.dumps(results, ensure_ascii=False))
