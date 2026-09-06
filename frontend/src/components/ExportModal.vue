<template>
  <Modal :show="show" size="custom" custom-class="max-w-[420px] w-full" @close="$emit('close')">
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-content">Export</h3>
        <IconButton @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

          <div class="px-6 py-5 space-y-5">

            <!-- Sprite targets: grouped Engines / Generic / Preview, same radio grammar. -->
            <template v-if="mediaCategory === 'sprite'">
              <div v-for="group in SPRITE_FORMAT_GROUPS" :key="group.label" class="space-y-2">
                <p class="text-xs font-semibold text-content-secondary">{{ group.label }}</p>
                <div class="grid grid-cols-3 gap-1.5" role="radiogroup" :aria-label="`${group.label} export format`">
                  <label v-for="fmt in group.formats" :key="fmt.value" class="cursor-pointer">
                    <input v-model="format" type="radio" name="export-format" :value="fmt.value" class="peer sr-only">
                    <span
                      :class="[
                        'flex min-h-9 items-center justify-center rounded-md px-3 py-2 text-center text-xs font-medium transition-colors duration-150 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60',
                        format === fmt.value
                          ? 'bg-accent/15 text-accent'
                          : 'bg-overlay-faint text-content-secondary hover:bg-overlay-subtle hover:text-content'
                      ]"
                    >
                      {{ fmt.label }}
                    </span>
                  </label>
                </div>
              </div>
              <p v-if="spriteFormatHint" class="text-xs text-content-tertiary">{{ spriteFormatHint }}</p>

              <div v-if="spriteUsesGeometry" class="border-t border-edge-subtle" />

              <div v-if="spriteUsesGeometry" class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Scale</label>
                <div class="flex gap-1">
                  <button
                    v-for="n in [1, 2, 3, 4]"
                    :key="n"
                    type="button"
                    @click="spriteScale = n"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      spriteScale === n
                        ? 'bg-accent text-white'
                        : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                    ]"
                  >
                    {{ n }}x
                  </button>
                </div>
              </div>

              <div v-if="spriteUsesGeometry" class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Trim to content</label>
                <input v-model="spriteTrim" type="checkbox" class="accent-accent">
              </div>

              <div v-if="spriteUsesSheetOptions" class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Edge bleed</label>
                <div class="flex items-center gap-1.5">
                  <input
                    v-model.number="spriteExtrude"
                    type="number"
                    min="0"
                    max="8"
                    step="1"
                    class="w-16 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
                  >
                  <span class="text-xs text-content-tertiary">px</span>
                </div>
              </div>

              <div v-if="format === 'frames'" class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Image format</label>
                <div class="flex gap-1">
                  <button
                    v-for="opt in ['png', 'webp', 'jpg']"
                    :key="opt"
                    type="button"
                    @click="spriteImageFormat = opt"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium uppercase transition-colors',
                      spriteImageFormat === opt
                        ? 'bg-accent text-white'
                        : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                    ]"
                  >
                    {{ opt }}
                  </button>
                </div>
              </div>

              <div v-if="spriteUsesBackground" class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Background</label>
                <input v-model="spriteBackground" type="color" class="h-7 w-10 bg-transparent border border-surface-raised rounded cursor-pointer">
              </div>

              <p v-if="spriteError" class="text-xs text-red-400">{{ spriteError }}</p>
            </template>

            <!-- Formats are a grid so every choice stays legible at modal width. -->
            <div v-if="mediaCategory !== 'sprite'" class="space-y-2">
              <p class="text-xs font-semibold text-content-secondary">Format</p>
              <div
                class="grid grid-cols-3 gap-1.5"
                role="radiogroup"
                aria-label="Export format"
              >
                <label
                  v-for="fmt in availableFormats"
                  :key="fmt.value"
                  class="cursor-pointer"
                >
                  <input
                    v-model="format"
                    type="radio"
                    name="export-format"
                    :value="fmt.value"
                    class="peer sr-only"
                  >
                  <span
                    :class="[
                      'flex min-h-9 items-center justify-center rounded-md px-3 py-2 text-center text-xs font-medium transition-colors duration-150 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60',
                      format === fmt.value
                        ? 'bg-accent/15 text-accent'
                        : 'bg-overlay-faint text-content-secondary hover:bg-overlay-subtle hover:text-content'
                    ]"
                  >
                    {{ fmt.label }}
                  </span>
                </label>
              </div>
            </div>

            <div v-if="showQuality" class="flex items-center gap-3">
              <label class="text-xs font-semibold text-content-secondary w-16 shrink-0">Quality</label>
              <input
                v-model.number="quality"
                type="range"
                min="1"
                max="100"
                step="1"
                class="flex-1 h-1 bg-surface-raised rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
              >
              <span class="text-xs text-content-secondary tabular-nums w-6 text-right">{{ quality }}</span>
            </div>

            <!-- Layout PNG size section -->
            <template v-if="mediaCategory === 'layout' && format === 'png'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Size</label>
                <div class="flex gap-1">
                  <button
                    v-for="opt in layoutScaleOptions"
                    :key="opt.value"
                    @click="selectLayoutScale(opt.value)"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      layoutScaleMode === opt.value
                        ? 'bg-accent text-white'
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
                    class="w-24 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
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

            <!-- Vector (SVG) sections -->
            <template v-if="mediaCategory === 'vector'">
              <template v-if="format === 'png'">
                <div class="border-t border-edge-subtle" />

                <div class="flex items-center justify-between">
                  <label class="text-xs font-semibold text-content-secondary">Size</label>
                  <div class="flex gap-1">
                    <button
                      v-for="opt in layoutScaleOptions"
                      :key="opt.value"
                      @click="selectLayoutScale(opt.value)"
                      :class="[
                        'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                        layoutScaleMode === opt.value
                          ? 'bg-accent text-white'
                          : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                      ]"
                    >
                      {{ opt.label }}
                    </button>
                  </div>
                </div>

                <div class="h-8 flex items-center">
                  <template v-if="layoutScaleMode === 'custom'">
                    <input
                      v-model.number="layoutCustomWidth"
                      type="number"
                      min="16"
                      max="4096"
                      step="1"
                      class="w-24 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
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

              <template v-else-if="format === 'png-set'">
                <div class="border-t border-edge-subtle" />

                <div class="flex items-start justify-between gap-3">
                  <label class="text-xs font-semibold text-content-secondary pt-1">Sizes</label>
                  <div class="flex flex-wrap gap-1 justify-end">
                    <button
                      v-for="size in PNG_SET_SIZES"
                      :key="size"
                      @click="togglePngSetSize(size)"
                      :class="[
                        'px-2 py-1 rounded text-xs font-medium tabular-nums transition-colors',
                        pngSetSizes.includes(size)
                          ? 'bg-accent text-white'
                          : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                      ]"
                    >
                      {{ size }}
                    </button>
                  </div>
                </div>
              </template>

              <template v-else-if="format === 'html'">
                <div class="space-y-3">
                  <div class="flex items-center justify-between">
                    <p class="text-xs font-semibold text-content-secondary">Form</p>
                    <div class="flex gap-1">
                      <button
                        v-for="opt in CODE_VARIANTS"
                        :key="opt.value"
                        type="button"
                        :aria-pressed="codeVariant === opt.value"
                        @click="codeVariant = opt.value"
                        :class="[
                          'rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150',
                          codeVariant === opt.value
                            ? 'bg-accent/15 text-accent'
                            : 'bg-overlay-faint text-content-secondary hover:bg-overlay-subtle hover:text-content'
                        ]"
                      >
                        {{ opt.label }}
                      </button>
                    </div>
                  </div>

                  <div class="relative h-32 overflow-hidden rounded-md bg-overlay-faint">
                    <pre
                      v-if="codePreview"
                      class="h-full overflow-auto whitespace-pre p-3 pr-11 font-mono text-[11px] leading-relaxed text-content-secondary custom-scrollbar select-text"
                    >{{ codePreview }}</pre>
                    <div
                      v-else
                      class="flex h-full items-center justify-center px-4 text-center text-xs text-content-muted"
                    >
                      {{ codePreviewError || 'Generating preview…' }}
                    </div>

                    <div class="absolute right-1.5 top-1.5">
                      <Tooltip :text="copied ? 'Copied' : 'Copy code'">
                        <IconButton
                          class="bg-surface/90 backdrop-blur"
                          :disabled="codePreviewLoading || !codePreview"
                          :aria-label="copied ? 'Copied' : 'Copy code'"
                          @click="copyCodePreview"
                        >
                          <CheckIcon v-if="copied" class="h-4 w-4 text-green-500" />
                          <ClipboardDocumentIcon v-else class="h-4 w-4" />
                        </IconButton>
                      </Tooltip>
                    </div>
                  </div>

                </div>
              </template>

              <template v-else-if="format === 'icon'">
                <div class="border-t border-edge-subtle" />

                <div class="flex items-center justify-between">
                  <label class="text-xs font-semibold text-content-secondary">Platform</label>
                  <div class="flex flex-wrap gap-1 justify-end">
                    <button
                      v-for="opt in ICON_PLATFORMS"
                      :key="opt.value"
                      @click="iconPlatform = opt.value"
                      :class="[
                        'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                        iconPlatform === opt.value
                          ? 'bg-accent text-white'
                          : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
                      ]"
                    >
                      {{ opt.label }}
                    </button>
                  </div>
                </div>

                <p class="text-xs text-content-tertiary">{{ iconPlatformHint }}</p>
              </template>

            </template>

            <!-- Resize section (images) -->
            <template v-if="mediaCategory === 'image'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Resize</label>
                <div class="flex gap-1">
                  <button
                    v-for="opt in resizeOptions"
                    :key="opt.value"
                    @click="resizeMode = opt.value"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      resizeMode === opt.value
                        ? 'bg-accent text-white'
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
                    class="w-24 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
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
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
                  >
                  <span class="text-xs text-content-tertiary mx-1.5">&times;</span>
                  <input
                    v-model.number="exactHeight"
                    type="number"
                    min="1"
                    max="16384"
                    step="1"
                    placeholder="H"
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
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
                    class="w-20 px-2.5 py-1 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-accent"
                  >
                  <span class="text-xs text-content-tertiary ml-2">%</span>
                </template>
              </div>
            </template>

            <!-- Video resolution (video only, when converting) -->
            <template v-if="mediaCategory === 'video' && format !== 'original'">
              <div class="border-t border-edge-subtle" />

              <div class="flex items-center justify-between">
                <label class="text-xs font-semibold text-content-secondary">Resolution</label>
                <div class="flex gap-1">
                  <button
                    v-for="res in videoResolutions"
                    :key="res.value"
                    @click="videoResolution = res.value"
                    :class="[
                      'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                      videoResolution === res.value
                        ? 'bg-accent text-white'
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
                  class="w-3.5 h-3.5 rounded border-surface-raised bg-surface-overlay accent-accent"
                >
                <span class="text-xs text-content-secondary">Strip metadata</span>
              </label>
            </template>

          </div>

    <template #footer>
      <Button variant="secondary" @click="$emit('close')">
        {{ isClipboardExport ? 'Close' : 'Cancel' }}
      </Button>
      <Button v-if="!isClipboardExport" variant="primary" :loading="exporting" @click="handleExport">
        {{ exporting ? 'Exporting...' : exportButtonLabel }}
      </Button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import Modal from './ui/Modal.vue'
