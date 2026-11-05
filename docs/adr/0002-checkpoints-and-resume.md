# ADR 0002: Checkpoints and resume semantics

- Status: accepted
- Decision: store serialized LangGraph checkpoint tuples in Postgres, keyed by run/thread ID. Persist approval decisions separately and enqueue the run after the decision.
- Rationale: worker restarts can requeue stale running rows and continue from the checkpoint; approval decisions remain auditable and single-use.
- Consequence: write tools must be idempotent because a crash can happen after an external side effect and before a checkpoint commit.
