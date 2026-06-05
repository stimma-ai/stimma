/**
 * Composable for creating custom drag preview images.
 *
 * When dragging images, the browser default uses the source element's full size,
 * which can be too large. This creates a smaller preview.
 */

import { setDraggedMedia, clearDraggedMedia } from '../stores/dragStore'

// Shared drag preview element (reused across drags)
let dragPreviewElement: HTMLDivElement | null = null
let dragPreviewImg: HTMLImageElement | null = null
let cleanupTimeout: ReturnType<typeof setTimeout> | null = null

// Cache of preloaded images for faster drag preview
const preloadedImages = new Map<string, HTMLImageElement>()

const PREVIEW_SIZE = 100

/**
 * Preload a thumbnail for faster drag preview.
 * Call this on mouseenter/hover to have the image ready before drag starts.
 */
export function preloadDragPreview(thumbnailUrl: string): void {
  if (preloadedImages.has(thumbnailUrl)) return

  const img = new Image()
  img.src = thumbnailUrl
  preloadedImages.set(thumbnailUrl, img)

  // Limit cache size
  if (preloadedImages.size > 50) {
    const firstKey = preloadedImages.keys().next().value
    if (firstKey) preloadedImages.delete(firstKey)
  }
}

/**
 * Create and show a custom drag preview image.
 * Also sets global drag state for sidebar tool compatibility feedback.
 */
/**
 * Extract all media IDs from a drop event.
 * Checks for multi-select (application/x-media-ids) first, falls back to single.
 */
export function getDroppedMediaIds(dataTransfer: DataTransfer | null): number[] {
  if (!dataTransfer) return []
  const multiStr = dataTransfer.getData('application/x-media-ids')
  if (multiStr) {
    try {
      const ids = JSON.parse(multiStr)
      if (Array.isArray(ids) && ids.length > 0) return ids.map(Number)
    } catch { /* fall through */ }
  }
  const singleStr = dataTransfer.getData('application/x-media-id')
  if (singleStr) {
    const id = parseInt(singleStr, 10)
    if (!isNaN(id)) return [id]
  }
  return []
}

export function createDragPreview(
  event: DragEvent,
  thumbnailUrl: string,
  mediaId?: number,
  fileFormat?: string,
  isVideo?: boolean,
  allMediaIds?: number[]
): void {
  if (!event.dataTransfer) return

  // Clear any pending cleanup
  if (cleanupTimeout) {
    clearTimeout(cleanupTimeout)
    cleanupTimeout = null
  }

  // Create the preview element if it doesn't exist
  if (!dragPreviewElement) {
    dragPreviewElement = document.createElement('div')
    dragPreviewElement.style.cssText = `
      position: fixed;
      top: -1000px;
      left: -1000px;
      width: ${PREVIEW_SIZE}px;
      height: ${PREVIEW_SIZE}px;
      border-radius: 8px;
      overflow: hidden;
      background-color: #1a1a1a;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
      pointer-events: none;
      z-index: -1;
    `
    document.body.appendChild(dragPreviewElement)
  }

  // Check if we have a preloaded image
  const preloaded = preloadedImages.get(thumbnailUrl)

  // Create or update the image element
  if (!dragPreviewImg) {
    dragPreviewImg = document.createElement('img')
    dragPreviewImg.style.cssText = 'width: 100%; height: 100%; object-fit: cover;'
    dragPreviewImg.draggable = false
    dragPreviewElement.innerHTML = ''
    dragPreviewElement.appendChild(dragPreviewImg)
  }

  // Use preloaded image src if available and loaded, otherwise use URL directly
  if (preloaded && preloaded.complete && preloaded.naturalWidth > 0) {
    dragPreviewImg.src = preloaded.src
  } else {
    dragPreviewImg.src = thumbnailUrl
  }

  // Set the drag data
  if (mediaId !== undefined) {
    event.dataTransfer.setData('application/x-media-id', String(mediaId))
    // Set multi-select IDs if provided
    if (allMediaIds && allMediaIds.length > 1) {
      event.dataTransfer.setData('application/x-media-ids', JSON.stringify(allMediaIds))
    }
    // Set global drag state for sidebar tool compatibility feedback
    setDraggedMedia({
      mediaId,
      fileFormat: fileFormat || '',
      isVideo: isVideo || false
    })
  }
  event.dataTransfer.effectAllowed = 'copy'

  // Add or remove count badge for multi-drag
  const existingBadge = dragPreviewElement.querySelector('.drag-count-badge')
  if (existingBadge) existingBadge.remove()

  if (allMediaIds && allMediaIds.length > 1) {
    const badge = document.createElement('div')
    badge.className = 'drag-count-badge'
    badge.textContent = String(allMediaIds.length)
    badge.style.cssText = `
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      color: white;
      font-size: 20px;
      font-weight: 700;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      backdrop-filter: blur(2px);
    `
    dragPreviewElement.appendChild(badge)
  }

  // Set the custom drag image
  // The offset centers the preview under the cursor
  event.dataTransfer.setDragImage(dragPreviewElement, PREVIEW_SIZE / 2, PREVIEW_SIZE / 2)

  // Clean up after drag ends (with a delay to ensure drag completes)
  cleanupTimeout = setTimeout(() => {
    if (dragPreviewElement) {
      dragPreviewElement.remove()
      dragPreviewElement = null
      dragPreviewImg = null
    }
  }, 5000)
}

