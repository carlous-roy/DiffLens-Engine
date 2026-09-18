"""Database models for DiffLens."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    types,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.db import Base

EMBEDDING_DIM = 384

# Custom column types


class UUIDType(types.TypeDecorator):
    """Platform-independent UUID type."""

    impl = types.CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(types.CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        return value.hex if isinstance(value, uuid.UUID) else uuid.UUID(value).hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


class EmbeddingType(types.TypeDecorator):
    """A finding embedding: pgvector `vector(384)` on PostgreSQL, JSON elsewhere.

    Values are bound from any float sequence and come back as float32 arrays.
    """

    impl = types.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(types.JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        import numpy as np

        return np.asarray(value, dtype=np.float32)


# Enums


class SeverityLevel(enum.StrEnum):
    """Severity of an individual finding (maps to GitHub annotation levels)."""

    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


# Models


class AnalysisRun(Base):
    """A single analysis invocation — triggered by the API, the GitHub webhook,
    or a manual run, and holding the summary of everything that was found."""

    __tablename__ = "analysis_runs"

    id = Column(UUIDType(), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    source = Column(String(50), nullable=False, default="api")
    status = Column(String(20), nullable=False, default="completed")
    summary = Column(JSON, nullable=True)
    # Risk score, categorization summary and similarity method of the run.
    risk = Column(JSON, nullable=True)

    findings = relationship("AnalysisFinding", back_populates="run", cascade="all, delete-orphan")
    github_pr = relationship(
        "GitHubPR", back_populates="run", uselist=False, cascade="all, delete-orphan"
    )


class AnalysisFinding(Base):
    """One issue found by an analyzer (complexity, naming, bug_risk)."""

    __tablename__ = "analysis_findings"

    id = Column(UUIDType(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUIDType(),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analyzer = Column(String(50), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    line_number = Column(Integer, nullable=True)
    severity = Column(
        SAEnum(SeverityLevel, native_enum=False),
        nullable=False,
        default=SeverityLevel.info,
    )
    message = Column(Text, nullable=False)
    suggestion = Column(Text, nullable=True)
    # Extra structured data (e.g. complexity score, matched pattern)
    metadata_ = Column("metadata", JSON, nullable=True)
    # Keyword-rule category (security, correctness, ...)
    category = Column(String(50), nullable=True)
    # Embedding of the finding text, the model that produced it, and the
    # cluster of repeat findings it was assigned to.
    embedding = Column(EmbeddingType(), nullable=True)
    embedding_model = Column(String(100), nullable=True)
    cluster_id = Column(Integer, nullable=True, index=True)

    run = relationship("AnalysisRun", back_populates="findings")


class GitHubPR(Base):
    """Tracks which GitHub pull requests have been analyzed and links each one
    back to the analysis run that produced its findings."""

    __tablename__ = "github_prs"

    id = Column(UUIDType(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUIDType(),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner = Column(String(200), nullable=False)
    repo = Column(String(200), nullable=False)
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String(40), nullable=False, index=True)
    action = Column(String(50), nullable=False, default="opened")
    pr_url = Column(String(500), nullable=True)
    # Id of the summary comment on the PR, updated in place on later pushes.
    comment_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    run = relationship("AnalysisRun", back_populates="github_pr")

    __table_args__ = (Index("ix_github_prs_owner_repo_number", "owner", "repo", "pr_number"),)


class WebhookDelivery(Base):
    """Every accepted webhook delivery, keyed by GitHub's delivery id, so a
    captured delivery cannot be replayed."""

    __tablename__ = "webhook_deliveries"

    delivery_id = Column(String(100), primary_key=True)
    event = Column(String(50), nullable=False)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
