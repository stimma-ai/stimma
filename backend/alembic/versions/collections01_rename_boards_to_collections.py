"""Rename boards to collections.

Revision ID: collections01
Revises: assetgroups02

Renames the four board tables, their board_* columns and indexes, and
rewrites saved workspace state (tabs, recents, last routes) that names a
board by type, tab id (``board:<id>``) or route (``/boards/...``).
"""
import json
import re

from alembic import op
import sqlalchemy as sa

revision = "collections01"
down_revision = "assetgroups02"
branch_labels = None
depends_on = None

_TABLES = [
    ("boards", "collections"),
    ("board_sections", "collection_sections"),
    ("board_items", "collection_items"),
    ("board_asset_items", "collection_asset_items"),
]
_COLUMNS = [
    ("sections", "board_id", "collection_id"),
    ("items", "board_section_id", "collection_section_id"),
    ("asset_items", "board_section_id", "collection_section_id"),
]
_TYPE_FIELDS = {"type", "kind", "entityType", "tabType"}


def _rename_schema(old: str, new: str) -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    pairs = _TABLES if old == "board" else [(b, a) for a, b in _TABLES]
    for src, dst in pairs:
        if src in tables and dst not in tables:
            op.execute(f'ALTER TABLE "{src}" RENAME TO "{dst}"')
    for suffix, board_col, collection_col in _COLUMNS:
        table = f"{new}_{suffix}"
        src, dst = (board_col, collection_col) if old == "board" else (collection_col, board_col)
        columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if src in columns:
            op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{src}" TO "{dst}"')
    # SQLite keeps index names through a rename; recreate them under the new noun.
    # The stored SQL already names the renamed table and columns.
    rows = bind.execute(sa.text(
        "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL "
        "AND tbl_name IN :tables"
    ).bindparams(sa.bindparam("tables", expanding=True)), {"tables": [dst for _, dst in pairs]}).all()
    for name, sql in rows:
        renamed = name.replace(old, new)
        if renamed == name:
            continue
        op.execute(f'DROP INDEX "{name}"')
        op.execute(re.sub(rf'^(CREATE (?:UNIQUE )?INDEX )"?{re.escape(name)}"?', rf'\1"{renamed}"', sql))


def _rewrite(value, old: str, new: str):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _TYPE_FIELDS and v == old:
                v = new
            out[_rewrite(k, old, new)] = _rewrite(v, old, new)
        return out
    if isinstance(value, list):
        return [_rewrite(v, old, new) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("[", "{"):
            try:
                inner = json.loads(stripped)
            except ValueError:
                inner = None
            if isinstance(inner, (dict, list)):
                rewritten = _rewrite(inner, old, new)
                return json.dumps(rewritten, separators=(",", ":")) if rewritten != inner else value
        value = re.sub(rf"^{old}:(\d+)$", rf"{new}:\1", value)
        if value.startswith("/"):
            value = re.sub(rf"(?<=/){old}s(?=/|\?|#|$)", f"{new}s", value)
        return value
    return value


def _rewrite_workspace(old: str, new: str) -> None:
    bind = op.get_bind()
    if "workspace_docs" not in set(sa.inspect(bind).get_table_names()):
        return
    rows = bind.execute(sa.text(
        "SELECT namespace, key, value FROM workspace_docs "
        "WHERE key LIKE :prefix OR value LIKE :needle"
    ), {"prefix": f"{old}:%", "needle": f"%{old}%"}).all()
    for namespace, key, raw in rows:
        new_key = _rewrite(key, old, new)
        new_raw = raw
        if raw is not None:
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if parsed is not None:
                rewritten = _rewrite(parsed, old, new)
                if rewritten != parsed:
                    new_raw = json.dumps(rewritten, separators=(",", ":"))
        if new_key == key and new_raw == raw:
            continue
        if new_key != key:
            taken = bind.execute(sa.text(
                "SELECT 1 FROM workspace_docs WHERE namespace = :ns AND key = :key"
            ), {"ns": namespace, "key": new_key}).first()
            if taken:
                continue
        bind.execute(sa.text(
            "UPDATE workspace_docs SET key = :new_key, value = :value, rev = rev + 1 "
            "WHERE namespace = :ns AND key = :key"
        ), {"new_key": new_key, "value": new_raw, "ns": namespace, "key": key})


def upgrade():
    _rename_schema("board", "collection")
    _rewrite_workspace("board", "collection")


def downgrade():
    _rewrite_workspace("collection", "board")
    _rename_schema("collection", "board")
