# Release Channels & Updates

How desktop builds are produced, which channel they land on, and how the Tauri
updater keeps installed apps current.

## Channels

| Channel | Bundle ID | How it is built |
|---------|-----------|-----------------|
| **Production** | `ai.stimma.stimma` | Push a final `v*` tag (e.g. `v0.1.39`) |
| **Beta** | `ai.stimma.stimma.beta` | Push a `-beta.N` tag (e.g. `v0.1.0-beta.1`) |
| **Alpha** | `ai.stimma.stimma.alpha` | Push an `-alpha.N` tag (e.g. `v0.1.0-alpha.162`) |
| **Sandbox** | `ai.stimma.stimma.debug` | On-demand `build-desktop` dispatch (test builds only) |

Each channel is a separate installable app — different bundle ID, different
product name (`Stimma`, `Stimma Beta`, `Stimma Alpha`, `Stimma Debug`), different
updater feed — so multiple channels can coexist on one machine.

There is no `canary`/`stable` channel, no `main`-push auto-build, and no
release branches. Releases are driven entirely by **`v*` git tags**.

## How a release is triggered

There are exactly two ways to start a desktop build. Both are gated by the
quality gate before any platform build starts.

1. **Tag push (the real release path).** Pushing a tag matching `v*` triggers
   `.github/workflows/release.yml`. The release workflow first runs backend
   tests and acceptance tests, then fans out to the platform build workflows.
   This builds, signs, creates GitHub release assets, and publishes to the
   updater channels + Cloudflare R2.

2. **`build-desktop` dispatch (on-demand test build).** The
   `build-desktop.yml` `workflow_dispatch` workflow runs the same quality gate,
   then calls the same three platform workflows via `workflow_call`. It is meant
   for sandbox/test builds and does **not** publish unless `publish_updates` is
   explicitly set to `true`.

### Quality gate

The quality gate is `.github/workflows/quality-gate.yml` and currently requires:

- backend lint + `tools/stimma test backend -vv -rA --maxfail=1`
- browser acceptance tests via `tools/stimma test acceptance`

The normal PR/main workflow (`.github/workflows/ci.yml`) also calls this gate.

### Reusable build workflows

| Workflow | Target | Updater path segment |
|----------|--------|----------------------|
| `.github/workflows/release-macos.yml` | macOS (Apple Silicon) | `darwin-aarch64` |
| `.github/workflows/release-windows.yml` | Windows x64 | `windows-x86_64` |
| `.github/workflows/linux-appimage.yml` | Linux AppImage x64 | `linux-x86_64` |

Each platform workflow is reusable only; release tags are handled by
`.github/workflows/release.yml` so tests can gate publication:

```yaml
on:
  workflow_call:
    inputs:
      ref: { required: true, type: string }
      channel: { required: true, type: string }
      version: { required: false, type: string }
      publish_updates: { required: true, type: boolean }
      publish_github_release: { required: false, type: boolean }
```

## Channel & version derivation

### On a release tag

- **Channel** is resolved by `.github/workflows/release.yml` from the tag suffix:
  - `…-alpha.N` → `alpha`
  - `…-beta.N` → `beta`
  - otherwise → `production`

- **Version** is the tag name with the leading `v` removed. Tags must match
  `v1.2.3`, `v1.2.3-alpha.N`, or `v1.2.3-beta.N`; anything else fails the build.
  So `v0.1.39` → version `0.1.39`, channel `production`; `v0.1.0-beta.1` →
  version `0.1.0-beta.1`, channel `beta`.

### On a `build-desktop` dispatch

- **Channel** is the `channel` input (`sandbox` / `alpha` / `beta` / `production`,
  default `sandbox`).
- **Version** is the `version` input if provided, otherwise a synthetic
  `0.0.0-<channel>.<run_number>`.
- **`publish_updates`** (boolean, default `false`) gates whether artifacts are
  uploaded to R2. Sandbox test builds leave it `false`.

## What CI patches per channel

