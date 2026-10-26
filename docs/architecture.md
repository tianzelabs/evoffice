# Architecture

This is the **EvOffice** layer inside the wider **Eye of God** research
system. Eye of God supplies the market-data substrate and god's-eye operational
audit; EvOffice supplies the persistent social world where the human,
manager, and AI workers coordinate. The office is a research instrument, not a
standalone trading product.

Decided with the user on 2026-10-08, revised 2026-10-09 after spikes 1–5
(`docs/spikes/`). The design history lives in the harness repo
(`eye-of-god-on-traderme-agent-world`, `todo/pixel-office.md`).

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
   backstop. Fees are Kraken Futures tier 1 (see "Kraken realism" below);
   the old spot 4bps-a-leg rows are labelled `spot-4bps` and never compared.
7. **v0 trades BTC only** -- since 2026-10-10 the perpetual `PF_XBTUSD`.
8. **The trader writes its own data model and calls Jev itself.** It starts
   with shared *mechanics* only — the fee arithmetic, that volatility clusters,
   that the holding horizon is the lever — not with a model or a strategy
   (mechanics shared, strategy private, as in the village).

## Tech stack (decided 2026-10-08)

| layer | choice | why |
|---|---|---|
| trader | Python 3.11 + `rlms` 0.1.3, **RLM + LocalREPL in one container** (`class` re-enabled) | RLM is the trader's agent loop. DockerREPL silently drops functions and cannot reach the host under rootless Docker (spike 1) |
| trader model | **anthropic/claude-haiku-5.5** via OpenRouter | the only candidate with correct arithmetic and truthful self-report, ~$0.002 and ~10 s a turn (spikes 2, 5) |
| fast judgement | **Jev 1.13** (`typesafe/jev-1.13`, `POST /api/alpha/decisions`) | typed answers with probabilities, 0.4 s, ~$0.0001 a call; called by the trader (spike 3) |
| manager | Python + **LangChain 1.x** (`create_agent`), OpenAI-compatible chat model pointed at OpenRouter | the user wants to learn the common framework, and its eval ecosystem (`openevals`) is the reason a manager needs a framework at all |
| multi-agent orchestration | **none** — the server's event stream | orchestration frameworks decide who speaks next and run a task to completion; this office is a persistent world where agents wake on their own |
| server | Python + FastAPI | same language as the agents; `settlement.py` / `market.py` and their tests carry over unchanged |
| database | SQLite, WAL | one writer, little data, no operations |
| realtime | **SSE** server → clients; every write is an HTTP POST | only the server pushes, so WebSocket's two-way channel buys nothing |
| frontend | Vite + TypeScript + **PixiJS 8**, with a DOM control shell around the canvas | the office is a fresh scene graph: facilities, actors, hit zones and animation are separate from chat/metrics |
| art | **Kenney** packs (CC0) | free, consistent, no licence questions |
| manager model | OpenRouter, chosen by measurement when P2 starts | never estimated (an estimate was once off 8x) |
| Python tooling | uv, ruff, pytest | |
| run | systemd user units on the server, reached over Tailscale | as agent-world |

Reference read, not adopted: a16z AI Town (MIT) for how characters move and how
conversation is shown — its Convex/TypeScript backend cannot host a Python RLM
and its chats are 1:1 by proximity, not one public room.

## Frontend reset — EvOffice modern room

The current `web/` application is a clean replacement for the earlier canvas
renderer. The old renderer and its asset pipeline are intentionally removed;
there is no legacy frontend kept beside the new one.

- `src/world.ts` owns the 2.5D room scene: window wall, city silhouette, data
  wall, manager glass office, commons table, studio, plants and lighting.
- Every facility has a real hit zone and selection state. Agent views are
  separate scene objects so positions, roles and movement can come from the
  event stream rather than being painted into a background image.
- `src/main.ts` and `src/style.css` own the modern control shell: public boss
  console, room status, research metrics and leaderboard.
- `src/api.ts` is the only browser-side transport layer: history, SSE and boss
  messages remain independent from the renderer.

The cover PNG is a visual reference for the composition, not a runtime
background. The scene is reconstructed as interactive geometry so the office
can respond to hires, state changes, meetings and chat.

## The one principle: the server is the world, everyone else is a client

## Repository boundaries

The repository is split by responsibility:

- `server/` is the authoritative office world and API;
- `agents/` contains manager/trader clients and their local loops;
- `web/` is the interactive renderer and browser client;
- `research/` contains isolated experiment implementations and schemas;
- `docs/` contains research cases, protocols, spikes, and architecture;
- `tests/` contains executable checks for the office runtime.

Research code must not silently become production runtime code. It enters the
office only through an explicit adapter and a measured experiment boundary.

