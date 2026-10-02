"""Existing views survive the project ownership migration unchanged."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_project_scope_migration_preserves_legacy_views_and_ids(tmp_path):
    path = Path(__file__).parents[1] / 'alembic/versions/sv01_project_saved_views.py'
    spec = importlib.util.spec_from_file_location('saved_view_scope_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path / "views.db"}')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE projects (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE saved_views (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR NOT NULL, filters VARCHAR NOT NULL, sort_by VARCHAR NOT NULL, display_order INTEGER NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)')
        connection.exec_driver_sql("INSERT INTO saved_views VALUES (7, 'Favorites', '{}', 'created_desc', 3, '2026-01-01', '2026-01-01')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        row = connection.exec_driver_sql('SELECT id, name, display_order, project_id, deleted_at FROM saved_views').one()
        assert tuple(row) == (7, 'Favorites', 3, None, None)
        schema = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='saved_views'").scalar()
        assert 'AUTOINCREMENT' in schema
        assert inspect(connection).get_foreign_keys('saved_views')[0]['referred_table'] == 'projects'
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert 'project_id' not in {c['name'] for c in inspect(connection).get_columns('saved_views')}
        assert connection.exec_driver_sql('SELECT id FROM saved_views').scalar() == 7
    engine.dispose()
