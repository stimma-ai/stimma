"""Remove the retired automatic caption and keyword feature.

Use native column drops so Media identity, foreign keys, AUTOINCREMENT, and
search-index triggers survive without rebuilding the library's central table.
"""
from alembic import op
import sqlalchemy as sa

revision = "retirevlm01"
down_revision = "mts02"
branch_labels = None
depends_on = None

RETIRED_COLUMNS = (
    "keywords",
    "vlm_caption",
    "vlm_caption_config_version",
    "vlm_caption_status",
    "vlm_caption_processed_at",
    "vlm_caption_error",
    "vlm_caption_retry_count",
    # Earlier installations used separate extraction and keyword phases.
    "vlm_extract_config_version",
    "vlm_extract_status",
    "vlm_extract_processed_at",
    "vlm_extract_error",
    "vlm_extract_retry_count",
    "llm_keywords_config_version",
    "llm_keywords_status",
    "llm_keywords_processed_at",
    "llm_keywords_error",
    "llm_keywords_retry_count",
)


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    for table in ("media_keywords", "keywords"):
        if table in tables:
            op.drop_table(table)
    if "media_items" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("media_items")}
    for index in inspector.get_indexes("media_items"):
        if set(index["column_names"]) & set(RETIRED_COLUMNS):
            op.drop_index(index["name"], table_name="media_items")
    for column in RETIRED_COLUMNS:
        if column in columns:
            op.drop_column("media_items", column)


def downgrade():
    raise NotImplementedError("Automatic visual analysis has been permanently retired")
