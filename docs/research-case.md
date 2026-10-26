# Recursive Commons: research case

## One-sentence case

Recursive Commons is a persistent, gamified pixel office in which a human boss,
a manager, and RLM workers form a visible working community. The office is a
research instrument for studying how agency, delegation, memory, and learning
change when AI workers can operate on an analytics environment over time.

The market office is a controlled sandbox: it supplies real data, uncertainty,
feedback, costs, and held-out evaluation. It is not evidence that a trading
strategy is profitable in the world, and the project does not optimize for live
financial deployment.

## Research questions

### RQ1 — AI community evolution

How does an AI-human community evolve as the human delegates more authority and
combines human judgment with different AI roles?

The important unit is not an isolated agent benchmark. It is the changing
division of labour: who notices, who proposes, who verifies, who decides, who
remembers, and how responsibility moves after an error.

### RQ2 — RLM in analytics environments

What is the value of a Recursive Language Model when it can inspect and transform
an analytics environment over multiple turns, rather than receiving all context
as a single prompt?

The hypothesis is that the main advantage of RLM is not only larger effective
context. In analytics, recursion may improve the *shape of work*: the model can
choose what to inspect, create intermediate representations, run calculations,
test a hypothesis, preserve useful state, and return with a smaller decision
surface.

## Hypotheses

### H1 — Delegation changes the community, not just throughput

As the boss delegates more bounded authority to the manager, the community will
show more autonomous research and faster iteration, but only if authority,
evidence, and rollback remain visible. Unbounded delegation is expected to
increase silent failure and make the human's mental model worse.

**Falsifier:** delegation does not change iteration rate or coordination quality,
or any gains disappear after controlling for model calls and available compute.

### H2 — Complementary roles outperform duplicated agents

A community with distinct roles (boss, manager, RLM worker, evaluator) will make
better-calibrated changes and recover from mistakes more reliably than the same
budget spent on duplicated general-purpose agents.

**Falsifier:** role separation does not improve held-out outcomes, error recovery,
or evidence traceability relative to matched-budget duplication.

### H3 — RLM helps analytics through recursive workflow

Compared with a flat-context agent with the same model and token budget, an RLM
will perform better on analytics tasks that require iterative inspection,
intermediate computation, hypothesis revision, and stateful reuse. The gain
should remain after context length is matched.

**Falsifier:** RLM's advantage disappears when both systems receive the same
context, tools, call budget, and memory, or it appears only on tasks that reward
more tokens rather than better workflow.

### H4 — Gamification changes behaviour, so it must be measured

Visible XP, seasons, badges, probation, and a leaderboard will increase useful
experimentation and explanation, but can also create gaming pressure: excessive
variant search, shallow activity, or risk-taking for rank.

**Falsifier:** the game layer has no measurable effect, or its apparent gains are
entirely explained by more calls, more trials, or lucky outcomes.

## Why a pixel office?

The game layer is an observation and intervention surface, not decoration.

- The public chat exposes negotiation, uncertainty, disagreement, and the human's
  changing role.
- The office map gives persistent agents a shared social location and makes state
  changes legible without reading logs.
- XP rewards validated improvement rather than raw P&L, so iteration is visible
  without making luck the objective.
- Seasons create comparable observation windows and let us test incentive changes.
- The event ledger preserves who acted, what evidence was available, which version
  acted, and what happened afterward.

The game should never hide the underlying record. Every score is derived from
events, positions, evaluations, and measured spend; agents cannot award themselves
XP or rewrite the leaderboard.

## Experimental design

Each experiment is a season or a matched replay with a pre-registered change.
Keep the market data, fee regime, model family, and daily budget fixed unless one
of them is the independent variable. Record the change in the public chat and in
the experiment log before looking at the outcome.

### Community conditions

Compare conditions such as:

1. human-only control;
2. human + one general agent;
3. human + manager + worker;
4. human + manager + RLM worker;
5. the same role structure with more or less delegated authority.

The conditions must be matched on model-call budget and access to data. The point
is to compare organization and workflow, not to reward the condition that simply
spends more.

### RLM conditions

Compare an RLM with a flat-context baseline under matched:

- model and prompt family;
- wall-clock and model-call budget;
- tool access and data availability;
- memory retention;
- evaluation windows and failure handling.

Vary the analytics task, not just the market: anomaly investigation, regime
description, feature construction, backtest diagnosis, error analysis, and
decision review. A market result alone cannot establish an RLM effect.

### Incentive conditions

Run the same workers with different reward surfaces:

- no visible score;
- P&L-only score;
- validated-improvement XP;
- XP plus public peer review;
- XP with an explicit anti-gaming penalty for redundant or invalid experiments.

Measure both productivity and distortion. A system that produces more experiments
but less reliable knowledge has not improved.

## Measures

### Community and delegation

- useful decisions per model dollar and per hour;
- time from observation to tested hypothesis;
- proportion of actions initiated without a human prompt;
- delegation depth and manager intervention rate;
- reversal/recovery time after a failed change;
- evidence traceability: decisions with data, uncertainty, and invalidation rule;
- human calibration: whether the boss can correctly predict the system's current
  state and authority boundaries;
- disagreement quality: whether disagreement predicts better subsequent tests.

### RLM and analytics

- held-out task quality and calibration;
- error rate in intermediate calculations;
- number and usefulness of recursive sub-steps;
- context read / context written / model-call cost;
- reuse of intermediate artifacts across turns;
- time to diagnose a failed hypothesis;
- robustness when irrelevant context is added or useful context is withheld;
- transfer across analytics tasks and data regimes.

### Game and incentives

- experiments per season, valid experiments per season, and duplicate rate;
- XP earned per validated improvement rather than per action;
- leaderboard rank stability across seeds and windows;
- risk-taking, premature stopping, and reward hacking;
- chat quality: claims with evidence, counterclaims, and explicit uncertainty;
- retention of workers' useful practices after a new hire or reset.

Raw P&L remains a secondary outcome. It is logged because the sandbox needs
consequences, but it is never treated as proof of general intelligence or a
production trading edge.

## Research loop

```text
observe → state a hypothesis → choose a bounded intervention
       → run on visible data → submit to held-out evaluation
       → act in the sandbox → record outcome and uncertainty
       → review the community process → update the next experiment
```

The manager may propose and coordinate changes, but the office server remains the
world's authority: it owns the ledger, budgets, settlement, evaluator, and event
history. The human boss can inspect the full record and change the delegation
boundary.

## Safety and interpretation

This is a paper/simulation environment. Live trading is off by default and is not
needed for either research question. Do not infer real-world financial performance
from a leaderboard result. Do not infer general social intelligence from a single
season. Report failures, invalid experiments, and negative results alongside wins.

The strongest result would not be “the RLM won.” It would be a reproducible,
matched-budget explanation of *which recursive analytics workflows helped, under
which conditions, at what cost, and how the human-AI community changed as a
result*.

## Current starting point

The prototype already contains the core instrument: a public event stream, manager
and RLM trader, persistent worker state, held-out evaluation, strategy-version
tracking, shared experience, XP, badges, seasons, and a leaderboard. The next
research step is to add explicit experiment metadata and matched baseline runs so
that the office can compare conditions rather than only display activity.
