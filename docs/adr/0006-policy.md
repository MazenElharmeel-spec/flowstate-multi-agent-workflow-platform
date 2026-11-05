# ADR 0006: Policy engine

- Status: accepted
- Decision: use explicit Python policy rules that return a named rule, risk, reason, and diff before any sensitive action.
- Rationale: financial thresholds and prompt-injection defenses must be deterministic, testable, and visible in the audit timeline.
- Consequence: policy rules should move to reviewed declarative config as policy count grows.
