<!--
  Viewer for .svg documents.

  The document renders through an <img>, never by inlining its markup into the
  page. An <img>-loaded SVG cannot execute script or fetch anything, so a file
  that arrived from a watched Source is inert here regardless of what it
  contains — and its ids and styles cannot collide with the app shell.

  Clicks on the artwork are left to bubble so the host (the chat artifact stage)
  can open the slideshow or a context menu. The control row below stops them, so
  operating the controls never doubles as a click on the work.
-->
<template>
  <div
    ref="containerRef"
    class="w-full h-full flex flex-col items-center justify-center overflow-hidden"
  >
    <div v-if="loading" class="text-content-tertiary text-sm">
      Loading…
    </div>

    <div v-else-if="error" class="text-sm text-content-secondary px-6 text-center">
      {{ error }}
    </div>

    <template v-else>
      <div class="flex-1 min-h-0 w-full flex items-center justify-center p-4 overflow-auto custom-scrollbar">
        <div :class="['flex-none overflow-hidden rounded-media', backgroundClass]" :style="stageStyle">
          <img
            :src="documentUrl"
            :style="imageStyle"
            class="block"
            :alt="`SVG document, ${naturalWidth} by ${naturalHeight}`"
            draggable="false"
            @error="imageFailed = true"
            @load="imageFailed = false"
          />
        </div>
      </div>

      <div
        class="flex-shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-3 pt-1 cursor-default"
        @click.stop
        @contextmenu.stop
        @pointerdown.stop
        @wheel.stop
      >
        <!-- Scale picker: percentages for judging the design, pixel widths for
             judging it at the size it will actually be used. -->
        <div class="relative" ref="scaleMenuRef">
          <button
            type="button"
            class="flex items-center gap-1 h-7 px-2.5 rounded border border-edge bg-overlay-subtle text-xs font-medium text-content-secondary hover:bg-overlay-hover hover:text-content transition-colors tabular-nums"
            @click="showScaleMenu = !showScaleMenu"
          >
            {{ scaleLabel }}
            <ChevronDownIcon class="w-3 h-3" />
          </button>

          <div
            v-if="showScaleMenu"
            class="absolute bottom-full left-0 mb-1 w-44 max-h-80 overflow-y-auto bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1 custom-scrollbar"
          >
            <button
              type="button"
              class="w-full flex items-center px-2.5 py-1.5 text-left text-[11.5px] rounded-md transition-colors"
              :class="scaleMode === 'fit' ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-hover'"
              @click="selectScale('fit')"
            >
              Fit to window
            </button>

            <div class="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-content-muted">
              Scale
            </div>
            <button
              v-for="pct in PERCENT_STEPS"
              :key="`pct-${pct}`"
              type="button"
              class="w-full flex items-center justify-between px-2.5 py-1.5 text-left text-[11.5px] rounded-md transition-colors tabular-nums"
              :class="scaleMode === 'percent' && percentValue === pct ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-hover'"
              @click="selectScale('percent', pct)"
            >
              <span>{{ pct }}%</span>
              <span class="text-[10px] text-content-muted">{{ Math.round(naturalWidth * pct / 100) }} px</span>
            </button>

            <div class="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-content-muted">
              Width
            </div>
            <button
              v-for="px in PIXEL_STEPS"
              :key="`px-${px}`"
              type="button"
              class="w-full flex items-center justify-between px-2.5 py-1.5 text-left text-[11.5px] rounded-md transition-colors tabular-nums"
              :class="scaleMode === 'pixels' && pixelValue === px ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-hover'"
              @click="selectScale('pixels', px)"
            >
              <span>{{ px }} px</span>
              <span class="text-[10px] text-content-muted">{{ PIXEL_HINTS[px] || '' }}</span>
            </button>
          </div>
        </div>

        <div class="w-px h-5 bg-edge"></div>

        <div class="flex items-center gap-1">
          <button
            v-for="option in BACKGROUND_OPTIONS"
            :key="option.value"
            :class="toggleClass(background === option.value)"
            @click="selectBackground(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="text-xs text-content-tertiary tabular-nums">
          {{ naturalWidth }} × {{ naturalHeight }}
        </div>
      </div>

      <div
        v-if="imageFailed"
        class="flex-shrink-0 px-4 pb-3 text-xs text-content-secondary text-center"
      >
        The document could not be rendered.
      </div>

      <div
        v-else-if="warnings.length"
        class="flex-shrink-0 px-4 pb-3 text-xs text-content-tertiary max-w-xl text-center"
      >
        {{ warnings.join(' · ') }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'
import { getApiBase } from '../../apiConfig'
import { useMediaApi } from '../../composables/useMediaApi'
import { makeProfileKey } from '../../utils/storageKeys'
import { syncedStorage } from '../../utils/workspaceStore'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true,
  },
})

// Percentages judge the design; pixel widths judge it at the size it ships at.
// Both matter here, because a mark that reads at 512 can turn to mud at 16.
const PERCENT_STEPS = [25, 50, 100, 200, 400, 800]
const PIXEL_STEPS = [16, 24, 32, 48, 64, 128, 180, 256, 512, 1024]
const PIXEL_HINTS = {
  16: 'favicon',
  24: 'UI icon',
  32: 'favicon 2x',
  48: 'toolbar',
  180: 'apple touch',
  512: 'store',
  1024: 'app icon',
}

