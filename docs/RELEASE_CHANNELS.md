# Release Channels & Updates

How code flows from `main` to users, and how the Tauri updater keeps apps current.

## Channels

| Channel | Bundle ID | Branch | Trigger | Icon |
|---------|-----------|--------|---------|------|
| **Canary** | `ai.stimma.stimma.canary` | `main` | Every push to main | Yellow ribbon badge |
| **Beta** | `ai.stimma.stimma.beta` | `release/beta` | Manual build tag | Blue ribbon badge |
| **Stable** | `ai.stimma.stimma` | `release/stable` | Manual build tag | Standard (no badge) |
| **Debug** | `ai.stimma.stimma.debug` | N/A | Local `stimma dev` | N/A |

Each channel is a **separate installable app** — different bundle ID, different data directory, different icon. All three can coexist on the same machine.

## Promotion Flow

Code flows one direction: **main → canary → beta → stable**.

```
main ──push──► canary (automatic)
  │
  └── cherry-pick to release/beta ──tag──► beta (manual)
  │
  └── cherry-pick to release/stable ──tag──► stable (manual)
```

Canary builds automatically on every push to `main`. Beta and stable require cherry-picking commits to their release branches, then pushing a build trigger tag.

## Versioning

**Format:** `Major.Minor.Build` (e.g., `0.1.5`)

- **Major.Minor** — Set manually via a **seed tag**: `git tag build/canary/macos-desktop/0.1`
- **Build** — Auto-incremented globally per product across all channels

The build counter is shared so versions always increase monotonically regardless of channel:

```
0.1.1  canary
0.1.2  canary
0.1.3  beta     ← promoted from canary
0.1.4  canary
0.1.5  stable   ← promoted from beta
0.1.6  canary
```

To bump Major.Minor (e.g., for a `1.0` release), create a new seed tag:
```bash
git tag build/canary/macos-desktop/1.0
git push --tags
```

## Git Tag Scheme

**Seed tags** (2-part, set manually):
```
build/canary/macos-desktop/0.1     ← tells CI what Major.Minor to use
```

**Build trigger tags** (2-part, pushed to start a beta/stable build):
```
build/beta/macos-desktop/0.1       ← triggers beta build
build/stable/macos-desktop/0.1     ← triggers stable build
```

**Build result tags** (3-part, created by CI after success):
```
build/canary/macos-desktop/0.1.5   ← records completed build
build/beta/macos-desktop/0.1.3
build/stable/macos-desktop/0.1.5
```

CI computes the next build number by scanning all existing result tags:
```bash
git tag -l "build/*/macos-desktop/*.*.*" | sed 's/.*\.\([0-9]*\)$/\1/' | sort -n -r | head -1
# next = result + 1
```

## CI Pipeline (`.github/workflows/build.yml`)

Triggered by: push to `main` (canary) or push of a `build/*/*/*` tag (beta/stable).

### Jobs

```
prepare ──► build-frontend ──► build-macos-desktop ──► publish
```

**1. Prepare** (Ubuntu)
- Parses git ref to determine channel, product, major.minor
- For beta/stable: validates the commit is on the correct release branch
- Computes next build number from existing result tags

**2. Build Frontend** (Ubuntu)
- `pnpm install && pnpm build` in `frontend/ui`
- Uploads `dist/` as artifact

**3. Build macOS Desktop** (self-hosted macOS runner)
- Downloads frontend dist
- **Patches `tauri.conf.json`:**
  - `version` → `Major.Minor.Build`
  - `identifier` → channel-specific bundle ID
  - `plugins.updater.endpoints` → channel-specific update URL
- **Swaps icons** for canary/beta (copies from `app/src-tauri/icons/{channel}/`)
- Builds server as universal binary (aarch64 + x86_64) via `lipo`
- Places sidecar binaries in `app/src-tauri/binaries/`
- Builds Tauri app with Apple code signing + notarization + updater signing
- Uploads: `.dmg`, `.app.tar.gz`, `.app.tar.gz.sig`

**4. Publish** (Ubuntu)
- Creates build result tag (e.g., `build/canary/macos-desktop/0.1.5`)
- Generates `latest.json` from the signature file
- Uploads artifact + `latest.json` to Cloudflare R2

### What CI patches in `tauri.conf.json`

| Field | Debug (checked in) | Canary (CI) | Stable (CI) |
|-------|-------------------|-------------|-------------|
| `version` | `0.1.0` | `0.1.5` | `0.1.5` |
| `identifier` | `ai.stimma.stimma.debug` | `ai.stimma.stimma.canary` | `ai.stimma.stimma` |
| `plugins.updater.endpoints[0]` | (template) | `...?channel=canary&product=macos-desktop&...` | `...?channel=stable&product=macos-desktop&...` |

