# Telemetry Event Catalog

This is the living catalog of every telemetry event the Stimma app can
send, the rules all events must follow, and the classification helpers
that keep user content out of the dataset. It is the single reference for
instrumentation work; the user-facing summary lives on the docs site.

Status column: **live** = instrumented today · **planned** = specified
here, not yet instrumented. Property shapes below are the catalog
contract; live events are migrated to these shapes as instrumentation
lands.

## Posture

- **Official builds only.** The telemetry client is a permanent no-op
  unless `STIMMA_DISTRIBUTION == official` (set only by release CI).
  Source/self-built installs emit none of these events — not opted out,
  *not present*. See `backend/distribution.py` and `backend/telemetry.py`.
- **Consent-gated.** Events are sent only after the user consents
  (onboarding toggle / Settings → Usage Analytics). While consent is
  undetermined (onboarding in progress) events buffer locally with zero
  network; the buffer flushes if consent lands on and is discarded if it
  lands off. Nothing egresses before an affirmative state.
- **`DO_NOT_TRACK=1` means "don't phone home", full stop.** It kills all
  telemetry buffering/sending regardless of consent, and also suppresses
  the feature-flags fetch (local defaults only), the update check, and
  the compliance/region call. Explicit user-initiated acts (cloud
  sign-in/API, submitting feedback) still work.
- **Carve-out:** the single `telemetry_enabled {enabled: false}`
  transition event fired by the toggle-off itself is the last thing sent.

## Testing official-build behavior (dev)

To exercise the official-build surfaces (telemetry client, consent
screen, thumbs feedback, crash reports) from a source checkout, pass
`--official` to the dev/run CLI commands:

```
stimma dev backend --official     # backend telemetry/crash surfaces active
stimma dev frontend --official    # consent UI / thumbs compiled in (Vite define)
stimma dev app --official         # Tauri shell + its Vite dev server
stimma run backend|frontend|app --official
```

The flag sets `STIMMA_DISTRIBUTION=official` in the child process only;
without it nothing changes (dev default, permanent no-op). The CLI
prints a warning banner when active because events really are sent to
the configured cloud (after consent). On the default debug channel the
User-Agent still reports `app_branch=dev` (branch derives from the
bundle id; non-release bundles fall back to `dev`), so test events are
filterable server-side. Note `dev app`/`run app` talk to the externally
running backend on :9191 — start that backend with `--official` too if
you want the backend surfaces live.

### Fresh first-run sandbox (onboarding / consent flows)

To exercise onboarding from a true first-run state (config auto-init,
consent undetermined, no feedback coachmark, no cached compliance
region) without touching your default sandbox, create an **empty**
sandbox and run both servers against it with `--official`:

```
stimma fork create consent-test --empty
stimma --sandbox=consent-test dev backend --official
stimma --sandbox=consent-test dev frontend --official
```

`fork create --empty` makes a data dir that contains only a `.fork.json`
with auto-assigned ports (server/frontend pairs from 9300 up, so your
default :9191/:9192 servers are untouched). On first boot the backend
initializes `config.yaml` with `telemetry.enabled` unset (tri-state
null = consent undetermined), a fresh profile/database, and no
onboarding state — `GET /api/settings` reports
`telemetry_enabled: null` and `distribution: "official"`. `dev
frontend` picks up the sandbox's ports automatically (Vite serves on
the fork's frontend port and proxies to its backend port).

To re-test the flow from scratch, destroy and recreate the sandbox:

```
stimma fork destroy consent-test --yes
stimma fork create consent-test --empty
```

(`--yes` skips the destroy confirmation for scripted use.)

## Rules (enforced at audit)

