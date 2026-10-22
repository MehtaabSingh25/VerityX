"""add idempotency keys to analysis jobs

Revision ID: 2f8c4a6d1b90
Revises: 7c2a9f4d1e60
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2f8c4a6d1b90"
down_revision: Union[str, Sequence[str], None] = "7c2a9f4d1e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_unique_constraint(
        "uq_analysis_jobs_media_idempotency_key",
        "analysis_jobs",
        ["media_asset_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_analysis_jobs_media_idempotency_key", "analysis_jobs", type_="unique")
    op.drop_column("analysis_jobs", "idempotency_key")
