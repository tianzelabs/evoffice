# Spike 4 — playing the trader: how should a data model and Jev cooperate? (2026-10-09)

**The user's ask:** the trader will write its own data model and call Jev
itself; simulate that trader and find the strongest cooperation pattern.
Judged the trader's way — **net bps per trade after the 8 bps round trip** —
not by AUC.

## Setup

- Every pattern trades only where a 风口 model (gradient boosting, 3c's
  features) puts the chance of a >30 bps move in its own top 35%; holds 2 h;
  differs only in **how the direction is chosen**.
- Jev sees the 3c winning form (percentiles in sentences) and answers five small
  questions: `direction`, `regime` (continuation / reversion / breakout pending),
  `exhausted`, `trend_quality`, `leadership`. Answers cached once per origin.
- **Discipline:** walk-forward validation over Mar–Aug (each month traded with
  models fit only on earlier months, 523 trades) for all iteration; the last 45
  days (132 trades) held out and run **once**, after the candidates and a filter
  test were fixed.
- $0.08 of Jev calls in total.

## Iteration log (as the trader)

1. **Single split.** Validation had only 81 trades (a quiet July–August); too
   few to judge. Jev's direction call lost −31 bps/trade (CI below zero).
2. **Changed method:** walk-forward to get 523 validation trades; Jev's state
   stripped of the model's probability (3c: it only echoes it), so answers are
   model-independent and cached. Added "fade Jev" — flagged as added after
   seeing run 1.
3. **Walk-forward validation (523 trades):**

| pattern | net bps / trade | 95% CI |
|---|---|---|
| momentum 2 h | −12.9 | [−20.6, −5.4] |
| momentum 30 min | −14.6 | [−22.3, −7.0] |
| reversion 30 min | −1.4 | [−9.0, 6.3] |
| Jev direction | −13.1 | [−22.2, −4.5] |
| fade Jev | −2.9 | [−11.5, 6.2] |
| Jev router (continuation→momentum, reversion→fade) | −7.3 | [−18.0, 3.5] |
| **reversion only if Jev says "reversion"** | **+9.3** (145 trades) | [−5.0, 25.6] |
| direction model, numeric features | −8.7 | [−16.0, −1.1] |
| direction model, numeric + Jev | −7.2 | [−15.2, 0.3] |
| **direction model, Jev answers only** | **−0.3** | [−8.1, 7.1] |

   Pre-registered filter test on validation: reversion trades where Jev said
   "reversion" averaged +9.3 vs −5.5 for the rest, P(no difference) = 0.044.
   Locked two candidates — the **Jev-filtered reversion** and the **Jev-only
   direction model** — with unfiltered reversion as control.

4. **Held-out test, run once (132 trades):**

| pattern | net bps / trade | 95% CI |
|---|---|---|
| reversion only if Jev says "reversion" | **−22.5** (42 trades) | [−36.3, −8.1] |
| direction model, Jev answers only | −11.7 | [−24.7, 0.4] |
| reversion 30 min (control) | −12.2 | [−25.2, 0.4] |
| momentum 30 min | −3.8 | [−16.3, 9.3] |
| Jev direction | −4.8 | [−16.9, 7.6] |

   The filter test **reversed**: Jev-"reversion" trades −22.5 vs −7.4 for the
   rest. **Neither candidate survived.** The validation result was a regime
   (August carried it) or noise; at p = 0.044 among ~10 patterns, that is what
   it should have been expected to be.

## What it means

**No model + Jev pattern chooses BTC's 2-hour direction well enough to pay the
fee.** Every directional pattern on held-out data is negative; most are within
noise of the −8 bps a coin flip costs. This is the project's oldest finding,
reproduced with the best tools it has had.

**What does survive is a division of labour, not a fusion:**

| job | who | evidence |
|---|---|---|
| **when** — is a 风口 coming? | the trader's **data model** | AUC 0.711 held out (3c) |
| **what is said** — orders, conflicts, out-of-bounds requests, news | **Jev** | its comparative advantage; untested on market text yet |
| **which way** | **unsolved** | spike 4: nothing tried pays the fee |

**The most important result is the near-miss.** A pattern with a validation
p-value of 0.044 and a plausible story ("quant proposes, Jev vetoes") lost
22.5 bps/trade the first time it met unseen data. A self-iterating trader will
produce such patterns constantly, and in its own REPL it will happily test on
data it has already seen. So the strongest "cooperation pattern" is the
**discipline around** the model and Jev:

- the trader proposes a strategy as code;
- **the office server owns a held-out window the trader cannot read**, evaluates
  the proposal there, and only then lets it trade (or scores it as a version);
- walk-forward, not one split; and a filter must beat its own complement, not
  just look good alone.

This makes "no peeking" structural, exactly like the fee model: the API is the
wall. It also gives the manager a real job — reviewing proposals against
held-out results, not vibes.

Untested here (each a real lever for the trader later): exits other than a
fixed 2 h hold (stops, targets, Jev "exhausted" as an exit signal), other
horizons, position sizing by the 风口 probability, and Jev on non-numeric input.
