# Lineage System Documentation

This document describes how lineage data works in Stimma for tracking the
generation history of images and videos. Use this as a reference when
implementing lineage display in external interfaces (e.g., web).

## Overview

Lineage tracks parent-child relationships between generated media:
- When you run an image edit, the source image is the "parent" and the result is the "child"
- When you upscale an image, the original is the parent, upscaled version is the child
- Multi-input operations (like video stitching) can have multiple parents

## Data Storage

Lineage is stored in two places:

### 1. media_lineage Table (Relational)

Used for efficient querying of relationships.

Schema:
```
media_lineage
├── id (int, primary key)
├── media_id (int, FK → media_items.id)      # The child/output
├── source_media_id (int, FK → media_items.id, nullable)  # Parent if internal
├── source_file_path (string, nullable)       # Parent if external file
├── source_order (int)                        # For multi-input ordering (0, 1, 2...)
├── task_type (string)                        # e.g., "image-to-image", "upscale-image"
└── created_at (datetime)
```

Key points:
- Each row represents one parent→child relationship
- Multi-input operations have multiple rows with same media_id, different source_order
- source_media_id is null when the source was an external file (not in library)
- source_file_path stores the original path for external sources

### 2. generation_metadata JSON (Embedded)

Stored on each MediaItem, contains full generation details including lineage.

```json
{
  "version": 3,
  "task_type": "image-to-image",
  "generated_at": "2025-01-19T10:30:00Z",
  "model": "flux-dev",
  "generator": "comfyui",
  "prompt": "make it brighter",
  "negative_prompt": "dark",
  "parameters": {
    "width": 1024,
    "height": 1024,
    "cfg": 7.0,
    "steps": 20,
    "seed": 12345
  },
  "tool_id": "builtin:comfyui:flux-dev:image-to-image",
  "source_inputs": [...],
  "lineage_trace": [...]
}
```

## Key JSON Fields for Lineage

### source_inputs

Direct inputs to THIS generation step. Array of objects:

```json
"source_inputs": [
  {
    "media_id": 123,
    "file_path": "/path/to/original.jpg",
    "role": "input_image"
  },
  {
    "media_id": 456,
    "file_path": "/path/to/mask.png",
    "role": "mask"
  }
]
```

Fields:
- media_id: ID in media_items table (may be null for external files)
- file_path: Original file path at generation time
- role: Semantic role like "input_image", "mask", "reference" (optional)

### lineage_trace

Complete ancestor chain. Ordered OLDEST first → NEWEST last.

```json
"lineage_trace": [
  {
    "media_id": 100,
    "task_type": "text-to-image",
    "generated_at": "2025-01-18T09:00:00Z",
    "model": "flux-dev",
    "generator": "comfyui",
    "prompt": "a logo design",
    "negative_prompt": null,
    "parameters": { "width": 1024, "height": 1024, ... },
    "source_inputs": [],
    "tool_id": "builtin:comfyui:flux-dev:text-to-image"
  },
  {
    "media_id": 110,
    "task_type": "image-to-image",
    "generated_at": "2025-01-18T10:00:00Z",
    "model": "flux-dev",
    "generator": "comfyui",
    "prompt": "add more detail",
    "negative_prompt": null,
    "parameters": { ... },
    "source_inputs": [{ "media_id": 100, ... }],
    "tool_id": "builtin:comfyui:flux-dev:image-to-image"
  }
]
```

Important:
- lineage_trace does NOT include the current image
- To build full history: lineage_trace + current image's own metadata
- The last entry in lineage_trace is the immediate parent

## API Endpoint

### GET /media/{media_id}/lineage

Query parameters:
- include_ancestors (bool): Fetch full ancestor tree recursively
- include_descendants (bool): Fetch full descendant tree recursively
- max_depth (int, 1-100, default 50): Limit recursion depth

Response:
```json
{
  "media_id": 123,
  "sources": [
    {
      "order": 0,
      "task_type": "image-to-image",
      "type": "internal",
      "media": { /* full MediaItem */ }
    }
  ],
  "derivatives": [
    {
      "media": { /* full MediaItem */ },
      "task_type": "upscale-image",
      "created_at": "2025-01-19T12:00:00Z"
    }
  ],
  "ancestors": [ /* if include_ancestors=true */ ],
  "descendants": [ /* if include_descendants=true */ ]
}
```

Source types:
- "internal": Source media exists in library (media object included)
- "external": Source was external file (file_path included, no media object)
- "deleted": Source was deleted (media_id known but no longer exists)

## Displaying Lineage in UI

### Building Generation History

To show a chronological history of how an image was created:

