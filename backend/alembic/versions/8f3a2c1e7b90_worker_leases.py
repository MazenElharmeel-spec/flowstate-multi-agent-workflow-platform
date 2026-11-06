"""Add worker leases for horizontal worker scaling.

Revision ID: 8f3a2c1e7b90
Revises: 69493f731a3f
Create Date: 2026-11-06 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f3a2c1e7b90"
down_revision: str | Sequence[str] | None = "69493f731a3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("worker_id", sa.String(length=64), nullable=True))
    op.add_column(
        "workflow_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_workflow_runs_worker_id", "workflow_runs", ["worker_id"])
    op.create_index(
        "ix_workflow_runs_status_lease", "workflow_runs", ["status", "lease_expires_at"]
    )
    # Recover any in-flight rows from the pre-lease worker implementation.
    op.execute("UPDATE workflow_runs SET status = 'queued' WHERE status = 'running'")


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_status_lease", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_worker_id", table_name="workflow_runs")
    op.drop_column("workflow_runs", "lease_expires_at")
    op.drop_column("workflow_runs", "worker_id")
