# ADR 0003: Approval records and graph interrupts

- Status: accepted
- Decision: persist a structured approval request, interrupt the graph, then resume with the approved, rejected, or edited decision.
- Rationale: the UI needs an inbox and complete audit history, while the graph needs to retain its exact continuation point.
- Consequence: approval expiry currently blocks a decision when submitted after expiry; a scheduled auto-expiry/escalation worker remains future work.
