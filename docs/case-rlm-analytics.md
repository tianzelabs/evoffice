# Case B — RLM for analytics

## Question

What is the value of a Recursive Language Model when it can inspect and transform
an analytics environment over multiple turns, instead of receiving all context in
one flat prompt?

The hypothesis is deliberately stronger than “RLM supports more context.” In an
analytics setting, recursion may improve the shape of work: selective inspection,
intermediate representations, calculation, hypothesis revision, stateful reuse,
and a smaller final decision surface.

## Hypotheses

**B1 — Recursive workflow improves analytics quality.** On tasks requiring
iterative inspection, computation, and revision, an RLM should outperform a
flat-context baseline with the same model and matched budget.

**B2 — The gain is workflow, not merely context length.** The advantage should
remain when context length, tool access, memory, model calls, and wall-clock budget
are matched.

**B3 — Recursive state improves diagnosis and transfer.** Useful intermediate
artifacts should be reusable across turns, reduce time to diagnose a failed
hypothesis, and transfer across analytics tasks and data regimes.

## Tasks

- anomaly investigation;
- regime description;
- feature construction;
- backtest diagnosis;
- error analysis;
- decision review and counterfactual testing.

The market sandbox is one task family, not the only benchmark. A market outcome
alone cannot establish an RLM effect.

The RLM-to-SLM compilation experiment is the implementation-focused sub-case:
[RLM → SLM: compiling recursive analytics behaviour](case-rlm-to-slm.md).
It tests whether the repeated REPL layer can be internalised by a small local
model without confusing that optimisation with replacing recursive planning.

## Matched comparison

Compare RLM and flat-context agents under the same model family, prompt family,
tool access, data availability, memory allowance, call budget, and failure rules.
Vary the task and the analytics environment. Record what was read, written,
computed, reused, and discarded.

## Measures

- held-out task quality and calibration;
- intermediate calculation error rate;
- number and usefulness of recursive sub-steps;
- context read/write and model-call cost;
- reuse of intermediate artifacts;
- time to diagnose a failed hypothesis;
- robustness to irrelevant or missing context;
- transfer across tasks and data regimes.

## Falsification

This case is weakened if the RLM advantage disappears under matched context and
budget, or if it appears only on tasks that reward extra tokens rather than a
better analytics workflow.
