<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="$emit('close')"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl w-[420px] mx-4" @click.stop>
          <!-- Header -->
          <div class="px-6 py-4 border-b border-edge flex items-center justify-between">
            <h3 class="text-lg font-semibold text-content">Export</h3>
            <button @click="$emit('close')" class="text-content-muted hover:text-content transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body — fixed structure, sections use visibility not v-if -->
          <div class="px-6 py-5 space-y-4">

            <!-- Format row -->
            <div class="flex items-center justify-between">
              <label class="text-xs font-medium text-content-tertiary uppercase tracking-wider">Format</label>
              <div class="flex gap-1">
                <button
                  v-for="fmt in availableFormats"
                  :key="fmt.value"
                  @click="format = fmt.value"
                  :class="[
                    'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                    format === fmt.value
                      ? 'bg-blue-500 text-white'
                      : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                  ]"
                >
                  {{ fmt.label }}
                </button>
              </div>
            </div>

            <!-- Quality row — always rendered for stable height, hidden when not applicable -->
            <div :class="['flex items-center gap-3 transition-opacity', showQuality ? 'opacity-100' : 'opacity-0 pointer-events-none']">
              <label class="text-xs font-medium text-content-tertiary uppercase tracking-wider w-16 shrink-0">Quality</label>
              <input
                v-model.number="quality"
                type="range"
                min="1"
                max="100"
                step="1"
                class="flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
              >
              <span class="text-xs text-content-secondary tabular-nums w-6 text-right">{{ quality }}</span>
            </div>

            <!-- Layout PNG size section -->
            <template v-if="mediaCategory === 'layout' && format === 'png'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-medium text-content-tertiary uppercase tracking-wider">Size</label>
                <div class="flex gap-1">
                  <button
                    v-for="opt in layoutScaleOptions"
                    :key="opt.value"
                    @click="selectLayoutScale(opt.value)"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      layoutScaleMode === opt.value
                        ? 'bg-blue-500 text-white'
                        : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                    ]"
                  >
                    {{ opt.label }}
                  </button>
                </div>
              </div>

              <!-- Dimensions preview / custom width -->
              <div class="h-8 flex items-center">
                <template v-if="layoutScaleMode === 'custom'">
                  <input
                    v-model.number="layoutCustomWidth"
                    type="number"
                    min="100"
                    max="16384"
                    step="1"
                    class="w-24 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                  >
                  <span class="text-xs text-content-tertiary mx-1.5">&times;</span>
                  <span class="text-xs text-content-secondary tabular-nums">{{ layoutDerivedHeight }}</span>
                  <span class="text-xs text-content-tertiary ml-1.5">px</span>
                </template>
                <template v-else>
                  <span class="text-xs text-content-secondary tabular-nums">{{ layoutOutputWidth }} &times; {{ layoutOutputHeight }}</span>
                  <span class="text-xs text-content-tertiary ml-1.5">px</span>
                </template>
              </div>
            </template>

            <!-- Resize section (images) -->
            <template v-if="mediaCategory === 'image'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-medium text-content-tertiary uppercase tracking-wider">Resize</label>
                <div class="flex gap-1">
                  <button
                    v-for="opt in resizeOptions"
                    :key="opt.value"
                    @click="resizeMode = opt.value"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      resizeMode === opt.value
                        ? 'bg-blue-500 text-white'
                        : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                    ]"
                  >
                    {{ opt.label }}
                  </button>
                </div>
              </div>

              <!-- Resize detail — fixed-height slot so the modal doesn't jump -->
              <div class="h-8 flex items-center">
                <template v-if="resizeMode === 'max_dimension'">
                  <input
                    v-model.number="maxDimension"
                    type="number"
                    min="64"
                    max="16384"
                    step="64"
                    class="w-24 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                  >
                  <span class="text-xs text-content-tertiary ml-2">px longest side</span>
                </template>
                <template v-else-if="resizeMode === 'exact'">
                  <input
                    v-model.number="exactWidth"
                    type="number"
                    min="1"
                    max="16384"
                    step="1"
                    placeholder="W"
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                  >
                  <span class="text-xs text-content-tertiary mx-1.5">&times;</span>
                  <input
                    v-model.number="exactHeight"
                    type="number"
                    min="1"
                    max="16384"
                    step="1"
                    placeholder="H"
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                  >
                  <span class="text-xs text-content-tertiary ml-1.5">px</span>
                </template>
                <template v-else-if="resizeMode === 'scale'">
                  <input
                    v-model.number="scalePercent"
                    type="number"
                    min="1"
                    max="1000"
                    step="1"
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                  >
                  <span class="text-xs text-content-tertiary ml-2">%</span>
                </template>
              </div>
            </template>

            <!-- Video resolution (video only, when converting) -->
            <template v-if="mediaCategory === 'video' && format !== 'original'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-medium text-content-tertiary uppercase tracking-wider">Resolution</label>
                <div class="flex gap-1">
                  <button
                    v-for="res in videoResolutions"
                    :key="res.value"
                    @click="videoResolution = res.value"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      videoResolution === res.value
                        ? 'bg-blue-500 text-white'
                        : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                    ]"
                  >
                    {{ res.label }}
                  </button>
                </div>
              </div>
            </template>

            <!-- Options -->
            <template v-if="mediaCategory === 'image'">
              <div class="border-t border-edge-subtle" />

              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  v-model="stripMetadata"
                  type="checkbox"
                  class="w-3.5 h-3.5 rounded border-surface-raised bg-surface-overlay accent-blue-500"
                >
                <span class="text-xs text-content-secondary">Strip metadata</span>
              </label>
            </template>

          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex gap-3 justify-end">
            <button
              @click="$emit('close')"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content-secondary rounded text-sm font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="handleExport"
              :disabled="exporting"
              :class="[
                'px-4 py-2 rounded text-sm font-medium transition-colors',
                exporting
                  ? 'bg-blue-500/50 text-white/50 cursor-not-allowed'
                  : 'bg-blue-500 hover:bg-blue-600 text-white'
              ]"
            >
              {{ exporting ? 'Exporting...' : exportButtonLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useTauriDownload } from '../composables/useTauriDownload'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  mediaIds: {
    type: Array,
    default: () => []
  },
  // Optional: pass media items so we can detect types
  // Each item should have at least { id, file_format }
  mediaItems: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'exported'])

