# Research implementations

This directory contains experimental implementation code for EvOffice's
research cases. It is separate from the production office runtime in
`server/`, `agents/`, and `web/`.

## Current experiment

`rlm-to-slm/` contains the Rust trajectory and workspace boundary for the
RLM-to-SLM analytics experiment:

```text
WorkspaceState → Action → Observation → WorkspaceState
```

It is intentionally small and does not yet contain a model or a market-data
connector. Those are added only after the trajectory schema and evaluator
contract are stable.
