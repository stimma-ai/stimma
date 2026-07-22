<template>
  <!-- Per-image prep for the inpaint source: Flip/Rotate / Crop / Scale /
       Extend Canvas. Same row grammar as MediaPicker's prep, minus Control
       (preprocessing doesn't apply to an inpaint source) and Paint (it would
       fight the mask layer). Prep is baked client-side via the same
       preprocess-reference pipeline; the parent transforms the mask along. -->
  <div v-if="image" class="w-full mt-2">
    <!-- Flip / Rotate row -->
    <div class="w-full border-b border-edge-subtle">
      <div
        class="flex items-center gap-2 px-1 pt-[5px] pb-[4px] leading-none cursor-pointer hover:bg-overlay-subtle transition-colors"
        @click="togglePanel('flip')"
      >
        <span class="text-[11px] text-content-secondary flex-1">Flip / Rotate</span>
        <span :class="['text-[10px] font-mono', hasFlip ? 'text-accent-hi font-medium' : 'text-content-muted']">
          {{ flipStatusText }}
        </span>
        <div class="w-3 h-3 flex-shrink-0">
          <Spinner v-if="processing === 'flip'" size="sm" />
          <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPanel === 'flip' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
        </div>
      </div>
      <div v-if="openPanel === 'flip'" class="px-2.5 py-2 bg-overlay-faint rounded-md">
        <div class="pl-5 flex items-center gap-1.5">
          <button
            @click="toggleFlip('horizontal')"
            :class="['p-1 rounded transition-colors', image._flip?.horizontal ? 'bg-accent/15 text-accent-hi' : 'text-content-muted hover:text-content-secondary hover:bg-overlay-medium']"
            title="Flip horizontally"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v18M8 7l-4 5 4 5M16 7l4 5-4 5"/></svg>
          </button>
          <button
            @click="toggleFlip('vertical')"
            :class="['p-1 rounded transition-colors', image._flip?.vertical ? 'bg-accent/15 text-accent-hi' : 'text-content-muted hover:text-content-secondary hover:bg-overlay-medium']"
            title="Flip vertically"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12h18M7 8 12 4l5 4M7 16l5 4 5-4"/></svg>
          </button>
          <button
            @click="rotate('left')"
            class="p-1 rounded text-content-muted hover:text-content-secondary hover:bg-overlay-medium transition-colors"
            title="Rotate 90° left"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 1 1 9 9 9.75 9.75 0 0 1-6.74-2.74L3 16M3 21v-5h5"/></svg>
          </button>
          <button
            @click="rotate('right')"
            class="p-1 rounded text-content-muted hover:text-content-secondary hover:bg-overlay-medium transition-colors"
            title="Rotate 90° right"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-9-9 9.75 9.75 0 0 1 6.74 2.74L21 8M21 3v5h-5"/></svg>
          </button>
        </div>
        <div v-if="hasFlip" class="mt-1.5 pl-5 flex justify-end">
          <button @click="resetFlip" class="text-[10px] text-content-muted hover:text-accent-hi">Reset</button>
        </div>
      </div>
    </div>

    <!-- Crop row (opens the modal crop editor) -->
    <div class="w-full border-b border-edge-subtle">
      <div class="flex items-center gap-2 px-1 pt-[5px] pb-[4px] leading-none">
        <span class="text-[11px] text-content-secondary flex-1">Crop</span>
        <span v-if="hasCrop" class="text-[10px] font-mono tabular-nums text-accent-hi font-medium">
          {{ cropStatusText }}
        </span>
        <Spinner v-if="processing === 'crop'" size="sm" />
        <button
          v-if="hasCrop"
          @click="applyCrop(null)"
          class="text-[10px] px-1.5 py-0.5 rounded text-content-muted bg-overlay-light hover:bg-red-500/10 hover:text-red-400 transition-colors"
          title="Clear crop"
        >
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"/></svg>
        </button>
        <button
          @click="cropEditorOpen = true"
          :class="[
            'text-[10px] px-2 py-0.5 rounded border transition-colors',
            hasCrop
              ? 'border-accent/50 text-accent-hi bg-accent/10 hover:bg-accent/15'
              : 'border-transparent text-content-muted bg-overlay-light hover:bg-overlay-medium'
          ]"
        >Edit</button>
      </div>
    </div>

    <!-- Scale row -->
    <div class="w-full border-b border-edge-subtle">
      <div
        class="flex items-center gap-2 px-1 pt-[5px] pb-[4px] leading-none cursor-pointer hover:bg-overlay-subtle transition-colors"
        @click="togglePanel('scale')"
      >
        <span class="text-[11px] text-content-secondary flex-1">Scale</span>
        <span :class="['text-[10px] font-mono', hasScale ? 'text-accent-hi font-medium' : 'text-content-muted']">
          {{ scaleStatusText }}
        </span>
        <div class="w-3 h-3 flex-shrink-0">
          <Spinner v-if="processing === 'scale'" size="sm" />
          <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPanel === 'scale' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
        </div>
      </div>
      <div v-if="openPanel === 'scale'" class="px-2.5 py-2 bg-overlay-faint rounded-md space-y-2">
        <div class="flex bg-overlay-faint rounded-md p-0.5 gap-0.5 ml-5">
          <button
            v-for="mode in scaleModes" :key="mode.value"
            @click="onScaleModeChange(mode.value)"
            :class="[
              'flex-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
              (image._scale?.mode || 'factor') === mode.value
                ? 'bg-accent/15 text-accent-hi'
                : 'text-content-muted hover:text-content-secondary'
            ]"
          >{{ mode.label }}</button>
        </div>
        <div v-if="!image._scale?.mode || image._scale.mode === 'factor'" class="pl-5 flex items-center gap-1.5">
          <input type="range" min="10" max="400" :step="5"
            :value="Math.round(((workingScale ?? image._scale)?.factor || 1) * 100)"
            @input="onScaleSliderInput(parseInt(($event.target as HTMLInputElement).value) / 100)"
            @mouseup="commitScale"
            @touchend="commitScale"
            class="flex-1 h-1 accent-accent cursor-pointer" />
          <span class="text-[10px] font-mono text-accent-hi tabular-nums w-10 text-right">{{ ((workingScale ?? image._scale)?.factor || 1).toFixed(2) }}x</span>
        </div>
        <div v-else-if="image._scale?.mode === 'megapixels'" class="pl-5 flex items-center gap-1.5">
          <input type="range" min="1" max="80" :step="1"
            :value="Math.round(((workingScale ?? image._scale)?.megapixels || origMegapixels) * 10)"
            @input="onMegapixelsSliderInput(parseInt(($event.target as HTMLInputElement).value) / 10)"
            @mouseup="commitScale"
            @touchend="commitScale"
            class="flex-1 h-1 accent-accent cursor-pointer" />
          <span class="text-[10px] font-mono text-accent-hi tabular-nums w-10 text-right">{{ ((workingScale ?? image._scale)?.megapixels || origMegapixels).toFixed(1) }} MP</span>
        </div>
        <div v-else-if="image._scale?.mode === 'manual'" class="pl-5 flex items-center gap-1.5">
          <input v-no-autocorrect type="number" min="1" step="1"
            :value="image._scale?.width ?? croppedDims.w"
            @change="onManualDimensionInput('width', parseInt(($event.target as HTMLInputElement).value))"
            class="w-16 px-1.5 py-0.5 text-[10px] bg-base border border-edge-subtle rounded text-content tabular-nums focus:outline-none focus:border-edge" />
          <svg class="w-3 h-3 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m12 0H4.5a1.5 1.5 0 0 0-1.5 1.5v7.5a1.5 1.5 0 0 0 1.5 1.5h15a1.5 1.5 0 0 0 1.5-1.5v-7.5a1.5 1.5 0 0 0-1.5-1.5z"/></svg>
          <input v-no-autocorrect type="number" min="1" step="1"
            :value="image._scale?.height ?? croppedDims.h"
            @change="onManualDimensionInput('height', parseInt(($event.target as HTMLInputElement).value))"
            class="w-16 px-1.5 py-0.5 text-[10px] bg-base border border-edge-subtle rounded text-content tabular-nums focus:outline-none focus:border-edge" />
        </div>
        <div v-if="hasScale" class="pl-5 flex justify-end">
          <button @click="resetScale" class="text-[10px] text-content-muted hover:text-accent-hi">Reset</button>
        </div>
      </div>
    </div>

    <!-- Extend Canvas row. New canvas area enters the mask as MASKED, so
         extend-then-generate is outpainting without touching the brush. -->
    <div class="w-full border-b border-edge-subtle">
      <div
        class="flex items-center gap-2 px-1 pt-[5px] pb-[4px] leading-none cursor-pointer hover:bg-overlay-subtle transition-colors"
        @click="togglePanel('extend')"
      >
        <span class="text-[11px] text-content-secondary flex-1">Extend Canvas</span>
        <span :class="['text-[10px] font-mono', hasExtend ? 'text-accent-hi font-medium' : 'text-content-muted']">
          {{ extendStatusText }}
        </span>
        <div class="w-3 h-3 flex-shrink-0">
          <Spinner v-if="processing === 'extend'" size="sm" />
          <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPanel === 'extend' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
        </div>
      </div>
      <div v-if="openPanel === 'extend'" class="px-2.5 py-2 bg-overlay-faint rounded-md">
        <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 pl-5">
          <div v-for="side in (['top', 'bottom', 'left', 'right'] as const)" :key="side">
            <div class="flex justify-between mb-0.5">
              <span class="text-[10px] text-content-muted capitalize">{{ side }}</span>
              <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ extendValue(side) }}%</span>
            </div>
            <input type="range" min="0" max="100" :step="1"
              :value="extendValue(side)"
              @input="onExtendSliderInput(side, parseInt(($event.target as HTMLInputElement).value))"
              @mouseup="commitExtend"
              @touchend="commitExtend"
              class="w-full h-1 accent-accent cursor-pointer" />
          </div>
        </div>
        <div class="flex items-center gap-1.5 mt-2 pl-5">
          <span class="text-[10px] text-content-muted">Fill</span>
          <input type="color"
            :value="image._extendBgColor || '#000000'"
            @change="onExtendBgColor(($event.target as HTMLInputElement).value)"
            class="w-5 h-4 border border-edge-subtle rounded cursor-pointer" />
          <span class="text-[10px] text-content-muted tabular-nums">{{ image._extendBgColor || '#000000' }}</span>
        </div>
        <div v-if="hasExtend" class="mt-1 pl-5 flex justify-end">
          <button @click="resetExtend" class="text-[10px] text-content-muted hover:text-accent-hi">Reset</button>
        </div>
      </div>
    </div>

    <!-- Crop editor modal (always against the ORIGINAL image) -->
    <CropEditorModal
      v-model="cropEditorOpen"
      :image-url="originalImageUrl"
      :image-width="origWidth"
      :image-height="origHeight"
      :flip="image._flip ?? null"
      :crop="image._crop ?? null"
      @apply="applyCrop"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import axios from 'axios'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { useMediaApi } from '../../composables/useMediaApi'
