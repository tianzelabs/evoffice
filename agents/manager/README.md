# agents/manager/ — the manager

A strong model in a **LangChain 1.x** agent (`create_agent`) — no RLM, it does
not need to compute over large data. LangChain was chosen so its behaviour can be
evaluated (`openevals`), and because the user wants to learn the framework. It has **full authority over the trader** and answers to the boss.

## Planned files

| file | owns |
|---|---|
| `runner.py` | the process: wakes on boss messages, trader messages, a heartbeat |
| `tools.py` | `say`, `set_trader_params`, `fire_trader`, read chat / positions / leaderboard |
| `prompt.md` | its role, its authority, and its limits |

## Authority and its limits

May: talk, change the trader's parameters (heartbeat, size cap, max hold), fire
it (the REPL and strategy are wiped, a new hire takes the seat; the old record
stays on the leaderboard).

May not: touch the office itself — fee model, settlement, prices, ledger,
budgets, server code. These are not forbidden by the prompt; the server has no
endpoint for them. Nothing illegal or unethical. **The boss outranks it.**
