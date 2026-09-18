"""The Alembic migrations build the schema the models expect, on SQLite."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    # alembic/env.py reads DATABASE_URL before the settings fallback.
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def test_upgrade_head_creates_the_expected_schema(database_url):
    command.upgrade(_alembic_config(database_url), "head")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
    assert {"analysis_runs", "analysis_findings", "github_prs", "alembic_version"} <= tables

    findings = {c["name"] for c in inspector.get_columns("analysis_findings")}
    assert {"embedding", "embedding_model", "cluster_id", "category"} <= findings
    runs = {c["name"] for c in inspector.get_columns("analysis_runs")}
    assert "risk" in runs
    indexes = {i["name"] for i in inspector.get_indexes("analysis_findings")}
    assert "ix_analysis_findings_cluster_id" in indexes


def test_migrations_match_the_models(database_url):
    """Every column the ORM models declare exists after `upgrade head`."""
    from app.db import Base, models  # noqa: F401 - registers the models on Base

    command.upgrade(_alembic_config(database_url), "head")
    inspector = inspect(create_engine(database_url))
    for table in Base.metadata.sorted_tables:
        actual = {c["name"] for c in inspector.get_columns(table.name)}
        expected = {c.name for c in table.columns}
        assert expected <= actual, f"{table.name} is missing {expected - actual}"


def test_downgrade_to_base_removes_everything(database_url):
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    inspector = inspect(create_engine(database_url))
    assert set(inspector.get_table_names()) <= {"alembic_version"}


class TestStartupMigration:
    def test_development_migrates_automatically(self, tmp_path):
        from app.config import Settings
        from app.db.migrate import migrate_on_startup, should_auto_migrate

        url = f"sqlite:///{tmp_path / 'auto.db'}"
        settings = Settings(database_url=url, app_env="development", auto_migrate=None)
        assert should_auto_migrate(settings) is True
        assert migrate_on_startup(settings) is True
        tables = set(inspect(create_engine(url)).get_table_names())
        assert "analysis_findings" in tables and "webhook_deliveries" in tables

    def test_production_does_not_migrate_unless_asked(self, tmp_path):
        from app.config import Settings
        from app.db.migrate import migrate_on_startup, should_auto_migrate

        url = f"sqlite:///{tmp_path / 'prod.db'}"
        settings = Settings(database_url=url, app_env="production", auto_migrate=None)
        assert should_auto_migrate(settings) is False
        assert migrate_on_startup(settings) is False
        assert inspect(create_engine(url)).get_table_names() == []

        forced = Settings(database_url=url, app_env="production", auto_migrate=True)
        assert migrate_on_startup(forced) is True
        assert "analysis_runs" in inspect(create_engine(url)).get_table_names()
