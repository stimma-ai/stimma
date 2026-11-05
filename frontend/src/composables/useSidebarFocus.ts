import { ref } from 'vue'
import { makeProfileKey } from '../utils/storageKeys'

// Focus screens (the slideshow, the image editor) give the picture the whole
// window, so the docked sidebar steps aside there. Two separate states:
//
// - focusSidebarOpen: the person's choice, stored per profile. Opening the
//   sidebar on a focus screen keeps it open on every later visit until they
//   collapse it again.
// - dragPeek: a transient reveal while a media drag is in flight, so the
//   sidebar's drop targets stay reachable. It is never stored.

const storageKey = () => makeProfileKey('sidebar', 'focus_open')

const stored = ref<boolean | null>(null)
function readStored(): boolean {
  if (stored.value !== null) return stored.value
  let open = false
  try { open = localStorage.getItem(storageKey()) === '1' } catch { /* storage unavailable: collapsed */ }
  stored.value = open
  return open
}

export const dragPeek = ref(false)

export function focusSidebarOpen(): boolean {
  return readStored()
}

export function setFocusSidebarOpen(open: boolean) {
  stored.value = open
  try { localStorage.setItem(storageKey(), open ? '1' : '0') } catch { /* choice still applies this session */ }
}

const MEDIA_TYPES = ['application/x-media-id', 'application/x-media-ids']

/** True when the drag carries an in-app media payload, which the sidebar's rows accept. */
export function carriesMedia(event: DragEvent): boolean {
  const types = event.dataTransfer?.types
  return !!types && MEDIA_TYPES.some(t => types.includes(t))
}

// Every change goes through one pending frame, last request wins. Changing the
// DOM inside dragstart can make Chromium cancel the drag, so even the reveal
// waits for the next frame, and an end event arriving first simply wins.
let wanted = false
let frame = 0
function setPeek(show: boolean) {
  wanted = show
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    dragPeek.value = wanted
  })
}

function leftWindow(e: DragEvent): boolean {
  if (e.relatedTarget) return false
  return e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth - 1 || e.clientY >= window.innerHeight - 1
}

/**
 * Reveal the sidebar for the length of an in-app media drag. Starts on dragstart
 * (a drag begun in this window) and on dragenter (a drag arriving from another
 * window of the app); ends on dragend, drop, leaving the window, and as a last
 * resort the first pointer move with no button down, which a live drag never
 * produces. Returns the cleanup.
 */
export function installDragPeek(): () => void {
  const show = (e: DragEvent) => { if (!e.defaultPrevented && carriesMedia(e)) setPeek(true) }
  const hide = () => { if (dragPeek.value || wanted) setPeek(false) }
  const onLeave = (e: DragEvent) => { if (leftWindow(e)) hide() }
  const onMove = (e: MouseEvent) => { if (e.buttons === 0) hide() }

  window.addEventListener('dragstart', show)
  window.addEventListener('dragenter', show)
  window.addEventListener('dragleave', onLeave)
  window.addEventListener('dragend', hide, true)
  window.addEventListener('drop', hide, true)
  window.addEventListener('mousemove', onMove, { passive: true })
  return () => {
    window.removeEventListener('dragstart', show)
    window.removeEventListener('dragenter', show)
    window.removeEventListener('dragleave', onLeave)
    window.removeEventListener('dragend', hide, true)
    window.removeEventListener('drop', hide, true)
    window.removeEventListener('mousemove', onMove)
    if (frame) cancelAnimationFrame(frame)
    frame = 0
    wanted = false
    dragPeek.value = false
  }
}
