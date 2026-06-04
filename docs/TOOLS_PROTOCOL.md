# Stimma Tools Protocol (STP)

**Version:** 1.0-draft4
**Status:** Draft

A JSON-RPC 2.0 protocol for exposing image/video generation tools to applications, designed to make
those tools legible to both software agents and human-facing UIs.

---

## Overview

STP defines two roles:

- **Provider** — an external process that exposes generation tools (image generation, video
  upscaling, etc.) and executes them. A provider may be a local subprocess or a remote service.
- **Host** — the application that connects to providers, routes execution requests, and surfaces
  the aggregated tools to its users. The host is the consumer of the protocol.

> Throughout this document, "the host" refers to whatever application is driving the protocol.
> [Stimma](https://stimma.ai) is the reference host, but STP is host-agnostic — any application can
> implement the host side.

Each provider manages its own set of tools and executes them independently. The host routes requests
to providers and aggregates their tools into a unified interface.

This document specifies the **wire protocol**: the messages peers exchange, their fields, their
sequencing, and what a conformant peer does with them. It does not prescribe how an implementation
is built — bind addresses, command-line interfaces, configuration formats, queue internals, and UI
rendering are implementation choices, not protocol.

---

## Conventions and Terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHOULD**, **SHOULD NOT**,
**RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted as described in
RFC 2119 and RFC 8174 when, and only when, they appear in all capitals.

| Term | Meaning |
|------|---------|
| **Provider** | A process that exposes and executes tools (the protocol *server* role). |
| **Host** | The application that connects to providers and consumes their tools (the protocol *client* role). |
| **Tool** | A single executable operation a provider exposes, described by a tool descriptor. |
| **Task type** | A category a tool belongs to (e.g. `text-to-image`) that carries shared UI and routing conventions. |
| **Session** | The lifetime of one provider connection, from registration to disconnect. Assets are scoped to a session. |
| **Asset** | A binary payload (image, video, weights) transferred out-of-band and referenced in messages by an opaque asset ID. |

---

## Transport

### WebSocket Transport

A provider runs a WebSocket server; the host connects to it:

```
ws://<provider-host>:port/stp-v1
wss://<provider-host>:port/stp-v1  (TLS)
```

- Messages are JSON-RPC 2.0 formatted text frames
- Keep messages small - no binary data in JSON
- Assets transferred via separate HTTP endpoints (see Asset Management)
- Optional bearer token authentication (see Authentication)

### Stdio Transport

The host spawns the provider as a child process:

- Messages sent as newline-delimited JSON on stdin/stdout
- One complete JSON-RPC message per line
- stderr reserved for provider logging (not parsed by the host)
- Assets transferred via shared filesystem directory (see Asset Management)

---

## Authentication

A WebSocket provider MAY require a bearer token. The token is a shared secret known to the host and
provider out of band.

When a provider requires a token, that single credential gates the **entire** provider — both the
WebSocket control channel and the HTTP asset channel:

- The host MUST send `Authorization: Bearer <token>` on the WebSocket upgrade and on every HTTP
  asset request.
- The provider MUST reject unauthenticated requests on **either** channel.

```
GET /stp-v1 HTTP/1.1               PUT /assets/abc123.png
Authorization: Bearer <token>      Authorization: Bearer <token>
Upgrade: websocket                 Content-Type: image/png
```

A provider MAY omit authentication when both peers share a mutually trusted channel, such as loopback
or the stdio transport.

---

## Provider Configuration (informative)

How a host is told which providers to connect to is outside the protocol — each host defines its own
configuration. The following is the reference host's format, shown only to make the two transports
concrete:

```yaml
tool_providers:
  # Stdio provider - the host spawns and manages the process
  - id: local-comfyui
    type: stdio
    command: python
    args: ["-m", "comfyui_provider"]
    working_dir: /path/to/provider
    env:
      CUDA_VISIBLE_DEVICES: "0"

  # WebSocket provider - connects to external service
  - id: remote-gpu-server
    type: websocket
    url: wss://gpu-server.example.com/stp-v1
    auth_token: ${GPU_SERVER_TOKEN}  # from environment
    reconnect_delay: 5  # seconds, exponential backoff

  # Local WebSocket provider (no auth needed)
  - id: local-service
    type: websocket
    url: ws://127.0.0.1:8188/stp-v1
```

**Stdio options:**
- `command`: Executable to run
- `args`: Command line arguments
- `working_dir`: Working directory for process
- `env`: Additional environment variables

**WebSocket options:**
- `url`: WebSocket endpoint URL
- `auth_token`: Optional bearer token (can use `${ENV_VAR}` syntax)
- `reconnect_delay`: Base delay for reconnection attempts (exponential backoff)

---

## Asset Management

Assets (images, videos) are transferred out-of-band, not embedded in JSON messages.

### WebSocket: HTTP Asset Endpoints

The **provider** hosts an HTTP asset server. During registration, the provider includes `asset_endpoint` to tell the host where to upload/download assets:

- **Relative path** (e.g., `/assets`): Same origin as WebSocket connection
- **Absolute URL** (e.g., `https://cdn.example.com/assets`): Different server (for cloud deployments)

The host constructs full URLs:

```
PUT    {asset_endpoint}/{asset_id}    # Upload input asset to provider
GET    {asset_endpoint}/{asset_id}    # Download output asset from provider
DELETE {asset_endpoint}/{asset_id}    # Delete asset
```

**Example with relative path:**
If WebSocket is `ws://localhost:8188/stp-v1` and `asset_endpoint` is `/assets`:

```http
PUT http://localhost:8188/assets/abc123.png
Content-Type: image/png

<binary data>
```

**Example with absolute URL:**
If `asset_endpoint` is `https://my-gpu-server.example.com/assets`:

```http
GET https://my-gpu-server.example.com/assets/xyz789.png
Authorization: Bearer <token>

Response:
Content-Type: image/png
<binary data>
```

#### Asset ID grammar (normative)

The uploader chooses the asset ID. An asset ID MUST match:

```
^[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9]{1,12}$
```

A receiver MUST reject an asset ID that does not match before using it to build a filesystem path or
URL.

**Lifecycle (normative):**
- Assets are **owned by the session** that created them.
- **Inputs:** the host `PUT`s the input; the provider MAY delete it once the job reaches a terminal
  result.
- **Outputs:** the provider creates the output; the host `GET`s it, then SHOULD `DELETE` it.
- **Retention floor:** a provider **MUST retain an output asset until the earlier of** (an explicit
  `DELETE`, session end) **and MUST NOT evict an output asset younger than 5 minutes.** This
  guarantees the host a window to fetch results.
- **`DELETE` is idempotent:** deleting a missing asset succeeds (no-op).
- When the session ends, the provider deletes all of the session's assets.

### Stdio: Filesystem Assets

When using stdio transport, the host sets environment variable:

```
ASSET_PATH=/path/to/temp/assets
```

Asset IDs are flat names (per the grammar above) within this directory — never paths. Both the host and provider read/write directly:

```python
asset_path = os.environ["ASSET_PATH"]

# the host writes input
open(f"{asset_path}/abc123.png", "wb").write(image_data)

# Provider reads input
image = open(f"{asset_path}/abc123.png", "rb").read()

# Provider writes output
open(f"{asset_path}/xyz789.png", "wb").write(result_data)
```

**Lifecycle:**
- The host creates and cleans up the asset directory
- Directory deleted when provider process exits

---

## Connection Lifecycle

### 1. Provider Registration

On connect, provider sends `provider.register`:

```json
{
  "jsonrpc": "2.0",
  "method": "provider.register",
  "params": {
    "stp_version": "1.0",
    "provider_id": "my-comfyui-server",
    "provider_name": "My ComfyUI Server",
    "server": "ComfyUI-Stimma/1.2.3",
    "max_concurrent": 2,
    "asset_endpoint": "/assets",
    "capabilities": {
      "cancel": true
    }
  },
  "id": 1
}
```

Registration fields:

| Field | Required | Description |
|-------|----------|-------------|
| `stp_version` | yes | Protocol version this provider speaks (e.g. `"1.0"`). Distinct from the provider software version. See [Versioning](#versioning--capabilities). |
| `provider_id` | yes | Stable identifier for this provider. Unique within a host's configuration; forms the first half of a tool's global address (`{provider_id}:{tool_id}`). |
| `provider_name` | yes | Human-readable display name (may be user-customized). |
| `server` | no | Software identifier in HTTP `Server`-header style: `Name/Version` (e.g. `"ComfyUI-Stimma/1.2.3"`). For telemetry and debugging only; the provider is the server, so this is the `Server` analog (not `User-Agent`). Implementor-filled. |
| `max_concurrent` | no | Provider-wide concurrency limit (default `1`). |
| `asset_endpoint` | no | Where the host uploads/downloads assets (see below). Omitted for stdio. |
| `capabilities` | no | Optional features this provider supports beyond the baseline. A provider that omits `capabilities` supports only the baseline. See [Versioning](#versioning--capabilities). |

The `asset_endpoint` tells the host where to upload/download assets:
- **Relative path** (e.g., `/assets`): Use same origin as WebSocket connection
- **Absolute URL** (e.g., `https://cdn.example.com/assets`): Use a different server. The host trusts
  the provider-supplied URL as-is.
- **Omitted**: For stdio transport (use `ASSET_PATH` env var instead)

The host responds with session info, echoing its own protocol version and capabilities:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "session_id": "abc123",
    "stp_version": "1.0",
    "host_version": "1.0.0",
    "capabilities": {}
  },
  "id": 1
}
```

### 2. Tool Discovery

After registration, the host calls `tools.list`:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.list",
  "params": {},
  "id": 2
}
```

Provider responds with an array of [tool descriptors](#tool-descriptor):

```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [ /* one or more tool descriptors */ ]
  },
  "id": 2
}
```

See [Appendix A](#appendix-a-example-tool-descriptor) for a complete, realistic descriptor.

**LoRAs in parameter_schema:** available LoRAs are listed in the `enum` of the tool's `loras.items.properties.path`, already filtered to the model family, so a client can offer LoRA selection without a separate call.

### 3. Tool Refresh

The host can request an updated tool list with `tools.refresh`. This triggers the provider to re-query its backend. The response format is identical to `tools.list`.

```json
{
  "jsonrpc": "2.0",
  "method": "tools.refresh",
  "params": {},
  "id": 3
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [...]
  },
  "id": 3
}
```

### 4. Disconnection

Either side can disconnect gracefully:

```json
{
  "jsonrpc": "2.0",
  "method": "provider.disconnect",
  "params": { "reason": "shutdown" }
}
```

No response expected. Connection closes immediately.

---

## Versioning & Capabilities

STP versions through two independent mechanisms:

### Protocol version (`stp_version`)

`stp_version` is the version of *the protocol* a peer speaks (e.g. `"1.0"`), exchanged in
`provider.register` and the registration response. It is distinct from the provider *software*
version (`server`) and from `host_version`.

- The major component (`1` in `1.0`) is also pinned in the WebSocket path (`/stp-v1`).
- The path changes **only** for a backward-incompatible major bump. Backward-compatible changes ride
  the `stp_version` minor and the capabilities object.
- A peer MAY refuse to proceed if it cannot speak the other side's major version.

### Capabilities

`capabilities` advertises optional features a peer supports. A key is present and `true` only when
the peer supports that feature; an absent key means it does not. Both peers send a `capabilities`
object — the provider in `provider.register`, the host in the registration response.

Defined capabilities:

| Capability | Type | Meaning |
|------------|------|---------|
| `cancel` | `bool` | Provider honors `tools.cancel` for queued and in-progress jobs. |

Later revisions add optional features as additional keys.

**Vendor-specific capabilities** use the `x-<vendor>-<feature>` convention (see [Extensions and
Vendor Namespacing](#extensions-and-vendor-namespacing)) and MUST be ignorable by peers that don't
recognize them.

---

## Queue Management

Providers manage their own internal queue. The host tracks queue state via notifications.

### Queue Status Notification

Provider sends `queue.status` whenever queue state changes:

```json
{
  "jsonrpc": "2.0",
  "method": "queue.status",
  "params": {
    "queued": 3,
    "running": 2,
    "capacity": 2
  }
}
```

Fields:
- `queued`: Jobs waiting to start
- `running`: Jobs currently executing
- `capacity`: Max concurrent executions (same as `max_concurrent` from registration)

**When to send:**
- After accepting a new job
- When a job starts executing
- When a job completes or fails
- When a job is cancelled

`queue.status` gives the host a live view of provider load.

---

## Tool Execution

### Execute Request

The host sends `tools.execute`:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.execute",
  "params": {
    "request_id": "job-456",
    "tool_id": "flux-dev:text-to-image",
    "parameters": {
      "prompt": "a cat wearing a hat",
      "negative_prompt": "blurry, low quality",
      "steps": 30,
      "cfg": 7.5,
      "width": 1024,
      "height": 1024,
      "seed": 12345
    }
  },
  "id": 10
}
```

Provider acknowledges immediately (job is queued):

```json
{
  "jsonrpc": "2.0",
  "result": { "accepted": true },
  "id": 10
}
```

Provider then sends `queue.status` to reflect the new job.

### Progress Notifications

Provider sends progress updates as notifications (no `id`):

```json
{
  "jsonrpc": "2.0",
  "method": "tools.progress",
  "params": {
    "request_id": "job-456",
    "progress": 0.5
  }
}
```

Fields:
- `progress`: 0.0 to 1.0

### Result Notification

When complete, provider sends result with asset reference:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.result",
  "params": {
    "request_id": "job-456",
    "success": true,
    "output": {
      "assets": [
        { "asset_id": "xyz789.png", "type": "image", "role": "primary" }
      ]
    },
    "metadata": {
      "actual_seed": 12345,
      "generation_time": 28.5
    }
  }
}
```

The host retrieves each output asset via HTTP GET to the provider's asset endpoint (WebSocket) or filesystem read (stdio).

**Asset flow for jobs with input images:**
1. Before sending `tools.execute`, the host uploads input images to the provider via HTTP PUT
2. The execute request carries the input asset IDs in `parameters` (e.g. `"input_images": ["abc123.png"]`)
3. Provider reads input assets from its local storage
4. Provider generates outputs and stores them locally
5. Provider sends the result listing the output assets
6. The host downloads each output asset via HTTP GET

On failure:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.result",
  "params": {
    "request_id": "job-456",
    "success": false,
    "error": {
      "code": "OUT_OF_MEMORY",
      "message": "GPU ran out of memory"
    }
  }
}
```

After sending result, provider sends `queue.status` to reflect completion.

### Cancellation

The host can cancel jobs (queued or in-progress):

```json
{
  "jsonrpc": "2.0",
  "method": "tools.cancel",
  "params": { "request_id": "job-456" },
  "id": 11
}
```

Provider responds:

```json
{
  "jsonrpc": "2.0",
  "result": { "cancelled": true },
  "id": 11
}
```

If already complete or unknown:

```json
{
  "jsonrpc": "2.0",
  "result": { "cancelled": false, "reason": "already_complete" },
  "id": 11
}
```

After cancellation, provider sends `queue.status`.

---

## Schema Definitions

### Tool Descriptor

```typescript
interface ToolDescriptor {
  // Unique ID within this provider (e.g., "flux-dev:text-to-image")
  id: string;

  // Human-readable name
  name: string;

  // All task types this tool supports (first is primary). Tools declaring
  // multiple types appear in multiple UI categories.
  // Example: ["text-to-image", "image-to-image"] for tools that work both ways
  task_types: string[];

  // JSON Schema for ALL tool parameters — prompts, media inputs (images,
  // videos, mask), resolution, seed, and tuning knobs (steps, cfg, loras, …)
  // all live here in a single namespace.
  parameter_schema: JSONSchema;

  // JSON Schema for outputs
  output_schema: JSONSchema;

  // UI layout for grouping parameters into sections (optional)
  layout?: LayoutSection[];

  // Human-readable short description (shown in tool cards)
  subtitle?: string;

  // Longer description (also shown in tool cards, used as subtitle fallback)
  description?: string;

  // Provider-specific metadata (optional, see Metadata Fields below)
  metadata?: Record<string, any>;
}

interface LayoutSection {
  // Section title (e.g., "Advanced", "Video Settings")
  label: string;

  // Parameters in this section
  params: LayoutParam[];

  // Whether the section starts collapsed (default: false)
  collapsed?: boolean;
}

interface LayoutParam {
  // Parameter name (must match a key in parameter_schema)
  name: string;

  // Span full width of the layout container
  full_width?: boolean;

  // Conditional visibility: show only when another param has a specific value
  visible_when?: { param: string; value: any };
}
```

**Recognized Task Types:**

| Task Type | Display Label | Description |
|-----------|---------------|-------------|
| `text-to-image` | Generate Image | Create image from text prompt |
| `image-to-image` | Image to Image | Transform/edit existing image |
| `image-to-video` | Image to Video | Animate an image |
| `text-to-video` | Generate Video | Create video from text prompt |
| `video-stitch` | Video Stitch | Combine video segments |
| `video-extend` | Video Extend | Extend video duration |
| `upscale-image` | Upscale Image | Increase image resolution |
| `upscale-video` | Upscale Video | Increase video resolution |
| `inpaint-image` | Inpaint | Fill masked region of image |
| `remove-background` | Background Removal | Remove image background |

An application MAY act on a recognized task type, but SHOULD handle unrecognized task types generically.

**Multi-Task Type Support:**

Tools declare their task types using the `task_types` array. This is useful for tools that can operate in multiple modes (e.g., both text-to-image generation and image editing).

- `task_types` is required and is the single source of truth for a tool's categories.
- Tools must validate against the schema requirements of ALL declared task types
- Unknown task types in the array are filtered out with a warning
- The first entry is the "primary" task type

The descriptor in [Appendix A](#appendix-a-example-tool-descriptor) declares
`["text-to-image", "image-to-image"]` and switches modes based on whether `input_images` is provided.

### Metadata Fields

The `metadata` object is freeform. The following keys are standard; hosts SHOULD honor them and MAY ignore the rest:

| Key | Type | Description |
|-----|------|-------------|
| `description` | `string` | Tool description shown in the All Tools page. Used as `subtitle` fallback if `subtitle` is not set at the top level. |
| `display_price` | `string` | Price string shown in tool cards (e.g., `"$0.03/megapixel"`, `"$0.05/second"`). |
| `badges` | `string[]` | Badge labels shown as pills in tool cards. Use standard labels for consistent styling (see below). |

**Standard badge labels:**

| Badge | Meaning | UI Color |
|-------|---------|----------|
| `Fast` | Optimized for speed | Yellow |
| `Highest Quality` | Best quality output | Purple |
| `HD` | High definition output | Purple |
| `Commercial Use` | Commercially licensable output | Blue |
| `Open Weights` | Open-source model weights | Teal |
| `New` | Recently added | Green |
| `Beta` / `Experimental` | Not production-ready | Orange |

Custom badge strings are also supported and rendered with neutral styling.

**Example tool with metadata:**

```json
{
  "id": "my-model:text-to-image",
  "name": "My Model",
  "description": "High-quality image generation using My Model",
  "task_types": ["text-to-image"],
  "metadata": {
    "description": "High-quality image generation using My Model",
    "display_price": "$0.05/megapixel",
    "badges": ["Fast", "Open Weights"]
  },
  "parameter_schema": { ... },
  "output_schema": { ... }
}
```

### Parameter Schema

Standard JSON Schema with optional `x-` prefixed extensions for UI hints.

#### UI Control Types (`x-control`)

Every schema property MAY declare an `x-control` hint specifying which UI control should render it. If omitted, a client SHOULD infer the control from the JSON Schema type.

| `x-control` value | Schema type | Description | Additional hints |
|--------------------|-------------|-------------|------------------|
| `prompt_editor` | `string` | Rich text editor with syntax highlighting | — |
| `textarea` | `string` | Multi-line plain text input | — |
| `slider` | `number`, `integer` | Range slider | `x-step`, `minimum`, `maximum` |
| `dropdown` | `string` | Dropdown/select from `enum` values | `x-enum-labels` for display names |
| `checkbox` | `boolean` | Toggle checkbox | — |
| `seed` | `integer` | Random seed with dice/lock controls | — |
| `image_picker` | `array` of strings | Image upload/selection | `x-min-items`, `x-max-items`, `x-controlnet` |
| `video_picker` | `array` of strings | Video upload/selection | `x-min-items`, `x-max-items` |
| `video_frame_picker` | `array` of strings | Start/end frame picker for image-to-video | `x-min-items`, `x-max-items` |
| `mask_editor` | `string` | Mask painting editor | `x-source-field`, `x-mask-format` |
| `resolution` | `integer` | Linked resolution field (see Resolution Picker) | `x-paired-with`, `x-step` |
| `upscale_resolution` | `number` or `integer` | Upscale scale factor / target resolution picker | `x-step` |
| `lora_picker` | `array` of objects | LoRA pool picker — array of `{path, weight}` with an `enum` on `path` | — |

If a client encounters an unknown `x-control` value, it SHOULD fall back to a generic input appropriate for the schema type (text input for strings, number input for numbers, etc.).

#### Common `x-*` Extension Properties

| Hint | Used With | Type | Description |
|------|-----------|------|-------------|
| `x-control` | Any property | `string` | UI control type (see table above) |
| `x-label` | Any property | `string` | Display label override (default: auto-generated from field name) |
| `x-step` | Sliders, resolution | `number` | Step value for numeric inputs |
| `x-enum-labels` | Dropdowns | `Record<string, string>` | Maps enum values to display labels |
| `x-format` | Any property | `string` | Display formatting hint (e.g., `"filename"`, `"percent"`) |
| `x-visible-when` | Any property | `{ param, value }` | Conditional visibility based on another parameter |
| `x-hidden` | Any property | `boolean` | Hide from UI entirely |
| `x-source-field` | `mask_editor` | `string` | Which input field contains the source image |
| `x-mask-format` | `mask_editor` | `string` | Output format for mask images (see below) |
| `x-controlnet` | `image_picker` | `string[]` | ControlNet preprocessor IDs (see below) |
| `x-allow-prep` | `image_picker` | `boolean` | Allow a client to offer input-image editing (resize, extend, paint) before sending. Default `false`. Implicitly `true` when `x-controlnet` is present. |
| `x-paired-with` | `resolution` | `string` | Declares this field is paired with another (see Resolution Picker) |
| `x-allowed-values` | Sliders | `number[]` | Fixed discrete values — a client SHOULD render a constrained selector instead of a free slider |
| `x-allowed-dimensions` | `resolution` | `[number, number][]` | Constrained width/height pairs (e.g., for models with fixed output sizes) |
| `x-min-items` | Arrays | `number` | Minimum items for media inputs |
| `x-max-items` | Arrays | `number` | Maximum items for media inputs |
| `x-accept-upload` | `string` with `enum` | `object` | Declares file upload capability (see Tool File Uploads) |

**Mask Formats (`x-mask-format`):**

When `x-control: "mask_editor"`, the `x-mask-format` hint specifies how the mask image should be encoded:

| Value | Inpaint Area | Preserve Area | Notes |
|-------|--------------|---------------|-------|
| `alpha` (default) | alpha=0, RGB=white | alpha=255, RGB=black | Used by ComfyUI workflows |
| `white-black` | white (255,255,255), alpha=255 | black (0,0,0), alpha=255 | Used by Runware, some cloud APIs |
| `black-white` | black (0,0,0), alpha=255 | white (255,255,255), alpha=255 | Inverse of above |

Example mask parameter with explicit format:

```json
{
  "mask": {
    "type": "string",
    "title": "Mask",
    "description": "Mask image for inpainting",
    "x-control": "mask_editor",
    "x-source-field": "input_image",
    "x-mask-format": "white-black"
  }
}
```

**ControlNet Preprocessing (`x-controlnet`):**

When `x-controlnet` is present on an `input_image` / `input_images` property, a client SHOULD let the user choose one of the listed preprocessors and apply it to the input. The preprocessed control map (canny edges, depth map, etc.) replaces the original image in the input, so the tool receives the control map in its place.

Available preprocessor IDs:

| ID | Name | Description |
|----|------|-------------|
| `canny` | Canny Edge | Edge detection using OpenCV Canny |
| `depth` | Depth Map | Monocular depth estimation using Depth Anything V2 |
| `lineart` | Line Art | Line extraction using adaptive threshold |
| `pose` | Pose | Body skeleton using DWPose |

Example input_image with controlnet options:

```json
{
  "input_image": {
    "type": "string",
    "format": "file-path",
    "title": "Control Image",
    "x-controlnet": ["canny", "depth", "lineart", "pose"]
  }
}
```

Only list the preprocessors that make sense for your tool. For example, a tool that only supports edge-guided generation should use `"x-controlnet": ["canny", "lineart"]`.

**Input Image Prep (`x-allow-prep`):**

By default an input image is treated as opaque and passed to the tool unchanged. Setting
`"x-allow-prep": true` on an `input_image` / `input_images` property signals that the tool accepts a
user-modified input, so a client MAY offer editing controls — such as resizing, canvas extension, or
painting over the image — before it is sent.

Set it on tools that transform an image into a generated output (edit, outpaint, image-to-image).
Omit it where the input is only a reference and editing would be meaningless — e.g. upscalers,
read-only analysis tools, or inpaint (which uses `mask_editor` instead).

`x-controlnet` implies `x-allow-prep: true`.

```json
{
  "input_image": {
    "type": "string",
    "format": "file-path",
    "title": "Source Image",
    "x-control": "image_picker",
    "x-allow-prep": true
  }
}
```

**Resolution Picker (`x-control: resolution`, `x-paired-with`):**

When two fields both declare `x-control: "resolution"` and use `x-paired-with` to reference each other, a client SHOULD render them as a linked 2D resolution picker (e.g. a grid of common aspect ratios).

```json
{
  "width": {
    "type": "integer",
    "default": 1024,
    "minimum": 512,
    "maximum": 2048,
    "x-step": 64,
    "x-control": "resolution",
    "x-paired-with": "height"
  },
  "height": {
    "type": "integer",
    "default": 1024,
    "minimum": 512,
    "maximum": 2048,
    "x-step": 64,
    "x-control": "resolution",
    "x-paired-with": "width"
  }
}
```

For models that only support specific dimension pairs (e.g., fixed output sizes), use `x-allowed-dimensions` on the width field:

```json
{
  "width": {
    "type": "integer",
    "x-control": "resolution",
    "x-paired-with": "height",
    "x-allowed-dimensions": [[1920, 1080], [1080, 1920], [1024, 1024]]
  }
}
```

**Upscale Resolution Picker (`x-control: upscale_resolution`):**

Upscale tools use `x-control: "upscale_resolution"` on `scale_factor` and/or `resolution` parameters. A client SHOULD render a picker that lets the user choose between relative scaling (2x, 3x) and absolute resolution (1080p, 1440p).

```json
{
  "scale_factor": {
    "type": "number",
    "default": 2,
    "minimum": 0.5,
    "maximum": 4,
    "x-step": 0.1,
    "x-control": "upscale_resolution"
  },
  "resolution": {
    "type": "integer",
    "default": 1080,
    "minimum": 480,
    "maximum": 4320,
    "x-control": "upscale_resolution"
  }
}
```

If both are declared, a client SHOULD present the two modes separately and send only the parameter for the selected mode.

**Discrete Value Constraints (`x-allowed-values`):**

Numeric parameters that only support specific discrete values can declare them with `x-allowed-values`. A client SHOULD render a constrained selector (e.g. segmented buttons or a dropdown) instead of a free slider:

```json
{
  "duration": {
    "type": "number",
    "default": 8,
    "minimum": 6,
    "maximum": 20,
    "x-control": "slider",
    "x-allowed-values": [6, 8, 10, 12, 14, 16, 18, 20]
  },
  "fps": {
    "type": "integer",
    "default": 25,
    "x-control": "slider",
    "x-allowed-values": [24, 25, 48, 50]
  }
}
```

**General Parameter Schema Example:**

```json
{
  "type": "object",
  "properties": {
    "steps": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 30,
      "title": "Steps",
      "description": "Number of sampling steps"
    },
    "cfg": {
      "type": "number",
      "minimum": 1,
      "maximum": 20,
      "default": 7.5,
      "title": "CFG Scale"
    },
    "sampler": {
      "type": "string",
      "enum": ["euler", "euler_a", "dpm++_2m", "dpm++_sde"],
      "default": "euler",
      "title": "Sampler"
    },
    "width": {
      "type": "integer",
      "enum": [512, 768, 1024, 1280],
      "default": 1024,
      "title": "Width"
    },
    "seed": {
      "type": "integer",
      "minimum": -1,
      "default": -1,
      "title": "Seed",
      "description": "-1 for random"
    }
  }
}
```

### Layout

The optional `layout` field controls how parameters are visually grouped and organized in the UI. Parameters not referenced in any layout section are shown ungrouped. Layout is purely presentational — it doesn't affect execution.

```json
{
  "layout": [
    {
      "label": "Inpaint Settings",
      "params": [
        { "name": "context_expand_factor" },
        { "name": "fill_method", "full_width": true }
      ]
    },
    {
      "label": "Advanced",
      "collapsed": true,
      "params": [
        { "name": "steps" },
        { "name": "cfg" },
        { "name": "sampler" },
        { "name": "scheduler" },
        { "name": "seed" }
      ]
    }
  ]
}
```

`layout` is a top-level field on the tool descriptor.

### Well-Known Field Names

These field names are a recommended vocabulary for common inputs; using them keeps tools consistent
and legible across providers and agents. They do not by themselves drive behavior — rendering
follows `x-control`. The table lists the control each name is conventionally paired with. Tools MAY
use any names.

| Field Name | Conventional control | Notes |
|------------|--------------|-------|
| `prompt` | Rich text editor (`prompt_editor`) | The `description` property is used as placeholder text |
| `input_images` | Media picker with drag-drop | Use `x-min-items`/`x-max-items` for count constraints |
| `input_videos` | Video picker | Same as above |
| `mask` | Mask painting editor | Requires `x-source-field` pointing to the source image |
| `width` + `height` | Linked resolution picker | See Resolution Picker section |
| `aspect_ratio` | Aspect ratio selector | When an `enum` is provided (e.g. `["1:1", "16:9"]`), a client SHOULD show a visual ratio picker. |
| `megapixels` | Megapixels picker | Slider with MP-based resolution output |
| `fps` | FPS selector | Shown alongside duration for video tools |
| `duration` | Duration control | Can be slider or discrete selector via `x-allowed-values` |
| `frame_count` | Frame count slider | Legacy — prefer `duration` for new tools |
| `loras` | LoRA pool picker | Array of `{path, weight}` objects with enum on `path` |
| `seed` | Seed control with randomize/lock | — |
| `scale_factor` | Upscale picker | Use `x-control: upscale_resolution` |

A client SHOULD render fields not in this list as **generic parameters**, inferring the control from the JSON Schema type (`string` → text input, `number` → slider, `boolean` → checkbox, `string` with `enum` → dropdown).

### Multi-Task Type Inference

When a tool declares multiple task types (e.g., `task_types: ["text-to-image", "image-to-image"]`), the host determines which mode is active from the inputs and sends the effective task type in the execution request. The host SHOULD resolve the mode as follows:

1. The **first** type in the `task_types` array is the **primary/default** mode
2. If `input_images` has at least one image and the tool supports `image-to-image`, the effective type switches to `image-to-image`
3. If the tool supports `image-to-video` and its primary type is `text-to-video`, the effective type switches to `image-to-video` when a start frame is provided
4. Otherwise, the primary task type is used

Providers MUST handle all task types they declare.

### Output Schema

A tool's output is a list of produced assets. Each asset carries its ID, media `type`, and an
optional `role` distinguishing it from the others when a tool returns more than one:

```json
{
  "type": "object",
  "required": ["assets"],
  "properties": {
    "assets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["asset_id", "type"],
        "properties": {
          "asset_id": { "type": "string", "description": "ID of the produced asset" },
          "type": { "type": "string", "enum": ["image", "video", "audio", "document"] },
          "role": { "type": "string", "description": "Distinguishes multiple outputs; defaults to \"primary\"" }
        }
      }
    }
  }
}
```

Each `asset_id` references a produced asset in the provider's asset storage, which the host retrieves
via the [asset transfer mechanism](#asset-management). `role` is an open vocabulary — `primary`
(default), `mask`, `preview`, `control`, etc. A single-output tool returns one asset with role
`primary`.

Result metadata (sent alongside the output in `tools.result`) may include additional information
like `generation_time`, `actual_seed`, etc.

---

## Extensions and Vendor Namespacing

STP is an opinionated, domain-specific protocol: the core vocabulary (task types, UI control hints,
capabilities, error codes) is *part of the standard* so tools stay legible to both agents and humans
across products. But products still need room to add their own ideas without forking the wire
format. The rule:

- **Standard keys are owned by STP.** Schema UI hints (`x-control`, `x-step`, …), the core task-type
  registry, baseline capabilities, and reserved error codes are defined here and grow through the
  spec process. (The `x-` prefix on schema hints is a JSON-Schema-compatibility detail — it keeps
  STP keywords from colliding with future JSON Schema keywords — *not* a signal that they're
  non-standard.)
- **Product-specific extensions are vendor-namespaced** with `x-<vendor>-…`, and any conformant peer
  MUST ignore extensions it does not recognize. This is the pressure-release valve: products extend
  in their own namespace instead of abusing or redefining standard keys.

The convention is uniform across the protocol:

| Surface | Standard form | Vendor extension |
|---------|---------------|------------------|
| Schema UI hints | `x-control`, `x-step`, … | `x-<vendor>-<hint>` |
| Task types | `text-to-image`, … (closed registry) | `x-<vendor>-<task>` |
| Capabilities | `cancel`, … | `x-<vendor>-<feature>` |
| Job error codes | `OUT_OF_MEMORY`, … (bare) | `X-<VENDOR>-XXXXX` |

Adding to a *standard* registry (a new task type, a new control hint) is a deliberate spec change,
not something any single product does unilaterally in the shared namespace.

---

## Error Codes

Errors come in two forms, depending on where the failure happens.

**Request errors** — JSON-RPC numeric error codes, returned in the `error` field of a response to a
request (`provider.register`, `tools.list`, `tools.refresh`, the `tools.execute` acknowledgement,
`tools.cancel`, `tools.upload*`):

| Code | Message | Meaning |
|------|---------|---------|
| -32700 | Parse error | Invalid JSON |
| -32600 | Invalid Request | Not valid JSON-RPC |
| -32601 | Method not found | Unknown method |
| -32602 | Invalid params | Bad parameters |
| -32603 | Internal error | Provider internal error |

**Job errors** — STP string codes, carried in the `error` field of a terminal `tools.result`
notification. Reserved codes are bare identifiers:

| Code | Meaning |
|------|---------|
| `TOOL_NOT_FOUND` | Tool doesn't exist |
| `ASSET_NOT_FOUND` | Referenced asset doesn't exist |
| `EXECUTION_FAILED` | Job failed during execution |
| `CANCELLED` | Job was cancelled |
| `TIMEOUT` | Job timed out (may be synthesized by the host; see the terminal-result guarantee) |
| `OUT_OF_MEMORY` | GPU/system memory exhausted |
| `MODEL_NOT_LOADED` | Required model not available |

**Vendor-specific job errors** use the `X-<VENDOR>-XXXXX` convention (e.g.
`X-COMFYUI-WORKFLOW_INVALID`). Reserved bare codes are owned by STP; anything a provider invents
MUST be vendor-prefixed. A host that doesn't recognize a code treats it as a generic failure.

---

## Limits

- **Message size.** A peer MUST enforce a maximum JSON-RPC message size and reject anything larger.
  The RECOMMENDED minimum is **16 MiB**.
- **Asset size.** Not bounded by the protocol.
- **Progress rate.** A provider SHOULD coalesce `tools.progress` notifications to roughly 10/s per
  job; a host MAY drop excess.

---

## Provider Implementation Notes

### Concurrency

- `max_concurrent` in registration sets provider-wide limit
- Provider manages its own queue internally
- Jobs always accepted (no rejection) - provider queues them
- Use `queue.status` to communicate queue state to the host

### Graceful Shutdown

When provider needs to shut down:

1. Complete in-progress jobs (or cancel them)
2. Send `provider.disconnect` with reason
3. Close connection

### Reconnection

- Stdio providers: the host restarts on crash
- WebSocket providers: Should implement reconnection with exponential backoff
- On reconnect: Re-register and re-send tool list
- In-flight jobs from previous session are considered failed

---

## Tool File Uploads

Providers can declare that a tool parameter accepts file uploads via the `x-accept-upload` schema extension. This enables users to upload files (e.g., LoRA weights) directly through the host UI.

### Schema Extension: `x-accept-upload`

A tool's parameter schema can include `x-accept-upload` on any string property with an `enum` to indicate it accepts uploads:

```json
{
  "loras": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "enum": ["flux/lora1.safetensors", "flux/lora2.safetensors"],
          "x-accept-upload": {
            "extensions": [".safetensors"],
            "max_size": 2147483648
          }
        }
      }
    }
  }
}
```

Fields:
- `extensions`: Array of accepted file extensions (e.g., `[".safetensors"]`)
- `max_size`: Maximum file size in bytes (e.g., 2GB = 2147483648)

This is purely declarative — the frontend uses it to show an upload button and validate file selection.

### `tools.upload` — Initiate Upload

The host sends `tools.upload` to the provider to initiate a file upload:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.upload",
  "params": {
    "upload_id": "upload-abc123",
    "tool_id": "flux-dev:text-to-image",
    "parameter": "loras",
    "filename": "my_lora.safetensors",
    "file_size": 184549376
  },
  "id": 20
}
```

