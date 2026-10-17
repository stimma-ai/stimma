# Agent library queries

The `library` agent tool and `stimma.library` Python SDK share filtering and
lineage implementations. Discover fields with `library(action="browse_schema")`
or `await stimma.library.schema()`. Discover recorded values with `browse_options`
or `await stimma.library.options("loras")` (also models, task_types, direct_tools,
tags, folders, and other facets).

## Find

`library(action="browse", filters=..., limit=20, offset=0)` and
`await stimma.library.query(filters, limit=20, offset=0)` return a page containing
`items`, `total`, `has_more`, `limit`, `offset`, `applied_filters`, and `sort`.
Advance `offset` by the page's item count until `has_more` is false. Limits are
1–500. The older SDK `browse()` and `search()` methods return lists and accept
filters and offsets too. Search is text matching, not semantic/vector search.

Text fields: `prompt_query`, `negative_prompt_query`, `caption_query`,
`keyword_query`, `query` (positive prompts, captions, keywords), `filenames`,
`models`, `loras`, `task_types`, `direct_tools`.

```python
page = await stimma.library.query({
    "media_types": ["images"],
    "loras": {"include": ["portrait*"], "exclude": ["*draft*"], "match": "glob"},
    "prompt_query": {"include": ["sunset", "ocean"], "mode": "all"},
})
```

- A string or list means `contains` matching, with any included term sufficient.
- Objects accept `include`, `exclude`, `match` (`contains`, `exact`, `glob`), and
  `mode` (`any`, `all`). Excluded terms must all be absent. Fields combine with AND.
- Glob operators are `*` and `?`; brackets, SQL `%`, and SQL `_` are literal.
  Matching uses SQLite case-insensitive LIKE (ASCII case folding).
- Model, LoRA and filename exact/glob matching accepts full paths or basenames;
  path separators are normalized. Prompts search imported/extracted, rendered,
  and original user prompts. Negative prompts are separate.
- Models, LoRAs, task types and direct tools describe the payload's own recorded
  generation. The legacy `tools` facet includes tools inherited from ancestors.
- Other facets include media types, resolution buckets, folders, keywords, tags,
  markers, generated status, creation date bounds, and exact `media_ids`.
  Use the schema for their supported values and include/exclude syntax.
- Unknown fields, invalid matching modes, and inappropriate action arguments
  fail with an error instead of silently broadening the query.

The default `scope="assets"` searches current, active library Assets, scoped to
the chat's project when present. `scope="media"` explicitly searches profile-wide
nondeleted, nonephemeral payloads, including intermediate media and old revisions.
Tags and markers require Assets scope. Pending metadata and unavailable files
remain discoverable; result summaries report their status.

## Inspect and traverse

`library(action="inspect", media_ids=[...])` or
`await stimma.library.inspect([...])` returns metadata and history for up to 500
IDs without copying files. Missing/deleted/ephemeral IDs return status placeholders.
Use `get(media_id)` when the actual file is needed in the workspace.

`lineage` accepts one `media_id` or a batch of `media_ids`, `direction`
(`parents`, `children`, `ancestors`, `descendants`), and `relationship`
(`derived`, `inspired`, `all`; default derived).

The response contains `roots`, `edges`, endpoint `items`, `total`, and `has_more`.
Pagination counts **edges per root**, not media. An edge contains
`root_media_id`, `source_media_id`, `output_media_id`, `task_type`,
`relationship_type`, `source_order`, and `input_role` when recorded. Shared
descendants keep every input edge; recursive traversal terminates even with cycles.

Optional `filters` select reached sources when going upstream, or reached outputs
when going downstream. They do not prune traversal through nonmatching media.
They use Media scope: ancestors need not be standalone Assets.

For videos based on Klein 9B images, find matching images in Media scope, then
traverse descendants with a video endpoint filter. Use options to discover the
recorded model names; paginate both searches and traversal for an exhaustive result.

```python
images = await stimma.library.query({
    "models": {"include": ["*klein*9b*"], "match": "glob"},
    "media_types": ["images"],
}, scope="media")
graph = await stimma.library.lineage(
    media_ids=[item["media_id"] for item in images["items"]],
    direction="descendants", filters={"media_types": ["videos"]},
)
```

