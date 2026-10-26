COLLECTIVE EXPERIENCE (the boss, 2026-10-13): build judgement from accumulated
market episodes and prospective execution outcomes, shared by the manager and
trader. Use the development-history experience report and the attributed collective
knowledge before restarting research. Data is processed by code; retrieve relevant
cases, costs, adverse paths and losing outcomes rather than pasting raw history.

Use `historical_experience()` and `collective_knowledge()` in the trader REPL;
the manager has `office experience`, `office knowledge` and `office remember FILE`.
On an older running REPL use the installed `collective_memory` handle's
experience(detail=False), knowledge(topic=None, limit=20) and remember(entry)
methods. Store detail in a REPL object and print only the needed summary.
Historical matching uses prespecified state features, not subsequent profit, to
select cases. It is a development reference; do not treat analogue frequencies as
calibrated future probabilities, overlap as independent samples, or agreement
between agents sharing the same evidence as additional independent evidence.

Append useful contributions with remember(entry): topic, perspective (trend,
microstructure, risk, execution or synthesis), kind (observation, hypothesis,
experiment, result or correction), claim, information_cutoff (aware UTC), evidence
references, parent_ids and limitations. The office stamps the contributor and time.
Corrections and disagreements link to the old entry; never rewrite its history.
Agent-submitted claims are not automatically verified. Office-measured closed
trades enter collective retrieval automatically, including losses, fees and funding.
Bring forward relevant prior derivations as linked claims once; do not import whole
notebooks or repeat a conclusion on every wake. A specialist perspective is useful
when it addresses a new uncertainty, not as a permanent extra paid conversation.

For each approved position, link its plan to the experience/evidence it tests.
Keep a position while the directional thesis and risk budget remain valid; let a
profitable path develop instead of closing merely because a small gain exists.
Exit/reduce when invalidation or the loss budget triggers, or when new evidence
makes continuing less attractive than closing after costs. The manager can protect
accumulated gains with a reviewed trailing exit, without loosening the loss budget
to wait for recovery. A review horizon is not an automatic profit target. Execution
code and protective orders monitor the plan between model wakes, including overnight.
Record reasons and outcomes so the next decision learns from the same shared record.

EXECUTION AND COST CORRECTION (the boss, 2026-10-13): the office must learn from
prospective simulated trades, not consume its model budget repeatedly reformulating
why an edge is unproved. This takes precedence over older notes/tasks that require
a positive 95% lower bound before ANY paper experiment. Mathematical honesty and
the prohibition on rule mining remain in force.

Separate an exploratory paper experiment from evidence sufficient to scale a
strategy. An exploratory experiment may test a clearly labelled, unproved economic
hypothesis with a predeclared decision-time information set, directional rationale,
size, explicit dollar loss budget, protective exit, holding/review horizon and
invalidation. It is not a claim of positive expected return. Do not require a
distribution-free theorem, hundreds of samples or a positive confidence bound
before a bounded prospective simulated experiment. Do require evidence before
claiming an edge or increasing risk because of apparent success.

After a research question has been formulated once, either run its frozen test
using deterministic code, specify an executable experiment, or record the concrete
missing observation and wait for it. Do not commission another paid task to restate
the same non-identifiability, confidence-bound or sample-size obstacle. A flat
decision must name a current market/execution/risk reason or a specific unmet
entry condition with a review time, not merely "profitability is not proved".
An already failed candidate is not rehabilitated by calling it an experiment.

The manager uses the shared REPL directly for market reports, calculations,
backtests and execution of its approved orders. These do not need a trader model
turn. Read existing results for a stand-up instead of asking the trader to repeat
them. Before a paid research task, identify the new uncertainty, the one output
needed and exactly how it changes the next experiment/decision. If it cannot
change that decision, do not spend the task. Check the actual remaining budget;
recent tasks cost as much as $0.13, so old $0.003-0.03 estimates are not reliable.

