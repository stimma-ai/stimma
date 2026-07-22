# Data Directories

Stimma uses a two-level directory scheme: **bundle identifier** selects the app channel, and **sandbox** selects an isolated instance within that channel.

```
<os-data-root>/<bundle-id>/<sandbox>/
```

## Bundle Identifiers (Release Channels)

Each release channel has its own bundle identifier, set in `tauri.conf.json` and patched by CI at build time:

| Channel | Bundle ID | When Used |
|---------|-----------|-----------|
| **Production** | `ai.stimma.stimma` | Production release |
| **Beta** | `ai.stimma.stimma.beta` | Beta testing |
| **Canary** | `ai.stimma.stimma.canary` | Canary builds (auto-built on every push to `main`) |
| **Debug** | `ai.stimma.stimma.debug` | Local development (default in `tauri.conf.json` and CLI) |

Channels are fully isolated — each has its own database, settings, and cache. You can run production and canary side-by-side without conflicts. See `docs/RELEASE_CHANNELS.md` for how each channel is built and updated.

## Sandboxes

Within a bundle, the **sandbox** selects which data directory to use. It defaults to `"default"`.

```
~/Library/Application Support/ai.stimma.stimma.debug/default/    # normal dev
~/Library/Application Support/ai.stimma.stimma.debug/my-feature/ # sandbox
~/Library/Application Support/ai.stimma.stimma.debug/test/       # another sandbox
```

Sandboxes exist to support **git worktrees** and parallel testing. Each sandbox has its own database, settings, logs, and port assignments.

### Creating sandboxes

```bash
stimma fork create my-feature     # snapshots default/ → my-feature/
stimma --sandbox=my-feature dev backend
stimma --sandbox=my-feature dev frontend
stimma fork destroy my-feature    # deletes my-feature/ data + cache
```

The fork is a complete snapshot of the default sandbox — database, settings,
auth tokens — so no re-login is needed. Stop the default sandbox's backend
before creating it. On macOS/APFS the snapshot uses copy-on-write clones, so it
is fast and initially consumes space only for filesystem metadata; subsequent
writes allocate private blocks in the sandbox that changed. Linux filesystems
use reflinks when available and otherwise fall back to an archive copy.

### Port allocation

| Instance | Server | Frontend |
|----------|--------|----------|
| Default | 9191 | 9192 |
| First fork | 9400 | 9401 |
| Second fork | 9402 | 9403 |
| ... | up to 9498 | up to 9499 |

Fork ports are stored in `<sandbox>/.fork.json` and loaded automatically by the CLI.

## Browser Profiles

The Tauri WebView profile follows the same sandbox lifecycle. On Windows and
Linux its files live at `<data-dir>/browser/`. macOS does not allow WKWebView
apps to select the physical website-data directory, so Stimma stores a random
WebKit data-store identifier at `<data-dir>/browser/data-store-id` and uses it
to select an isolated persistent profile. Deleting or recreating the Stimma
sandbox therefore produces a blank WebView profile even though macOS manages
the profile's physical files under `~/Library/WebKit`.

## Platform Paths

### macOS (desktop)

```
Data:  ~/Library/Application Support/<bundle-id>/<sandbox>/
Cache: ~/Library/Caches/<bundle-id>/<sandbox>/
```

Example:
```
~/Library/Application Support/ai.stimma.stimma.debug/default/
~/Library/Caches/ai.stimma.stimma.debug/default/
```

The bundle ID is used directly as the folder name. The Tauri app sets `STIMMA_DATA_DIR` and `STIMMA_CACHE_DIR` environment variables before launching the backend.

### Windows

```
Data:  %LOCALAPPDATA%/<bundle-id>/<sandbox>/
Cache: %LOCALAPPDATA%/<bundle-id>/<sandbox>/
```

### Linux

```
Data:  ~/.local/share/<bundle-id>/<sandbox>/
Cache: ~/.cache/<bundle-id>/<sandbox>/
```

### iOS

The app sandbox provides further isolation.

```
Data:  <app-sandbox>/Library/Application Support/<bundle-id>/<sandbox>/
Cache: <app-sandbox>/Library/Caches/<bundle-id>/<sandbox>/
```

### Android

Paths are constructed directly from the bundle identifier:

```
Data:  /data/data/<bundle-id>/files/<sandbox>/
Cache: /data/data/<bundle-id>/cache/<sandbox>/
```

## Contents of a Data Directory

