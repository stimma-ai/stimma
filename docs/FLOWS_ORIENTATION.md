# Flows — Orientation

Single-file entry point for agents working on the Stimma flows feature. Read
this first. The source of truth for behavior is the code (see the file map in
§11); §9 lists known gaps where behavior may not match expectations.

---

## 1. What a flow is

A flow is a parameterized, repeatable creative workflow authored as a Python
program. The user defines inputs (a list of artist names, a style enum, a
reference image, etc.), phases (organizational grouping), and steps (tool
calls, LLM calls, human decisions, code transforms). Running a flow
evaluates its equation graph for a given set of inputs and produces library
assets.

Flows are scoped top-level or project-scoped, and can be **forked**. A fork
snapshots the program and reuses compatible upstream results for free via a
content-addressed store.

---

## 2. Two-phase mental model

Flow files have **two lives in the same Python source**:

1. **Graph-build time.** The DSL primitives (`tool`, `llm`, `code`, `hitl.*`,
   `foreach`, `switch`, `filter`, `partition`) don't execute anything. They return opaque `NodeRef`
   objects and register equations in the graph. The whole decorated `@flow`
   function runs once to shape the graph.
2. **Evaluation time.** The FRP runtime walks the graph, resolves
   dependencies, runs tools/LLMs/code/HITL tasks, writes results to the store.

Consequences an agent must internalize:

- `NodeRef` values are **opaque at build time**. Don't `if` on them, don't
  subscript them, don't print them, don't pass them through non-DSL code. Use
  them only as inputs to other primitives or inside `code()` bodies.
- Flow input values and `foreach` callback item parameters **are** resolved
  values; you can use them in f-strings and arithmetic at build time.
- The graph is data-dependency driven. Phases are organizational only; they
  don't constrain execution order.

---

## 3. DSL surface (quick reference)

All importable from `flow_dsl.primitives` (compat shim exists at
`flow_runtime.dsl`):