For upscaled videos and their originals, find video outputs whose own `task_types`
match the recorded upscale task, then traverse `parents`. Pair each edge's
`source_media_id` with `output_media_id`; preserve input roles/order for multi-input
steps. A non-null `asset_id` on endpoint summaries identifies a current library Asset.

Lineage only claims **recorded relational edges**. Imported files and older records
may contain history snapshots without navigable edges; `inspect` exposes these
snapshots and raw metadata. External or deleted sources are reported explicitly.
No edges is not proof that an item has no ancestry. Model names are recorded labels
or parameters, not inferred identities. Missing provenance cannot be reconstructed
by a query.

The lineage action now returns graph pages; callers that previously read
`lineage()["history"]` should use `inspect()["items"][0]["history"]`.

## Similarity and embeddings

Background indexing stores a CLIP embedding for every library image and an
identity embedding for every detected face. The `stimma` SDK exposes both in
`run_code`; `sdk_help("similarity")` lists the methods for the agent.

| Method | Answers |
|---|---|
| `detect_faces(media_id, *, wait=True, timeout=60)` | Faces in an image: `id`, `bbox`, `area`, `confidence`, `embedding`, most confident first |
| `face_similarity(a, b)` | Same person? Cosine plus which faces were compared |
| `find_faces_like(ref, *, limit=50, min_similarity=None)` | Every library shot of this person, best face per image |
| `clip_embedding(target)` | The CLIP vector, `dim` and `model` for a media id, workspace path or text |
| `clip_similarity(a, b)` | Look/content similarity between any mix of media, paths and text |
| `find_similar(ref, *, limit=50, min_similarity=None)` | The library's "find similar", by image or text |
| `pairwise_similarity(targets, *, kind="clip"\|"face")` | N×N matrix (N ≤ 64) for duplicate/diversity checks |

Face similarity is identity; CLIP is visual and semantic similarity (scene,
style, subject, near-duplicates). The two answer different questions.

References. A media id reads the stored embedding. A face reference is an
entry from `detect_faces`/`find_faces_like` or `{"face_id": n}`; a media id
used as a face means its largest face. A workspace path (or `ToolResult`) is
embedded live with the loaded models and never inserted into the library.
For CLIP, a string naming an image file is a path and any other string is
text. Search results are dicts with `media_id`, so they can be passed back in.

Cache first. Media that is still pending indexing is waited on (the indexer is
woken, then the status is polled) up to `timeout`; `wait=False` raises
immediately. Failed indexing, non-visual media, and run intermediates raise
with a message naming the workaround (copy the file into the workspace and
pass the path). A media id whose CLIP vector came from an older model is
rescheduled for indexing and waited on, and the library-wide search
reschedules stale candidates the same way as the HTTP similar search.

Population. `find_similar` and `find_faces_like` search the same population as
`POST /api/search/similar` (`routes.media.similarity_search_population`):
live current-revision Asset payloads only, never trashed, deletion-pending,
ephemeral run intermediates, unfinished metadata or unavailable files. The
reference image itself is excluded. Default thresholds come from settings:
`clip_similarity_threshold` (0.75) for image references,
`clip_text_similarity_threshold` (0.225) for text, and
`face_detection.similarity_threshold` (0.55) for faces.

Calibration, measured with the shipped models on 57 single-face public
portraits of two people (804 same-person and 792 different-person pairs):

| Pair | Face cosine | CLIP cosine |
|---|---|---|
| Different people | median 0.03, max 0.20 | median 0.73, p5–p95 0.60–0.79 |
| Same person, different photo | median 0.63, p5 0.32; 94% ≥ 0.35, 66% ≥ 0.55 | median 0.88, p5–p95 0.73–0.95 |
| Same photo recropped and resized | median 0.97 | median 0.99, p5 0.95 |

The 0.55 face default favours precision and misses about a third of genuine
same-person pairs across varied photos; about 0.35 still left a wide margin
over every different-person pair seen. The sample is small (two identities),
so the help text presents these as guidance, not rules.
