"""add append-only analysis job events

Revision ID: 5b1f7a9c2d31
Revises: 94696e6b8d80
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b1f7a9c2d31"
down_revision: Union[str, Sequence[str], None] = "94696e6b8d80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_job_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_job_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_job_events_analysis_job_id",
        "analysis_job_events",
        ["analysis_job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_job_events_analysis_job_id", table_name="analysis_job_events")
    op.drop_table("analysis_job_events")
