import { onBeforeUnmount, ref } from 'vue'
import { getDroppedMediaIds } from './useDragPreview'
import { useMediaApi } from './useMediaApi'
import { useWorkingContext } from './useWorkingContext'
import { addToast } from './useToasts'

/** True when the drag carries library media (not files or text). */
export function isMediaDrag(event: DragEvent) {
  return !!event.dataTransfer?.types.includes('application/x-media-id')
}

/**
 * Project rows as drop targets: dropping library media adds it to that
 * project (from anywhere, including from inside another project). Shared by
 * the sidebar's recent rows and every row of the project picker.
 */
export function useProjectDrop() {
  const { projects } = useWorkingContext()
  const { addMediaToProject } = useMediaApi()
  const dropTarget = ref<number | null>(null)

  function onDragOver(projectId: number, event: DragEvent) {
    if (!isMediaDrag(event)) return
    event.preventDefault()
    event.dataTransfer!.dropEffect = 'copy'
    dropTarget.value = projectId
  }

  function onDragLeave(projectId: number) {
    if (dropTarget.value === projectId) dropTarget.value = null
  }

  async function onDrop(projectId: number, event: DragEvent) {
    event.preventDefault()
    dropTarget.value = null
    const mediaIds = getDroppedMediaIds(event.dataTransfer)
    if (!mediaIds.length) return
    const noun = mediaIds.length === 1 ? 'asset' : 'assets'
    try {
      await addMediaToProject(projectId, mediaIds)
      const name = projects.value.find(p => p.id === projectId)?.name || 'Untitled project'
      addToast(`Added ${mediaIds.length} ${noun} to ${name}`, 'success')
    } catch {
      addToast('Could not add to the project.', 'warning')
    }
  }

  return { dropTarget, onDragOver, onDragLeave, onDrop }
}

/**
 * Hovering a trigger with dragged media for a moment opens what it opens
 * (the project picker), so the rows inside can take the drop.
 */
export function useDragHoverOpen(open: () => void, delay = 500) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let fired = false
  function cancel() {
    if (timer) { clearTimeout(timer); timer = null }
    fired = false
  }
  function onDragEnter(event: DragEvent) {
    if (!isMediaDrag(event) || timer || fired) return
    timer = setTimeout(() => { timer = null; fired = true; open() }, delay)
  }
  // The trigger is not a drop target itself; it only arms the timer.
  const onDragOver = onDragEnter
  function onDragLeave(event: DragEvent) {
    const next = event.relatedTarget as Node | null
    if (next && (event.currentTarget as Node | null)?.contains(next)) return
    cancel()
  }
  onBeforeUnmount(cancel)
  return { onDragEnter, onDragOver, onDragLeave, onDrop: cancel }
}
