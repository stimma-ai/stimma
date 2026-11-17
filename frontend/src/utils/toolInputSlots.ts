/**
 * Where media handed to a tool lands, and how it combines with what the tool
 * already holds. Shared by the sidebar's tool-tab drop targets (which read a
 * tool's slots to offer "replace image 2") and ToolView (which applies the
 * handoff). Pure: no storage, no Vue.
 */

import { analyzeToolMultiInputCapability, toolParameterProperties, type ToolSchemaSource } from './toolSchemaUtils.ts'

export type ToolInputField = 'inputImages' | 'inputVideos' | 'inputAudios' | 'frames'

export interface ToolDropSlot {
  field: ToolInputField
  /** How many items the slot holds (Infinity when the schema sets no limit). */
  max: number
}

/**
 * The slot a send-to-tool of this media type fills. Mirrors the routing in
 * useSendToTool so the drop targets describe where the drop really goes.
 */
export function toolDropSlot(
  tool: ToolSchemaSource & { task_type?: string },
  draggedType: string | null | undefined,
): ToolDropSlot | null {
  const props = toolParameterProperties(tool) || {}
  if (draggedType === 'audio' && props.input_audios) {
    const prop = props.input_audios
    const max = prop.type === 'array' ? (prop.maxItems ?? prop['x-max-items'] ?? Infinity) : 1
    return { field: 'inputAudios', max }
  }
  const taskType = tool.task_type
  if (taskType === 'image-to-video' && (props.start_image || props.input_images?.['x-control'] === 'video_frame_picker')) {
    return { field: 'frames', max: 2 }
  }
  const multi = analyzeToolMultiInputCapability(tool)
  if (multi.supportsMultiInput) {
    const field: ToolInputField = multi.inputType === 'videos' ? 'inputVideos' : multi.inputType === 'audios' ? 'inputAudios' : 'inputImages'
    return { field, max: multi.maxItems }
  }
  if (props.input_image || ['image-to-image', 'upscale-image', 'inpaint-image', 'erase-image', 'outpaint-image', 'remove-background'].includes(taskType ?? '')) {
    return { field: 'inputImages', max: 1 }
  }
  if (['upscale-video', 'video-to-video', 'video-extend', 'video-stitch'].includes(taskType ?? '')) {
    return { field: 'inputVideos', max: 1 }
  }
  return null
}

export interface SlotThumb {
  mediaId?: number
  hash?: string
}

/** What a stored slot item shows as: its library media, or the video a frame came from. */
function thumbOf(item: any): SlotThumb | null {
  if (!item || typeof item !== 'object') return null
  const mediaId = typeof item.mediaId === 'number' ? item.mediaId : item._videoSource?.mediaId
  const hash = item.hash ?? item._videoSource?.hash
  if (typeof mediaId !== 'number' && typeof hash !== 'string') return {}
  return { mediaId: typeof mediaId === 'number' ? mediaId : undefined, hash: typeof hash === 'string' ? hash : undefined }
}

/**
 * The filled slots of a tool tab, from its saved working state (and, for
 * start/end frame tools, its saved frames). Null when the state can't say
 * (nothing saved, or a batch, where slots aren't individually replaceable).
 */
export function filledSlots(
  field: ToolInputField,
  state: Record<string, any> | null,
  frames?: { startImage?: any; endImage?: any } | null,
): SlotThumb[] | null {
  if (field === 'frames') {
    if (!frames) return state ? [] : null
    return [frames.startImage, frames.endImage].filter(Boolean).map(f => thumbOf(f) ?? {})
  }
  if (!state) return null
  if (state.batchMode) return null
  const items = state[field]
  if (!Array.isArray(items)) return []
  return items.map(item => thumbOf(item) ?? {})
}

export interface MergeOptions {
  append?: boolean
  /** Replace just this slot; every other slot keeps its item (and its prep). */
  replaceIndex?: number | null
  max: number
}

/**
 * Combine incoming media with a slot's current items. Replace-at-index keeps
 * the other items as the very same objects, so their crop/scale/paint survive.
 * A replace index past the end appends, when there is room.
 */
export function mergeSlotItems<T>(existing: T[], incoming: T[], opts: MergeOptions): T[] {
  const max = opts.max > 0 ? opts.max : 1
  const index = opts.replaceIndex
  if (typeof index === 'number' && index >= 0 && incoming.length > 0) {
    if (index < existing.length) {
      const next = [...existing]
      next[index] = incoming[0]
      return next
    }
    return [...existing, incoming[0]].slice(0, max)
  }
  if (opts.append && max > 1) return [...existing, ...incoming].slice(0, max)
  return incoming.slice(0, max)
}
