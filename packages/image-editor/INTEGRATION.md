# Integrating @stimma/image-editor

This guide covers how to integrate the Stimma Image Editor into your Vue 3 application.

## Installation (Local Development)

In your project's `package.json`:

```json
{
  "dependencies": {
    "@stimma/image-editor": "file:../stimma-image-editor"
  }
}
```

Then run:

```bash
npm install
```

## Basic Usage

```vue
<script setup lang="ts">
import { ref } from 'vue';
import {
  StimmaEditor,
  cropPlugin,
  finetunePlugin,
  filterPlugin,
  effectsPlugin,
  annotatePlugin,
  retouchPlugin,
} from '@stimma/image-editor';
import '@stimma/image-editor/style.css';

const editorRef = ref<InstanceType<typeof StimmaEditor> | null>(null);

const plugins = [
  cropPlugin(),
  finetunePlugin(),
  filterPlugin(),
  effectsPlugin(),
  annotatePlugin(),
  retouchPlugin(),
];
</script>

<template>
  <StimmaEditor
    ref="editorRef"
    :plugins="plugins"
    src="/path/to/image.jpg"
  />
</template>
```

## Image I/O

### Loading Images

The `:src` prop accepts multiple formats:

- `string` - URL to an image
- `File` - File object from input or drag-drop
- `Blob` - Raw image data
- `HTMLImageElement` - Existing image element
- `HTMLCanvasElement` - Canvas with image data
- `ImageBitmap` - ImageBitmap object

```vue
<StimmaEditor :src="imageUrl" />
```

Or load programmatically:

```typescript
await editorRef.value.loadImage(file);
```

### Exporting Rasterized Image

Export the edited image as a Blob:

```typescript
const result = await editorRef.value.rasterize({
  format: 'image/jpeg',  // 'image/png', 'image/webp'
  quality: 0.9,          // 0-1 for JPEG/WebP
  maxWidth: 1920,        // Optional size constraints
  maxHeight: 1080,
});

// result.dest is a Blob
const url = URL.createObjectURL(result.dest);
```

## Project Serialization

Save and restore the full editor state for lossless editing.

### Save Project (with history - full undo/redo)

```typescript
const project = await editorRef.value.serialize({
  name: 'My Project',
  includeThumbnail: true,
  thumbnailMaxSize: 200,
});

// Store project (e.g., in IndexedDB or send to server)
localStorage.setItem('project', JSON.stringify(project));
```

### Save Project (without history - compact lossless)

For smaller file sizes when undo history isn't needed:

```typescript
const project = await editorRef.value.serialize({
  name: 'My Project',
  includeHistory: false,
});
```

### Load Project

```typescript
const projectJson = localStorage.getItem('project');
const project = JSON.parse(projectJson);
await editorRef.value.loadProject(project);
```

## Settings Persistence

User preferences (brush colors, sizes, tool settings, last selected tools) are **automatically persisted** to localStorage. No manual save/restore code is needed.

### Automatic Persistence (Default)

```vue
<!-- Settings auto-saved to localStorage key "stimma-settings" -->
<StimmaEditor :plugins="plugins" src="/image.jpg" />
```

