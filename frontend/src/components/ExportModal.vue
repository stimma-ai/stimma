<template>
  <Modal :show="show" size="custom" :custom-class="mediaCategory === 'sprite' ? 'max-w-[520px] w-full' : 'max-w-[440px] w-full'" @close="$emit('close')">
    <template #header>
      <div class="flex items-center gap-3">
        <div v-if="thumbnailIds.length > 1" class="relative h-11 w-[52px] shrink-0" aria-hidden="true">
          <img
            v-for="(id, index) in thumbnailIds"
            :key="id"
            :src="getThumbnailUrl(Number(id))"
            alt=""
            class="absolute h-9 w-9 rounded-md border-2 border-surface bg-overlay-faint object-cover"
            :style="{ left: `${index * 7}px`, top: `${(thumbnailIds.length - 1 - index) * 3}px`, transform: `rotate(${(index - 1) * 4}deg)` }"
            @error="($event.target).style.display = 'none'"
          >
        </div>
        <img
          v-else-if="thumbnailIds.length === 1"
          :src="getThumbnailUrl(Number(thumbnailIds[0]))"
          alt=""
          class="h-11 w-11 shrink-0 rounded-md bg-overlay-faint object-cover"
          @error="($event.target).style.display = 'none'"
        >
        <div class="min-w-0 flex-1">
          <h3 class="text-base font-semibold text-content">{{ dialogTitle }}</h3>
          <p v-if="dialogSubtitle" class="truncate text-xs text-content-tertiary">{{ dialogSubtitle }}</p>
        </div>
        <IconButton class="self-start" aria-label="Close" @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <div v-if="hasOptions" class="px-6 py-5 space-y-4">

      <!-- Sprite targets: grouped Engines / Generic / Preview, same radio grammar. -->
      <template v-if="mediaCategory === 'sprite'">
        <div :class="ROW">
          <span :class="LABEL">Format</span>
          <div class="min-w-0">
            <div v-for="group in SPRITE_FORMAT_GROUPS" :key="group.label" class="mb-2.5 last:mb-0">
              <p class="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-content-tertiary">{{ group.label }}</p>
              <div class="grid grid-cols-3 gap-1.5" role="radiogroup" :aria-label="`${group.label} export format`">
                <label v-for="fmt in group.formats" :key="fmt.value" class="cursor-pointer">
                  <input v-model="format" type="radio" name="export-format" :value="fmt.value" class="peer sr-only">
                  <span :class="[TILE, format === fmt.value ? TILE_ON : TILE_OFF]">{{ fmt.label }}</span>
                </label>
              </div>
            </div>
            <p v-if="spriteFormatHint" class="mt-2 text-xs text-content-tertiary">{{ spriteFormatHint }}</p>
          </div>
        </div>

        <div v-if="spriteUsesGeometry" :class="ROW">
          <span :class="LABEL">Scale</span>
          <SegmentedControl v-model="spriteScale" :options="SPRITE_SCALES" aria-label="Scale" />
        </div>

        <div v-if="spriteUsesSheetOptions" :class="ROW">
          <span :class="LABEL">Edge bleed</span>
          <div class="flex items-center gap-1.5">
            <input v-model.number="spriteExtrude" type="number" min="0" max="8" step="1" aria-label="Edge bleed" :class="[NUMBER, 'w-16']">
            <span class="text-xs text-content-tertiary">px</span>
          </div>
        </div>

        <div v-if="spriteUsesGeometry" :class="ROW">
          <span :class="LABEL">Trim</span>
          <label :class="SWITCH_ROW">
            <span class="relative inline-flex shrink-0 items-center">
              <input v-model="spriteTrim" type="checkbox" role="switch" class="peer sr-only">
              <span :class="SWITCH" />
            </span>
            Trim to content
          </label>
        </div>

        <div v-if="format === 'frames'" :class="ROW">
          <span :class="LABEL">Image format</span>
          <SegmentedControl v-model="spriteImageFormat" :options="SPRITE_IMAGE_FORMATS" aria-label="Image format" />
        </div>

        <div v-if="spriteUsesBackground" :class="ROW">
          <span :class="LABEL">Background</span>
          <input v-model="spriteBackground" type="color" aria-label="Background" class="h-7 w-10 bg-transparent border border-edge rounded cursor-pointer">
        </div>

        <p v-if="spriteError" class="text-xs text-red-400">{{ spriteError }}</p>
      </template>

      <!-- Package targets: one row each, since every choice carries a qualifier. -->
      <div v-else-if="mediaCategory === 'package'" :class="ROW">
        <span :class="LABEL">Format</span>
        <div class="space-y-1.5" role="radiogroup" aria-label="Package export format">
          <label v-for="fmt in PACKAGE_EXPORT_FORMATS" :key="fmt.value" class="block cursor-pointer">
            <input v-model="format" type="radio" name="export-format" :value="fmt.value" class="peer sr-only">
            <span :class="[TILE, '!justify-start gap-1', format === fmt.value ? TILE_ON : TILE_OFF]">
              <span class="font-medium">{{ fmt.label }}</span>
              <span class="font-normal text-content-tertiary">— {{ fmt.hint }}</span>
            </span>
          </label>
        </div>
      </div>

      <div v-else-if="availableFormats.length > 1" :class="ROW">
        <span :class="LABEL">Format</span>
        <div :class="['grid gap-1.5', availableFormats.length === 4 ? 'grid-cols-4' : 'grid-cols-3']" role="radiogroup" aria-label="Export format">
          <label v-for="fmt in availableFormats" :key="fmt.value" class="cursor-pointer">
            <input v-model="format" type="radio" name="export-format" :value="fmt.value" class="peer sr-only">
            <span :class="[TILE, format === fmt.value ? TILE_ON : TILE_OFF]">{{ fmt.label }}</span>
          </label>
        </div>
      </div>

      <div v-if="showQuality" :class="ROW">
        <span :class="LABEL">Quality</span>
        <div class="flex items-center gap-3 pt-1">
          <input
            v-model.number="quality"
            type="range"
            min="1"
            max="100"
            step="1"
            aria-label="Quality"
            class="flex-1 h-1 bg-surface-raised rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
          >
          <span class="text-xs text-content-secondary tabular-nums w-6 text-right">{{ quality }}</span>
        </div>
      </div>

      <!-- Layout and vector PNG size -->
      <div v-if="(mediaCategory === 'layout' || mediaCategory === 'vector') && format === 'png'" :class="ROW">
        <span :class="LABEL">Size</span>
        <div>
          <SegmentedControl v-model="layoutScaleMode" :options="layoutScaleOptions" aria-label="Size" />
          <div class="mt-2 flex h-7 items-center text-xs">
            <template v-if="layoutScaleMode === 'custom'">
              <input v-model.number="layoutCustomWidth" type="number" :min="mediaCategory === 'vector' ? 16 : 100" :max="mediaCategory === 'vector' ? 4096 : 16384" step="1" aria-label="Width" :class="[NUMBER, 'w-24']">
              <span class="mx-1.5 text-content-tertiary">&times;</span>
              <span class="text-content-secondary tabular-nums">{{ layoutDerivedHeight }}</span>
              <span class="ml-1.5 text-content-tertiary">px</span>
            </template>
            <template v-else>
              <span class="text-content-secondary tabular-nums">{{ layoutOutputWidth }} &times; {{ layoutOutputHeight }}</span>
              <span class="ml-1.5 text-content-tertiary">px</span>
            </template>
          </div>
        </div>
      </div>

      <div v-if="mediaCategory === 'vector' && format === 'png-set'" :class="ROW">
        <span :class="LABEL">Sizes</span>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="size in PNG_SET_SIZES"
            :key="size"
            type="button"
            :aria-pressed="pngSetSizes.includes(size)"
            :class="[
              'rounded px-2 py-1 text-xs font-medium tabular-nums transition-colors',
              pngSetSizes.includes(size) ? 'bg-accent/15 text-accent' : 'bg-overlay-faint text-content-secondary hover:bg-overlay-subtle hover:text-content'
            ]"
            @click="togglePngSetSize(size)"
          >
            {{ size }}
          </button>
        </div>
      </div>

      <template v-if="mediaCategory === 'vector' && format === 'html'">
        <div :class="ROW">
          <span :class="LABEL">Form</span>
          <SegmentedControl v-model="codeVariant" :options="CODE_VARIANTS" aria-label="Code form" />
        </div>
        <div class="relative h-32 overflow-hidden rounded-md bg-overlay-faint">
          <pre
            v-if="codePreview"
            class="h-full overflow-auto whitespace-pre p-3 pr-11 font-mono text-[11px] leading-relaxed text-content-secondary custom-scrollbar select-text"
          >{{ codePreview }}</pre>
          <div v-else class="flex h-full items-center justify-center px-4 text-center text-xs text-content-muted">
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
      </template>

      <div v-if="mediaCategory === 'image'" :class="ROW">
        <span :class="LABEL">Size</span>
        <div>
          <SegmentedControl v-model="resizeMode" :options="resizeOptions" aria-label="Size" />
          <div v-if="resizeMode !== 'none'" class="mt-2 flex h-7 items-center gap-1.5 text-xs text-content-tertiary">
            <template v-if="resizeMode === 'max_dimension'">
              <input v-model.number="maxDimension" type="number" min="64" max="16384" step="64" aria-label="Longest side" :class="[NUMBER, 'w-24']">
              <span>px longest side</span>
            </template>
            <template v-else-if="resizeMode === 'exact'">
              <input v-model.number="exactWidth" type="number" min="1" max="16384" step="1" placeholder="W" aria-label="Width" :class="[NUMBER, 'w-20']">
              <span>&times;</span>
              <input v-model.number="exactHeight" type="number" min="1" max="16384" step="1" placeholder="H" aria-label="Height" :class="[NUMBER, 'w-20']">
              <span>px</span>
            </template>
            <template v-else-if="resizeMode === 'scale'">
              <input v-model.number="scalePercent" type="number" min="1" max="1000" step="1" aria-label="Scale" :class="[NUMBER, 'w-20']">
              <span>%</span>
            </template>
            <span v-if="imageOutputSize && resizeMode !== 'exact'" class="ml-auto tabular-nums text-content-secondary">
              {{ imageOutputSize }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="mediaCategory === 'video' && format !== 'original'" :class="ROW">
        <span :class="LABEL">Resolution</span>
        <SegmentedControl v-model="videoResolution" :options="videoResolutions" aria-label="Resolution" />
      </div>

      <div v-if="mediaCategory === 'image'" :class="ROW">
        <span :class="LABEL">Metadata</span>
        <label :class="SWITCH_ROW">
          <span class="relative inline-flex shrink-0 items-center">
            <input v-model="includeMetadata" type="checkbox" role="switch" class="peer sr-only">
            <span :class="SWITCH" />
          </span>
          Include metadata
        </label>
      </div>

      <div v-if="showBundleChoice" :class="ROW">
        <span :class="LABEL">Save as</span>
        <SegmentedControl v-model="bundleAs" :options="BUNDLE_CHOICES" aria-label="Save as" />
      </div>

      <div v-if="showCombineChoice" :class="ROW">
        <span :class="LABEL">Files</span>
        <label :class="SWITCH_ROW">
          <span class="relative inline-flex shrink-0 items-center">
            <input v-model="combineZip" type="checkbox" role="switch" class="peer sr-only">
            <span :class="SWITCH" />
          </span>
          Combine into one zip
        </label>
      </div>
    </div>

    <p v-if="exportError" role="alert" class="px-6 pb-4 text-sm text-red-500" :class="hasOptions ? '' : 'pt-5'">{{ exportError }}</p>

    <template #footer>
      <Button
        v-if="canChooseLocation && !isClipboardExport"
        variant="ghost"
        class="mr-auto"
        :disabled="exporting"
        :loading="exportingTo === 'downloads'"
        @click="handleExport('downloads')"
      >
        Save to Downloads
      </Button>
      <Button variant="secondary" @click="$emit('close')">
        {{ isClipboardExport ? 'Close' : 'Cancel' }}
      </Button>
      <Button
        v-if="!isClipboardExport"
        variant="primary"
        :disabled="exporting"
        :loading="exportingTo === 'choose'"
        @click="handleExport('choose')"
      >
        {{ primaryLabel }}
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
import SegmentedControl from './ui/SegmentedControl.vue'
import { CheckIcon, ClipboardDocumentIcon } from '@heroicons/vue/24/outline'
import { useMediaApi } from '../composables/useMediaApi'
import {
  canChooseExportLocation,
  exportToChosenFile,
  exportToChosenFolder,
  exportToDownloads,
  isZipExport,
} from '../composables/useExportDestination'
import { desktop } from '../desktop'
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
  // Media items for type detection and the header. Each needs at least
  // { id, file_format }; width/height/file_path/title/duration fill the header.
  mediaItems: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'exported'])

