"""The map: the trader's whole view of its REPL, generated every turn (spike 5).

The trader never loads data itself. The runner writes the facts into the
namespace and this module describes them -- what each object is, how fresh,
what changed -- plus the objects the trader wrote itself and the index of its
past turns. Data never enters the prompt; the map stays a few hundred tokens
however much sits underneath.
"""
from __future__ import annotations

import re

HISTORY = re.compile(r"^history_\d+$")

SCAFFOLD = {"answer", "context", "history", "llm_query", "llm_query_batched", "rlm_query", "rlm_query_batched",
            "SHOW_VARS", "FINAL_VAR"}


def shape(v) -> str:
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            return f"ndarray{tuple(v.shape)}"
    except ImportError:
        pass
    if isinstance(v, (list, tuple)):
        return f"{type(v).__name__}[{len(v)}]"
    if isinstance(v, dict):
        return f"dict[{len(v)} keys]"
    if isinstance(v, str):
        return f"str[{len(v)} chars]"
    if callable(v):
        return "function" if hasattr(v, "__code__") else type(v).__name__
    return type(v).__name__


def own_objects(ns: dict, facts: set, tools: set) -> list[str]:
    return sorted(k for k in ns if not k.startswith("_") and k not in facts and k not in tools
                  and k not in SCAFFOLD and not k.startswith("context_") and not HISTORY.match(k))


def history_names(ns: dict) -> list[str]:
    return sorted((k for k in ns if HISTORY.match(k)), key=lambda k: int(k.split("_")[1]))


def render(ns: dict, facts: dict[str, tuple[str, str, str]], tools: dict[str, str], wake: list[str],
           notes: list[str], version: str | None) -> str:
    """facts: name -> (meaning, updated_at, change note). tools: name -> one-line signature."""
    out = ["WHY YOU ARE AWAKE: " + "; ".join(wake), ""]
    out.append("OFFICE DATA in your REPL (refreshed by the office before every turn; read by name, do not assign):")
    for name, (meaning, at, note) in facts.items():
        out.append(f"  {name:15s} {shape(ns.get(name)):16s} {meaning}. updated {at}{(' -- ' + note) if note else ''}")
    out.append("")
    out.append("TOOLS: " + "; ".join(f"{k}{sig}" for k, sig in tools.items()))
    out.append("")
    mine = own_objects(ns, set(facts), set(tools))
    out.append("YOUR OBJECTS (you created them; they persist): "
               + (", ".join(f"{k} ({shape(ns[k])})" for k in mine) or "none yet"))
    out.append(f"YOUR STRATEGY VERSION (measured by the office from your functions and models): {version or 'none yet'}")
    hist = history_names(ns)
    if hist:
        out.append(f"YOUR PAST TURNS: {hist[0]} .. {hist[-1]} ({len(hist)} message lists; read only what you need)")
    for n in notes:
        out.append("NOTE FROM THE OFFICE: " + n)
    return "\n".join(out)
