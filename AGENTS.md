> If this checkout lives inside a larger workspace, check the parent directory (`../CLAUDE.md` / `../AGENTS.md`) for additional agent guidance — some agents don't walk up on their own.

## Development notes

- ALWAYS USE TAILWINDCSS. No custom CSS unless absolutely necessary.
- **This is a uv project.** Always use `uv run` to execute Python commands in the backend (e.g., `uv run python`, `uv run pytest`). Never try to activate the venv manually.
- This project has a comprehensive CLI at tools/stimma which abstracts devex tasks. See below for help info.
- Do not start or restart development servers automatically. Assume the developer manages long-running frontend and backend processes; ask before restarting them.
- Always implement soft-delete for new database tables.
- Use trash icons for delete actions, not X icons - this is the project convention.
- **Built-in stimpack SOURCE lives in a sibling repo, not here:** `../stimma-skills` (i.e. `~/stimma/stimma-skills`), one directory per stimpack. They are *not* loaded from this repo — at runtime the app loads stimpacks from the profile dir (after cloud marketplace install). For dev, point the app at the sibling repo with `stimma stimpacks dev` (writes `dev_stimpacks_dir` to config.yaml); those stimpacks then shadow the profile-installed copies live, so editing `../stimma-skills` needs no publish/install. See backend `agent/v2/stimpacks.py` (`_dev_stimpacks_dir` / `_iter_effective_stimpack_dirs`).

## Database Guidelines

Database migrations are handled using alembi and run automatically at startup. Do not modify the database schema any other way. 

## Data Directories

Stimma uses a two-level directory scheme: **bundle ID** (release channel) + **sandbox** (isolated instance).

```
~/Library/Application Support/<bundle-id>/<sandbox>/
```

Bundle IDs: `ai.stimma.stimma` (stable), `ai.stimma.stimma.debug` (dev, default for CLI).

The CLI defaults to the `debug` channel and `default` sandbox. Use `--channel=X` or `--prod` to switch channels, `--sandbox=NAME` for sandboxes.

See `docs/DATA_DIRECTORIES.md` for full details.

Config files are located at:
- `~/Library/Application Support/ai.stimma.stimma/default/config.yaml` (PRODUCTION)
- `~/Library/Application Support/ai.stimma.stimma.debug/default/config.yaml` (DEVELOPMENT)


## UI Guidelines

- When building code that adds a new entity, don't pop up a modal asking the person to name it. Just create it with no name or Untitled or whatever makes sense and make it easy for the user to rename later.
- Never use browser based "alert" sheets for confirmations or prompts to the user. Use modals instead.

### Design language — READ frontend/DESIGN.md FIRST

All UI work follows the Atelier v3 design language, specified in
`frontend/DESIGN.md` (tokens, z-scale, radius roles, row grammars, separator
law, greppable review rules). Read it before building or restyling anything.
Quick anchors: teal `accent` = actions; indigo `selection` = selected state;
magenta `live` = user-armed continuous modes; `matte` behind media;
`rounded-media` (2px) on artwork; sentence-case section labels with no rule
under headings; hairlines only BETWEEN peers; blue-500 is status-only (never
an interactive accent). Use the kit in `frontend/src/components/ui/` instead
of hand-rolling controls.

### Stimma Cloud Branding

**All Stimma Cloud UI elements must use the Stimma Cloud gradient branding.** The GRADIENT (and gradient text/borders) is cloud-reserved — never on non-cloud features. Solid teal via the `accent` token is the app-wide interactive accent and is fine everywhere; solid indigo via `selection` likewise. What is reserved is the teal→cyan→indigo gradient treatment, not the individual hues.

**Core Gradient:** `teal-600` → `cyan-500` → `indigo-500`
- CSS variables: `--stimma-cloud-start: #0d9488`, `--stimma-cloud-mid: #06b6d4`, `--stimma-cloud-end: #6366f1`
- Tailwind: `from-teal-600 via-cyan-500 to-indigo-500`

**CSS Utility Classes** (defined in `style.css`):
- `.stimma-cloud-text` - Gradient text effect
- `.stimma-cloud-border` - Animated gradient border (40% opacity, 60% on hover)
- `.stimma-cloud-border-solid` - Solid gradient border (60% opacity)

**Common Patterns:**
- Gradient borders: Wrap with `p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40`, inner `bg-zinc-900/90`
- CTA buttons: `bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 text-white`
- Hover: `hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400`

