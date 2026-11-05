"""LangGraph workflow definition for Weekly Ops Digest."""

import json
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.app.agents.ops_digest import OPS_DIGEST_SYSTEM_PROMPT
from backend.app.llm.base import LLMMessage
from backend.app.llm.gateway import get_llm_provider
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.state import WorkflowState


async def metrics_collector_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="metrics_collector",
        trace_id=trace_id,
    )

    metrics = {
        "period": "Last 7 Days",
        "total_workflow_runs": 142,
        "success_rate_pct": 98.6,
        "p95_run_latency_s": 5.4,
        "mcp_server_uptime_pct": 99.9,
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="metrics_collector",
        payload=metrics,
        trace_id=trace_id,
    )

    return {
        "current_node": "metrics_collector",
        "agent_outputs": {"metrics": metrics},
        "step_count": state.get("step_count", 0) + 1,
    }


async def anomaly_analyzer_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    metrics = state.get("agent_outputs", {}).get("metrics", {})

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="anomaly_analyzer",
        trace_id=trace_id,
    )

    llm = get_llm_provider()
    messages = [
        LLMMessage(role="system", content=OPS_DIGEST_SYSTEM_PROMPT),
        LLMMessage(role="user", content=f"Analyze platform telemetry:\n{json.dumps(metrics)}"),
    ]
    res = await llm.generate(messages=messages)
    analysis = res.structured_output or {
        "anomalies_detected": [],
        "system_health_status": "healthy",
        "executive_summary": "All workflow services operational within target parameters.",
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="anomaly_analyzer",
        payload=analysis,
        trace_id=trace_id,
    )

    return {
        "current_node": "anomaly_analyzer",
        "agent_outputs": {"analysis": analysis},
        "step_count": state.get("step_count", 0) + 1,
        "total_tokens": state.get("total_tokens", 0) + res.total_tokens,
    }


async def digest_reporter_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    analysis = state.get("agent_outputs", {}).get("analysis", {})

    digest_output = {
        "report_title": "Weekly Platform Operations Summary",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "published",
        "digest": analysis,
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="run.completed",
        node_name="digest_reporter",
        payload=digest_output,
        trace_id=trace_id,
    )

    return {
        "current_node": "digest_reporter",
        "is_completed": True,
        "agent_outputs": {"report": digest_output},
        "step_count": state.get("step_count", 0) + 1,
    }


def build_ops_digest_graph() -> Any:
    workflow = StateGraph(WorkflowState)
    workflow.add_node("metrics_collector", metrics_collector_node)
    workflow.add_node("anomaly_analyzer", anomaly_analyzer_node)
    workflow.add_node("digest_reporter", digest_reporter_node)

    workflow.add_edge(START, "metrics_collector")
    workflow.add_edge("metrics_collector", "anomaly_analyzer")
    workflow.add_edge("anomaly_analyzer", "digest_reporter")
    workflow.add_edge("digest_reporter", END)

    return workflow
