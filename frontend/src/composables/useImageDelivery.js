/**
 * Progressive image delivery: thumb → screen → (full | original).
 *
 * Each step is fetched and decoded off-screen, then swapped into the same
 * <img> box. The box size comes from the item's known dimensions, so a swap
 * changes sharpness and nothing else: no layout shift and no fade.
 */
import { ref, shallowRef, watch, onScopeDispose, unref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useMultiDevice } from './useMultiDevice'
import { isMobileShell } from '../desktop/mobileBridge'
import { placeholderTier, sameTierBytes, isTieredImage } from '../utils/imageTiers'

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

/**
 * The bytes travel over a network rather than from this machine's disk: a
 * remote server, the mobile shell (always proxied), or a browser that opened
 * the app from another host. Remote viewers zoom with `full`, never prefetch.
 */
export function isRemoteBackend() {
  try {
    if (useMultiDevice().isRemote.value) return true
  } catch { /* outside the app shell (tests): fall through */ }
  try {
    if (isMobileShell()) return true
  } catch { /* no bridge */ }
  if (typeof window === 'undefined' || !window.location) return false
  const { protocol, hostname } = window.location
  if (protocol !== 'http:' && protocol !== 'https:') return false
  return !LOOPBACK_HOSTS.has(hostname)
}

/**
 * Fetch and decode `url` in a detached Image. Resolves true once the bitmap is
 * ready to paint without a blank frame, false on error. `cancel()` aborts.
 */
export function loadDecodedImage(url, { priority = 'auto' } = {}) {
  const image = new Image()
  if (priority !== 'auto') image.fetchPriority = priority
  let settle
  const promise = new Promise((resolve) => { settle = resolve })
  image.onload = async () => {
    image.onload = null
    image.onerror = null
    if (typeof image.decode === 'function') {
      try { await image.decode() } catch { /* loaded; decode may already be done */ }
    }
    settle(true)
  }
  image.onerror = () => {
    image.onload = null
    image.onerror = null
    settle(false)
  }
  image.src = url
  return {
    image,
    promise,
    cancel() {
      image.onload = null
      image.onerror = null
      image.src = ''
      settle(false)
    },
  }
}

const TIER_RANK = { thumb: 0, screen: 1, full: 2, original: 3 }

/**
 * Drive one progressive image for `item` (a ref or getter).
 *
 * Options:
 * - `loadScreen(url)`: how to fetch the screen tier (Promise<boolean>); the
 *   slideshow passes its decoded-image cache so neighbors stay warm.
 * - `isWarm(url)`: true when `url` is already decoded, so the thumb step can
 *   be skipped.
 * - `enabled`: ref/getter; when false nothing is loaded.
 *
 * Returns `src` (bind to the <img>), `tier` (what `src` holds), `upgrading`
 * (a higher tier is in flight, for a quiet progress ring),
 * `requestTier(tier)` to upgrade, e.g. on zoom start, and `prefetchTier(tier)`
 * to warm a tier quietly so a later request swaps at once.
 */
export function useProgressiveImage(item, options = {}) {
  const { getImageTierUrl } = useMediaApi()
  const src = ref('')
  const tier = ref(null)
  const upgrading = ref(false)
  const current = shallowRef(null)
  let generation = 0
  let screenLoad = null
  let upgradeLoad = null
  let upgradeTarget = null
  // Quiet loads started ahead of need (local original at idle), by tier.
  const prefetched = new Map()
  // Keeps the decoded bitmap of what is shown alive until the next swap.
  let retained = null

  const read = (value) => (typeof value === 'function' ? value() : unref(value))
  const loadScreen = options.loadScreen
    || ((url) => { screenLoad = loadDecodedImage(url, { priority: 'high' }); return screenLoad.promise })

  function show(nextTier, url, image = null) {
    tier.value = nextTier
    src.value = url
    if (image) retained = image
  }

  function cancelLoads() {
    screenLoad?.cancel()
    screenLoad = null
    upgradeLoad?.cancel()
    upgradeLoad = null
    upgradeTarget = null
    upgrading.value = false
    for (const load of prefetched.values()) load.cancel()
    prefetched.clear()
  }

  async function start(next) {
    const epoch = ++generation
    cancelLoads()
    retained = null
    current.value = next
    if (!next?.file_hash || read(options.enabled) === false) {
      tier.value = null
      src.value = ''
      return
    }
    if (!isTieredImage(next)) {
      show('original', getImageTierUrl(next, 'original'))
      return
    }
    const screenUrl = getImageTierUrl(next, 'screen')
    const screenTier = sameTierBytes(next, 'screen', 'original') ? 'original' : 'screen'
    if (options.isWarm?.(screenUrl)) {
      show(screenTier, screenUrl)
      return
    }
    const placeholder = placeholderTier(next)
    if (!placeholder) {
      show(screenTier, screenUrl)
      return
    }
    show('thumb', getImageTierUrl(next, 'thumb'))
    const loaded = await loadScreen(screenUrl)
    if (epoch !== generation) return
    // Even a failed screen load swaps: the <img> then shows the original or
    // reports its own error through the normal recovery path.
    if (TIER_RANK[tier.value] < TIER_RANK[screenTier]) {
      show(screenTier, loaded ? screenUrl : getImageTierUrl(next, 'original'))
    }
  }

  /** Upgrade to `nextTier` ('full' | 'original'), swapping once decoded. */
  async function requestTier(nextTier) {
    const target = current.value
    if (!target?.file_hash || !isTieredImage(target)) return false
    if (tier.value && (sameTierBytes(target, nextTier, tier.value) || TIER_RANK[tier.value] >= TIER_RANK[nextTier])) return true
    if (upgradeTarget && TIER_RANK[upgradeTarget] >= TIER_RANK[nextTier]) return upgradeLoad?.promise ?? true
    upgradeLoad?.cancel()
    const epoch = generation
    const url = getImageTierUrl(target, nextTier)
    const load = prefetched.get(nextTier) ?? loadDecodedImage(url, { priority: 'high' })
    prefetched.delete(nextTier)
    upgradeLoad = load
    upgradeTarget = nextTier
    upgrading.value = true
    const loaded = await load.promise
    if (epoch !== generation || upgradeLoad !== load) return false
    upgradeLoad = null
    upgradeTarget = null
    upgrading.value = false
    if (loaded) show(nextTier, url, load.image)
    return loaded
  }

  /** Fetch and decode `nextTier` without showing it, so a later request is instant. */
  function prefetchTier(nextTier) {
    const target = current.value
    if (!target?.file_hash || !isTieredImage(target) || prefetched.has(nextTier)) return
    if (tier.value && (sameTierBytes(target, nextTier, tier.value) || TIER_RANK[tier.value] >= TIER_RANK[nextTier])) return
    if (upgradeTarget === nextTier) return
    prefetched.set(nextTier, loadDecodedImage(getImageTierUrl(target, nextTier), { priority: 'low' }))
  }

  const stop = watch(
    () => {
      const value = read(item)
      // A string key: a refreshed copy of the same item must not restart.
      return `${value?.file_hash ?? ''}|${value?.id ?? ''}|${read(options.enabled) !== false}`
    },
    () => { void start(read(item)) },
    { immediate: true },
  )

  onScopeDispose(() => {
    stop()
    generation++
    cancelLoads()
    retained = null
  })

  return { src, tier, upgrading, requestTier, prefetchTier, reset: () => start(read(item)) }
}
