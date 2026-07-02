import { ref, computed, watch, nextTick, onUnmounted, type Ref } from 'vue'

const PADDING = 8

export interface ContextMenuCoords {
  x: number
  y: number
  bottomY?: number // If set, anchor menu bottom to this y instead of top
}

/**
 * Measure a menu's layout size for placement decisions.
 *
 * Uses offsetWidth/offsetHeight so CSS transforms (scale-in animations) don't
 * under-report the final size. When `appliedCap` — a max-height we set
 * ourselves — is what's constraining the element, the rendered height is
 * self-fulfilling, so fall back to content height (scrollHeight) to decide
 * placement as if the cap weren't there.
 */
function measureMenu(el: HTMLElement, appliedCap: number | null = null): { w: number; h: number } {
  const w = el.offsetWidth || 180
  let h = el.offsetHeight || 200
  if (appliedCap !== null && h >= appliedCap - 1) {
    h = Math.max(h, el.scrollHeight)
  }
  return { w, h }
}

/**
 * Re-run `reposition` whenever the menu's content resizes (async-loaded items)
 * or the window resizes, for as long as `visible` is true. Also runs it once
 * after the menu first renders. Shared plumbing for all positioners below.
 */
function useRepositionTriggers(
  menuRef: Ref<HTMLElement | null>,
  visible: Ref<boolean>,
  reposition: () => void,
  onShow?: () => void
) {
  let resizeObserver: ResizeObserver | null = null

  function unobserve() {
    resizeObserver?.disconnect()
    resizeObserver = null
  }

  function onWindowResize() {
    reposition()
  }

  function teardown() {
    unobserve()
    window.removeEventListener('resize', onWindowResize)
  }

  watch(visible, async (v) => {
    if (v) {
      onShow?.()
      await nextTick()
      reposition()
      unobserve()
      if (menuRef.value && typeof ResizeObserver !== 'undefined') {
        resizeObserver = new ResizeObserver(() => reposition())
        resizeObserver.observe(menuRef.value)
      }
      window.addEventListener('resize', onWindowResize)
    } else {
      teardown()
    }
  }, { immediate: true })

  onUnmounted(teardown)
}

/**
 * Provides viewport-aware positioning for a context menu element.
 * Measures the actual rendered size and adjusts to stay on-screen; re-clamps
 * as async content loads and caps the height to the viewport so oversized
 * menus scroll instead of clipping.
 */
export function useContextMenuPosition(
  menuRef: Ref<HTMLElement | null>,
  coords: Ref<ContextMenuCoords>,
  visible: Ref<boolean>
) {
  const adjustedX = ref(0)
  const adjustedY = ref(0)
  const anchorBottom = ref(false)
  const maxHeight = ref<number | null>(null)

  function reposition() {
    const el = menuRef.value
    if (!el || !visible.value) return

    const { x, y, bottomY } = coords.value
    const { w, h } = measureMenu(el, maxHeight.value)

    // Horizontal: prefer click position, clamp to viewport
    let ax = x
    if (ax + w > window.innerWidth - PADDING) {
      ax = Math.max(PADDING, window.innerWidth - w - PADDING)
    }
    ax = Math.max(PADDING, ax)
    adjustedX.value = ax

    // Vertical
    if (bottomY !== undefined) {
      anchorBottom.value = true
      // Keep the bottom edge on-screen, and cap height so the top edge is too
      const anchoredBottom = Math.min(bottomY, window.innerHeight - PADDING)
      adjustedY.value = window.innerHeight - anchoredBottom
      maxHeight.value = h > anchoredBottom - PADDING ? anchoredBottom - PADDING : null
      return
    }

    anchorBottom.value = false
    let ay = y
    if (ay + h > window.innerHeight - PADDING) {
      ay = Math.max(PADDING, window.innerHeight - h - PADDING)
    }
    ay = Math.max(PADDING, ay)
    adjustedY.value = ay

    const available = window.innerHeight - 2 * PADDING
    maxHeight.value = h > available ? available : null
  }

  useRepositionTriggers(menuRef, visible, reposition, () => {
    // Seed from raw coords so the menu renders near the click before measuring
    adjustedX.value = coords.value.x
    adjustedY.value = coords.value.bottomY !== undefined
      ? window.innerHeight - coords.value.bottomY
      : coords.value.y
    anchorBottom.value = coords.value.bottomY !== undefined
    maxHeight.value = null
  })

  const menuStyle = computed(() => {
    const style: Record<string, string> = anchorBottom.value
      ? { left: `${adjustedX.value}px`, bottom: `${adjustedY.value}px` }
      : { top: `${adjustedY.value}px`, left: `${adjustedX.value}px` }
    if (maxHeight.value !== null) {
      style.maxHeight = `${maxHeight.value}px`
      style.overflowY = 'auto'
    }
    return style
  })

  return { menuStyle, reposition }
}