**Tier Badge Colors:**
| Tier | Background | Text |
|------|-----------|------|
| Power | `bg-indigo-900/50` | `text-indigo-400` |
| Pro | `bg-cyan-900/50` | `text-cyan-400` |
| Free (BYOAI) | `bg-zinc-700/50` | `text-zinc-400` |

## Important Docs

See the docs/ folder. In particular:

- If you are working on tools or the Stimma Tools Protocol (STP), see the spec at https://github.com/stimma-ai/stimma-tools-protocol
- If you are working on local Stimma Cloud target overrides, see docs/CLOUD_TARGETS.md. Keep private staging hostnames and Access tokens out of this OSS repo; use ignored `.env.local` values instead.
- If you are working on the agent, **read docs/AGENT_V2_PRINCIPLES.md first** — it defines the design philosophy, anti-patterns to avoid, and diagnosis checklist for agent bugs
- If you are creating or modifying stimpacks, see docs/STIMPACK_AUTHORING.md — covers both markdown-only stimpacks and stimpacks with bundled Python code

### Media Display Components

**NEVER use raw `<img>` tags for displaying library media.** Always use the standard media components which provide:
- Drag-drop support (in-app transfers + native file drag in Tauri)
- Context menu integration (right-click actions)
- Proper URL computation from mediaId/fileHash
- Correct impleementation of checkerboard backgrounds, thumbnails, etc.
- Support for all data types (image,video,audio,document,set,grid)

| Component | Use Case |
|-----------|----------|
| **MediaImage** | Primary component for library images. Use when you have a `mediaId`. Handles thumbnails, drag-drop, and context menu automatically. |
| **AppImage** | Lower-level component for arbitrary image URLs (non-library images, external URLs). No drag-drop or context menu. |

## Stimma CLI

Stimma Development CLI

Usage: stimma [FLAGS] <command> <subcommand>

Flags:
  --prod              Shorthand for --channel=production
  --channel=CHANNEL   Release channel: debug (default), sandbox, canary, beta, production
  --sandbox=NAME      Sandbox name (default: "default")
  --official          dev/run only: set STIMMA_DISTRIBUTION=official in the child
                      process so telemetry, consent UI, thumbs, and crash reports
                      behave like an official build (events go to the configured
                      cloud; app_branch stays 'dev' on the debug channel)

Commands:
  dev frontend    Run Vite dev server with HMR (default port 9192)
  dev backend     Run Python backend with nodemon (default port 9191)
  dev backend2    Run Rust backend (default port 9191)
  dev app         Run Tauri in dev mode
  dev all         Run backend + frontend + Tauri together with merged logs
  run backend     Run backend without file watching
  run frontend    Build and serve frontend (no HMR)
  run app         Run Tauri app (release, no watching)
  tail backend    Tail backend logs
  tail app        Tail Tauri app logs
  app build       Build packaged app with portable backend
  app build --release  Build with polished DMG (macOS)
  app run         Run built app
  app install     Install built app
  config edit     Open config.yaml in $EDITOR
  stimpacks dev [path]   Use a stimpacks dir as the live authority for built-in stimpacks
                      (default: sibling stimma-skills repo). Shadows installed copies.
  stimpacks dev --off    Clear the dev stimpacks override
  stimpacks validate PATH...  Validate stimpack directories with the real loader
                      (skills, environments, lib modules; non-zero exit on errors)
  backup          Create timestamped backup of data directory
  lint backend    Run ruff over the backend (undefined names, syntax errors)
  lint frontend-dead-code
                  Run Knip's conservative unused frontend file check
  test backend    Run backend pytest tests
  test acceptance Run the release acceptance lane (fresh sandbox + fake tools)
  test acceptance --headed --slow-mo=250  Watch Chromium run the lane slowly
  test cv2-parity Run cv2 parity proof (uses optional cv2-parity extra)
  doctor assets     Read-only Asset/Media integrity audit
  doctor assets --verify-hashes  Also hash every managed payload
  tag beta [X.Y.Z]    Tag HEAD as the next beta (train = next production version)
                      (canary builds are automatic on push to main — not tag-driven)
  promote production  Promote the latest beta's commit to a production release
                      [--ref REF] hotfix override: promote an explicit git ref
                      [--yes] skip the confirmation prompt
  dir               Print data directory path
  fork              List all sandboxes with sizes and ports
  fork create NAME  Copy default sandbox to a new named sandbox
  fork create NAME --empty  Create a FRESH first-run sandbox (empty except
                      .fork.json with assigned ports) — backend boots it
                      as a new install: config auto-init, consent undetermined
  fork destroy NAME [--yes]  Delete a named sandbox (data + cache); --yes skips
                      the confirmation prompt (required for non-interactive use)
  bd [args...]    Passthrough to beads CLI

