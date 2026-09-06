/**
 * Touch long-press → `contextmenu`.
 *
 * Every right-click menu in the app listens for `contextmenu`. iOS Safari
 * never fires it for touch, and Android fires it only sometimes, so on coarse
 * pointers a press held for LONG_PRESS_MS without moving dispatches a
 * synthetic `contextmenu` at the touch point. The native one that Android may
 * fire right after is swallowed so a menu never opens twice, and the click
 * that follows the release is swallowed so the row under the finger does not
 * also activate.
 */
import { useViewport } from '../composables/useViewport'

const LONG_PRESS_MS = 450
const MOVE_TOLERANCE_PX = 10

let timer: number | null = null
let startX = 0
let startY = 0
let target: EventTarget | null = null
let fired = false

function clear() {
  if (timer !== null) { window.clearTimeout(timer); timer = null }
}

function onTouchStart(e: TouchEvent) {
  if (e.touches.length !== 1) { clear(); return }
  const t = e.touches[0]
  startX = t.clientX; startY = t.clientY; target = e.target; fired = false
  clear()
  timer = window.setTimeout(() => {
    timer = null
    if (!target) return
    fired = true
    const ev = new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: startX, clientY: startY, button: 2,
    })
    ;(ev as unknown as { stimmaSynthetic: boolean }).stimmaSynthetic = true
    target.dispatchEvent(ev)
    hoverSuppressUntil = Date.now() + 1000
    try { navigator.vibrate?.(10) } catch { /* no haptics */ }
  }, LONG_PRESS_MS)
}

function onTouchMove(e: TouchEvent) {
  const t = e.touches[0]
  if (!t) return
  if (Math.abs(t.clientX - startX) > MOVE_TOLERANCE_PX || Math.abs(t.clientY - startY) > MOVE_TOLERANCE_PX) clear()
}

function onTouchEnd() { clear() }

function onContextMenu(e: MouseEvent) {
  if ((e as unknown as { stimmaSynthetic?: boolean }).stimmaSynthetic) return
  // Native long-press contextmenu (Android): ours already opened the menu.
  if (fired) { e.preventDefault(); e.stopImmediatePropagation() }
}

function onClick(e: MouseEvent) {
  if (fired) { fired = false; e.preventDefault(); e.stopImmediatePropagation() }
}

// After a touch ends, browsers replay compatibility mouse events (mousemove,
// mouseover, mouseenter) at the touch point. With a sheet now under that
// point, those would "hover" a row and pop its submenu. There is no hover on
// a phone; swallow them for a moment after a long-press.
let hoverSuppressUntil = 0
function onCompatHover(e: Event) {
  // A phone has no hover: every mouseenter/mouseover the browser synthesises
  // after a tap is noise, and the app's hover-driven UI (submenus that open on
  // mouseenter, hover-revealed controls) must never react to it. Swallowed at
  // the capture phase so element listeners never see them.
  void hoverSuppressUntil
  e.stopImmediatePropagation()
}

export function installLongPressContextMenu() {
  if (typeof window === 'undefined') return
  if (!useViewport().isCoarsePointer.value) return
  document.addEventListener('touchstart', onTouchStart, { passive: true, capture: true })
  document.addEventListener('touchmove', onTouchMove, { passive: true, capture: true })
  document.addEventListener('touchend', onTouchEnd, { passive: true, capture: true })
  document.addEventListener('touchcancel', onTouchEnd, { passive: true, capture: true })
  document.addEventListener('contextmenu', onContextMenu, true)
  document.addEventListener('click', onClick, true)
  for (const type of ['mousemove', 'mouseover', 'mouseenter', 'pointerover', 'pointerenter']) {
    document.addEventListener(type, onCompatHover, true)
  }
}