Provider responds with acceptance and an asset ID for the transfer:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "accepted": true,
    "asset_id": "upload-abc123.safetensors"
  },
  "id": 20
}
```

After receiving acceptance, the host uploads the file bytes to `{asset_endpoint}/{asset_id}` via HTTP PUT (same mechanism as regular asset uploads).

#### Optional: provider-supplied upload URL

A provider MAY include an `upload_url` (and matching `upload_method`, always `"PUT"`) in the response. When present, the client uploads bytes directly to that URL with the specified method instead of `{asset_endpoint}/{asset_id}`, with no Authorization header (the URL itself is the auth — typically a short-TTL signed URL).

```json
{
  "jsonrpc": "2.0",
  "result": {
    "accepted": true,
    "asset_id": "upload-abc123",
    "upload_url": "https://abc.r2.cloudflarestorage.com/bucket/lora-staging/upload-abc123?X-Amz-Signature=...",
    "upload_method": "PUT"
  },
  "id": 20
}
```

If the provider rejects the upload:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "accepted": false,
    "error": "Unsupported file type"
  },
  "id": 20
}
```

### `tools.upload_complete` — Finalize Upload

After the file bytes have been transferred, the host sends `tools.upload_complete`:

```json
{
  "jsonrpc": "2.0",
  "method": "tools.upload_complete",
  "params": {
    "upload_id": "upload-abc123"
  },
  "id": 21
}
```

