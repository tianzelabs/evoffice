# Spike 3b — Jev as the 风口 radar (2026-10-08)

**Why a second Jev spike:** the user's correction — Jev should judge the
**风口** (whether this is a window worth trading), not predict the next bar. And
TypeSafe's own docs showed spike 3 used Jev wrongly: they recommend many small
judgments combined **in code with weights**, and state *"Every answer is
independent"* — so the "contradictions" spike 3 reported are by design, not a
defect. That part of spike 3 is withdrawn.

## Setup (pre-registered before any result)

- 334 origins, every 2 h over the last 30 days (23 skipped for gaps). Jev sees a
  multi-scale state: 48 five-minute bars for BTC, ETH and SOL (close and range in
  bps), BTC volume, the last 30 one-minute BTC closes, and the UTC day and time.
- **8 small questions in one request** — 7 *describing the present*
  (`trend_2h`, `vol_regime`, `volume_surge`, `breakout`, `cross_asset`,
  `coiling`, `exhaustion`), 1 gestalt (`opportunity`: a tradable move within 2 h?).
- **Primary truth:** |BTC net move over the next 2 h| > 30 bps (~4x the round-trip
  fee); base rate 0.377. Secondary: next-2 h range (Spearman).
- $0.032 for 334 calls ($0.000095 each), 0 errors, 0.40 s median.

## Results

**(a) Jev's 风口 judgement alone carries real information.**

| score | AUC (primary) | 95% CI | Spearman vs next-2 h range |
|---|---|---|---|
| Jev `opportunity` | **0.644** | 0.584–0.703 | 0.427 |
| trailing 2 h range | 0.649 | 0.586–0.705 | 0.532 |
| UTC-hour base rate (leave-one-out) | 0.500 | | |

The CI excludes 0.5. As a ranking over all cases it ties the best simple
baseline.

**As a wake gate it is better than that baseline where it matters — the top:**

| wake on the top 30% by | precision (base 0.38) | recall |
|---|---|---|
| trailing range | 0.43 | 0.34 |
| **Jev `opportunity`** | **0.53** | **0.43** |
| rank average of both (no fitted parameters) | 0.49 | 0.39 |

(~100 cases in the top 30%, so precision has a standard error of ~0.05:
suggestive, not settled.)

**(b) Combined, Jev adds to the baseline — suggestive, not yet proven.**
Logistic regression, 5-fold CV ×5: Jev's 8 answers 0.640, baseline features
(trailing ranges, volume ratio, hour) 0.638, **both 0.673**. A parameter-free
rank average of Jev `opportunity` + trailing range gains +0.015 AUC over the
range alone, paired-bootstrap 95% CI [−0.015, +0.045] — positive in 83.5% of
resamples, not significant at n=334.

**(c) Jev reads the present state accurately.** Against values computed in code:
`volume_surge` ρ = **0.71**, `trend_2h` vs efficiency ratio ρ = **0.63**,
`vol_regime` vs range ratio ρ = 0.50. Its categorical answers are lopsided:
`cross_asset` was "together" 263/334 and never "btc_alone" or "all_quiet";
`breakout` never "failed_break" — those two questions need rewording before they
carry weight.

## What changes

- **Spike 3's "nothing to say about price" was too strong.** At the 30-minute,
  next-bar scale it is still true. At the **2-hour 风口** scale, Jev's judgement
  has real signal, ties the best one-line baseline on ranking, and beats it at the
  top of the distribution — which is exactly where a wake gate operates.
- **Scale decides**, again (as the horizon study found for the forecasters).

## How Jev pairs with the RLM trader

1. **风口 radar → wake gate.** Every 5 min the watcher sends Jev the multi-scale
   state and a question set; code combines the answers into a 风口 score; the RLM
   wakes when the score is high **or** Jev's confidence is low (TypeSafe's own
   escalate-to-a-reasoning-model pattern). Cost: 288 calls/day ≈ **$0.03/day**.
2. **The question set and the weights belong to the trader** — they are part of
   its strategy version. The RLM can add a question (nearly free), reword a
   lopsided one, and refit weights against its own ledger. This gives
   self-iteration a concrete, measurable handle.
3. **Context labels on every trade.** The 8 answers at entry are stored with the
   position, so the trader can compute in its REPL which 风口 it makes money in.
4. **Jev for language** (spike 3's other finding) stands: classifying manager
   messages, conflicts with the boss, out-of-bounds requests.

To firm up (b): more origins (a longer ETH/SOL history, or 30-minute steps with
overlap accounted for) and the reworded categorical questions.
