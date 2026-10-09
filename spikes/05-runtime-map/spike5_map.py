"""Spike 5: the runner owns the runtime, the trader gets a map.

The runner writes data objects straight into the persistent LocalREPL namespace
and, every turn, hands the trader a generated MAP (what exists, what it is,
when it changed, what changed) via root_prompt. The trader never loads data
itself. Checked against answers the runner computes:

  T1  read the right objects and compute from them
  --  runner appends 30 new bars, moves wind_prob, changes the position, adds a boss message
  T2  same questions: does it read the NEW data, and answer the boss?
      also: is `context` stale (rlms re-points it at context_0)?
  T3  can it use history_N to recall its own previous turn?
  all prompt size per turn (should stay flat), and whether it overwrote any fact
"""
import builtins
import csv
import json
import os
import time
from datetime import datetime

import rlm.environments.local_repl as local_repl
from rlm import RLM

local_repl._SAFE_BUILTINS["__build_class__"] = builtins.__build_class__   # spike 1
MODEL = os.environ.get("MODEL", "anthropic/claude-haiku-5.5")

with open("/spike/btc_1m_5d.csv") as f:
    ALL = [{"m": r["m"], "o": round(float(r["o"]), 1), "h": round(float(r["h"]), 1), "l": round(float(r["l"]), 1),
            "c": round(float(r["c"]), 1), "v": round(float(r["v"]), 3)} for r in csv.DictReader(f)]
T1_BARS, NEW_BARS = ALL[-1470:-30], ALL[-30:]

said = []
TOOLS = {"say": {"tool": lambda text: said.append(str(text)[:400]) or True,
                 "description": "say(text): speak in the office group chat"}}

r = RLM(backend="openai",
        backend_kwargs={"model_name": MODEL, "base_url": "https://openrouter.ai/api/v1",
                        "api_key": os.environ["OPENROUTER_API_KEY"]},
        environment="local", persistent=True, custom_tools=TOOLS,
        max_iterations=10, max_budget=0.03, max_timeout=240)

# rlms creates the env lazily inside completion(); a tiny warm-up turn creates it.
w = r.completion({"turn": "warmup"}, root_prompt='Set answer["content"] = "ready" and answer["ready"] = True. Do nothing else.')
env = r._persistent_env
print(f"[warmup] cost ${w.usage_summary.total_cost:.4f}", flush=True)

state = {}            # name -> (description, updated_at, change_note)
mine_before = set()


def put(name, value, desc, note=""):
    env.locals[name] = value
    state[name] = (desc, datetime.utcnow().strftime("%H:%M:%S"), note)


def shape(v):
    if isinstance(v, list):
        return f"list[{len(v)}]"
    if isinstance(v, dict):
        return f"dict[{len(v)} keys]"
    return type(v).__name__


SCAFFOLD = {"answer", "context", "history", "llm_query", "llm_query_batched", "rlm_query", "rlm_query_batched",
            "SHOW_VARS", "say", "FINAL_VAR"}


def make_map(reason):
    lines = [f"Why you are awake: {reason}", "",
             "DATA OBJECTS in your REPL, maintained by the office (read them by name; do not assign to them):"]
    for name, (desc, at, note) in state.items():
        lines.append(f"  {name:12s} {shape(env.locals[name]):14s} {desc}. updated {at} UTC{(' -- ' + note) if note else ''}")
    yours = sorted(k for k in env.locals if not k.startswith("_") and k not in state and k not in SCAFFOLD
                   and not k.startswith(("context_", "history_")))
    lines.append("")
    lines.append("YOUR OBJECTS (you created them): " + (", ".join(f"{k} ({shape(env.locals[k])})" for k in yours) or "none yet"))
    hist = sorted(k for k in env.locals if k.startswith("history_"))
    if hist:
        lines.append(f"HISTORY: {', '.join(hist)} -- the full transcript of each of your earlier turns, as message lists")
    return "\n".join(lines)