No PII, no prompts, no file names/paths, no generation parameters, no
image data, no conversation content. camelCase properties; counts over
enumerations; durations in ms; error info categorical only. Property
enums are **closed lists of mechanical UI verbs/states** — never semantic
categories derived from user content. The server accepts any
event/category (this catalog defines shapes); there are no per-property
validation micro-limits, only abuse caps (≤1 MB body, ≤200 events/batch,
event/category name ≤128 chars), so catalog evolution needs no server
change. Renames, duplicates, undo-restores, and purge-vs-trash
distinctions are deliberately untracked (mutation counts suffice;
forks/clones surface as the corresponding `*_created`).

## Envelope

Identity/platform (install ID, version, branch, os, arch) ride the
**User-Agent** (`backend/user_agent.py`) — never the payload:

```
User-Agent: Stimma/<version> (<os>; <arch>; <branch>) install/<install_id>
```

The User-Agent is the **only** place the install ID ever leaves the
machine, on requests to Stimma's own infrastructure only (telemetry,
compliance/region, feature flags, app/version, cloud API).

Body: `POST {cloud}/api/telemetry`

```json
{
  "sessionId": "<uuid>",
  "userId": "<firebase uid, only when signed in>",
  "events": [
    { "event": "...", "category": "...", "properties": { }, "timestamp": 1730000000000 }
  ]
}
```

`timestamp` is client occurrence time (epoch ms) — batches can flush up
to 60 s late, at shutdown, or after retries, so server receive time is
not occurrence time. The server adds country from the request edge; IP is
never stored. Session IDs are plain random UUIDs owned by the frontend,
rotated on app start and after 30 minutes of inactivity.

Client mechanics: flush every 60 s / 50 events / on shutdown, ≤200 events
per batch, 3 retries with backoff, fire-and-forget.

## Where cloud usage is measured (NOT here)

Stimma Cloud usage is authoritative **server-side**: every cloud LLM/tool
call terminates in the cloud with auth context, and the cloud writes a
usage row per call (user, kind, tool, task type, model, status,
duration). Client `tool_*` events keep `mode: cloud` purely as a funnel
join key — cloud usage dashboards read the server table, which counts
every build (including source builds) and is not consent-gated
(operating the service, disclosed).

## Pseudonymization & classification helpers

All live in the backend; only their outputs ever egress.

- **Salted object hashes** (`backend/object_hash.py`) —
  sha256(install-local random salt ‖ object id); the salt is generated
  once per install, stored in config, never transmitted. Irreversible,
  stable within an install (enables per-object funnels), meaningless
  across installs. Used for `projectHash`, `flowHash`, `boardHash`,
  `chatHash`, `presetHash`, `chainHash`, and user-provider `toolRef`s.
  Deliberately NOT used for media items (per-asset rows would be a
  per-creation activity trace; counts suffice), saved views (no reuse
  event to join), or profiles (trivially low cardinality).
- **`actor: user | agent | system`** — who initiated a library mutation
  (direct UI, agent tool call, or background process).
- **Model munger** (`backend/model_family.py`) — single source of truth
  mapping any model string (API id, checkpoint filename, `.gguf` path,
  STP-declared model) → `modelFamily`. An ordered, first-match-wins list
  of case-insensitive regex → family rules over the normalized basename
  (path, extension, quant suffixes stripped). **Granularity = model
  version line, not manufacturer**: `flux-1-dev`, `flux-1-schnell`,
  `flux-1.1-pro`, `flux-kontext` are four families. Quant/precision/
  fine-tune variants collapse into the line. No match → `other`; no model
  string → `unknown`. The raw string never leaves the machine. The rules
  table is a normal catalog asset (hardcoded today, feature-flag
  deliverable later — privacy holds as long as rules are never
  user-configurable). CI fixture tests in
  `backend/tests/test_model_family.py`.
- **Tool references** (`backend/tool_ref.py`) — `toolRef` +
  `toolSource: builtin | marketplace | cloud | user`. For
  builtin/marketplace/cloud tools `toolRef` is the toolId verbatim
  (catalog data). For user-provider tools `toolRef` is the salted hash:
  STP tool slugs are user-chosen strings (e.g. ComfyUI workflow node
  names), so raw toolIds are content. `taskType` is protocol-level
  mechanical and stays in clear for every tool.
