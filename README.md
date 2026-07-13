# Stimma

[![CI](https://github.com/stimma-ai/stimma/actions/workflows/ci.yml/badge.svg)](https://github.com/stimma-ai/stimma/actions/workflows/ci.yml)
[![Canary](https://github.com/stimma-ai/stimma/actions/workflows/canary.yml/badge.svg)](https://github.com/stimma-ai/stimma/actions/workflows/canary.yml)

Stimma is a desktop app for making images, videos, and designs with AI, and a durable home for the work you produce along the way. It pairs a local media library — semantic search, boards, full generation lineage, repeatable flows — with an agent that can drive every tool in the app, from a single generation to a multi-step pipeline.

Generation tools plug in over the [Stimma Tools Protocol (STP)](https://github.com/stimma-ai/stimma-tools-protocol), an open JSON-RPC protocol. Your ComfyUI workflows, a provider you write yourself, and Stimma Cloud are all peers on the same protocol: the app discovers whatever tools your providers expose and builds its UI and agent capabilities from their schemas.

This repo is the app itself — every release builds from here. [AGPL-3.0](LICENSE).

## How it fits together

```
Tauri shell (macOS / Windows / Linux)
 ├─ Vue 3 frontend
 └─ FastAPI backend ── SQLite + managed media storage + external Sources
      ├─ local ML: CLIP search, face detection, segmentation (ONNX)
      ├─ agent: chat, flows, stimpacks (skills)
      └─ STP client ──► tool providers
            ├─ ComfyUI  (ComfyUI-Stimma plugin, WebSocket)
            ├─ your own provider  (stdio or WebSocket)
            └─ Stimma Cloud  (optional hosted tools + LLMs)
```

Your library is ordinary files on disk plus a per-profile SQLite database. Search, face grouping, filters, and lineage tracking run locally (ONNX weights are fetched on first use and cached). Generation runs on whichever providers you connect. The agent and captioning need an LLM — any OpenAI-compatible endpoint (vLLM, LM Studio, Ollama, ...) or Stimma Cloud.

No account is required. Source builds send no telemetry and do not check for updates. Aside from providers you choose to connect, their only automatic network contact is downloading local model weights on first use; `STIMMA_PRIVACY_LOCKDOWN=1` disables all contact with Stimma services.

## Running from source

You need **Node.js 20+**, **Python 3.11+** with [uv](https://docs.astral.sh/uv/), **Rust** (for the desktop shell), and **FFmpeg** on `PATH`. Everything goes through the dev CLI at `tools/stimma` (it self-installs Deno on first run; run it with no args for full help):

```bash
tools/stimma dev all        # backend + frontend + Tauri shell, merged logs
```

or run the pieces separately:

```bash
tools/stimma dev backend    # FastAPI on :9191, auto-reload
tools/stimma dev frontend   # Vite on :9192, HMR
tools/stimma dev app        # Tauri shell
```

Dependencies install on first run. Development uses its own data directory and config, separate from any packaged install — see [docs/DATA_DIRECTORIES.md](docs/DATA_DIRECTORIES.md).

```bash
tools/stimma test backend       # backend pytest suite
tools/stimma test acceptance    # end-to-end lane against a fresh sandbox
tools/stimma doctor assets      # read-only Asset/Media integrity audit
tools/stimma app build          # packaged app with portable backend
```

Prebuilt signed binaries are at [stimma.ai/downloads](https://stimma.ai/downloads).

## Connecting tools

Stimma ships with no bundled generation backend; you connect one or more providers and the tool catalog is whatever they declare.

**ComfyUI.** Install [ComfyUI-Stimma](https://github.com/stimma-ai/ComfyUI-Stimma) into `custom_nodes`. Drop Stimma nodes into any workflow to declare its inputs and outputs, save it, and it becomes a tool Stimma can call — the plugin serves STP over WebSocket at `/stp-v1`. Your workflows stay ordinary ComfyUI workflows; the nodes only mark what to expose.

**Your own provider.** Anything that speaks STP works, as a subprocess or a WebSocket service. The [spec](https://github.com/stimma-ai/stimma-tools-protocol) covers discovery, execution, progress, cancellation, and asset transfer; there are [Python](https://github.com/stimma-ai/stimma-tools-protocol-python) and [TypeScript](https://github.com/stimma-ai/stimma-tools-protocol-ts) SDKs that handle the plumbing, and an [`stp` CLI](https://github.com/stimma-ai/stimma-tools-protocol-cli) for poking at any provider from the command line.

**Stimma Cloud.** Hosted generation tools and LLMs over the same protocol, for when local hardware isn't enough or you want closed models. Optional; connect by signing in from the app.

Providers are configured in `config.yaml` (`tools/stimma config edit`; template in [config.default.yaml](config.default.yaml)):

```yaml
tool_providers:
  - id: comfyui
    type: websocket
    url: ws://127.0.0.1:8188/stp-v1

  - id: my-provider
    type: stdio
    command: /path/to/provider
    args: ["--serve"]
```

Multiple providers connect at once; tasks route to whichever provider offers the tool.

## Extending the agent

The agent's skills come from **stimpacks** — packages of markdown skill definitions with optional bundled Python, loaded per profile. [docs/STIMPACK_AUTHORING.md](docs/STIMPACK_AUTHORING.md) covers the format; the stock set lives in [stimma-skills](https://github.com/stimma-ai/stimma-skills) and doubles as a set of worked examples. `tools/stimma stimpacks dev` points the app at a local checkout so edits load live, and `stimpacks validate` runs the real loader against your directories.

## Repository map

| Repo | Contents |
|------|----------|
| **stimma** (this repo) | The desktop app: `frontend/` (Vue 3), `backend/` (FastAPI), `src-tauri/` (shell), `tools/stimma` (dev CLI), `docs/` |
| [stimma-tools-protocol](https://github.com/stimma-ai/stimma-tools-protocol) | The STP specification |
| [stimma-tools-protocol-cli](https://github.com/stimma-ai/stimma-tools-protocol-cli) | `stp` — command-line STP client |
| [stimma-tools-protocol-python](https://github.com/stimma-ai/stimma-tools-protocol-python) | Python SDK for building providers |
| [stimma-tools-protocol-ts](https://github.com/stimma-ai/stimma-tools-protocol-ts) | TypeScript SDK for building providers |
| [ComfyUI-Stimma](https://github.com/stimma-ai/ComfyUI-Stimma) | ComfyUI plugin: saved workflows as STP tools |
| [stimma-skills](https://github.com/stimma-ai/stimma-skills) | Stock stimpacks |

Design and reference docs are in [docs/](docs/) — data directories, release channels, stimpack authoring, agent design principles, delete behavior, and more. CI runs the quality gate (backend tests, lint, acceptance smoke) on every push to `main` and every pull request.
