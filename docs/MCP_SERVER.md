# MCP server

Stimma exposes an authenticated, profile-bound MCP endpoint (Streamable HTTP) through the existing backend. The server is disabled by default. Enable it and create a connection in the profile’s **Settings → MCP** section. Settings provides the server URL and a one-time connection key per named connection, and shows when each connection was created and last used. Assistant-specific setup instructions live in the [MCP setup guide](https://docs.stimma.ai/mcp/).

## Transports and setup

The native endpoint is `/mcp/profiles/{profile_id}`. It implements Streamable HTTP using the official Python MCP SDK. Each request carries `Authorization: Bearer <connection credential>`.

The server URL that Settings shows is on the computer running the Stimma app: the desktop shell's loopback proxy, which forwards to whichever install the window is on. The backend itself listens on loopback only, and its LAN-facing multi-device listener sits behind a TLS device gate, so an assistant cannot reach a remote Stimma Server directly. Instead the app is the relay: the proxy carries the device session in `X-Stimma-Device-Session` and passes the assistant's own `Authorization` header through untouched, so the same URL works whether the window is on the local install or a remote server, as long as Stimma is open and connected. The settings API returns `path` (the profile-bound route the app joins to its own origin) and `endpoint` (the backend's own loopback address, for development on the same machine). Credentials are created through the owner-facing settings API; the server stores their hashes, installation identity and originating profile. MCP requests cannot select another profile through REST headers or query parameters.

Assistants connect with the server URL and key directly; there is no local helper to install. Media leaves the server through download links (see Transfers).

## Access and scope

A connection authenticates one configured client on one profile. A profile without a PIN is open as soon as the credential is accepted: there is no unlock step, and `access_open` is a no-op there. A profile with a PIN starts locked; `workspace_get` and tool discovery still work, and `access_open` takes the existing profile PIN. PIN failures are serialized per profile and temporarily delay further attempts. PIN input and rejected validation values are omitted from MCP logs and error responses.

Unlock grants are in memory, keyed by profile and configured client. They survive a client reconnect and disappear when the backend restarts. On a PIN-protected profile they also expire after the profile’s idle timeout; a profile without a PIN is simply granted again on the next call. Chats using the same credential share the grant. Job polling does not extend it. An accepted task can finish after idle expiry, but reading its results or extending it requires an unlocked connection.

Explicit locking, disconnecting, disabling MCP and PIN changes revoke external work. Cancellation cannot undo an operation already accepted by a provider. Desktop input into a delegated chat takes control and invalidates stale MCP continuations. References are signed and bind an entity kind, profile and database identity; a numeric identifier from another profile is never a valid substitute.

Profile context also scopes active chat execution identifiers, pending tool permission identifiers and custom-tool catalogs. These are shared runtime components, so their scoping applies to desktop and MCP execution alike.

## Operation surface

Tool schemas are available through `tools/list`. Families use an `action` discriminant and one flat object per action: the route's body model is inlined, every field that carries an entity reference is named `*_ref` or `*_refs` on input and output alike, and Pydantic titles and internal names are stripped. `operations.py` explicitly selects existing domain functions and derives their typed inputs, then removes private configuration and filesystem fields and replaces entity IDs with signed references. This is a curated adapter, not arbitrary REST dispatch.

The surface below is deliberately small: an external agent that makes assets with Stimma and keeps the library organized. It is a client of the library and the generation tools, not a remote control for the app.

| Surface | Purpose |
| --- | --- |
| `workspace_get`, `access_open`, `access_lock` | Bound profile, PIN unlock when the profile has one |
| `tools_search`, `tools_inspect`, `tools_options`, `tools_run` | Find and run generation tools, including batches and chains |
| `jobs_get`, `jobs_cancel`, `jobs_retry`, `interaction_respond` | Progress, cancellation, retries and answering permission or choice questions |
| `agent_start`, `agent_continue` | Delegate creative work to Stimma's agent in a chat the connection created; such chats are tagged and shown as MCP-driven in the app |
| `assets_query`, `assets_get`, `lineage_get`, `media_read`, `media_export` | Search, details with download links, provenance, inline previews, downloads |
| `assets_update` | trash, restore, markers, tags, clear_expiration, add_to_project, remove_from_project |
| `content_update` | Save an external file, transformed image or document as an asset or revision with lineage |
| `catalog_get`, `projects_get`, `projects_update`, `boards_get`, `boards_update` | Markers, tags and sources; projects (create, update); boards with sections (create, update, trash, restore, section_create, section_update, section_delete, section_reorder, add, remove, move) |
| `chats_get`, `chats_update` | List, read metadata, rename and trash chats. No chat contents, no messages into chats |

Deliberately not offered: Flow control, custom-tool authoring, arbitrary chat contents and forking, saved-view editing, presets, container editing, contextual media, entity search, stable selections, facets, permanent deletion, revision browsing/restoration, public sharing and shared-selection snapshots. Those are inside-Stimma activities. Existing permitted tools remain discoverable, including installed user tools; `catalog_get` can list saved views.

`tools_run` calls the same SDK dispatch and permission gate used by the agent, without an LLM planning turn. For MCP-driven chats the gate treats a tool's "ask" default as allow: the connection key is the consent, and the assistant would only approve its own question. Explicit denies in tool permissions still block. Media inputs and schema versions are checked before acceptance. Batches retain per-item results. Chains can bind the previous saved media output to a declared media input. The server does not infer an output binding from an arbitrary parameter name.

`agent_start` records the brief, reference roles, selected skills and deliverables in a normal chat. It reuses the existing agent, project context, model resolution and permissions. Permission questions are relayed to the connected assistant, which is trusted to obtain the human’s answer. Responses apply once and cannot change persistent permission policy through MCP arguments.

Choose `tools_run` for a known operation and parameters; choose `agent_start` when Stimma should select tools and creatively iterate. The external assistant can supply business context from other connected systems in its brief.

For library discovery, scope to a known project or inspect a board first. `similar_to_text` searches visual appearance, `caption_query` matches captions and `prompt_query` matches generation instructions. Tags, markers and board sections can record explicit approval; visual similarity and recency cannot establish approval. Use `media_read` to inspect a shortlist.

There is no separate MCP budget, cumulative spend allocation or renewal protocol. Existing agent/runtime safeguards, tool permissions and cancellation remain in effect.

## Receipts and recovery

`mcp_operations` stores durable task acceptance and mutation receipts. Synchronous database mutations use a transaction that commits the change and its receipt together. Request identity includes the configured client, operation and request key. Reusing a key with changed input returns `request_key_conflict`.

Long-running or filesystem-affecting operations return a durable job before execution. Retrying acceptance retrieves that job rather than launching it again. The job links its ordinary chat, controller version, visible events and retained result manifest. Follow-ups and question responses require the current controller version and their own retry key.

Work whose backend execution disappears is marked interrupted when recovered. Unknown provider outcomes are retained and excluded from automatic retries. A batch retry selects only explicitly failed items; it preserves successful outputs. No operation receipt is a promise that an external provider supports transactional rollback or exactly-once billing.

`tools_run` accepts optional `batch_labels`, one string per item in `batch`. Every attempted item echoes its label on success or failure. Labels are bookkeeping and never provider parameters. A retry runs only confirmed failures, echoes their labels and `original_index`, and links to the original receipt through `retry_of`; successful original outputs stay in the original job. `index` is local to each job's batch.

Delegated results contain `outputs` (exact Asset, revision and Media refs explicitly shown as final), `summary` (the agent's closing message, including reported limitations), and `shortfalls` (reported errors and a missing-output-count notice when applicable). Intermediate displays are excluded. A later final revision of the same asset supersedes its earlier final display within the turn. A follow-up starts a new result for that turn. These receipts report work; they do not verify creative quality or approve deliverables. `succeeded` means execution ended.

Poll `jobs_get` with `after` set to the previous `next_cursor` for incremental events. Stop polling at `succeeded`, `failed`, `cancelled`, `interrupted` or `control_changed`; respond to `input_required` using `interaction_respond`.

## Transfers

`workspace_get` returns an `upload_url`, a signed link bound to the connection. POST the file body with an `X-Filename` header. A normal upload creates an asset immediately. For external edits or composites, add `X-Stimma-Stage: true`: the upload is retained provisionally, returns a `media_ref`, and creates no intermediate library asset.

Save that upload using `content_update` with `format: "file"` and `source_ref` for its bytes. `source_refs` independently identifies the library inputs used to make it, in source order; omitting this field uses `source_ref` as the provenance source. Supply a `note` describing the edit. Add `target_asset_ref` and `expected_current_revision` to publish a revision, or omit them to create an asset. Successful saves release provisional upload ownership. Conflicting revisions leave the upload available for recovery. Files retain their stored bytes, format and media metadata; SVG uploads retain the app's standard sanitization. `format: "image"` applies explicit transforms and records the exact transform list in provenance; an empty list also preserves bytes.

Uploads enter the existing upload and Asset services and never select a server destination directory. Downloads are plain `GET` links: asset details and media objects carry `download_url`, and `media_export` returns one on demand from any result's `media_ref`. The link is bound to the connection and its current unlock grant, expires after four hours (also shown as a UTC `expires` query parameter) and stops working after relocking. No key or headers are needed. Download files into the external project before integrating them: these links are temporary transfers, not permanent hosting URLs. Links use the desktop relay's origin. Directory media is delivered as a complete ZIP bundle, with symlinks rejected. Downloads support byte ranges and include a SHA-256 checksum header.

Inline image previews are bounded to 1024 pixels on the longest edge. Small SVG, Markdown, text and JSON documents can be returned as text. Other formats use original-file delivery.

## Validation

Run from the repository root:

```sh
tools/stimma lint backend
tools/stimma test backend
tools/stimma test acceptance
```

`backend/tests/test_mcp_server.py` covers native MCP discovery, staged uploads and downloads, credential and profile boundaries, idle expiry, PIN redaction, atomic retries, interrupted jobs, external-edit lineage, saved-edit conflicts, labeled batch recovery, delegated output receipts and desktop takeover. The acceptance lane exercises the existing application with fake providers in an isolated sandbox.
