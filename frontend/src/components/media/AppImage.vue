<template>
  <!--
    Base image component with consistent loading, error, and transparency handling.

    - Loading: Shows pulse animation until image loads
    - Error: Shows broken image icon
    - Transparency: bg-checker shows through transparent pixels
    - Contain mode: black letterbox, checker through image transparency
    - Cover mode: checker behind entire image (no letterbox)
  -->
  <div
    ref="containerRef"
    :class="[
      'relative overflow-hidden',
      contain ? 'bg-surface-raised' : 'bg-base',
      containerClass
    ]"
    :style="{ transform: 'translateZ(0)' }"
    :draggable="draggable"
    @dragstart="$emit('dragstart', $event)"
  >
    <!-- Loading skeleton (shown until image loads or errors) -->
    <div
      v-if="!loaded && !error"
      class="absolute inset-0 bg-surface animate-pulse"
    />

    <!-- CONTAIN MODE: Use flex centering with aspect-ratio wrapper for proper checker placement -->
    <template v-if="contain && displaySrc && !error">
      <div class="absolute inset-0 flex items-center justify-center">
        <div
          :class="['max-w-full max-h-full', loaded && showChecker ? 'bg-checker' : '']"
          :style="contentStyle"
          :draggable="draggable"
          @dragstart="$emit('dragstart', $event)"
        >
          <img
            ref="imgRef"
            :src="displaySrc"
            :alt="alt"
            :class="[
              'w-full h-full transition-opacity duration-150',
              loaded ? 'opacity-100' : 'opacity-0',
              imgClass
            ]"
            :loading="effectiveLoading"
            :draggable="draggable"
            @load="handleLoad"
            @error="handleError"
            @click="$emit('click', $event)"
          />
        </div>
      </div>
    </template>

    <!-- COVER MODE: Standard approach with bg-checker on img -->
    <img
      v-else-if="!contain && displaySrc && !error"
      :src="displaySrc"
      :alt="alt"
      :class="[
        'w-full h-full object-cover transition-opacity duration-150',
        showChecker ? 'bg-checker' : '',
        loaded ? 'opacity-100' : 'opacity-0',
        imgClass
      ]"
      :loading="effectiveLoading"
      :draggable="draggable"
      @load="handleLoad"
      @error="handleError"
      @click="$emit('click', $event)"
    />

    <!-- Error state -->
    <div
      v-if="error"
      class="absolute inset-0 flex items-center justify-center bg-base"
    >
      <!-- Broken image icon (heroicons photo with X) -->
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="1.5"
        stroke="currentColor"
        class="w-8 h-8 text-content-muted"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"
        />
        <!-- X overlay -->
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M6 18L18 6M6 6l12 12"
          stroke-width="2"
          class="text-red-500/50"
        />
      </svg>
    </div>

    <!-- Slot for overlays (badges, hover effects, etc.) -->
    <slot />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import { enqueueThumbnail, type ThumbnailQueueHandle } from '../../composables/useThumbnailQueue'

interface Props {
  src?: string
  alt?: string
  /** Use object-contain (fit whole image). Default is object-cover (fill, may crop). */
  contain?: boolean
  /**
   * Whether the source file actually has an alpha channel (from media
   * metadata, computed at ingest — header-only, no pixel decode). `false`
   * means the checkerboard never renders at all, so there's nothing to race
   * against a loading image. `null`/`undefined` (unknown — not a library
   * item, or metadata predates this field) falls back to the old
   * load-gated checker so nothing regresses.
   */
  hasAlpha?: boolean | null
  /** Additional classes for the container div */
  containerClass?: string
  /** Additional classes for the img element */
  imgClass?: string
  /** Loading attribute for lazy loading */
  loading?: 'lazy' | 'eager'
  /** Whether the image is draggable */
  draggable?: boolean | 'true' | 'false'
  /** Keep current image visible until the next src has loaded to avoid flicker on rapid src swaps */
  preservePreviousOnSrcChange?: boolean
  /**
   * Auto-retry a failed load with backoff before showing the broken-image icon.
   * Use for sources that may be generated lazily/asynchronously (e.g. layout
   * thumbnails the backend rasterizes on demand and may not have ready yet).
   */
  retryOnError?: boolean
  /** Max auto-retry attempts when retryOnError is set. */
  maxRetries?: number
  /**
   * Route this load through the app-level thumbnail admission queue: the
   * request doesn't start until a slot frees up, nearest-to-viewport first.
   * Keeps big scroll bursts from flooding the connection pool and the
   * backend's generation workers. Takes precedence over
   * preservePreviousOnSrcChange.
   */
  queued?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  alt: '',
  contain: false,
  hasAlpha: null,
  containerClass: '',
  imgClass: '',
  loading: 'lazy',
  draggable: false,
  preservePreviousOnSrcChange: false,
  retryOnError: false,
  maxRetries: 4,
  queued: false
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
  (e: 'load', event: Event): void
  (e: 'error', event: Event): void
  (e: 'dragstart', event: DragEvent): void
}>()

