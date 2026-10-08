# server/ — the world

One process (FastAPI). **The only writer** to the office database, and the only
place a rule of the world lives. Every agent, the web page and the boss are
clients of it, with the same standing: the API is the whole surface of what can
be done.

That is what makes "the manager cannot demolish the office" structural rather
than a prompt instruction — there is simply no endpoint that edits the fee
model, settlement, the ledger, or a budget.

## Planned files

| file | owns |
|---|---|
| `app.py` | HTTP routes and the SSE event stream |
| `schema.sql` | `employees`, `positions`, `events` |
| `events.py` | append an event, read events since an id, fan out to SSE subscribers |
| `positions.py` | open / close a position; max-hold backstop; void when no price |
| `settlement.py` | fee model, pure — carried from agent-world `village/` |
| `market.py` | BTC/USD price from ClickHouse, read-only, never fabricated — carried from `village/` |
| `leaderboard.py` | per-employee and per-strategy-version standings, derived from `positions` |
| `budget.py` | daily spend per role from `spend` events; answers "may this call go out?" |

## Does not own

Any agent's reasoning, prompts or memory. Strategy. Animation. The server never
decides *what* to trade — only what a trade was worth.
