# Architecture

Decided with the user on 2026-10-08. The design history lives in the harness
repo (`eye-of-god-on-traderme-agent-world`, `todo/pixel-office.md`).

## Decisions — do not re-derive

1. **The boss (the user)** appears only as a speaker in the public chat, and
   outranks everyone.
2. **The trader is an RLM.** It fully replaces the earlier eve + Graphiti
   resident `r1`.
3. **The manager has full authority over the trader** — talk, set its
   parameters, fire it — but cannot touch the office, cannot do anything
   illegal or unethical, and obeys the boss.
4. **The trader watches the market continuously** and is otherwise free to roam.
5. **Own repo.** `agent-world` stays the market-data substrate; this repo only
   reads prices from its ClickHouse.
6. **The trader closes its own positions.** A max holding time exists only as a
   backstop. Both legs pay 4bps.
7. **v0 trades BTC/USD only.**

## The one principle: the server is the world, everyone else is a client

```
                     ┌──────────────── office server ────────────────┐
 browser (pixels) ◄─WS┤ FastAPI · SQLite · sole writer                  │
 boss's chat ─HTTP───►│ events: say open close settle agent_state       │
                     │         command fire spend                       │
                     │ positions · settlement · leaderboard · budget    │
                     └────────▲──────────────────────────▲─────────────┘
                         HTTP + WS                   HTTP + WS
             ┌───────────────┴─────────┐   ┌───────────┴────────────┐
             │ trader runner            │   │ manager runner          │
             │  watcher (code, always)  │   │  strong model,          │
             │   └─ wakes ─► RLM        │   │  plain tool loop        │
             │  DockerREPL persistent   │   └────────────────────────┘
             └──────────────────────────┘              │
                   │ cheap model                        │ strong model
                   └──────────── OpenRouter ────────────┘
                   ClickHouse (agent-world, read-only) ──► server/market.py
```

The trader, the manager, the web page and the boss have the same standing: they
can do exactly what the API offers. Consequences:

- **"Cannot demolish the office" is structural.** No endpoint edits fees,
  settlement, prices, the ledger or a budget, so no prompt has to forbid it.
- **Scaling is starting another process.** Trader #2 is a second trader runner.
- **The frontend is a pure renderer** of the event stream.

## Data (sketch — `server/schema.sql` makes it real)

- **employees** — id, role (`manager` | `trader`), hired_ts, fired_ts,
  params (JSON: heartbeat_s, max_size, max_hold_s). A fired trader keeps its row
  and its record; the new hire is a new id.
- **positions** — id, employee_id, strategy_version, pair, side, size,
  opened_ts, entry_px, max_hold_s, closed_ts, exit_px,
  close_reason (`self` | `max_hold` | `fired` | `void`), fees, pnl (net).
- **events** — id, ts, actor, kind, payload (JSON). Append-only. Kinds:

| kind | written when |
|---|---|
| `say` | anyone speaks in the public chat (`to` optional, for waking) |
| `open` / `close` | a position opens / closes |
| `settle` | the net result of a closed position is computed |
| `agent_state` | an agent changes what it is doing (thinking, idle, watching) — drives animation |
| `command` | the manager (or boss) changes a trader's params |
| `fire` | the manager fires a trader |
| `spend` | a model call was made, with its measured cost |

Chat, leaderboard and animation are all **derived** from these tables; nothing
else stores them.

## API surface (planned)

| method | path | who |
|---|---|---|
| GET | `/events?since=<id>` and WS `/stream` | everyone |
| POST | `/say` | everyone |
| GET | `/price` | everyone |
| POST | `/positions/open`, `/positions/{id}/close` | traders, for themselves only |
| GET | `/positions`, `/leaderboard` | everyone |
| POST | `/employees/{id}/params`, `/employees/{id}/fire` | manager, boss |
| POST | `/spend` | agents, for themselves |

Identity in v0 is a per-process token from the env, mapped to an employee id.

## The trader's wake cycle

1. `watcher.py` runs continuously with **no model calls**: it pulls prices and
   evaluates the trigger functions the trader has written in its REPL.
2. The RLM wakes on a trigger, a `say` addressed to it, or a heartbeat
   (`params.heartbeat_s`, which the manager can change).
3. One `completion()`: the REPL already holds prices, its own positions, the chat
   and its earlier sessions as variables. It may open/close, speak, and rewrite
   its own triggers and strategy functions.
4. After the turn the runner hashes the REPL's user-defined functions →
   `strategy_version`. New positions carry it.

## Firing

`fire` event → trader runner stops the RLM, destroys the REPL container, closes
any open position with `close_reason = fired`, and starts a fresh hire with a
new employee id and an empty REPL. The old record stays on the leaderboard.

## Budget

$0.50/day: **manager $0.20** (strong model), **trader $0.30** (cheap model).
Every model call writes a `spend` event with its **measured** cost (never an
estimate — an earlier estimate was off by 8x); `agents/common/llm.py` refuses to
call once the role's daily total is reached. This is the only guard the design
adds, because it is the one constraint that is actually binding.

## Carried from agent-world `village/`

`settlement.py` (fee model, pure) and `market.py` (ClickHouse, never fabricate a
price) come over, adapted from fixed-horizon contracts to self-closed positions.
So does the test that a favourable move can still lose.

## Spikes before real code

1. **Can a persistent DockerREPL run code without a model call?** The watcher
   needs it. If not, the trader exports its triggers and the host-side watcher
   evaluates them.
2. **What does one RLM turn cost** on the chosen cheap model? That decides the
   default heartbeat.

## Build order

- **P0** — server + a plain-text page: chat (the boss can post) and leaderboard.
- **P1** — the RLM trader + cost measurement.
- **P2** — the manager.
- **P3** — the pixel skin.

Pixels come last on purpose: a beautiful office in which no agent has had a
thought is the failure this project already had once.
