# Spike 2 — which model can be the RLM trader (2026-10-08)

**Question:** can a cheap model drive an RLM trader — write working REPL code,
define a `should_wake(bars)` the watcher can call with no model, decide sensibly
— and what does a turn cost? Run on the server in the design spike 1 led to:
RLM + LocalREPL in **one container**, `class` re-enabled. Real BTC/USD 1m bars
from ClickHouse; trading tools are mocks that only record. Costs are
OpenRouter's own accounting via rlms. Scripts: `spikes/02-trader-model/`.

Two consecutive turns per model in one persistent REPL: turn 1 = 230 bars + the
manager's welcome, must define `should_wake` and decide; then the host calls
`should_wake` directly (the watcher, no model); turn 2 = 10 new bars, review or
rewrite `should_wake`, decide again. **One run per model (qwen3.7-flash: two)
— a small sample; it separates the models, it does not rank close ones.**

## Results

| | qwen/qwen3.7-flash | qwen/qwen3-coder-next | anthropic/claude-haiku-5.5 |
|---|---|---|---|
| price in/out per M | $0.03 / $0.13 | $0.12 / $0.80 | $0.10 / $0.50 |
| cost per turn | $0.0011–0.0026 | $0.0067–0.0093 | **$0.0022–0.0028** |
| time per turn | 64–148 s | 31–64 s | **14 s** |
| finished both turns | yes | **no** — turn 2 returned raw model text, could not find its own `should_wake` | yes |
| `should_wake` persisted, callable by the watcher | yes (0.01–0.07 ms) | yes | yes (0.7 ms) |
| wake rate over the last 60 min | 100% in run 1, **0%** in run 2 | **87%** | 0% (its own backtest: 29 wakes in 230 bars) |
| arithmetic | wrong: MA computed as 77652 against 81700 prices; 0.09% called "0.09 bps" | — | correct, in bps, against the 8 bps fee |
| self-report of "should_wake changed" | **false** while the hash changed | — | false, hash unchanged — **truthful** |
| what it did | opened a short; in run 1 also opened a long while still short | waited, then failed | did nothing twice — both times because the move did not clear the fee |

## What it means

- **Trader model: claude-haiku-5.5.** The only one whose numbers were right, the
  only one that reported its own change truthfully, and 5–10x faster. At
  ~$0.0025/turn the $0.30/day budget is ~120 turns/day (one per ~12 min on
  average). Turn input grows as REPL history grows (12.9K → 16.9K tokens) —
  watch it; rlms `compaction=True` exists.
- **The cheapest model is not cheap.** qwen3-coder-next's 87% wake rate would wake
  it almost every minute: ~0.87 × 1440 × $0.008 ≈ **$10/day**, 30x the budget.
  The wake rate is the cost driver, not the price per token.
- **Wake rate fails in both directions:** always-awake burns the budget,
  never-awake is a trader that has stopped existing. So the **heartbeat is a
  floor, not an option**, the daily cap is the ceiling, and the wake rate
  belongs on the manager's dashboard — it is exactly what a manager should
  notice and correct.
- **Never trust self-report for the strategy version.** qwen said "unchanged"
  while the function's hash changed. The runner measures the version; the
  trader does not declare it.
- **The `answer` dict persists across turns** in a persistent LocalREPL: in
  qwen's first run, turn 2 returned turn 1's answer verbatim. The runner must
  reset `answer` before each turn.

Spend for the whole spike: ≈ $0.03.
