# Docs screenshot harness

Automated documentation screenshots for docs.stimma.ai. Every shot is
reproducible: a seeded sandbox provides the content, Playwright stages the
UI, and the specs in `shots/` are the record of how each image was made.
`SHOTS.md` is the per-shot log.

## How it works

There are two sets of shots, each in its own sandbox:

- **demo** (`shots/*.spec.ts`): the seeded library and procedural demo tools
  described below. No models, no GPU.
- **fluent** (`shots/fluent/`): Tool View with Fluent against a real chat model
  and a real image tool. See [The Fluent set](#the-fluent-set).

The demo set:

- **Sandbox**: a dedicated `docs-demo` sandbox (`stimma fork`) on the debug
  bundle, ports 9300/9301. Its data dir is wherever `stimma dir` puts it
  (Application Support on macOS, the XDG data dir on Linux). Its library, collections, and markers are created by
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

### The Fluent set

```bash
scripts/docs-shots/run.sh fluent setup   # (re)create the docs-fluent sandbox and connect it
scripts/docs-shots/run.sh fluent shoot   # capture shots/fluent/ into out/
scripts/docs-shots/run.sh fluent clean   # destroy it
```

It needs a chat model and an image tool, named in `scripts/docs-shots/local.env`
(ignored by git) or the environment. Never commit real endpoints:

```bash
DOCS_SHOTS_CHAT_URL=http://localhost:8000/v1     # OpenAI-compatible endpoint
DOCS_SHOTS_CHAT_MODEL=my-chat-model              # a model it serves
DOCS_SHOTS_STP_URL=ws://localhost:8188/stp-v1    # the image tools' STP provider
DOCS_SHOTS_IMAGE_TOOL=comfyui:my-image-tool      # full tool id the shots use
DOCS_SHOTS_PEOPLE_FROM=US                        # optional: Fluent's People are from
```

Setup adds the chat model the way Settings does (it is tested on the way in),
sets every agent role to it with reasoning off, and adds the image tool's
provider. The chat model must answer plain JSON with reasoning off: a model
that writes its thinking into the reply leaves every slot as written. The
prompt in `shots/fluent/fluent.spec.ts` suits a photographic model. The sandbox
runs on ports 9310/9311 (`DOCS_SHOTS_FLUENT_BACKEND_PORT`,
`DOCS_SHOTS_FLUENT_FRONTEND_PORT`).

The set takes a few minutes: the chat model writes each slot's ideas before
the first frame, then the tool makes four images. Its shots are real model
output, so each run differs; review them before publishing. The chat-bar test
also records `out/tools/tool-assistant.webm`.

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

- Agent chats and flows built by the agent are not covered yet. The Fluent
  set's setup is the pattern for them.
- The Settings → Chat Models shot currently shows an
  unconfigured endpoint; recapture after pointing the sandbox at a local
  endpoint via an ssh tunnel (`localhost` URLs only — no hostnames).
