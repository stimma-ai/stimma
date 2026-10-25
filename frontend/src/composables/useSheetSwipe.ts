/**
 * Swipe down to dismiss, for every bottom sheet on a touch screen.
 *
 * Sheets come from two places (DESIGN.md §1.11): the kit Sheet, and menus or
 * popovers that style.css converts into sheets on coarse pointers. One
 * document-level gesture serves both, so no sheet has to opt in. A downward
 * drag that starts on a sheet (and, inside its content, only once that
 * content is scrolled to the top) moves the sheet with the finger; releasing
 * past a third of its height, or flicking down, dismisses it exactly the way
 * a tap outside does. Anything else springs back.
 *
 * Sheets that must not be swiped away (a kit Sheet with closeOnBackdrop off,
 * or an expandable one, which owns its handle gesture) carry
 * data-sheet-swipe="off".
 */

const CONVERTED = [
  '.z-menu.fixed:not([data-sheet-layer]):not(.inset-0)',
  '.z-menu.absolute:not([data-sheet-layer]):not(.inset-0)',
  '.z-submenu.fixed:not([data-sheet-layer]):not(.inset-0)',
  '.z-submenu.absolute:not([data-sheet-layer]):not(.inset-0)',
  '[data-sheet-menu]',
].join(', ')
const KIT = '[data-sheet-layer] .sheet-panel'
const NO_DRAG = 'textarea, input, select, [contenteditable="true"], [data-sheet-no-drag]'

function sheetFor(target: Element): HTMLElement | null {
  const kit = target.closest<HTMLElement>(KIT)
  if (kit) return kit.closest('[data-sheet-swipe="off"]') ? null : kit
  if (document.documentElement.dataset.pointer !== 'coarse') return null
  return target.closest<HTMLElement>(CONVERTED)
}

/** True when nothing between the target and the sheet can scroll further up. */
function atTop(target: Element, sheet: HTMLElement): boolean {
  for (let el: Element | null = target; el; el = el.parentElement) {
    if (el instanceof HTMLElement && el.scrollTop > 0) {
      const oy = getComputedStyle(el).overflowY
      if (oy === 'auto' || oy === 'scroll') return false
    }
    if (el === sheet) break
  }
  return true
}

function setTransform(el: HTMLElement, value: string | null, transition: string | null) {
  if (value === null) el.style.removeProperty('transform')
  else el.style.setProperty('transform', value, 'important')
  if (transition === null) el.style.removeProperty('transition')
  else el.style.setProperty('transition', transition, 'important')
}

/** Dismiss the way a tap outside would: tap whatever sits above the sheet. */
function dismiss(sheet: HTMLElement, x: number) {
  const top = sheet.getBoundingClientRect().top
  // The sheet is mid-slide; look just above where it started.
  const above = document.elementFromPoint(x, Math.max(1, top - 12)) as HTMLElement | null
  const isBackdrop = above && (above.hasAttribute('data-sheet-backdrop')
    || above.hasAttribute('data-sheet-layer')
    || (above.classList.contains('inset-0') && above.classList.contains('fixed')))
  if (isBackdrop) above.click()
  else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }))
}

export function installSheetSwipeDismiss() {
  if (typeof document === 'undefined') return
  let g: { id: number; x: number; y: number; sheet: HTMLElement; target: Element; mode: 'pending' | 'drag' | 'native'; samples: Array<[number, number]> } | null = null

  document.addEventListener('touchstart', (e) => {
    if (g || e.touches.length !== 1) return
    const target = e.target as Element
    if (!(target instanceof Element) || target.closest(NO_DRAG)) return
    const sheet = sheetFor(target)
    if (!sheet) return
    const t = e.touches[0]
    g = { id: t.identifier, x: t.clientX, y: t.clientY, sheet, target, mode: 'pending', samples: [[performance.now(), t.clientY]] }
  }, { passive: true, capture: true })

  document.addEventListener('touchmove', (e) => {
    if (!g) return
    const t = Array.from(e.changedTouches).find((c) => c.identifier === g!.id)
    if (!t) return
    const dx = t.clientX - g.x
    const dy = t.clientY - g.y
    if (g.mode === 'pending') {
      if (Math.abs(dx) < 3 && Math.abs(dy) < 3) return
      g.mode = dy > 0 && Math.abs(dy) > Math.abs(dx) && atTop(g.target, g.sheet) ? 'drag' : 'native'
    }
    if (g.mode !== 'drag') return
    if (e.cancelable) e.preventDefault()
    g.samples.push([performance.now(), t.clientY])
    if (g.samples.length > 6) g.samples.shift()
    setTransform(g.sheet, `translateY(${Math.max(0, dy)}px)`, 'none')
  }, { passive: false, capture: true })

  const end = (e: TouchEvent) => {
    if (!g) return
    const t = Array.from(e.changedTouches).find((c) => c.identifier === g!.id)
    if (!t) return
    const { sheet, mode, samples, x, y: g0y } = g
    g = null
    if (mode !== 'drag') return
    const [t0, y0] = samples[0]
    const [t1, y1] = samples[samples.length - 1]
    const velocity = t1 > t0 ? (y1 - y0) / (t1 - t0) : 0
    const offset = Math.max(0, t.clientY - g0y)
    const h = sheet.getBoundingClientRect().height
    if (e.type !== 'touchcancel' && (offset > h / 3 || velocity > 0.5)) {
      setTransform(sheet, 'translateY(100%)', 'transform 160ms ease-in')
      window.setTimeout(() => {
        dismiss(sheet, x)
        // A sheet that ignored the dismissal is still here: bring it back.
        window.setTimeout(() => { if (sheet.isConnected) setTransform(sheet, null, null) }, 250)
      }, 150)
    } else {
      setTransform(sheet, 'translateY(0px)', 'transform 180ms ease-out')
      window.setTimeout(() => setTransform(sheet, null, null), 200)
    }
  }
  document.addEventListener('touchend', end, { capture: true })
  document.addEventListener('touchcancel', end, { capture: true })
}
