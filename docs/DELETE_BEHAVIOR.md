# Delete Behavior

This document describes how permanent delete works after the resumable delete-pipeline rewrite.

## Goals

Permanent delete is intended to remove a media item from the live app state without blocking the backend on large trash-empty operations.

After a permanent delete completes:
- the original `media_items` row is gone
- the original file and editor sidecar are gone
- surviving references in chats and lineage are rewritten to tombstones
- thumbnail cache entries created under the new system are purged
- related association rows are removed

Out of scope:
- filesystem shredding / secure erase
- scrubbing arbitrary exported files outside the managed DB + cache
- exact purge of legacy thumbnail cache files that predate thumbnail-cache indexing

## High-Level Model

Permanent delete is now a background operation, not an inline request.

Request flow:
1. User trashes an asset with soft delete as before.
2. User permanently deletes one item, a batch, or empties trash.
3. The API creates a durable delete operation and returns immediately.
4. A background worker processes the operation in small batches.
5. The UI observes progress through websocket events or polling endpoints.

This is designed for large `empty trash` runs that may contain tens of thousands of items.

## Schema

The delete pipeline adds three tables:

- `delete_operations`
  - durable parent operation
  - one row per single delete / batch delete / empty-trash request
- `delete_operation_items`
  - one row per media item in the operation
  - tracks per-item state, lease, retries, and cached file metadata
- `media_thumbnail_cache`
  - exact index of generated thumbnail cache files by `media_id`
  - used so permanent delete can purge known cached previews without scanning the whole cache tree

Relevant code:
- [database.py](backend/database.py)
- [c3d4e5f6a7b8_add_delete_operations_and_thumbnail_cache.py](backend/alembic/versions/c3d4e5f6a7b8_add_delete_operations_and_thumbnail_cache.py)

## Operation States

Operation-level status:
- `queued`
- `running`
- `completed`
- `failed`

Per-item state:
- `pending`
- `claimed`
- `refs_scrubbed`
- `cache_purged`
- `media_deleted`
- `done`
- `failed`

The worker also tracks `current_phase` for UI visibility:
- `claiming`
- `scrubbing_refs`
- `purging_cache`
- `deleting_media_row`
- `completed`
- `failed`

## Worker Behavior

Implementation lives in:
- [delete_operations.py](backend/delete_operations.py)

Startup wiring:
- [app.py](backend/core/app.py)

Important properties:

- The worker runs continuously in the main backend process.
- It processes one profile at a time, in small batches.
- It does not hold a long SQLite write lock across the full operation.
- Each item is leased for a short interval.
- Expired leased items are returned to `pending`, which makes the system crash-safe and resumable.

Batching defaults:
- claim batch size: 100 items
- short commits between claim, scrub, cache purge, and row delete phases

## Scrubbing Rules

Before a media row is deleted, the worker rewrites surviving references.

### Chat references

Code path:
- [delete_operations.py](backend/delete_operations.py)
- read-time fallback still exists in [chats.py](backend/routes/chats.py)

Behavior:
- `chat_items.media_id` becomes `NULL` if it pointed to the deleted asset
- `chat_items.media_ids` removes deleted ids
- `item_metadata` and `tool_result` JSON payloads are recursively rewritten
- references become a generic tombstone object rather than retaining `media_id`, path, prompt, etc.

The UI already knows how to render deleted placeholders in chat.

### Generation metadata / descendant provenance

Behavior:
- descendant `media_items.generation_metadata` is parsed and rewritten
- `source_inputs` entries referencing the deleted media become tombstones
- `lineage_trace` entries referencing the deleted media become tombstones
- prompt/model/parameter-like fields are stripped from rewritten entries

### Lineage rows

Behavior:
- for descendant `media_lineage` rows where `source_media_id` referenced the deleted asset:
  - `source_media_id -> NULL`
  - `source_file_path -> NULL`
- direct lineage rows owned by the deleted media are removed when the media row is deleted

Result:
- descendants can still show that some deleted source existed
- identity/path/media id are not preserved in the surviving lineage row

