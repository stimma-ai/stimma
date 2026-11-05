/**
 * Catalog facts the All tools screen filters and compares on. Every fact here
 * is read from data every tool carries: its declared media input slots (the
 * schema, or a catalog summary's parameter outline) and its task types.
 * Nothing is a tool-level tag that only some providers fill in.
 */
import { AUDIO_TASK_TYPES, getToolDeclaredAcceptMedia } from './taskTypeIcons.ts'
import type { ToolSchemaSource } from './toolSchemaUtils.ts'

export type MediaKind = 'image' | 'video' | 'audio'

type FacetTool = ToolSchemaSource & { task_type?: string | null; task_types?: string[] | null }

const MEDIA_ORDER: MediaKind[] = ['image', 'video', 'audio']

/**
 * The media a tool accepts as input, in image, video, audio order. Empty for a
 * tool with no media slot (text in); null when the catalog entry carries no
 * schema or outline at all, so nothing is known.
 */
export function toolTakes(tool: FacetTool): MediaKind[] | null {
  const accepted = getToolDeclaredAcceptMedia(tool)
  if (!accepted) return null
  return MEDIA_ORDER.filter(kind => accepted.has(kind))
}

/** True when the tool's task is speech, music or sound (the app's audio-output task types). */
export function toolMakesAudio(tool: FacetTool): boolean {
  const types = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
  return types.some(type => (AUDIO_TASK_TYPES as readonly string[]).includes(type))
}

export interface MediaFilterOption {
  id: string
  group: 'takes' | 'makes'
  label: string
}

export const MEDIA_FILTER_OPTIONS: MediaFilterOption[] = [
  { id: 'takes:image', group: 'takes', label: 'Image' },
  { id: 'takes:video', group: 'takes', label: 'Video' },
  { id: 'takes:audio', group: 'takes', label: 'Audio' },
  { id: 'makes:audio', group: 'makes', label: 'Speech, music, sound' },
]

export function toolMatchesMediaFilter(tool: FacetTool, id: string): boolean {
  if (id === 'makes:audio') return toolMakesAudio(tool)
  if (id.startsWith('takes:')) return !!toolTakes(tool)?.includes(id.slice('takes:'.length) as MediaKind)
  return false
}

/** A tool passes when it matches every selected option; nothing selected passes all. */
export function toolMatchesMediaFilters(tool: FacetTool, selected: ReadonlySet<string>): boolean {
  for (const id of selected) if (!toolMatchesMediaFilter(tool, id)) return false
  return true
}

/** The card fact for a tool's media input ("takes image, audio"); '' when it takes none. */
export function takesFact(tool: FacetTool): string {
  const takes = toolTakes(tool)
  return takes?.length ? `takes ${takes.join(', ')}` : ''
}
