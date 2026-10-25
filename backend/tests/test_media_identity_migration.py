"""Exercise the migrated schema: ORM create_all can hide lost AUTOINCREMENT."""
from alembic import command
import pytest
from sqlalchemy import create_engine, inspect

from database import (
    Base, CachedProviderTool, Chat, ChatItem, DeleteOperation, DeleteOperationItem,
    GenerationJob, MediaItem, Preset,
)
from utils.migrations import get_alembic_config


def test_migrations_preserve_non_reusable_ids(tmp_path):
    path = tmp_path / "identity.db"
    command.upgrade(get_alembic_config(str(path)), "head")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            missing = []
            for table in Base.metadata.tables.values():
                if not table.dialect_options["sqlite"]["autoincrement"]:
                    continue
                schema = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE name=?", (table.name,)
                ).scalar()
                if schema and "AUTOINCREMENT" not in schema.upper():
                    missing.append(table.name)
            assert not missing, f"Migrations removed AUTOINCREMENT from: {missing}"

            for table, values in (
                (MediaItem.__table__, dict(
                    file_path="generated.png", file_hash="new-content", file_size=100,
                    file_format="png", width=64, height=64, megapixels=0.004,
                )),
                (GenerationJob.__table__, dict(
                    status="queued", generator_type="test", generator_name="test",
                    model_name="test", parameters="{}", folder_path="staging",
                )),
            ):
                first = connection.execute(table.insert().values(**values)).inserted_primary_key[0]
                connection.execute(table.delete().where(table.c.id == first))
                second = connection.execute(table.insert().values(**values)).inserted_primary_key[0]
                assert second > first, f"{table.name} recycled a deleted identity"
    finally:
        engine.dispose()


@pytest.mark.parametrize("already_autoincrement", [False, True])
def test_identity_repair_preserves_existing_data_and_high_water(tmp_path, already_autoincrement):
    path = tmp_path / "existing.db"
    config = get_alembic_config(str(path))
    engine = create_engine(f"sqlite:///{path}")
    if already_autoincrement:
        Base.metadata.create_all(engine)
        command.stamp(config, "sv01")
    else:
        command.upgrade(config, "sv01")
    tables = (MediaItem, GenerationJob, ChatItem, Preset, CachedProviderTool)
    values = dict(
        file_path="generated.png", file_hash="retained-content", file_size=100,
        file_format="png", width=64, height=64, megapixels=0.004,
    )
    try:
        with engine.begin() as connection:
            connection.execute(Preset.__table__.insert().values(id=3, name="Saved", tool_id="test:tool"))
            connection.execute(MediaItem.__table__.insert().values(id=7, preset_id=3, **values))
            connection.execute(GenerationJob.__table__.insert().values(
                id=11, result_media_id=7, preset_id=3, status="completed", generator_type="test",
                generator_name="test", model_name="test", parameters="{}", folder_path="staging",
            ))
            connection.execute(Chat.__table__.insert().values(id=17, name="Chat"))
            connection.execute(ChatItem.__table__.insert().values(
                id=19, chat_id=17, media_id=7, item_type="generated_media",
            ))
            connection.execute(CachedProviderTool.__table__.insert().values(
                id=23, full_tool_id="test:tool", tool_id="tool", provider_id="test", name="Tool",
            ))
            operation_id = connection.execute(DeleteOperation.__table__.insert().values(
                kind="asset", profile_id="default", status="completed",
            )).inserted_primary_key[0]
            connection.execute(DeleteOperationItem.__table__.insert().values(
                operation_id=operation_id, media_id=999, state="done",
            ))
            # A deleted high ID must remain reserved even when no row holds it.
            if already_autoincrement:
                connection.execute(MediaItem.__table__.insert().values(id=1000, **values))
                connection.exec_driver_sql("DELETE FROM media_items WHERE id=1000")
            connection.exec_driver_sql("CREATE TABLE identity_audit (media_id INTEGER)")
            connection.exec_driver_sql("""
                CREATE TRIGGER audit_media_identity AFTER INSERT ON media_items
                BEGIN INSERT INTO identity_audit VALUES (NEW.id); END
            """)
            rows_before = {
                model.__tablename__: connection.exec_driver_sql(
                    f'SELECT * FROM "{model.__tablename__}" ORDER BY id'
                ).all()
                for model in tables
            }
            inspector = inspect(connection)
            indexes_before = {model.__tablename__: inspector.get_indexes(model.__tablename__) for model in tables}
            fks_before = {model.__tablename__: inspector.get_foreign_keys(model.__tablename__) for model in tables}

        command.upgrade(config, "head")
        with engine.begin() as connection:
            inspector = inspect(connection)
            for model in tables:
                name = model.__tablename__
                assert connection.exec_driver_sql(f'SELECT * FROM "{name}" ORDER BY id').all() == rows_before[name]
                assert inspector.get_indexes(name) == indexes_before[name]
                by_columns = lambda fk: tuple(fk["constrained_columns"])
                assert sorted(inspector.get_foreign_keys(name), key=by_columns) == sorted(fks_before[name], key=by_columns)
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            media_id = connection.execute(MediaItem.__table__.insert().values(**values)).inserted_primary_key[0]
            assert media_id > (1000 if already_autoincrement else 999)
            assert connection.exec_driver_sql("SELECT media_id FROM identity_audit").scalar_one() == media_id
    finally:
        engine.dispose()
