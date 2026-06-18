import { useRouter } from 'vue-router'
import axios from 'axios'
import { analyzeToolMultiInputCapability } from '../utils/toolSchemaUtils'
import { makeToolDbKey } from '../utils/storageKeys'

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
   * @returns Promise that resolves when navigation completes
   */
  async function sendToTool(
    mediaIdOrItems: number | MediaItem | MediaItem[],
    tool: Pick<Tool, 'full_tool_id' | 'task_type'> & { parameter_schema?: Record<string, any> },
    targetTaskType?: string,
    projectId?: number | null
  ) {
    // Use the target task type if provided, otherwise fall back to tool's primary task type
    const effectiveTaskType = targetTaskType || tool.task_type
    // Normalize to array
    let mediaItems: MediaItem[]
    if (typeof mediaIdOrItems === 'number') {
      const mediaResponse = await axios.get(`/api/media/${mediaIdOrItems}`)
      mediaItems = [mediaResponse.data]
    } else if (Array.isArray(mediaIdOrItems)) {
      mediaItems = mediaIdOrItems
    } else {
      mediaItems = [mediaIdOrItems]
    }

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
        let path = mediaItem.file_path
        let filename: string | undefined

        try {
          const endpoint = isVideo
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

    // Infer project context from current route if not explicitly provided
    const route = router.currentRoute.value
    const effectiveProjectId = projectId ?? (
      route.params.id && String(route.name || '').startsWith('project-')
        ? Number(route.params.id)
        : null
    )

    // Project-scoped pending-input key. ToolView keeps a separate KeepAlive'd
    // instance per (tool, project) and reads a matching scoped key, so the
    // project-entangled tool and the global tool never race to consume the same
    // handoff. Must mirror ToolView's scopedToolId(): `${id}__project_${pid}`.
    const scopedToolId = effectiveProjectId
      ? `${tool.full_tool_id}__project_${effectiveProjectId}`
      : tool.full_tool_id
    const storageKey = makeToolDbKey(scopedToolId, 'pending_input')

    // Check if tool supports multi-input via schema
    const multiInputInfo = tool.parameter_schema
      ? analyzeToolMultiInputCapability(tool as any)
      : null

    // image-to-video: use startImage if tool has videoFramePicker or start_image in schema
    const hasStartImage = tool.parameter_schema?.properties?.start_image
    const hasVideoFramePicker = tool.parameter_schema?.properties?.input_images?.['x-control'] === 'video_frame_picker'
    if (effectiveTaskType === 'image-to-video' && (hasStartImage || hasVideoFramePicker)) {
      sessionStorage.setItem(storageKey, JSON.stringify({ startImage: mediaEntries[0] }))
    } else if (multiInputInfo?.supportsMultiInput) {
      // Schema-driven: tool explicitly accepts arrays
      if (multiInputInfo.inputType === 'videos') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: mediaEntries, appendVideos: true }))
      } else {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputImages: mediaEntries, appendImages: true }))
      }
    } else {
      // Fall back to task_type based logic for single-input tools
      // Check if tool schema has input_image for generic single-image tools (e.g., bg removal)
      const hasInputImage = tool.parameter_schema?.properties?.input_image

      if (['image-to-image', 'upscale-image', 'inpaint-image', 'outpaint-image', 'remove-background'].includes(effectiveTaskType) || hasInputImage) {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputImages: mediaEntries, appendImages: true }))
      } else if (effectiveTaskType === 'upscale-video' || effectiveTaskType === 'video-extend') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: mediaEntries }))
      } else if (effectiveTaskType === 'video-stitch') {
        sessionStorage.setItem(storageKey, JSON.stringify({ inputVideos: mediaEntries }))
      }
    }

    // Add timestamp to force route change detection (important for KeepAlive'd components)
    const query: Record<string, string> = { loadInput: Date.now().toString() }
    if (effectiveProjectId) {
      query.project_id = String(effectiveProjectId)
    }
    router.push({ name: 'tool', params: { fullToolId: tool.full_tool_id }, query })
  }

  return {
    sendToTool
  }
}
