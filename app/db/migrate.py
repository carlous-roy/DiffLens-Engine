"""Run the Alembic migrations from inside the application."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import Settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    """Alembic configuration for the repository's migrations against `database_url`."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def upgrade_to_head(database_url: str) -> None:
    """Apply every pending migration to the database at `database_url`."""
    command.upgrade(alembic_config(database_url), "head")


def should_auto_migrate(settings: Settings) -> bool:
    """AUTO_MIGRATE decides; unset, migrations run automatically in development only."""
    if settings.auto_migrate is not None:
        return settings.auto_migrate
    return settings.app_env == "development"


def migrate_on_startup(settings: Settings) -> bool:
    """Run migrations when configured to; returns True when they ran."""
    if not should_auto_migrate(settings):
        logger.info(
            "Automatic migrations are off (APP_ENV=%s, AUTO_MIGRATE=%s); "
            "run `alembic upgrade head` before serving.",
            settings.app_env,
            settings.auto_migrate,
        )
        return False
    logger.info("Applying database migrations (alembic upgrade head).")
    upgrade_to_head(settings.database_url)
    return True
