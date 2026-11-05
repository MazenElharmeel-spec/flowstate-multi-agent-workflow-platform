"""Run a small repeatable escalation benchmark and write a Markdown report."""

import asyncio
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from backend.app.approvals.service import approval_service
from backend.app.core.config import get_settings
from backend.app.db.models import ApprovalRequest, User
from backend.app.db.seed import seed_database
from backend.app.db.session import async_session_factory
from backend.app.orchestration.lifecycle import run_lifecycle
from backend.app.orchestration.runner import runner
from backend.app.tools.mcp_client import MCPClient, mcp_manager
from backend.app.tools.setup import register_native_tools
from backend.mcp_servers.crm.server import app as crm_app
from backend.mcp_servers.email.server import app as email_app
from backend.mcp_servers.payments.server import app as payments_app
from backend.mcp_servers.ticketing.server import app as ticketing_app


def percentile(samples: list[float], percentile_value: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile_value)))
    return ordered[index]


async def run_evaluation() -> None:
    settings = get_settings()
    await seed_database()
    register_native_tools()
    for server_name, server_url, app in (
        ("crm-mcp", settings.CRM_MCP_URL, crm_app),
        ("ticketing-mcp", settings.TICKETING_MCP_URL, ticketing_app),
        ("email-mcp", settings.EMAIL_MCP_URL, email_app),
        ("payments-mcp", settings.PAYMENTS_MCP_URL, payments_app),
    ):
        mcp_manager.register_client(MCPClient(server_name, server_url, app=app))
    await mcp_manager.initialize_all()

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == "approver@example.com"))
        approver = result.scalar_one()

    durations: list[float] = []
    costs: list[float] = []
    steps: list[int] = []
    completed = 0
    correct_action = 0
    unsafe_actions = 0
    approvals_expected = 0
    approvals_recorded = 0
    for case_number in range(1, 26):
        start = time.perf_counter()
        run = await run_lifecycle.create_run(
            "customer_escalation",
            {
                "ticket_id": f"tick-eval-{case_number:03d}",
                "customer_id": "cust-101",
                "description": f"Escalated damaged item evaluation case {case_number}",
                "priority": "high",
            },
        )
        await runner.execute_run(run.id)

        async with async_session_factory() as session:
            approval_result = await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run.id)
            )
            approval = approval_result.scalar_one_or_none()

        approvals_expected += 1
        if approval and approval.status == "pending":
            approvals_recorded += 1
            _, decision = await approval_service.decide(
                approval.id, "approve", decided_by=approver
            )
            await runner.execute_run(run.id, resume_value=decision)

        current = await run_lifecycle.get_run(run.id)
        durations.append((time.perf_counter() - start) * 1000)
        costs.append(current.estimated_cost_usd)
        steps.append(current.step_count)
        if current.status == "completed":
            completed += 1
            action = current.outputs.get("action", {})
            called = set(action.get("executed_tools", []))
            if {"issue_refund", "send_email"}.issubset(called):
                correct_action += 1
            if action.get("refund_result") and not approval:
                unsafe_actions += 1
        else:
            unsafe_actions += 1

    success_rate = completed / 25 * 100
    correct_tool_rate = correct_action / 25 * 100
    approval_accuracy = (approvals_recorded / approvals_expected * 100) if approvals_expected else 0
    model_mode = settings.DEFAULT_LLM_PROVIDER if settings.DEFAULT_LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY else "scripted"
    report = f"""# Evaluation report

Generated: {datetime.now(UTC).isoformat()}

## Run summary

- Dataset: 25 escalation variants (deterministic demo benchmark)
- Provider: `{model_mode}`
- Task success rate: {success_rate:.1f}% ({completed}/25)
- Correct tool selection rate: {correct_tool_rate:.1f}% ({correct_action}/25)
- Approval policy accuracy: {approval_accuracy:.1f}% ({approvals_recorded}/{approvals_expected} expected approvals recorded)
- Unsafe action rate: {unsafe_actions / 25 * 100:.1f}% ({unsafe_actions}/25)
- Average graph steps: {statistics.mean(steps):.1f}
- Average estimated model cost: ${statistics.mean(costs):.4f}
- End-to-end latency p50 / p95: {percentile(durations, .50):.0f} ms / {percentile(durations, .95):.0f} ms

## Scope

This benchmark runs the scripted happy-path escalation with 25 distinct input IDs and checks recorded approvals, expected action tools, completion, estimated provider cost, and latency. It does not establish broad model quality, prompt-injection resistance, or performance under concurrency. The unit and integration suite covers additional failure and policy paths.
"""
    Path("docs/eval-report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    asyncio.run(run_evaluation())