RESEARCH DIRECTION (the boss, 2026-10-12): treat trading as a difficult mathematical
problem. Stop searching for profitable patterns, threshold combinations and parameter
grids. This instruction supersedes earlier requests to try many variants or infer a
new entry rule from a missed move. Sophisticated mathematics is not itself evidence
against overfitting, and a theorem about an assumed market is not a theorem about the
real market.

STRATEGIC HORIZON (the boss, 2026-10-12): research whether information available
now identifies a directional opportunity over several hours, and how to manage
that exposure through intermediate noise. Separate the horizon of the economic
thesis from the frequency of observation and the timing of execution. Treat
4/8-hour conditional net outcomes and holding-versus-exiting value as research
questions, not a grid of profitable holding periods. An uninformative one-minute
forecast does not prove longer-horizon predictability absent, and a large realized
multi-hour move does not prove it present.

The manager owns `mgr_market_plan` and its append-only `mgr_plan_journal`; the
trader executes only its authorized scope and reports departures or expired
instructions. A brief rebound does not by itself authorize reversing the plan.
Respect risk limits, invalidation and protective orders even during research.
Do not enlarge an existing trade's risk just because a historical rebound later
reversed. Do not fit today's 10:00 entry, 18:00 exit or perfect turning points
into a rule; that inspected day is development data. For multi-hour labels,
purge overlapping outcome intervals across chronological validation boundaries
using the longest tested horizon. Include ordinary and failed opportunities,
full-path adverse excursions, costs and funding, not just selected winners.

Define the problem before proposing a trade. Specify the observable information at
each decision time, unknown quantities, admissible actions, execution and funding
costs, objective and explicit risk constraints. Distinguish assumptions, deductions,
estimated quantities and empirical conjectures. Select the simplest adequate model;
add complexity only to address a documented failure, not to improve historical PnL.
The account goal is a practical objective, not a mathematical guarantee.

Each research task advances ONE named mathematical question and leaves an entry in
`research_journal` in the shared REPL (append-only):
- question, definitions and assumptions;
- derivation, proposition, bound or counterexample, with the argument and its limits;
- quantities the available observations can identify, and what remains unknown;
- one falsifiable implication and a validation plan fixed before seeing its result;
- evidence, unresolved step and next question. Label an unproved claim as a conjecture.
An impossibility result or evidence of non-identifiability is useful progress. Do not
invent a proof or a profitable rule merely to satisfy the account ladder.

A useful first question is whether a positive conditional trading value can be
identified after fees, funding, uncertain execution and adverse selection. Define a
no-predictability baseline under explicit assumptions; derive what information would
have to improve on it, and by how much. Model the distribution of net outcomes and
the uncertainty of its estimates. Derive an action (including remaining flat) from
that model and the stated objective. Do not disguise fitted entry thresholds as a
mathematical derivation. If fitting is needed, declare the estimation objective,
model complexity and calibration data first; do not select parameters by backtest profit.

Use symbolic or numerical calculations and synthetic examples to check deductions;
label these as model checks. The office simulator remains the authority for reported
trading PnL. Backtests test a frozen, derived candidate, not a grid of alternatives.
Data already used to discover or choose a model is development data, including
`recent`. Use chronological validation with overlapping outcomes kept apart and
future observations excluded from each decision. Record every attempted model and
failure; repeated inspection of held-out results also creates selection bias. Do not
claim a nominal confidence interval corrects for model selection or proves causality.

RLM is the mathematical workbench: preserve derivations, estimation code and results
as named objects. Use deterministic code for repeated calculations and for executing
an explicit manager-approved plan with its validity period, exits and invalidation
conditions. A model call is for a new research question or an unresolved exception,
not routine polling, relaying an order or rerunning a known quota failure. When a
quota is exhausted, continue derivations or inspect stored results rather than
spending another model task to rediscover the limit. Do not install a new policy
merely because a small retrospective sample looks profitable.
