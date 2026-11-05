"""The opt-in is decided once, independently in each profile database."""
import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine


@pytest.mark.parametrize('existing', ['none', 'live', 'deleted', 'explicit-off'])
def test_flows_preference_migration(tmp_path, existing):
    path = Path(__file__).parents[1] / 'alembic/versions/flowsopt01_experimental_flows.py'
    spec = importlib.util.spec_from_file_location('experimental_flows_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path / "profile.db"}')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE flows (id INTEGER PRIMARY KEY, deleted_at DATETIME)')
        connection.exec_driver_sql('CREATE TABLE user_preferences (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL, updated_at DATETIME NOT NULL)')
        if existing != 'none':
            connection.exec_driver_sql('INSERT INTO flows VALUES (1, ?)', ('2026-01-01' if existing == 'deleted' else None,))
        if existing == 'explicit-off':
            connection.exec_driver_sql("INSERT INTO user_preferences VALUES ('experimental_flows', '{\"enabled\": false}', CURRENT_TIMESTAMP)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        expected = existing == 'live'
        assert json.loads(connection.exec_driver_sql("SELECT value FROM user_preferences WHERE key='experimental_flows'").scalar()) == {'enabled': expected}
        # Rerunning cannot turn a prior off into on, even after adding a flow.
        connection.exec_driver_sql('INSERT INTO flows VALUES (2, NULL)')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert json.loads(connection.exec_driver_sql("SELECT value FROM user_preferences WHERE key='experimental_flows'").scalar()) == {'enabled': expected}
    engine.dispose()