When the user changes a tool setting (color, brush size, etc.), it's automatically saved. On page reload, settings are restored including:
- The last used tool in annotate mode (e.g., if user was using "rectangle", it's pre-selected)
- The last used tool in retouch mode

### Custom Storage Prefix

Use `storage-prefix` to scope localStorage keys (useful when multiple editors or apps share the same domain):

```vue
<!-- Settings saved to "myapp-stimma-settings" -->
<StimmaEditor
  :plugins="plugins"
  src="/image.jpg"
  storage-prefix="myapp-"
/>
```

### Override Specific Settings

The `initial-settings` prop still works and takes precedence over persisted values:

```vue
<StimmaEditor
  :plugins="plugins"
  src="/image.jpg"
  :initial-settings="{ annotateStrokeColor: { r: 255, g: 0, b: 0, a: 1 } }"
/>
```

Order of precedence:
1. `initial-settings` prop (highest priority)
2. Persisted localStorage values
3. Default values (lowest priority)

### Manual Settings Access

You can still access settings programmatically if needed:

```typescript
// Get current settings
const settings = editorRef.value.getSettings();

// Apply settings (will also trigger auto-save)
editorRef.value.setState(settings);
```

### Settings Included

The `EditorSettings` type includes:

- **Annotation colors/stroke**: `annotateStrokeColor`, `annotateFillColor`, `annotateStrokeWidth`, `annotateBrushSettings`, `annotateIsEraser`, `annotatePenId`
- **Text settings**: `annotateTextFontFamily`, `annotateTextFontSize`, `annotateTextFontWeight`, `annotateTextFontStyle`, `annotateTextAlign`, `annotateTextBackgroundPadding`, `annotateTextBackgroundCornerRadius`, `annotateTextColor`, `annotateTextBgColor`
- **Redact settings**: `annotateRedactBlockSize`
- **Polygon settings**: `annotatePolygonSides`
- **Retouch settings**: `retouchBrushSettings`, `selectionFeather`, `wandTolerance`, `dodgeBurnExposure`, `dodgeBurnRange`, `spongeFlow`, `spongeMode`, `blurSharpenStrength`, `patchBlendWidth`, `retouchForegroundColor`, `retouchBackgroundColor`

Additionally persisted (not part of EditorSettings):
- **Last selected tools**: `lastAnnotateTool`, `lastRetouchTool`

## Complete Integration Pattern

```typescript
async function saveWork() {
  // 1. Rasterized image for display/sharing
  const rasterized = await editorRef.value.rasterize({
    format: 'image/jpeg',
    quality: 0.9,
  });

  // 2. Lossless project for future editing (no undo history for smaller size)
  const project = await editorRef.value.serialize({
    name: 'My Edit',
    includeHistory: false,
  });

  // 3. User settings for next session
  const settings = editorRef.value.getSettings();

  return { rasterized, project, settings };
}

async function loadWork(savedProject, savedSettings) {
  // Settings are applied via prop, project loaded after mount
  await editorRef.value.loadProject(savedProject);
}
```

## Available Plugins

| Plugin | Description |
|--------|-------------|
| `cropPlugin()` | Crop, rotate, flip, and transform images |
| `finetunePlugin()` | Adjust brightness, contrast, saturation, exposure, temperature, gamma |
| `filterPlugin()` | Apply preset color filters |
| `effectsPlugin()` | Add blur, sharpen, noise, glow, vignette, and other effects |
| `annotatePlugin()` | Draw shapes, text, arrows, and freehand annotations |
| `retouchPlugin()` | Clone stamp, healing brush, dodge/burn, blur/sharpen brushes |

## TypeScript Types

Import types for full type safety:

```typescript
import type {
  EditorState,
  EditorSettings,
  SerializedProject,
  SerializeOptions,
  ExportOptions,
  ProcessResult,
} from '@stimma/image-editor';
```

## Custom Toolbar Controls

You can replace the default "Done" and close ("x") buttons with your own controls using the `toolbar-end` slot:

```vue
<StimmaEditor
  ref="editorRef"
  :plugins="plugins"
  src="/path/to/image.jpg"
>
  <template #toolbar-end>
    <button @click="handleCancel">Cancel</button>
    <button @click="handleSave">Save</button>
    <button @click="handleSaveAsNew">Save as New</button>
  </template>
</StimmaEditor>
```

When using the slot, the default buttons are completely replaced, giving you full control over the toolbar's right side.

### Hiding Buttons Without Custom Controls

If you just want to hide the buttons without adding custom controls:

```vue
<StimmaEditor
  :show-close-button="false"
  :show-done-button="false"
  :plugins="plugins"
  src="/path/to/image.jpg"
/>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `src` | `ImageSource` | - | Image to load (URL, File, Blob, etc.) |
| `plugins` | `StimmaPlugin[]` | `[]` | Array of plugins to enable |
| `theme` | `'light' \| 'dark' \| 'auto'` | `'light'` | UI theme |
| `initialSettings` | `Partial<EditorSettings>` | - | Initial settings (overrides persisted) |
| `storagePrefix` | `string` | `''` | Prefix for localStorage key |
| `showCloseButton` | `boolean` | `true` | Show/hide the close (x) button |
| `showDoneButton` | `boolean` | `true` | Show/hide the Done button |

When hiding these buttons, use the exposed methods to handle export/close:

```typescript
// Trigger export programmatically
const result = await editorRef.value.rasterize();

// Handle close in your own UI
function handleClose() {
  // Your close logic
}
```

## Events

```vue
<StimmaEditor
  @load-start="onLoadStart"
  @load="onLoad"
  @load-error="onLoadError"
  @process-start="onProcessStart"
  @process="onProcess"
  @process-error="onProcessError"
  @update="onStateUpdate"
  @close="onClose"
  @revert="onRevert"
/>
```

## Exposed Methods

All methods available on the editor ref:

| Method | Description |
|--------|-------------|
| `loadImage(src)` | Load an image from any supported source |
| `rasterize(options?)` | Export the edited image as a Blob |
| `processImage(options?)` | Alias for `rasterize()` |
| `serialize(options?)` | Save project state for later restoration |
| `loadProject(project)` | Restore a saved project |
| `getSettings()` | Get current user preferences |
| `getState()` | Get current editor state |
| `setState(partial)` | Update editor state |
| `undo()` | Undo last action |
| `redo()` | Redo last undone action |
| `revert()` | Reset to original image |
| `getCanvas()` | Get the canvas element |