### Tool / job references

Behavior:
- `tools.source_media_id -> NULL`
- `generation_jobs.result_media_id -> NULL`

### Association cleanup

Explicit deletes are used for:
- `faces`
- `media_keywords`
- `media_markers`
- `media_tags`
- `media_tool_lineage`
- `project_media`
- `board_items`

This is deliberate. The code does not rely on SQLite FK enforcement to clean everything up.

## Tombstone Shape

The worker rewrites references to a minimal tombstone form.

Base shape:

```json
{
  "deleted": true,
  "tombstone_type": "media"
}
```

Some non-sensitive structural keys may be preserved when useful, such as:
- `role`
- `task_type`
- `relationship_type`
- `status`
- `label`
- `name`

Fields that should not survive when attached to a deleted media ref include:
- `media_id`
- `media_ids`
- `file_path`
- `file_hash`
- `prompt`
- `negative_prompt`
- `parameters`
- `model`
- `tool_id`
- `preset_id`
- `caption`
- `raw_metadata`
- `generation_metadata`
- `workspace_url`

## Thumbnail Cache

Thumbnail generation now records cache file paths in `media_thumbnail_cache`.

Relevant code:
- [media_files.py](backend/routes/media_files.py)

Behavior:
- when a thumbnail is served from cache or newly generated, the cache path is indexed against `media_id`
- on permanent delete, indexed cache files are deleted and their index rows are removed

Limitation:
- cache files created before this index existed are not known precisely
- clearing the cache directory manually is the supported cleanup for those legacy files

## API Contract

Trash endpoints now queue work instead of deleting inline:

- `DELETE /api/trash/{media_id}`
- `POST /api/trash/batch/delete`
- `DELETE /api/trash`

Response shape is now `202 Accepted` with an operation payload.

Additional endpoints:
- `GET /api/delete-operations/active`
- `GET /api/delete-operations/{operation_id}`

Relevant code:
- [trash.py](backend/routes/trash.py)

## Websocket Events

The worker emits:
- `delete_operation_started`
- `delete_operation_progress`
- `delete_operation_completed`
- `delete_operation_failed`

Existing delete-related events are still used for item removal:
- `media_permanently_deleted`
- `trash_emptied`

## Frontend Behavior

Frontend integration points:
- [useDeleteOperations.js](frontend/src/composables/useDeleteOperations.js)
- [TopBar.vue](frontend/src/components/TopBar.vue)
- [BrowseGridView.vue](frontend/src/views/BrowseGridView.vue)
- [MediaContextMenu.vue](frontend/src/components/media/MediaContextMenu.vue)
- [SlideshowMode.vue](frontend/src/components/SlideshowMode.vue)

Behavior:
- permanent delete actions now enqueue and toast immediately
- the UI does not optimistically assume the item is already gone
- the top bar shows progress for active delete operations
- trash/grid/chat cleanup happens when websocket completion/removal events arrive

## Tests

Primary coverage:
- [test_alembic_integrity.py](backend/tests/test_alembic_integrity.py)
- [test_trash.py](backend/tests/test_trash.py)
- [test_boards.py](backend/tests/test_boards.py)

Covered areas:
- Alembic graph integrity
- async permanent delete contract
- batch delete and empty-trash queueing
- websocket completion behavior
- board cleanup after permanent delete
- scrubbing of chat refs, lineage refs, and tool refs

## Guidance For Future Agents

If you change delete behavior:
- do not convert permanent delete back to inline request work
- do not hold one SQLite transaction across a whole trash-empty run
- preserve idempotence at the per-item phase level
- keep tombstones minimal and non-identifying
- update tests when changing API semantics or websocket behavior

If you add a new data structure that can reference media:
- decide whether it should be deleted, nulled, or tombstoned on permanent delete
- add explicit scrub logic in [delete_operations.py](backend/delete_operations.py)
- add a test proving the reference is cleaned up

If you add a new cache derived from media:
- either index it like `media_thumbnail_cache`
- or provide an equally precise purge mechanism for permanent delete