const { downloadMedia } = useMediaApi()
const { downloadFromResponse } = useTauriDownload()

// --- State ---
const format = ref('original')
const quality = ref(85)
const resizeMode = ref('none')
const maxDimension = ref(2048)
const exactWidth = ref(1920)
const exactHeight = ref(1080)
const scalePercent = ref(50)
const stripMetadata = ref(false)
const videoResolution = ref('original')
const exporting = ref(false)

// Layout-specific state
const layoutScaleMode = ref('2x')
const layoutCustomWidth = ref(1600)
const layoutFetchedWidth = ref(0)
const layoutFetchedHeight = ref(0)
const layoutDimsLoading = ref(false)

// --- Computed ---

const IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif']
const VIDEO_FORMATS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']
const AUDIO_FORMATS = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']

const mediaCategory = computed(() => {
  if (props.mediaItems.length === 0) return 'mixed'

  const categories = new Set()
  for (const item of props.mediaItems) {
    const fmt = (item.file_format || '').toLowerCase()
    if (fmt === 'stimmalayout') categories.add('layout')
    else if (IMAGE_FORMATS.includes(fmt)) categories.add('image')
    else if (VIDEO_FORMATS.includes(fmt)) categories.add('video')
    else if (AUDIO_FORMATS.includes(fmt)) categories.add('audio')
    else categories.add('other')
  }

  if (categories.size === 1) return [...categories][0]
  return 'mixed'
})

// Layout dimensions — prefer fetched from HTML, fall back to DB, then defaults
const layoutNativeWidth = computed(() => {
  if (layoutFetchedWidth.value > 0) return layoutFetchedWidth.value
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return 800
  const item = props.mediaItems[0]
  return item.width || 800
})

const layoutNativeHeight = computed(() => {
  if (layoutFetchedHeight.value > 0) return layoutFetchedHeight.value
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return 600
  const item = props.mediaItems[0]
  return item.height || 600
})

async function fetchLayoutDimensions() {
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return
  const mediaId = props.mediaIds[0]
  layoutDimsLoading.value = true
  try {
    const response = await axios.get(`${getApiBase()}/media/${mediaId}/layout-html`)
    const html = response.data
    const wMatch = html.match(/data-stimma-width="(\d+)"/)
    const hMatch = html.match(/data-stimma-height="(\d+)"/)
    if (wMatch) layoutFetchedWidth.value = parseInt(wMatch[1])
    if (hMatch) layoutFetchedHeight.value = parseInt(hMatch[1])
  } catch (e) {
    console.warn('[ExportModal] Failed to fetch layout dimensions:', e)
  } finally {
    layoutDimsLoading.value = false
  }
}

const layoutAspect = computed(() => layoutNativeHeight.value / layoutNativeWidth.value)

const layoutScaleOptions = [
  { label: '1x', value: '1x' },
  { label: '2x', value: '2x' },
  { label: '3x', value: '3x' },
  { label: 'Custom', value: 'custom' },
]

function selectLayoutScale(value) {
  layoutScaleMode.value = value
}

const layoutScaleNumber = computed(() => {
  if (layoutScaleMode.value === '1x') return 1
  if (layoutScaleMode.value === '2x') return 2
  if (layoutScaleMode.value === '3x') return 3
  return null // custom
})

const layoutOutputWidth = computed(() => {
  if (layoutScaleMode.value === 'custom') return layoutCustomWidth.value
  return Math.round(layoutNativeWidth.value * layoutScaleNumber.value)
})

const layoutOutputHeight = computed(() => {
  if (layoutScaleMode.value === 'custom') {
    return Math.round(layoutCustomWidth.value * layoutAspect.value)
  }
  return Math.round(layoutNativeHeight.value * layoutScaleNumber.value)
})

const layoutDerivedHeight = computed(() => {
  return Math.round(layoutCustomWidth.value * layoutAspect.value)
})