/**
 * Viewport-aware positioning for a dropdown menu anchored to a trigger element
 * (e.g. "Send to Tool" buttons). Prefers opening below the anchor, flips above
 * when there isn't room, clamps horizontally, and caps the height to whichever
 * side it opens on so the menu scrolls instead of clipping.
 */
export function useAnchoredMenuPosition(
  menuRef: Ref<HTMLElement | null>,
  anchorRect: Ref<DOMRect | null>,
  visible: Ref<boolean>,
  opts: { gap?: number } = {}
) {
  const gap = opts.gap ?? 4
  const style = ref<Record<string, string>>({})
  let appliedCap: number | null = null

  function reposition() {
    const el = menuRef.value
    const anchor = anchorRect.value
    if (!el || !anchor || !visible.value) return

    const { w, h } = measureMenu(el, appliedCap)

    let x = anchor.left
    if (x + w > window.innerWidth - PADDING) {
      x = Math.max(PADDING, window.innerWidth - w - PADDING)
    }
    x = Math.max(PADDING, x)

    const spaceBelow = window.innerHeight - PADDING - (anchor.bottom + gap)
    const spaceAbove = anchor.top - gap - PADDING

    const next: Record<string, string> = { left: `${x}px` }
    appliedCap = null
    if (h <= spaceBelow) {
      next.top = `${anchor.bottom + gap}px`
    } else if (h <= spaceAbove) {
      next.top = `${anchor.top - gap - h}px`
    } else {
      // Doesn't fully fit either side — open on the roomier side and cap height
      const below = spaceBelow >= spaceAbove
      const space = Math.max(Math.floor(below ? spaceBelow : spaceAbove), 40)
      next.top = below ? `${anchor.bottom + gap}px` : `${Math.max(PADDING, anchor.top - gap - space)}px`
      next.maxHeight = `${space}px`
      next.overflowY = 'auto'
      appliedCap = space
    }
    style.value = next
  }

  useRepositionTriggers(menuRef, visible, reposition, () => {
    appliedCap = null
  })

  return { menuStyle: style, reposition }
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
 * Clamp a submenu's y-position to the viewport and cap its height when it
 * cannot fit. Returns the positional style fields shared by all submenu
 * positioners; the caller should feed `maxHeight` (if present) back into the
 * next measurement as the applied cap.
 */
function computeSubmenuStyle(
  x: number,
  triggerTop: number,
  submenuHeight: number
): Record<string, string> {
  let y = triggerTop
  if (y + submenuHeight > window.innerHeight - PADDING) {
    y = Math.max(PADDING, window.innerHeight - submenuHeight - PADDING)
  }

  const style: Record<string, string> = { top: `${y}px`, left: `${x}px` }
  const available = window.innerHeight - 2 * PADDING
  if (submenuHeight > available) {
    style.maxHeight = `${available}px`
    style.overflowY = 'auto'
  }
  return style
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
  const pos = ref<Record<string, string>>({ top: '0px', left: '0px' })
  const bridgeStyle = ref<Record<string, string>>({ display: 'none' })
  let appliedCap: number | null = null

  function reposition() {
    const parent = parentMenuRef.value
    const trigger = triggerRect.value
    if (!parent || !trigger) {
      pos.value = { top: '0px', left: '0px' }
      bridgeStyle.value = { display: 'none' }
      appliedCap = null
      return
    }

    const parentRect = parent.getBoundingClientRect()
    const submenu = submenuRef.value
    const measured = submenu ? measureMenu(submenu, appliedCap) : { w: 260, h: 400 }

    const { x, opensLeft } = computeSubmenuX(parentRect, measured.w)

    const style = computeSubmenuStyle(x, trigger.top, measured.h)
    appliedCap = style.maxHeight ? parseInt(style.maxHeight, 10) : null
    pos.value = style
    bridgeStyle.value = computeBridgeStyle(parentRect, trigger, opensLeft)
  }

  useRepositionTriggers(submenuRef, active, reposition, () => {
    appliedCap = null
  })

  watch(active, (v) => {
    if (!v) bridgeStyle.value = { display: 'none' }
  })

  return { submenuStyle: pos, bridgeStyle, reposition }
}

/**
 * Standalone submenu positioning for components that manage their own
 * computed properties (e.g. MediaContextMenu which shares one position
 * across multiple submenus).
 */
export { computeSubmenuX, computeBridgeStyle, computeSubmenuStyle, measureMenu, SUBMENU_GAP }
