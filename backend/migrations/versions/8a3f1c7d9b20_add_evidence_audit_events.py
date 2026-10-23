
"""add hash-linked evidence audit events

Revision ID: 8a3f1c7d9b20
Revises: 6e4a1c9d2b70
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a3f1c7d9b20"
down_revision: Union[str, Sequence[str], None] = "6e4a1c9d2b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("media_asset_id", sa.Uuid(), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "investigation_id",
            "sequence_number",
            name="uq_evidence_audit_investigation_sequence",
        ),
    )
    op.create_index(
        "ix_evidence_audit_investigation_sequence",
        "evidence_audit_events",
        ["investigation_id", "sequence_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_audit_investigation_sequence",
        table_name="evidence_audit_events",
    )
    op.drop_table("evidence_audit_events")