import { getApiBase } from '../../apiConfig'
import Spinner from '../ui/Spinner.vue'
import CropEditorModal from './CropEditorModal.vue'

const API_BASE = '/api'
const { getMediaFileUrl } = useMediaApi()

export interface InpaintPrepImage {
  path: string
  filename?: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
  _originalPath?: string
  _originalHash?: string
  _originalWidth?: number
  _originalHeight?: number
  _flip?: { horizontal?: boolean; vertical?: boolean; rotation?: number } | null
  _crop?: { x: number; y: number; width: number; height: number; rotation?: number } | null
  _scale?: { mode?: 'factor' | 'megapixels' | 'manual'; factor?: number; megapixels?: number; width?: number; height?: number } | null
  _extendPadding?: { top: number; bottom: number; left: number; right: number } | null
  _extendBgColor?: string | null
}

const props = defineProps<{ image: InpaintPrepImage | null }>()

const emit = defineEmits<{
  (e: 'update:image', value: InpaintPrepImage): void
}>()

const openPanel = ref<string | null>(null)
const processing = ref<string | null>(null)
const cropEditorOpen = ref(false)

// Working (uncommitted) slider values — live preview text without a pipeline
// run per input event; committed on release.
const workingScale = ref<InpaintPrepImage['_scale']>(null)
const workingExtend = ref<InpaintPrepImage['_extendPadding']>(null)

