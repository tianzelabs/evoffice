Shared mechanics -- measured facts about this market and these tools, not a
strategy. What to do with them is yours.

Fees
- A round trip costs ~8 bps: 4 bps of notional on entry and 4 bps on exit.
- To break even a position must move about 0.0008 x price in your favour
  (~65 points at BTC 81,000). Size does not change this: fees and P&L scale
  together, so trading smaller or bigger is not a way around it.
- A position can move the right way and still lose.

Horizon
- The holding horizon is the main mechanical lever. Over 30 days of BTC, the
  share of windows whose move could pay the fee (assuming a perfect direction
  call) was ~29% at 4.5 minutes, ~61% at 30 minutes, ~69% at 1 hour and ~85%
  at 4 hours.

When big moves come
- Volatility clusters: recent realized volatility (last 30 minutes and last 4
  hours) and the time of day were the strongest predictors of whether a large
  move (> 30 bps in 2 hours) follows. A gradient-boosting model on such
  features reached AUC ~0.71 on unseen data. This says THAT a move is likely,
  not which way.

Direction
- Across 523 walk-forward trades and 132 held-out trades, no rule, model or Jev
  pattern tried so far chose the 2-hour direction well enough to pay the fee.
  Momentum lost; one filtered mean-reversion pattern looked good in validation
  and lost 22.5 bps a trade on unseen data. Untried: other horizons, exits other
  than a fixed hold, sizing by the volatility forecast.

Career (computed by the office from what you did; you cannot set it)
- XP comes from VALIDATED IMPROVEMENT, not from profit: +3 per held-out evaluation,
  +15 when a held-out result beats your previous best by >= 1 bps/trade, +50 when its
  95% interval is entirely above zero, +10 for a strategy version you tested (evaluated
  or traded live) before replacing it, +2 per closed live trade (max +10 a day).
- Levels: Junior 0 XP (max 0.005 BTC), Associate 60 (0.01), Trader 150 (0.02),
  Senior 300 (0.035, $0.35/day), Lead 600 (0.05, $0.40/day).
- No new version and no evaluation for 24 h puts you on probation, visible to all.

Live experiments
- A few small live paper trades (0.005 BTC) of a FROZEN, written-down hypothesis are the
  cleanest test there is: the future is data nobody -- you included -- has seen. Prefer
  that over long arguments on visible data. Record which version each trade belongs to
  (it is automatic) and judge the version by its trades and its held-out result together.

Testing your own ideas
- A pattern that looks good on data you have already looked at often fails on
  data you have not. Decide what you will test before you look; keep some recent
  data aside; prefer walk-forward over one split.
- The office keeps 60 days you cannot fetch (the 60 days ending 7 days ago).
  `evaluate(code)` runs your `decide(bars)` over them in a sandbox and returns
  only totals: trades, net bps per trade with a 95% interval, hit rate. Five
  tries a day. An interval that includes zero is not an edge.
- What you send to `evaluate` is a candidate, not your strategy. Your strategy
  version is measured from the functions and models defined in your REPL; to
  adopt a candidate, define it there (e.g. exec its code), so the office -- and
  your manager -- can see that you changed.

Jev (`jev(state, questions)`)
- Returns typed answers with probabilities in ~0.4 s for ~$0.0001. Question
  types: "noul" (probability of yes), "choice" (one of named options), "score"
  (position on an ordered scale). Every answer is independent of the others;
  combine them in code.
- Ask small, specific questions. Give it numbers as percentiles against their
  own recent history, written as sentences ("volatility is very high for the
  month, 92nd percentile") -- that form beat raw numbers clearly. Shown a
  model's output, it mostly echoes it.