- **Run correlation** — `runId`: an ephemeral random UUID minted
  client-side per user-initiated generation pipeline, carried by that
  pipeline's `tool_used/completed/failed/cancelled` events and its
  `generation_pipeline_completed` row. Random and content-free; not
  persisted to any library entity. `isRetry: bool` rides the pipeline
  event when launched from a retry affordance.
- **Refusal classification** (`backend/refusal_detection.py`) — one
  shared classifier detecting textual model refusals, applied to all
  agent surfaces (chat main/flow/delegate + prompt agent). Output is
  the single categorical label `refusal` in the agent `errorType` enums;
  the matched text never egresses. `refusal` (textual decline detected
  client-side) and `content_filtered` (provider-side filter signal) are
  distinct members — different causes, different fixes.
- **Provider identity** (`backend/stp_identity.py`) — provider names and
  provider-reported display names are user content and never egress.
  Instead: `providerType` (closed connection-kind enum) plus
  `productName`/`productVersion` validated out of the STP registration's
  `server` field (`Name/Version`, set by the provider software, not the
  user). Known product patterns pass; everything else is `other`; the
  version must be version-shaped (dotted digits + optional `-suffix`) or
  it is dropped; missing/unparseable → `unknown`.
- **endpointClass** (`backend/endpoint_class.py`) — BYOAI endpoint URLs
  classify into `openai | anthropic | openrouter | other_known |
  localhost | lan | custom`. Hostnames/ports never egress (LAN names are
  private).

### Rule fixes baked into the current shapes

1. Raw provider error text → categorical `errorType` + `errorHash` (sha1
   of normalized message — groupable without content).
2. Endpoint domain/port → `endpointClass`.
3. Screen tracking sends route **names** only, never paths (paths embed
   entity ids like `/boards/<id>`).
4. Built-in marker names pass through; custom markers send the literal
   placeholder `custom`.
5. User-provider toolIds → `toolRef`/`toolSource`.
6. Provider labels/reported names → `providerType` + `productName`/
   `productVersion`.
7. Raw model strings → `modelFamily`.
8. `app_error` carries no request path.

## App lifecycle (`app`)

| Event | Status | Properties |
|---|---|---|
| `app_launched` | live | `{ previousExitClean: bool }` — dirty-flag file written at startup, cleared on orderly shutdown; `false` on next launch = the prior session died hard. Categorical, content-free |
| `app_updated` | live | `{ fromVersion }` (new version rides the UA) |
| `session_started` | live | **The per-launch state snapshot**: `{ providerCount, providers[]{providerType,toolCount,connected,productName?,productVersion?}, toolCountsBySource{builtin,marketplace,cloud,user}, llmConfig{role→{source: auto\|stimma_cloud\|endpoint, endpointClass, modelFamily}}, mediaCountsByType{image,video,audio,document,set,grid,layout}, chatCount, boardCount, flowCount, projectCount, savedViewCount, profileCount, markerCounts{favorite,library,custom}, stimpackCounts{marketplace,dev,builtin} }` — counts only, no names/content. `llmConfig` role keys are the app-defined closed role set; `source` is the *configured* value, distinct from per-event *resolved* `llmSource`. `markerCounts` keys are a literal match against the shipped default marker set (anything else, including renamed defaults, counts under `custom`). `providers[]` is the one sanctioned enumeration under the counts-over-enumerations rule (bounded by configured connections; mechanical fields only) |
| `session_ended` | live | `{ durationMs }` — fired at shutdown **and** on the 30-min-inactivity session rotation. Dead-session recovery: when `previousExitClean: false`, the next launch flushes a buffered `session_ended{durationMs}` for the dead session from its last persisted activity timestamp |
| `app_error` | live | `{ source: backend\|frontend, errorType, stackHash, module? }` — exception type, stack hash, and top app-frame module only; no messages, paths, or locals (those can contain prompts/paths). Counting only |
| `onboarding_completed` | live | `{}` — activation-funnel endpoint (`first_run` → `screen_viewed: onboarding` → this); all three buffer pre-consent and flush together on consent-on |
| `first_run` | live | `{}` — fired client-side once on first launch, buffered through onboarding per the pre-consent rule. Authoritative install counting is server-side (`installs.first_seen_at`, upserted by every endpoint) — this event is the funnel-side marker, not the count |