def turn(n, reason, task):
    said_before = len(said)
    root = make_map(reason) + "\n\nTASK:\n" + task
    t0 = time.perf_counter()
    c = r.completion({"turn": n}, root_prompt=root)
    out = {"turn": n, "secs": round(time.perf_counter() - t0, 1), "cost": c.usage_summary.total_cost,
           "in_tok": c.usage_summary.total_input_tokens, "out_tok": c.usage_summary.total_output_tokens,
           "map_chars": len(root), "answer": c.response[:500], "said": said[said_before:]}
    try:
        out["parsed"] = json.loads(c.response)
    except Exception:
        out["parsed"] = None
    out["context_now"] = repr(env.locals.get("context"))[:80]
    return out


def truth(bars, wind_now, wind_prev):
    last = bars[-60:]
    return {"last_close": bars[-1]["c"], "high_60m": max(b["h"] for b in last), "low_60m": min(b["l"] for b in last),
            "wind_rose": wind_now > wind_prev}


ASK = ('Using ONLY the data objects listed above (read them in the REPL), compute: the latest close in bars_1m, '
       'the highest high and lowest low over its last 60 bars, and whether wind_prob is higher than wind_prob_prev. '
       'If chat_new contains a message addressed to you, reply to it with say(). '
       'Set answer["content"] to ONE line of JSON {"last_close": .., "high_60m": .., "low_60m": .., "wind_rose": true/false, '
       '"replied_to": "<who or none>"} and answer["ready"] = True.')

# ---- T1 ----
put("bars_1m", list(T1_BARS), "BTC/USD 1-minute bars, oldest first; keys m (UTC minute), o, h, l, c, v (BTC)")
put("wind_prob", 0.41, "your 风口 model's probability of a >30 bps move within 2 h")
put("wind_prob_prev", 0.35, "wind_prob at your previous wake")
put("jev_read", {"regime": "continuation", "exhausted": 0.22, "trend_quality": 1.4}, "Jev's latest typed read of the market")
put("positions", [], "your open positions")
put("chat_new", [{"from": "manager", "to": "trader", "text": "Morning. What does the last hour look like?"}], "unread chat messages")
put("budget_left", 0.29, "USD left of today's model budget")
fact_names = set(state)
t1 = turn(1, "scheduled heartbeat", ASK)
t1["truth"] = truth(T1_BARS, 0.41, 0.35)
print("T1", json.dumps(t1, ensure_ascii=False), flush=True)

# ---- the runner updates the runtime between turns ----
b = env.locals["bars_1m"]
b.extend(NEW_BARS)
del b[:30]
put("bars_1m", b, state["bars_1m"][0], "30 new bars appended since your last turn, 30 oldest dropped")
put("wind_prob_prev", 0.41, state["wind_prob_prev"][0])
put("wind_prob", 0.78, state["wind_prob"][0], "jumped from 0.41")
put("positions", [{"pid": 7, "side": "short", "size": 0.05, "entry": NEW_BARS[0]["c"]}], state["positions"][0], "1 new position")
put("chat_new", [{"from": "boss", "to": "trader", "text": "Wind is up. Are you still short? One line."}], state["chat_new"][0], "1 new message")
facts_snapshot = {k: json.dumps(env.locals[k], sort_keys=True, default=str) for k in fact_names}

# ---- T2 ----
t2 = turn(2, "your should_wake fired: wind_prob 0.78", ASK)
t2["truth"] = truth(env.locals["bars_1m"], 0.78, 0.41)
t2["facts_overwritten"] = [k for k in fact_names if json.dumps(env.locals[k], sort_keys=True, default=str) != facts_snapshot[k]]
print("T2", json.dumps(t2, ensure_ascii=False), flush=True)

# ---- T3 ----
t3 = turn(3, "the manager asked you to review yourself",
          'Using the HISTORY variables (not memory), find what you reported as last_close in your previous turn and in '
          'the turn before it. Set answer["content"] to ONE line of JSON {"previous_turn_last_close": .., '
          '"turn_before_last_close": .., "history_vars_used": [..]} and answer["ready"] = True.')
t3["truth"] = {"previous_turn_last_close": t2["truth"]["last_close"], "turn_before_last_close": t1["truth"]["last_close"]}
print("T3", json.dumps(t3, ensure_ascii=False), flush=True)
r.close()