## Backend Tests

The backend has a comprehensive integration test suite in `backend/tests/`. Run tests with:

```bash
cd backend
uv run pytest                          # Run all tests
uv run pytest tests/test_media.py -v   # Run specific file with verbose output
uv run pytest -k "test_filter"         # Run tests matching pattern
```

**Test files:**
- `test_media.py` - Media listing, filtering, search, WebSocket events
- `test_markers.py` - Marker CRUD, assignment, bulk operations
- `test_boards.py` - Board CRUD, membership, cover images
- `test_tags.py` - Tag CRUD, assignment, bulk operations
- `test_trash.py` - Soft delete, restore, permanent delete, empty trash
- `test_browse_filters.py` - Media type, resolution, folder, date, generated filters

**Test helpers** (`tests/helpers/`):
- `media.py` - `create_media_item()` and `create_test_media()` for seeding test data
- `ws.py` - `MockWebSocketManager` for verifying WebSocket broadcasts

When adding new API endpoints, ALWAYS add corresponding tests. The test infrastructure uses module-scoped fixtures for database isolation. Do not over-mock tests, use real database operations where possible.

## Config Files

Config files are located in:

- ~/Library/Application Support/ai.stimma.stimma/default/config.yaml (PRODUCTION)
- ~/Library/Application Support/ai.stimma.stimma.debug/default/config.yaml (DEVELOPMENT)

If you are asked to modify config files for 'prod' and 'dev', you may. Rules:

- Always make a .bak file before modifying existing config files
- Always modify these files incrementally in a narrow task specific way. Don't replace the whole file.

ASK FOR PERMISSION before touching production files or databases.

Most of the config file surface area is mirrored in the settings UI. The correct way to edit config is to change the file. The app auto-reloads config and will pick up changes.

## Terminology

- **Filter Cart**: The 'shopping cart' strip on the browse views at the top that shows selected criteria
- **STP**: Stimma Tools Protocol - JSONRPC protocol for tool communication
- **Asset**: A stable, user-meaningful item shown in ordinary browsers. Assets are durable roots with immutable revisions; they are not owned or garbage-collected by chats, projects, or containers.
- **Asset Revision**: One immutable saved state of an Asset. Its primary Media payload supplies the current browser projection.
- **Media Item**: An immutable payload/provenance record retained by an Asset revision or another explicit owner. Bare Media does not appear in ordinary Asset browsers.
- **Atomic Media**: Standalone media files that don't contain other media: images, videos, audio, documents. These can be transformed by tools.
- **Composite Media**: Container media that holds references to other media items: sets (.stimmaset.json), grids (.stimmagrid.json). These are grouping operations, not transformations. See `utils/query_builder.py` for `ATOMIC_FORMATS`, `COMPOSITE_FORMATS`, `is_composite_media()`, `is_atomic_media()`.
- **Container Member**: A set/grid member that either weakly links an independent Asset (following its current revision) or embeds exact Media retained by the container revision. Membership is non-exclusive.
- **Tool**: A tool provided by Stimma Tools Protocol. Tools can be internal (built-in) or external (third-party). Tools perform operations on media items
- **Task**: What a tool does. A tool can implement multiple tasks. Each task comes with a set of required inputs + outputs, like an interface. Examples include 'text-to-image', 'image-to-image', etc.
- **Ingestion**: A separate process that handles processing and importing media in the background. Performs tasks like AI captioning, visual indexing (CLIP encoding), metadata extraction, etc.
- **Source**: An optional external folder Stimma scans for media. Sources are read-only from Stimma's perspective and are never generation or upload destinations.
- **Managed Storage**: Private per-profile content-addressed storage owned by Stimma. Generated and uploaded payloads pass through private staging before ingestion; clients do not select its location.
- **Browser Screens**: This includes All Assets, saved views, board screens, and Trash. These are Asset browsers and never list bare Media. They share substantial infrastructure, treatment, functionality, and behavior, and should be kept in sync.
- **Selection Bar**: The controls that appear at the bottom of the browser screen when the user selects an asset
- <If you encounter new terms, add them here.>
