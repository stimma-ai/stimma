# Data Directories

Stimma uses a two-level directory scheme: **bundle identifier** selects the app channel, and **sandbox** selects an isolated instance within that channel.

```
<os-data-root>/<bundle-id>/<sandbox>/
```

## Bundle Identifiers (Release Channels)

Each release channel has its own bundle identifier, set in `tauri.conf.json` and patched by CI at build time:

| Channel | Bundle ID | When Used |
|---------|-----------|-----------|
| **Stable** | `ai.stimma.stimma` | Production release |
| **Beta** | `ai.stimma.stimma.beta` | Beta testing |
| **Canary** | `ai.stimma.stimma.canary` | Nightly/canary builds from `main` |
| **Debug** | `ai.stimma.stimma.debug` | Local development (default in `tauri.conf.json` and CLI) |

Channels are fully isolated — each has its own database, settings, and cache. You can run stable and canary side-by-side without conflicts.

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
stimma fork create my-feature     # copies default/ → my-feature/
stimma --sandbox=my-feature dev server
stimma --sandbox=my-feature dev frontend
stimma fork destroy my-feature    # deletes my-feature/ data + cache
```

The fork is a full copy of the default sandbox — database, settings, auth tokens — so no re-login is needed.

### Port allocation

| Instance | Server | Frontend |
|----------|--------|----------|
| Default | 9292 | 9293 |
| First fork | 9300 | 9301 |
| Second fork | 9302 | 9303 |
| ... | up to 9398 | up to 9399 |

Fork ports are stored in `<sandbox>/.fork.json` and loaded automatically by the CLI.

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
├── stimma.db               # SQLite database (library, metadata)
├── stimma.db-wal           # SQLite write-ahead log
├── stimma.db-shm           # SQLite shared memory
├── settings.yaml         # User config (auth, folders, preferences)
├── .fork.json            # Port assignments (sandboxes only)
└── Logs/
    ├── server.jsonl      # Current server log (JSON lines)
    ├── server.01.jsonl   # Previous session
    ├── ...               # Up to server.20.jsonl
    ├── app.jsonl          # Current Tauri app log
    ├── app.01.jsonl
    └── ...               # Up to app.20.jsonl
```

**Key rules:**
- `settings.yaml` holds user preferences, auth tokens, folder config — never library content.
- `stimma.db` holds library content and indexed data — never user preferences.
- Logs rotate on startup: `server.jsonl` → `server.01.jsonl` → ... → `server.20.jsonl` (oldest deleted).

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
stimma fork create my-feature             # copy default → my-feature, assign ports
stimma --sandbox=my-feature dev server    # run against the fork
stimma fork destroy my-feature            # clean up

# Inspect
stimma dir                                # print data directory path
stimma fork                               # list all sandboxes with sizes and ports
```
