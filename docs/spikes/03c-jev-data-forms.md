# Spike 3c — what form of the data is best for Jev, and does Jev add to a real model? (2026-10-09)

**The user's question:** build a real, data-driven model, then show Jev its
output — and find which *form* of the data serves Jev best.

## Setup (pre-registered)

- BTC/ETH/SOL 1-minute bars, 2026-01-01 → 2026-10-09; an origin every 2 h
  (3,350 usable). **Train** = everything before the last 45 days minus a 1-day
  embargo (2,822 origins); **test** = the last 45 days (516 origins, base rate
  0.388), unseen by the model.
- Truth: |BTC net move over the next 2 h| > 30 bps (same as 3b).
- **Data model:** gradient boosting (depth 3, 300 iterations) on 18 causal
  features — multi-scale realized vol and ranges, range expansion, volume ratios,
  net moves, trend efficiency, position in the 4 h range, largest 1-min move,
  ETH/SOL moves, BTC-ETH correlation, hour, weekday.
- **Same information, five forms**, one Jev question (the 2 h `opportunity` score):

| form | what Jev sees | input tokens |
|---|---|---|
| R0 raw | 5-min bps sequences for 3 pairs (3b's state) | ~1,500 |
| R1 features | the 18 features as raw numbers with units | ~660 |
| R2 percentiles | the same features as percentiles vs the past 30 days (causal) | ~630 |
| R3 narrative | English sentences generated from R2 ("volatility is very high for the month (85th percentile) and contracting…") | ~580 |
| R4 model + narrative | the model's probability, the typical probability, its top inputs as percentiles, plus R3 | ~720 |

$0.089 for 2,580 calls, 0 errors.

## Results (test set)

| | AUC | top-30% wake precision / recall | rank corr. with the model |
|---|---|---|---|
| **data model** | **0.711** | **0.594 / 0.46** | 1 |
| trailing 2 h range | 0.654 | 0.458 / 0.36 | |
| Jev R0 raw | 0.578 | 0.472 / 0.38 | 0.34 |
| Jev R1 raw features | 0.585 | 0.427 / 0.35 | 0.36 |
| Jev R2 percentiles | 0.629 | 0.506 / 0.40 | 0.52 |
| Jev R3 narrative | 0.655 | 0.506 / 0.40 | 0.62 |
| Jev R4 model + narrative | 0.708 | 0.568 / 0.44 | **0.93** |
| rank average of model + Jev R4 | 0.714 | 0.594 / 0.46 | |

- Jev R4 minus model: −0.003 AUC, 95% CI [−0.023, +0.018].
- Rank average minus model: +0.003, CI [−0.007, +0.013].

## What it means

**1. The form matters a lot, and the order is clear:** raw numbers (0.578) <
numbers as features (0.585) < **relative to their own history** (0.629) <
**that, said in words** (0.655). Jev is a language model reading a state, so it
reads *"very high for the month (85th percentile)"* far better than *"111.8"*.
Absolute numbers carry no scale it can use; percentiles carry the scale, and
sentences carry it in the form it was trained on. The +0.08 AUC from raw to
narrative is larger than any model-vs-baseline gap in this project's history.
This replicates, at n=516, the hint in the 2026-09-21 ablation (n=60) that the
compressed form beat the detailed one.

**2. A real data model beats every form of Jev on numeric market data**
(0.711 vs the best model-free Jev form, 0.655), and is free to run.

**3. Given the model's output, Jev echoes it.** R4 correlates 0.93 with the
model, and neither R4 nor a combination adds anything measurable. Jev does not
find information in the narrative that the model missed — because the narrative
is built from the same features the model already uses.

**4. The model's 风口 skill is volatility clustering:** its top inputs are 4 h
and 30 min realized vol, then hour of day. It predicts *that* a large move is
likely, not its direction.

## Consequences for the trader

- **The 风口 radar is a data model, not Jev.** It runs every minute for free,
  it is the best measured signal, and — crucially for the mission — **the trader
  can own it**: retrain it, add features, and measure the change in its REPL.
  A model the trader improves is self-iteration with a number attached.
- **Jev's place is where the model cannot go: information that is not
  numbers.** A data model cannot read a news headline, a manager's instruction or
  a trader's stated reasoning; Jev can, cheaply and with probabilities. Point 3
  says Jev adds nothing when the input is the model's own features — so the test
  that matters next is Jev on *non-numeric* input, where it has no competitor.
- **Whenever Jev does see numbers: percentiles, in sentences.** Never raw values.

Caveats: one question; one test window (45 days); a different period moved Jev
R0 from 3b's 0.644 to 0.578 here, so single-window numbers move by ~0.06 —
compare forms *within* a window, as this table does. The narrative template had a
cosmetic ordinal bug ("93th").
