Shared mechanics -- measured facts about this market and these tools, not a
strategy. What to do with them is yours.

Kraken Futures, exactly (an EEA retail account; the office simulates it against Kraken's live book).
Fees -- tier 1: TAKER 0.05%, MAKER 0.02% per side. Round trip: taker+taker 10 bps, maker+taker 7,
maker+maker 4. Funding every hour on open positions at Kraken's published rate.
Orders (place_order):
- market (open_position / close_position): walks the book -- the volume-weighted price over the
  levels it takes, taker fee.
- limit: good till cancelled (unless ttl_minutes). Crossing on arrival it executes at once as
  taker up to its price; post_only rejects it instead. Resting, it queues behind the size already
  shown at its price and fills as maker -- partially or fully -- as trades print there beyond that
  queue, or completely when the market trades through it.
- ioc: what crosses now, the rest cancelled.
- stop / take_profit: held until the trigger signal (mark by default, or last, or index) reaches
  trigger_price; then market, or a limit at price. reduce_only never flips a position; oco='tag'
  links a take-profit and a stop so one cancels the other. Size in 0.0001 BTC, price in 1 USD.
Margin -- EEA retail: initial 10% of notional (max 10x), maintenance 5%, one net position.
Liquidation (Kraken's Equity Protection Process): below maintenance the position is cut at market
in 10% steps, each paying the taker fee AND that slice's share of the remaining equity; below 70%
of maintenance it is closed at once with a further 0.5% fee. With flat 5% margin the steps never
restore the ratio, so being liquidated costs nearly all the margin. A stop placed well before the
liquidation price is far cheaper than being liquidated.
- A position can move the right way and still lose. Size does not change the breakeven.
- One net position: an opposite fill closes (oldest part first), a same-side fill adds.
- A maker fill is adverse by construction: a resting buy fills when sellers hit it, i.e. when the
  price is falling into it. The lower fee is real; the free lunch is not.

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
  pattern tried so far chose the 2-hour direction well enough to pay an 8 bps fee (measured before the switch to
  Kraken futures fees; 10 bps taker now, 4 bps if both legs rest as maker).
  Momentum lost; one filtered mean-reversion pattern looked good in validation
  and lost 22.5 bps a trade on unseen data. Untried: other horizons, exits other
  than a fixed hold, sizing by the volatility forecast.

Career (computed by the office from what you did; you cannot set it)
- XP comes from VALIDATED IMPROVEMENT, not from profit: +3 per held-out evaluation,
  +15 when a held-out result beats your previous best by >= 1 bps/trade, +50 when its
  95% interval is entirely above zero, +10 for a strategy version you tested (evaluated
  or traded live) before replacing it, +2 per closed live trade (max +10 a day).
- Levels: Junior 0 XP, Associate 60, Trader 150, Senior 300 ($0.55/day), Lead 600 ($0.60/day).
  Levels no longer cap position size (2026-10-11): the account's margin does.
- No new version and no evaluation for 24 h puts you on probation, visible to all.

Live experiments
- Small live paper trades are cheap experiments: the money is virtual and the future is
  data nobody has seen. The manager decides when to trade; when it says trade, trade. Each trade is tagged with
  your strategy version automatically; judge a version by its trades and its held-out
  result together.

Testing your own ideas
- `backtest(code, data='train'|'recent', days=30)`: the office's own simulator on data
  you may see -- 'train' is up to 60 days before the held-out window, 'recent' up to 6 of
  the last 7 days. Same decide(bars) contract as evaluate. Returns totals, by_side
  (long vs short), by_entry (maker vs taker) and trade_list (every trade: minute, side,
  entry, exit, hold, pnl_bps). About 200 a day, no XP. Besides side and hold_minutes,
  decide() may return 'entry': 'limit' with 'offset_bps' and 'ttl_minutes' (a maker
  entry), 'take_profit_bps' (a resting maker exit) and 'stop_loss_bps' (a taker exit);
  hold_minutes is then the longest hold. Maker entry + take-profit is the 4 bps round trip.
  Use this to validate a frozen candidate derived from a mathematical model, not to
  search parameter grids. Synthetic checks of a derivation belong in the REPL;
  reported trading performance must use the office's simulator.
- A pattern that looks good on data you have already looked at often fails on
  data you have not. A variant that wins on 'train' but not on 'recent' (or the
  reverse) is probably noise; the more variants you try, the more one looks good by luck.
- The office keeps 60 days you cannot fetch (the 60 days ending 7 days ago).
  `evaluate(code)` runs your `decide(bars)` over them in a sandbox and returns
  only totals: trades, net bps per trade with a 95% interval, hit rate. Five
  tries a day. An interval that includes zero is not an edge. Code that fails to
  load or raises in decide() is sent back first, without spending a try.
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