```
                     ┌──────────────────── office server ────────────────────┐
 browser (pixels) ◄SSE┤ FastAPI · SQLite · sole writer                          │
 boss's chat ─HTTP───►│ events · positions · settlement · leaderboard           │
                     │ /llm gateway: holds the key, enforces budget, logs spend │
                     │ evaluator: held-out window the trader cannot read (P1.5) │
                     └────────▲─────────────────────────────▲─────────────────┘
                         HTTP + SSE                     HTTP + SSE
        ┌────────────────────┴───────────────┐   ┌───────┴────────────────┐
        │ trader container (no key, no DB)    │   │ manager runner          │
        │  runner: writes facts + the MAP     │   │  LangChain agent,       │
        │  watcher: should_wake() in-process  │   │  strong model           │
        │  RLM + LocalREPL (persistent)       │   └────────────────────────┘
        │   objects: bars, wind model, Jev    │
        │   reads, positions, chat, history_N │
        └─────────────────────────────────────┘
                   model calls ──► server /llm ──► OpenRouter (haiku-5.5, Jev)
                   ClickHouse (agent-world, read-only) ──► server/market.py
```

The trader, the manager, the web page and the boss have the same standing: they
can do exactly what the API offers. Consequences:

- **"Cannot demolish the office" is structural.** No endpoint edits fees,
  settlement, prices, the ledger or a budget, so no prompt has to forbid it.
- **Scaling is starting another process.** Trader #2 is a second trader runner.
- **The frontend is a pure renderer** of the event stream.
- **The budget is structural too.** The trader's container holds no API key;
  every model and Jev call goes through the server's `/llm`, which refuses once
  the role's daily cap is spent and writes the `spend` event itself.

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
| `spend` | a model or Jev call went through `/llm`, with its measured cost |
| `wake` | the trader was woken, and why (trigger, message, heartbeat) — the wake rate is the cost driver (spike 2) |
| `version` | the runner measured a new strategy version (hash of the trader's own functions and models) |

Chat, leaderboard and animation are all **derived** from these tables; nothing
else stores them.

## API surface (planned)

| method | path | who |
|---|---|---|
| GET | `/events?since=<id>` and SSE `/stream` | everyone |
| POST | `/say` | everyone |
| GET | `/price` | everyone |
| POST | `/positions/open`, `/positions/{id}/close` | traders, for themselves only |
| GET | `/positions`, `/leaderboard` | everyone |
| POST | `/employees/{id}/params`, `/employees/{id}/fire` | manager, boss |
| POST | `/llm` | agents — model and Jev calls; the server holds the key, enforces the budget, records `spend` |
| POST | `/evaluate` | traders — submit a strategy as code; scored on the held-out window (P1.5) |

Identity in v0 is a per-process token from the env, mapped to an employee id.

## The trader's runtime and its map (spike 5)

The **runner owns the REPL namespace's facts**: market data, the trader's model
outputs, Jev's latest reads, positions, chat, budget. It rewrites them before
every turn; the server stays the truth, so a trader that assigns to `positions`
only fools itself. Per turn the trader is handed a generated **map** as
`root_prompt` — why it is awake, each object's name, shape, meaning, freshness and
what changed, the objects it wrote itself, and the `history_N` index of its past
turns. The data never enters its prompt; the prompt stays flat (~10K tokens)
however much data sits underneath, and cost rises only when the trader chooses to
dig.

Never pass per-turn data as the RLM `context`: in persistent mode rlms re-points
`context` at `context_0` every turn, so it would show the first turn forever.

## The trader's wake cycle

1. The watcher runs in the trader's container with **no model calls**: it updates
   the facts and calls the trader's own `should_wake()` in-process (~0.01 ms).
2. The RLM wakes on that trigger, a `say` addressed to it, or a heartbeat.
   **The heartbeat is a floor, the daily cap a ceiling** (spike 2): an
   always-true trigger burns the budget, a never-true one is a trader that has
   stopped existing. The wake rate is shown to the manager.
3. One `completion()`, reading through the map. It may open/close, speak, and
   rewrite its triggers, its data model, its Jev questions.
4. After the turn the runner hashes the trader's own functions and models →
   `strategy_version`. **Measured, never self-reported**: in spike 2 a model said
   "unchanged" while its function's hash changed. The runner also resets
   `answer`, which otherwise carries over between turns.

## Division of labour: data model, Jev, and what is unsolved (spikes 3–4)

| job | who | evidence |
|---|---|---|
| **when** — is a 风口 coming? | the trader's own **data model** | a gradient-boosting reference reached AUC 0.711 held out; what it learned is volatility clustering + time of day |
| **reading language** — orders, conflicts with the boss, out-of-bounds requests, news | **Jev** | its comparative advantage; on numbers it echoes a model it is shown (3c) |
| **which way** | **unsolved** | no model / Jev pattern paid the 8 bps fee on held-out data (spike 4) |

When Jev must read numbers: **percentiles against their own history, in
sentences** — AUC rose from 0.578 (raw) to 0.655 (narrative) on the same
information (3c).

## Held-out evaluation (decided in principle; built in P1.5)

Spike 4's best validation pattern (p = 0.044, a plausible story) lost 22.5 bps a
trade on unseen data. A self-iterating trader will produce such patterns
constantly, and in its own REPL it will test on data it has already seen. So:

- the server keeps a **held-out window out of the trader's data**, and an
  **evaluator** (a sandbox like the trader's container, no network, metrics out
  only) scores strategies the trader submits as code;
- the final, un-gameable test is the **leaderboard per strategy version on live
  paper trades** — the future is the only data nobody has seen.

Open for P1.5: which days are held out, how many evaluations a day, and what the
evaluator returns (aggregates only, so repeated probing cannot reconstruct it).

## Kraken realism (2026-10-10)

The user trades on a new Kraken account, so the office simulates **Kraken
Futures tier 1 on real PF_XBTUSD data**. Kraken's own demo environment is
decommissioned. kraken-cli's paper engine charges the taker rate on every fill
and cancels a resting post-only order when the price touches it, so the office
runs its own engine and uses kraken-cli only as a reference.

- **Data**: agent-world `ingestion/futures_capture.py` (WS trades and ticker)
  and `futures_backfill.py` (1m candles and hourly funding, 120 days).
- **Fees** (`server/fees.py`): maker 0.02%, taker 0.05% a side. Round trips
  cost 10 / 7 / 4 bps (taker/taker, maker/taker, maker/maker).
- **Market orders** fill at the ask / bid as taker. **Limit orders**
  (`server/orders.py`) are tick 1 USD; post-only orders are rejected if they
  would cross; a resting order fills at its limit as maker only when a trade
  prints *through* it (a touch is not a fill).
- **Funding** (`server/funding.py`) is charged hourly at Kraken's published rate
  and is part of each position's P&L.
- **Evaluator** uses the same rules on held-out futures bars, with an optional
  limit entry.
- **Parity** (`ops/kraken_parity.py`): market fills agree with kraken-cli paper
  6/6 on price (+-1 tick) and fee.
- **Not modelled**: partial fills, depth slippage for large sizes, queue
  position (a through-fill is the conservative stand-in).

### Going live (`server/broker.py`) -- built, OFF

`GET /golive/{trader}` is a read-only checklist with five items:
- a held-out 95% interval above zero under the current regime;
- at least 30 live paper trades of that same version, net positive;
- the boss's hand-written `~/pixel-office/LIVE_APPROVED.json` (trader, version,
  max_size);