import IconButton from './ui/IconButton.vue'
import Button from './ui/Button.vue'
import Tooltip from './ui/Tooltip.vue'
import { CheckIcon, ClipboardDocumentIcon } from '@heroicons/vue/24/outline'
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
const copied = ref(false)

// Layout-specific state
const layoutScaleMode = ref('2x')
const layoutCustomWidth = ref(1600)
const layoutFetchedWidth = ref(0)
const layoutFetchedHeight = ref(0)
const layoutDimsLoading = ref(false)

// Vector-specific state
const codeVariant = ref('inline')
const codePreview = ref('')
const codePreviewLoading = ref(false)
const codePreviewError = ref('')
const iconPlatform = ref('icon-macos')
const pngSetSizes = ref([16, 32, 64, 128, 256, 512, 1024])
let codePreviewRequestId = 0
let copiedTimer = null

const PNG_SET_SIZES = [16, 24, 32, 48, 64, 128, 180, 256, 512, 1024]

const CODE_VARIANTS = [
  { label: 'Inline', value: 'inline' },
  { label: 'Data URI', value: 'data-uri' },
  { label: 'Sprite', value: 'symbol' },
]

const ICON_PLATFORMS = [
  { label: 'macOS', value: 'icon-macos' },
  { label: 'Windows', value: 'icon-windows' },
  { label: 'iOS', value: 'icon-ios' },
  { label: 'Android', value: 'icon-android' },
  { label: 'Web', value: 'icon-web' },
]

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
    else if (fmt === 'stimmasprite.json') categories.add('sprite')
    else if (fmt === 'svg') categories.add('vector')
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
  if (mediaCategory.value === 'vector' && props.mediaItems.length > 0) {
    return props.mediaItems[0].width || 512
  }
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return 800
  const item = props.mediaItems[0]
  return item.width || 800
})

