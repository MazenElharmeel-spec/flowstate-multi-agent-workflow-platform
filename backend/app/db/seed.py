"""Database seeding script for default workflows, users, and roles."""

import asyncio
import logging

from sqlalchemy import select

from backend.app.core.security import Role, get_password_hash
from backend.app.db.models import User, WorkflowDefinition
from backend.app.db.session import async_session_factory, init_db

logger = logging.getLogger(__name__)


async def seed_database() -> None:
    await init_db()

    async with async_session_factory() as session:
        # 1. Seed Users
        users_to_seed = [
            ("admin@example.com", "AdminSecret123!", Role.ADMIN.value),
            ("operator@example.com", "OperatorSecret123!", Role.OPERATOR.value),
            ("approver@example.com", "ApproverSecret123!", Role.APPROVER.value),
            ("viewer@example.com", "ViewerSecret123!", Role.VIEWER.value),
        ]

        for email, password, role in users_to_seed:
            res = await session.execute(select(User).where(User.email == email))
            existing = res.scalar_one_or_none()
            if not existing:
                u = User(
                    email=email,
                    hashed_password=get_password_hash(password),
                    role=role,
                    is_active=True,
                )
                session.add(u)
                logger.info("Seeded user %s (%s)", email, role)

        # 2. Seed Workflow 1: Customer Escalation Resolution
        res_wf1 = await session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.key == "customer_escalation")
        )
        if not res_wf1.scalar_one_or_none():
            wf1 = WorkflowDefinition(
                key="customer_escalation",
                version=1,
                name="Customer Escalation Resolution",
                description="Multi-agent workflow resolving high-priority support escalations with least privilege and human-in-the-loop approvals.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string", "description": "Support Ticket ID"},
                        "customer_id": {"type": "string", "description": "Customer ID in CRM"},
                        "description": {"type": "string", "description": "Customer issue summary"},
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                            "default": "high",
                        },
                    },
                    "required": ["ticket_id", "customer_id"],
                },
                graph_definition={
                    "nodes": ["triage", "research", "planner", "policy_gate", "action", "reviewer", "report"],
                    "agents": ["TriageAgent", "ResearchAgent", "PlannerAgent", "ActionAgent", "ReviewerAgent"],
                },
                is_active=True,
            )
            session.add(wf1)
            logger.info("Seeded workflow definition: customer_escalation")

        # 3. Seed Workflow 2: Weekly Ops Digest
        res_wf2 = await session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.key == "weekly_ops_digest")
        )
        if not res_wf2.scalar_one_or_none():
            wf2 = WorkflowDefinition(
                key="weekly_ops_digest",
                version=1,
                name="Weekly Ops Digest",
                description="Aggregates system metrics, detects latency/cost anomalies, and generates executive operations summaries.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "reporting_period": {
                            "type": "string",
                            "default": "last_7_days",
                            "description": "Period to summarize",
                        },
                        "recipients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["ops-team@example.com"],
                            "description": "Notification recipients",
                        },
                    },
                },
                graph_definition={
                    "nodes": ["metrics_collector", "anomaly_analyzer", "digest_reporter"],
                    "agents": ["MetricsCollector", "AnomalyAnalyzer", "DigestReporter"],
                },
                is_active=True,
            )
            session.add(wf2)
            logger.info("Seeded workflow definition: weekly_ops_digest")

        await session.commit()
    logger.info("Database seeding completed.")


if __name__ == "__main__":
    asyncio.run(seed_database())