const { getThumbnailUrl } = useMediaApi()

// --- Shared classes -----------------------------------------------------------

const ROW = 'grid grid-cols-[84px_minmax(0,1fr)] items-start gap-3'
const LABEL = 'pt-1.5 text-xs font-semibold text-content-secondary'
const TILE = 'flex min-h-8 items-center justify-center rounded-md px-3 py-1.5 text-center text-xs font-medium transition-colors duration-150 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60'
const TILE_ON = 'bg-accent/15 text-accent'
const TILE_OFF = 'bg-overlay-faint text-content-secondary hover:bg-overlay-subtle hover:text-content'
const NUMBER = 'px-2.5 py-1 bg-surface-overlay border border-edge rounded text-content-secondary text-xs tabular-nums focus:outline-none focus:border-accent'
const SWITCH_ROW = 'flex cursor-pointer select-none items-center gap-2 pt-1 text-xs text-content-secondary'
const SWITCH = "h-4 w-7 rounded-full bg-surface-hover after:absolute after:left-[2px] after:top-[2px] after:h-3 after:w-3 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60"

// --- State --------------------------------------------------------------------

const format = ref('original')
const quality = ref(85)
const resizeMode = ref('none')
const maxDimension = ref(2048)
const exactWidth = ref(1920)
const exactHeight = ref(1080)
const scalePercent = ref(50)
const includeMetadata = ref(true)
const videoResolution = ref('original')
const exportingTo = ref(null)
const exporting = computed(() => exportingTo.value !== null)
const exportError = ref('')
const copied = ref(false)

