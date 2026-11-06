# CV project description

This repository implements an agent workflow platform. It does **not** implement the RAG knowledge assistant in the example brief: there is no document ingestion pipeline, pgvector index, source citations, or retrieval evaluation. Use the following project entry only if it accurately reflects your contribution.

## SELECTED AI ENGINEERING PROJECTS

**Flowstate — Multi-Agent Workflow Platform** | Python, FastAPI, LangGraph, PostgreSQL, Redis, React, Docker

- Built checkpointed customer-escalation and operations-digest workflows with human approval, editable decisions, audit history, and retry.
- Added role-protected REST APIs, authenticated SSE event streams, Redis event fanout, and idempotent payment/email sandbox actions.
- Enabled horizontal API and worker replicas with a Docker API gateway, PostgreSQL `SKIP LOCKED` claims, and renewable worker leases; verified a local two-API/three-worker deployment.
- Delivered a responsive operations console, OpenAPI documentation, synthetic fixtures, deterministic evaluation, and automated backend tests.

**Links:** [GitHub](https://github.com/MazenElharmeel-spec/flowstate-multi-agent-workflow-platform) · Local demo instructions: [README](../README.md#run-the-demo). No public hosted demo is currently available.

## Claims to avoid for this repository

Do not describe Flowstate as a RAG assistant or claim document ingestion, semantic vector search, pgvector, grounded citations, or retrieval evaluation. Those features are not implemented here.