## Updates (`app`)

| Event | Status | Properties |
|---|---|---|
| `update_checked` | live | `{ trigger: manual\|auto }` |
| `update_available` | live | `{ version }` |
| `update_installed` | live | `{ version }` |

The backend's daily `GET /api/app/version` covers server-side *check*
counting; these are the update-adoption funnel. Official builds only by
construction (the updater is official-gated).

## Navigation (`navigation`)

| Event | Status | Properties |
|---|---|---|
| `screen_viewed` | live | `{ screen }` — values pinned to the live router: `onboarding, home, browse, trash, upload, boards, board-detail, projects, project-overview, project-assets, project-chats, project-boards, project-flows, project-settings, project-tools, chats, chat, flows, flow, saved-view, all-tools, edit-image, edit-image-landing, edit-image-empty, lineage, tool`. The stimpacks/marketplace surface lives inside the settings modal today (no route); if it becomes a route, `stimpacks` joins the list. Dev-only routes (`dev-*`) excluded. No path property, ever |

## Account (`account`)

| Event | Status | Properties |
|---|---|---|
| `cloud_signed_in` | live | `{ tier }` |
| `cloud_signed_out` | live | `{}` |
| `gate_encountered` | live | `{ gate: signin_required\|tier_required\|quota_exhausted, surface: tool\|agent\|stimpack\|share }` — fired when the user hits a cloud gate. Outcome is derived by sequence (next `cloud_signed_in` / mode switch / abandon within session), not a semantic outcome property. Live surfaces today: `agent` (quota/tier/sign-in errors from the agent path) and `share` (share status checked signed-out); `tool`/`stimpack` gate UIs don't exist yet and emit nothing until they do |

## Generation & tools (`generation`)

| Event | Status | Properties |
|---|---|---|
| `tool_used` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode: cloud\|byoai\|local, providerType?, controlnet? }` |
| `tool_completed` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, durationMs, queueMs, computeMs, providerType? }` — `durationMs` = end-to-end (submit→result, includes queue wait), `queueMs` = time queued, `computeMs` = pure provider compute |
| `tool_failed` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, errorType, errorHash, providerType? }` — `errorType` closed list (pinned): `timeout \| cancelled \| out_of_memory \| connection_error \| provider_disconnected \| provider_error` |
| `tool_cancelled` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, durationMs, providerType? }` — `durationMs` = elapsed-at-cancel (cancellation latency is the best per-job frustration signal) |
| `batch_submitted` | live | `{ toolRef, jobCount, expandedFromSets: bool }` |
| `forever_mode_used` | live | `{ toolRef, action: started\|stopped }` |
| `controlnet_preview_used` | live | `{}` |
| `config_from_media_used` | live | `{}` |
| `auto_delete_configured` | live | `{ enabled, durationMinutes? }` |
| `tool_provider_added` | live | `{ providerType }` — user label never sent |
| `tool_provider_removed` | live | `{}` |
| `provider_connection_changed` | live | `{ providerType, productName?, state: connected\|disconnected, inFlightJobs }` — mid-session connection transitions; `inFlightJobs` = jobs orphaned by a disconnect. `providerType` domain (pinned, everywhere it appears): `builtin \| stdio \| websocket` — connection kinds, matching `tool_provider_added.providerType` |
| `tool_provider_tested` | live | `{ success, providerType, productName?, productVersion? }` — product identity validated from the STP `server` field, never the free-string provider-reported version |
| `tool_preset_saved` / `tool_preset_applied` | live | `{ toolRef, presetHash }` |
| `preset_reverted` | live | `{ toolRef, presetHash }` |
| `tool_preset_deleted` | live | `{ toolRef, presetHash }` |
| `params_reset` | live | `{ toolRef }` |
| `tool_hop_used` | live | `{ fromToolRef, toToolRef }` |
| `generation_pipeline_completed` | live | `{ runId, isRetry: bool, toolRef, toolSource, taskType, modelFamily, mode, source: toolview\|agent\|flow\|forever, status: completed\|failed\|cancelled, durationMs, queueMs, genDurationMs, postprocessDurationMs, postprocessStepCount, postprocessToolRefs[], presetHash?, failedStepIndex?, errorType? }` — one event per user-initiated generation, emitted when the whole pipeline settles (generation + its post-processing chain). `durationMs` is wall-clock click→final asset; `postprocessToolRefs` is the ordered step list as a JSON array, each entry verbatim-or-hashed per the toolRef rule. `presetHash?` present when launched from a preset |

