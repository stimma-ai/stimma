"""Split the search index into prompt and title columns; drop filenames.

Revision ID: mts02
Revises: mts01

mts01 indexed one blob per media row: prompts, original filename and Asset
title together. The browser's prompt filter then matched words nobody can see
in media info: generated files' machine filenames (timestamps, counters) and a
ComfyUI node graph stored under ``prompt`` (seeds, node ids). Text search now
covers only what people can see: the prompt column holds what the prompt panel
shows (the prompt and the prompt as typed, and the metadata prompt only when
it is text) and the title column the Asset title. Filenames are not indexed.

Same contentless table, secure-delete and trigger set as mts01, rebuilt.
"""
from alembic import op

revision = "mts02"
down_revision = "mts01"
branch_labels = None
depends_on = None

TABLE = "media_text_search"


def _json_text(m: str, path: str) -> str:
    """The string at ``path`` of the row's generation metadata, else NULL.
    json_valid guards json_extract so malformed metadata never fails a write."""
    gm = f"{m}.generation_metadata"
    return (
        f"CASE WHEN json_valid({gm}) AND json_type({gm}, '{path}') = 'text' "
        f"THEN json_extract({gm}, '{path}') END"
    )


def _columns(m: str) -> str:
    """prompt, title for media row ``m``."""
    prompt = (
        f"coalesce({m}.extracted_prompt, '') || ' ' || "
        f"coalesce({_json_text(m, '$.prompt')}, '') || ' ' || "
        f"coalesce({_json_text(m, '$.prompt_metadata.original_prompt')}, '')"
    )
    title = (
        "coalesce((SELECT a.title FROM assets a "
        "JOIN asset_revisions r ON r.id = a.current_revision_id "
        f"WHERE r.primary_media_id = {m}.id AND a.deleted_at IS NULL LIMIT 1), '')"
    )
    return f"{prompt}, {title}"


_INSERT = f"INSERT INTO {TABLE}(rowid, prompt, title)"


def _reindex(media_id_sql: str) -> str:
    """Statements that rewrite the index entry of the media row with this id."""
    return (
        f"DELETE FROM {TABLE} WHERE rowid = {media_id_sql};\n"
        f"{_INSERT} SELECT mi.id, {_columns('mi')} FROM media_items mi WHERE mi.id = {media_id_sql};"
    )


def _revision_media(revision_id_sql: str) -> str:
    return f"(SELECT primary_media_id FROM asset_revisions WHERE id = {revision_id_sql})"


TRIGGERS = {
    "media_text_search_media_ai": f"""
        AFTER INSERT ON media_items BEGIN
            {_INSERT} VALUES (NEW.id, {_columns('NEW')});
        END""",
    "media_text_search_media_au": f"""
        AFTER UPDATE OF extracted_prompt, generation_metadata ON media_items BEGIN
            {_reindex('NEW.id')}
        END""",
    "media_text_search_media_ad": f"""
        AFTER DELETE ON media_items BEGIN
            DELETE FROM {TABLE} WHERE rowid = OLD.id;
        END""",
    "media_text_search_asset_ai": f"""
        AFTER INSERT ON assets WHEN NEW.current_revision_id IS NOT NULL BEGIN
            {_reindex(_revision_media('NEW.current_revision_id'))}
        END""",
    "media_text_search_asset_au": f"""
        AFTER UPDATE OF title, current_revision_id, deleted_at ON assets BEGIN
            {_reindex(_revision_media('OLD.current_revision_id'))}
            {_reindex(_revision_media('NEW.current_revision_id'))}
        END""",
    "media_text_search_asset_ad": f"""
        AFTER DELETE ON assets WHEN OLD.current_revision_id IS NOT NULL BEGIN
            {_reindex(_revision_media('OLD.current_revision_id'))}
        END""",
    "media_text_search_revision_ai": f"""
        AFTER INSERT ON asset_revisions BEGIN
            {_reindex('NEW.primary_media_id')}
        END""",
    "media_text_search_revision_au": f"""
        AFTER UPDATE OF primary_media_id ON asset_revisions BEGIN
            {_reindex('OLD.primary_media_id')}
            {_reindex('NEW.primary_media_id')}
        END""",
    "media_text_search_revision_ad": f"""
        AFTER DELETE ON asset_revisions BEGIN
            {_reindex('OLD.primary_media_id')}
        END""",
}


def upgrade():
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    # unicode61 splits words on anything that is not a letter or digit and
    # folds case and accents, so "Starfire — App Icons" yields plain words.
    op.execute(
        f"CREATE VIRTUAL TABLE {TABLE} USING fts5("
        "prompt, title, content='', contentless_delete=1, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    op.execute(f"INSERT INTO {TABLE}({TABLE}, rank) VALUES ('secure-delete', 1)")
    op.execute(f"{_INSERT} SELECT m.id, {_columns('m')} FROM media_items m")
    for name, body in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade():
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
