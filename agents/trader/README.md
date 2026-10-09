# agents/trader/ — the RLM trader

Built on **Recursive Language Models** (`rlms`, `from rlm import RLM`,
github.com/alexzhang13/rlm). The trader's data and its past sessions live as
**variables in a persistent Python REPL**, so it can compare and recompute over
them instead of re-reading them into a prompt. The whole trader — runner, watcher,
RLM and its **LocalREPL** — runs in **one container** with no API key and no
database access (spike 1: DockerREPL silently drops functions and cannot reach the
host). Model: claude-haiku-5.5 (spike 2).

## Planned files

| file | owns |
|---|---|
| `runner.py` | the process: holds the RLM + REPL, writes the facts into the namespace, wakes it, applies manager commands |
| `map.py` | generates the per-turn map: wake reason, every object's meaning / freshness / change, the trader's own objects, the `history_N` index (spike 5) |
| `watcher.py` | always-on, **no model calls**: evaluates the trader's own trigger functions on live prices and wakes the RLM |
| `repl_bootstrap.py` | what a fresh REPL starts with: `class` re-enabled, the office tools (open/close/say/jev), shared mechanics; ledger and recent chat as variables |
| `prompt.md` | the trader's starting instructions |
| `mechanics.md` | shared, measured mechanics (fees, horizon, volatility clustering, how to use Jev) -- no strategy |
| `version.py` | the strategy version: a hash of the trader's own functions, classes and fitted models |
| `Dockerfile` | the container: rlms, dill, numpy, pandas, scikit-learn; code mounted read-only, objects in `/state` |

## How it is awake

A model in a loop would spend the $0.30/day trader budget in under an hour, so
"always watching" is split: `watcher.py` watches continuously for free, and the
model wakes on (a) a trigger **the trader wrote itself**, (b) a chat message
addressed to it, (c) a heartbeat. Between wakes the character roams the office —
that is animation and costs nothing.

## Strategy version

The hash of the functions the trader has defined in its REPL. It changes when
the trader changes how it trades, and the leaderboard scores each version
separately — so iteration is measured instead of punished.

## Does not own

Fees, settlement, prices, the ledger, its budget cap, the held-out evaluation
window (all server). Never pass per-turn data as the RLM `context` — rlms
re-points it at `context_0` every turn (spike 5).