// Transparency is the normal state for an icon or a logo, so the ground is a
// control rather than a fixed choice: a white mark and a black mark cannot both
// be legible against the same backdrop. Auto is the default and reads the
// document's own paint (svg-info's `ink`), because the failure it prevents —
// a black icon on the app's dark chrome — looks like a bug, not a preference.
const BACKGROUND_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'checker', label: 'Checker' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

// Ink tone → the ground that keeps it legible. 'mixed' means the document uses
// more than one tone (or paint we cannot reduce), where checkerboard is the
// honest answer.
const GROUND_FOR_INK = { dark: 'light', light: 'dark', mixed: 'checker' }

const BACKGROUND_STORAGE_PART = 'background'

const loading = ref(true)
const error = ref(null)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const warnings = ref([])
const imageFailed = ref(false)

const scaleMode = ref('fit')
const percentValue = ref(100)
const pixelValue = ref(256)
const showScaleMenu = ref(false)
const scaleMenuRef = ref(null)

const background = ref('auto')
const ink = ref('mixed')

const containerRef = ref(null)
const containerWidth = ref(0)
const containerHeight = ref(0)
let resizeObserver = null

const { getSvgDocumentUrl } = useMediaApi()

// Built by useMediaApi, not by hand: an <img> cannot send the X-Profile-ID
// header, so the URL has to carry its database in the path.
const documentUrl = computed(() => getSvgDocumentUrl(props.mediaId))

const resolvedBackground = computed(() =>
  background.value === 'auto' ? (GROUND_FOR_INK[ink.value] || 'checker') : background.value
)

const backgroundClass = computed(() => ({
  checker: 'bg-checker',
  light: 'bg-white',
  dark: 'bg-black',
}[resolvedBackground.value]))

function backgroundStorageKey() {
  return makeProfileKey('svg-viewer', BACKGROUND_STORAGE_PART)
}

function selectBackground(value) {
  background.value = value
  try {
    syncedStorage.setItem(backgroundStorageKey(), value)
  } catch {
    // A full or unavailable localStorage must not break the viewer.
  }
}

function toggleClass(active) {
  const base = 'px-2.5 h-7 rounded text-xs font-medium transition-colors cursor-pointer'
  return active
    ? `${base} bg-accent/15 text-accent-hi`
    : `${base} text-content-tertiary hover:text-content hover:bg-surface`
}

function selectScale(mode, value) {
  scaleMode.value = mode
  if (mode === 'percent') percentValue.value = value
  if (mode === 'pixels') pixelValue.value = value
  showScaleMenu.value = false
}

const scaleLabel = computed(() => {
  if (scaleMode.value === 'percent') return `${percentValue.value}%`
  if (scaleMode.value === 'pixels') return `${pixelValue.value} px`
  return 'Fit'
})

const scale = computed(() => {
  if (!naturalWidth.value || !naturalHeight.value) return 1
  if (scaleMode.value === 'percent') return percentValue.value / 100
  if (scaleMode.value === 'pixels') return pixelValue.value / naturalWidth.value
  if (!containerWidth.value || !containerHeight.value) return 1
  // Padding allowance matches the p-4 on the stage wrapper.
  const available = Math.max(1, containerWidth.value - 32)
  const availableHeight = Math.max(1, containerHeight.value - 32)
  // Fit UPSCALES. Capping at 1:1 is a raster habit — it left a 24-unit icon as
  // a 24px speck in the middle of the stage. Vector has no native pixel size to
  // respect, so "fit to window" means fit the window.
  return Math.min(available / naturalWidth.value, availableHeight / naturalHeight.value)
})

const renderWidth = computed(() => Math.max(1, Math.round(naturalWidth.value * scale.value)))
const renderHeight = computed(() => Math.max(1, Math.round(naturalHeight.value * scale.value)))

const stageStyle = computed(() => ({
  width: `${renderWidth.value}px`,
  height: `${renderHeight.value}px`,
}))

const imageStyle = computed(() => ({
  width: `${renderWidth.value}px`,
  height: `${renderHeight.value}px`,
}))

function onDocumentClick(event) {
  if (scaleMenuRef.value && !scaleMenuRef.value.contains(event.target)) {
    showScaleMenu.value = false
  }
}

onMounted(() => {
  try {
    const saved = syncedStorage.getItem(backgroundStorageKey())
    if (BACKGROUND_OPTIONS.some(o => o.value === saved)) background.value = saved
  } catch {
    // Ignore — the default ground is fine.
  }

  resizeObserver = new ResizeObserver(entries => {
    for (const entry of entries) {
      containerWidth.value = entry.contentRect.width
      containerHeight.value = entry.contentRect.height
    }
  })
  if (containerRef.value) resizeObserver.observe(containerRef.value)
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  document.removeEventListener('click', onDocumentClick)
})

async function loadInfo() {
  loading.value = true
  error.value = null
  warnings.value = []
  imageFailed.value = false
  try {
    const { data } = await axios.get(`${getApiBase()}/media/${props.mediaId}/svg-info`)
    naturalWidth.value = data.width
    naturalHeight.value = data.height
    ink.value = data.ink || 'mixed'
    warnings.value = data.warnings || []
  } catch (e) {
    error.value = e.response?.data?.detail || `Failed to load SVG: ${e.message}`
  } finally {
    loading.value = false
  }
}

watch(() => props.mediaId, loadInfo, { immediate: true })
</script>
