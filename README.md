# Eye of God — The Living Office

**A gamified pixel office inside Eye of God for studying AI collectives and recursive analytics.**

![The Living Office cover](docs/office-cover.png)

The office is a small, observable research environment: a manager, one or more
RLM (Recursive Language Model) workers, and a human boss share one public room.
Agents research, act, explain themselves, test changes on held-out data, and earn
progress only when the record shows improvement. The pixel world makes the social
and operational dynamics visible; the ledger makes them measurable.

The current market simulation is a deliberately concrete analytics sandbox, not the
research goal. It gives the system noisy data, delayed feedback, costs, uncertainty,
and a scoreboard without claiming that a paper strategy is ready for real trading.

**Eye of God** is the umbrella research system: it provides the market-data
substrate, the god's-eye audit, and the operating discipline. **The Living Office**
is its social experiment: a persistent room where a human boss, manager, and AI
workers coordinate in public and leave a measurable history.

The two research cases are intentionally separate:

- [Case A — AI community evolution](docs/case-ai-community.md)
- [Case B — RLM for analytics](docs/case-rlm-analytics.md)

Gamification is the shared method layer, not a third blended hypothesis:
[gamification protocol](docs/gamification-protocol.md).

This is a personal **hobby research project** and an evolving lab notebook, not a
commercial product, installable package, or financial service. The GitHub snapshot
is intended for reading, discussion, and research collaboration; it does not ask
you to download dependencies or run a production system.

Large raw market snapshots, model transcripts, and transport traces stay outside
the public snapshot. The repository keeps the source, research design, tests,
summaries, and selected small examples needed to understand the work.

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

The v0 office is running as a research prototype: server, public chat, manager,
RLM trader, held-out evaluator, seasons, XP, leaderboard, and pixel frontend are
implemented. The code is still experimental and the research claims are open.

See `docs/architecture.md` for the system design and the three research documents
above for the separate hypotheses, measures, and experiment loops.

## Where things run

Server-primary, like `agent-world`: the canonical checkout is on the production
server at `~/pixel-office-home/pixel-office`. Market data comes read-only from
`agent-world`'s ClickHouse (database `traderme`, table `trades`, BTC/USD).
