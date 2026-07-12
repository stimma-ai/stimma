import { useRouter } from 'vue-router'
import axios from 'axios'
import {
  analyzeToolMultiInputCapability,
  getBatchableMediaField,
  getSingleInputMediaType,
  toolRequiresMask,
} from '../utils/toolSchemaUtils'
import { makeToolDbKey } from '../utils/storageKeys'
import { getMediaType } from '../utils/mediaTypes'
import { planToolHandoff, ToolHandoffError } from '../utils/toolHandoff'
import { useWorkspaceTabs, toolInstanceScopedId, toolInstanceRoute } from './useWorkspaceTabs'

interface MediaEntry {
  mediaId?: number
  hash: string
  path: string
  filename?: string
  width?: number
  height?: number
  // Set-specific fields
  isSet?: boolean
  setItemCount?: number
  setId?: number
}

interface Tool {
  full_tool_id: string
  task_type: string
  parameter_schema?: Record<string, any>
  [key: string]: any
}

interface MediaItem {
  id: number
  file_path: string
  file_hash: string
  file_format?: string
  is_video?: boolean
  width?: number
  height?: number
  member_count?: number
  raw_metadata?: string
}

/**
 * Composable for "Send to Tool" functionality.
 * Used by MediaContextMenu, MultiSelectActionBar, and NavigationSidebar drag-drop.
 */