// Destination choices persist across exports.
const COMBINE_KEY = 'stimma:export-combine-zip'
const BUNDLE_KEY = 'stimma:export-bundle-as'
const combineZip = ref(localStorage.getItem(COMBINE_KEY) === 'true')
const bundleAs = ref(localStorage.getItem(BUNDLE_KEY) === 'zip' ? 'zip' : 'folder')
watch(combineZip, value => localStorage.setItem(COMBINE_KEY, String(value)))
watch(bundleAs, value => localStorage.setItem(BUNDLE_KEY, value))

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
const pngSetSizes = ref([16, 32, 64, 128, 256, 512, 1024])
let codePreviewRequestId = 0
let copiedTimer = null

const PNG_SET_SIZES = [16, 24, 32, 48, 64, 128, 180, 256, 512, 1024]

const CODE_VARIANTS = [
  { label: 'Inline', value: 'inline' },
  { label: 'Data URI', value: 'data-uri' },
  { label: 'Sprite', value: 'symbol' },
]

const PACKAGE_EXPORT_FORMATS = [
  { value: 'zip', label: 'Zip', hint: 'full package' },
  { value: 'pdf', label: 'PDF', hint: 'presentation, not production files' },
  { value: 'html', label: 'Single HTML file', hint: 'cover with previews, read-only' },
]

