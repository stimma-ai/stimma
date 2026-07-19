# Release Channels & Updates

How desktop builds are produced, which channel they land on, and how the Tauri
updater keeps installed apps current.

## Channels

| Channel | Bundle ID | How it is built |
|---------|-----------|-----------------|
| **Production** | `ai.stimma.stimma` | `stimma tag beta` a version, verify it, then `stimma promote production` |
| **Beta** | `ai.stimma.stimma.beta` | `stimma tag beta [X.Y.Z]` tags the next beta of the upcoming production version |
| **Canary** | `ai.stimma.stimma.canary` | Automatic — every push to `main` (`.github/workflows/canary.yml`) |
| **Debug** | `ai.stimma.stimma.debug` | On-demand `build-desktop` dispatch (test builds only), or local dev |

Each channel is a separate installable app — different bundle ID, different
product name (`Stimma`, `Stimma Beta`, `Stimma Canary`, `Stimma Debug`), different
updater feed — so multiple channels can coexist on one machine.

Official builds check their updater feed once at startup and then on a
channel-specific schedule: canary every 15 minutes, beta and production every
6 hours. Automatic updates on macOS and Linux are installed in the background
and take effect on restart; if another release lands while the app remains
open, the newer package is installed over the previously staged package.
Manual update mode disables scheduled checks. Debug/source builds normally
have no updater endpoint and therefore do not schedule checks.

There is no `alpha` channel and no `stimma tag alpha`/`stimma tag canary`/
`stimma tag production` commands — the CLI rejects all three. Canary is a
continuous build off `main`, not tag-driven. Production is never tagged
directly; it is a **promotion** of a beta commit that has already been tested.

## How a release is triggered

There are four ways a desktop build gets produced. All are gated by the
quality gate before any platform build starts (except an explicit emergency
bypass, see below).

1. **Push to `main` (canary — automatic).** Every push to `main` triggers
   `.github/workflows/canary.yml`. It computes a synthetic version
   (`<next-patch>-canary.<commit-count>`), runs the quality gate, then builds
   and publishes a macOS build to the canary updater feed. This is the
   fastest signal for "does `main` still work" and requires no manual step.

2. **`stimma tag beta [X.Y.Z]` (the real release path).** Tags the current
   commit as the next beta of the upcoming production version — pushing a
   `v*-beta.N` tag triggers `.github/workflows/release.yml`. The release
   workflow first runs the quality gate, then fans out to the three platform
   build workflows. This builds, signs, creates GitHub release assets, and
   publishes to the beta updater channel + Cloudflare R2.

3. **`stimma promote production [--ref REF]`.** Promotes the latest beta's
   commit (or an explicit `--ref` for a hotfix) to a production release by
   tagging it `vX.Y.Z` and pushing that tag, which also triggers
   `.github/workflows/release.yml`. Production tags always require the beta
   to be strictly ahead of the currently shipped production version.

4. **`build-desktop` dispatch (on-demand test build).** The
   `build-desktop.yml` `workflow_dispatch` workflow runs the same quality
   gate, then calls the same three platform workflows via `workflow_call`.
   It is meant for sandbox/test builds and does **not** publish unless
   `publish_updates` is explicitly set to `true`.

### Quality gate

The quality gate is `.github/workflows/quality-gate.yml` and currently requires:

- backend lint + `tools/stimma test backend -vv -rA --maxfail=1`
- browser acceptance tests via `tools/stimma test acceptance` (the smoke lane
  by default; `acceptance_suite=full` runs the full suite)

The normal PR/main workflow (`.github/workflows/ci.yml`) also calls this gate.
Both `release.yml` and `build-desktop.yml` support `skip_quality_gate` as an
emergency `workflow_dispatch` bypass.

### Reusable build workflows

| Workflow | Target | Updater path segment |
|----------|--------|----------------------|
| `.github/workflows/release-macos.yml` | macOS (Apple Silicon) | `darwin-aarch64` |
| `.github/workflows/release-windows.yml` | Windows x64 | `windows-x86_64` |
| `.github/workflows/linux-appimage.yml` | Linux AppImage x64 and arm64 | `linux-x86_64` / `linux-aarch64` |

Each platform workflow is reusable only; release tags are handled by
`.github/workflows/release.yml` and canary builds by
`.github/workflows/canary.yml`, so tests can gate publication:

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

