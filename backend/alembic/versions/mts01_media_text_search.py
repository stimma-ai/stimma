"""Index media names and prompts for search-as-you-type.

Revision ID: mts01
Revises: sv02

The browser's prompt filter matched with LIKE over every row's prompt, title
and filename, and each keystroke runs that match for the grid and for every
facet count, so typing waited seconds on a large library. This adds a
word-prefix index over the same text and keeps it current with triggers, so
every write path (ORM, raw SQL, offline tools) updates it.

The index is contentless: it holds the words' postings, never a copy of the
text. With FTS5 secure-delete on, removing a row physically removes its words
from the index, matching the database-wide secure_delete for prompt text.
"""
from alembic import op

revision = "mts01"
down_revision = "sv02"
branch_labels = None
depends_on = None

TABLE = "media_text_search"

# The text searched for media row ``m``: its prompts, its original filename and
# the title of the Asset whose current revision it is. json_valid guards
# json_extract so a malformed metadata blob can never fail a write.
_BODY = """
    coalesce({m}.extracted_prompt, '') || ' ' ||
    coalesce(CASE WHEN json_valid({m}.generation_metadata)
                  THEN json_extract({m}.generation_metadata, '$.prompt') END, '') || ' ' ||
    coalesce({m}.original_filename, '') || ' ' ||
    coalesce((SELECT a.title FROM assets a
              JOIN asset_revisions r ON r.id = a.current_revision_id
              WHERE r.primary_media_id = {m}.id AND a.deleted_at IS NULL
              LIMIT 1), '')
"""


def _reindex(media_id_sql: str) -> str:
    """Statements that rewrite the index entry of the media row with this id."""
    return (
        f"DELETE FROM {TABLE} WHERE rowid = {media_id_sql};\n"
        f"INSERT INTO {TABLE}(rowid, body) SELECT mi.id, {_BODY.format(m='mi')} "
        f"FROM media_items mi WHERE mi.id = {media_id_sql};"
    )


def _revision_media(revision_id_sql: str) -> str:
    return f"(SELECT primary_media_id FROM asset_revisions WHERE id = {revision_id_sql})"


TRIGGERS = {
    "media_text_search_media_ai": f"""
        AFTER INSERT ON media_items BEGIN
            INSERT INTO {TABLE}(rowid, body) VALUES (NEW.id, {_BODY.format(m='NEW')});
        END""",
    "media_text_search_media_au": f"""
        AFTER UPDATE OF extracted_prompt, generation_metadata, original_filename ON media_items BEGIN
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
    bind = op.get_bind()
    exists = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).fetchone()
    if not exists:
        # unicode61 splits words on anything that is not a letter or digit and
        # folds case and accents, so "starfire-app-icon.png" and "Starfire —
        # App Icons" both yield plain words.
        op.execute(
            f"CREATE VIRTUAL TABLE {TABLE} USING fts5("
            "body, content='', contentless_delete=1, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        op.execute(f"INSERT INTO {TABLE}({TABLE}, rank) VALUES ('secure-delete', 1)")
        op.execute(
            f"INSERT INTO {TABLE}(rowid, body) "
            f"SELECT m.id, {_BODY.format(m='m')} FROM media_items m"
        )
    for name, body in TRIGGERS.items():
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade():
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
