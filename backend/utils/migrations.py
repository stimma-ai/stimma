"""
Programmatic Alembic migrations for multi-profile databases.

Runs migrations at startup for all profile databases automatically.
"""
from core.logging import get_logger
from pathlib import Path
from contextlib import closing
import math
import os
import shutil
import sqlite3
import tempfile

from alembic.script import ScriptDirectory
from filelock import FileLock
from config_writer import atomic_write

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
    path = Path(db_path)
    # Both the app and ingestion process can discover a new profile together.
    with FileLock(f"{db_path}.migration.lock"):
        snapshot = None
        try:
            config = get_alembic_config(db_path)
            if path.exists() and path.stat().st_size:
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                    has_version = source.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
                    ).fetchone()
                    current = {row[0] for row in source.execute("SELECT version_num FROM alembic_version")} if has_version else set()
                    if current == set(ScriptDirectory.from_config(config).get_heads()):
                        return
                    # Page count includes committed pages still resident in WAL.
                    size = source.execute("PRAGMA page_count").fetchone()[0] * source.execute("PRAGMA page_size").fetchone()[0]
                    required = math.ceil(max(size, path.stat().st_size) * 1.2)
                    available = shutil.disk_usage(path.parent).free
                    if available < required:
                        raise RuntimeError(
                            f"Not enough free disk space to migrate profile '{profile_id}': "
                            f"need {required} bytes for a safety snapshot, have {available}. "
                            "Free disk space and restart. The database has not been changed."
                        )
                    snapshot_path = path.with_name(path.name + ".pre-migration")
                    fd, temporary = tempfile.mkstemp(prefix=path.name + ".snapshot-", dir=path.parent)
                    os.close(fd)
                    try:
                        with closing(sqlite3.connect(temporary)) as destination:
                            source.backup(destination)
                        with open(temporary, "rb") as handle:
                            os.fsync(handle.fileno())
                        os.replace(temporary, snapshot_path)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                    snapshot = snapshot_path

            log.info(f"MIGRATIONS [{profile_id}]: Upgrading '{db_path}'...")
            try:
                command.upgrade(config, "head")
            except BaseException:
                if snapshot is not None:
                    with atomic_write(path, "wb") as destination, snapshot.open("rb") as source:
                        shutil.copyfileobj(source, destination)
                    # These files belong to the failed schema, not the snapshot.
                    Path(f"{db_path}-wal").unlink(missing_ok=True)
                    Path(f"{db_path}-shm").unlink(missing_ok=True)
                raise
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