const scaleModes = [
  { value: 'factor' as const, label: 'Factor' },
  { value: 'megapixels' as const, label: 'MP' },
  { value: 'manual' as const, label: 'W×H' },
]

// --- Active-state helpers ---------------------------------------------------

const hasFlip = computed(() => {
  const f = props.image?._flip
  return !!(f && (f.horizontal || f.vertical || ((f.rotation ?? 0) % 360 !== 0)))
})

const hasCrop = computed(() => {
  const c = props.image?._crop
  if (!c) return false
  return !!(c.rotation || c.x > 0 || c.y > 0 || c.width < 1 || c.height < 1)
})

const hasScale = computed(() => {
  const s = props.image?._scale
  if (!s) return false
  if (s.mode === 'megapixels') return true
  if (s.mode === 'manual') return true
  return (s.factor ?? 1) !== 1
})

const hasExtend = computed(() => {
  const p = props.image?._extendPadding
  return !!(p && (p.top > 0 || p.bottom > 0 || p.left > 0 || p.right > 0))
})

// --- Dimension helpers (mirror the backend pipeline's stage order) ----------

const origWidth = computed(() => props.image?._originalWidth ?? props.image?.width ?? 1)
const origHeight = computed(() => props.image?._originalHeight ?? props.image?.height ?? 1)

