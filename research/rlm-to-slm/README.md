# RLM → SLM trajectory crate

This crate defines the first stable boundary for the EvOffice experiment:

```text
WorkspaceState → Action → Observation → WorkspaceState
```

The REPL or Rust executor remains authoritative for data and numeric results.
The model learns the choice of operation and parameters from `Trajectory`
records; it does not receive hidden raw market snapshots as model memory.

The schema is intentionally small and typed. Add an operation only when a
recorded RLM trajectory needs it and the evaluator can verify it.
