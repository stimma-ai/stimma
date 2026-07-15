# Docs screenshot harness

Automated documentation screenshots for docs.stimma.ai. Every shot is
reproducible: a seeded sandbox provides the content, Playwright stages the
UI, and the specs in `shots/` are the record of how each image was made.
`SHOTS.md` is the per-shot log.

## How it works

- **Sandbox**: a dedicated `docs-demo` sandbox (`stimma fork`) on the debug
  bundle, ports 9300/9301. Its library, boards, and markers are created by
  `scripts/docs-shots/seed.py` through the normal backend API, so everything
  has real lineage.
- **Content**: `scripts/docs-shots/demo_provider.py` is a stdio STP provider
  ("ComfyUI") whose tools render deterministic procedural art — same prompt
  and seed, same image. No models, no GPU, no cloud spend.
- **Capture**: the Playwright project in this directory navigates, stages
  state (menus open, chains built, generations running), and writes PNGs to
  `out/<section>/<shot>.png`.

## Conventions

- **Light theme** (set via the sandbox config's `theme: light`; the backend
  is the source of truth for theme).
- **1480x940 viewport at deviceScaleFactor 2** — crisp retina PNGs.
- **No personal paths in frame.** The sandbox library folder lives inside the
  sandbox data dir; do not capture screens that display absolute filesystem
  paths (Settings → Folders, file-path fields) without checking the frame.

## Running

```bash
scripts/docs-shots/run.sh setup    # (re)create + seed the sandbox (~3 min)
scripts/docs-shots/run.sh shoot    # capture everything into out/
scripts/docs-shots/run.sh shoot -g "tool panel"   # one shot group
scripts/docs-shots/run.sh clean    # destroy the sandbox
```

Publishing: review `out/`, then copy keepers into
`stimma-cloud/packages/docs/src/assets/<section>/` and wire them into the
MDX pages. The docs screenshot inventory
(`stimma-cloud/packages/docs/SCREENSHOT_INVENTORY.md`) tracks which
placeholders these satisfy.

## Adding a shot

1. Add a test to the right `shots/*.spec.ts` (or a new one). Stage with
   user-visible selectors (`getByText`, `getByRole`) so specs survive
   refactors.
2. Name the output `<section>/<shot-id>` to match the docs asset path.
3. Add a row to `SHOTS.md` describing what the shot shows and any staging
   nuance.

## Known gaps

- Shots needing real LLM content (agent chats, flows built by the agent)
  are not covered yet — they need either a local endpoint or the planned
  cloud "bake" session.
- The Settings → LLM Providers shot currently shows an
  unconfigured endpoint; recapture after pointing the sandbox at a local
  endpoint via an ssh tunnel (`localhost` URLs only — no hostnames).
