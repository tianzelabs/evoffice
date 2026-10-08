# pixel-office

A 2D pixel trading office. v0 cast: **one manager, one trader**; more traders later.
Everyone — the manager, the trader, and the boss (the user) — talks in **one public
chat**. A **leaderboard** on the office wall tracks every employee's record, per
strategy version.

The point is not the game. The point is **agent self-iteration**: a trader that
changes how it trades, and a record that shows whether the change helped. The
office is how that becomes visible. A profitable trader that never changes is the
failure mode, not the goal.

## Layout

| path | what it is |
|---|---|
| `server/` | the world: the only writer, the only place rules live |
| `agents/common/` | what every agent shares: the office client, the model client |
| `agents/trader/` | the RLM trader and its always-on watcher |
| `agents/manager/` | the manager: a strong model with authority over the trader |
| `web/` | the pixel office, a renderer of the event stream |
| `systemd/` | one user unit per process |
| `tests/` | |
| `docs/architecture.md` | how the pieces fit, and why |

Each directory's README says what it owns and — as important — what it does not.

## Status

**Scaffold only. No logic yet.** See `docs/architecture.md` for the build order
and the two spikes that run before real code.

## Where things run

Server-primary, like `agent-world`: the canonical checkout is on the production
server at `~/pixel-office-home/pixel-office`. Market data comes read-only from
`agent-world`'s ClickHouse (database `traderme`, table `trades`, BTC/USD).
