# Spike 3 — Jev 1.13 as the trader's fast "System One" (2026-10-08)

**Question:** can Jev (`typesafe/jev-1.13`, TypeSafe's typed-decision model on
OpenRouter) make the RLM trader stronger — as the watcher's judgement, or as a
cheap bulk labeller the RLM computes over? Script: `spikes/03-jev/`.

**Call:** `POST https://openrouter.ai/api/alpha/decisions` with `model`, `state`
and named `questions` of type `noul` (P(yes)), `choice` (option + per-option
probabilities + confidence) or `score`. Input billed at $0.042/M, output free;
each response carries `usage.cost`.

**Test:** 238 origins, 30 minutes apart, over the last 5 days of real BTC/USD 1m
bars. Jev saw only the 30 bars before each origin (close and range in bps vs the
last close, volume) and answered two questions; the following 30 minutes are the
truth. Every answer is set against a naive baseline.

## Mechanics — excellent

| | |
|---|---|
| errors | 0 / 238 |
| latency | median **0.41 s**, p90 0.53 s; 238 calls in 14 s at 8 parallel |
| cost | **$0.000076 per call** (1.8K input tokens); $0.018 for the whole run |

## Information — none beyond a one-line baseline

| question | Jev | naive baseline |
|---|---|---|
| will the next 30 min move > 8 bps? (AUC) | 0.656 | **0.678** — trailing 30-min range |
| direction up / down / flat: accuracy | 0.382 | 0.349 always "flat"; 0.333 chance |
| direction: log loss (lower is better) | **1.283** | **1.098** — just the base rates |
| hit rate when it committed to up/down (n=99) | 0.364 | ~0.33 |

- On volatility it is about as good as the trailing range, not better
  (AUC standard error at this n is ~0.035).
- On direction its probabilities are **worse than knowing nothing**: log loss
  above the base rates means confident and wrong. It picked "flat" 58% of the
  time against a true 35%.
- **It contradicts itself within one request:** in 139 of 238 cases it gave
  P(move > 8 bps) > 0.5 *and* picked "flat" (= moves less than 8 bps). Median gap
  between P(clear) and 1 − P(flat): 0.15. Answers to separate questions are not
  coherent with each other.
- `P(clear)` used only 22 distinct values in 0.55–0.77: it barely moves.

## What it means

- **Do not put Jev in the watcher or anywhere it predicts price.** It adds
  nothing over a one-line rule there, and a rule the trader writes is iterable
  and free. This repeats the earlier era's finding — nothing tested has
  predicted 30-minute BTC beyond the fee — so it is evidence, not surprise.
- **Jev as an instrument is very good**: sub-second, fractions of a cent,
  typed and probabilistic. Its fit in this office is **judgement over
  language, not prices** — e.g. "is this manager message an order, a question
  or small talk?", "does this command conflict with the boss's last
  instruction?", "is this request outside the office rules (illegal,
  unethical)?" — decisions that cannot be written as a rule and that the
  office actually has to make.
- It may still be offered to the trader later as a `judge()` tool in its REPL —
  cheap enough that the trader can discover for itself what it is and is not
  good for. That is a self-iteration question, not a v0 one.

Caveats: one prompt formulation and one state encoding; 5 days; n=238. A
different encoding could change the numbers — but the bar to clear is a
one-line baseline, and the direction result is below the base rates.