- kraken-cli installed;
- `OFFICE_LIVE_TRADING` set by the user.

`KrakenLive.submit` refuses unless all five pass, and even then is not wired to
any route. Connecting it is a deliberate code change by the user, who
configures trade-only API keys (no withdrawal permission) with `kraken setup`
themselves.

## Firing

`fire` event → the trader's container is destroyed, the server closes
any open position with `close_reason = fired`, and starts a fresh hire with a
new employee id, a new container and an empty REPL. The old record stays on the leaderboard.

## Budget

$0.50/day: **manager $0.20** (strong model), **trader $0.30** (cheap model).
Every model and Jev call goes through the server's `/llm`, which writes a
`spend` event with the **measured** cost (never an estimate — an earlier estimate
was off by 8x) and refuses once the role's daily total is reached. Measured trader
turn: ~$0.0016–0.0025; Jev: ~$0.0001 a call. This is the only guard the design
adds, because it is the one constraint that is actually binding.

## Carried from agent-world `village/`

`settlement.py` (fee model, pure) and `market.py` (ClickHouse, never fabricate a
price) come over, adapted from fixed-horizon contracts to self-closed positions.
So does the test that a favourable move can still lose.

## Spikes (done — see `docs/spikes/`)

| # | question | answer |
|---|---|---|
| 1 | does a persistent REPL keep what the trader defines? | DockerREPL silently drops functions and can't reach the host → RLM + LocalREPL in one container |
| 2 | which model, what does a turn cost? | haiku-5.5, ~$0.0025; the wake rate, not the token price, decides cost |
| 3 / 3b / 3c | what is Jev good for, in what form? | 风口 signal at 2 h (AUC 0.64); best form = percentiles in sentences; echoes a model it is shown |
| 4 | how should a data model and Jev cooperate? | division of labour; nothing pays the fee on direction; held-out evaluation is the real pattern |
| 5 | runtime + map? | works: 10/10 correct, flat prompt, history recall; `context` goes stale |

The 2-hour horizon used in spikes 3b–4 was a choice, not a measurement; the
horizon is the main mechanical lever and is the trader's to explore.

## Build order

- **P0** — server + a plain-text page: chat (the boss can post) and leaderboard.
- **P1** — the trader container: runner, map, watcher, RLM; `/llm` gateway.
- **P1.5** — held-out evaluator.
- **P2** — the manager.
- **P3** — the pixel skin.

Pixels come last on purpose: a beautiful office in which no agent has had a
thought is the failure this project already had once.