export function useSendToTool() {
  const router = useRouter()

  /**
   * Send one or more media items to a tool.
   * @param mediaIdOrItems - A media ID, MediaItem, or array of MediaItems
   * @param tool - The target tool (needs full_tool_id, task_type, and optionally parameter_schema)
   * @param targetTaskType - Optional task type override (for tools with multiple task types,
   *                         use this to specify which facet was selected)
   * @param opts.add - Add to the tool's existing inputs instead of replacing them
   *                   (shift-drag / shift-click). Default is replace: an untargeted
   *                   send means "this is the input now".
   * @returns Promise that resolves when navigation completes
   */
  async function sendToTool(
    mediaIdOrItems: number | MediaItem | Array<number | MediaItem>,
    tool: Pick<Tool, 'full_tool_id' | 'task_type'> & Partial<Tool>,
    targetTaskType?: string,
    projectId?: number | null,
    instanceId?: string | null,
    opts?: { add?: boolean }
  ) {
    const add = opts?.add === true
    // Use the target task type if provided, otherwise fall back to tool's primary task type
    let effectiveTaskType = targetTaskType || tool.task_type
    // Normalize to an array of full MediaItem records (fetching any bare IDs).
    const fetchItem = async (v: number | MediaItem): Promise<MediaItem> =>
      typeof v === 'number' || !v.file_format
        ? (await axios.get(`/api/media/${typeof v === 'number' ? v : v.id}`)).data
        : v
    let mediaItems: MediaItem[]
    if (Array.isArray(mediaIdOrItems)) {
      mediaItems = await Promise.all(mediaIdOrItems.map(fetchItem))
    } else {
      mediaItems = [await fetchItem(mediaIdOrItems)]
    }

    // Some callers (e.g. the sidebar tab map) pass a lightweight tool object
    // without parameter_schema. Batch detection needs the schema to see the
    // media slot, so fetch the full tool when it's missing.
    if (!tool.parameter_schema?.properties) {
      try {
        const { data } = await axios.get(`/api/tools/provider-tool/${encodeURIComponent(tool.full_tool_id)}`)
        if (data?.parameter_schema) {
          ;(tool as any).parameter_schema = data.parameter_schema
        }
      } catch (e) {
        console.warn('Failed to fetch tool schema for send-to-tool:', e)
      }
    }

    // Resolve structured members for accurate type planning. A video set must
    // target video tools in every UI, while the set itself still counts as one
    // transfer for the existing set/batch semantics below.
    const structuredMembers = new Map<number, MediaItem[]>()
    const planningItems: MediaItem[] = []
    for (const item of mediaItems) {
      const fmt = item.file_format
      if (fmt === 'stimmagrid.json') {
        throw new ToolHandoffError('Grids cannot be sent to tools')
      }
      if (fmt !== 'stimmaset.json' && fmt !== 'stimmagrid.json') {
        planningItems.push(item)
        continue
      }
      try {
        const { data } = await axios.get(`/api/media/${item.id}/content`)
        const members = fmt === 'stimmaset.json' ? (data.items || []) : (data.cells || [])
        const resolvedItems = members
          .filter((member: any) => member.resolved?.media_id || member.resolved?.id)
          .map((member: any) => ({
            ...member.resolved,
            id: member.resolved.media_id ?? member.resolved.id,
            file_path: member.resolved.file_path ?? member.path,
            file_hash: member.resolved.file_hash,
            file_format: member.resolved.file_format,
            is_video: member.resolved.is_video,
            is_audio: member.resolved.is_audio,
            width: member.resolved.width,
            height: member.resolved.height,
          }))
        structuredMembers.set(item.id, resolvedItems)
        planningItems.push(...(resolvedItems.length > 0 ? resolvedItems : [item]))
      } catch (e) {
        console.warn('Failed to inspect structured media for handoff:', e)
        planningItems.push(item)
      }
    }

    const plan = planToolHandoff({
      tool,
      items: planningItems,
      count: mediaItems.length,
      requestedTaskType: targetTaskType,
    })
    if (!plan.eligible || !plan.taskType) {
      throw new ToolHandoffError(plan.reason || 'These assets cannot be sent to this tool')
    }
    effectiveTaskType = plan.taskType

    // Batch detection: per the plan, N items in ONE media slot = a batch (run the
    // tool once per item). This holds whether the slot is single-valued or an
    // array (e.g. Flux's input_images): an array slot with multiple items is a
    // batch, not a single multi-reference run. Use "explode batch" to turn a
    // batch back into ordinary multi-reference inputs.
    //
    // Exception that stays single: the image-to-video start/end frame picker.
    const multiInputInfo = tool.parameter_schema
      ? analyzeToolMultiInputCapability(tool as any)
      : null
    const props = tool.parameter_schema?.properties || {}
    const batchField = getBatchableMediaField(tool as any)
    const hasStartImageSlot = !!props.start_image
    const hasVideoFramePicker = props.input_images?.['x-control'] === 'video_frame_picker'
    const isI2VStart = effectiveTaskType === 'image-to-video' && (hasStartImageSlot || hasVideoFramePicker)
    // A slot that *requires* multiple inputs (minItems > 1, e.g. a 2-image blend)
    // fills one run instead of batching.
    const slotMin = multiInputInfo?.minItems ?? 1
    const canMediaBatch = !!batchField && !isI2VStart && !toolRequiresMask(tool as any) && slotMin <= 1

    // Expand selected sets/grids before deciding whether this is a batch. A
    // single structured asset with N members is a batch input convenience, not
    // the set-based output-set batch path.
    if (canMediaBatch && mediaItems.some(item => item.file_format === 'stimmaset.json' || item.file_format === 'stimmagrid.json')) {
      const expanded: MediaItem[] = []
      for (const item of mediaItems) {
        const fmt = item.file_format
        if (fmt === 'stimmaset.json' || fmt === 'stimmagrid.json') {
          expanded.push(...(structuredMembers.get(item.id) || []))
        } else {
          expanded.push(item)
        }
      }
      if (expanded.length > 0) mediaItems = expanded
    }

    const wantBatch = canMediaBatch && mediaItems.length > 1

    // Process all items - copy to reference directory (unless it's a set)
    const mediaEntries: MediaEntry[] = []
    for (const mediaItem of mediaItems) {
      // Check if this is a set
      const isSet = mediaItem.file_format === 'stimmaset.json'

      if (isSet) {
        // For sets, don't copy to reference - pass set reference directly
        // Get item count from member_count or parse raw_metadata
        let itemCount = mediaItem.member_count || 0
        if (!itemCount && mediaItem.raw_metadata) {
          try {
            const setData = JSON.parse(mediaItem.raw_metadata)
            itemCount = setData.items?.length || 0
          } catch (e) {
            console.warn('Failed to parse set raw_metadata:', e)
          }
        }

        mediaEntries.push({
          mediaId: mediaItem.id,
          hash: mediaItem.file_hash,
          path: mediaItem.file_path,
          filename: mediaItem.file_path.split('/').pop(),
          isSet: true,
          setItemCount: itemCount,
          setId: mediaItem.id
        })
      } else {
        // Regular media - copy to reference directory
        const isVideo = mediaItem.is_video || false
        const isAudio = mediaItem.is_audio || false
        let path = mediaItem.file_path
        let filename: string | undefined

        try {
          const endpoint = isAudio
            ? `/api/generate/copy-audio-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
            : isVideo
            ? `/api/generate/copy-video-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
            : `/api/generate/copy-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
          const copyResponse = await axios.post(endpoint)
          path = copyResponse.data.path
          filename = copyResponse.data.filename
        } catch (error) {
          console.warn('Failed to copy to reference, using original path:', error)
        }

        mediaEntries.push({
          mediaId: mediaItem.id,
          hash: mediaItem.file_hash,
          path,
          filename,
          width: mediaItem.width,
          height: mediaItem.height
        })
      }
    }

    // Infer project context from current route if not explicitly provided.
    // An explicit instance target already pins the full (tool, project,
    // instance) triple — its caller passed the tab's own projectId (possibly
    // null for a global tab), which must NOT be overridden by route inference
    // or the handoff key/route would address a different instance.
    const route = router.currentRoute.value
    const effectiveProjectId = instanceId != null
      ? (projectId ?? null)
      : projectId ?? (
        route.params.id && String(route.name || '').startsWith('project-')
          ? Number(route.params.id)
          : null
      )

    // Resolve the target INSTANCE: an explicit one (sidebar row drop, menu
    // instance pick) wins; otherwise the most-recently-active open instance
    // matching (tool, project), opening a fresh one only when none exists.
    // The pending-input key mirrors ToolView's scopedToolId() (project +
    // instance suffixes) so sibling instances never race to consume a handoff.
    const { resolveToolInstance } = useWorkspaceTabs()
    const targetInstanceId = instanceId
      ?? resolveToolInstance(tool.full_tool_id, effectiveProjectId).instanceId
    const scopedToolId = toolInstanceScopedId(tool.full_tool_id, effectiveProjectId, targetInstanceId)
    const storageKey = makeToolDbKey(scopedToolId, 'pending_input')
    const targetRoute = (extra: Record<string, string>) =>
      toolInstanceRoute(tool.full_tool_id, effectiveProjectId, targetInstanceId, extra)

    // Media-batch: run the single-input tool once per item in one slot. Mark the
    // slot as a batch; ToolView enters batch mode and Run submits one job per item.
    if (wantBatch) {
      sessionStorage.setItem(storageKey, JSON.stringify({
        mode: 'batch',
        field: batchField,
        items: mediaEntries,
      }))
      router.push(targetRoute({ loadInput: Date.now().toString() }))
      return
    }

    // The dragged media's OWN type decides its slot. Audio must land in the audio
    // slot, never the visual one: avatar/lip-sync tools have both an image/video
    // (face) slot and an audio slot, and analyzeToolMultiInputCapability
    // deliberately reports the VISUAL slot — so without this an audio drop would
    // wrongly fill input_images.
    const sendsAudio = mediaItems.some(m => getMediaType({ file_format: m.file_format }) === 'audio')
    const hasAudioSlot = !!props.input_audios

    // image-to-video: use startImage if tool has videoFramePicker or start_image in schema
    // (hasStartImageSlot / hasVideoFramePicker computed above with batch detection)
    if (sendsAudio && hasAudioSlot) {
      sessionStorage.setItem(storageKey, JSON.stringify({ inputAudios: mediaEntries, append: add }))
    } else if (effectiveTaskType === 'image-to-video' && (hasStartImageSlot || hasVideoFramePicker)) {
      sessionStorage.setItem(storageKey, JSON.stringify({ startImage: mediaEntries[0], append: add }))
    } else if (multiInputInfo?.supportsMultiInput) {
      // Schema-driven: tool explicitly accepts arrays. The array shape is the
      // STP canonical form for ALL media slots — capacity lives in
      // x-max-items — so cap the payload at the slot's declared capacity.
      const slotMax = multiInputInfo.maxItems
      const entries = Number.isFinite(slotMax) ? mediaEntries.slice(0, slotMax) : mediaEntries
      if (multiInputInfo.inputType === 'videos') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: entries, append: add }))
      } else if (multiInputInfo.inputType === 'audios') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputAudios: entries, append: add }))
      } else {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputImages: entries, append: add }))
      }
    } else {
      // Fall back to task_type based logic for single-input tools
      // Check if tool schema has input_image for generic single-image tools (e.g., bg removal)
      const hasInputImage = tool.parameter_schema?.properties?.input_image

      if (['image-to-image', 'upscale-image', 'inpaint-image', 'outpaint-image', 'remove-background'].includes(effectiveTaskType) || hasInputImage) {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputImages: mediaEntries, append: add }))
      } else if (effectiveTaskType === 'upscale-video' || effectiveTaskType === 'video-to-video' || effectiveTaskType === 'video-extend') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: mediaEntries, append: add }))
      } else if (effectiveTaskType === 'video-stitch') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: mediaEntries, append: add }))
      }
    }

    // Add timestamp to force route change detection (important for KeepAlive'd components)
    router.push(targetRoute({ loadInput: Date.now().toString() }))
  }

  return {
    sendToTool
  }
}
