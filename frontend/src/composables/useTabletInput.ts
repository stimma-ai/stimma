/**
 * Stylus (graphics tablet) pressure, merged from two sources:
 *
 * - Real pen pointer events (Chromium/WebView2 on Windows): pressure arrives
 *   on the PointerEvent itself, recognizable by `pointerType === 'pen'`.
 * - The native `tablet-input` stream (macOS, src-tauri/src/tablet.rs):
 *   WKWebView reports tablet input as a plain mouse pointer with no usable
 *   pressure, so an NSEvent monitor forwards it and it is matched to DOM
 *   pointer events here.
 *
 * The match is per stroke, not per proximity: a pen PARKED on the tablet
 * keeps it in proximity indefinitely while the person draws with the mouse,
 * and those mouse strokes must not inherit the pen's resting pressure of
 * zero. The native stream therefore marks plain mouse strokes explicitly
 * (`mouseStroke`), and pen state only applies while the pen is actually
 * pressed (`penDown`) or actively producing samples — a parked pen produces
 * none. Hover samples cover the stroke's first dab: the native "down" emit
 * can reach JS after the DOM pointerdown it belongs to, but the pen always
 * hovers in before touching, so the stream is already fresh.
 *
 * With no pen involved, `tabletPressureFor` returns null and callers treat
 * the input as a mouse.
 */
import { isTauri } from '../apiConfig'
import { desktop } from '../desktop'
import {
  claimTabletWheelGesture,
  createTabletWheelGestureState,
  noteTabletPointForWheelGesture,
  releaseTabletWheelGesture,
} from './tabletWheelGesture'

type TabletInputPayload =
  | {
      kind: 'point'
      phase: 'down' | 'move' | 'up' | 'hover'
      pressure: number
      tiltX: number
      tiltY: number
      x: number
      y: number
      absoluteX: number
      absoluteY: number
      deltaX: number
      deltaY: number
      buttons: number
    }
  | { kind: 'proximity'; entering: boolean; eraser: boolean }
  | { kind: 'mouseStroke'; down: boolean }
  | {
      kind: 'pan'
      phase: 'down' | 'move' | 'up'
      x: number
      y: number
    }

export interface NativeTabletPanSample {
  phase: 'down' | 'move' | 'up'
  deltaX: number
  deltaY: number
  source: 'middle'
}

/** How recent a native sample must be to speak for the current DOM event. */
const SAMPLE_FRESH_MS = 150

const native = {
  penDown: false,
  penInProximity: false,
  mouseStroke: false,
  pressure: 0,
  tiltX: 0,
  tiltY: 0,
  eraser: false,
  lastSampleAt: 0,
}
const wheelGesture = createTabletWheelGestureState()

let started = false
let stopNativeListening: (() => void) | null = null
let listeningGeneration = 0
const panListeners = new Set<(sample: NativeTabletPanSample) => void>()

const pan = {
  active: false,
  middlePoint: null as { x: number; y: number } | null,
}

function emitPan(sample: NativeTabletPanSample): void {
  for (const listener of panListeners) listener(sample)
}

function handleMiddlePan(
  payload: Extract<TabletInputPayload, { kind: 'pan' }>,
): void {
  if (payload.phase === 'down') {
    pan.active = true
    pan.middlePoint = { x: payload.x, y: payload.y }
    emitPan({ phase: 'down', deltaX: 0, deltaY: 0, source: 'middle' })
    return
  }
  if (!pan.active || !pan.middlePoint) return
  if (payload.phase === 'up') {
    emitPan({ phase: 'up', deltaX: 0, deltaY: 0, source: 'middle' })
    pan.active = false
    pan.middlePoint = null
    return
  }
  emitPan({
    phase: 'move',
    deltaX: payload.x - pan.middlePoint.x,
    deltaY: pan.middlePoint.y - payload.y,
    source: 'middle',
  })
  pan.middlePoint = { x: payload.x, y: payload.y }
}

