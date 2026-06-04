"""Phase 1 tests for the Recipes feature.

Covers the Phase 1 exit gate from docs/RECIPES_DEV_PLAN.md §Phase 1:

1. CRUD end-to-end.
2. Fork produces an independent copy.
3. Equation store read/write round-trips.
4. Per-recipe SQLite schema matches spec, WAL on, indexes created.
5. Fork (FK SET NULL) + delete behavior.

These tests hit real databases and real on-disk directories via the
`client` / `db_session` fixtures in conftest.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from app_dirs import get_data_dir
from database import Chat, Recipe
from recipe_runtime import (
    EquationStore,
    blob_path_for_hash,
    create_recipe_state_db,
    get_equation_store,
    get_recipe_dir,
    get_recipe_program_base_path,
    get_recipe_program_path,
    get_recipe_state_db_path,
    reset_transient_equation_states,
    verify_state_db_schema,
)
from recipe_runtime.state_db import REQUIRED_INDEXES, REQUIRED_TABLES


# -----------------------------------------------------------------------------
# Per-recipe state.db schema + WAL
# -----------------------------------------------------------------------------

class TestStateDbSchema:
    def test_create_state_db_enables_wal(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal", f"expected WAL mode, got {mode!r}"
        finally:
            conn.close()

    def test_create_state_db_creates_required_tables(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        assert REQUIRED_TABLES <= tables

    def test_create_state_db_includes_equation_definition_column(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(equations)").fetchall()
            }
        finally:
            conn.close()
        assert "definition" in columns

    def test_create_state_db_creates_required_indexes(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        finally:
            conn.close()
        assert REQUIRED_INDEXES <= indexes

    def test_hitl_key_hash_is_unique(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO hitl_results (equation_key, inputs_hash, resolution, created_at) "
                "VALUES ('k', 'h', '\"ok\"', '2026-01-01')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO hitl_results (equation_key, inputs_hash, resolution, created_at) "
                    "VALUES ('k', 'h', '\"other\"', '2026-01-01')"
                )
        finally:
            conn.close()

    def test_verify_state_db_schema_passes_on_fresh_db(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)
        verify_state_db_schema(db_path)  # should not raise

    def test_verify_state_db_schema_fails_without_wal(self, tmp_path):
        # Hand-built DB in delete journal mode — verify_state_db_schema must reject.
        db_path = tmp_path / "state.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute(
                "CREATE TABLE equations (id INTEGER PRIMARY KEY, "
                "equation_key TEXT, equation_type TEXT, status TEXT, "
                "attempt INTEGER, created_at TEXT)"
            )
            conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, task_type TEXT, status TEXT, created_at TEXT, equation_id INTEGER)")
            conn.execute("CREATE TABLE hitl_results (id INTEGER PRIMARY KEY, equation_key TEXT, inputs_hash TEXT, resolution TEXT, created_at TEXT)")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(RuntimeError, match="WAL"):
            verify_state_db_schema(db_path)

    def test_reset_transient_equation_states(self, tmp_path):
        db_path = tmp_path / "state.db"
        create_recipe_state_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executemany(
                "INSERT INTO equations "
                "(equation_key, equation_type, status, attempt, created_at) VALUES (?, ?, ?, 1, '2026-01-01')",
                [
                    ("a", "tool_call", "computing"),
                    ("b", "hitl", "awaiting_input"),
                    ("c", "tool_call", "completed"),
                    ("d", "tool_call", "pending"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        updated = reset_transient_equation_states(db_path)
        assert updated == 2

        conn = sqlite3.connect(str(db_path))
        try:
            rows = dict(
                conn.execute("SELECT equation_key, status FROM equations").fetchall()
            )
        finally:
            conn.close()
        assert rows == {
            "a": "pending",
            "b": "pending",
            "c": "completed",
            "d": "pending",
        }


# -----------------------------------------------------------------------------
# Equation store
# -----------------------------------------------------------------------------

class TestEquationStore:
    def test_initialize_creates_layout(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.initialize()
        assert (tmp_path / "equation_store" / "equations.db").exists()
        assert (tmp_path / "equation_store" / "blobs").is_dir()

    def test_initialize_enables_wal(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.initialize()
        conn = sqlite3.connect(str(store.db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode.lower() == "wal"

    def test_insert_and_lookup_roundtrip_small_result(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.insert(
            "sk-small",
            "tool_call",
            result_small={"media_ids": [1, 2, 3]},
            size_bytes=32,
        )
        entry = store.lookup("sk-small")
        assert entry is not None
        assert entry["equation_type"] == "tool_call"
        assert entry["result_small"] == {"media_ids": [1, 2, 3]}
        assert entry["result_blob_hash"] is None
        assert entry["access_count"] == 1

    def test_insert_and_lookup_roundtrip_metadata(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.insert(
            "sk-meta",
            "tool_call",
            result_small=42,
            result_media_ids=[42],
            execution_duration_ms=1234,
            size_bytes=8,
        )
        entry = store.lookup("sk-meta")
        assert entry is not None
        assert entry["result_small"] == 42
        assert entry["result_media_ids"] == [42]
        assert entry["execution_duration_ms"] == 1234

    def test_lookup_miss_returns_none(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        assert store.lookup("not-a-key") is None

    def test_touch_updates_last_accessed_and_increments_count(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.insert("sk-touch", "llm_call", result_small={"text": "hi"})

        initial = store.lookup("sk-touch")
        assert initial["access_count"] == 1

        assert store.touch("sk-touch") is True

        after = store.lookup("sk-touch")
        assert after["access_count"] == 2
        assert after["last_accessed_at"] >= initial["last_accessed_at"]

    def test_touch_missing_returns_false(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        store.initialize()
        assert store.touch("missing") is False

    def test_blob_write_read_roundtrip(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        payload = b"\x00\x01\x02binary blob"
        content_hash = store.write_blob(payload)
        assert store.read_blob(content_hash) == payload

        # Entry stored with blob hash
        store.insert(
            "sk-blob",
            "code",
            result_blob_hash=content_hash,
            size_bytes=len(payload),
        )
        entry = store.lookup("sk-blob")
        assert entry["result_blob_hash"] == content_hash

    def test_blob_prefix_bucketing_directory_layout(self, tmp_path):
        """The blob's on-disk path must be blobs/<first-2-hex>/<full-hash>."""
        store = EquationStore(tmp_path / "equation_store")
        payload = b"bucket-test"
        content_hash = store.write_blob(payload)

        expected = tmp_path / "equation_store" / "blobs" / content_hash[:2] / content_hash
        assert expected.exists()
        assert expected.read_bytes() == payload

    def test_blob_prefix_bucketing_distinct_hashes(self, tmp_path):
        """Two blobs with different hashes that happen to share no prefix bytes
        must land in different subdirectories; two blobs with the same prefix
        must land in the same subdirectory but as different files."""
        # Pre-fabricated content with overlap only in prefix collision space
        store = EquationStore(tmp_path / "equation_store")

        # Seek two short payloads whose sha256 digests share the same 2-hex prefix.
        # Deterministic and cheap: brute-force a handful of small inputs.
        import hashlib

        prefix_map: dict[str, list[str]] = {}
        for i in range(2000):
            data = f"payload-{i}".encode()
            digest = hashlib.sha256(data).hexdigest()
            bucket = digest[:2]
            prefix_map.setdefault(bucket, []).append(digest)
            if len(prefix_map[bucket]) >= 2:
                shared_bucket = bucket
                hash_a, hash_b = prefix_map[bucket][:2]
                # Find which payloads produced them
                payload_a = next(
                    f"payload-{j}".encode()
                    for j in range(2000)
                    if hashlib.sha256(f"payload-{j}".encode()).hexdigest() == hash_a
                )
                payload_b = next(
                    f"payload-{j}".encode()
                    for j in range(2000)
                    if hashlib.sha256(f"payload-{j}".encode()).hexdigest() == hash_b
                )
                break
        else:
            pytest.skip("no hash-prefix collision found in search space")

        stored_a = store.write_blob(payload_a)
        stored_b = store.write_blob(payload_b)
        assert stored_a == hash_a
        assert stored_b == hash_b

        path_a = blob_path_for_hash(hash_a, store.blobs_dir)
        path_b = blob_path_for_hash(hash_b, store.blobs_dir)
        assert path_a.parent == path_b.parent  # same prefix bucket
        assert path_a != path_b                 # different files inside the bucket
        assert path_a.parent.name == shared_bucket
        assert path_a.read_bytes() == payload_a
        assert path_b.read_bytes() == payload_b

    def test_write_blob_is_idempotent(self, tmp_path):
        store = EquationStore(tmp_path / "equation_store")
        data = b"dedup me"
        h1 = store.write_blob(data)
        h2 = store.write_blob(data)
        assert h1 == h2
        path = blob_path_for_hash(h1, store.blobs_dir)
        # Only one file (plus the atomic-rename safety the writer should clean up).
        stray_tmp = path.with_name(path.name + ".tmp")
        assert path.exists()
        assert not stray_tmp.exists()