## Update Server (`cloud/updates/`)

A Cloudflare Worker (Hono) serving updates from R2.

**Deployed at:** `updates.hi.ro` (prod), `updates-dev.hi.ro` (dev)

### Endpoints

**`GET /update`** — Tauri updater endpoint
```
?channel=canary&product=macos-desktop&target=darwin&arch=aarch64&current_version=0.1.4
```
- Reads `{channel}/{product}/latest.json` from R2
- Looks up platform entry for `{target}-{arch}`
- Returns 200 + JSON if update available, 204 if not
- Tauri handles version comparison client-side

**`GET /artifacts/{channel}/{product}/{filename}`** — Streams artifact from R2

**`GET /ls`** — Debug: lists all R2 objects

### R2 Layout

```
stimma-updates/
  canary/macos-desktop/
    latest.json
    Stimma_0.1.5_universal.app.tar.gz
  beta/macos-desktop/
    latest.json
    Stimma_0.1.3_universal.app.tar.gz
  stable/macos-desktop/
    latest.json
    Stimma_0.1.1_universal.app.tar.gz
```

### `latest.json` Format

```json
{
  "version": "0.1.5",
  "notes": "Build 0.1.5",
  "pub_date": "2026-03-26T12:00:00Z",
  "platforms": {
    "darwin-aarch64": {
      "url": "https://updates.hi.ro/artifacts/canary/macos-desktop/Stimma_0.1.5_universal.app.tar.gz",
      "signature": "<minisign signature>"
    },
    "darwin-x86_64": {
      "url": "https://updates.hi.ro/artifacts/canary/macos-desktop/Stimma_0.1.5_universal.app.tar.gz",
      "signature": "<minisign signature>"
    }
  }
}
```

## App Update Flow

### Tauri Commands (`app/src-tauri/src/main.rs`)

**`check_for_update()`** — Calls updater plugin, which hits the baked-in endpoint URL. Returns available version or null. Stashes the `Update` object in `AppState`.

**`download_and_install_update()`** — Downloads the stashed update, emitting `"update-progress"` events with `{chunkLength, contentLength}`. After download, calls `update.install(bytes)`. On next app restart, the new version launches.

### Signing & Verification

- CI signs the `.app.tar.gz` with `TAURI_SIGNING_PRIVATE_KEY` (minisign)
- The resulting `.sig` is embedded in `latest.json`
- The app verifies downloads against the public key in `tauri.conf.json`
- Apple code signing + notarization happen separately via Developer ID certificate

### Frontend UI (`AboutSection.vue`)

Update states: `idle` → `checking` → `up-to-date` | `available` → `downloading` → `restart-pending`

`auto_install` setting (in `settings.yaml`): when true, the app downloads and installs automatically after checking. When false, the user must click "Download and install".

## How to Build Each Channel

### Canary (automatic)
```bash
git push origin main   # CI builds automatically
```

### Beta
```bash
git checkout release/beta
git cherry-pick <commit>   # from main
git tag build/beta/macos-desktop/0.1
git push origin release/beta --tags
```

### Stable
```bash
git checkout release/stable
git cherry-pick <commit>   # from release/beta (usually)
git tag build/stable/macos-desktop/0.1
git push origin release/stable --tags
```

### Bumping Major.Minor
```bash
git tag build/canary/macos-desktop/1.0
git push --tags
# Next canary build will be 1.0.N
```

## Testing Updates Locally

```bash
# Terminal 1: run local update server
cd cloud/updates && npm run dev

# Terminal 2: build and test
./cloud/updates/scripts/test-updater.ts init    # build 0.1.0, install to /Applications
./cloud/updates/scripts/test-updater.ts build   # build 0.1.1, upload to local R2
# Open /Applications/Stimma.app → Settings → Check for Updates
```

Requires a dev signing key in `cloud/updates/.dev-keys/stimma-updater.key` (generate with `pnpm tauri signer generate`).

## Key Files

| File | Purpose |
|------|---------|
| `app/src-tauri/tauri.conf.json` | Base config (patched by CI) |
| `.github/workflows/build.yml` | CI pipeline |
| `cloud/updates/src/index.ts` | Update server (Cloudflare Worker) |
| `cloud/updates/wrangler.jsonc` | Worker deployment config |
| `cloud/updates/scripts/test-updater.ts` | Local update testing |
| `app/src-tauri/src/main.rs` | `check_for_update`, `download_and_install_update` |
| `app/src-tauri/icons/{canary,beta}/` | Channel-specific icon sets |