const layoutNativeHeight = computed(() => {
  if (layoutFetchedHeight.value > 0) return layoutFetchedHeight.value
  if (mediaCategory.value === 'vector' && props.mediaItems.length > 0) {
    return props.mediaItems[0].height || 512
  }
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

// Sprite targets mirror backend/sprite_export.py EXPORT_TARGETS, grouped for the dialog.
const SPRITE_FORMAT_GROUPS = [
  { label: 'Engines', formats: [
    { label: 'Phaser / Pixi', value: 'atlas-hash' },
    { label: 'Atlas (array)', value: 'atlas-array' },
    { label: 'Godot', value: 'godot' },
    { label: 'Unity', value: 'unity' },
    { label: 'Unreal', value: 'unreal' },
    { label: 'GameMaker', value: 'gamemaker' },
    { label: 'RPG Maker', value: 'rpgmaker' },
    { label: 'Defold', value: 'defold' },
    { label: 'libGDX', value: 'libgdx' },
    { label: 'Cocos2d', value: 'cocos2d' },
  ] },
  { label: 'Generic', formats: [
    { label: 'Frames', value: 'frames' },
    { label: 'Grid sheet', value: 'grid-sheet' },
    { label: 'Strips', value: 'strips' },
    { label: 'Stills', value: 'stills' },
  ] },
  { label: 'Preview', formats: [
    { label: 'GIF', value: 'gif' },
    { label: 'WebP', value: 'webp' },
    { label: 'APNG', value: 'apng' },
    { label: 'MP4', value: 'mp4' },
  ] },
]

const SPRITE_FORMAT_HINTS = {
  'atlas-hash': 'Sheet PNG + TexturePacker JSON hash. Phaser, PixiJS, Cocos Creator.',
  'atlas-array': 'Sheet PNG + TexturePacker JSON array.',
  godot: 'Sheet PNG + SpriteFrames .tres for Godot 4.',
  unity: 'Sheet PNG + atlas JSON + an Editor script that slices and builds AnimationClips.',
  unreal: 'Sheet PNG + .paper2dsprites for Paper2D flipbooks.',
  gamemaker: 'One horizontal strip per animation, named name_stripN.png.',
  rpgmaker: '$Name.png 3×4 charset. Needs the walk facing south, west, east and north.',
  defold: '.atlas text plus per-frame PNGs with fps and playback mode.',
  libgdx: 'Sheet PNG + libGDX .atlas pack file.',
  cocos2d: 'Sheet PNG + .plist in the TexturePacker cocos2d format.',
  frames: 'Zip of per-frame images with alpha, one folder per animation.',
  'grid-sheet': 'One uniform-cell sheet per animation plus a sidecar JSON.',
  strips: 'One horizontal strip PNG per animation.',
  stills: 'The base cut-out and portrait as PNGs.',
  gif: 'Animated GIF per animation (1-bit transparency).',
  webp: 'Animated lossless WebP per animation.',
  apng: 'Animated PNG per animation, alpha preserved.',
  mp4: 'Preview clip per animation on a background colour. Needs FFmpeg.',
}

const spriteScale = ref(1)
const spriteTrim = ref(false)
const spriteExtrude = ref(1)
const spriteBackground = ref('#202020')
const spriteImageFormat = ref('png')
const spriteError = ref('')

const spriteFormatHint = computed(() => SPRITE_FORMAT_HINTS[format.value] || '')
const spriteUsesBackground = computed(() => (
  format.value === 'mp4' || (format.value === 'frames' && spriteImageFormat.value === 'jpg')
))
const spriteUsesSheetOptions = computed(() => (
  ['atlas-hash', 'atlas-array', 'godot', 'unity', 'unreal', 'libgdx', 'cocos2d', 'defold'].includes(format.value)
))
const spriteUsesGeometry = computed(() => !['stills'].includes(format.value))

const availableFormats = computed(() => {
  if (mediaCategory.value === 'sprite') {
    return SPRITE_FORMAT_GROUPS.flatMap(group => group.formats)
  }

  if (mediaCategory.value === 'vector') {
    return [
      { label: 'SVG', value: 'svg' },
      { label: 'PNG', value: 'png' },
      { label: 'PDF', value: 'pdf' },
      { label: 'Multi-size PNGs', value: 'png-set' },
      { label: 'App icon', value: 'icon' },
      { label: 'SVG code', value: 'html' },
    ]
  }

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

const iconPlatformHint = computed(() => ({
  'icon-macos': 'One .icns file, 32 through 1024px.',
  'icon-windows': 'One .ico file, 16 through 256px.',
  'icon-ios': 'AppIcon.appiconset with Contents.json. Flattened — iOS rejects alpha.',
  'icon-android': 'mipmap densities plus adaptive-icon layers and the Play Store icon.',
  'icon-web': 'favicon.ico, PNGs, site.webmanifest, and the <link> block.',
}[iconPlatform.value]))

// Code goes to the clipboard: downloading a snippet you are about to paste is
// the wrong shape.
const isClipboardExport = computed(() => mediaCategory.value === 'vector' && format.value === 'html')

const isOriginalExport = computed(() => {
  if (mediaCategory.value === 'layout' || mediaCategory.value === 'vector' || mediaCategory.value === 'sprite') return false
  return format.value === 'original'
    && resizeMode.value === 'none'
    && !stripMetadata.value
    && videoResolution.value === 'original'
})

const exportButtonLabel = computed(() => {
  if (isClipboardExport.value) return copied.value ? 'Copied' : 'Copy'
  const count = props.mediaIds.length
  if (count <= 1) return 'Export'
  return `Export ${count}`
})

function togglePngSetSize(size) {
  const next = new Set(pngSetSizes.value)
  if (next.has(size)) next.delete(size)
  else next.add(size)
  pngSetSizes.value = [...next].sort((a, b) => a - b)
}

async function refreshCodePreview() {
  const requestId = ++codePreviewRequestId
  copied.value = false
  codePreviewError.value = ''

  if (!props.show || !isClipboardExport.value) {
    codePreview.value = ''
    codePreviewLoading.value = false
    return
  }

  const mediaId = props.mediaIds[0]
  if (mediaId === undefined || mediaId === null) {
    codePreview.value = ''
    codePreviewLoading.value = false
    codePreviewError.value = 'Code preview unavailable.'
    return
  }

  codePreview.value = ''
  codePreviewLoading.value = true
  try {
    const response = await axios.post(`${getApiBase()}/media/${mediaId}/svg-export`, {
      format: 'html',
      variant: codeVariant.value,
    })
    if (requestId !== codePreviewRequestId) return
    codePreview.value = String(response.data)
  } catch (error) {
    if (requestId !== codePreviewRequestId) return
    console.error('[ExportModal] Failed to generate SVG code preview:', error)
    codePreviewError.value = 'Couldn’t load the code preview.'
  } finally {
    if (requestId === codePreviewRequestId) codePreviewLoading.value = false
  }
}

async function copyCodePreview() {
  if (!codePreview.value) return
  try {
    await navigator.clipboard.writeText(codePreview.value)
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copied.value = false }, 1500)
  } catch (error) {
    console.error('[ExportModal] Failed to copy SVG code:', error)
  }
}

// Reset state when modal opens
watch(() => props.show, (newVal) => {
  if (newVal) {
    layoutFetchedWidth.value = 0
    layoutFetchedHeight.value = 0
    copied.value = false
    if (mediaCategory.value === 'sprite') {
      format.value = 'atlas-hash'
      spriteScale.value = 1
      spriteTrim.value = false
      spriteExtrude.value = 1
      spriteImageFormat.value = 'png'
      spriteError.value = ''
    } else if (mediaCategory.value === 'vector') {
      format.value = 'svg'
      codeVariant.value = 'inline'
      iconPlatform.value = 'icon-macos'
      pngSetSizes.value = [16, 32, 64, 128, 256, 512, 1024]
      layoutScaleMode.value = '1x'
      layoutCustomWidth.value = layoutNativeWidth.value
    } else if (mediaCategory.value === 'layout') {
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

watch(
  [
    () => props.show,
    format,
    codeVariant,
    () => props.mediaIds[0],
  ],
  refreshCodePreview,
)

onBeforeUnmount(() => {
  codePreviewRequestId += 1
  if (copiedTimer) clearTimeout(copiedTimer)
})

// --- Export handler ---

async function handleExport() {
  if (exporting.value) return
  exporting.value = true

  try {
    if (mediaCategory.value === 'sprite') {
      await handleSpriteExport()
    } else if (mediaCategory.value === 'vector') {
      await handleVectorExport()
    } else if (mediaCategory.value === 'layout') {
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
    if (!isClipboardExport.value) emit('close')
  } catch (error) {
    console.error('[ExportModal] Export failed:', error)
  } finally {
    exporting.value = false
  }
}

async function handleVectorExport() {
  const mediaId = props.mediaIds[0]
  const body = { format: format.value === 'icon' ? iconPlatform.value : format.value }

  if (format.value === 'png') {
    if (layoutScaleMode.value === 'custom') body.width = layoutCustomWidth.value
    else body.scale = layoutScaleNumber.value
  } else if (format.value === 'png-set') {
    if (pngSetSizes.value.length === 0) throw new Error('Pick at least one size')
    body.sizes = pngSetSizes.value
  } else if (format.value === 'html') {
    body.variant = codeVariant.value
  }

  if (format.value === 'html') {
    const response = await axios.post(`${getApiBase()}/media/${mediaId}/svg-export`, body)
    await navigator.clipboard.writeText(response.data)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
    return
  }

  const response = await axios.post(
    `${getApiBase()}/media/${mediaId}/svg-export`,
    body,
    { responseType: 'blob' }
  )

  const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
  let filename = 'svg-export'
  if (contentDisposition) {
    const match = contentDisposition.match(/filename="([^"]+)"/)
    if (match) filename = match[1]
  }

  await downloadFromResponse(response.data, filename)
}

async function handleSpriteExport() {
  const mediaId = props.mediaIds[0]
  spriteError.value = ''
  const body = {
    format: format.value,
    scale: spriteScale.value,
    trim: spriteTrim.value,
    extrude: spriteUsesSheetOptions.value ? spriteExtrude.value : 0,
    image_format: spriteImageFormat.value,
  }
  if (spriteUsesBackground.value) body.background = spriteBackground.value

  let response
  try {
    response = await axios.post(
      `${getApiBase()}/media/${mediaId}/sprite-export`,
      body,
      { responseType: 'blob' }
    )
  } catch (error) {
    // The writer explains what the sprite is missing (e.g. RPG Maker directions).
    const blob = error?.response?.data
    let detail = ''
    if (blob && typeof blob.text === 'function') {
      try { detail = JSON.parse(await blob.text())?.detail || '' } catch { /* not JSON */ }
    }
    spriteError.value = detail || 'Export failed.'
    throw error
  }

  const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
  let filename = 'sprite-export'
  if (contentDisposition) {
    const match = contentDisposition.match(/filename="([^"]+)"/)
    if (match) filename = match[1]
  }

  await downloadFromResponse(response.data, filename)
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
