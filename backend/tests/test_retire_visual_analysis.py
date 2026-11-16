"""The retired analysis schema and API do not survive an upgrade."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_retirement_preserves_media_identity_references_and_triggers(tmp_path):
    path = Path(__file__).parents[1] / "alembic/versions/retirevlm01_remove_visual_analysis.py"
    spec = importlib.util.spec_from_file_location("retire_visual_analysis", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        columns = ", ".join(f"{name} VARCHAR" for name in migration.RETIRED_COLUMNS)
        connection.exec_driver_sql(f"CREATE TABLE media_items (id INTEGER PRIMARY KEY AUTOINCREMENT, extracted_prompt VARCHAR, {columns})")
        connection.exec_driver_sql("CREATE INDEX ix_media_items_vlm_caption_status ON media_items(vlm_caption_status)")
        connection.exec_driver_sql("CREATE INDEX ix_media_items_prompt ON media_items(extracted_prompt)")
        connection.exec_driver_sql("CREATE TABLE asset_revisions (id INTEGER PRIMARY KEY, primary_media_id INTEGER REFERENCES media_items(id))")
        connection.exec_driver_sql("CREATE TABLE keywords (id INTEGER PRIMARY KEY, keyword_text VARCHAR)")
        connection.exec_driver_sql("CREATE TABLE media_keywords (media_id INTEGER, keyword_id INTEGER)")
        connection.exec_driver_sql("CREATE TABLE changes (media_id INTEGER)")
        connection.exec_driver_sql("CREATE TRIGGER media_updated AFTER UPDATE OF extracted_prompt ON media_items BEGIN INSERT INTO changes VALUES (NEW.id); END")
        connection.exec_driver_sql("INSERT INTO media_items(id, extracted_prompt, keywords, vlm_caption) VALUES (7, 'retained prompt', 'old keyword', 'old caption'), (42, 'temporary', NULL, NULL)")
        connection.exec_driver_sql("DELETE FROM media_items WHERE id=42")
        connection.exec_driver_sql("INSERT INTO asset_revisions VALUES (1, 7)")
        connection.exec_driver_sql("INSERT INTO keywords VALUES (1, 'old keyword')")
        connection.exec_driver_sql("INSERT INTO media_keywords VALUES (7, 1)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # Also covers schemas already created by current ORM.
        inspector = inspect(connection)
        assert not {"keywords", "media_keywords"} & set(inspector.get_table_names())
        assert {c["name"] for c in inspector.get_columns("media_items")} == {"id", "extracted_prompt"}
        assert connection.exec_driver_sql("SELECT * FROM media_items").all() == [(7, "retained prompt")]
        assert connection.exec_driver_sql("SELECT primary_media_id FROM asset_revisions").scalar() == 7
        connection.exec_driver_sql("UPDATE media_items SET extracted_prompt='updated' WHERE id=7")
        assert connection.exec_driver_sql("SELECT * FROM changes").all() == [(7,)]
        connection.exec_driver_sql("INSERT INTO media_items(extracted_prompt) VALUES ('next')")
        assert connection.exec_driver_sql("SELECT max(id) FROM media_items").scalar() == 43
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert {i["name"] for i in inspector.get_indexes("media_items")} == {"ix_media_items_prompt"}


async def test_retired_routes_fields_and_facets_are_absent(client):
    from agent.v2.tools.library import _browse_schema, _normalize_filters
    from ingestion import PHASES
    import pytest

    assert PHASES == ["metadata", "clip", "face_detection"]
    for route in ("/api/keywords/top", "/api/assets/keywords/top"):
        assert (await client.get(route)).status_code == 404
    assert (await client.post("/api/admin/reset-keywords")).status_code == 404
    counts = (await client.get("/api/assets/filter-counts")).json()
    assert "keywords" not in counts
    assert not {"keywords", "caption_query", "keyword_query"} & _browse_schema()["filters"].keys()
    for field in ("keywords", "caption_query", "keyword_query"):
        with pytest.raises(ValueError, match="Unknown library filters"):
            _normalize_filters({field: "old"})


def test_legacy_captioning_config_does_not_prevent_startup(tmp_path):
    from config import Settings

    config = tmp_path / "config.yaml"
    config.write_text("""
profiles:
  - id: default
    name: Default
    folders: []
    markers: []
llms: {}
clip:
  model: ViT-g-14
  pretrained: laion2b_s12b_b42k
face_detection:
  enabled: false
server:
  host: 0.0.0.0
  port: 8000
captioning:
  enabled: true
  parallelism: 20
""")
    settings = Settings.load_config(str(config))
    assert not hasattr(settings, "captioning")
    assert "captioning" not in settings.model_dump()