`modelFamily` × `taskType` is the headline product question and both
fields are classification outputs / protocol mechanics — they stay in
clear for every tool, including user-provider ones whose names we never
see.

## ToolView prompt agent (`prompt_agent`)

| Event | Status | Properties |
|---|---|---|
| `prompt_agent_step` | live | `{ llmSource: stimma_cloud\|endpoint\|unknown, modelFamily, endpointClass?, durationMs, status: completed\|failed\|timeout, errorType? }` — one agent request/response cycle. `errorType` domain = the shared agent error list incl. `refusal`; `endpointClass?` present when `llmSource: endpoint` |
| `prompt_agent_action` | live | `{ action }` — **UI clicks only**, closed enum pinned to the live controls: `send \| select_suggestion \| select_option \| surprise \| wildcard \| refresh_category \| refresh_suggestions \| undo \| redo`. Never semantic suggestion categories (those derive from prompt content) |

## Chat & agent (`chat`)

| Event | Status | Properties |
|---|---|---|
| `chat_created` | live | `{ chatHash, projectHash? }` |
| `chat_message_sent` | live | `{ chatHash, hasAttachments, hasSelectedMedia, messageCount }` |
| `agent_chat_sent` | live | `{ chatHash, llmSource: stimma_cloud\|endpoint\|unknown }` |
| `agent_turn_completed` | live | `{ chatHash, llmSource, modelFamily, endpointClass?, durationMs, toolCallCount, status: completed\|failed\|cancelled\|quota_exceeded\|paused_for_permission, errorType?, agentContext: main\|flow\|delegate }` — `errorType?` set when `failed`, domain = the shared closed agent error list (pinned): `quota_exceeded \| content_filtered \| subscription_required \| llm_not_configured \| refusal \| timeout \| other`. A turn whose final visible content the shared classifier flags as a textual refusal reports `status: failed, errorType: refusal` |
| `agent_error` | live | `{ errorType, chatHash?, agentContext }` — `errorType` is the same shared closed list (`quota_exceeded`, `content_filtered`, `subscription_required`, `llm_not_configured`, `refusal`, …); unknown errors map to `other`, never raw exception class names |
| `chat_deleted` | live | `{ chatHash }` |
| `stimpack_invoked` | live | `{ chatHash, stimpackSource: marketplace\|dev\|builtin, stimpackName? }` — `stimpackName` passes **only when `stimpackSource: marketplace`** (catalog data); dev/user stimpack names are user content and never pass. `dev` covers both the dev_stimpacks_dir override and user/agent-authored stimpacks |

`chatHash` turns conversation depth/retention into a measurable funnel —
still zero content.

## Flows (`flow`)

All flow events carry `flowHash` (install-salted, irreversible).

