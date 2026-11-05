# ADR 0007: Worker and durable queue

- Status: accepted
- Decision: use a separate asyncio worker that atomically claims queued Postgres rows; retain Arq as a future option but do not add a second queue of record.
- Rationale: the database is already the durable source of run lifecycle and approval state; atomic claims and checkpoints support the single-worker demo with minimal moving parts.
- Consequence: scale-out requires leases or a broker-backed queue and shared event pub/sub. Redis is provisioned but not yet the run queue.