The provider installs the file (e.g., moves it to the LoRA directory) and responds:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "success": true,
    "installed_path": "flux/my_lora.safetensors"
  },
  "id": 21
}
```

After a successful `tools.upload_complete`, the host automatically calls `tools.refresh` to update the tool's state.

### End-to-End Upload Flow

1. Tool registers with `x-accept-upload` on `loras.items.properties.path`
2. Frontend sees `x-accept-upload` → shows upload button in LoRA picker
3. User clicks upload, selects a `.safetensors` file (validated by extensions/max_size)
4. Frontend POSTs file to `POST /api/tools/{tool_id}/upload` with `parameter=loras`
5. Backend sends `tools.upload` RPC → gets `asset_id` → PUTs bytes to asset endpoint → sends `tools.upload_complete`
6. Backend calls `tools.refresh` → provider rescans → updated enum list
7. Frontend receives `tools-changed` event → re-fetches tool → LoRA picker updates

---

## Appendix A: Example Tool Descriptor

A complete, realistic tool descriptor — a Flux.2 Klein 9B model exposing both text-to-image and
image-to-image, with ControlNet inputs, a LoRA picker, and a collapsed Advanced layout group.

```json
{
  "id": "flux-klein-9b",
  "name": "Flux.2 Klein 9B",
  "task_types": ["text-to-image", "image-to-image"],
  "parameter_schema": {
    "type": "object",
    "required": ["prompt"],
    "properties": {
      "prompt": { "type": "string", "description": "Describe the image to generate or edit", "default": "", "x-control": "prompt_editor" },
      "width":  { "type": "integer", "default": 1024, "minimum": 256, "maximum": 2048, "x-control": "resolution", "x-step": 64, "x-paired-with": "height" },
      "height": { "type": "integer", "default": 1024, "minimum": 256, "maximum": 2048, "x-control": "resolution", "x-step": 64, "x-paired-with": "width" },
      "seed":   { "type": "integer", "description": "Random seed", "x-control": "seed" },
      "input_images": { "type": "array", "items": { "type": "string" }, "x-control": "image_picker", "x-min-items": 0, "x-max-items": 10, "x-controlnet": ["canny", "depth", "lineart", "pose"] },
      "steps":    { "type": "integer", "default": 4, "minimum": 1, "maximum": 20, "x-control": "slider", "x-step": 1, "x-label": "Steps" },
      "guidance": { "type": "number", "default": 1, "minimum": 0, "maximum": 10, "x-control": "slider", "x-step": 0.1, "x-label": "Guidance" },
      "sampler": {
        "type": "string", "default": "euler", "x-control": "dropdown", "x-label": "Sampler",
        "enum": [
          "euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", "lms",
          "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde",
          "ddpm", "lcm", "deis", "res_multistep", "ddim", "uni_pc", "uni_pc_bh2"
        ]
      },
      "loras": {
        "type": "array", "default": [], "x-control": "lora_picker",
        "items": {
          "type": "object",
          "required": ["path"],
          "properties": {
            "path":   { "type": "string", "enum": ["flux2-klein-9b/ultra_real_v4.safetensors"] },
            "weight": { "type": "number", "default": 1, "minimum": -2, "maximum": 2 }
          }
        }
      }
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["assets"],
    "properties": {
      "assets": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["asset_id", "type"],
          "properties": {
            "asset_id": { "type": "string" },
            "type": { "type": "string", "enum": ["image"] },
            "role": { "type": "string" }
          }
        }
      }
    }
  },
  "layout": [
    { "label": "Advanced", "collapsed": true, "params": [
      { "name": "steps" }, { "name": "sampler" }, { "name": "guidance" }, { "name": "loras" }, { "name": "seed" }
    ] }
  ],
  "metadata": { "badges": ["Open Weights", "Fast"] }
}
```
