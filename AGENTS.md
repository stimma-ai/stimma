## Development notes

- ALWAYS USE TAILWINDCSS. No custom CSS unless absolutely necessary.
- **This is a uv project.** Always use `uv run` to execute Python commands in the backend (e.g., `uv run python`, `uv run pytest`). Never try to activate the venv manually.
- This project has a comprehensive CLI at tools/stimma which abstracts devex tasks. See below for help info.
- I am already running the backend and frontend in other terminal windows with nodemon/etc. You don't need to restart it, start it, etc. If you need something from me, just ask.
- Always implement soft-delete for new database tables.
- Use trash icons for delete actions, not X icons - this is the project convention.
- Stimma includes an agent system like claude code with stimpacks. 99% of the time when I talk about the agent or stimpacks, I mean Stimma's system, not Claude Code's. Don't get confused!
- **Built-in stimpack SOURCE lives in a sibling repo, not here:** `../stimma-skills` (i.e. `~/stimma/stimma-skills`), one directory per stimpack. They are *not* loaded from this repo — at runtime the app loads stimpacks from the profile dir (after cloud marketplace install). For dev, point the app at the sibling repo with `stimma stimpacks dev` (writes `dev_stimpacks_dir` to config.yaml); those stimpacks then shadow the profile-installed copies live, so editing `../stimma-skills` needs no publish/install. See backend `agent/v2/stimpacks.py` (`_dev_stimpacks_dir` / `_iter_effective_stimpack_dirs`).

## Database Guidelines
- Database migrations are handled using alembic
- DO NOT modify schemas outside of this context. DO NOT run sqlite commands to modify schemas. DO NOT write other code that modifies schemas
- Database migrations run automatically at startup.
- **Database migrations run automatically at backend startup** - no manual migration commands needed. Just restart the backend. DO NOT MANUALLY MODIFY THE DATABASE. INSTEAD STOP AND ASK FOR HELP.

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

### Standard Colors

Use these Tailwind color classes consistently across the UI:

- **Primary Blue** (`blue-500`): Active/selected states, positive filter criteria, links, accents
  - Background: `bg-blue-500/15` with `border-blue-500/50`
  - Text: `text-blue-500` or `text-blue-400`
- **Red** (`red-500`): Negative/excluded states, destructive actions
  - Background: `bg-red-500/15` with `border-red-500/50`
  - Text: `text-red-500` or `text-red-400`
- **Neutral/Inactive**: `bg-white/[0.05]` with `border-white/10`, `text-[#888]`

### Stimma Cloud Branding

**All Stimma Cloud UI elements must use the Stimma Cloud gradient branding.** Do not use these colors (teal-600, cyan-500, indigo-500) for non-cloud features.

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
  --prod              Shorthand for --channel=stable
  --channel=CHANNEL   Release channel: debug (default), canary, beta, stable
  --sandbox=NAME      Sandbox name (default: "default")

Commands:
  dev frontend    Run Vite dev server with HMR (port 9192)
  dev backend     Run backend with nodemon (port 9191)
  dev app         Run Tauri in dev mode
  run backend     Run backend without file watching
  run frontend    Build and serve frontend (no HMR)
  run app         Run Tauri app (release, no watching)
  tail backend    Tail backend logs
  tail app        Tail Tauri app logs
  app build       Build packaged app (fast, no DMG polish)
  app build --release  Build with polished DMG
  app run         Run built app
  app install     Install built app to /Applications
  config edit     Open config.yaml in $EDITOR
  backup          Create timestamped backup of data directory
  dir             Print data directory path
  fork            List all sandboxes with sizes and ports
  fork create NAME  Copy default sandbox to a new named sandbox
  fork destroy NAME Delete a named sandbox (data + cache)
  test backend    Run backend pytest tests
  eval run        Run agent evals
  eval list       List available eval tasks
  eval results    Show recent eval runs

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
- `test_collections.py` - Collection CRUD, membership, cover images
- `test_tags.py` - Tag CRUD, assignment, bulk operations
- `test_trash.py` - Soft delete, restore, permanent delete, empty trash
- `test_browse_filters.py` - Media type, resolution, folder, date, generated filters

**Test helpers** (`tests/helpers/`):
- `media.py` - `create_media_item()` and `create_test_media()` for seeding test data
- `ws.py` - `MockWebSocketManager` for verifying WebSocket broadcasts

When adding new API endpoints, ALWAYS add corresponding tests. The test infrastructure uses module-scoped fixtures for database isolation. Do not over-mock tests, use real database operations where possible.

## Agent Evals

The agent has a statistical eval framework in `backend/agent/evals/`. Use `/eval-results` stimpack when working on eval failures.

**Running evals:**
```bash
cd backend
uv run python -m agent.evals --llm-config agent/evals/configs/dev.yaml --tasks greeting --no-open
uv run python -m agent.evals --list  # List all tasks
```

**Results structure:**
```
backend/agent/evals/results/
  run_<timestamp>/
    report.json           # Overall summary
    <task_id>/
      summary.json        # Task stats + source code location
      trial_0001_PASS.json
      trial_0002_FAIL.json
```

**Key files:**
- `tasks/*.py` - Task definitions (what to test, how to grade)
- `graders.py` - Built-in graders (ResponseContainsGrader, NoErrorGrader, etc.)
- `hitl.py` - Scripts for automated HITL responses in tests

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
- **Media Item**: An image, video, audio, or document file stored in the Stimma library. Also known as ASSET. Media Item types include image, video, audio, document, set, and grid
- **Atomic Media**: Standalone media files that don't contain other media: images, videos, audio, documents. These can be transformed by tools.
- **Composite Media**: Container media that holds references to other media items: sets (.stimmaset.json), grids (.stimmagrid.json). These are grouping operations, not transformations. See `utils/query_builder.py` for `ATOMIC_FORMATS`, `COMPOSITE_FORMATS`, `is_composite_media()`, `is_atomic_media()`.
- **Hidden Media**: Media items that are hidden from normal library views. This includes both superseded media and media marked as hidden by the user
- **Superseded Media**: A type of hidden media. These media items have been replaced by newer versions (e.g., after editing, being grouped into sets/grids, upscaling)
- **Tool**: A tool provided by Stimma Tools Protocol. Tools can be internal (built-in) or external (third-party). Tools perform operations on media items
- **Task**: What a tool does. A tool can implement multiple tasks. Each task comes with a set of required inputs + outputs, like an interface. Examples include 'text-to-image', 'image-to-image', etc.
- **Ingestion**: A separate process that handles processing and importing media in the background. Performs tasks like AI captioning, visual indexing (CLIP encoding), metadata extraction, etc.
- **Browser Screens**: This includes the 'all assets (aka all media)' screen, the saved views, the collection screen, and the trash screen. All of these screens share substantial infrastructure, treatment, functionality, and behavior, and should be kept in sync
- **Selection Bar**: The controls that appear at the bottom of the browser screen when the user selects an asset
- <If you encounter new terms, add them here.>

