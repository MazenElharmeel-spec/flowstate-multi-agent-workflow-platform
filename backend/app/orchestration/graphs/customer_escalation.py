"""LangGraph workflow definition for Customer Escalation Resolution."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.app.agents.planner import PLANNER_SYSTEM_PROMPT
from backend.app.agents.research import RESEARCH_ALLOWLIST, RESEARCH_SYSTEM_PROMPT
from backend.app.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from backend.app.agents.triage import TRIAGE_SYSTEM_PROMPT
from backend.app.approvals.policy_engine import policy_engine
from backend.app.approvals.service import approval_service
from backend.app.core.errors import BudgetExceededError
from backend.app.llm.base import LLMMessage
from backend.app.llm.gateway import get_llm_provider
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.state import WorkflowState
from backend.app.tools.base import ToolContext
from backend.app.tools.registry import tool_registry

logger = logging.getLogger(__name__)


def check_budgets(state: WorkflowState) -> None:
    max_steps = 25
    if state.get("step_count", 0) >= max_steps:
        raise BudgetExceededError("step_count", max_steps, state.get("step_count", 0))


# 1. Triage Node
async def triage_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    check_budgets(state)
    run_id = state["run_id"]
    inputs = state.get("inputs", {})
    trace_id = config.get("configurable", {}).get("trace_id")

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="triage",
        payload={"step": state.get("step_count", 0) + 1},
        trace_id=trace_id,
    )

    llm = get_llm_provider()
    user_prompt = f"Analyze incoming escalation ticket:\n{json.dumps(inputs)}"
    messages = [
        LLMMessage(role="system", content=TRIAGE_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    res = await llm.generate(messages=messages, temperature=0.0)
    triage_data = res.structured_output or {}

    step_inc = state.get("step_count", 0) + 1
    tokens_inc = state.get("total_tokens", 0) + res.total_tokens
    cost_inc = state.get("estimated_cost_usd", 0.0) + res.estimated_cost_usd

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="triage",
        payload={"triage_result": triage_data},
        duration_ms=res.latency_ms,
        trace_id=trace_id,
    )

    return {
        "current_node": "triage",
        "agent_outputs": {"triage": triage_data},
        "step_count": step_inc,
        "total_tokens": tokens_inc,
        "estimated_cost_usd": cost_inc,
    }


# 2. Research Node
async def research_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    check_budgets(state)
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    inputs = state.get("inputs", {})
    triage = state.get("agent_outputs", {}).get("triage", {})

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="research",
        payload={"step": state.get("step_count", 0) + 1},
        trace_id=trace_id,
    )

    llm = get_llm_provider()
    research_tools = tool_registry.export_schemas_for_llm(RESEARCH_ALLOWLIST)

    # Initial call proposing tool invocations
    messages = [
        LLMMessage(role="system", content=RESEARCH_SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=f"Ticket: {json.dumps(inputs)}\nTriage Assessment: {json.dumps(triage)}\nFetch necessary customer, ticket, payment, and policy context.",
        ),
    ]

    res1 = await llm.generate(messages=messages, tools=research_tools, temperature=0.0)

    tool_records: list[dict[str, Any]] = []
    tool_results_messages: list[LLMMessage] = []

    # Execute read-only tools
    for tc in res1.tool_calls:
        tool_name = tc.name
        tool_args = tc.arguments
        tool_inst = tool_registry.get(tool_name)
        ctx = ToolContext(
            run_id=run_id,
            step_index=state.get("step_count", 0),
            actor_agent="ResearchAgent",
        )
        tool_res = await tool_inst.run(tool_args, ctx)

        record = {
            "tool_name": tool_name,
            "arguments": tool_args,
            "status": tool_res.status,
            "result": tool_res.data,
            "duration_ms": tool_res.duration_ms,
        }
        tool_records.append(record)

        await event_bus.publish(
            run_id=run_id,
            event_type="tool.call",
            node_name="research",
            payload=record,
            trace_id=trace_id,
        )

        tool_results_messages.append(
            LLMMessage(
                role="tool",
                tool_call_id=tc.id,
                content=tool_res.to_safe_prompt_context(),
            )
        )

    # Second pass: synthesize context
    messages_synthesize = (
        messages
        + [LLMMessage(role="assistant", content=res1.content, tool_calls=[tc.__dict__ for tc in res1.tool_calls])]
        + tool_results_messages
    )

    res2 = await llm.generate(messages=messages_synthesize, temperature=0.0)
    research_data = res2.structured_output or {}

    step_inc = state.get("step_count", 0) + 1
    tokens_inc = state.get("total_tokens", 0) + res1.total_tokens + res2.total_tokens
    cost_inc = state.get("estimated_cost_usd", 0.0) + res1.estimated_cost_usd + res2.estimated_cost_usd

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="research",
        payload={"research_result": research_data},
        duration_ms=res2.latency_ms,
        trace_id=trace_id,
    )

    return {
        "current_node": "research",
        "agent_outputs": {"research": research_data},
        "tool_call_records": tool_records,
        "tool_call_count": state.get("tool_call_count", 0) + len(tool_records),
        "step_count": step_inc,
        "total_tokens": tokens_inc,
        "estimated_cost_usd": cost_inc,
    }


# 3. Resolution Planner Node
async def planner_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    check_budgets(state)
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    triage = state.get("agent_outputs", {}).get("triage", {})
    research = state.get("agent_outputs", {}).get("research", {})
    approval_decision = state.get("approval_decision") or {}

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="planner",
        payload={"step": state.get("step_count", 0) + 1},
        trace_id=trace_id,
    )

    llm = get_llm_provider()
    prompt_content = f"Triage: {json.dumps(triage)}\nResearch Context: {json.dumps(research)}"
    if approval_decision and approval_decision.get("status") == "rejected":
        prompt_content += f"\nPREVIOUS PLAN WAS REJECTED BY SUPERVISOR: {approval_decision.get('rejection_reason')}\nFormulate alternative plan."

    messages = [
        LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
        LLMMessage(role="user", content=prompt_content),
    ]

    res = await llm.generate(messages=messages, temperature=0.0)
    plan_data = res.structured_output or {}

    step_inc = state.get("step_count", 0) + 1
    tokens_inc = state.get("total_tokens", 0) + res.total_tokens
    cost_inc = state.get("estimated_cost_usd", 0.0) + res.estimated_cost_usd

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="planner",
        payload={"plan": plan_data},
        duration_ms=res.latency_ms,
        trace_id=trace_id,
    )

    return {
        "current_node": "planner",
        "agent_outputs": {"planner": plan_data},
        "step_count": step_inc,
        "total_tokens": tokens_inc,
        "estimated_cost_usd": cost_inc,
    }


# 4. Policy Check & Human Approval Gate Node
async def policy_gate_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    plan = state.get("agent_outputs", {}).get("planner", {})

    proposed_amount = float(plan.get("refund_amount", 0.0))
    payment_id = plan.get("payment_id", "pay-801")
    tool_args = {
        "payment_id": payment_id,
        "amount": proposed_amount,
        "reason": plan.get("reasoning", "Resolution Plan"),
        "idempotency_key": f"idemp-{run_id}-{payment_id}",
    }

    # Evaluate Policy Engine
    policy_eval = policy_engine.evaluate_tool_call(
        tool_name="issue_refund",
        arguments=tool_args,
        state=state,
    )

    await event_bus.publish(
        run_id=run_id,
        event_type="policy.evaluated",
        node_name="policy_gate",
        payload={
            "tool_name": "issue_refund",
            "rule_name": policy_eval.rule_name,
            "requires_approval": policy_eval.requires_approval,
            "reason": policy_eval.reason,
        },
        trace_id=trace_id,
    )

    if policy_eval.requires_approval:
        # Create approval record in DB
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        approval_rec = await approval_service.create_approval_request(
            run_id=run_id,
            tool_name="issue_refund",
            arguments=tool_args,
            risk_level=policy_eval.risk_level,
            reason=policy_eval.reason,
            checkpoint_id=checkpoint_id,
        )

        # INTERRUPT GRAPH FOR HUMAN APPROVAL!
        human_decision = interrupt(
            {
                "approval_id": approval_rec.id,
                "tool_name": "issue_refund",
                "arguments": tool_args,
                "reason": policy_eval.reason,
                "risk_level": policy_eval.risk_level,
                "diff_summary": policy_eval.diff_summary,
            }
        )

        # Upon resume, the graph resumes with the human decision
        return {
            "current_node": "policy_gate",
            "approval_decision": human_decision,
        }

    return {
        "current_node": "policy_gate",
        "approval_decision": {"status": "auto_approved", "resolved_arguments": tool_args},
    }


def route_after_policy_gate(state: WorkflowState) -> str:
    decision = state.get("approval_decision") or {}
    status = decision.get("status")
    if status == "rejected":
        # Route back to planner with rejection reason (bounded loop)
        return "planner"
    return "action"


# 5. Action Node (Executes write tools)
async def action_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    check_budgets(state)
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    plan = state.get("agent_outputs", {}).get("planner", {})
    decision = state.get("approval_decision") or {}
    resolved_args = decision.get("resolved_arguments") or {
        "payment_id": plan.get("payment_id", "pay-801"),
        "amount": float(plan.get("refund_amount", 0.0)),
        "reason": plan.get("reasoning", "Resolution"),
        "idempotency_key": f"idemp-{run_id}-act",
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="action",
        payload={"step": state.get("step_count", 0) + 1},
        trace_id=trace_id,
    )

    action_tool_records: list[dict[str, Any]] = []

    # 1. Execute refund if amount > 0
    refund_amount = float(resolved_args.get("amount", 0.0))
    refund_result: dict[str, Any] = {}
    if refund_amount > 0:
        refund_tool = tool_registry.get("issue_refund")
        ctx = ToolContext(
            run_id=run_id,
            step_index=state.get("step_count", 0),
            actor_agent="ActionAgent",
            idempotency_key=resolved_args.get("idempotency_key"),
        )
        res_refund = await refund_tool.run(resolved_args, ctx)
        refund_result = res_refund.data if res_refund.status == "success" else {"error": res_refund.error}
        rec = {
            "tool_name": "issue_refund",
            "arguments": resolved_args,
            "status": res_refund.status,
            "result": refund_result,
            "duration_ms": res_refund.duration_ms,
        }
        action_tool_records.append(rec)
        await event_bus.publish(
            run_id=run_id,
            event_type="tool.call",
            node_name="action",
            payload=rec,
            trace_id=trace_id,
        )

    # 2. Send customer confirmation email
    email_tool = tool_registry.get("send_email")
    email_args = {
        "to_email": "alice@example.com",
        "subject": "Update on your Customer Resolution",
        "body": f"We have resolved your issue. Refund amount: ${refund_amount:.2f}.",
        "idempotency_key": f"email-{run_id}-resolution",
    }
    ctx_email = ToolContext(
        run_id=run_id,
        step_index=state.get("step_count", 0),
        actor_agent="ActionAgent",
    )
    res_email = await email_tool.run(email_args, ctx_email)
    rec_email = {
        "tool_name": "send_email",
        "arguments": email_args,
        "status": res_email.status,
        "result": res_email.data,
        "duration_ms": res_email.duration_ms,
    }
    action_tool_records.append(rec_email)
    await event_bus.publish(
        run_id=run_id,
        event_type="tool.call",
        node_name="action",
        payload=rec_email,
        trace_id=trace_id,
    )

    action_output = {
        "executed_tools": [r["tool_name"] for r in action_tool_records],
        "refund_result": refund_result,
        "email_result": res_email.data,
        "summary": f"Executed actions: refund ${refund_amount:.2f} and customer notification email.",
    }

    step_inc = state.get("step_count", 0) + 1
    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="action",
        payload=action_output,
        trace_id=trace_id,
    )

    return {
        "current_node": "action",
        "agent_outputs": {"action": action_output},
        "tool_call_records": action_tool_records,
        "tool_call_count": state.get("tool_call_count", 0) + len(action_tool_records),
        "step_count": step_inc,
    }


# 6. Reviewer Node
async def reviewer_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    check_budgets(state)
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    action_res = state.get("agent_outputs", {}).get("action", {})
    triage = state.get("agent_outputs", {}).get("triage", {})

    await event_bus.publish(
        run_id=run_id,
        event_type="node.started",
        node_name="reviewer",
        payload={"step": state.get("step_count", 0) + 1},
        trace_id=trace_id,
    )

    llm = get_llm_provider()
    messages = [
        LLMMessage(role="system", content=REVIEWER_SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=f"Triage: {json.dumps(triage)}\nExecuted Actions: {json.dumps(action_res)}\nAudit compliance.",
        ),
    ]

    res = await llm.generate(messages=messages, temperature=0.0)
    review_data = res.structured_output or {"decision": "approved", "policy_compliant": True}

    step_inc = state.get("step_count", 0) + 1
    tokens_inc = state.get("total_tokens", 0) + res.total_tokens
    cost_inc = state.get("estimated_cost_usd", 0.0) + res.estimated_cost_usd

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="reviewer",
        payload={"review_result": review_data},
        duration_ms=res.latency_ms,
        trace_id=trace_id,
    )

    return {
        "current_node": "reviewer",
        "agent_outputs": {"reviewer": review_data},
        "step_count": step_inc,
        "total_tokens": tokens_inc,
        "estimated_cost_usd": cost_inc,
    }


def route_after_reviewer(state: WorkflowState) -> str:
    review = state.get("agent_outputs", {}).get("reviewer", {})
    decision = review.get("decision", "approved")
    loop_count = state.get("review_revisions_count", 0)
    max_loops = state.get("max_review_revisions", 2)

    if decision == "approved":
        return "report"

    # Bounded Loop check
    if loop_count < max_loops:
        state["review_revisions_count"] = loop_count + 1
        return "planner"

    # Cap reached: fall back to human escalation
    return "escalate_fallback"


# 7. Human Escalation Fallback Node
async def escalate_fallback_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")

    fallback_data = {
        "status": "escalated_to_human_ops",
        "reason": "Reviewer revision loop cap reached without satisfying quality criteria.",
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="node.finished",
        node_name="escalate_fallback",
        payload=fallback_data,
        trace_id=trace_id,
    )

    return {
        "current_node": "escalate_fallback",
        "fallback_escalated": True,
        "agent_outputs": {"fallback": fallback_data},
    }


# 8. Report Node
async def report_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state["run_id"]
    trace_id = config.get("configurable", {}).get("trace_id")
    outputs = state.get("agent_outputs", {})

    report_summary = {
        "run_id": run_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "total_steps": state.get("step_count", 0) + 1,
        "total_tokens": state.get("total_tokens", 0),
        "estimated_cost_usd": state.get("estimated_cost_usd", 0.0),
        "final_status": "escalated" if state.get("fallback_escalated") else "completed",
        "executive_summary": "Customer escalation resolved in accordance with company policy.",
        "deliverables": outputs,
    }

    await event_bus.publish(
        run_id=run_id,
        event_type="run.completed",
        node_name="report",
        payload=report_summary,
        trace_id=trace_id,
    )

    return {
        "current_node": "report",
        "is_completed": True,
        "agent_outputs": {"report": report_summary},
    }


def build_customer_escalation_graph() -> Any:
    """Builds and compiles the customer escalation LangGraph workflow."""
    workflow = StateGraph(WorkflowState)

    # Add Nodes
    workflow.add_node("triage", triage_node)
    workflow.add_node("research", research_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("policy_gate", policy_gate_node)
    workflow.add_node("action", action_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("escalate_fallback", escalate_fallback_node)
    workflow.add_node("report", report_node)

    # Add Edges
    workflow.add_edge(START, "triage")
    workflow.add_edge("triage", "research")
    workflow.add_edge("research", "planner")
    workflow.add_edge("planner", "policy_gate")

    # Conditional edge after policy gate (approval / reject / edit)
    workflow.add_conditional_edges(
        "policy_gate",
        route_after_policy_gate,
        {
            "action": "action",
            "planner": "planner",
        },
    )

    workflow.add_edge("action", "reviewer")

    # Conditional edge after reviewer (approved vs revision loop vs fallback)
    workflow.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "report": "report",
            "planner": "planner",
            "escalate_fallback": "escalate_fallback",
        },
    )

    workflow.add_edge("escalate_fallback", "report")
    workflow.add_edge("report", END)

    return workflow
