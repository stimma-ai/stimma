import { ref, computed, watch, nextTick, type Ref } from 'vue'

const PADDING = 8

export interface ContextMenuCoords {
  x: number
  y: number
  bottomY?: number // If set, anchor menu bottom to this y instead of top
}

/**
 * Provides viewport-aware positioning for a context menu element.
 * Measures the actual rendered size and adjusts to stay on-screen.
 */
export function useContextMenuPosition(
  menuRef: Ref<HTMLElement | null>,
  coords: Ref<ContextMenuCoords>,
  visible: Ref<boolean>
) {
  const adjustedX = ref(0)
  const adjustedY = ref(0)
  const anchorBottom = ref(false)

  function reposition() {
    const el = menuRef.value
    if (!el || !visible.value) return

    const { x, y, bottomY } = coords.value
    const rect = el.getBoundingClientRect()
    const w = rect.width || 180
    const h = rect.height || 200

    // Horizontal: prefer click position, clamp to viewport
    let ax = x
    if (ax + w > window.innerWidth - PADDING) {
      ax = Math.max(PADDING, window.innerWidth - w - PADDING)
    }
    ax = Math.max(PADDING, ax)

    // Vertical
    if (bottomY !== undefined) {
      anchorBottom.value = true
      adjustedX.value = ax
      adjustedY.value = window.innerHeight - bottomY
      return
    }

    anchorBottom.value = false
    let ay = y
    if (ay + h > window.innerHeight - PADDING) {
      ay = Math.max(PADDING, window.innerHeight - h - PADDING)
    }
    ay = Math.max(PADDING, ay)

    adjustedX.value = ax
    adjustedY.value = ay
  }

  watch(visible, async (v) => {
    if (v) {
      // Set initial position from raw coords so the menu renders near the click
      adjustedX.value = coords.value.x
      adjustedY.value = coords.value.bottomY !== undefined
        ? window.innerHeight - coords.value.bottomY
        : coords.value.y
      anchorBottom.value = coords.value.bottomY !== undefined
      // Then measure and adjust after render
      await nextTick()
      requestAnimationFrame(reposition)
    }
  })

  const menuStyle = computed(() => {
    if (anchorBottom.value) {
      return {
        left: `${adjustedX.value}px`,
        bottom: `${adjustedY.value}px`,
      }
    }
    return {
      top: `${adjustedY.value}px`,
      left: `${adjustedX.value}px`,
    }
  })

  return { menuStyle, reposition }
}

const SUBMENU_GAP = 4

/**
 * Compute submenu x-position that never overlaps the parent menu.
 *
 * Strategy:
 *   1. Try right of parent (parentRect.right + gap)
 *   2. Try left of parent (parentRect.left - submenuWidth - gap)
 *   3. If neither fits, pick the side with more room and pin to viewport edge,
 *      but never cross into the parent's horizontal bounds.
 *
 * Returns { x, opensLeft }.
 */
function computeSubmenuX(
  parentRect: DOMRect,
  submenuWidth: number,
  gap: number = SUBMENU_GAP
): { x: number; opensLeft: boolean } {
  const availableRight = window.innerWidth - PADDING - parentRect.right - gap
  const availableLeft = parentRect.left - gap - PADDING

  // 1. Fits to the right
  if (submenuWidth <= availableRight) {
    return { x: parentRect.right + gap, opensLeft: false }
  }

  // 2. Fits to the left
  if (submenuWidth <= availableLeft) {
    return { x: parentRect.left - submenuWidth - gap, opensLeft: true }
  }

  // 3. Neither side has full room — pick the side with more space.
  //    Clamp to the viewport edge but never let the submenu cross into the parent.
  if (availableLeft >= availableRight) {
    // Open left — submenu's right edge must stay at or before parentRect.left - gap.
    // Pin to left viewport edge if the submenu doesn't fully fit.
    const x = Math.max(PADDING, parentRect.left - submenuWidth - gap)
    return { x, opensLeft: true }
  } else {
    // Open right — submenu's left edge stays at parentRect.right + gap, even if
    // that means the submenu extends past the viewport. Clipping the edge is
    // preferable to overlapping the parent the user is reading.
    return { x: parentRect.right + gap, opensLeft: false }
  }
}

/**
 * Build an invisible bridge rect between the parent menu edge and the submenu
 * so the mouse can travel across the gap without triggering mouseleave.
 */
function computeBridgeStyle(
  parentRect: DOMRect,
  triggerRect: DOMRect,
  opensLeft: boolean
): Record<string, string> {
  const vertPad = 40
  const bridgeTop = Math.max(0, triggerRect.top - vertPad)
  const bridgeHeight = triggerRect.height + vertPad * 2

  if (opensLeft) {
    // Bridge spans from submenu's right edge area to parent's left edge
    const left = parentRect.left - SUBMENU_GAP - 8
    const right = parentRect.left + 8 // overlap slightly into parent for seamless transition
    return {
      top: `${bridgeTop}px`,
      left: `${left}px`,
      width: `${Math.max(0, right - left)}px`,
      height: `${bridgeHeight}px`,
    }
  }

  // Bridge spans from parent's right edge to submenu's left edge area
  const left = parentRect.right - 8
  const width = SUBMENU_GAP + 16 + 8
  return {
    top: `${bridgeTop}px`,
    left: `${left}px`,
    width: `${width}px`,
    height: `${bridgeHeight}px`,
  }
}

/**
 * Provides viewport-aware positioning for a submenu.
 * Positions relative to the parent menu and trigger element.
 * The submenu never overlaps the parent menu horizontally.
 * Returns submenu position, bridge style, and reposition function.
 */
export function useSubmenuPosition(
  parentMenuRef: Ref<HTMLElement | null>,
  triggerRect: Ref<DOMRect | null>,
  submenuRef: Ref<HTMLElement | null>,
  active: Ref<boolean>
) {
  const pos = ref({ top: '0px', left: '0px' })
  const bridgeStyle = ref<Record<string, string>>({ display: 'none' })

  function reposition() {
    const parent = parentMenuRef.value
    const trigger = triggerRect.value
    if (!parent || !trigger) {
      pos.value = { top: '0px', left: '0px' }
      bridgeStyle.value = { display: 'none' }
      return
    }

    const parentRect = parent.getBoundingClientRect()
    const submenu = submenuRef.value
    const submenuWidth = submenu ? submenu.getBoundingClientRect().width : 260
    const submenuHeight = submenu ? submenu.getBoundingClientRect().height : 400

    const { x, opensLeft } = computeSubmenuX(parentRect, submenuWidth)

    // Vertical: align to trigger top, clamp to viewport
    let y = trigger.top
    if (y + submenuHeight > window.innerHeight - PADDING) {
      y = Math.max(PADDING, window.innerHeight - submenuHeight - PADDING)
    }

    pos.value = { top: `${y}px`, left: `${x}px` }
    bridgeStyle.value = computeBridgeStyle(parentRect, trigger, opensLeft)
  }

  watch(active, async (v) => {
    if (v) {
      await nextTick()
      requestAnimationFrame(reposition)
    } else {
      bridgeStyle.value = { display: 'none' }
    }
  })

  return { submenuStyle: pos, bridgeStyle, reposition }
}

/**
 * Standalone submenu positioning for components that manage their own
 * computed properties (e.g. MediaContextMenu which shares one position
 * across multiple submenus).
 */
export { computeSubmenuX, computeBridgeStyle, SUBMENU_GAP }
