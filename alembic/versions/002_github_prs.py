"""add github_prs table

Revision ID: 002_github_prs
Revises: 001_initial
Create Date: 2025-02-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.models import UUIDType

# revision identifiers, used by Alembic.
revision: str = "002_github_prs"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_prs",
        sa.Column("id", UUIDType(), nullable=False),
        sa.Column("run_id", UUIDType(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False, server_default="opened"),
        sa.Column("pr_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_github_prs_run_id", "github_prs", ["run_id"])
    op.create_index(
        "ix_github_prs_owner_repo_number", "github_prs", ["owner", "repo", "pr_number"]
    )
    op.create_index("ix_github_prs_head_sha", "github_prs", ["head_sha"])


def downgrade() -> None:
    op.drop_index("ix_github_prs_head_sha", table_name="github_prs")
    op.drop_index("ix_github_prs_owner_repo_number", table_name="github_prs")
    op.drop_index("ix_github_prs_run_id", table_name="github_prs")
    op.drop_table("github_prs")
