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
