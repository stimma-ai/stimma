# MCP server

Stimma exposes an authenticated, profile-bound MCP endpoint through the existing backend and a local stdio bridge through `stimma mcp`. The server is disabled by default. Enable it and create a connection in the profile’s **Settings → MCP** section.

## Transports and setup

The native endpoint is `/mcp/profiles/{profile_id}`. It implements Streamable HTTP using the official Python MCP SDK. Each request carries `Authorization: Bearer <connection credential>`. Credentials are created through the owner-facing settings API; the server stores their hashes, installation identity and originating profile. MCP requests cannot select another profile through REST headers or query parameters.

The bridge runs on the assistant’s machine:

```sh
stimma mcp install connection.stimma-mcp.json
stimma mcp bridge connection-alias
```

The installer prints an `mcpServers` entry and stores the connection credential in a separate file with mode `0600`. Its argument is a downloaded connection file, not the profile PIN. The bridge requires the Stimma CLI and its Python backend dependencies. It opens authenticated HTTP sessions as needed; transport reconnections do not create new access grants.

The bridge adds `media_upload` and `media_download`. Upload paths and downloaded result paths belong to the assistant’s machine. Native clients can implement the same authenticated HTTP transfer endpoints. A tool-only HTTP client can use workspace operations and inline previews but needs a transfer integration for full files.

## Access and scope

A connection authenticates one configured client on one profile. `workspace_get` and tool discovery work while locked. `access_open` accepts the existing profile PIN; profiles without a PIN can call it without an argument. PIN failures are serialized per profile and temporarily delay further attempts. PIN input and rejected validation values are omitted from MCP logs and error responses.

Unlock grants are in memory, keyed by profile and configured client. They survive a bridge reconnect, expire after the profile’s idle timeout and disappear when the backend restarts. Chats using the same credential share the grant. Job polling does not extend it. An accepted task can finish after idle expiry, but reading its results or extending it requires an unlocked connection.

Explicit locking, disconnecting, disabling MCP and PIN changes revoke external work. Cancellation cannot undo an operation already accepted by a provider. Desktop input into a delegated chat takes control and invalidates stale MCP continuations. References are signed and bind an entity kind, profile and database identity; a numeric identifier from another profile is never a valid substitute.

Profile context also scopes active chat execution identifiers, pending tool permission identifiers and custom-tool catalogs. These are shared runtime components, so their scoping applies to desktop and MCP execution alike.

## Operation surface

Tool schemas are available through `tools/list`. Families use an `action` discriminant and action-specific schemas. `operations.py` explicitly selects existing domain functions and derives their typed inputs, then removes private configuration and filesystem fields and replaces entity IDs with signed references. This is a curated adapter, not arbitrary REST dispatch.

| Surface | Purpose |
| --- | --- |
| `assets_query`, `assets_get`, `assets_facets`, `entities_search` | Browser filtering, inspection, counts and named-entity search |
| `catalog_get`, `assets_select`, `selections_get` | Catalog discovery and stable, paginated selections with exact revision references |
| `lineage_get`, `revisions_list`, `revisions_restore`, `contextual_media_get` | Provenance, saved revisions and contextual media |
| Board, project, saved-view, preset, marker and tag families | Workspace organization through existing domain behavior |
| Container families | Membership, promotion, creation and explosion |
| `tools_search`, `tools_inspect`, `tools_options`, `tools_run` | Provider discovery and exact execution, including batches and sequential chains |
| `agent_start`, `agent_continue` | Creative delegation in an ordinary Stimma chat |
| `flows_get`, `flows_update`, `flows_run`, custom-tool families | Flow inspection/editing, one-shot execution and frozen tool management |
| `content_update` | Saved raster transforms and SVG, Markdown or layout documents, with revision conflict guards |
| `jobs_get`, `jobs_cancel`, `jobs_retry`, `interaction_respond` | Progress, cancellation, known-failure retries and exact-question responses |
| `media_read`, `media_export` | Bounded previews and private original/bundle delivery |
| `ui_context_get`, `ui_open` | Explicitly shared selection snapshots and UI route handoff |
| `assets_delete_permanently`, `share_publish` | Explicit irreversible deletion and public sharing |

`tools_run` calls the same SDK dispatch and permission gate used by the agent, without an LLM planning turn. Media inputs and schema versions are checked before acceptance. Batches retain per-item results. Chains can bind the previous saved media output to a declared media input. The server does not infer an output binding from an arbitrary parameter name.

`agent_start` records the brief, reference roles, selected skills and deliverables in a normal chat. It reuses the existing agent, project context, model resolution and permissions. Permission questions are relayed to the connected assistant, which is trusted to obtain the human’s answer. Responses apply once and cannot change persistent permission policy through MCP arguments.

`flows_run` uses the existing one-shot Flow runner with its runtime safeguards. Human selection callbacks wait for an explicit response instead of automatically choosing a candidate. This endpoint executes a separate run; it does not take over a Flow already running in the editor.

There is no separate MCP budget, cumulative spend allocation or renewal protocol. Existing agent/runtime safeguards, tool permissions and cancellation remain in effect.

## Receipts and recovery

`mcp_operations` stores durable task acceptance, mutation receipts and selection snapshots. Synchronous database mutations use a transaction that commits the change and its receipt together. Request identity includes the configured client, operation and request key. Reusing a key with changed input returns `request_key_conflict`.

Long-running or filesystem-affecting operations return a durable job before execution. Retrying acceptance retrieves that job rather than launching it again. The job links its ordinary chat, controller version, visible events and retained result manifest. Follow-ups and question responses require the current controller version and their own retry key.

Work whose backend execution disappears is marked interrupted when recovered. Unknown provider outcomes are retained and excluded from automatic retries. A batch retry selects only explicitly failed items; it preserves successful outputs. No operation receipt is a promise that an external provider supports transactional rollback or exactly-once billing.

Stable selection snapshots expire after 24 hours and record Asset, revision and Media references. Desktop context snapshots are separate: the user chooses **Share selection with connected assistants** from the media context menu, and the snapshot expires after ten minutes. Ordinary desktop selection changes do not expose ambient UI state.

## Transfers

Uploads enter the existing upload and Asset services and never select a server destination directory. Download handles bind the connection and current unlock grant, expire after fifteen minutes and stop working after relocking. Directory media is delivered as a complete ZIP bundle, with symlinks rejected. Downloads support byte ranges and include a SHA-256 checksum that the bridge verifies before completing its local file.

Inline image previews are bounded to 1024 pixels on the longest edge. Small SVG, Markdown, text and JSON documents can be returned as text. Other formats use original-file delivery. `ui_open` returns a relative route and profile ID; host integrations must honor both and decide how to navigate.

## Validation

Run from the repository root:

```sh
tools/stimma lint backend
tools/stimma test backend
tools/stimma test acceptance
```

`backend/tests/test_mcp_server.py` covers native MCP discovery, real stdio bridge upload/download, credential and profile boundaries, idle expiry, PIN redaction, atomic retries, interrupted jobs, saved-edit conflicts, stable selections, direct batch recovery, Flow execution and desktop takeover. The acceptance lane exercises the existing application with fake providers in an isolated sandbox.
