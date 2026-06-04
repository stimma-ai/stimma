"""
Programmatic Alembic migrations for multi-profile databases.

Runs migrations at startup for all profile databases automatically.
"""
from core.logging import get_logger
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from config import get_settings

log = get_logger(__name__)


def get_alembic_config(db_path: str) -> AlembicConfig:
    """Create an Alembic config pointing to a specific database."""
    backend_dir = Path(__file__).parent.parent
    alembic_ini = backend_dir / "alembic.ini"

    config = AlembicConfig(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    return config


def run_migrations_for_profile(profile_id: str, db_path: str) -> None:
    """Run all pending migrations for a single profile database."""
    try:
        log.info(f"MIGRATIONS [{profile_id}]: Upgrading '{db_path}'...")
        config = get_alembic_config(db_path)
        command.upgrade(config, "head")
        log.info(f"MIGRATIONS [{profile_id}]: Up to date")
    except Exception as e:
        log.error(f"MIGRATIONS [{profile_id}]: Failed: {e}", exc_info=True)
        raise


def run_all_migrations() -> None:
    """Run migrations for all configured profile databases at startup."""
    settings = get_settings()
    log.info(f"MIGRATIONS: Running for {len(settings.profiles)} profile(s)...")

    for profile in settings.profiles:
        run_migrations_for_profile(profile.id, profile.database)

    log.info("MIGRATIONS: All databases up to date")