# -----------------------------------------------------------------------------
# Recipe CRUD via HTTP
# -----------------------------------------------------------------------------

class TestRecipeCrud:
    async def test_create_recipe_creates_disk_layout(self, client):
        resp = await client.post(
            "/api/recipes",
            json={
                "name": "Poster Series",
                "description": "Test recipe",
                "input_schema": {"names": "list[str]"},
                "output_schema": {"posters": "list[media]"},
                "inputs": {"names": ["Mojito"]},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Poster Series"
        assert body["execution_state"] == "idle"
        assert body["input_schema"] == {"names": "list[str]"}
        assert body["parent_id"] is None
        assert body["program_hash"] is None or isinstance(body["program_hash"], str)

        recipe_id = body["id"]
        recipe_dir = get_recipe_dir(recipe_id)
        assert recipe_dir.is_dir()
        assert get_recipe_program_path(recipe_id).exists()
        assert get_recipe_state_db_path(recipe_id).exists()
        assert not get_recipe_program_base_path(recipe_id).exists(), \
            "non-forked recipe must not have program_base.py"
        assert (recipe_dir / "resources").is_dir()
        metadata = json.loads((recipe_dir / "metadata.json").read_text())
        assert metadata["recipe_id"] == recipe_id
        assert metadata["name"] == "Poster Series"

        # Verify per-recipe DB schema and WAL
        verify_state_db_schema(get_recipe_state_db_path(recipe_id))

    async def test_get_recipe_roundtrips(self, client):
        created = (await client.post("/api/recipes", json={"name": "R1"})).json()
        fetched = (await client.get(f"/api/recipes/{created['id']}")).json()
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "R1"

    async def test_get_recipe_404(self, client):
        resp = await client.get("/api/recipes/999999")
        assert resp.status_code == 404

    async def test_patch_recipe(self, client):
        created = (await client.post("/api/recipes", json={"name": "old"})).json()
        resp = await client.patch(
            f"/api/recipes/{created['id']}",
            json={"name": "new", "execution_state": "running"},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "new"
        assert updated["execution_state"] == "running"

    async def test_patch_rejects_invalid_execution_state(self, client):
        created = (await client.post("/api/recipes", json={"name": "x"})).json()
        resp = await client.patch(
            f"/api/recipes/{created['id']}",
            json={"execution_state": "bogus"},
        )
        assert resp.status_code == 400

    async def test_delete_is_soft(self, client, db_session):
        created = (await client.post("/api/recipes", json={"name": "to-del"})).json()
        recipe_id = created["id"]

        resp = await client.delete(f"/api/recipes/{recipe_id}")
        assert resp.status_code == 200

        # Not in default list
        listed = (await client.get("/api/recipes")).json()
        assert all(r["id"] != recipe_id for r in listed)

        # GET returns 404
        assert (await client.get(f"/api/recipes/{recipe_id}")).status_code == 404

        # Directory preserved
        assert get_recipe_dir(recipe_id).is_dir()

        # DB row has deleted_at set
        from sqlalchemy import select
        async with db_session() as session:
            row = (await session.execute(select(Recipe).where(Recipe.id == recipe_id))).scalar_one()
            assert row.deleted_at is not None

    async def test_list_filters(self, client):
        # Create three recipes: two idle, one we then put in running.
        a = (await client.post("/api/recipes", json={"name": "A"})).json()
        b = (await client.post("/api/recipes", json={"name": "B"})).json()
        c = (await client.post("/api/recipes", json={"name": "C"})).json()

        await client.patch(f"/api/recipes/{b['id']}", json={"execution_state": "running"})

        running = (await client.get("/api/recipes?execution_state=running")).json()
        running_ids = {r["id"] for r in running}
        assert b["id"] in running_ids
        assert a["id"] not in running_ids
        assert c["id"] not in running_ids

        bad = await client.get("/api/recipes?execution_state=bogus")
        assert bad.status_code == 400

    async def test_list_filter_by_project_id(self, client):
        project = (await client.post("/api/projects", json={"name": "P"})).json()
        in_proj = (
            await client.post("/api/recipes", json={"name": "in", "project_id": project["id"]})
        ).json()
        out_proj = (await client.post("/api/recipes", json={"name": "out"})).json()

        listed = (await client.get(f"/api/recipes?project_id={project['id']}")).json()
        ids = {r["id"] for r in listed}
        assert in_proj["id"] in ids
        assert out_proj["id"] not in ids

    async def test_list_without_project_id_excludes_project_recipes(self, client):
        project = (await client.post("/api/projects", json={"name": "P-top"})).json()
        in_proj = (
            await client.post(
                "/api/recipes", json={"name": "scoped", "project_id": project["id"]}
            )
        ).json()
        out_proj = (await client.post("/api/recipes", json={"name": "unscoped"})).json()

        listed = (await client.get("/api/recipes")).json()
        ids = {r["id"] for r in listed}
        assert in_proj["id"] not in ids
        assert out_proj["id"] in ids

    async def test_list_filter_by_parent_id(self, client):
        parent = (await client.post("/api/recipes", json={"name": "parent-f"})).json()
        fork = (
            await client.post(f"/api/recipes/{parent['id']}/fork", json={})
        ).json()
        other = (await client.post("/api/recipes", json={"name": "unrelated-f"})).json()

        listed = (await client.get(f"/api/recipes?parent_id={parent['id']}")).json()
        ids = {r["id"] for r in listed}
        assert fork["id"] in ids
        assert other["id"] not in ids
        assert parent["id"] not in ids

    async def test_rejects_invalid_project_id(self, client):
        resp = await client.post("/api/recipes", json={"name": "bad", "project_id": 999999})
        assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Fork
# -----------------------------------------------------------------------------

class TestRecipeFork:
    async def test_fork_sets_parent_id_and_copies_directory(self, client):
        parent = (
            await client.post(
                "/api/recipes",
                json={"name": "P", "inputs": {"names": ["A"]}},
            )
        ).json()

        # Drop a fake resource file inside parent's resources/ so we can prove
        # the fork got a real copy (not just an empty dir).
        marker = get_recipe_dir(parent["id"]) / "resources" / "marker.txt"
        marker.write_text("parent resource")

        fork = (
            await client.post(
                f"/api/recipes/{parent['id']}/fork",
                json={"inputs": {"names": ["B"]}},
            )
        ).json()
        assert fork["parent_id"] == parent["id"]
        assert fork["execution_state"] == "idle"
        assert fork["inputs"] == {"names": ["B"]}

        fork_marker = get_recipe_dir(fork["id"]) / "resources" / "marker.txt"
        assert fork_marker.exists()
        assert fork_marker.read_text() == "parent resource"

    async def test_fork_creates_program_base(self, client):
        parent = (await client.post("/api/recipes", json={"name": "P2"})).json()

        # Write distinctive parent program so we can check program_base.py
        parent_program = get_recipe_program_path(parent["id"])
        parent_program.write_text("# PARENT PROGRAM VERSION 1\n")

        fork = (
            await client.post(f"/api/recipes/{parent['id']}/fork", json={})
        ).json()

        base = get_recipe_program_base_path(fork["id"])
        assert base.exists()
        assert base.read_text() == "# PARENT PROGRAM VERSION 1\n"

        # Parent's own program_base.py must not exist (parent was not forked).
        assert not get_recipe_program_base_path(parent["id"]).exists()

    async def test_fork_edits_dont_affect_parent(self, client):
        parent = (await client.post("/api/recipes", json={"name": "P3"})).json()
        fork = (
            await client.post(f"/api/recipes/{parent['id']}/fork", json={})
        ).json()

        # Modify the fork's program and add a file to its resources/.
        fork_program = get_recipe_program_path(fork["id"])
        fork_program.write_text("# FORK-SPECIFIC EDIT\n")
        (get_recipe_dir(fork["id"]) / "resources" / "fork_only.txt").write_text("fork content")

        # Parent's program must remain the empty placeholder.
        parent_program = get_recipe_program_path(parent["id"])
        assert "FORK-SPECIFIC EDIT" not in parent_program.read_text()
        assert not (get_recipe_dir(parent["id"]) / "resources" / "fork_only.txt").exists()

    async def test_fork_resets_transient_equation_states(self, client):
        parent = (await client.post("/api/recipes", json={"name": "P4"})).json()

        # Pre-populate parent's state.db with mixed equation statuses.
        parent_db = get_recipe_state_db_path(parent["id"])
        conn = sqlite3.connect(str(parent_db))
        try:
            conn.executemany(
                "INSERT INTO equations "
                "(equation_key, equation_type, status, attempt, created_at) VALUES (?, ?, ?, 1, '2026-01-01')",
                [
                    ("k1", "tool_call", "computing"),
                    ("k2", "hitl", "awaiting_input"),
                    ("k3", "tool_call", "completed"),
                ],
            )
            k2_id = conn.execute(
                "SELECT id FROM equations WHERE equation_key = 'k2'",
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO tasks "
                "(equation_id, task_type, status, instructions, created_at) "
                "VALUES (?, 'configure', 'pending', 'choose', '2026-01-01')",
                (k2_id,),
            )
            conn.commit()
        finally:
            conn.close()

        fork = (await client.post(f"/api/recipes/{parent['id']}/fork", json={})).json()

        fork_db = get_recipe_state_db_path(fork["id"])
        conn = sqlite3.connect(str(fork_db))
        try:
            rows = dict(
                conn.execute("SELECT equation_key, status FROM equations").fetchall()
            )
            task_count = conn.execute(
                "SELECT count(*) FROM tasks WHERE status = 'pending'",
            ).fetchone()[0]
        finally:
            conn.close()
        # Transient statuses reset, completed untouched.
        assert rows == {"k1": "pending", "k2": "pending", "k3": "completed"}
        assert task_count == 0

    async def test_fork_with_override_fields(self, client):
        parent = (
            await client.post(
                "/api/recipes",
                json={"name": "orig", "description": "orig desc"},
            )
        ).json()
        fork = (
            await client.post(
                f"/api/recipes/{parent['id']}/fork",
                json={"name": "override", "description": "override desc"},
            )
        ).json()
        assert fork["name"] == "override"
        assert fork["description"] == "override desc"


# -----------------------------------------------------------------------------
# FK behavior (SET NULL) + recipe-scoped chat
# -----------------------------------------------------------------------------

class TestRecipeFkBehavior:
    async def test_soft_deleting_parent_leaves_fork_functional(self, client):
        """Soft delete is the actual v1 delete path. The fork must remain
        reachable and continue to reference its parent's id."""
        parent = (await client.post("/api/recipes", json={"name": "parent"})).json()
        fork = (
            await client.post(f"/api/recipes/{parent['id']}/fork", json={})
        ).json()

        assert (await client.delete(f"/api/recipes/{parent['id']}")).status_code == 200

        still = (await client.get(f"/api/recipes/{fork['id']}")).json()
        assert still["parent_id"] == parent["id"]
        # And resources are intact — fork is fully operational.
        assert get_recipe_dir(fork["id"]).is_dir()
        assert get_recipe_program_path(fork["id"]).exists()

    async def test_recipes_fk_set_null_declared_in_schema(self, db_session):
        """The recipes table's parent_id and project_id FKs must be declared
        with ON DELETE SET NULL, so a future hard-delete path doesn't orphan
        the fork. Verified via PRAGMA foreign_key_list, which returns the
        declared on_delete action regardless of whether FK enforcement is on.
        """
        from sqlalchemy import text

        async with db_session() as session:
            rows = (
                await session.execute(
                    text("PRAGMA foreign_key_list(recipes)")
                )
            ).fetchall()

        fk_by_column = {row._mapping["from"]: row._mapping["on_delete"] for row in rows}
        assert fk_by_column.get("parent_id") == "SET NULL"
        assert fk_by_column.get("project_id") == "SET NULL"

    async def test_chats_has_recipe_id_column(self, db_session):
        """chats.recipe_id is added by alembic as a nullable column + index.
        SQLite's `op.add_column` does not attach FK constraints to an existing
        table (that would require a full table rebuild); enforcement is at the
        app layer (create_chat 404s for invalid recipe_id), matching the
        existing pattern for chats.project_id."""
        from sqlalchemy import text

        async with db_session() as session:
            rows = (
                await session.execute(text("PRAGMA table_info(chats)"))
            ).fetchall()
            columns = {row._mapping["name"] for row in rows}

            idx_rows = (
                await session.execute(text("PRAGMA index_list(chats)"))
            ).fetchall()
            index_names = {row._mapping["name"] for row in idx_rows}

        assert "recipe_id" in columns
        assert "ix_chats_recipe_id" in index_names


class TestRecipeScopedChat:
    async def test_create_chat_with_recipe_id(self, client):
        recipe = (await client.post("/api/recipes", json={"name": "chatty"})).json()

        resp = await client.post("/api/chats", json={"recipe_id": recipe["id"]})
        assert resp.status_code == 200, resp.text
        chat = resp.json()
        assert chat["recipe_id"] == recipe["id"]

    async def test_chat_rejects_invalid_recipe_id(self, client):
        resp = await client.post("/api/chats", json={"recipe_id": 999999})
        assert resp.status_code == 404

    async def test_general_chat_lists_exclude_recipe_chats_by_default(self, client):
        recipe = (await client.post("/api/recipes", json={"name": "chatty"})).json()

        general_resp = await client.post("/api/chats", json={})
        assert general_resp.status_code == 200, general_resp.text
        general_chat = general_resp.json()

        recipe_resp = await client.post("/api/chats", json={"recipe_id": recipe["id"]})
        assert recipe_resp.status_code == 200, recipe_resp.text
        recipe_chat = recipe_resp.json()

        list_resp = await client.get("/api/chats?page=1&page_size=20")
        assert list_resp.status_code == 200, list_resp.text
        listed_ids = {item["id"] for item in list_resp.json()["items"]}
        assert general_chat["id"] in listed_ids
        assert recipe_chat["id"] not in listed_ids

        preview_resp = await client.get("/api/chats/previews?page=1&page_size=20")
        assert preview_resp.status_code == 200, preview_resp.text
        preview_ids = {item["id"] for item in preview_resp.json()["items"]}
        assert general_chat["id"] in preview_ids
        assert recipe_chat["id"] not in preview_ids

    async def test_recipe_chat_lists_remain_available_when_recipe_id_is_specified(self, client):
        recipe = (await client.post("/api/recipes", json={"name": "chatty"})).json()
        resp = await client.post("/api/chats", json={"recipe_id": recipe["id"]})
        assert resp.status_code == 200, resp.text
        recipe_chat = resp.json()

        list_resp = await client.get(f"/api/chats?page=1&page_size=20&recipe_id={recipe['id']}")
        assert list_resp.status_code == 200, list_resp.text
        listed_ids = {item["id"] for item in list_resp.json()["items"]}
        assert recipe_chat["id"] in listed_ids

        preview_resp = await client.get(f"/api/chats/previews?page=1&page_size=20&recipe_id={recipe['id']}")
        assert preview_resp.status_code == 200, preview_resp.text
        preview_ids = {item["id"] for item in preview_resp.json()["items"]}
        assert recipe_chat["id"] in preview_ids
