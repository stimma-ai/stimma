"""A failed SQLite DDL migration must leave a retryable database."""
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command

from utils.migrations import get_alembic_config, run_migrations_for_profile


def test_failed_migration_restores_schema_version_and_wal(tmp_path):
    # Use the real config/env, with temporary revision scripts selected by an ini.
    scripts = tmp_path / "alembic"
    scripts.mkdir()
    (scripts / "versions").mkdir()
    source_env = Path(__file__).parents[1] / "alembic" / "env.py"
    (scripts / "env.py").write_text(source_env.read_text())
    path = tmp_path / "profile.db"
    config = get_alembic_config(str(path))
    # The runner takes the same config path used by get_alembic_config.
    config.set_main_option("script_location", str(scripts))
    (scripts / "versions" / "base.py").write_text('''
from alembic import op
revision = "snapshot_base"
down_revision = None
def upgrade():
    op.execute("CREATE TABLE retained (value TEXT)")
def downgrade():
    pass
''')
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO retained VALUES ('original')")
        connection.commit()
    failing = scripts / "versions" / "next.py"
    failing.write_text('''
from alembic import op
revision = "snapshot_next"
down_revision = "snapshot_base"
def upgrade():
    op.execute("CREATE TABLE partial (id INTEGER)")
    op.execute("INSERT INTO nonexistent VALUES (1)")
def downgrade():
    pass
''')
    # Exercise the public runner without patching any DB or Alembic operations.
    import utils.migrations as migrations
    original_config = migrations.get_alembic_config
    try:
        migrations.get_alembic_config = lambda db_path: config
        with pytest.raises(Exception, match="nonexistent"):
            run_migrations_for_profile("test", str(path))
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT value FROM retained").fetchall() == [("original",)]
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("snapshot_base",)
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchall() == []
        snapshot = path.with_name(path.name + ".pre-migration")
        assert snapshot.is_file()
        with closing(sqlite3.connect(snapshot)) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("snapshot_base",)
        assert not Path(f"{path}-wal").exists()
        assert not Path(f"{path}-shm").exists()
        failing.write_text(failing.read_text().replace('    op.execute("INSERT INTO nonexistent VALUES (1)")\n', ''))
        run_migrations_for_profile("test", str(path))
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("snapshot_next",)
            assert connection.execute("SELECT value FROM retained").fetchall() == [("original",)]
        snapshot_stat = snapshot.stat()
        run_migrations_for_profile("test", str(path))
        assert snapshot.stat() == snapshot_stat  # Head startup does not rewrite the snapshot.
        assert len(list(tmp_path.glob("*.pre-migration"))) == 1

        fresh = tmp_path / "fresh.db"
        fresh_config = original_config(str(fresh))
        fresh_config.set_main_option("script_location", str(scripts))
        migrations.get_alembic_config = lambda db_path: fresh_config
        run_migrations_for_profile("fresh", str(fresh))
        assert not fresh.with_name(fresh.name + ".pre-migration").exists()
    finally:
        migrations.get_alembic_config = original_config