// Flip/rotate runs first; 90/270 swaps the dims every later stage sees.
const flippedDims = computed(() => {
  const rot = (((props.image?._flip?.rotation ?? 0) % 360) + 360) % 360
  if (rot === 90 || rot === 270) return { w: origHeight.value, h: origWidth.value }
  return { w: origWidth.value, h: origHeight.value }
})

const croppedDims = computed(() => {
  const { w, h } = flippedDims.value
  const c = props.image?._crop
  if (!c || !hasCrop.value) return { w, h }
  return {
    w: Math.max(1, Math.round(w * c.width)),
    h: Math.max(1, Math.round(h * c.height)),
  }
})

const origMegapixels = computed(() => (croppedDims.value.w * croppedDims.value.h) / 1_000_000)

// --- Status texts -----------------------------------------------------------

const flipStatusText = computed(() => {
  const f = props.image?._flip
  if (!hasFlip.value || !f) return 'Original'
  const parts: string[] = []
  if (f.horizontal) parts.push('H')
  if (f.vertical) parts.push('V')
  const rot = (((f.rotation ?? 0) % 360) + 360) % 360
  if (rot) parts.push(`${rot}°`)
  return parts.join(' · ')
})

const cropStatusText = computed(() => {
  const c = props.image?._crop
  if (!c) return ''
  const { w, h } = flippedDims.value
  return `${Math.max(1, Math.round(w * c.width))}×${Math.max(1, Math.round(h * c.height))}`
})

const scaleStatusText = computed(() => {
  const s = props.image?._scale
  if (!hasScale.value || !s) return 'Original'
  const { w, h } = croppedDims.value
  const factor = scaleFactorOf(s, w, h)
  return `${w}×${h} → ${Math.max(1, Math.round(w * factor))}×${Math.max(1, Math.round(h * factor))}`
})

