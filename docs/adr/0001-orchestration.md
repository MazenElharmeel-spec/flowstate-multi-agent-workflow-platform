# ADR 0001: LangGraph orchestration

- Status: accepted
- Decision: use LangGraph `StateGraph` for explicit routing, bounded loops, interrupts, and checkpointed execution.
- Rationale: the platform needs inspectable graph state and a first-class human approval interrupt. Nodes remain ordinary typed Python functions, and routing is deterministic.
- Consequence: graph definitions are built in code and selected by versioned workflow key; persisted arbitrary graph JSON is descriptive metadata today.