const loaded = ref(false)
const error = ref(false)
// hasAlpha === false is a known fact from file metadata — never render the
// checker for opaque content, so there's no loading race to hide. Unknown
// (null/undefined) keeps today's load-gated checker as a safe fallback.
const showChecker = computed(() => props.hasAlpha !== false)
// Queued loads must fetch as soon as their src is applied — admission control
// has already decided the timing, and native lazy-loading deferring an
// admitted request would hold its queue slot without making progress.
const effectiveLoading = computed(() => (props.queued ? 'eager' : props.loading))
const imgRef = ref<HTMLImageElement | null>(null)
const containerRef = ref<HTMLElement | null>(null)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const containerWidth = ref(0)
const containerHeight = ref(0)
const displaySrc = ref(props.src || '')
let preloadRequestId = 0
let resizeObserver: ResizeObserver | null = null

// Auto-retry state. A failed load (e.g. a layout thumbnail the backend hasn't
// finished rasterizing) is re-fetched with a cache-busting param after a short
// backoff so the browser actually re-requests it instead of reusing the cached
// failure. We keep showing the loading skeleton across retries rather than
// flashing the broken-image icon.
let retryCount = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let queueHandle: ThumbnailQueueHandle | null = null

function clearRetryTimer() {
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
}

function withRetryParam(src: string, attempt: number): string {
  if (!attempt) return src
  const sep = src.includes('?') ? '&' : '?'
  return `${src}${sep}_imgretry=${attempt}`
}

// Contain-mode sizing. The checker wrapper must be exactly the size of the
// visible (letterboxed) image content. We can't lean on CSS auto-sizing for
// this: the wrapper is a flex item, so width:auto resolves to the image's
// intrinsic pixel size — fine when the source is the full-res file, but
// thumbnails (e.g. 256px) then render smaller than the tile with a uniform
// border instead of filling it. Instead we measure the container and compute
// the contained box ourselves from the image's natural aspect, which fills
// (and upscales small thumbnails) while preserving aspect and keeping the
// checker exactly behind the content. Measured only in contain mode.
const contentStyle = computed(() => {
  const nw = naturalWidth.value
  const nh = naturalHeight.value
  const cw = containerWidth.value
  const ch = containerHeight.value
  if (nw && nh && cw && ch) {
    const scale = Math.min(cw / nw, ch / nh)
    return {
      width: `${Math.round(nw * scale)}px`,
      height: `${Math.round(nh * scale)}px`
    }
  }
  // Before the image or container is measured, fall back to an aspect-ratio
  // box (capped by max-w/h-full on the element) so there's no overflow.
  if (nw && nh) return { aspectRatio: `${nw} / ${nh}` }
  return { aspectRatio: '1 / 1' }
})

onMounted(() => {
  // Only contain mode needs container measurements; cover mode fills via
  // object-cover, so we avoid attaching observers to the (many) grid images.
  if (!props.contain || !containerRef.value || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect
    if (rect) {
      containerWidth.value = rect.width
      containerHeight.value = rect.height
    }
  })
  resizeObserver.observe(containerRef.value)
})

onBeforeUnmount(() => {
  clearRetryTimer()
  queueHandle?.cancel()
  queueHandle = null
  resizeObserver?.disconnect()
  resizeObserver = null
})

