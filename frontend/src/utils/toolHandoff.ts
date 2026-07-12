import type { ProviderTool } from '../composables/useProvidersApi'
import { getMediaType, type MediaType } from './mediaTypes.ts'
import { TASK_INPUT_MEDIA, getEligibleTaskTypesForMediaType, isToolCompatibleWithMediaType } from './taskTypeIcons.ts'
import { isSelectionValidForTool } from './toolSchemaUtils.ts'

export interface HandoffMediaItem {
  id?: number
  file_format?: string
  is_video?: boolean
  is_audio?: boolean
}

export interface ToolHandoffPlan {
  eligible: boolean
  reason?: string
  taskType?: string
  mediaTypes: MediaType[]
  count: number
}

function mediaTypeForItem(item: HandoffMediaItem): MediaType | null {
  if (item.is_audio) return 'audio'
  if (item.is_video) return 'video'
  if (!item.file_format) return null
  return getMediaType({ file_format: item.file_format })
}

function uniqueMediaTypes(types: Array<MediaType | null>): MediaType[] {
  return Array.from(new Set(types.filter((type): type is MediaType => type != null)))
}

/**
 * The authoritative decision for every "send assets to tool" affordance.
 * UI surfaces use this to render eligibility; useSendToTool runs it again after
 * resolving full media records and the latest tool schema before committing the
 * handoff. Keeping task choice and count/type validation here prevents sidebar
 * drops and menu clicks from drifting apart.
 */
export function planToolHandoff({
  tool,
  items = [],
  mediaTypes,
  count,
  requestedTaskType,
}: {
  tool: Pick<ProviderTool, 'task_type'> & Partial<ProviderTool>
  items?: HandoffMediaItem[]
  mediaTypes?: MediaType[]
  count?: number
  requestedTaskType?: string
}): ToolHandoffPlan {
  const resolvedTypes = uniqueMediaTypes(mediaTypes ?? items.map(mediaTypeForItem))
  const selectionCount = count ?? items.length

  if (tool.availability && tool.availability !== 'available') {
    const reason = tool.availability === 'disconnected'
      ? 'Tool provider is disconnected'
      : 'Tool provider is not configured'
    return { eligible: false, reason, mediaTypes: resolvedTypes, count: selectionCount }
  }
  if (selectionCount < 1) {
    return { eligible: false, reason: 'No assets selected', mediaTypes: resolvedTypes, count: selectionCount }
  }
  if (resolvedTypes.length === 0) {
    return { eligible: false, reason: 'Checking media compatibility…', mediaTypes: resolvedTypes, count: selectionCount }
  }
  if (resolvedTypes.includes('grid')) {
    return { eligible: false, reason: 'Grids cannot be sent to tools', mediaTypes: resolvedTypes, count: selectionCount }
  }
  const unsupported = resolvedTypes.find(type => type === 'text' || type === 'layout')
  if (unsupported) {
    return { eligible: false, reason: `No tools support ${unsupported} input`, mediaTypes: resolvedTypes, count: selectionCount }
  }

  // A single handoff targets one media slot. Visual mixtures are valid because
  // videos can be frame-grabbed into image slots; audio + visual would require
  // independently targeting multiple slots and must be an explicit future UX.
  const hasAudio = resolvedTypes.includes('audio')
  const hasVisual = resolvedTypes.some(type => type === 'image' || type === 'video' || type === 'set')
  if (hasAudio && hasVisual) {
    return { eligible: false, reason: 'Send audio and visual assets separately', mediaTypes: resolvedTypes, count: selectionCount }
  }

  const toolTaskTypes = tool.task_types?.length
    ? tool.task_types
    : (tool.task_type ? [tool.task_type] : [])
  const candidates = requestedTaskType
    ? [requestedTaskType]
    : [...toolTaskTypes].sort((a, b) => {
        const directScore = (taskType: string) => resolvedTypes.reduce((score, type) => {
          const normalized = type === 'set' ? 'image' : type
          return score + (TASK_INPUT_MEDIA[taskType]?.includes(normalized as 'image' | 'video' | 'audio') ? 1 : 0)
        }, 0)
        return directScore(b) - directScore(a)
      })
  if (requestedTaskType && !toolTaskTypes.includes(requestedTaskType)) {
    return { eligible: false, reason: 'Tool does not provide that task', mediaTypes: resolvedTypes, count: selectionCount }
  }

  const taskType = candidates.find(candidate => {
    const facet = { ...tool, task_type: candidate, task_types: [candidate] }
    return resolvedTypes.every(type => {
      const eligibleTasks = getEligibleTaskTypesForMediaType(type)
      return eligibleTasks.includes(candidate) && isToolCompatibleWithMediaType(facet, type).compatible
    })
  })
  if (!taskType) {
    const label = resolvedTypes.join('/')
    return { eligible: false, reason: `Tool does not accept ${label} input`, mediaTypes: resolvedTypes, count: selectionCount }
  }

  // For a visual mixture, the image is the restrictive member: video can feed
  // an image slot, but an image cannot feed a video-only slot.
  const validationType: MediaType = hasAudio
    ? 'audio'
    : resolvedTypes.some(type => type === 'image' || type === 'set') ? 'image' : 'video'
  const validation = isSelectionValidForTool(tool as ProviderTool, selectionCount, validationType)
  if (!validation.valid) {
    return { eligible: false, reason: validation.reason, taskType, mediaTypes: resolvedTypes, count: selectionCount }
  }

  return { eligible: true, taskType, mediaTypes: resolvedTypes, count: selectionCount }
}

export class ToolHandoffError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ToolHandoffError'
  }
}