Canary builds only run the macOS reusable workflow (`publish_github_release:
false`) — canary is meant for fast macOS-only signal, not a full
cross-platform release. Beta and production releases fan out to macOS,
Windows, and both Linux AppImage architectures.

## Channel & version derivation

### On a release tag

- **Channel** is resolved by `.github/workflows/release.yml` from the tag name:
  - `v1.2.3-beta.N` → `beta`
  - `v1.2.3` → `production`
  - anything else fails the build (`Release refs must be tags like v1.2.3 or
    v1.2.3-beta.1.`) — there is no `-alpha.N` or `-canary.N` tag form.

- **Version** is the tag name with the leading `v` removed. So `v0.1.39` →
  version `0.1.39`, channel `production`; `v0.1.0-beta.1` → version
  `0.1.0-beta.1`, channel `beta`.

### On a canary push

- **Channel** is always `canary`.
- **Version** is computed in `canary.yml`: the next patch above the latest
  `vX.Y.Z` production tag, suffixed with `-canary.<commit-count>` (e.g.
  `0.1.40-canary.842`).

### On a `build-desktop` dispatch

- **Channel** is the `channel` input (`sandbox` / `canary` / `beta` /
  `production`, default `sandbox`). `sandbox` (like any unrecognized value)
  resolves to the debug bundle ID at build time.
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
| `identifier` | channel bundle ID (`ai.stimma.stimma[.beta/.canary/.debug]`) |
| `productName` | `Stimma` / `Stimma Beta` / `Stimma Canary` / `Stimma Debug` |
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
stimma/canary/darwin-aarch64/0.1.40-canary.842/...
```

Targets are `darwin-aarch64`, `windows-x86_64`, `linux-x86_64`, and
`linux-aarch64`.

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
Publish also refuses to move a channel's own `latest.json` backward: it parses
the candidate version and the currently published version and skips the
publish if the candidate sorts lower (by core `X.Y.Z`, then channel, then
pre-release number).

## Signing

- The updater archive is signed with `TAURI_SIGNING_PRIVATE_KEY` (minisign); the
  `.sig` value is embedded in `latest.json` and verified client-side against the
  `pubkey` baked into the Tauri config.
- macOS builds additionally Apple-code-sign + notarize when
  `vars.ENABLE_APPLE_SIGNING == 'true'` (Developer ID cert + Apple ID secrets).

## How to cut each release

### Beta

```bash
stimma tag beta            # tags v<next-patch>-beta.<N> from HEAD
stimma tag beta 0.2.0      # explicit version instead of auto-derived next patch
```

The beta train always carries the next production version — if a newer
production release ships, the next `stimma tag beta` (with no explicit
version) automatically rebases onto the version after that.

### Production

```bash
stimma promote production            # promotes the latest beta's commit
stimma promote production --ref REF  # hotfix: promote an explicit git ref
stimma promote production --yes      # skip the confirmation prompt (needed non-interactively)
```

This requires at least one beta tag ahead of the current production version;
it fails with a clear error otherwise. It tags the resolved commit `vX.Y.Z`
and pushes it, which triggers the same `release.yml` flow as a beta tag.

### Canary

Nothing to run — canary builds automatically on every push to `main`. To
force a canary build of a specific ref without waiting for a push, dispatch
the workflow directly:

```bash
gh workflow run canary.yml -f ref=main
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
| `tools/stimma` (`stimma tag beta` / `stimma promote production`) | The only supported way to cut beta and production releases |
| `.github/workflows/ci.yml` | PR/main CI entrypoint |
| `.github/workflows/quality-gate.yml` | Reusable backend + acceptance test gate |
| `.github/workflows/canary.yml` | Push-to-`main` canary build (macOS only, auto-triggered) |
| `.github/workflows/release.yml` | Tag-triggered release orchestrator (beta/production); runs the quality gate before fan-out |
| `.github/workflows/build-desktop.yml` | On-demand dispatcher; runs the quality gate before fan-out |
| `.github/workflows/release-macos.yml` | macOS build/sign/publish reusable |
| `.github/workflows/release-windows.yml` | Windows build/sign/publish reusable |
| `.github/workflows/linux-appimage.yml` | Linux AppImage build/sign/publish reusable (x64 + arm64) |
| `src-tauri/tauri.conf.json` | Base Tauri config (version / identity / updater patched by CI) |
| `src-tauri/Cargo.toml` | Crate version (patched by CI) |
