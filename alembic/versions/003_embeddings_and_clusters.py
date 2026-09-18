"""add embeddings, cluster ids, categories and run risk

Revision ID: 003_embeddings
Revises: 002_github_prs
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.models import EmbeddingType

# revision identifiers, used by Alembic.
revision: str = "003_embeddings"
down_revision: str | None = "002_github_prs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        # pgvector provides the `vector` type and the `<=>` cosine operator.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("analysis_runs", sa.Column("risk", sa.JSON(), nullable=True))

    op.add_column("analysis_findings", sa.Column("category", sa.String(length=50), nullable=True))
    op.add_column("analysis_findings", sa.Column("embedding", EmbeddingType(), nullable=True))
    op.add_column(
        "analysis_findings", sa.Column("embedding_model", sa.String(length=100), nullable=True)
    )
    op.add_column("analysis_findings", sa.Column("cluster_id", sa.Integer(), nullable=True))
    op.create_index("ix_analysis_findings_cluster_id", "analysis_findings", ["cluster_id"])

    if _is_postgres():
        op.execute(
            "CREATE INDEX ix_analysis_findings_embedding_hnsw ON analysis_findings "
            "USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_analysis_findings_embedding_hnsw")
    op.drop_index("ix_analysis_findings_cluster_id", table_name="analysis_findings")
    op.drop_column("analysis_findings", "cluster_id")
    op.drop_column("analysis_findings", "embedding_model")
    op.drop_column("analysis_findings", "embedding")
    op.drop_column("analysis_findings", "category")
    op.drop_column("analysis_runs", "risk")
