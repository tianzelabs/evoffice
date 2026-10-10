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


def grouped(ns: dict, names: list[str]) -> str:
    """Objects, compactly: families sharing a prefix (mgr_fix_*, mgr_exp_*) collapse to one entry.
    The shared REPL holds the whole office's work; listed one by one it grew past 170 names in an
    afternoon, and every name costs context on every turn."""
    fam: dict[str, list[str]] = {}
    for k in names:
        parts = k.split("_")
        key = "_".join(parts[:2]) + "_" if len(parts) > 2 else None
        fam.setdefault(key or k, []).append(k)
    out = []
    for key, members in fam.items():
        if len(members) >= 4 and key.endswith("_"):
            out.append(f"{key}* ({len(members)} objects)")
        else:
            out += [f"{k} ({shape(ns[k])})" for k in members]
    return ", ".join(out)


def throwaways(names: list[str]) -> list[str]:
    return [k for k in names if len(k) <= 2 or k in ("tmp", "row", "res", "result", "out", "src", "code", "data", "key")]


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
    out.append("OBJECTS IN THE SHARED REPL (yours and the manager's; they persist): " + (grouped(ns, mine) or "none yet"))
    junk = throwaways(mine)
    if len(junk) >= 5:
        out.append(f"NOTE: {len(junk)} throwaway names clutter the shared REPL ({', '.join(junk[:12])}); "
                   "delete the ones you created and keep scratch work inside a dict")
    out.append(f"YOUR STRATEGY VERSION (measured by the office from your functions and models): {version or 'none yet'}")
    hist = history_names(ns)
    if hist:
        out.append(f"YOUR PAST TURNS: {hist[0]} .. {hist[-1]} ({len(hist)} message lists; read only what you need)")
    for n in notes:
        out.append("NOTE FROM THE OFFICE: " + n)
    return "\n".join(out)