```
<sandbox>/
├── config.yaml             # User config (auth, Sources, preferences)
├── .fork.json              # Port assignments (sandboxes only)
├── <profile-id>/
│   ├── stimma_v1.db        # SQLite database (Assets, Media, metadata)
│   ├── objects/
│   │   ├── sha256/         # Canonical content-addressed managed payloads
│   │   └── media/          # Stable per-Media compatibility links
│   └── staging/
│       ├── generated/      # Private transient generation staging
│       └── uploads/        # Private transient upload staging
└── Logs/
    ├── server.jsonl      # Current server log (JSON lines)
    ├── server.01.jsonl   # Previous session
    ├── ...               # Up to server.20.jsonl
    ├── app.jsonl          # Current Tauri app log
    ├── app.01.jsonl
    └── ...               # Up to app.20.jsonl
```

**Key rules:**
- `config.yaml` holds user preferences, auth tokens, and optional external Source paths — never library content.
- Each profile database holds Asset/Media identity and indexed data; managed bytes live beside it under `objects/`.
- Generated and uploaded payloads never use a Source as an output destination.
- `staging/` is private and transient. Durable managed identity is the content-addressed object under `objects/sha256/`.
- Logs rotate on startup: `server.jsonl` → `server.01.jsonl` → ... → `server.20.jsonl` (oldest deleted).

## Local snapshots

`stimma backup` creates a timestamped snapshot beside the selected sandbox.
Stop that sandbox's backend first so its SQLite databases and WAL files cannot
change during the snapshot. On macOS/APFS, regular files are copy-on-write
clones; Linux uses reflinks when the filesystem supports them. The command
falls back to a full byte copy when cloning is unavailable.

The completed snapshot is first assembled under a temporary name and then
renamed into place, so an interrupted copy is not presented as a completed
snapshot. These same-volume snapshots are useful for local rollback and
development, but they are not off-machine disaster-recovery backups. Tools
such as `du` may count shared clone extents more than once; filesystem free
space is the better measure of their incremental physical cost.

## Environment Variable Overrides

Environment variables take highest precedence, overriding all path derivation:

| Variable | Purpose |
|----------|---------|
| `STIMMA_DATA_DIR` | Override data directory |
| `STIMMA_CACHE_DIR` | Override cache directory |
| `STIMMA_TMP_DIR` | Override temp directory |
| `STIMMA_PORT` | Override server port |
| `STIMMA_LOG_LEVEL` | `debug`, `info`, `warn`, `error` |

The Tauri app only derives paths from the bundle identifier when `STIMMA_DATA_DIR` is **not** set. The CLI always computes paths from the bundle ID and sandbox name, then passes them as env vars to the server.

## How It Fits Together

```
┌──────────────────┐     ┌──────────────────────────────────────┐
│  CLI               │     │  Tauri App                            │
│  (stimma dev)      │     │  (desktop / mobile)                   │
│                    │     │                                       │
│  --channel=debug   │     │  identifier from tauri.conf.json      │
│  --sandbox=NAME    │     │  (patched by CI per channel)          │
│                    │     │                                       │
│  Derives bundleId  │     │  Uses bundle ID directly as folder    │
│  from channel,     │     │  name, always sandbox="default"       │
│  passes to backend │     │                                       │
│  as --bundle-id    │     │  Sets STIMMA_DATA_DIR, STIMMA_CACHE_DIR│
│  and --sandbox     │     │  before launching server              │
└──────┬─────────────┘     └──────────────┬─────────────────────┘
       │                                  │
       ▼                                  ▼
┌────────────────────────────────────────────────┐
│  Server (stimma backend)                       │
│                                                │
│  Reads STIMMA_DATA_DIR / STIMMA_CACHE_DIR      │
│  or derives from --bundle-id + --sandbox       │
│  Opens config.yaml, profile databases          │
│  Writes logs to Logs/                          │
└────────────────────────────────────────────────┘
```

## CLI Quick Reference

```bash
# Default dev instance
stimma dev backend                        # ai.stimma.stimma.debug/default/

# Named sandbox
stimma --sandbox=test dev backend         # ai.stimma.stimma.debug/test/

# Fork workflow (for git worktrees)
stimma fork create my-feature             # snapshot default → my-feature, assign ports
stimma --sandbox=my-feature dev backend   # run backend against the fork
stimma --sandbox=my-feature dev frontend  # run frontend against the fork
stimma fork destroy my-feature            # clean up

# Inspect
stimma dir                                # print data directory path
stimma fork                               # list all sandboxes with sizes and ports
```
