# agents/manager/ — the manager

The default backend runs Codex in the manager's isolated container; LangChain
is the paid fallback. The manager directs the trader and can use the shared
persistent Python REPL for deterministic analysis without a trader model call.
It answers to the boss.

Each wake includes a computed 1/4/8/24-hour market view: observed changes,
minute-close ranges, largest intervening rebound/drawdown, gaps and freshness.
Only completed candles enter the view. It supplies context, not a forecast or
an automatic trading signal. Unavailable market data does not abort the briefing.
Code reads raw candles and gives the manager a Markdown table. The latest data
model (`schema_version: 1`) is stored in `$MANAGER_STATE/market-report.json`,
with the readable `market-report.md` and append-only `market-report-history.jsonl`.
Reports compare observations with the prior report and may be cached for 60 seconds;
their freshness is explicit. Raw data is for targeted follow-up, not routine reading.

The manager maintains `mgr_market_plan` and an append-only `mgr_plan_journal`
in the shared REPL. Plans include horizon, evidence, risk, invalidation, execution,
review and expiry. A multi-hour thesis does not reduce monitoring frequency or
override protective orders. Minute-level execution follows the approved plan.

## Planned files

| file | owns |
|---|---|
| `runner.py` | the process: wakes on boss messages, trader messages, a heartbeat |
| `tools.py` | `say`, `set_trader_params`, `fire_trader`, read chat / positions / leaderboard |
| `prompt.md` | its role, its authority, and its limits |
| `market_view.py` | causal observed market summaries, without model calls |

## Authority and its limits

May: talk, change the trader's parameters (heartbeat, size cap, max hold), fire
it (the REPL and strategy are wiped, a new hire takes the seat; the old record
stays on the leaderboard).

May not: touch the office itself — fee model, settlement, prices, ledger,
budgets, server code. These are not forbidden by the prompt; the server has no
endpoint for them. Nothing illegal or unethical. **The boss outranks it.**
