# Spike 1 — the persistent REPL (2026-10-08)

**Question:** can the watcher run the trader's own trigger functions in its
persistent REPL with no model call, and does what the trader defines actually
persist? Measured on the production server, `rlms` 0.1.3, rootless Docker. No
model was called. Scripts: `spikes/01-persistent-repl/`.

## How rlms persistence actually works (read from the source)

- **DockerREPL:** every `execute_code()` is a *new* `python` process in the
  container. Variables are dill-pickled to `/workspace/state.dill` after each
  cell and unpickled before the next. A value that fails to pickle is dropped
  inside `except: pass` — **silently**.
- **LocalREPL:** one in-process namespace dict, `exec` against restricted
  builtins. Nothing is serialized.

## Results

| test | DockerREPL | LocalREPL |
|---|---|---|
| code with no model call (`execute_code`) | yes | yes |
| watcher trigger check, median | **340 ms** (870 ms once state.dill was 1.8 MB) | **0.12 ms** |
| a plain function survives to the next cell | yes | yes |
| `class` statement | works | **fails**: `__build_class__ not found` — and the *whole cell's* variables are discarded |
| a function defined in the same cell as one unpicklable value (e.g. a generator) | **silently lost**; plain data in that cell survives | survives (no pickling) |
| state survives a runner restart | yes, if `state.dill` is copied into the new workspace | no — in memory only |
| container reaches the host's LM proxy (`llm_query`, `rlm_query`) | **NO** — `host.docker.internal` is unreachable under rootless Docker, so RLM recursion cannot work in DockerREPL on this server | n/a — in process |
| isolation | container | **none**: runs as uid 1001, can read `~/.village.env` (the OpenRouter key) |

## What this means

The architecture assumed "DockerREPL with persistent=True keeps the trader's
strategy functions". On this server it does not reliably: functions vanish
without an error depending on what else was in the cell, every check costs a
container exec, and sub-model calls cannot reach the host at all. The trader's
strategy *is* its functions, so this is load-bearing.

## Proposed change (needs the user's decision)

Run the **whole trader process** — RLM + LocalREPL — inside **one container we
build**, instead of RLM on the host driving a DockerREPL:

- isolation moves to the container boundary, where it is one wall instead of
  rlms' per-cell one;
- the REPL is in-process: functions persist, the watcher check is ~0.1 ms, and
  `llm_query` / `rlm_query` work because nothing crosses a network;
- re-enable `class` by restoring `__build_class__` in the REPL's builtins;
- the container holds **no API key**: model calls go through the office
  server (`/llm`), which holds the key, enforces the daily budget and writes the
  `spend` event — the budget becomes structural, like everything else the
  server owns;
- restart persistence is ours to write: snapshot the namespace, and **report**
  what failed to serialize instead of dropping it — never `except: pass`.
