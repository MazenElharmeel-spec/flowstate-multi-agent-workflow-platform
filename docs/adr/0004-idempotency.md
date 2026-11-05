# ADR 0004: Write idempotency

- Status: accepted
- Decision: derive payment idempotency keys from stable run/action identity and have the payment sandbox return the original result on duplicate keys.
- Rationale: at-least-once execution is required for worker crash recovery.
- Consequence: downstream MCP write providers must honor idempotency keys before production use.
