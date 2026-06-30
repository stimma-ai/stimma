import { h } from 'vue'
import type { MediaType } from './mediaTypes'

/**
 * Centralized task type icons and labels
 * Used by: NavigationSidebar, SendToToolMenu, MediaContextMenu, AllToolsView
 */

/**
 * Improved task-generic glyphs (the 12 redrawn variants from the signed-off
 * icon-branding mock: plans/icon-branding/mocks/tool-icons.html `#tasks`).
 *
 * These are full inner-SVG fragments (multiple shapes, mixed fill/stroke) rather
 * than single path strings, because several glyphs (sparkle, brush, dashed
 * frame, corner-bracket upscalers) cannot be expressed as one path. The shared
 * `ToolIcon.vue` renders these via `getTaskTypeIconSvg()`. The legacy
 * single-path `TASK_TYPE_ICON_PATHS` map below is kept intact so existing
 * callers of `getTaskTypeIconPath()` / `createTaskTypeIconComponent()` keep
 * working unchanged.
 *
 * Each fragment expects a `viewBox="0 0 24 24"` wrapper with
 * `stroke="currentColor"`; embedded `fill="currentColor"` accents inherit the
 * tint. The `filter` glyph uses `#17171c` knockout dots to match the mock's
 * neutral tile; on a Cloud ring tile the dots read against the same dark inner
 * background, so this matches the mock exactly.
 */
export const TASK_TYPE_ICON_SVGS: Record<string, string> = {
  'text-to-image': '<rect x="3" y="3" width="18" height="18" rx="2.5"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="M21 15l-5-5L5 21"/><path d="M17.5 2.5l.6 1.5 1.5.6-1.5.6-.6 1.5-.6-1.5L15 5.1l1.5-.6z" fill="currentColor" stroke="none"/>',
  'image-to-image': '<rect x="2.5" y="5" width="10.5" height="10.5" rx="2"/><rect x="11" y="8.5" width="10.5" height="10.5" rx="2"/>',
  'inpaint-image': '<rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M14.5 8.5l-6 6a1.5 1.5 0 0 0-.4.7L7.5 17l1.8-.6a1.5 1.5 0 0 0 .7-.4l6-6z"/><path d="M14.5 8.5l1.8-1.8a1.1 1.1 0 0 1 1.6 1.6l-1.8 1.8z" fill="currentColor"/>',
  'outpaint-image': '<rect x="8.5" y="8.5" width="7" height="7" rx="1"/><path d="M5 8V5h3M16 5h3v3M19 16v3h-3M8 19H5v-3"/>',
  'text-to-video': '<rect x="2.5" y="6" width="15" height="12" rx="2"/><path d="M17.5 10l4-2.5v9l-4-2.5z"/><path d="M6 9.5h0.01M6 14.5h0.01"/>',
  'image-to-video': '<rect x="2.5" y="6" width="15" height="12" rx="2"/><path d="M17.5 10l4-2.5v9l-4-2.5z"/><path d="M8 9.5l4 2.5-4 2.5z" fill="currentColor" stroke="none"/>',
  'video-stitch': '<rect x="2.5" y="7" width="8" height="10" rx="1.5"/><rect x="13.5" y="7" width="8" height="10" rx="1.5"/><path d="M12 5v14" stroke-dasharray="2 2"/>',
  'video-extend': '<rect x="2.5" y="7" width="11" height="10" rx="1.5"/><path d="M16.5 12h5M19 9.5l2.5 2.5-2.5 2.5"/>',
  'upscale-image': '<path d="M4 8V5a1 1 0 0 1 1-1h3"/><path d="M20 8V5a1 1 0 0 0-1-1h-3"/><path d="M4 16v3a1 1 0 0 0 1 1h3"/><path d="M20 16v3a1 1 0 0 0-1 1h-3"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
  'upscale-video': '<path d="M4 8V5a1 1 0 0 1 1-1h3"/><path d="M20 8V5a1 1 0 0 0-1-1h-3"/><path d="M4 16v3a1 1 0 0 0 1 1h3"/><path d="M20 16v3a1 1 0 0 0-1 1h-3"/><path d="M10 9.2l5 2.8-5 2.8z" fill="currentColor" stroke="none"/>',
  'remove-background': '<rect x="3" y="3" width="18" height="18" rx="2.5" stroke-dasharray="3 2.5"/><circle cx="12" cy="10.5" r="3"/><path d="M6.5 19c1.1-2.6 3.1-4 5.5-4s4.4 1.4 5.5 4"/>',
  'filter': '<path d="M5 7h14M5 12h14M5 17h14"/><circle cx="9" cy="7" r="2" fill="#17171c"/><circle cx="15" cy="12" r="2" fill="#17171c"/><circle cx="8" cy="17" r="2" fill="#17171c"/>',
}

