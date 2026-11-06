# API reference

The running API serves interactive Swagger docs at `/docs` and its OpenAPI 3 schema at `/openapi.json`. The local Compose gateway base URL is `http://localhost:8100`; application routes are under `/api/v1`.

## Authentication

Most routes require a JWT in the header:

```http
Authorization: Bearer <access_token>
```

Obtain a local demo token:

```bash
curl -sS http://localhost:8100/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"operator@example.com","password":"OperatorSecret123!"}'
```

The response contains `access_token`, `token_type`, and `role`. Use the access token only against the local demo.

## Routes

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | Public | Exchange demo credentials for a JWT. |
| `GET` | `/auth/me` | Authenticated | Return the current user. |
| `POST` | `/auth/register` | Admin | Register a user and role. |
| `GET` | `/workflows` | Authenticated | List active, versioned workflow definitions. |
| `GET` | `/workflows/{key}` | Authenticated | Read the latest or selected workflow version. |
| `POST` | `/workflows` | Admin | Register a workflow definition. |
| `POST` | `/runs` | Operator | Validate inputs and enqueue a workflow run. |
| `GET` | `/runs` | Authenticated | List runs; supports `status`, `workflow`, `limit`, and `offset`. |
| `GET` | `/runs/{run_id}` | Authenticated | Read run status, inputs, outputs, and usage. |
| `GET` | `/runs/{run_id}/events` | Authenticated | Read the ordered event log. |
| `GET` | `/runs/{run_id}/checkpoints` | Authenticated | Inspect persisted checkpoints. |
| `GET` | `/runs/{run_id}/stream` | Authenticated | Stream run events as Server-Sent Events. |
| `POST` | `/runs/{run_id}/cancel` | Operator | Cancel a non-terminal run. |
| `POST` | `/runs/{run_id}/retry` | Operator | Retry a failed run with its original inputs/version. |
| `GET` | `/approvals` | Authenticated | List approvals; supports `status`, `limit`, and `offset`. |
| `GET` | `/approvals/{approval_id}` | Authenticated | Read an approval request. |
| `POST` | `/approvals/{approval_id}/decide` | Approver | Approve, reject, or edit and approve a proposed action. |
| `GET` | `/tools` | Authenticated | List registered tool schemas and risk metadata. |
| `GET` | `/healthz` | Public | Liveness probe. |
| `GET` | `/readyz` | Public | Database and Redis readiness. |
| `GET` | `/metrics` | Public | Prometheus metrics. |

## Start a demo run

With a valid operator token in `$TOKEN`, enqueue the synthetic ticket example:

```bash
curl -sS http://localhost:8100/api/v1/runs \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data @examples/customer-escalation-request.json
```

The response is a version-pinned run record. Poll `GET /runs/{run_id}`, read the event log, or connect to the authenticated SSE endpoint. Customer escalation may pause at `waiting_approval` until an approver decides.

Example payloads are in [`../examples/`](../examples/). Request and response schemas are authoritative in the interactive docs and OpenAPI document.