| Primitive | Purpose | Returns |
|---|---|---|
| `@flow(...)` | Decorator on the top-level function | `FlowDecorated` |
| `input(spec)` / `output(spec)` | Declare flow I/O schema | spec objects |
| `phase(name)` | Context manager; groups equations in the tree | context mgr |
| `tool(tool_id, *, task_type, **params)` | Invoke a registered tool (`task_type` required, must match the tool's declared `task_types`) | `NodeRef` |
| `llm(template, inputs=..., ...)` | LLM call | `NodeRef` |
| `code(fn_or_src, *, inputs, output_type)` | Run Python in sandbox | `NodeRef` |
| `info(body, *, title, subtitle="", inputs=None)` | Render inline markdown card | `NodeRef` |
| `foreach(items, callback, **kwargs)` | Iterate over a collection | `NodeRef` (list) |
| `fill_slots(count, generate, *, instructions)` | N user-approved candidates with regenerate-on-reject | `NodeRef` (list of N) |
| `switch(value, cases, default=None)` | Select a value without changing graph shape | `NodeRef` |
| `when(condition, value, otherwise=None)` / `gate(condition, value, otherwise=None)` | Value-level conditional pass-through | `NodeRef` |
| `filter(items, predicate)` / `filter_items(...)` | Keep matching collection items | `NodeRef` (list) |
| `partition(items, classifier, labels=[...])` | Split a collection into labeled lists | `NodeRef` |
| `take(items, n)` | Return the first `n` items | `NodeRef` (list) |
| `zip_nodes(*collections)` | Parallel-iterate keyed collections | `NodeRef` |
| `web_search(query, *, kind="text"|"images", n=10)` | Search web/images; image rows include previewable URL media | `NodeRef` (list) |
| `fetch_media(url, *, max_size_mb=10)` | Download one URL into the asset library | `NodeRef` (media) |
| `hitl.select(candidates, count=1)` | Human picks from candidates | `NodeRef` |
| `hitl.approve(asset)` | Human accepts/rejects | `NodeRef` |

`hitl` is a namespace object (`_Hitl()` in `primitives.py`), not a module.

Media outputs also declare retention behavior with
`output("media", disposition=...)`: `independent` (the default) creates an
Asset, `container` requires one set/grid and creates one container Asset,
`internal` keeps contextual Flow Media out of Asset browsers, and `ephemeral`
marks short-lived contextual output. Intermediate equations are always
contextual Media regardless of the surfaced output defaults.

Source of truth: `backend/flow_dsl/primitives.py`.

### Media states in flow flows

Be precise about media representation:

- `media` means a library asset, usually a media id. It can participate in
  lineage and can be passed to tools, `llm(images=...)`, `create_layout`, etc.
- URL media is a previewable remote image descriptor:
  `{type: "url_media", url, mime_type, title, source}`. It is not in the
  library and has no media id yet.
- `web_search(..., kind="images")` returns rows with both legacy `image_url`
  and a `media` URL-media descriptor. Showing or selecting these rows does not
  add all search results to the asset library.
- When a URL media descriptor is chosen through `hitl.select`/reselect, the
  runtime promotes only that chosen item to a library media item and records
  the resulting `media_id` on the selected row. Use `fetch_media(url)` only
  when the flow intentionally needs to import a URL before selection or for
  every item in a batch.

---

## 4. Equation keys (identity)

Every equation has a stable **equation key** used for dependency tracking,
HITL result recovery, and seed derivation.

- Top level: `"{function_name}:{iteration_key}"`
- Nested: `"{fn}:{iter}/{nested_kind}${index}"`

**Iteration keys** identify items in a collection so store reuse works across
re-runs. Derivation is automatic (`backend/flow_runtime/keys.py`):

- **`KEYED` mode** — value-derived; driven by `element_kind`:
  - `"scalar"` → the value itself (e.g. `"Monet"`)
  - `"media"` → media content hash
  - `"json"` / `"dict"` → stable JSON hash
- **`POSITIONAL`** — `range(N)`, `llm(..., n=N)`, and hand-built node lists use indices `"0".."N-1"`
- **`INHERITED`** — callbacks inside `foreach` inherit the outer iteration key

Rules to remember:

- Renaming a function changes every one of its equation keys → HITL decisions
  on those equations are lost (best-effort recovery is **not implemented**
  today — see §9).
- `zip_nodes` across mixed key sources (keyed + positional) currently fails
  at eval time, not build time.

---

## 5. Store keys (result sharing)

Separate from equation keys. A **store key** is a content-address over the
equation's resolved inputs + definition. Two equations with the same store
key (same tool, same params, same upstream values) share one stored result.
Forking is cheap because store keys align across fork trees.

Store keys also encode seed lineage so invalidate-and-retry (attempt counter
bump) deterministically produces a new result for stochastic tools.

Source: `backend/flow_runtime/store_key.py`,
`backend/flow_runtime/equation_store.py`.

---

## 6. Lifecycle & runtime

**Equation statuses** (`flow_runtime/graph.py:EquationStatus`):

```
PENDING → COMPUTING → { COMPLETED | FAILED | AWAITING_INPUT | SKIPPED }
```

Plus transient `INVALIDATED` during re-computation.

**Runtime wiring:**

- `FlowRuntime` (`runtime.py`) — one per flow; the public entry point for
  start/pause/resume/invalidate/edit. Wires the in-memory graph to per-flow
  `state.db` and `program.py`.
- `FlowRun` (`engine.py`) — the FRP scheduler. Resolves ready equations,
  expands `foreach` lazily, runs up to `CONCURRENCY_CAP=10`
  evaluations in parallel, routes to evaluators, applies store + HITL-result
  lookup before eval, classifies errors.
- Evaluators — `evaluators.py` (stubs, for dev) and
  `production_evaluators.py` (real tool/LLM/code dispatch).

**Invalidation.** User clicks "regenerate" on an equation: attempt counter
bumps, equation recomputes with a fresh seed, downstream cascades.

**Error classes** — transient, tool, code, LLM, resource. Errors inside
`foreach` are isolated per iteration; errors outside loops block downstream
work.

---

## 7. HITL & tasks

HITL primitives pause evaluation and emit a **task** persisted in the
per-flow `hitl_results` table, keyed by `(equation_key, inputs_hash)`.

Task resolution payloads:

- `select` → resolution is the chosen candidate(s)
- `approve` → resolution is `{accepted: bool}`; reject forces upstream
  re-compute

Errors also surface as tasks with actions: `retry`, `skip` (only inside
`foreach`), `edit_flow`.

**API** (what the code actually exposes):

- `GET /api/flows/:id/tasks` — per-flow list
- `GET /api/tasks` — global; scans every active flow's state.db
- `POST /api/tasks/{flow_id}/{task_id}/resolve` — composite ID in the path.
  WS events emit the task ID as `"{flow_id}:{task_id}"`, split server-side.

---

## 8. Storage model

- **Main DB** (`stimma.db`): `flows` table — metadata, soft-delete, FK to
  project/chat, denormalized `pending_task_count`.
- **Per-flow SQLite** (`<data_dir>/flows/<flow_id>/state.db`):
  - `equations` — current graph: status, definition JSON (with `_dynamic`
    node refs), attempt counter.
  - `hitl_results` — durable human decisions, keyed by
    `(equation_key, inputs_hash)`.
  - `program_history` — `program.py` version snapshots.
- **Equation store** (global, content-addressed):
  `equation_store_entries` table +
  `<data_dir>/equation_store/blobs/<hash_prefix>/<hash>` filesystem blobs.
- **Program source** (`<data_dir>/flows/<flow_id>/program.py`) — the
  editable flow file.

---

## 9. Known gaps (as of 2026-04)

Load-bearing places where current behavior may not match expectations:

1. **Shape validation is partial.** Only dict-subscript existence checking and
   partial tool-input conformance (only when the tool is in the registry) are
   wired in `flow_dsl/shapes.py`. Most shape mismatches still surface at
   runtime.
2. **HITL recovery on function rename is missing.** There is no
   `(task_type, inputs_hash)` fallback in `flow_runtime/graph_diff.py`, so
   renaming a flow function loses HITL approvals on its equations.
3. **`code()` accepts both callable and source-string forms.** Back-compat
   debt; shape inference differs between them.
4. **No `flow_phase_updated` WS event.** Phase state is derived client-side
   from equations.

---

## 10. Undocumented features worth knowing

- **`info()` primitive** — inline markdown cards.
- **`analyze_flow` agent tool** — agent-internal introspection of current
  flow state.
- **`EquationGraph.vue`** — interactive debug graph visualizer
  (`frontend/src/components/flow/`).
- **`CompletedSelectPanel.vue`, `EquationTraceRow.vue`** — polished
  inspection UI.
- **`equations.definition` JSON shape** —
  `{tool_id, n, static_params, _dynamic: {param: NodeRef, ...}}`.
- **Program history** — each save snapshots source; forks copy history.

---

## 11. File map

### Backend

| Path | Purpose |
|---|---|
| `backend/flow_dsl/primitives.py` | All DSL primitives |
| `backend/flow_dsl/loader.py` | Parse + exec `program.py` with error classification |
| `backend/flow_dsl/shapes.py` | Shape types + build-time validation (partial) |
| `backend/flow_dsl/errors.py` | DSL error taxonomy |
| `backend/flow_dsl/versions.py` | Program version store |
| `backend/flow_runtime/graph.py` | `EquationGraph`, `Equation`, `EquationStatus`, `NodeRef` |
| `backend/flow_runtime/graph_builder.py` | DSL → graph construction |
| `backend/flow_runtime/graph_diff.py` | Edit diffing, store-key carry-over |
| `backend/flow_runtime/graph_db.py` | `state.db` persistence |
| `backend/flow_runtime/keys.py` | Equation keys + iteration keys |
| `backend/flow_runtime/store_key.py` | Content-addressed store key derivation |
| `backend/flow_runtime/equation_store.py` | Global result store (inline + blobs) |
| `backend/flow_runtime/engine.py` | FRP scheduler (`FlowRun`) |
| `backend/flow_runtime/runtime.py` | Top-level orchestrator (`FlowRuntime`) |
| `backend/flow_runtime/evaluators.py` | Stub evaluators |
| `backend/flow_runtime/production_evaluators.py` | Real tool/LLM/code evaluators |
| `backend/flow_lifecycle.py` | CRUD, fork, soft-delete, task-count, WS broadcasts |
| `backend/flow_registry.py` | Active runtime registry |
| `backend/flow_service.py` | Service-layer glue |
| `backend/routes/flows.py` | REST API |
| `backend/routes/tasks.py` | Task list / resolve API |
| `backend/agent/v2/flow_prompt.py` | Flow agent system prompt |
| `backend/agent/v2/tools/flow_update.py` | Metadata-edit tool |
| `backend/agent/v2/tools/analyze_flow.py` | Introspection tool (undocumented) |

### Frontend (`frontend/src/`)

| Path | Purpose |
|---|---|
| `views/FlowView.vue` | Main flow workspace |
| `views/FlowsLandingView.vue` | Top-level flows list |
| `views/ProjectFlowsView.vue` | Project-scoped flows tab |
| `components/flow/PhaseTree.vue` | Hierarchical phase / equation renderer |
| `components/flow/TaskCard.vue` | HITL task resolution UI |
| `components/flow/EquationGraph.vue` | Debug graph visualizer |
| `components/flow/EquationTraceRow.vue` | Inspection details |
| `components/flow/CompletedSelectPanel.vue` | Review past selections |
| `composables/useFlowsApi.js` | REST client |
| `composables/useFlowState.js` | Flow + graph state + WS |