On each build the reusable workflow rewrites the Tauri config in `src-tauri/`
(`tauri.conf.json`, plus `Cargo.toml` for the version):

| Field | Set to |
|-------|--------|
| `version` | resolved version (e.g. `0.1.39`) |
| `identifier` | channel bundle ID (`ai.stimma.stimma[.beta/.alpha/.debug]`) |
| `productName` | `Stimma` / `Stimma Beta` / `Stimma Alpha` / `Stimma Debug` |
| `plugins.updater.endpoints[0]` | `${BASE}/stimma/{channel}/{target}/latest.json` |
| `plugins.updater.pubkey` | `TAURI_SIGNING_PUBLIC_KEY` |

`${BASE}` is the `STIMMA_UPDATE_BASE_URL` repo variable, defaulting to
`https://updates.stimma.ai`.

## Update server & R2 layout

Updates are served from Cloudflare R2 under `https://updates.stimma.ai`. Each
published target writes a versioned artifact directory plus a channel-level
`latest.json` that the Tauri updater polls:

```
stimma/{channel}/{target}/latest.json          ← updater feed (per channel+target)
stimma/{channel}/{target}/{version}/...         ← versioned, immutable artifacts
```

For example:

```
stimma/production/darwin-aarch64/latest.json
stimma/production/darwin-aarch64/0.1.39/Stimma_0.1.39_aarch64.app.tar.gz
stimma/beta/windows-x86_64/latest.json
stimma/alpha/linux-x86_64/0.1.0-alpha.162/...
```

Targets are `darwin-aarch64`, `windows-x86_64`, and `linux-x86_64`.

### `latest.json` format

```json
{
  "version": "0.1.39",
  "notes": "...",
  "pub_date": "2026-06-04T21:00:00Z",
  "platforms": {
    "darwin-aarch64": {
      "signature": "<minisign signature>",
      "url": "https://updates.stimma.ai/stimma/production/darwin-aarch64/0.1.39/Stimma_0.1.39_aarch64.app.tar.gz"
    }
  }
}
```

Each target's `latest.json` carries its own platform entry; the workflow merges
into any existing channel `latest.json` so other targets' entries are preserved.

## Signing

- The updater archive is signed with `TAURI_SIGNING_PRIVATE_KEY` (minisign); the
  `.sig` value is embedded in `latest.json` and verified client-side against the
  `pubkey` baked into the Tauri config.
- macOS builds additionally Apple-code-sign + notarize when
  `vars.ENABLE_APPLE_SIGNING == 'true'` (Developer ID cert + Apple ID secrets).

## How to cut each release

### Production

```bash
git tag v0.1.39
git push origin v0.1.39
```

### Beta

```bash
git tag v0.1.0-beta.1
git push origin v0.1.0-beta.1
```

### Alpha

```bash
git tag v0.1.0-alpha.162
git push origin v0.1.0-alpha.162
```

### Sandbox / test build (no publish)

Use the `build-desktop` workflow dispatch — this runs the full build on the
self-hosted runners after the quality gate, without publishing to real updater
channels:

```bash
gh workflow run build-desktop.yml \
  -f ref=main -f channel=sandbox -f version='' -f publish_updates=false
```

Set `publish_updates=true` (and a real `channel`) only if you intend to publish
a hand-rolled build to R2.

## Key files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | PR/main CI entrypoint |
| `.github/workflows/quality-gate.yml` | Reusable backend + acceptance test gate |
| `.github/workflows/release.yml` | Tag-triggered release orchestrator; runs the quality gate before fan-out |
| `.github/workflows/build-desktop.yml` | On-demand dispatcher; runs the quality gate before fan-out |
| `.github/workflows/release-macos.yml` | macOS build/sign/publish reusable |
| `.github/workflows/release-windows.yml` | Windows build/sign/publish reusable |
| `.github/workflows/linux-appimage.yml` | Linux AppImage build/sign/publish reusable |
| `src-tauri/tauri.conf.json` | Base Tauri config (version / identity / updater patched by CI) |
| `src-tauri/Cargo.toml` | Crate version (patched by CI) |
