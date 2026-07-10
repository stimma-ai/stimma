# Stimma

![CI](https://github.com/stimma-ai/stimma/actions/workflows/ci.yml/badge.svg)

**AI-powered visual media copilot**

Stimma is a desktop application that combines intelligent media library management with an AI assistant that understands your creative workflow. Organize, search, edit, and generate visual content through natural conversation.

## What It Does

Stimma sits at the intersection of a media library and an AI-powered creative tool. Instead of switching between apps and manually orchestrating complex workflows, you describe what you want and Stimma figures out how to do it.

**Ask it things like:**
- "Upscale all the images in my favorites board"
- "Generate 5 variations of this image with different lighting"
- "Find all portraits and tag them automatically"
- "Remove the background from this photo and extend it to 16:9"
- "Create a video from this image"

The AI assistant breaks down your request into a plan, executes the steps (in parallel when possible), and shows you results along the way. You can pause, adjust, and guide the process at any point.

## Key Features

### Media Library
- Browse and organize images and videos
- Boards, tags, and custom markers
- Semantic search powered by CLIP embeddings ("find images similar to sunset over water")
- Automatic captioning and keyword extraction
- Face detection and grouping
- Trash with restore capability

### AI Assistant
- Natural language interface for media operations
- 35+ built-in tools for generation, editing, analysis, and organization
- Plan-based execution with parallel processing
- Human-in-the-loop—pause for feedback, adjust mid-flight
- Extensible via the Stimma Tools Protocol

### Generation & Editing
- Text-to-image generation
- Image and video upscaling
- Inpainting and outpainting
- Background removal and subject extraction
- Image-to-video conversion
- Prompt enhancement and crafting

### Organization
- Profiles for separate workspaces
- Saved views with custom filters
- Generation metadata tracking (prompts, models, settings)
- Auto-deletion scheduling for temporary content

## Tools

Stimma's power comes from its tool system. Tools are discrete operations the AI assistant can invoke—everything from "generate an image" to "add a tag" to "crop to a face."

### Built-in Agent Tools

These tools run inside Stimma and are always available:

| Category | Tools |
|----------|-------|
| **Generation** | text-to-image, image-to-image, generate variations |
| **Upscaling** | upscale image, upscale video, batch upscale |
| **Editing** | inpaint, outpaint, uncrop, extend canvas |
| **Extraction** | remove background, crop to face, smart crop |
| **Analysis** | score image, interrogate, detect objects, extract keywords |
| **Video** | text-to-video, image-to-video, video-to-video, video upscale |
| **Library** | add/remove tags, create board, set marker, move to trash |
| **Prompting** | enhance prompt, craft prompt, style transfer |
| **Utility** | resize, convert format, composite images |

### External Tool Providers

For GPU-intensive work like image generation, Stimma connects to external **tool providers** via the **Stimma Tools Protocol (STP)**. This lets you:

- Run ComfyUI workflows as Stimma tools
- Connect to remote GPU servers
- Use multiple providers simultaneously (route different tasks to different machines)
- Build custom providers for any backend

Providers can be local processes (stdio) or remote services (WebSocket). Each provider registers its available tools, and Stimma aggregates them into a unified interface the AI can use.

### Stimma Tools Protocol (STP)

STP is a JSON-RPC 2.0 based protocol for tool providers. Key features:

- **Tool discovery**: Providers declare their tools with JSON Schema for parameters and I/O
- **Queue management**: Providers manage their own queues; Stimma tracks status for features like "generate forever"
- **Asset transfer**: Images/videos transferred via HTTP (WebSocket) or filesystem (stdio)
- **Progress & cancellation**: Real-time progress updates and job cancellation

Example provider configuration in `config.yaml`:

```yaml
tool_providers:
  # Local ComfyUI via stdio
  - id: local-comfyui
    type: stdio
    command: python
    args: ["-m", "comfyui_provider"]

  # Remote GPU server via WebSocket
  - id: gpu-server
    type: websocket
    url: wss://gpu.example.com/stp-v1
    auth_token: ${GPU_TOKEN}
```

See the [Stimma Tools Protocol spec](https://github.com/stimma-ai/stimma-tools-protocol) for the full specification.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Tauri Shell                       │
│              (macOS / Windows / Linux)               │
├─────────────────────────────────────────────────────┤
│                                                     │
│   ┌─────────────┐           ┌─────────────────┐    │
│   │   Vue.js    │◄─────────►│  FastAPI        │    │
│   │   Frontend  │  WebSocket │  Backend        │    │
│   │             │  + REST    │                 │    │
│   └─────────────┘           ├─────────────────┤    │
│                             │  Agent System   │    │
│                             │  ┌───────────┐  │    │
│                             │  │  Planner  │  │    │
│                             │  │  Executor │  │    │
│                             │  │  35+ Tools│  │    │
│                             │  └───────────┘  │    │
│                             └────────┬────────┘    │
│                                      │             │
│                             ┌────────▼────────┐    │
│                             │    Providers    │    │
│                             │  Gemini, ComfyUI│    │
│                             │  Local models   │    │
│                             └─────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Desktop shell | Tauri 2 (Rust) |
| Frontend | Vue 3, Tailwind CSS |
| Backend | FastAPI, Python 3.11+ |
| Database | SQLite |
| ML/AI | ONNX Runtime, CLIP, LiteLLM |
| Media processing | Pillow, FFmpeg |

## Development

**Prerequisites:** Node.js 18+, Python 3.11+, Rust, uv

```bash
# Install dependencies
./setup.sh

# Run in development mode
# Terminal 1: Backend
tools/stimma dev backend

# Terminal 2: Frontend
tools/stimma dev frontend

# Terminal 3: Tauri shell (optional, for native features)
tools/stimma dev app
```

Set `STIMMA_DEV=1` to use the external backend on port 9191 instead of the bundled one.

## License

Proprietary. All rights reserved.