const extendStatusText = computed(() => {
  const p = props.image?._extendPadding
  if (!hasExtend.value || !p) return 'Original'
  const parts: string[] = []
  if (p.top) parts.push(`T${p.top}`)
  if (p.bottom) parts.push(`B${p.bottom}`)
  if (p.left) parts.push(`L${p.left}`)
  if (p.right) parts.push(`R${p.right}`)
  return parts.join(' ') + '%'
})

function scaleFactorOf(s: NonNullable<InpaintPrepImage['_scale']>, w: number, h: number): number {
  if (s.mode === 'megapixels') {
    const target = s.megapixels || 1
    const current = (w * h) / 1_000_000
    return current > 0 ? Math.sqrt(target / current) : 1
  }
  if (s.mode === 'manual') return (s.width || w) / w
  return s.factor || 1
}

// --- Crop editor ------------------------------------------------------------

const originalImageUrl = computed(() => {
  const img = props.image
  if (!img) return null
  const hash = img._originalHash || img.hash
  if (hash) return getMediaFileUrl(hash)
  const path = img._originalPath || img.path
  if (path?.startsWith('/')) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  return path ? getMediaFileUrl(path) : null
})

// --- Mutations --------------------------------------------------------------

function togglePanel(panel: string) {
  openPanel.value = openPanel.value === panel ? null : panel
}

function toggleFlip(axis: 'horizontal' | 'vertical') {
  const current = props.image?._flip || {}
  applyPrep({ _flip: { ...current, [axis]: !current[axis as keyof typeof current] } }, 'flip')
}

function rotate(dir: 'left' | 'right') {
  const current = props.image?._flip || {}
  const delta = dir === 'right' ? 90 : 270
  const rotation = ((((current.rotation ?? 0) + delta) % 360) + 360) % 360
  applyPrep({ _flip: { ...current, rotation } }, 'flip')
}

function resetFlip() {
  applyPrep({ _flip: null }, 'flip')
}

function applyCrop(rect: { x: number; y: number; width: number; height: number; rotation?: number } | null) {
  applyPrep({ _crop: rect }, 'crop')
}

function onScaleModeChange(mode: 'factor' | 'megapixels' | 'manual') {
  const s = props.image?._scale
  if ((s?.mode || 'factor') === mode) return
  applyPrep({ _scale: { mode } }, 'scale')
}

function onScaleSliderInput(factor: number) {
  workingScale.value = { ...(props.image?._scale || {}), mode: 'factor', factor }
}

function onMegapixelsSliderInput(megapixels: number) {
  workingScale.value = { ...(props.image?._scale || {}), mode: 'megapixels', megapixels }
}

function commitScale() {
  if (!workingScale.value) return
  const s = workingScale.value
  workingScale.value = null
  applyPrep({ _scale: s }, 'scale')
}

function onManualDimensionInput(dim: 'width' | 'height', value: number) {
  if (!Number.isFinite(value) || value < 1) return
  const { w, h } = croppedDims.value
  const aspect = w / h
  const next = dim === 'width'
    ? { mode: 'manual' as const, width: Math.round(value), height: Math.max(1, Math.round(value / aspect)) }
    : { mode: 'manual' as const, width: Math.max(1, Math.round(value * aspect)), height: Math.round(value) }
  applyPrep({ _scale: next }, 'scale')
}

function resetScale() {
  applyPrep({ _scale: null }, 'scale')
}

function extendValue(side: 'top' | 'bottom' | 'left' | 'right'): number {
  const p = workingExtend.value ?? props.image?._extendPadding
  return p?.[side] ?? 0
}

function onExtendSliderInput(side: 'top' | 'bottom' | 'left' | 'right', value: number) {
  const base = workingExtend.value ?? props.image?._extendPadding ?? { top: 0, bottom: 0, left: 0, right: 0 }
  workingExtend.value = { ...base, [side]: value }
}

function commitExtend() {
  if (!workingExtend.value) return
  const p = workingExtend.value
  workingExtend.value = null
  applyPrep({ _extendPadding: p }, 'extend')
}

function onExtendBgColor(color: string) {
  applyPrep({ _extendBgColor: color }, 'extend')
}

