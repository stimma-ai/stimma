# Stimma Structured Media Formats

Stimma supports structured media types for organizing and presenting content. These include markdown files (`.md`) and JSON-based formats (`.stimmaset.json`, `.stimmagrid.json`).

## Markdown Files (`.md`)

Markdown files store text content with optional YAML front matter for metadata. Standard CommonMark/GFM syntax is supported, with inline images that can reference library media.

### Format

```markdown
---
title: Optional Title
author: Optional Author
---

# Your Content Here

Standard markdown syntax including **bold**, *italic*, [links](url), etc.

Images can reference library media:
![caption](./relative/path/to/image.png)
![external](https://example.com/image.jpg)
```

### Fields (Front Matter)

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `title` | No | `string` | Display title |
| `author` | No | `string` | Author attribution |

Any other YAML front matter fields are preserved and accessible via the API.

### Image Path Resolution

- **Relative paths**: Resolved from the markdown file's parent directory
  - `"image.png"` - same directory as the .md file
  - `"subfolder/image.png"` - subfolder relative to .md file
  - `"../other/image.png"` - parent directory navigation
- **Absolute paths**: Used as-is (`"/Users/you/photos/image.png"`)
- **External URLs**: HTTP/HTTPS URLs are passed through directly
- **Missing files**: Show placeholder or broken image (graceful degradation)

### Example

```markdown
---
title: Japan Trip Notes
author: Jane Doe
---

# My Trip to Japan

These images were taken during my trip to Japan in 2024.

## Day 1: Tokyo

We started in Shibuya and visited the famous crossing.

![Shibuya Crossing](./photos/shibuya-crossing.png)

The neon lights were amazing at night.

## Day 2: Kyoto

![Fushimi Inari](./photos/fushimi-inari.jpg)

The thousand torii gates were breathtaking.
```

### Viewer Behavior

- Rendered markdown with proper typography
- Images display inline with their resolved library thumbnails/files
- Scrollable content with dark theme
- Gray document badge in grid view

---

## Sets (`.stimmaset.json`)

Sets are ordered lists of media, referenced by path. This enables stimma to work on media at a batch level.

### Schema

```json
{
  "version": 1,
  "title": "My Image Set",
  "description": "Optional description",
  "items": [
    { "path": "relative/path/to/image.png" },
    { "path": "/absolute/path/to/image.jpg" },
    { "path": "../sibling-folder/video.mp4" }
  ]
}
```

### Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `version` | Yes | `integer` | Schema version, currently `1` |
| `title` | No | `string` | Display title |
| `description` | No | `string` | Description text |
| `items` | Yes | `array` | Array of item references |
| `items[].path` | Yes | `string` | Path to media file (relative or absolute) |

### Path Resolution

- **Relative paths**: Resolved from the JSON file's parent directory
  - `"image.png"` -> same directory as the .stimmaset.json
  - `"subfolder/image.png"` -> subfolder relative to .stimmaset.json
  - `"../other/image.png"` -> parent directory navigation
- **Absolute paths**: Used as-is (`"/Users/you/photos/image.png"`)
- **Missing files**: Show a placeholder (graceful degradation)

### Example

```json
{
  "version": 1,
  "title": "Character Design Iterations",
  "description": "Evolution of the character design from sketch to final",
  "items": [
    { "path": "sketches/initial-sketch.png", "caption": "Initial rough sketch" },
    { "path": "sketches/refined-sketch.png", "caption": "Refined linework" },
    { "path": "colors/flat-colors.png", "caption": "Flat color pass" },
    { "path": "colors/shading.png", "caption": "Shading and highlights" },
    { "path": "final/character-final.png", "caption": "Final render" }
  ]
}
```

### Viewer Behavior

- Slideshow-style navigation
- Previous/next buttons and arrow key navigation
- Thumbnail strip at bottom
- Caption overlay when present
- Amber layers/stack badge in grid view

---

## Grids (`.stimmagrid.json`)

Grids display media in a table layout with optional row and column headers. Ideal for style comparisons, prompt matrices, or any content that benefits from a grid arrangement.

### Schema

```json
{
  "version": 1,
  "title": "Style Comparison Grid",
  "description": "Comparing different styles across prompts",
  "rows": 3,
  "cols": 4,
  "row_headers": ["Style A", "Style B", "Style C"],
  "col_headers": ["Prompt 1", "Prompt 2", "Prompt 3", "Prompt 4"],
  "cells": [
    { "row": 0, "col": 0, "path": "grid-images/r0c0.png" },
    { "row": 0, "col": 1, "path": "grid-images/r0c1.png", "caption": "Best result" },
    { "row": 1, "col": 0, "path": "grid-images/r1c0.png" }
  ]
}
```

### Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `version` | Yes | `integer` | Schema version, currently `1` |
| `title` | No | `string` | Display title |
| `description` | No | `string` | Description text |
| `rows` | Yes | `integer` | Number of rows |
| `cols` | Yes | `integer` | Number of columns |
| `row_headers` | No | `array` | Array of row header labels (length should match `rows`) |
| `col_headers` | No | `array` | Array of column header labels (length should match `cols`) |
| `cells` | Yes | `array` | Array of cell definitions |
| `cells[].row` | Yes | `integer` | Zero-indexed row number |
| `cells[].col` | Yes | `integer` | Zero-indexed column number |
| `cells[].path` | Yes | `string` | Path to media file (relative or absolute) |
| `cells[].caption` | No | `string` | Caption for this cell |

### Path Resolution

Same as Sets - relative paths resolve from the JSON file's directory.

### Sparse Grids

Not every cell needs to be populated. Empty cells (no image at that row/col) show a placeholder. This is useful for partial comparisons or when some combinations don't exist.

### Example

```json
{
  "version": 1,
  "title": "Model Comparison: Flux vs SDXL",
  "description": "Same prompts, different models and schedulers",
  "rows": 2,
  "cols": 3,
  "row_headers": ["Flux Dev", "SDXL 1.0"],
  "col_headers": ["Euler", "DPM++", "UniPC"],
  "cells": [
    { "row": 0, "col": 0, "path": "comparison/flux-euler.png" },
    { "row": 0, "col": 1, "path": "comparison/flux-dpm.png" },
    { "row": 0, "col": 2, "path": "comparison/flux-unipc.png" },
    { "row": 1, "col": 0, "path": "comparison/sdxl-euler.png" },
    { "row": 1, "col": 1, "path": "comparison/sdxl-dpm.png", "caption": "Best quality" },
    { "row": 1, "col": 2, "path": "comparison/sdxl-unipc.png" }
  ]
}
```

### Viewer Behavior

- Table-based grid display
- Row and column headers in cyan
- Thumbnail cells (128x128)
- Click cell to view full-size in modal
- Caption overlay on selected image
- Cyan grid badge in grid view

---

## API Endpoints

### Content Endpoint

```
GET /api/media/{id}/content
```

Returns the parsed content with resolved references for structured types.

**Response for Markdown:**
```json
{
  "format": "markdown",
  "frontmatter": {
    "title": "My Document",
    "author": "Jane Doe"
  },
  "content": "# Heading\n\nParagraph text...\n\n![alt](path)",
  "images": [
    {
      "alt": "alt text",
      "path": "./image.png",
      "resolved": {
        "media_id": 123,
        "file_hash": "abc123...",
        "width": 1024,
        "height": 768
      }
    },
    {
      "alt": "external",
      "path": "https://example.com/img.jpg",
      "resolved": null,
      "external": true
    }
  ]
}
```

**Response for Sets:**
```json
{
  "version": 1,
  "title": "My Collection",
  "items": [
    {
      "path": "/path/to/image.png",
      "caption": "Optional caption",
      "resolved": {
        "media_id": 123,
        "file_hash": "abc123...",
        "width": 1024,
        "height": 768,
        "vlm_caption": "AI-generated description"
      }
    },
    {
      "path": "/nonexistent/file.png",
      "resolved": null
    }
  ]
}
```

**Response for Grids:**
```json
{
  "version": 1,
  "title": "Comparison Grid",
  "rows": 2,
  "cols": 2,
  "row_headers": ["A", "B"],
  "col_headers": ["1", "2"],
  "cells": [
    {
      "row": 0,
      "col": 0,
      "path": "/path/to/image.png",
      "resolved": { "media_id": 123, "file_hash": "..." }
    }
  ]
}
```

Returns 404 for non-structured types (images, videos, audio).

### Filtering

```
GET /api/media?media_types=text
GET /api/media?media_types=sets
GET /api/media?media_types=grids
GET /api/media?media_types=structured  # text + sets + grids
GET /api/media?excluded_media_types=grids
```

---

## Creating Structured Media

Structured media files are created manually using any text editor. There is currently no in-app creation wizard.

### Quick Start

1. Create a new file with the appropriate extension (`.md`, `.stimmaset.json`, or `.stimmagrid.json`)
2. Copy one of the example schemas above
3. Modify the content for your use case
4. Save in a watched folder
5. Wait for Stimma to scan and index the file

### Tips

- Use relative paths when files are in the same directory or subdirectories
- Use absolute paths when referencing files in other locations
- Missing references show gracefully - you won't break the set/grid
- Files are read-only in the app; edit directly to make changes

---

## Processing Behavior

All structured types skip AI processing phases since they don't contain visual content:

- `clip_status = 'skipped'`
- `vlm_caption_status = 'skipped'`
- `face_detection_status = 'skipped'`

For markdown files, the parsed content (frontmatter + body) is stored in the `raw_metadata` field.
For JSON-based types, the raw JSON is stored in `raw_metadata` for quick access without re-reading the file.

---

## Future Enhancements

Planned features that are not yet implemented:

- In-app set/grid creation wizard
- Drag-drop item reordering for sets
- Nested sets (set containing other sets)
