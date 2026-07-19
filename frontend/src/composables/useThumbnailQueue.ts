/**
 * App-level admission control for thumbnail loads.
 *
 * Without this, a fast scroll (or opening the slideshow over a busy view)
 * fires an unbounded burst of <img> requests. The browser's ~6-connection
 * limit then serializes them in DOM order, cache-miss requests hold
 * connections open for the whole server-side generation, and the request the
 * user actually cares about (the visible tile, the slideshow hero) starves.
 *
 * The queue admits a bounded number of thumbnail loads at a time, always
 * picking the tile closest to the viewport center next, so completion order
 * follows what's on screen rather than DOM order. Tiles that unmount or
 * change source while still queued never issue a request at all, and the
 * backend sheds their generation work when an in-flight request is aborted.
 *
 * Extra rules:
 * - While a hero/full-res load is in flight (slideshow), thumbnail admissions
 *   drop to a trickle so the hero owns the connection pool.
 * - During a fast scroll fling, admissions pause entirely until the scroll
 *   settles — tiles that merely transit the viewport never load.
 */

export interface ThumbnailQueueHandle {
  /** Resolves when this load may set its <img> src. */
  admitted: Promise<void>
  /** Call when the load finished (load or error) to free the slot. */
  done(): void
  /** Call when the tile unmounts or its source changes. */
  cancel(): void
}

interface Entry {
  getEl: () => HTMLElement | null | undefined
  resolve: () => void
  state: 'pending' | 'inflight' | 'settled'
  safetyTimer: ReturnType<typeof setTimeout> | null
}

const MAX_INFLIGHT = 8
const HERO_INFLIGHT = 2
const FAST_SCROLL_SETTLE_MS = 150
// A slot held longer than this is assumed wedged (lost load event) and freed.
const SLOT_SAFETY_MS = 30000

const pending = new Set<Entry>()
let inflight = 0
let heroCount = 0
let fastScrollUntil = 0
let pumpScheduled = false
let gateTimer: ReturnType<typeof setTimeout> | null = null

function distanceScore(entry: Entry): number {
  const el = entry.getEl()
  if (!el || !el.isConnected) return Number.POSITIVE_INFINITY
  const rect = el.getBoundingClientRect()
  // Hidden elements measure 0x0 at the origin — load them last, but load them.
  if (rect.width === 0 && rect.height === 0) return Number.MAX_SAFE_INTEGER
  const dx = rect.left + rect.width / 2 - window.innerWidth / 2
  const dy = rect.top + rect.height / 2 - window.innerHeight / 2
  return dx * dx + dy * dy
}

function settleEntry(entry: Entry) {
  if (entry.safetyTimer !== null) {
    clearTimeout(entry.safetyTimer)
    entry.safetyTimer = null
  }
  if (entry.state === 'inflight') inflight = Math.max(0, inflight - 1)
  if (entry.state === 'pending') pending.delete(entry)
  entry.state = 'settled'
}

function pump() {
  pumpScheduled = false
  const now = performance.now()
  if (now < fastScrollUntil) {
    if (gateTimer === null) {
      gateTimer = setTimeout(() => {
        gateTimer = null
        schedulePump()
      }, fastScrollUntil - now + 10)
    }
    return
  }
  const cap = heroCount > 0 ? HERO_INFLIGHT : MAX_INFLIGHT
  while (inflight < cap && pending.size > 0) {
    let best: Entry | null = null
    let bestScore = Number.POSITIVE_INFINITY
    for (const entry of pending) {
      const score = distanceScore(entry)
      if (best === null || score < bestScore) {
        best = entry
        bestScore = score
      }
    }
    if (!best) return
    pending.delete(best)
    best.state = 'inflight'
    inflight++
    const admitted = best
    admitted.safetyTimer = setTimeout(() => {
      admitted.safetyTimer = null
      if (admitted.state === 'inflight') {
        settleEntry(admitted)
        schedulePump()
      }
    }, SLOT_SAFETY_MS)
    best.resolve()
  }
}

function schedulePump() {
  if (pumpScheduled) return
  pumpScheduled = true
  requestAnimationFrame(pump)
}

/** Register a thumbnail load; resolves when it may start. */
export function enqueueThumbnail(getEl: () => HTMLElement | null | undefined): ThumbnailQueueHandle {
  let resolveAdmitted!: () => void
  const admitted = new Promise<void>((resolve) => {
    resolveAdmitted = resolve
  })
  const entry: Entry = { getEl, resolve: resolveAdmitted, state: 'pending', safetyTimer: null }
  pending.add(entry)
  schedulePump()
  return {
    admitted,
    done() {
      if (entry.state === 'settled') return
      settleEntry(entry)
      schedulePump()
    },
    cancel() {
      if (entry.state === 'settled') return
      settleEntry(entry)
      schedulePump()
    },
  }
}

/**
 * Mark a full-res hero load as in flight (e.g. the slideshow's main image).
 * While any hero is pending, thumbnail admissions drop to a trickle.
 * Returns a release function; safe to call more than once.
 */
export function beginHeroLoad(): () => void {
  heroCount++
  let released = false
  // Heroes free themselves if the caller loses track (missed load event).
  const safety = setTimeout(release, SLOT_SAFETY_MS)
  function release() {
    if (released) return
    released = true
    clearTimeout(safety)
    heroCount = Math.max(0, heroCount - 1)
    schedulePump()
  }
  return release
}

/**
 * Report a fast scroll fling. Pauses thumbnail admissions until scrolling has
 * settled for a beat, so tiles that merely transit the viewport never load.
 */
export function noteFastScroll() {
  fastScrollUntil = performance.now() + FAST_SCROLL_SETTLE_MS
}