function resetExtend() {
  applyPrep({ _extendPadding: null }, 'extend')
}

// The prompt-agent path drives the same mutations by name.
defineExpose({ toggleFlip, rotate, resetFlip, applyCrop, resetScale, resetExtend, applyPrep })

// --- Pipeline ---------------------------------------------------------------

/**
 * Merge new prep fields into the image and bake via preprocess-reference
 * (flip → crop → scale → extend; no preprocessor, no paint). Emits the
 * updated image; the parent (MaskEditor) transforms the mask alongside.
 */
async function applyPrep(fields: Partial<InpaintPrepImage>, reason: string) {
  const img = props.image
  if (!img) return

  const merged: InpaintPrepImage = { ...img, ...fields }
  const originalPath = merged._originalPath || merged.path
  const originalHash = merged._originalHash || merged.hash
  const originalWidth = merged._originalWidth ?? merged.width
  const originalHeight = merged._originalHeight ?? merged.height

  const f = merged._flip
  const mergedHasFlip = !!(f && (f.horizontal || f.vertical || ((f.rotation ?? 0) % 360 !== 0)))
  const c = merged._crop
  const mergedHasCrop = !!(c && (c.rotation || c.x > 0 || c.y > 0 || c.width < 1 || c.height < 1))
  const s = merged._scale
  const mergedHasScale = !!(s && (s.mode === 'megapixels' || s.mode === 'manual' || (s.factor ?? 1) !== 1))
  const p = merged._extendPadding
  const mergedHasExtend = !!(p && (p.top > 0 || p.bottom > 0 || p.left > 0 || p.right > 0))

  // All prep cleared — restore the original.
  if (!mergedHasFlip && !mergedHasCrop && !mergedHasScale && !mergedHasExtend) {
    emit('update:image', {
      ...merged,
      path: originalPath,
      hash: originalHash,
      width: originalWidth,
      height: originalHeight,
      _originalPath: undefined,
      _originalHash: undefined,
      _originalWidth: undefined,
      _originalHeight: undefined,
      _flip: null,
      _crop: null,
      _scale: null,
      _extendPadding: null,
    })
    return
  }

  processing.value = reason
  try {
    const body: Record<string, any> = { source_path: originalPath }
    if (mergedHasFlip && f) {
      body.flip = {
        horizontal: !!f.horizontal,
        vertical: !!f.vertical,
        rotation: (((f.rotation ?? 0) % 360) + 360) % 360,
      }
    }
    if (mergedHasCrop) body.crop = merged._crop
    if (mergedHasScale && s) {
      if (s.mode === 'megapixels') {
        body.scale = { mode: 'megapixels', megapixels: s.megapixels || 1 }
      } else if (s.mode === 'manual') {
        // Scale runs on the post-crop image, so the factor is relative to it.
        const rot = (((f?.rotation ?? 0) % 360) + 360) % 360
        const fw = rot === 90 || rot === 270 ? (originalHeight ?? 1) : (originalWidth ?? 1)
        const cw = mergedHasCrop && c ? Math.max(1, Math.round(fw * c.width)) : fw
        body.scale = { mode: 'factor', factor: (s.width || cw) / cw }
      } else {
        body.scale = { mode: 'factor', factor: s.factor || 1 }
      }
    }
    if (mergedHasExtend) {
      body.extend_padding = merged._extendPadding
      if (merged._extendBgColor) body.extend_bg_color = merged._extendBgColor
    }

    const response = await axios.post(`${API_BASE}/generate/preprocess-reference`, body)
    emit('update:image', {
      ...merged,
      path: response.data.path,
      hash: undefined,
      width: response.data.width,
      height: response.data.height,
      _originalPath: originalPath,
      _originalHash: originalHash,
      _originalWidth: originalWidth,
      _originalHeight: originalHeight,
    })
  } catch (err) {
    console.error('Inpaint source preprocessing failed:', err)
  } finally {
    processing.value = null
  }
}
</script>