function ensureListening(): void {
  if (started) return
  started = true
  if (!isTauri()) return
  const generation = ++listeningGeneration
  desktop.onTabletInput((rawPayload) => {
    const payload = rawPayload as TabletInputPayload
    if (payload.kind === 'point') {
      const now = performance.now()
      native.pressure = Math.max(0, Math.min(1, payload.pressure))
      native.tiltX = payload.tiltX
      native.tiltY = payload.tiltY
      native.penInProximity = true
      native.lastSampleAt = now
      noteTabletPointForWheelGesture(wheelGesture, payload.phase, now)
      if (payload.phase === 'down') {
        native.penDown = true
        native.mouseStroke = false
      }
      if (payload.phase === 'up') {
        native.penDown = false
        native.pressure = 0
      }
    } else if (payload.kind === 'proximity') {
      native.penInProximity = payload.entering
      native.eraser = payload.entering && payload.eraser
      if (!payload.entering) {
        releaseTabletWheelGesture(wheelGesture)
        native.penDown = false
        native.pressure = 0
        native.lastSampleAt = 0
      }
    } else if (payload.kind === 'mouseStroke') {
      native.mouseStroke = payload.down
      if (payload.down) {
        releaseTabletWheelGesture(wheelGesture)
        native.penDown = false
      }
    } else {
      handleMiddlePan(payload)
    }
  }).then((unlisten) => {
    // HMR can dispose this module before the shell resolves the asynchronous
    // subscription. Never leave that stale native listener attached.
    if (generation !== listeningGeneration) unlisten()
    else stopNativeListening = unlisten
  }).catch(() => {
    // Not fatal: strokes fall back to mouse behavior.
  })
}

/**
 * Claim a wheel event as Wacom Pan/Scroll.
 *
 * The driver stops tablet-point delivery after it takes over the gesture, so
 * this deliberately latches beyond the normal pressure sample freshness window.
 */
export function tabletWheelPanActive(): boolean {
  ensureListening()
  return claimTabletWheelGesture(
    wheelGesture,
    performance.now(),
    native.penInProximity,
    native.mouseStroke,
  )
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    listeningGeneration += 1
    stopNativeListening?.()
    stopNativeListening = null
    panListeners.clear()
    started = false
  })
}

/** Subscribe to the complete native macOS middle/barrel drag stream. */
export function subscribeTabletPan(
  listener: (sample: NativeTabletPanSample) => void,
): () => void {
  ensureListening()
  panListeners.add(listener)
  return () => panListeners.delete(listener)
}

/**
 * Pressure for a pointer event, in [0, 1] — or null when no stylus is
 * involved and the stroke should behave exactly as a mouse stroke.
 */
export interface TabletInputAxes {
  pressure: number
  tiltX: number
  tiltY: number
  rotation: number
  tangentialPressure: number
  eraser: boolean
}

/**
 * All axes available for this DOM event. Null still means a real mouse event;
 * callers must not mistake a mouse button's synthetic pressure for a pen.
 */
export function tabletInputFor(event: PointerEvent): TabletInputAxes | null {
  ensureListening()
  if (event.pointerType === 'pen') {
    return {
      pressure: Math.max(0, Math.min(1, event.pressure)),
      tiltX: event.tiltX,
      tiltY: event.tiltY,
      rotation: event.twist,
      tangentialPressure: event.tangentialPressure,
      // Pointer Events uses button 5 for the eraser end where supported.
      eraser: event.button === 5 || native.eraser,
    }
  }
  if (native.mouseStroke) return null
  if (native.penDown || performance.now() - native.lastSampleAt < SAMPLE_FRESH_MS) {
    return {
      pressure: native.pressure,
      tiltX: native.tiltX,
      tiltY: native.tiltY,
      rotation: 0,
      tangentialPressure: 0,
      eraser: native.eraser,
    }
  }
  return null
}

export function tabletPressureFor(event: PointerEvent): number | null {
  return tabletInputFor(event)?.pressure ?? null
}
