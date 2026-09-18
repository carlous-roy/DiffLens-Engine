import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Resolve the database URL: a URL handed over programmatically wins (the app
# passes it when migrating at startup), then DATABASE_URL, then the
# application settings. alembic.ini deliberately leaves sqlalchemy.url blank.
from app.config import get_settings

database_url = (
    config.attributes.get("database_url")
    or os.environ.get("DATABASE_URL")
    or get_settings().database_url
)
config.set_main_option("sqlalchemy.url", database_url)

# The CLI configures logging from alembic.ini; callers that already have
# logging set up (the app at startup, the tests) pass configure_logger=False.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect them
from app.db import Base
from app.db.models import (  # noqa: F401
    AnalysisFinding,
    AnalysisRun,
    GitHubPR,
    WebhookDelivery,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
