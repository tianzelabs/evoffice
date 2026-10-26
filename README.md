# Recursive Commons

**A gamified pixel office for studying AI collectives and recursive analytics.**

The office is a small, observable research environment: a manager, one or more
RLM (Recursive Language Model) workers, and a human boss share one public room.
Agents research, act, explain themselves, test changes on held-out data, and earn
progress only when the record shows improvement. The pixel world makes the social
and operational dynamics visible; the ledger makes them measurable.

The current market simulation is a deliberately concrete analytics sandbox, not the
research goal. It gives the system noisy data, delayed feedback, costs, uncertainty,
and a scoreboard without claiming that a paper strategy is ready for real trading.

The project is named **Recursive Commons** because the two questions are coupled:
how humans and AI form a shared working community, and how recursive language-model
work changes when it can manipulate an analytics environment rather than merely
answer a prompt.

Research protocol: [Research case](docs/research-case.md).

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

See `docs/architecture.md` for the system design and
`docs/research-case.md` for the hypotheses, measures, and experiment loop.

## Where things run

Server-primary, like `agent-world`: the canonical checkout is on the production
server at `~/pixel-office-home/pixel-office`. Market data comes read-only from
`agent-world`'s ClickHouse (database `traderme`, table `trades`, BTC/USD).
