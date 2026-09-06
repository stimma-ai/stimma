/**
 * The single source of truth for "what kind of screen is this".
 *
 * Nothing else in the app may read window.innerWidth or evaluate a width /
 * pointer media query to make a layout decision (popover positioning math is
 * geometry, not a layout decision, and is fine). One place means one bug: the
 * compact chrome, the kit's touch behaviour and the phone acceptance lane all
 * agree on where the line is.
 *
 * Breakpoints (match Tailwind's md / lg):
 *   compact  < 768px   phones, narrow split view      → tab bar + compact header
 *   medium   768–1023  tablets, narrow windows        → sidebar collapses (later)
 *   wide     ≥ 1024    today's desktop layout
 *
 * On a desktop-sized window every flag is false and every code path is the
 * one that existed before mobile work started. That is the regression
 * guarantee for desktop: mobile behaviour is an additive branch desktop never
 * trips.
 *
 * Override for dev and tests: `?viewport=compact|medium|wide` and
 * `?pointer=coarse|fine` on the URL pin the values for the session so the
 * compact chrome can be exercised in a desktop window (and the phone lane can
 * force it without relying on emulation alone). `clearViewportOverride()`
 * returns to the live media queries.
 */
import { computed, readonly, ref } from 'vue'

export type ViewportTier = 'compact' | 'medium' | 'wide'
export type PointerKind = 'coarse' | 'fine'

const OVERRIDE_KEY = 'stimma-viewport-override'

const COMPACT_MAX = 767
const MEDIUM_MAX = 1023

const hasWindow = typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const compactQuery = hasWindow ? window.matchMedia(`(max-width: ${COMPACT_MAX}px)`) : null
const mediumQuery = hasWindow ? window.matchMedia(`(min-width: ${COMPACT_MAX + 1}px) and (max-width: ${MEDIUM_MAX}px)`) : null
const coarseQuery = hasWindow ? window.matchMedia('(pointer: coarse)') : null

const liveTier = ref<ViewportTier>(readTier())
const livePointer = ref<PointerKind>(coarseQuery?.matches ? 'coarse' : 'fine')

interface Override { tier?: ViewportTier; pointer?: PointerKind }
const override = ref<Override>(readOverride())

function readTier(): ViewportTier {
  if (compactQuery?.matches) return 'compact'
  if (mediumQuery?.matches) return 'medium'
  return 'wide'
}

function readOverride(): Override {
  if (!hasWindow) return {}
  const out: Override = {}
  try {
    const params = new URLSearchParams(window.location.search)
    const tier = params.get('viewport')
    const pointer = params.get('pointer')
    if (tier === 'compact' || tier === 'medium' || tier === 'wide') out.tier = tier
    if (pointer === 'coarse' || pointer === 'fine') out.pointer = pointer
    if (out.tier || out.pointer) {
      window.sessionStorage.setItem(OVERRIDE_KEY, JSON.stringify(out))
      return out
    }
    const stored = window.sessionStorage.getItem(OVERRIDE_KEY)
    if (stored) return JSON.parse(stored) as Override
  } catch {
    // sessionStorage can be unavailable (privacy modes); live queries win.
  }
  return {}
}

if (hasWindow) {
  const refresh = () => { liveTier.value = readTier() }
  compactQuery?.addEventListener('change', refresh)
  mediumQuery?.addEventListener('change', refresh)
  coarseQuery?.addEventListener('change', (e) => { livePointer.value = e.matches ? 'coarse' : 'fine' })
}

const tier = computed<ViewportTier>(() => override.value.tier ?? liveTier.value)
const pointer = computed<PointerKind>(() => override.value.pointer ?? livePointer.value)
const isCompact = computed(() => tier.value === 'compact')
const isMedium = computed(() => tier.value === 'medium')
const isWide = computed(() => tier.value === 'wide')
const isCoarsePointer = computed(() => pointer.value === 'coarse')
const hasOverride = computed(() => !!(override.value.tier || override.value.pointer))

/** Mirror onto <html> so CSS and tests can hook the same truth. */
if (hasWindow) {
  const apply = () => {
    document.documentElement.setAttribute('data-viewport', tier.value)
    document.documentElement.setAttribute('data-pointer', pointer.value)
  }
  apply()
  // Cheap manual watch: no Vue app context is guaranteed at module init.
  const q = [compactQuery, mediumQuery, coarseQuery]
  q.forEach((m) => m?.addEventListener('change', () => queueMicrotask(apply)))
  ;(window as unknown as { __stimmaViewportApply?: () => void }).__stimmaViewportApply = apply
}

export function setViewportOverride(next: Override) {
  override.value = { ...next }
  if (hasWindow) {
    try { window.sessionStorage.setItem(OVERRIDE_KEY, JSON.stringify(override.value)) } catch { /* ignore */ }
    ;(window as unknown as { __stimmaViewportApply?: () => void }).__stimmaViewportApply?.()
  }
}

export function clearViewportOverride() {
  override.value = {}
  if (hasWindow) {
    try { window.sessionStorage.removeItem(OVERRIDE_KEY) } catch { /* ignore */ }
    ;(window as unknown as { __stimmaViewportApply?: () => void }).__stimmaViewportApply?.()
  }
}

export function useViewport() {
  return {
    tier: readonly(tier),
    pointer: readonly(pointer),
    isCompact,
    isMedium,
    isWide,
    isCoarsePointer,
    hasOverride,
    setViewportOverride,
    clearViewportOverride,
  }
}