// Default task-generic glyph fragment for unknown task types (wrench).
export const DEFAULT_TASK_TYPE_ICON_SVG =
  '<path d="M14.7 6.3a4 4 0 0 0-5.2 5.2L4 17l3 3 5.5-5.5a4 4 0 0 0 5.2-5.2l-2.6 2.6-2.3-.6-.6-2.3z"/>'

/**
 * Get the improved task-generic glyph as an inner-SVG fragment for ToolIcon.
 * Wrap in `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ...>`.
 */
export function getTaskTypeIconSvg(taskType: string): string {
  return TASK_TYPE_ICON_SVGS[taskType] || DEFAULT_TASK_TYPE_ICON_SVG
}

// SVG path data for each task type (Heroicons outline style, 24x24 viewBox)
export const TASK_TYPE_ICON_PATHS: Record<string, string> = {
  'text-to-image': 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z',
  'image-to-image': 'm16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10',
  'inpaint-image': 'M9.53 16.122a3 3 0 0 0-5.78 1.128 2.25 2.25 0 0 1-2.4 2.245 4.5 4.5 0 0 0 8.4-2.245c0-.399-.078-.78-.22-1.128Zm0 0a15.998 15.998 0 0 0 3.388-1.62m-5.043-.025a15.994 15.994 0 0 1 1.622-3.395m3.42 3.42a15.995 15.995 0 0 0 4.764-4.648l3.876-5.814a1.151 1.151 0 0 0-1.597-1.597L14.146 6.32a15.996 15.996 0 0 0-4.649 4.763m3.42 3.42a6.776 6.776 0 0 0-3.42-3.42',
  'outpaint-image': 'M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15',
  'text-to-video': 'm15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z',
  'image-to-video': 'm15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z',
  'video-stitch': 'm15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z',
  'video-extend': 'm15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z',
  'upscale-image': 'M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15',
  'upscale-video': 'M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15',
  'remove-background': 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z',
}

// Gradient classes for each task type (used for icon backgrounds in AllToolsView, etc.)
export const TASK_TYPE_GRADIENT_CLASSES: Record<string, string> = {
  'text-to-image': 'bg-gradient-to-br from-violet-500/80 to-violet-700/80',
  'image-to-image': 'bg-gradient-to-br from-blue-500/80 to-blue-700/80',
  'inpaint-image': 'bg-gradient-to-br from-rose-500/80 to-rose-700/80',
  'outpaint-image': 'bg-gradient-to-br from-pink-500/80 to-pink-700/80',
  'text-to-video': 'bg-gradient-to-br from-emerald-500/80 to-emerald-700/80',
  'image-to-video': 'bg-gradient-to-br from-teal-500/80 to-teal-700/80',
  'video-stitch': 'bg-gradient-to-br from-cyan-500/80 to-cyan-700/80',
  'video-extend': 'bg-gradient-to-br from-sky-500/80 to-sky-700/80',
  'upscale-image': 'bg-gradient-to-br from-amber-500/80 to-amber-700/80',
  'upscale-video': 'bg-gradient-to-br from-orange-500/80 to-orange-700/80',
  'remove-background': 'bg-gradient-to-br from-indigo-500/80 to-indigo-700/80',
}

export const DEFAULT_TASK_TYPE_GRADIENT_CLASS = 'bg-gradient-to-br from-gray-500/80 to-gray-700/80'

/**
 * Get the gradient class for a task type icon background
 */
export function getTaskTypeGradientClass(taskType: string): string {
  return TASK_TYPE_GRADIENT_CLASSES[taskType] || DEFAULT_TASK_TYPE_GRADIENT_CLASS
}

// Default icon for unknown task types (wrench/tool icon)
export const DEFAULT_TASK_TYPE_ICON_PATH = 'M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z'

// Human-readable labels for each task type
export const TASK_TYPE_LABELS: Record<string, string> = {
  'text-to-image': 'Generate Image',
  'image-to-image': 'Image to Image',
  'inpaint-image': 'Inpaint',
  'outpaint-image': 'Outpaint',
  'text-to-video': 'Text to Video',
  'image-to-video': 'Image to Video',
  'video-stitch': 'Video Stitch',
  'video-extend': 'Video Extend',
  'upscale-image': 'Upscale Image',
  'upscale-video': 'Upscale Video',
  'remove-background': 'Background Removal',
  'detect-objects': 'Detect Objects',
  'filter': 'Filter',
  'utility': 'Utility',
}

