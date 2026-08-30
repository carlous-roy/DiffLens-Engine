"""initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2025-02-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.models import UUIDType

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", UUIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_created_at", "analysis_runs", ["created_at"])

    op.create_table(
        "analysis_findings",
        sa.Column("id", UUIDType(), nullable=False),
        sa.Column("run_id", UUIDType(), nullable=False),
        sa.Column("analyzer", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "error",
                "critical",
                name="severitylevel",
                native_enum=False,
            ),
            nullable=False,
            server_default="info",
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_findings_run_id", "analysis_findings", ["run_id"])
    op.create_index("ix_analysis_findings_analyzer", "analysis_findings", ["analyzer"])


def downgrade() -> None:
    op.drop_index("ix_analysis_findings_analyzer", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_run_id", table_name="analysis_findings")
    op.drop_table("analysis_findings")
    op.drop_index("ix_analysis_runs_created_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