const availableFormats = computed(() => {
  if (mediaCategory.value === 'layout') {
    return [
      { label: 'PDF', value: 'pdf' },
      { label: 'PNG', value: 'png' },
      { label: 'HTML', value: 'html' },
    ]
  }

  const original = { label: 'Original', value: 'original' }

  if (mediaCategory.value === 'image') {
    return [original, { label: 'JPEG', value: 'jpeg' }, { label: 'PNG', value: 'png' }, { label: 'WebP', value: 'webp' }]
  }
  if (mediaCategory.value === 'video') {
    return [original, { label: 'MP4', value: 'mp4' }, { label: 'WebM', value: 'webm' }]
  }
  if (mediaCategory.value === 'audio') {
    return [original, { label: 'MP3', value: 'mp3' }, { label: 'WAV', value: 'wav' }, { label: 'FLAC', value: 'flac' }]
  }
  // Mixed - only original
  return [original]
})

const showQuality = computed(() => {
  if (format.value === 'original') return false
  // Quality applies to lossy formats
  return ['jpeg', 'webp', 'mp4', 'webm', 'mp3'].includes(format.value)
})

const resizeOptions = [
  { label: 'None', value: 'none' },
  { label: 'Max dimension', value: 'max_dimension' },
  { label: 'Exact', value: 'exact' },
  { label: 'Scale', value: 'scale' },
]

const videoResolutions = [
  { label: 'Original', value: 'original' },
  { label: '4K', value: '2160' },
  { label: '1080p', value: '1080' },
  { label: '720p', value: '720' },
]

const isOriginalExport = computed(() => {
  if (mediaCategory.value === 'layout') return false
  return format.value === 'original'
    && resizeMode.value === 'none'
    && !stripMetadata.value
    && videoResolution.value === 'original'
})

const exportButtonLabel = computed(() => {
  const count = props.mediaIds.length
  if (count <= 1) return 'Export'
  return `Export ${count}`
})

// Reset state when modal opens
watch(() => props.show, (newVal) => {
  if (newVal) {
    layoutFetchedWidth.value = 0
    layoutFetchedHeight.value = 0
    if (mediaCategory.value === 'layout') {
      format.value = 'pdf'
      layoutScaleMode.value = '2x'
      fetchLayoutDimensions().then(() => {
        layoutCustomWidth.value = layoutNativeWidth.value * 2
      })
    } else {
      format.value = 'original'
    }
    quality.value = 85
    resizeMode.value = 'none'
    maxDimension.value = 2048
    exactWidth.value = 1920
    exactHeight.value = 1080
    scalePercent.value = 50
    stripMetadata.value = false
    videoResolution.value = 'original'
  }
})

// --- Export handler ---

async function handleExport() {
  if (exporting.value) return
  exporting.value = true

  try {
    if (mediaCategory.value === 'layout') {
      await handleLayoutExport()
    } else if (isOriginalExport.value) {
      // No conversion needed - use existing download path
      await downloadMedia(props.mediaIds)
    } else {
      // Build export options and use the new export endpoint
      const options = {}

      if (format.value !== 'original') {
        options.format = format.value
      }

      if (showQuality.value) {
        options.quality = quality.value
      }

      if (mediaCategory.value === 'image' && resizeMode.value !== 'none') {
        options.resize = { mode: resizeMode.value }
        if (resizeMode.value === 'max_dimension') {
          options.resize.max_dimension = maxDimension.value
        } else if (resizeMode.value === 'exact') {
          options.resize.width = exactWidth.value
          options.resize.height = exactHeight.value
        } else if (resizeMode.value === 'scale') {
          options.resize.scale = scalePercent.value / 100
        }
      }

      if (mediaCategory.value === 'video' && videoResolution.value !== 'original') {
        options.video_resolution = videoResolution.value
      }

      if (stripMetadata.value) {
        options.strip_metadata = true
      }

      const response = await axios.post(
        `${getApiBase()}/media/export`,
        {
          media_ids: props.mediaIds.map(id => parseInt(id)),
          options
        },
        { responseType: 'blob' }
      )

      const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
      let filename = 'export'
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="([^"]+)"/)
        if (match) filename = match[1]
      }

      await downloadFromResponse(response.data, filename)
    }

    emit('exported')
    emit('close')
  } catch (error) {
    console.error('[ExportModal] Export failed:', error)
  } finally {
    exporting.value = false
  }
}

async function handleLayoutExport() {
  const mediaId = props.mediaIds[0]
  const body = { format: format.value }

  if (format.value === 'png') {
    if (layoutScaleMode.value === 'custom') {
      body.width = layoutCustomWidth.value
    } else {
      body.scale = layoutScaleNumber.value
    }
  }

  const response = await axios.post(
    `${getApiBase()}/media/${mediaId}/layout-export`,
    body,
    { responseType: 'blob' }
  )

  const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
  let filename = 'layout-export'
  if (contentDisposition) {
    const match = contentDisposition.match(/filename="([^"]+)"/)
    if (match) filename = match[1]
  }

  await downloadFromResponse(response.data, filename)
}
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
