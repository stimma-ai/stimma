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
          class="bg-checker max-w-full max-h-full"
          :style="aspectRatioStyle"
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
            :loading="loading"
            draggable="false"
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
        'w-full h-full object-cover bg-checker transition-opacity duration-150',
        loaded ? 'opacity-100' : 'opacity-0',
        imgClass
      ]"
      :loading="loading"
      draggable="false"
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
import { ref, watch, computed, onBeforeUnmount } from 'vue'

interface Props {
  src?: string
  alt?: string
  /** Use object-contain (fit whole image). Default is object-cover (fill, may crop). */
  contain?: boolean
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
}

const props = withDefaults(defineProps<Props>(), {
  alt: '',
  contain: false,
  containerClass: '',
  imgClass: '',
  loading: 'lazy',
  draggable: false,
  preservePreviousOnSrcChange: false,
  retryOnError: false,
  maxRetries: 4
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
  (e: 'load', event: Event): void
  (e: 'error', event: Event): void
  (e: 'dragstart', event: DragEvent): void
}>()

const loaded = ref(false)
const error = ref(false)
const imgRef = ref<HTMLImageElement | null>(null)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const displaySrc = ref(props.src || '')
let preloadRequestId = 0

// Auto-retry state. A failed load (e.g. a layout thumbnail the backend hasn't
// finished rasterizing) is re-fetched with a cache-busting param after a short
// backoff so the browser actually re-requests it instead of reusing the cached
// failure. We keep showing the loading skeleton across retries rather than
// flashing the broken-image icon.
let retryCount = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null

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

onBeforeUnmount(clearRetryTimer)

// Aspect ratio style for contain mode wrapper
// This ensures the checker div is exactly the size of the visible image content
const aspectRatioStyle = computed(() => {
  if (naturalWidth.value && naturalHeight.value) {
    return {
      aspectRatio: `${naturalWidth.value} / ${naturalHeight.value}`
    }
  }
  // Before image loads, use a square placeholder
  return { aspectRatio: '1 / 1' }
})

// Reset state when src changes. Optionally keep old image visible until next src is ready.
watch(() => props.src, (nextSrc) => {
  const normalizedSrc = nextSrc || ''

  // A genuinely new source starts its retry budget fresh.
  clearRetryTimer()
  retryCount = 0

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
    displaySrc.value = normalizedSrc
    loaded.value = true
    error.value = false
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
  const img = event.target as HTMLImageElement
  naturalWidth.value = img.naturalWidth
  naturalHeight.value = img.naturalHeight
  loaded.value = true
  error.value = false
  retryCount = 0
  clearRetryTimer()
  emit('load', event)
}

function handleError(event: Event) {
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
