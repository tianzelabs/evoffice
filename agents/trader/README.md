# agents/trader/ — the RLM trader

Built on **Recursive Language Models** (`rlms`, `from rlm import RLM`,
github.com/alexzhang13/rlm). The trader's data and its past sessions live as
**variables in a persistent Python REPL** (`DockerREPL`, `persistent=True`, which
keeps `context_N` / `history_N` across `completion()` calls), so it can compare
and recompute over them instead of re-reading them into a prompt.

## Planned files

| file | owns |
|---|---|
| `runner.py` | the process: holds the RLM + REPL, wakes it, applies manager commands (params, fire) |
| `watcher.py` | always-on, **no model calls**: evaluates the trader's own trigger functions on live prices and wakes the RLM |
| `repl_bootstrap.py` | what a fresh REPL starts with: the `office` client injected as code, ledger + recent chat loaded as variables |
| `prompt.md` | the trader's starting instructions |

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

Fees, settlement, prices, the ledger (server). Its own budget cap (`common/llm.py`).
