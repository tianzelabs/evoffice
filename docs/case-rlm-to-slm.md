# RLM → SLM: compiling recursive analytics behaviour

This is a sub-experiment of [Case B — RLM for analytics](case-rlm-analytics.md).
It does not ask whether a smaller model can answer analytics questions in
language. It asks whether the high-frequency behaviour of an RLM using a REPL
can be learned by a small local model and executed inside the data environment.

## Research question

Can a small, locally deployed model internalise the common data-manipulation
steps of an RLM, reducing dependence on an external REPL while preserving
analytical correctness on unseen market data?

## Hypothesis

An RLM's repeated REPL behaviour contains a compressible operational layer:
schema inspection, profiling, filtering, window calculations, aggregation,
comparison, validation, and workspace maintenance. A small model trained on
these trajectories should be able to execute that layer faster and more cheaply
than the original RLM, while the RLM remains responsible for recursion,
planning, novel operations, and recovery from failure.

This is not the claim that a small model can replace the RLM. The claim is that
part of the RLM can be compiled into a reusable local policy.

## System boundary

```text
office market stream
        ↓
Rust analytics environment
        ↓
workspace owned by the experiment
        ↓
RLM planner ────────┐
        ↓           │ fallback / teacher
   local SLM  ←─────┘
        ↓
structured data observation
        ↓
held-out office evaluator
```

The SLM does not write a prose answer. It receives a structured workspace state
and returns a typed operation or a stop/fallback decision. The actual data and
numeric results remain outside the model in the Rust workspace and REPL. This
prevents the weights from becoming a hidden copy of the market data.

## What is distilled

The training unit is an RLM/REPL transition:

```text
(workspace state, available objects, task state)
        → REPL operation
        → observation and workspace delta
```

Initial operation vocabulary:

- inspect schema and data freshness;
- profile missingness, cardinality, and distributions;
- filter and select a time window;
- create rolling returns and volatility;
- aggregate by time, regime, or instrument;
- compare two windows;
- detect and inspect outliers;
- validate an intermediate object on a held-out slice;
- reuse, invalidate, or checkpoint a workspace object;
- escalate to the RLM/REPL when the operation is novel or confidence is low.

## Training loop

### Phase 0 — trajectory collection

Run the existing RLM against reproducible historical market windows. Record the
workspace state before each REPL call, the exact operation, the result, cost,
and whether the resulting object was later reused.

### Phase 1 — behaviour distillation

Train a small open-source model on the recorded transitions. The first target
is structured operation selection and parameters, not language generation.
Numerical results are always recomputed by the environment.

### Phase 2 — closed-loop operation

Let the SLM handle operations from its supported vocabulary. Compare it with
the teacher RLM at matched tasks and budgets. Unknown operations must fall back
to the real REPL; the SLM is not allowed to fabricate a result.

### Phase 3 — selective compilation

Compile only the operations where the SLM is both accurate and cheaper. Keep
rare, difficult, or failure-prone operations on the RLM/REPL path.

## Evaluation

The office market environment is the evaluation world, not merely a data
source. Every run is scored on a future or held-out market window that the
model cannot inspect during training.

Primary measures:

- correctness of intermediate numeric objects;
- correctness of the final analytics result;
- held-out transfer across market regimes;
- REPL calls avoided;
- wall-clock latency and local compute cost;
- workspace object reuse;
- fallback rate and fallback correctness;
- invalid-operation rate;
- provenance completeness and reproducibility.

The experiment must not use live trading or P&L as the first success criterion.
The first claim is about analytical behaviour. Paper-market outcomes may be a
later downstream measure, never a substitute for validating the data work.

## Baselines

1. RLM + real REPL, with no SLM.
2. SLM trained on RLM trajectories, with REPL fallback.
3. SLM without fallback, to measure the cost of overclaiming competence.
4. Flat-context model given the same raw data and task budget.
5. Hand-written Rust analytics operators, as an execution-speed lower bound.

All baselines use the same market windows, task seeds, evaluator, and data
access boundary.

## First minimum experiment

Use one BTC perpetual market stream and three task families:

1. rolling volatility regime construction;
2. anomaly window identification;
3. comparison of two historical windows.

Collect a small teacher set, train one local SLM policy, and test whether it can
execute at least ten consecutive valid workspace operations while preserving
numeric equality with the REPL. A successful first result is not a trading
profit. It is a measured reduction in REPL calls with no significant loss in
held-out analytical correctness.

## Falsification

The hypothesis is weakened if the SLM cannot generalise beyond memorised
trajectories, if its numeric errors require more correction than the REPL work
it saves, or if all gains disappear once fallback and compute costs are counted.
