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
  across installs. Used for `projectHash`, `recipeHash`, `boardHash`,
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
  agent surfaces (chat main/recipe/delegate + prompt agent). Output is
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
| `session_started` | live | **The per-launch state snapshot**: `{ providerCount, providers[]{providerType,toolCount,connected,productName?,productVersion?}, toolCountsBySource{builtin,marketplace,cloud,user}, llmConfig{role→{source: auto\|stimma_cloud\|endpoint, endpointClass, modelFamily}}, mediaCountsByType{image,video,audio,document,set,grid,layout}, chatCount, boardCount, recipeCount, projectCount, savedViewCount, profileCount, markerCounts{favorite,library,custom}, skillCounts{marketplace,dev,builtin} }` — counts only, no names/content. `llmConfig` role keys are the app-defined closed role set; `source` is the *configured* value, distinct from per-event *resolved* `llmSource`. `markerCounts` keys are a literal match against the shipped default marker set (anything else, including renamed defaults, counts under `custom`). `providers[]` is the one sanctioned enumeration under the counts-over-enumerations rule (bounded by configured connections; mechanical fields only) |
| `session_ended` | planned | `{ durationMs }` — fired at shutdown **and** on the 30-min-inactivity session rotation. Dead-session recovery: when `previousExitClean: false`, the next launch flushes a buffered `session_ended{durationMs}` for the dead session from its last persisted activity timestamp |
| `app_error` | live | `{ source: backend\|frontend, errorType, stackHash, module? }` — exception type, stack hash, and top app-frame module only; no messages, paths, or locals (those can contain prompts/paths). Counting only |
| `onboarding_completed` | planned | `{}` — activation-funnel endpoint (`first_run` → `screen_viewed: onboarding` → this); all three buffer pre-consent and flush together on consent-on |
| `first_run` | planned | `{}` — fired client-side once on first launch, buffered through onboarding per the pre-consent rule. Authoritative install counting is server-side (`installs.first_seen_at`, upserted by every endpoint) — this event is the funnel-side marker, not the count |

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
| `screen_viewed` | live | `{ screen }` — values: `onboarding, home, browse, trash, upload, boards, board-detail, projects, project-overview, project-assets, project-chats, project-boards, project-recipes, project-settings, project-tools, chats, chat, recipes, recipe, saved-view, all-tools, edit-image, edit-image-landing, edit-image-empty, lineage, tool, skills`. Dev-only routes (`dev-*`) excluded. No path property, ever |

## Account (`account`)

| Event | Status | Properties |
|---|---|---|
| `cloud_signed_in` | live | `{ tier }` |
| `cloud_signed_out` | live | `{}` |
| `gate_encountered` | planned | `{ gate: signin_required\|tier_required\|quota_exhausted, surface: tool\|agent\|skill\|share }` — fired when the user hits a cloud gate. Outcome is derived by sequence (next `cloud_signed_in` / mode switch / abandon within session), not a semantic outcome property |

## Generation & tools (`generation`)

