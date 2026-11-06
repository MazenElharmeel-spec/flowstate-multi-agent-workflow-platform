"""Workflow runner compiling graphs with durable database checkpoints and handling interrupts."""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from sqlalchemy import select

from backend.app.core.errors import BudgetExceededError, PermanentError
from backend.app.db.models import WorkflowDefinition, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import (
    ESTIMATED_COST_TOTAL,
    RUN_DURATION_SECONDS,
    TOKEN_USAGE_TOTAL,
)
from backend.app.observability.tracing import tracer
from backend.app.orchestration.checkpointing import DatabaseCheckpointSaver
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.graphs.customer_escalation import build_customer_escalation_graph
from backend.app.orchestration.graphs.ops_digest import build_ops_digest_graph

logger = logging.getLogger(__name__)

checkpointer = DatabaseCheckpointSaver()


class WorkflowRunner:
    """Executes workflows asynchronously with checkpoint persistence and interruption handling."""

    def _get_graph_for_key(self, key: str) -> Any:
        if key == "customer_escalation":
            return build_customer_escalation_graph()
        elif key == "weekly_ops_digest":
            return build_ops_digest_graph()
        else:
            raise PermanentError(f"No executable graph builder for workflow key '{key}'")

    async def execute_run(
        self,
        run_id: str,
        resume_value: Any | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute or resume a run using its thread_id checkpoint."""
        trace_id = trace_id or uuid.uuid4().hex
        execution_started_at = time.perf_counter()
        async with async_session_factory() as session:
            stmt = select(WorkflowRun).where(WorkflowRun.id == run_id)
            res = await session.execute(stmt)
            run = res.scalar_one_or_none()
            if not run:
                raise PermanentError(f"Run '{run_id}' not found")

            # Fetch definition key
            def_stmt = select(WorkflowDefinition).where(
                WorkflowDefinition.id == run.workflow_definition_id
            )
            def_res = await session.execute(def_stmt)
            wf_def = def_res.scalar_one_or_none()
            if not wf_def:
                raise PermanentError(f"Definition {run.workflow_definition_id} not found")

            workflow_key = wf_def.key
            initial_inputs = run.inputs or {}

            # Transition status to running if not already
            run.status = "running"
            if not run.started_at:
                run.started_at = datetime.now(UTC)
            await session.commit()

        await event_bus.publish(
            run_id=run_id,
            event_type="run.started",
            payload={"workflow_key": workflow_key, "is_resume": resume_value is not None},
            trace_id=trace_id,
        )

        builder = self._get_graph_for_key(workflow_key)
        app = builder.compile(checkpointer=checkpointer)

        config = {
            "configurable": {
                "thread_id": run_id,
                "trace_id": trace_id,
            }
        }

        # If resuming from interrupt, pass Command(resume=resume_value), otherwise initial inputs
        input_data: Any = (
            Command(resume=resume_value)
            if resume_value is not None
            else {
                "run_id": run_id,
                "workflow_key": workflow_key,
                "inputs": initial_inputs,
                "step_count": 0,
                "tool_call_count": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "review_revisions_count": 0,
            }
        )

        final_state: dict[str, Any] = {}

        try:
            with tracer.start_as_current_span("workflow.run") as span:
                span.set_attribute("workflow.run_id", run_id)
                span.set_attribute("workflow.key", workflow_key)
                span.set_attribute("workflow.trace_id", trace_id)
                async for event in app.astream(input_data, config=config, stream_mode="values"):
                    final_state = event

            # Check if execution paused on an interrupt (human-in-the-loop approval)
            snapshot = await app.aget_state(config)
            # LangGraph versions differ in whether a pending interrupt is
            # represented on the task or only as a non-empty `next` tuple.
            has_interrupt = bool(snapshot.next) or any(t.interrupts for t in snapshot.tasks)

            clean_snapshot = {k: v for k, v in final_state.items() if not k.startswith("__")}

            if has_interrupt:
                logger.info("Run %s paused at approval gate", run_id)
                async with async_session_factory() as session:
                    res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                    run_rec = res.scalar_one()
                    run_rec.status = "waiting_approval"
                    run_rec.current_node = "policy_gate"
                    run_rec.state_snapshot = clean_snapshot
                    run_rec.worker_id = None
                    run_rec.lease_expires_at = None
                    await session.commit()

                await event_bus.publish(
                    run_id=run_id,
                    event_type="run.waiting_approval",
                    payload={"status": "waiting_approval"},
                    trace_id=trace_id,
                )
                return {"status": "waiting_approval", "run_id": run_id}

            # Completed normally
            now = datetime.now(UTC)
            async with async_session_factory() as session:
                res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                run_rec = res.scalar_one()
                run_rec.status = "completed"
                run_rec.outputs = final_state.get("agent_outputs", {})
                run_rec.state_snapshot = clean_snapshot
                run_rec.current_node = final_state.get("current_node")
                run_rec.step_count = final_state.get("step_count", run_rec.step_count)
                run_rec.total_tokens = final_state.get("total_tokens", run_rec.total_tokens)
                run_rec.estimated_cost_usd = final_state.get(
                    "estimated_cost_usd", run_rec.estimated_cost_usd
                )
                run_rec.finished_at = now
                run_rec.worker_id = None
                run_rec.lease_expires_at = None
                await session.commit()

            RUN_DURATION_SECONDS.labels(workflow_key=workflow_key).observe(
                time.perf_counter() - execution_started_at
            )
            TOKEN_USAGE_TOTAL.labels(workflow_key=workflow_key).inc(run_rec.total_tokens)
            ESTIMATED_COST_TOTAL.labels(workflow_key=workflow_key).inc(
                run_rec.estimated_cost_usd
            )

            return final_state

        except GraphInterrupt:
            # GraphInterrupt caught directly
            async with async_session_factory() as session:
                res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                run_rec = res.scalar_one()
                run_rec.status = "waiting_approval"
                run_rec.current_node = "policy_gate"
                run_rec.worker_id = None
                run_rec.lease_expires_at = None
                await session.commit()

            await event_bus.publish(
                run_id=run_id,
                event_type="run.waiting_approval",
                payload={"status": "waiting_approval"},
                trace_id=trace_id,
            )
            return {"status": "waiting_approval", "run_id": run_id}

        except BudgetExceededError as budget_exc:
            logger.warning("Run %s exceeded budget: %s", run_id, budget_exc)
            now = datetime.now(UTC)
            async with async_session_factory() as session:
                res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                run_rec = res.scalar_one()
                run_rec.status = "failed"
                run_rec.finished_at = now
                run_rec.worker_id = None
                run_rec.lease_expires_at = None
                await session.commit()

            await event_bus.publish(
                run_id=run_id,
                event_type="run.failed",
                payload={"error": "BudgetExceededError", "message": budget_exc.message},
                trace_id=trace_id,
            )
            raise

        except Exception as exc:
            logger.exception("Run %s encountered unhandled error: %s", run_id, exc)
            now = datetime.now(UTC)
            async with async_session_factory() as session:
                res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                run_rec = res.scalar_one()
                run_rec.status = "failed"
                run_rec.finished_at = now
                run_rec.worker_id = None
                run_rec.lease_expires_at = None
                await session.commit()

            await event_bus.publish(
                run_id=run_id,
                event_type="run.failed",
                payload={"error": exc.__class__.__name__, "message": str(exc)},
                trace_id=trace_id,
            )
            raise


runner = WorkflowRunner()
