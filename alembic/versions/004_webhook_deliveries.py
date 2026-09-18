"""add webhook_deliveries table and github_prs.comment_id

Revision ID: 004_webhook_deliveries
Revises: 003_embeddings
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_webhook_deliveries"
down_revision: str | None = "003_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column("delivery_id", sa.String(length=100), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("delivery_id"),
    )
    op.add_column("github_prs", sa.Column("comment_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("github_prs", "comment_id")
    op.drop_table("webhook_deliveries")
