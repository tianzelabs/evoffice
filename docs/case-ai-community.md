# Case A — AI community evolution

## Question

How does an AI-human community evolve when the human delegates more authority and
combines AI roles instead of using one general assistant?

The unit of study is the division of labour: who notices, proposes, verifies,
decides, remembers, and repairs an error. The office makes these transitions
visible in public chat, agent state, commands, evidence, and outcomes.

## Hypotheses

**A1 — Bounded delegation increases autonomy.** More clearly bounded authority
should increase useful self-initiated research and shorten the path from an
observation to a tested hypothesis. Unbounded authority should reduce the human's
ability to predict what the system is doing.

**A2 — Complementary roles beat duplicated agents.** A boss, manager, worker, and
held-out evaluator should produce better recovery and evidence traceability than
the same model-call budget spent on several undifferentiated agents.

**A3 — Community memory changes responsibility.** A shared, append-only history
should make the community better at learning from errors, provided that evidence
has authorship, time boundaries, and limitations.

## Conditions

- human only;
- human + one general assistant;
- human + manager + worker;
- human + manager + RLM worker;
- the same roles under different delegation boundaries.

Conditions must be matched on budget, data access, and evaluation window. The
comparison is about organization and responsibility, not raw compute.

## Measures

- useful decisions per dollar and per hour;
- time from observation to tested hypothesis;
- actions initiated without a direct human prompt;
- manager intervention and reversal rates;
- recovery time after a failed change;
- evidence traceability and uncertainty reporting;
- human calibration about current state and authority boundaries;
- whether disagreement predicts better later tests.

## Falsification

This case is weakened if delegation does not change coordination, if role
separation does not improve recovery or evidence quality, or if the apparent gain
vanishes after controlling for calls, tokens, and data access.
