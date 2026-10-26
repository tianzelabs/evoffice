# MiMo V2.6 Pro: one-problem mathematical smoke test

Date: 2026-10-12. The user requested a simple test after discussing MiMo as a
candidate for mathematical research. This test used isolated OpenRouter calls,
without office tools, orders, agent state changes, or a production model change.

## Protocol and its limitation

The prompt and rubric were saved before calling either model. The same question
asked for a Gaussian conditional-return derivation, a transaction-cost and
mean-variance optimizer, seven numerical examples, executable Python, and a
finite-support counterexample to extending Gaussian conclusions to all
independent distributions with the same first two moments.

The initial configuration enabled reasoning and capped total completion tokens
at 6,000 per model. Both responses exhausted all 6,000 tokens in reasoning and
returned null content with finish_reason=length. This is an unsuitable budget
configuration for assessing their completed reasoning answers; it does not show
that either model cannot solve the task.

After observing this failure, one extra request per model used the same prompt
and cap with reasoning disabled. Both completed. This adaptive rescue was kept
within the original $0.03 total test budget. There were four paid requests in
total and no automatic retries. Results below assess the completed, non-thinking
responses, not full reasoning capability. No RLM harness or tool feedback was
provided to either model.

## Observed results

| Measurement | MiMo V2.6 Pro | Claude Haiku 5.5 |
|---|---:|---:|
| Initial reasoning response | No final answer, cap reached | No final answer, cap reached |
| Initial latency | 81.21 s | 32.26 s |
| Initial billed cost | $0.00545403 | $0.00308080 |
| Non-thinking latency | 49.49 s | 10.70 s |
| Non-thinking billed cost | $0.00296670 | $0.00119660 |
| Non-thinking completion tokens | 3,140 | 2,232 |
| Generated function checks passed | 775 / 775 | 775 / 775 |
| Fully correct numerical rows in prose | 1 / 7 | 3 / 7 |

Total actually billed across all four requests: **$0.01269813**. Costs are the
API's reported usage.cost, not an estimate. No cache hits were reported.

## Independent mathematical reference

For independent Gaussian R and epsilon, write

    m(s) = tau^2 s / (tau^2 + sigma^2)
    v    = tau^2 sigma^2 / (tau^2 + sigma^2)
    J(a) = a*m(s) - k*abs(a) - (lam/2)*a^2*v

Concavity establishes the global optimum. For lam>0 it is the signed,
soft-thresholded mean, divided by lam*v and clipped to [-1,1]. For lam=0,
choose full size in the mean's direction when abs(m)>k, otherwise zero;
at equality there are ties, including zero. If m=k=lam=0 all actions tie.

At tau=12, sigma=16, k=8, lam=0.04, m(s)=0.36s and v=92.16:

| s | Optimal a | Conditional expected net bps | Maximum objective bps |
|---:|---:|---:|---:|
| -40 | -1 | 6.4 | 4.5568 |
| -24 | -0.1736111111 | 0.1111111111 | 0.0555555556 |
| -16 | 0 | 0 | 0 |
| 0 | 0 | 0 | 0 |
| 16 | 0 | 0 | 0 |
| 24 | 0.1736111111 | 0.1111111111 | 0.0555555556 |
| 40 | 1 | 6.4 | 4.5568 |

Both generated Python functions implemented the optimizer correctly for all
775 checked parameter combinations. These are numerical function checks, not
775 independent research questions or a proof for all floating-point inputs.
Code was inspected before execution in a restricted namespace, with a process
timeout. Models were not given the reference results or checker feedback.

## Material errors in the completed answers

MiMo's numerical table contradicted its own correct code in six of seven rows.
It proposed full positions at s=+/-16 despite reporting negative objectives;
zero is feasible and better. Its negative-position prose branch also gave the
wrong condition and clipping interval, although its Python had these correct.
Its counterexample left several abandoned, incorrect calculations in the final
answer. The eventual asymmetric two-point marginals have the required moments,
and at k=5 can contradict the Gaussian action, but its assertion that all four
joint outcomes have probability 1/16 is false. This was a partially successful
construction, not a clean verified proof.

Haiku's table contradicted its own correct code in four rows. It supplied zero
net returns even for nonzero profitable positions and failed to calculate the
interior actions at s=+/-24. Its counterexample used variances 1600 and 1 rather
than 144 and 256. More seriously, its stated Gaussian action of approximately
0.825 is an arithmetic error: the unconstrained action is approximately 825
and clips to +1, the same as the actual finite-support optimum. Thus that example
does not establish the claimed action contradiction.

For a simple valid counterexample with the requested variances, take independent
equiprobable R=+/-12 and epsilon=+/-16. At S=4, R=-12 surely, so the true
conditional variance is zero and, with k=8, the optimal action is -1. The
Gaussian formula gives m=1.44 and recommends zero. Covariance still fixes the
best linear predictor, but not the conditional mean or variance. The generic
mean-variance optimization structure survives with the true conditional moments;
the Gaussian formulas for those moments and signal thresholds need not survive.

## Interpretation

This run gives no reason to replace the current trader model with MiMo. MiMo's
completed response was slower and costlier, and both models needed executable
checks to catch serious inconsistencies in their prose. The test is too small,
and its completed runs disable deep reasoning, so it cannot rank their general
mathematical ability. A fuller reasoning evaluation would need an appropriate
reasoning/output budget and multiple independently checked research tasks.

Artifacts: ../../spikes/06-mimo-math/ contains the frozen prompt and rubric,
runner, price preflights, four raw responses with usage, and numerical verifier.
