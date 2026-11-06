# Synthetic examples

These files contain invented workflow request payloads and scenario summaries that map to the local MCP sandbox fixtures in `backend/mcp_servers/`. They are included for local testing and documentation only.

- [`customer-escalation-request.json`](customer-escalation-request.json) queues a synthetic damaged-delivery scenario.
- [`weekly-ops-digest-request.json`](weekly-ops-digest-request.json) queues a short digest run.
- [`synthetic-support-scenarios.json`](synthetic-support-scenarios.json) describes the three seeded support scenarios, including the prompt-injection safety case.

No external customer dataset was imported. Email addresses in the MCP fixtures use `example.com` placeholders; the payment service is a local sandbox.