| Event | Status | Properties |
|---|---|---|
| `tool_used` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode: cloud\|byoai\|local, providerType?, controlnet? }` |
| `tool_completed` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, durationMs, queueMs, computeMs, providerType? }` — `durationMs` = end-to-end (submit→result, includes queue wait), `queueMs` = time queued, `computeMs` = pure provider compute |
| `tool_failed` | live | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, errorType, errorHash, providerType? }` — `errorType` is a closed list that **must include `provider_disconnected`** so disconnect-caused failures are separable from genuine job failures |
| `tool_cancelled` | planned | `{ runId, toolRef, toolSource, taskType, modelFamily, mode, durationMs, providerType? }` — `durationMs` = elapsed-at-cancel (cancellation latency is the best per-job frustration signal) |
| `batch_submitted` | planned | `{ toolRef, jobCount, expandedFromSets: bool }` |
| `forever_mode_used` | live | `{ toolRef, action }` |
| `controlnet_preview_used` | live | `{}` |
| `config_from_media_used` | live | `{}` |
| `auto_delete_configured` | live | `{ enabled, durationMinutes? }` |
| `tool_provider_added` | live | `{ providerType }` — user label never sent |
| `tool_provider_removed` | live | `{}` |
| `provider_connection_changed` | planned | `{ providerType, productName?, state: connected\|disconnected, inFlightJobs }` — mid-session connection transitions; `inFlightJobs` = jobs orphaned by a disconnect |
| `tool_provider_tested` | live | `{ success, providerType, productName?, productVersion? }` — product identity validated from the STP `server` field, never the free-string provider-reported version |
| `tool_preset_saved` / `tool_preset_applied` | live | `{ toolRef, presetHash }` |
| `preset_reverted` | planned | `{ toolRef, presetHash }` |
| `tool_preset_deleted` | planned | `{ toolRef, presetHash }` |
| `params_reset` | planned | `{ toolRef }` |
| `tool_hop_used` | planned | `{ fromToolRef, toToolRef }` |
| `generation_pipeline_completed` | planned | `{ runId, isRetry: bool, toolRef, toolSource, taskType, modelFamily, mode, source: toolview\|agent\|recipe\|forever, status: completed\|failed\|cancelled, durationMs, queueMs, genDurationMs, postprocessDurationMs, postprocessStepCount, postprocessToolRefs[], presetHash?, failedStepIndex?, errorType? }` — one event per user-initiated generation, emitted when the whole pipeline settles (generation + its post-processing chain). `durationMs` is wall-clock click→final asset; `postprocessToolRefs` is the ordered step list as a JSON array, each entry verbatim-or-hashed per the toolRef rule. `presetHash?` present when launched from a preset |

`modelFamily` × `taskType` is the headline product question and both
fields are classification outputs / protocol mechanics — they stay in
clear for every tool, including user-provider ones whose names we never
see.

## ToolView prompt agent (`prompt_agent`)

| Event | Status | Properties |
|---|---|---|
| `prompt_agent_step` | planned | `{ llmSource: stimma_cloud\|endpoint\|unknown, modelFamily, endpointClass?, durationMs, status: completed\|failed\|timeout, errorType? }` — one agent request/response cycle. `errorType` domain = the shared agent error list incl. `refusal`; `endpointClass?` present when `llmSource: endpoint` |
| `prompt_agent_action` | planned | `{ action }` — **UI clicks only**, closed enum from the actual controls: `select_suggestion \| reroll \| wildcard \| refresh_suggestions \| apply_edit \| dismiss`. Never semantic suggestion categories (those derive from prompt content) |

## Chat & agent (`chat`)

| Event | Status | Properties |
|---|---|---|
| `chat_created` | live | `{ chatHash, projectHash? }` |
| `chat_message_sent` | live | `{ chatHash, hasAttachments, hasSelectedMedia, messageCount }` |
| `agent_chat_sent` | live | `{ chatHash, llmSource: stimma_cloud\|endpoint\|unknown }` |
| `agent_turn_completed` | planned | `{ chatHash, llmSource, modelFamily, endpointClass?, durationMs, toolCallCount, status: completed\|failed\|cancelled\|quota_exceeded\|paused_for_permission, errorType?, agentContext: main\|recipe\|delegate }` — `errorType?` set when `failed`, domain = the shared closed agent error list with `refusal` and `content_filtered` as distinct members |
| `agent_error` | live | `{ errorType, chatHash?, agentContext }` — `errorType` is the same shared closed list (`quota_exceeded`, `content_filtered`, `subscription_required`, `llm_not_configured`, `refusal`, …); unknown errors map to `other`, never raw exception class names |
| `chat_deleted` | planned | `{ chatHash }` |
| `skill_invoked` | planned | `{ chatHash, skillSource: marketplace\|dev\|builtin, skillName? }` — `skillName` passes **only when `skillSource: marketplace`** (catalog data); dev/user skill names are user content and never pass |

`chatHash` turns conversation depth/retention into a measurable funnel —
still zero content.

## Recipes (`recipe`)

All recipe events carry `recipeHash` (install-salted, irreversible).

| Event | Status | Properties |
|---|---|---|
| `recipe_created` | planned | `{ recipeHash, projectHash?, forked: bool }` |
| `recipe_deleted` | planned | `{ recipeHash }` |
| `recipe_started` | planned | `{ recipeHash, dryRun: bool }` |
| `recipe_paused` / `recipe_resumed` / `recipe_cleared` | planned | `{ recipeHash }` |
| `recipe_completed` | planned | `{ recipeHash, durationMs, taskCount, llmCallCount, toolCallCount }` |
| `recipe_failed` | planned | `{ recipeHash, errorType, errorHash, stepKind }` — `stepKind` = the node type that killed the run, domain = the recipe runtime's closed node-type enum (`llm_call`, `tool_call`, `task`, `fetch_media`, `web_search`, …) — distinct from both the HITL `taskKind` list and the tool `taskType` list |
| `recipe_task_resolved` | planned | `{ recipeHash, taskKind, waitDurationMs }` — HITL responses; `waitDurationMs` = task-raised→resolved |

## Post-processing chains (`postprocess`)

| Event | Status | Properties |
|---|---|---|
| `chain_saved` | planned | `{ chainHash, stepCount, stepTypes[] }` — `stepTypes` = ordered values from the closed `taskType` enum incl. `filter` (never tool ids or step names) |
| `chain_executed` | planned | `{ chainHash?, stepCount, status: completed\|failed\|cancelled, durationMs }` — `chainHash?` present when running a saved chain (ad-hoc runs omit it) |
| `chain_step_failed` | planned | `{ stepType, errorType }` — `stepType` = the step's `taskType` (in-app filter steps are `filter`) — never a tool id or step name |
| `chain_retried` / `chain_run_dismissed` | planned | `{}` |

## Boards (`organize`)

All board events carry `boardHash` (install-salted, irreversible).

| Event | Status | Properties |
|---|---|---|
| `board_created` | planned | `{ boardHash, projectHash? }` |
| `board_deleted` | planned | `{ boardHash }` |
| `board_items_added` / `board_items_removed` | planned | `{ boardHash, count }` |
| `board_items_moved` | planned | `{ boardHash, count }` — moved between sections |
| `board_section_added` / `board_section_removed` | planned | `{ boardHash }` |
| `board_sections_reordered` | planned | `{ boardHash }` |

## Library (`library`)

| Event | Status | Properties |
|---|---|---|
| `media_uploaded` | live | `{ fileCount }` |
| `media_imported` | live | `{ count }` |
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
| `saved_view_deleted` | planned | `{}` |
| `project_created` / `project_deleted` | planned | `{ projectHash }` |
| `profile_created` | live | `{}` |
| `profile_deleted` | planned | `{}` |
| `profile_switched` | planned | `{}` |
| `profile_pin_set` / `profile_pin_removed` | planned | `{}` |
| `profile_locked` / `profile_unlocked` | planned | `{}` (PIN lock usage; never the PIN) |
| `folder_added` / `folder_removed` | live | `{ count }` (no paths) |
| `theme_changed` | live | `{ theme }` |
| `telemetry_enabled` | live | `{ enabled }` — fired on toggle change; the final `false` event is the last thing sent (the documented CI carve-out) |

## Skills (`skills`)

| Event | Status | Properties |
|---|---|---|
| `skill_marketplace_installed` | live | `{ skillName }` (marketplace names are catalog data, not user content) |
| `skills_auto_installed` | live | `{ count, skills[] }` — auto-installed skills are stock/marketplace, so names are catalog data |
| `skill_updated` | live | `{ skillSource, skillName? }` — the editor fires this for user-authored skills too, so the name passes only when `skillSource: marketplace` |
| `skill_uninstalled` | planned | `{ skillSource, skillName? }` — same marketplace-only name rule |
| `dev_skills_enabled` | planned | `{ skillCount }` — fired on the configuration transition, not per-launch; count only |

## Shares (`share`)

| Event | Status | Properties |
|---|---|---|
| `media_shared_to_cloud` | planned | `{ count }` (moderation outcomes live server-side, not in client telemetry) |

## Voice (`feature`)

| Event | Status | Properties |
|---|---|---|
| `voice_model_downloaded` | planned | `{ model }` (closed list — the shipped whisper models) |
| `voice_input_used` | planned | `{ surface: main_chat\|recipe_chat\|prompt_agent\|feedback, durationMs, outcome: committed\|cancelled }` (no transcript) |

## UI features (`feature`)

| Event | Status | Properties |
|---|---|---|
| `slideshow_enter` | live | `{}` |
| `slideshow_leave` | live | `{ itemsSeen }` |
| `slideshow_control_used` | planned | `{ control }` — closed enum from the actual controls: `mute \| unmute \| fullscreen \| exit_fullscreen \| timer_set \| pause \| resume \| next \| prev \| shuffle` |
| `image_editor_opened` / `edit_image_used` | live | `{}` |
| `lineage_viewed` | planned | `{}` |
| `remix_used`, `send_to_tool_used`, `send_to_chat_used`, `find_similar_used`, `compare_used`, `export_used`, `print_used` | live | `{}` |

## Feedback & privacy meta (`feedback`)

| Event | Status | Properties |
|---|---|---|
| `feedback_opened` | planned | `{ source: menu\|thumb\|crash_prompt\|coachmark }` |
| `feedback_submitted` | planned | `{ kind: feedback\|thumbs\|crash, thumb?, agentContext?, hasLogs, hasScreenshot, hasPackage }` — counting only; content goes through the consented feedback pipeline, never through telemetry |
| `feedback_consent_set` | planned | `{ subject: thumbs\|crash, value: ask\|always\|never }` |

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
