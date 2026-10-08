# tests/

Few tests, each one able to change a decision if it failed. The load-bearing one,
carried from agent-world: **a position that moved the right way can still lose**,
because the round trip costs 8bps. If that test ever reports a win, the fee model
is broken and every number on the leaderboard is meaningless.