```javascript
function buildGenerationHistory(mediaItem) {
  const history = [];
  const metadata = mediaItem.generation_metadata;

  if (!metadata) return history;

  // Add ancestors (oldest first)
  if (metadata.lineage_trace) {
    for (const ancestor of metadata.lineage_trace) {
      history.push({
        media_id: ancestor.media_id,
        task_type: ancestor.task_type,
        prompt: ancestor.prompt,
        model: ancestor.model,
        generated_at: ancestor.generated_at,
        parameters: ancestor.parameters
      });
    }
  }

  // Add current image (newest)
  history.push({
    media_id: mediaItem.id,
    task_type: metadata.task_type,
    prompt: metadata.prompt,
    model: metadata.model,
    generated_at: metadata.generated_at,
    parameters: metadata.parameters
  });

  return history;
}
```

### Building Prompt Chain

To show the evolution of prompts:

```javascript
function buildPromptChain(mediaItem) {
  const prompts = [];
  const metadata = mediaItem.generation_metadata;

  if (!metadata) return prompts;

  // Collect all prompts from ancestors
  if (metadata.lineage_trace) {
    for (const ancestor of metadata.lineage_trace) {
      if (ancestor.prompt) {
        prompts.push(ancestor.prompt);
      }
    }
  }

  // Add current prompt
  if (metadata.prompt) {
    prompts.push(metadata.prompt);
  }

  return prompts;  // ["a logo", "add detail", "make brighter"]
}
```

### Displaying Source Thumbnails

To show what images were used as input:

```javascript
function getSourceImages(mediaItem) {
  const metadata = mediaItem.generation_metadata;

  if (!metadata?.source_inputs) return [];

  return metadata.source_inputs
    .filter(input => input.media_id)  // Only internal sources
    .map(input => input.media_id);
}
```

## Task Types

Common task_type values and their meanings:

| task_type | Description | Typical Inputs |
|-----------|-------------|----------------|
| text-to-image | Generated from text prompt only | None |
| image-to-image | Image-to-image with text guidance | 1 image |
| image-to-image | Style transfer / img2img | 1 image |
| inpaint-image | Masked inpainting | 1 image + mask |
| outpaint-image | Extended canvas | 1 image |
| upscale-image | Resolution upscaling | 1 image |
| image-to-video | Animated from still | 1 image |
| text-to-video | Generated video from text prompt | None |
| video-to-video | Video edit / transformation | 1 video |
| upscale-video | Video resolution upscaling | 1 video |
| video-extend | Extended video | 1 video |
| video-stitch | Combined videos | 2+ videos |

## Edge Cases

### No Lineage

Images with no lineage (text-to-image or imported):
- source_inputs: [] or missing
- lineage_trace: [] or missing
- No rows in media_lineage table

### External Sources

When source was an external file (not imported to library):
- source_media_id is null in media_lineage
- source_file_path contains original path
- In source_inputs: media_id may be null, file_path is set

### Deleted Sources

When parent image was deleted:
- media_lineage row remains (source_media_id becomes null via SET NULL)
- lineage_trace JSON preserves the media_id that no longer exists
- API returns type: "deleted" for these sources

### Missing Metadata

Older images may have incomplete generation_metadata:
- Check for null/missing fields before accessing
- Fall back to media_lineage table for basic relationships
- Some fields like tool_id may be missing in older records

## Example: Full Lineage Chain

Original generation (text-to-image):
```json
{
  "id": 100,
  "generation_metadata": {
    "task_type": "text-to-image",
    "prompt": "a logo",
    "model": "flux-dev",
    "source_inputs": [],
    "lineage_trace": []
  }
}
```

After first edit:
```json
{
  "id": 110,
  "generation_metadata": {
    "task_type": "image-to-image",
    "prompt": "add more detail",
    "model": "flux-dev",
    "source_inputs": [{ "media_id": 100, "file_path": "..." }],
    "lineage_trace": [
      {
        "media_id": 100,
        "task_type": "text-to-image",
        "prompt": "a logo",
        "source_inputs": []
      }
    ]
  }
}
```

After second edit:
```json
{
  "id": 120,
  "generation_metadata": {
    "task_type": "image-to-image",
    "prompt": "make brighter",
    "model": "flux-dev",
    "source_inputs": [{ "media_id": 110, "file_path": "..." }],
    "lineage_trace": [
      {
        "media_id": 100,
        "task_type": "text-to-image",
        "prompt": "a logo",
        "source_inputs": []
      },
      {
        "media_id": 110,
        "task_type": "image-to-image",
        "prompt": "add more detail",
        "source_inputs": [{ "media_id": 100 }]
      }
    ]
  }
}
```

## Summary

For web implementation:

1. **Fetch metadata**: Use GET /media/{id} to get generation_metadata JSON
2. **Get relationships**: Use GET /media/{id}/lineage for queried relationships
3. **Build history**: Combine lineage_trace + current metadata
4. **Display prompts**: Extract prompt field from each step
5. **Show sources**: Use source_inputs to show input thumbnails
6. **Handle missing data**: Check for null/missing fields gracefully