| Event | Status | Properties |
|---|---|---|
| `flow_created` | live | `{ flowHash, projectHash?, forked: bool }` |
| `flow_deleted` | live | `{ flowHash }` |
| `flow_started` | live | `{ flowHash, dryRun: bool }` |
| `flow_paused` / `flow_resumed` / `flow_cleared` | live | `{ flowHash }` |
| `flow_completed` | live | `{ flowHash, durationMs, taskCount, llmCallCount, toolCallCount }` — the runtime is a reactive scheduler with no single terminal transition, so "completed" = the root status summary settling to all-done for a run started this process |
| `flow_failed` | live | `{ flowHash, errorType, errorHash, stepKind }` — `stepKind` = the node type that killed the run, domain = the runtime's closed `EquationType` enum (pinned): `tool_call, llm_call, llm_batch, llm_slot, code, hitl, control, flow_input, info, create_set, create_grid, create_document, create_image, create_layout, rasterize_layout, web_search, fetch_media` — distinct from both the HITL `taskKind` list and the tool `taskType` list. Fired once per started run, on the first equation failure |
| `flow_task_resolved` | live | `{ flowHash, taskKind, waitDurationMs }` — HITL responses; `taskKind` = the runtime's closed HITL kind enum (pinned: `select \| approve`); `waitDurationMs` = task-raised→resolved from the durable task row |

## Post-processing chains (`postprocess`)

| Event | Status | Properties |
|---|---|---|
| `chain_saved` | planned | `{ chainHash, stepCount, stepTypes[] }` — `stepTypes` = ordered values from the closed `taskType` enum incl. `filter` (never tool ids or step names). **No emission point yet**: chains have no saved-entity/save action today (they ride tool state and presets), so there is no chain id to hash — lands with the chain-library feature |
| `chain_executed` | live | `{ stepCount, status: completed\|failed\|cancelled, durationMs }` — `chainHash?` joins when saved chains exist (every run is ad-hoc today, so it is always omitted) |
| `chain_step_failed` | live | `{ stepType, errorType }` — `stepType` = the step's `taskType` (in-app filter steps are `filter`) — never a tool id or step name |
| `chain_retried` / `chain_run_dismissed` | live | `{}` |

## Boards (`organize`)

All board events carry `boardHash` (install-salted, irreversible).

| Event | Status | Properties |
|---|---|---|
| `board_created` | live | `{ boardHash, projectHash? }` |
| `board_deleted` | live | `{ boardHash }` |
| `board_items_added` / `board_items_removed` | live | `{ boardHash, count }` |
| `board_items_moved` | live | `{ boardHash, count }` — moved between sections |
| `board_section_added` / `board_section_removed` | live | `{ boardHash }` |
| `board_sections_reordered` | live | `{ boardHash }` |

## Library (`library`)

| Event | Status | Properties |
|---|---|---|
| `media_uploaded` | live | `{ fileCount }` |
| `media_imported` | live | `{}` — fired at the rescan trigger; the import runs asynchronously, so no count is available at the emission point (count lands when import-completion gets a seam) |
| `media_deleted` / `media_restored` | live | `{ count }` |
| `media_exported` | live | `{ count }` |
| `search_used` | live | `{ queryType, hasResults }` — both mechanical. No query text, now or ever |
| `similarity_search_used` | live | `{}` |
| `filter_applied` | live | `{ filterFlags }` — closed mechanical flag object |
| `set_created` / `grid_created` | live | `{ count, actor }` / `{ cellCount, actor }` |
| `set_exploded` / `grid_exploded` | live | `{ count, actor }` / `{ cellCount, actor }` |

## Organization & settings (`organize` / `settings`)

