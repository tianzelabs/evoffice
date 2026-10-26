# Protocol frozen before paid inference

Three independent tasks, each given to both xiaomi/mimo-v2.6-pro and
anthropic/claude-haiku-5.5 with identical task definitions and identical visible
real data. Tasks cover partial observation, stochastic control, and robust
decisions. They are prespecified model diagnostics, not profit-driven strategy
search. A correct conclusion may be that there is no evidence to trade.

Data is a frozen seven-day office snapshot of Kraken PF_XBTUSD. First 60% of
rows are train, next 20% validation, final 20% unseen holdout. The split is
chronological and was chosen before running models. Return/label pairs that
cross partitions or missing minutes are excluded. Hidden microstructure fields
are never zero-filled. The model REPL receives visible records only; no holdout
values or reference solutions. The office's separate 60-day heldout evaluator
is not accessed.

Each model/task session has a persistent Python tool with numpy/pandas/scipy,
without network, API keys, user-file access, or order tools. It may execute
code, inspect the real visible data, revise, and deliver a final answer. Native
tool messages and reasoning blocks are preserved across the tool loop. Maximum
4 API requests per model/task; request completion limit 32,768 including
reasoning, substantially above the previous 6,000. Both use reasoning enabled;
actual provider reasoning allocation differs and is recorded. If a response
hits its limit without an answer, it is an incomplete session, not a math
failure or a non-thinking replacement. No model gets the other's answer.

The total experiment has a $1 actual-spend ceiling, with conservative per-next-
request checks, and a $0.18 per-session ceiling. These are execution cost caps,
not requested goals or a profit target. No retries without recording failure.
Preserve raw usage, costs, finish reasons, generated code and tool results.

Assess separate dimensions instead of inventing an overall intelligence score:

* Mathematical derivation: correct timing, conditional moments, costs, risk
  objective, optimality, boundary cases, and assumptions.
* Numerical reproducibility: independent reference calculations on the visible
  snapshot, structural tests of the submitted pure function, and agreement of
  stated empirical values with executed outputs.
* Causality and validation: training-only estimates, prediction before target,
  gap handling, and distinction between observation and conditional-mean CIs.
* Scientific restraint: no inference of true latent drift, executable profit,
  valid iid CIs on dependent data, or uniform selection guarantees without
  evidence. No-trade is allowed and not penalized.
* Usability: completed result, tool use/errors, latency, tokens, actual cost.

After both models freeze their answers, independent code applies the same
prespecified models to the heldout data. This is one short recent holdout, not
proof of trading edge. Report limits from model assumptions and data coverage.

References: https://arxiv.org/abs/1611.07843,
https://arxiv.org/abs/1203.5957, https://arxiv.org/abs/1809.01464.
The exact small mathematical problems here are our own explicit formulations;
the papers motivate the frameworks, not these data or numerical conclusions.
