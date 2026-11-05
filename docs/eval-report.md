# Evaluation report

Generated: 2026-11-05T22:53:15.814718+00:00

## Run summary

- Dataset: 25 escalation variants (deterministic demo benchmark)
- Provider: `scripted`
- Task success rate: 100.0% (25/25)
- Correct tool selection rate: 100.0% (25/25)
- Approval policy accuracy: 100.0% (25/25 expected approvals recorded)
- Unsafe action rate: 0.0% (0/25)
- Average graph steps: 5.0
- Average estimated model cost: $0.0094
- End-to-end latency p50 / p95: 141 ms / 156 ms

## Scope

This benchmark runs the scripted happy-path escalation with 25 distinct input IDs and checks recorded approvals, expected action tools, completion, estimated provider cost, and latency. It does not establish broad model quality, prompt-injection resistance, or performance under concurrency. The unit and integration suite covers additional failure and policy paths.