| Event | Status | Properties |
|---|---|---|
| `media_tagged` | live | `{ added, removed }` |
| `media_marked` | live | `{ count, markerName }` — names matching the shipped default set (today `favorite`/`library`) pass through literally; everything else, including renamed defaults, → `markerName: "custom"` |
| `saved_view_created` | live | `{}` |
| `saved_view_deleted` | live | `{}` |
| `project_created` / `project_deleted` | live | `{ projectHash }` |
| `profile_created` | live | `{}` |
| `profile_deleted` | live | `{}` |
| `profile_switched` | live | `{}` |
| `profile_pin_set` / `profile_pin_removed` | live | `{}` |
| `profile_locked` / `profile_unlocked` | live | `{}` (PIN lock usage; never the PIN) |
| `folder_added` / `folder_removed` | live | `{ count }` (no paths) |
| `theme_changed` | live | `{ theme }` |
| `telemetry_enabled` | live | `{ enabled }` — fired on toggle change; the final `false` event is the last thing sent (the documented CI carve-out) |

## Stimpacks (`stimpacks`)

| Event | Status | Properties |
|---|---|---|
| `stimpack_marketplace_installed` | live | `{ stimpackName }` (marketplace names are catalog data, not user content) |
| `stimpacks_auto_installed` | live | `{ count, stimpacks[] }` — auto-installed stimpacks are stock/marketplace, so names are catalog data |
| `stimpack_updated` | live | `{ stimpackSource, stimpackName? }` — the editor fires this for user-authored stimpacks too, so the name passes only when `stimpackSource: marketplace` |
| `stimpack_uninstalled` | live | `{ stimpackSource, stimpackName? }` — same marketplace-only name rule |
| `dev_stimpacks_enabled` | live | `{ stimpackCount }` — fired on the configuration transition, not per-launch; count only |

## Shares (`share`)

| Event | Status | Properties |
|---|---|---|
| `media_shared_to_cloud` | live | `{ count }` (moderation outcomes live server-side, not in client telemetry) |

## Voice (`feature`)

| Event | Status | Properties |
|---|---|---|
| `voice_model_downloaded` | live | `{ model }` (closed list — the shipped whisper models) |
| `voice_input_used` | live | `{ surface: main_chat\|flow_chat\|prompt_agent\|feedback, durationMs, outcome: committed\|cancelled }` (no transcript) |

## UI features (`feature`)

| Event | Status | Properties |
|---|---|---|
| `slideshow_enter` | live | `{}` |
| `slideshow_leave` | live | `{ itemsSeen }` |
| `slideshow_control_used` | live | `{ control }` — closed enum pinned to the live controls: `next \| prev \| play \| pause \| shuffle \| loop \| mute \| unmute \| timer_set \| focus_mode`. Fires only on user-initiated clicks/keys — never on timer auto-advance |
| `image_editor_opened` / `edit_image_used` | live | `{}` |
| `lineage_viewed` | live | `{}` |
| `remix_used`, `send_to_tool_used`, `send_to_chat_used`, `find_similar_used`, `compare_used`, `export_used`, `print_used` | live | `{}` |

## Feedback & privacy meta (`feedback`)

| Event | Status | Properties |
|---|---|---|
| `feedback_opened` | live | `{ source: menu\|thumb\|crash_prompt\|coachmark }` |
| `feedback_submitted` | live | `{ kind: feedback\|thumbs\|crash, thumb?, agentContext?, hasLogs, hasScreenshot, hasPackage }` — counting only; content goes through the consented feedback pipeline, never through telemetry |
| `feedback_consent_set` | live | `{ subject: thumbs\|crash, value: ask\|always\|never }` |

## Deliberately untracked

Per-media hashes, install attribution/referrers, uninstall beacons,
in-screen impression events, query text, semantic suggestion categories,
renames/duplicates/undo-restores, purge-vs-trash distinctions.

## CI guard

`backend/tests/test_privacy.py` asserts the load-bearing gates on every
PR: dev distribution → permanent no-op; official → nothing sent without
consent; pre-consent buffering semantics; the `telemetry_enabled
{enabled:false}` carve-out; `DO_NOT_TRACK=1` kills telemetry, the flags
fetch, the update check, and the region call; the User-Agent emits
exactly version/os/arch/branch/install-id; the body carries no install
id. `backend/tests/test_model_family.py` pins the munger fixtures and the
raw-string-never-egresses property.
