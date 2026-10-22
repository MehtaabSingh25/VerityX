"""add investigation-scoped access token hashes

Revision ID: 7c2a9f4d1e60
Revises: 5b1f7a9c2d31
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7c2a9f4d1e60"
down_revision: Union[str, Sequence[str], None] = "5b1f7a9c2d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("access_token_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investigations", "access_token_hash")
