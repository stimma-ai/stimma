"""The chat item window indexes apply to an existing database and revert."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine


def _indexes(connection) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql("PRAGMA index_list('chat_items')")}


def test_chat_item_window_indexes_upgrade_and_downgrade(tmp_path):
    path = Path(__file__).parents[1] / 'alembic/versions/chat01_chat_item_window_indexes.py'
    spec = importlib.util.spec_from_file_location('chat_item_window_indexes', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path / "chat.db"}')
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'CREATE TABLE chat_items (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, '
            'item_type VARCHAR NOT NULL, created_at DATETIME)'
        )
        connection.exec_driver_sql('CREATE INDEX idx_chat_items_chat_created ON chat_items (chat_id, created_at)')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            # Re-running is harmless (databases created from the models already have them).
            migration.upgrade()
        assert {'idx_chat_items_chat_id', 'idx_chat_items_chat_type'} <= _indexes(connection)
        plan = ' '.join(str(row[-1]) for row in connection.exec_driver_sql(
            'EXPLAIN QUERY PLAN SELECT * FROM chat_items WHERE chat_id = 1 AND id < 10 ORDER BY id DESC LIMIT 5'
        ))
        assert 'TEMP B-TREE' not in plan, plan
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert not {'idx_chat_items_chat_id', 'idx_chat_items_chat_type'} & _indexes(connection)
    engine.dispose()
