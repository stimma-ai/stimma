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
            run_migrations_for_profile("test", str(path), exclusive_access=True)
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT value FROM retained").fetchall() == [("original",)]
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("snapshot_base",)
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchall() == []
        snapshot = path.with_name(path.name + ".pre-migration")
        assert not snapshot.exists()  # Recovery consumes the snapshot without copying it.
        assert not Path(f"{path}-wal").exists()
        assert not Path(f"{path}-shm").exists()
        failing.write_text(failing.read_text().replace('    op.execute("INSERT INTO nonexistent VALUES (1)")\n', ''))
        run_migrations_for_profile("test", str(path), exclusive_access=True)
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
        run_migrations_for_profile("fresh", str(fresh), exclusive_access=True)
        assert not fresh.with_name(fresh.name + ".pre-migration").exists()
    finally:
        migrations.get_alembic_config = original_config


def test_failed_migration_restores_with_less_than_two_databases_free(tmp_path, monkeypatch):
    import utils.migrations as migrations
    from types import SimpleNamespace

    path = tmp_path / "profile.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE retained (value TEXT)")
        connection.execute("INSERT INTO retained VALUES ('original')")
        connection.commit()
    size = path.stat().st_size
    monkeypatch.setattr(migrations.shutil, "disk_usage", lambda _: SimpleNamespace(free=int(size * 1.5)))

    def fail_upgrade(*args):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE partial (id INTEGER)")
        raise RuntimeError("failed upgrade")

    def no_room_for_copy(*args):
        raise OSError("no space for another database copy")

    monkeypatch.setattr(migrations.command, "upgrade", fail_upgrade)
    monkeypatch.setattr(migrations.shutil, "copyfileobj", no_room_for_copy)
    with pytest.raises(RuntimeError, match="failed upgrade"):
        run_migrations_for_profile("test", str(path), exclusive_access=True)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT value FROM retained").fetchall() == [("original",)]
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchall()
    assert not path.with_name(path.name + ".pre-migration").exists()


@pytest.mark.parametrize("exclusive_access", [False, True])
def test_held_wal_connection_prevents_migration_and_preserves_snapshot(tmp_path, monkeypatch, exclusive_access):
    import utils.migrations as migrations

    path = tmp_path / "profile.db"
    with closing(sqlite3.connect(path)) as held:
        held.execute("PRAGMA journal_mode=WAL")
        held.execute("CREATE TABLE retained (value TEXT)")
        held.commit()
        upgraded = []
        monkeypatch.setattr(migrations.command, "upgrade", lambda *args: upgraded.append(True))
        with pytest.raises(RuntimeError, match="Stop.*restart"):
            run_migrations_for_profile("test", str(path), exclusive_access=exclusive_access)
        assert not upgraded
        snapshot = path.with_name(path.name + ".pre-migration")
        assert snapshot.exists()
        held.execute("INSERT INTO retained VALUES ('still original')")
        held.commit()
        assert held.execute("SELECT value FROM retained").fetchall() == [("still original",)]
        with closing(sqlite3.connect(snapshot)) as connection:
            assert connection.execute("SELECT value FROM retained").fetchall() == []