const BUNDLE_CHOICES = [
  { label: 'Folder', value: 'folder' },
  { label: 'Zip', value: 'zip' },
]

// --- Media ----------------------------------------------------------------------

const IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif']
const VIDEO_FORMATS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']
const AUDIO_FORMATS = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']

function categoryOf(item) {
  const fmt = (item.file_format || '').toLowerCase()
  if (fmt === 'stimmalayout') return 'layout'
  if (fmt === 'stimmasprite.json') return 'sprite'
  if (fmt === 'stimmapackage') return 'package'
  if (fmt === 'svg') return 'vector'
  if (IMAGE_FORMATS.includes(fmt)) return 'image'
  if (VIDEO_FORMATS.includes(fmt)) return 'video'
  if (AUDIO_FORMATS.includes(fmt)) return 'audio'
  return 'other'
}

const mediaCategory = computed(() => {
  if (props.mediaItems.length === 0) return 'mixed'
  const categories = new Set(props.mediaItems.map(categoryOf))
  if (categories.size === 1) return [...categories][0]
  return 'mixed'
})

const itemCount = computed(() => props.mediaIds.length)
const isMulti = computed(() => itemCount.value > 1)
const firstItem = computed(() => props.mediaItems[0] || null)
const canChooseLocation = canChooseExportLocation()