// Display order for task type groups in menus
export const TASK_TYPE_ORDER = [
  'text-to-image',
  'image-to-image',
  'inpaint-image',
  'outpaint-image',
  'image-to-video',
  'text-to-video',
  'upscale-image',
  'remove-background',
  'upscale-video',
  'video-stitch',
  'video-extend',
]

// Task types that accept image input
export const IMAGE_INPUT_TASK_TYPES = [
  'image-to-image',
  'inpaint-image',
  'outpaint-image',
  'image-to-video',
  'upscale-image',
  'remove-background',
]

// Task types that accept video input
export const VIDEO_INPUT_TASK_TYPES = [
  'upscale-video',
  'video-stitch',
  'video-extend',
]

// Task types that accept audio input (none currently)
export const AUDIO_INPUT_TASK_TYPES: string[] = []

// Task types that accept text/document input (none currently)
export const TEXT_INPUT_TASK_TYPES: string[] = []

/**
 * Get eligible task types for a given media type.
 * Returns an empty array for unsupported media types (audio, text, grid).
 * Sets default to image task types (caller should pass actual content type when known).
 */
export function getEligibleTaskTypesForMediaType(mediaType: MediaType | null): string[] {
  switch (mediaType) {
    case 'image':
      return IMAGE_INPUT_TASK_TYPES
    case 'video':
      // A video can be used anywhere an image can (we grab a frame), in addition to
      // video-only tools (upscale/extend/stitch). Keeps drag/send affordances from
      // graying out image tools when dragging a video.
      return Array.from(new Set([...VIDEO_INPUT_TASK_TYPES, ...IMAGE_INPUT_TASK_TYPES]))
    case 'set':
      // Sets default to image tools; caller should pass actual content type when known
      return IMAGE_INPUT_TASK_TYPES
    case 'audio':
      return AUDIO_INPUT_TASK_TYPES
    case 'text':
      return TEXT_INPUT_TASK_TYPES
    case 'grid':
    case null:
    default:
      return []
  }
}

/**
 * Check if a tool is compatible with a given media type.
 * Returns { compatible, reason } for use in compatibility maps.
 */
export function isToolCompatibleWithMediaType(
  tool: { task_type?: string; task_types?: string[] },
  mediaType: MediaType | null
): { compatible: boolean; reason?: string } {
  // Grids cannot be sent to any tool
  if (mediaType === 'grid') {
    return { compatible: false, reason: 'Grids cannot be sent to tools' }
  }

  const eligibleTaskTypes = getEligibleTaskTypesForMediaType(mediaType)

  // If no eligible task types (audio, text), tool is incompatible
  if (eligibleTaskTypes.length === 0) {
    const label = mediaType || 'this type'
    return { compatible: false, reason: `No tools support ${label} input` }
  }

  const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
  const hasEligibleTaskType = toolTaskTypes.some(tt => eligibleTaskTypes.includes(tt))

  if (!hasEligibleTaskType) {
    return {
      compatible: false,
      reason: mediaType === 'video' ? 'Tool does not accept video input' : 'Tool does not accept image input'
    }
  }

  return { compatible: true }
}

/**
 * Get the SVG path for a task type icon
 */
export function getTaskTypeIconPath(taskType: string): string {
  return TASK_TYPE_ICON_PATHS[taskType] || DEFAULT_TASK_TYPE_ICON_PATH
}

/**
 * Get the human-readable label for a task type
 */
export function formatTaskTypeLabel(taskType: string): string {
  return TASK_TYPE_LABELS[taskType] || taskType
}

/**
 * Create a Vue component that renders a task type icon as SVG
 * Useful for dynamic component rendering with :is
 *
 * @param taskType - The task type key
 * @param strokeColor - The stroke color (can be 'currentColor' or a gradient URL)
 */
export function createTaskTypeIconComponent(taskType: string, strokeColor: string = 'currentColor') {
  const pathData = getTaskTypeIconPath(taskType)

  return {
    render() {
      return h('svg', {
        fill: 'none',
        viewBox: '0 0 24 24',
        'stroke-width': '2',
        stroke: strokeColor,
        overflow: 'visible'
      }, [
        h('path', {
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          d: pathData
        })
      ])
    }
  }
}
