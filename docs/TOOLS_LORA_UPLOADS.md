# Adding LoRA Upload Support to Your Tool Provider

This doc explains what you need to do in your tool provider to let users upload LoRA files through the Stimma UI.

## Overview

There are two parts:

1. **Declare upload support** — Add `x-accept-upload` to your tool's loras schema so the UI shows an upload button.
2. **Handle the upload** — Implement two new RPC methods (`tools.upload` and `tools.upload_complete`) that receive the file and install it.

After a successful upload, Stimma calls `tools.refresh` (which you already handle) to pick up the new LoRA in the enum list.

---

## 1. Declare Upload Support

Add `x-accept-upload` to the `path` property inside your loras parameter schema. You're already returning this schema in your `tools.list` / `tools.refresh` responses — just add the extension:

```json
"loras": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "enum": ["flux/existing_lora.safetensors"],
        "x-accept-upload": {
          "extensions": [".safetensors"],
          "max_size": 2147483648
        }
      },
      "name": {
        "type": "string",
        "enum": ["Existing LoRA"]
      },
      "weight": { "type": "number", "default": 1.0 }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `extensions` | `string[]` | Accepted file extensions. The UI restricts the file picker to these. |
| `max_size` | `integer` | Maximum file size in bytes. The UI rejects files larger than this before uploading. |

That's all the schema needs. The presence of `x-accept-upload` tells the frontend to show an "Upload" button in the LoRA picker.

---

## 2. Handle `tools.upload`

When a user uploads a file, Stimma sends `tools.upload` to your provider:

```json
{
  "method": "tools.upload",
  "params": {
    "upload_id": "upload-a1b2c3d4e5f6",
    "tool_id": "flux-dev:text-to-image",
    "parameter": "loras",
    "filename": "my_new_style.safetensors",
    "file_size": 184549376
  },
  "id": 20
}
```

Your provider should:

1. Decide whether to accept (check disk space, validate the filename, etc.)
2. Choose an `asset_id` for the incoming file — this is where Stimma will PUT the bytes
3. Respond

**Accept:**

```json
{
  "result": {
    "accepted": true,
    "asset_id": "upload-a1b2c3d4e5f6.safetensors"
  },
  "id": 20
}
```

**Reject:**

```json
{
  "result": {
    "accepted": false,
    "error": "Not enough disk space"
  },
  "id": 20
}
```

After you accept, Stimma transfers the file bytes using the same asset mechanism you already support:

- **WebSocket providers:** HTTP PUT to `{asset_endpoint}/{asset_id}`
- **Stdio providers:** Written to `{ASSET_PATH}/{asset_id}`

You don't need to do anything for this step — it uses the existing asset transfer infrastructure.

---

## 3. Handle `tools.upload_complete`

After the bytes are transferred, Stimma sends `tools.upload_complete`:

```json
{
  "method": "tools.upload_complete",
  "params": {
    "upload_id": "upload-a1b2c3d4e5f6"
  },
  "id": 21
}
```

This is your signal to **install the file**. Typically:

1. Read the file from the asset location (using the `asset_id` you returned earlier)
2. Move/copy it to the appropriate LoRA directory (e.g., `ComfyUI/models/loras/flux/`)
3. Clean up the asset copy
4. Respond with the installed path

**Success:**

```json
{
  "result": {
    "success": true,
    "installed_path": "flux/my_new_style.safetensors"
  },
  "id": 21
}
```

The `installed_path` should match what will appear in the `path.enum` array after the next `tools.refresh`.

**Failure:**

```json
{
  "result": {
    "success": false,
    "error": "Failed to move file to loras directory"
  },
  "id": 21
}
```

---

## 4. What Happens Next

After a successful `tools.upload_complete`, Stimma automatically:

1. Calls `tools.refresh` — your provider rescans for LoRAs and returns the updated tool list
2. Updates the UI — the new LoRA appears in the picker

You don't need to do anything extra here. Your existing `tools.refresh` handler already returns the current LoRA enum list. As long as the file was installed to the right directory, it'll show up.

---

## Example: Stdio Provider (Python)

Minimal handler additions for a provider that stores LoRAs in a local directory:

```python
import shutil

LORA_DIR = "/path/to/ComfyUI/models/loras"
ASSET_PATH = os.environ.get("ASSET_PATH", "/tmp/stimma-assets")

# Track pending uploads: upload_id -> asset_id
pending_uploads = {}

# In your message loop, add these handlers:

if method == "tools.upload":
    upload_id = params["upload_id"]
    filename = params["filename"]
    asset_id = f"{upload_id}.safetensors"
    pending_uploads[upload_id] = {
        "asset_id": asset_id,
        "filename": filename,
        "tool_id": params["tool_id"],
    }
    send({
        "jsonrpc": "2.0",
        "result": {"accepted": True, "asset_id": asset_id},
        "id": msg_id,
    })

elif method == "tools.upload_complete":
    upload_id = params["upload_id"]
    upload = pending_uploads.pop(upload_id, None)
    if not upload:
        send({
            "jsonrpc": "2.0",
            "result": {"success": False, "error": "Unknown upload_id"},
            "id": msg_id,
        })
    else:
        # Move from asset path to loras directory
        src = os.path.join(ASSET_PATH, upload["asset_id"])
        # Determine subdirectory from tool_id (e.g., "flux" for flux tools)
        subdir = get_lora_subdir(upload["tool_id"])
        dest = os.path.join(LORA_DIR, subdir, upload["filename"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        installed_path = f"{subdir}/{upload['filename']}"
        send({
            "jsonrpc": "2.0",
            "result": {"success": True, "installed_path": installed_path},
            "id": msg_id,
        })
```

---

## Checklist

- [ ] Add `x-accept-upload` to `loras.items.properties.path` in your tool schema
- [ ] Handle `tools.upload` — accept the upload request, return an `asset_id`
- [ ] Handle `tools.upload_complete` — move the file from asset storage to the LoRA directory
- [ ] Verify `tools.refresh` picks up the newly installed LoRA in the enum list