/**
 * Clean up drag preview immediately
 */
export function cleanupDragPreview(): void {
  if (cleanupTimeout) {
    clearTimeout(cleanupTimeout)
    cleanupTimeout = null
  }
  if (dragPreviewElement) {
    dragPreviewElement.remove()
    dragPreviewElement = null
  }
}

// Section drag preview canvas (canvas gives true per-pixel transparency for rounded corners)
let sectionPreviewCanvas: HTMLCanvasElement | null = null
let sectionPreviewCleanup: ReturnType<typeof setTimeout> | null = null

const SECTION_W = 220
const SECTION_H = 80
const SECTION_R = 20
const SECTION_DPR = 2 // render at 2x for retina clarity

/**
 * Create a stylized section drag preview with dots pattern and label pill.
 * Uses canvas to avoid browser drag-image rasterization artifacts at rounded corners.
 */
export function createSectionDragPreview(
  event: DragEvent,
  sectionName: string,
  theme: 'light' | 'dark'
): void {
  if (!event.dataTransfer) return

  if (sectionPreviewCleanup) {
    clearTimeout(sectionPreviewCleanup)
    sectionPreviewCleanup = null
  }

  if (!sectionPreviewCanvas) {
    sectionPreviewCanvas = document.createElement('canvas')
    sectionPreviewCanvas.style.cssText = `position:fixed;top:-2000px;left:-2000px;pointer-events:none;z-index:-1;`
    sectionPreviewCanvas.style.width = `${SECTION_W}px`
    sectionPreviewCanvas.style.height = `${SECTION_H}px`
    sectionPreviewCanvas.width = SECTION_W * SECTION_DPR
    sectionPreviewCanvas.height = SECTION_H * SECTION_DPR
    document.body.appendChild(sectionPreviewCanvas)
  }

  const ctx = sectionPreviewCanvas.getContext('2d')!
  const s = SECTION_DPR
  ctx.clearRect(0, 0, SECTION_W * s, SECTION_H * s)

  const isLight = theme === 'light'

  // Draw rounded rect background
  ctx.save()
  ctx.beginPath()
  ctx.roundRect(0, 0, SECTION_W * s, SECTION_H * s, SECTION_R * s)
  ctx.clip()

  // Fill background
  ctx.fillStyle = isLight ? '#fcfcfd' : 'rgba(255,255,255,0.06)'
  ctx.fillRect(0, 0, SECTION_W * s, SECTION_H * s)

  // Draw dot grid
  const dotSpacing = 16 * s
  const dotRadius = 1 * s
  ctx.fillStyle = isLight ? 'rgba(0,0,0,0.13)' : 'rgba(255,255,255,0.13)'
  for (let y = dotSpacing; y < SECTION_H * s; y += dotSpacing) {
    for (let x = dotSpacing; x < SECTION_W * s; x += dotSpacing) {
      ctx.beginPath()
      ctx.arc(x, y, dotRadius, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // Draw border
  ctx.beginPath()
  ctx.roundRect(0.5 * s, 0.5 * s, (SECTION_W - 1) * s, (SECTION_H - 1) * s, SECTION_R * s)
  ctx.strokeStyle = isLight ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)'
  ctx.lineWidth = 1 * s
  ctx.stroke()

  ctx.restore()

  // Draw label pill
  const label = sectionName || ''
  if (label) {
    ctx.font = `500 ${11 * s}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
    const metrics = ctx.measureText(label)
    const pillPadX = 12 * s
    const pillPadY = 3 * s
    const pillH = 11 * s + pillPadY * 2
    const pillW = Math.min(metrics.width + pillPadX * 2, 180 * s)
    const pillX = 12 * s
    const pillY = 12 * s
    const pillR = pillH / 2

    // Pill background
    ctx.beginPath()
    ctx.roundRect(pillX, pillY, pillW, pillH, pillR)
    ctx.fillStyle = isLight ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.9)'
    ctx.fill()
    ctx.strokeStyle = isLight ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.06)'
    ctx.lineWidth = 1 * s
    ctx.stroke()

    // Pill text
    ctx.fillStyle = '#71717a'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, pillX + pillPadX, pillY + pillH / 2, 160 * s)
  }

  event.dataTransfer.setDragImage(sectionPreviewCanvas, SECTION_W / 2, SECTION_H / 2)

  sectionPreviewCleanup = setTimeout(() => {
    if (sectionPreviewCanvas) {
      sectionPreviewCanvas.remove()
      sectionPreviewCanvas = null
    }
  }, 5000)
}

/**
 * Clean up section drag preview immediately.
 */
export function cleanupSectionDragPreview(): void {
  if (sectionPreviewCleanup) {
    clearTimeout(sectionPreviewCleanup)
    sectionPreviewCleanup = null
  }
  if (sectionPreviewCanvas) {
    sectionPreviewCanvas.remove()
    sectionPreviewCanvas = null
  }
}

/**
 * Handle drag end - clears global drag state.
 * Call this from dragend event handlers.
 */
export function handleDragEnd(): void {
  cleanupDragPreview()
  cleanupSectionDragPreview()
  clearDraggedMedia()
}

export function useDragPreview() {
  return {
    createDragPreview,
    createSectionDragPreview,
    cleanupDragPreview,
    cleanupSectionDragPreview,
    handleDragEnd,
    preloadDragPreview,
    getDroppedMediaIds,
    PREVIEW_SIZE
  }
}