// Reset state when src changes. Optionally keep old image visible until next src is ready.
watch(() => props.src, (nextSrc) => {
  const normalizedSrc = nextSrc || ''

  // A genuinely new source starts its retry budget fresh.
  clearRetryTimer()
  retryCount = 0

  // The previous source's queue slot is stale either way: pending entries
  // dequeue without ever issuing a request; an in-flight one frees its slot
  // (the img unrenders when displaySrc clears, aborting the network request).
  queueHandle?.cancel()
  queueHandle = null

  if (props.queued) {
    displaySrc.value = ''
    loaded.value = false
    error.value = false
    naturalWidth.value = 0
    naturalHeight.value = 0
    if (!normalizedSrc) return
    const handle = enqueueThumbnail(() => containerRef.value)
    queueHandle = handle
    handle.admitted.then(() => {
      // Bail if the src moved on (or the component unmounted) while queued.
      if (queueHandle !== handle) return
      displaySrc.value = normalizedSrc
    })
    return
  }

  if (!props.preservePreviousOnSrcChange || !displaySrc.value || !normalizedSrc || normalizedSrc === displaySrc.value) {
    displaySrc.value = normalizedSrc
    loaded.value = false
    error.value = false
    naturalWidth.value = 0
    naturalHeight.value = 0
    return
  }

  const requestId = ++preloadRequestId
  const preload = new Image()
  preload.onload = () => {
    if (requestId !== preloadRequestId) return
    naturalWidth.value = preload.naturalWidth
    naturalHeight.value = preload.naturalHeight
    const finish = () => {
      if (requestId !== preloadRequestId) return
      displaySrc.value = normalizedSrc
      loaded.value = true
      error.value = false
    }
    // decode() before flipping loaded — `load` alone fires before the bitmap
    // is guaranteed decoded, leaving a gap where the checker background
    // underneath shows through blank space.
    if (typeof preload.decode === 'function') {
      preload.decode().then(finish, finish)
    } else {
      finish()
    }
  }
  preload.onerror = () => {
    if (requestId !== preloadRequestId) return
    // Fall back to normal error handling with the new src.
    displaySrc.value = normalizedSrc
    loaded.value = false
    error.value = false
    naturalWidth.value = 0
    naturalHeight.value = 0
  }
  preload.src = normalizedSrc
}, { immediate: true })

function handleLoad(event: Event) {
  queueHandle?.done()
  const img = event.target as HTMLImageElement
  const srcAtLoad = displaySrc.value
  naturalWidth.value = img.naturalWidth
  naturalHeight.value = img.naturalHeight
  retryCount = 0
  clearRetryTimer()
  const finish = () => {
    // Bail if the src has already moved on (rapid swap) by the time decode() settles.
    if (displaySrc.value !== srcAtLoad) return
    loaded.value = true
    error.value = false
  }
  // decode() before flipping loaded — `load` alone fires before the bitmap is
  // guaranteed decoded, leaving a gap where the checker background underneath
  // shows through blank space.
  if (typeof img.decode === 'function') {
    img.decode().then(finish, finish)
  } else {
    finish()
  }
  emit('load', event)
}

function handleError(event: Event) {
  // Free the admission slot either way; auto-retries are rare, backoff-spaced,
  // and always for a visible tile, so they reload outside the queue.
  queueHandle?.done()
  const baseSrc = props.src || ''
  if (props.retryOnError && baseSrc && retryCount < props.maxRetries) {
    retryCount += 1
    // Backoff: 0.4s, 0.8s, 1.6s, 3.2s — covers the on-demand render window
    // without hammering the backend.
    const delay = 400 * Math.pow(2, retryCount - 1)
    loaded.value = false
    error.value = false
    clearRetryTimer()
    retryTimer = setTimeout(() => {
      retryTimer = null
      displaySrc.value = withRetryParam(baseSrc, retryCount)
    }, delay)
    return
  }
  error.value = true
  loaded.value = false
  emit('error', event)
}
</script>

<style scoped>
/* Apply EXIF orientation when rendering. Modern browsers default to this,
   but WKWebView versions in Tauri have shipped with the default off — set
   it explicitly so rotated images (e.g. portrait phone photos) display
   right-side up. */
img {
  image-orientation: from-image;
}

/* Prevent any scrollbar elements from appearing in WebKit/WKWebView */
/* This fixes a rendering bug where scrollbar corners can appear at rounded edges */
:deep(*)::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
:deep(*)::-webkit-scrollbar-corner {
  display: none;
  background: transparent;
}
</style>