function itemName(item) {
  if (!item) return ''
  if (item.title) return item.title
  const path = item.file_path || ''
  return path.split(/[\\/]/).filter(Boolean).pop() || ''
}

function formatDuration(seconds) {
  const total = Math.round(seconds)
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

const thumbnailIds = computed(() => props.mediaIds.slice(0, 3))

const dialogTitle = computed(() => {
  if (!isMulti.value) return 'Export'
  const noun = {
    image: 'images',
    video: 'videos',
    audio: 'audio files',
  }[mediaCategory.value] || 'items'
  return `Export ${itemCount.value} ${noun}`
})

const dialogSubtitle = computed(() => {
  if (isMulti.value) {
    const names = props.mediaItems.slice(0, 2).map(itemName).filter(Boolean)
    const rest = itemCount.value - names.length
    if (names.length === 0) return ''
    return rest > 0 ? `${names.join(', ')}, and ${rest} more` : names.join(', ')
  }
  const item = firstItem.value
  if (!item) return ''
  const parts = [itemName(item)]
  const category = mediaCategory.value
  if (item.width && item.height && category !== 'audio' && category !== 'package') {
    parts.push(`${item.width} × ${item.height}`)
  }
  if ((category === 'video' || category === 'audio') && item.duration) {
    parts.push(formatDuration(item.duration))
  }
  return parts.filter(Boolean).join(' · ')
})

// Layout dimensions — prefer fetched from HTML, fall back to DB, then defaults
const layoutNativeWidth = computed(() => {
  if (layoutFetchedWidth.value > 0) return layoutFetchedWidth.value
  if (mediaCategory.value === 'vector' && props.mediaItems.length > 0) {
    return props.mediaItems[0].width || 512
  }
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return 800
  return props.mediaItems[0].width || 800
})

const layoutNativeHeight = computed(() => {
  if (layoutFetchedHeight.value > 0) return layoutFetchedHeight.value
  if (mediaCategory.value === 'vector' && props.mediaItems.length > 0) {
    return props.mediaItems[0].height || 512
  }
  if (mediaCategory.value !== 'layout' || props.mediaItems.length === 0) return 600
  return props.mediaItems[0].height || 600
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
  { label: '1×', value: '1x' },
  { label: '2×', value: '2x' },
  { label: '3×', value: '3x' },
  { label: 'Custom', value: 'custom' },
]

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

// backend/sprite_export.py _SINGLE_FILE_OK: these can come back as one file;
// the rest always come back as several files in an archive.
const SPRITE_SINGLE_FILE_TARGETS = ['rpgmaker', 'gif', 'webp', 'apng', 'mp4', 'gamemaker', 'strips', 'stills']

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
  frames: 'Per-frame images with alpha, one folder per animation.',
  'grid-sheet': 'One uniform-cell sheet per animation plus a sidecar JSON.',
  strips: 'One horizontal strip PNG per animation.',
  stills: 'The base cut-out and portrait as PNGs.',
  gif: 'Animated GIF per animation (1-bit transparency).',
  webp: 'Animated lossless WebP per animation.',
  apng: 'Animated PNG per animation, alpha preserved.',
  mp4: 'Preview clip per animation on a background colour. Needs FFmpeg.',
}

const SPRITE_SCALES = [1, 2, 3, 4].map(n => ({ label: `${n}×`, value: n }))
const SPRITE_IMAGE_FORMATS = ['png', 'webp', 'jpg'].map(value => ({ label: value.toUpperCase(), value }))

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
  if (mediaCategory.value === 'vector') {
    return [
      { label: 'SVG', value: 'svg' },
      { label: 'PNG', value: 'png' },
      { label: 'PDF', value: 'pdf' },
      { label: 'PNG sizes', value: 'png-set' },
      { label: 'Code', value: 'html' },
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
  // Mixed and other files export as they are.
  return [original]
})

const showQuality = computed(() => {
  if (format.value === 'original') return false
  if (!['image', 'video', 'audio'].includes(mediaCategory.value)) return false
  return ['jpeg', 'webp', 'mp4', 'webm', 'mp3'].includes(format.value)
})

const resizeOptions = [
  { label: 'Original', value: 'none' },
  { label: 'Longest side', value: 'max_dimension' },
  { label: 'Exact', value: 'exact' },
  { label: 'Scale', value: 'scale' },
]

// Mirrors the backend's resize (Pillow thumbnail only ever shrinks).
const imageOutputSize = computed(() => {
  const item = firstItem.value
  if (isMulti.value || !item?.width || !item?.height) return ''
  const { width, height } = item
  let w = width
  let h = height
  if (resizeMode.value === 'max_dimension' && maxDimension.value > 0) {
    const factor = Math.min(1, maxDimension.value / Math.max(width, height))
    w = Math.max(1, Math.round(width * factor))
    h = Math.max(1, Math.round(height * factor))
  } else if (resizeMode.value === 'scale' && scalePercent.value > 0) {
    w = Math.max(1, Math.floor(width * scalePercent.value / 100))
    h = Math.max(1, Math.floor(height * scalePercent.value / 100))
  } else if (resizeMode.value === 'exact') {
    return ''
  }
  return `${w} × ${h} px`
})

const videoResolutions = [
  { label: 'Original', value: 'original' },
  { label: '4K', value: '2160' },
  { label: '1080p', value: '1080' },
  { label: '720p', value: '720' },
]

// Code goes to the clipboard: downloading a snippet you are about to paste is
// the wrong shape.
const isClipboardExport = computed(() => mediaCategory.value === 'vector' && format.value === 'html')

const isOriginalExport = computed(() => {
  if (!['image', 'video', 'audio', 'mixed', 'other'].includes(mediaCategory.value)) return false
  return format.value === 'original'
    && resizeMode.value === 'none'
    && includeMetadata.value
    && videoResolution.value === 'original'
})

// Formats that come back as several files. Several items always do.
const producesBundle = computed(() => {
  if (mediaCategory.value === 'sprite') return !SPRITE_SINGLE_FILE_TARGETS.includes(format.value)
  if (mediaCategory.value === 'vector') return format.value === 'png-set'
  return false
})

const showBundleChoice = computed(() => canChooseLocation && !isMulti.value && producesBundle.value)
const showCombineChoice = computed(() => canChooseLocation && isMulti.value)

const hasOptions = computed(() => (
  !['mixed', 'other'].includes(mediaCategory.value) || showCombineChoice.value
))

const primaryLabel = computed(() => {
  if (exportingTo.value === 'choose') return 'Exporting…'
  const count = itemCount.value
  if (canChooseLocation) return count > 1 ? `Export ${count}…` : 'Export…'
  if (desktop.kind === 'ios' || desktop.kind === 'android') return 'Share…'
  return count > 1 ? `Download ${count}` : 'Download'
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
    exportError.value = ''
    if (mediaCategory.value === 'sprite') {
      format.value = 'atlas-hash'
      spriteScale.value = 1
      spriteTrim.value = false
      spriteExtrude.value = 1
      spriteImageFormat.value = 'png'
      spriteError.value = ''
    } else if (mediaCategory.value === 'package') {
      format.value = 'zip'
    } else if (mediaCategory.value === 'vector') {
      format.value = 'svg'
      codeVariant.value = 'inline'
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
    includeMetadata.value = true
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

// --- Export -------------------------------------------------------------------

function filenameFrom(response, fallback) {
  const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
  if (contentDisposition) {
    const match = contentDisposition.match(/filename="([^"]+)"/)
    if (match) return match[1]
  }
  return fallback
}

// Blob error bodies hide the backend's explanation until read back as text.
async function errorDetail(error) {
  const blob = error?.response?.data
  if (blob && typeof blob.text === 'function') {
    try { return JSON.parse(await blob.text())?.detail || '' } catch { /* not JSON */ }
  }
  return ''
}

async function postForFile(url, body, fallbackName) {
  const response = await axios.post(url, body, { responseType: 'blob' })
  return { blob: response.data, filename: filenameFrom(response, fallbackName) }
}

/**
 * Build the export on the backend. Resolves { blob, filename }, or null when
 * the export went to the clipboard instead.
 */
async function produceExport() {
  const ids = props.mediaIds.map(id => parseInt(id))
  const category = mediaCategory.value

  if (category === 'sprite') return produceSpriteExport()
  if (category === 'package') return producePackageExport()
  if (category === 'vector') return produceVectorExport()
  if (category === 'layout') return produceLayoutExport()

  if (isOriginalExport.value) {
    return postForFile(`${getApiBase()}/media/download`, { media_ids: ids }, 'download')
  }

  const options = {}
  if (format.value !== 'original') options.format = format.value
  if (showQuality.value) options.quality = quality.value
  if (category === 'image' && resizeMode.value !== 'none') {
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
  if (category === 'video' && videoResolution.value !== 'original') {
    options.video_resolution = videoResolution.value
  }
  if (!includeMetadata.value) options.strip_metadata = true

  return postForFile(`${getApiBase()}/media/export`, { media_ids: ids, options }, 'export')
}

async function producePackageExport() {
  try {
    return await postForFile(
      `${getApiBase()}/media/${props.mediaIds[0]}/package-export`,
      { format: format.value },
      `package.${format.value}`,
    )
  } catch (error) {
    throw new Error((await errorDetail(error)) || 'Export failed. Please try again.')
  }
}

async function produceVectorExport() {
  const mediaId = props.mediaIds[0]
  const body = { format: format.value }

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
    return null
  }

  return postForFile(`${getApiBase()}/media/${mediaId}/svg-export`, body, 'svg-export')
}

async function produceSpriteExport() {
  spriteError.value = ''
  const body = {
    format: format.value,
    scale: spriteScale.value,
    trim: spriteTrim.value,
    extrude: spriteUsesSheetOptions.value ? spriteExtrude.value : 0,
    image_format: spriteImageFormat.value,
  }
  if (spriteUsesBackground.value) body.background = spriteBackground.value

  try {
    return await postForFile(`${getApiBase()}/media/${props.mediaIds[0]}/sprite-export`, body, 'sprite-export')
  } catch (error) {
    // The writer explains what the sprite is missing (e.g. RPG Maker directions).
    spriteError.value = (await errorDetail(error)) || 'Export failed.'
    throw error
  }
}

async function produceLayoutExport() {
  const body = { format: format.value }
  if (format.value === 'png') {
    if (layoutScaleMode.value === 'custom') body.width = layoutCustomWidth.value
    else body.scale = layoutScaleNumber.value
  }
  return postForFile(`${getApiBase()}/media/${props.mediaIds[0]}/layout-export`, body, 'layout-export')
}

/**
 * Write a finished export where the user wants it. Resolves false when they
 * cancelled a picker, which keeps the dialog open.
 */
async function deliver(file, destination) {
  if (destination === 'downloads' || !canChooseLocation) {
    await exportToDownloads(file)
    return true
  }
  const category = mediaCategory.value
  if (isZipExport(file) && category !== 'package') {
    if (isMulti.value) {
      return combineZip.value
        ? exportToChosenFile(file, category)
        : exportToChosenFolder(file, category, { ownFolder: false })
    }
    return bundleAs.value === 'zip'
      ? exportToChosenFile(file, category)
      : exportToChosenFolder(file, category, { ownFolder: true })
  }
  return exportToChosenFile(file, category)
}

async function handleExport(destination) {
  if (exporting.value) return
  exportError.value = ''
  exportingTo.value = destination

  try {
    const file = await produceExport()
    if (!file) {
      emit('exported')
      return
    }
    if (!(await deliver(file, destination))) return
    emit('exported')
    emit('close')
  } catch (error) {
    console.error('[ExportModal] Export failed:', error)
    exportError.value = error instanceof Error ? error.message : 'Export failed. Please try again.'
  } finally {
    exportingTo.value = null
  }
}
</script>
