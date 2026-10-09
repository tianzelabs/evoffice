# Spike 5 — the runner owns the runtime, the trader gets a map (2026-10-09)

**The user's idea:** the runtime holds every data object; the trader's context
is not loaded by the trader but is a **map** the runner keeps current — the
runner, not the agent, changes what the agent knows. Is RLM friendly to that?

## What rlms gives out of the box (read from source)

Per turn the root model sees only: *"Your context is a dict of N total
characters"*, the counts of `context_N` / `history_N`, and a `SHOW_VARS()` that
lists names and types. Nothing about what an object is, when it changed, or what
changed. And in persistent mode **`context` is re-pointed at `context_0` every
turn** — a trader reading `context` sees the first turn's data forever, with no
error. So the map is ours to build.

## Test

haiku-5.5, RLM + LocalREPL in one container (spikes 1–2). The runner writes
objects straight into the namespace (`bars_1m` 1,440 real BTC bars, `wind_prob`,
`wind_prob_prev`, `jev_read`, `positions`, `chat_new`, `budget_left`) and passes a
generated map (name, shape, meaning, updated-at, change note, the trader's own
objects, the history variables) as `root_prompt`. Answers are checked against
values the runner computes.

| | T1 | runner update | T2 | T3 |
|---|---|---|---|---|
| task | compute last close, 60-bar high/low, did wind rise; answer the manager | +30 bars, wind 0.41→0.78, a new short, a boss message | same task on the new data; answer the boss | recall own answers from `history_N` |
| correct | **4/4** | | **4/4** (new close, new low) | **2/2**, named `history_1`, `history_2` |
| chat | answered the manager with the numbers | | *"Yes, still short: 0.05 BTC, entry 81716.9."* — correct, one line as asked | |
| input tokens | 10.1K | | 10.7K | 34.7K |
| cost / time | $0.0016 / 8 s | | $0.0017 / 9 s | $0.0051 / 22 s |
| facts overwritten by the trader | | | none | |
| `context` | `{'turn': 'warmup'}` | | **still warmup** | **still warmup** |

Warm-up turn (rlms creates the env lazily): $0.0005.

## What it means

- **RLM fits this design well.** The trader read every object by name from the
  map, computed on 1,440 bars without them entering its prompt, saw the runner's
  updates on the next turn, and answered the right person.
- **The prompt stays flat** (10.1K → 10.7K, the map grew 300 chars) while the
  data underneath is arbitrarily large. Cost grows only when the trader **chooses**
  to dig — T3 read two full transcripts and cost 3x. That is the right shape:
  spending follows decisions, not data volume.
- **Cheaper and faster than spike 2's turn** ($0.0016 / 8 s vs $0.0025 / 14 s),
  because the data is no longer passed as context.
- **The stale-`context` trap is real**: never pass per-turn data as the RLM
  context; write it into the namespace and describe it in the map.

## Design rules this fixes

1. The **runner owns the namespace's facts** (market data, model and Jev outputs,
   positions, chat, budget) and rewrites them before every turn; the server
   remains the truth, so a trader that assigns to `positions` only fools itself.
2. The **map is the trader's whole prompt context**: wake reason, each object's
   meaning, freshness and change, the trader's own objects, the history index.
   Generated, never written by hand.
3. Per-turn data never goes through `context`; `root_prompt` carries the map.
4. The held-out evaluation window never enters the namespace (spike 4).
