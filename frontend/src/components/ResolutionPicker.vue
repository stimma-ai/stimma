<template>
  <div ref="containerRef" class="relative inline-block max-w-full">
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      :class="[
        'flex items-center gap-2 font-medium transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap',
        compact
          ? 'px-2.5 h-7 rounded-md text-xs text-content-tertiary hover:text-content hover:bg-overlay-subtle'
          : 'px-3 h-10 rounded-md border border-edge-subtle bg-overlay-subtle text-sm text-content-tertiary hover:bg-overlay-light hover:text-content'
      ]"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
    >
      <span class="border border-edge bg-surface-raised flex-shrink-0 rounded-media" :style="previewStyle(resolved.width, resolved.height, 12)"></span>
      <template v-if="resolved.shapeFromImage && resolved.sizeFromImage">
        <span :class="tagClass">from image</span>
        <span>{{ resolved.width }}×{{ resolved.height }}</span>
      </template>
      <template v-else-if="resolved.shapeFromImage">
        <span :class="tagClass">image shape</span>
        <span>{{ sizeLabel }} · {{ resolved.width }}×{{ resolved.height }}</span>
      </template>
      <template v-else-if="resolved.sizeFromImage">
        <span>{{ resolved.ratioLabel }}</span>
        <span :class="tagClass">image size</span>
        <span>{{ resolved.width }}×{{ resolved.height }}</span>
      </template>
      <template v-else>
        <span>{{ resolved.ratioLabel }} · {{ sizeLabel }}</span>
        <span class="font-mono tabular-nums text-[11px] text-content-muted">{{ resolved.width }}×{{ resolved.height }}</span>
      </template>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" :class="compact ? 'w-3 h-3 text-content-muted' : 'w-4 h-4 text-content-muted'">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <Teleport to="body">
      <div v-if="isOpen" class="fixed inset-0 z-menu" @click="close" />
      <div
        v-if="isOpen"
        ref="panelRef"
        class="fixed z-menu w-[22rem] max-w-[calc(100vw-1rem)] rounded-lg border border-edge-subtle bg-surface p-3 shadow-lg"
        :style="panelStyle"
        role="dialog"
        @click.stop
      >
        <!-- Shape -->
        <div class="text-[11px] font-semibold text-content-muted mb-1.5">Shape</div>
        <div class="grid grid-cols-6 gap-1">
          <button
            v-if="hasImageInput"
            type="button"
            :class="tileClass(followShapeState)"
            @click="toggleFollowShape"
          >
            <span class="w-5 h-5 grid place-items-center"><ImageGlyph /></span>
            <span class="text-[10px] leading-none">From image</span>
          </button>
          <button
            v-for="r in ratioChoices"
            :key="r"
            type="button"
            :class="tileClass(ratioTileState(r))"
            @click="pickRatio(r)"
          >
            <span class="w-5 h-5 grid place-items-center"><i class="block border-[1.5px] border-current rounded-media" :style="previewStyle(ratioValue(r), 1, 18)"></i></span>
            <span class="text-[10px] leading-none">{{ r }}</span>
          </button>
          <div
            v-if="customRatioLabel"
            :class="tileClass('on')"
            class="cursor-default"
          >
            <span class="w-5 h-5 grid place-items-center"><i class="block border-[1.5px] border-current rounded-media" :style="previewStyle(resolved.width, resolved.height, 18)"></i></span>
            <span class="text-[10px] leading-none">{{ customRatioLabel }}</span>
          </div>
        </div>

        <!-- Size -->
        <div class="text-[11px] font-semibold text-content-muted mt-3 mb-1.5">Size</div>
        <div :class="['grid gap-1 items-center', hasImageInput ? 'grid-cols-6' : 'grid-cols-1']">
          <button
            v-if="hasImageInput"
            type="button"
            :class="tileClass(followSizeState)"
            @click="toggleFollowSize"
          >
            <span class="w-5 h-5 grid place-items-center"><ImageGlyph /></span>
            <span class="text-[10px] leading-none">From image</span>
          </button>
          <div :class="hasImageInput ? 'col-span-5 pl-1' : ''">
            <template v-if="tiers">
              <div class="flex bg-overlay-subtle rounded-md p-0.5 gap-0.5">
                <button
                  v-for="opt in sizeOptions"
                  :key="opt.label"
                  type="button"
                  :class="[
                    'flex-1 px-2 py-1.5 rounded-md text-xs font-medium transition-colors duration-150',
                    tierState(opt.tier) === 'on' ? 'bg-accent/15 text-accent'
                      : tierState(opt.tier) === 'echo' ? 'text-accent/60'
                      : 'text-content-muted hover:text-content-secondary'
                  ]"
                  @click="pickTier(opt.tier)"
                >{{ opt.label }}</button>
              </div>
            </template>
            <template v-else>
              <div class="flex items-center gap-3">
                <input v-no-autocorrect
                  type="range"
                  :min="MP_MIN_LOG"
                  :max="MP_MAX_LOG"
                  step="0.02"
                  :value="Math.log2(resolved.mp)"
                  :disabled="resolved.sizeFromImage"
                  class="flex-1 h-1 bg-overlay-subtle rounded-full appearance-none cursor-pointer disabled:cursor-default disabled:opacity-50 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-accent [&::-moz-range-thumb]:border-0"
                  @input="onSlider(($event.target as HTMLInputElement).value)"
                >
                <span :class="['font-mono tabular-nums text-xs font-semibold min-w-[3.25rem] text-right', resolved.sizeFromImage ? 'text-accent' : 'text-content']">{{ formatMegapixels(resolved.mp) }}</span>
              </div>
              <div class="flex justify-between text-[10px] text-content-muted px-0.5 mt-0.5 pr-[3.75rem]">
                <span v-for="m in MP_TICKS" :key="m">{{ m }}</span>
              </div>
            </template>
          </div>
        </div>

        <!-- Exact dims -->
        <div class="flex items-center gap-2 mt-2">
          <input v-no-autocorrect
            type="number"
            :value="resolved.width"
            :disabled="!!tiers"
            :class="dimInputClass"
            @change="onTypedDims(Number(($event.target as HTMLInputElement).value), resolved.height)"
          >
          <span class="text-content-muted">×</span>
          <input v-no-autocorrect
            type="number"
            :value="resolved.height"
            :disabled="!!tiers"
            :class="dimInputClass"
            @change="onTypedDims(resolved.width, Number(($event.target as HTMLInputElement).value))"
          >
        </div>

        <!-- Result -->
        <div :class="['mt-2 flex items-center gap-2 text-xs', resolved.cropWarning ? 'text-amber-400' : 'text-content-secondary']">
          <span class="border border-edge bg-surface-raised flex-shrink-0 rounded-media" :style="previewStyle(resolved.width, resolved.height, 14)"></span>
          <span>{{ resolved.cropWarning || resultLine }}<template v-if="resolved.tierMissing"> · {{ tierLabel(policy.tier) }} isn't offered at {{ resolved.ratioLabel }}</template></span>
        </div>
        <div v-if="armedNote" class="mt-1.5 text-[11px] text-accent/80">{{ armedNote }}</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted, defineComponent, h } from 'vue'
import {
  RATIO_CHOICES,
  resolveResolution,
  ratioValue,
  formatMegapixels,
  formatTier,
  tierGroups,
  policyWithDims,
  roundMp,
  type ResolutionPolicy,
  type ImageDims,
} from '../utils/resolutionPolicy'
import { detectResolutionControls } from '../utils/resolutionControls'

const props = withDefaults(defineProps<{
  policy: ResolutionPolicy
  /** First input image (or start frame). Null when the slot is empty. */
  image?: ImageDims | null
  /** Whether this tool takes an image at all. Hides the From-image tiles when false. */
  hasImageInput?: boolean
  /** Tool schema properties: grid step / allowed dimensions. */
  schemaProps?: Record<string, any> | null
  disabled?: boolean
  compact?: boolean
  /** Text shown while following is armed with no image yet. */
  armedText?: string
  /** How list-constrained sizes are labelled: '720p' for video, '1.6MP' for images. */
  sizeStyle?: 'tier' | 'mp'
}>(), {
  image: null,
  hasImageInput: false,
  schemaProps: null,
  disabled: false,
  compact: false,
  armedText: '',
  sizeStyle: 'mp',
})

const emit = defineEmits<{
  (e: 'update:policy', policy: ResolutionPolicy): void
}>()

const ImageGlyph = defineComponent({
  render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8 }, [
    h('rect', { x: 3, y: 4, width: 18, height: 16, rx: 2 }),
    h('circle', { cx: 9, cy: 10, r: 1.6 }),
    h('path', { d: 'M21 16l-5-5-8 8' }),
  ]),
})

const MP_MIN_LOG = -2  // 0.25MP
const MP_MAX_LOG = 3   // 8MP
const MP_TICKS = ['0.25', '0.5', '1', '2', '4', '8']

const resolved = computed(() => resolveResolution(props.policy, props.image ?? null, props.schemaProps))
const allowed = computed(() => detectResolutionControls(props.schemaProps).allowedDimensions)
const tiers = computed(() => (allowed.value && allowed.value.length ? tierGroups(allowed.value) : null))
const ratioChoices = computed<readonly string[]>(() => tiers.value ? tiers.value.map(g => g.ratio) : RATIO_CHOICES)
function tierLabel(shortEdge: number, pair?: [number, number]): string {
  if (props.sizeStyle === 'tier') return formatTier(shortEdge)
  return formatMegapixels(pair ? (pair[0] * pair[1]) / 1_000_000 : resolved.value.mp)
}
/** Sizes offered at the current shape, deduped by label. */
const sizeOptions = computed(() => {
  if (!tiers.value) return []
  const g = tiers.value.find(x => x.ratio === resolved.value.ratioLabel)
  if (!g) return []
  const seen = new Set<string>()
  const out: { tier: number; label: string }[] = []
  for (const p of g.pairs) {
    const tier = Math.min(p[0], p[1])
    const label = tierLabel(tier, p)
    if (seen.has(label)) continue
    seen.add(label)
    out.push({ tier, label })
  }
  return out
})
const hasImage = computed(() => !!(props.image && props.image.width > 0 && props.image.height > 0))

const sizeLabel = computed(() => tiers.value ? tierLabel(resolved.value.tier ?? 0, [resolved.value.width, resolved.value.height]) : formatMegapixels(resolved.value.mp))
const tagClass = 'text-[11px] font-semibold px-1.5 py-0.5 rounded-md bg-accent/15 text-accent'
const dimInputClass = 'w-full px-2.5 py-1.5 bg-overlay-subtle border border-transparent rounded-md text-content font-mono tabular-nums text-sm focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none disabled:opacity-50'

const customRatioLabel = computed(() => {
  if (tiers.value || resolved.value.shapeFromImage || resolved.value.ratioChoice) return null
  return resolved.value.ratioLabel
})

type TileState = 'on' | 'armed' | 'echo' | 'off'
const followShapeState = computed<TileState>(() => props.policy.followShape ? (hasImage.value ? 'on' : 'armed') : 'off')
const followSizeState = computed<TileState>(() => props.policy.followSize ? (hasImage.value ? 'on' : 'armed') : 'off')
function ratioTileState(r: string): TileState {
  if (resolved.value.shapeFromImage) return resolved.value.ratioChoice === r ? 'echo' : 'off'
  return props.policy.ratio === r ? 'on' : 'off'
}
function tierState(t: number): TileState {
  if (resolved.value.sizeFromImage) return resolved.value.tier === t ? 'echo' : 'off'
  return resolved.value.tier === t ? 'on' : 'off'
}
function tileClass(state: TileState) {
  return [
    'aspect-square flex flex-col items-center justify-center gap-1 rounded-md border transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60',
    state === 'on' ? 'bg-accent/15 border-accent/40 text-accent'
      : state === 'armed' ? 'bg-overlay-subtle border-dashed border-accent/50 text-accent'
      : state === 'echo' ? 'bg-overlay-subtle border-transparent text-accent/60'
      : 'bg-overlay-subtle border-transparent text-content-secondary hover:bg-overlay-light hover:text-content',
  ]
}

const resultLine = computed(() => {
  const r = resolved.value
  const name = props.image?.name ?? 'the image'
  const size = sizeLabel.value
  if (r.shapeFromImage && r.sizeFromImage) return `Same as ${name}: ${r.width}×${r.height}`
  if (r.shapeFromImage) return `${name}'s shape at ${size}: ${r.width}×${r.height}`
  if (r.sizeFromImage) return `${r.ratioLabel} at ${name}'s size: ${r.width}×${r.height}`
  if (customRatioLabel.value) return `Exactly ${r.width}×${r.height}. Tap a shape or size to let go.`
  return `${r.ratioLabel} at ${size}: ${r.width}×${r.height}`
})

const armedNote = computed(() => {
  if (!props.hasImageInput || hasImage.value) return ''
  const p = props.policy
  if (!p.followShape && !p.followSize) return ''
  if (props.armedText) return props.armedText
  if (p.followShape && p.followSize) return 'Will match the first image you add.'
  if (p.followShape) return 'Shape will follow the first image you add.'
  return 'Size will follow the first image you add.'
})

function update(patch: Partial<ResolutionPolicy>) {
  emit('update:policy', { ...props.policy, ...patch })
}

// With an image present, picking a chip overrides the image for that axis.
// With no image, it only sets the fallback and following stays armed.
function pickRatio(r: string) {
  update({ ratio: r, followShape: hasImage.value ? false : props.policy.followShape })
}
function toggleFollowShape() { update({ followShape: !props.policy.followShape }) }
function toggleFollowSize() { update({ followSize: !props.policy.followSize }) }
function pickTier(t: number) {
  update({ tier: t, followSize: hasImage.value ? false : props.policy.followSize })
}
function onSlider(v: string) {
  const mp = roundMp(Math.pow(2, Number(v)))
  update({ mp, followSize: hasImage.value ? false : props.policy.followSize })
}
function onTypedDims(w: number, hgt: number) {
  if (!Number.isFinite(w) || !Number.isFinite(hgt) || w <= 0 || hgt <= 0) return
  emit('update:policy', { ...policyWithDims(props.policy, w, hgt), followShape: false, followSize: false })
}

function previewStyle(w: number, h: number, max: number) {
  if (!(w > 0) || !(h > 0)) return { width: `${max}px`, height: `${max}px` }
  return w >= h
    ? { width: `${max}px`, height: `${Math.max(3, Math.round((h / w) * max))}px` }
    : { width: `${Math.max(3, Math.round((w / h) * max))}px`, height: `${max}px` }
}

// --- Popover ---
const isOpen = ref(false)
const containerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})

function toggle() {
  if (props.disabled) return
  isOpen.value ? close() : open()
}
async function open() {
  isOpen.value = true
  await nextTick()
  position()
  window.addEventListener('resize', position)
  window.addEventListener('scroll', position, true)
  document.addEventListener('keydown', onKeydown)
}
function close() {
  isOpen.value = false
  window.removeEventListener('resize', position)
  window.removeEventListener('scroll', position, true)
  document.removeEventListener('keydown', onKeydown)
}
function onKeydown(e: KeyboardEvent) { if (e.key === 'Escape') close() }
function position() {
  if (!containerRef.value || !panelRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const el = panelRef.value
  const width = el.offsetWidth
  const height = el.offsetHeight
  const left = Math.max(8, Math.min(rect.left, vw - width - 8))
  const spaceBelow = vh - rect.bottom - 12
  const spaceAbove = rect.top - 12
  if (height <= spaceBelow || spaceBelow >= spaceAbove) {
    panelStyle.value = { left: `${left}px`, top: `${rect.bottom + 4}px`, maxHeight: `${Math.max(120, Math.floor(spaceBelow))}px`, overflowY: 'auto' }
  } else {
    panelStyle.value = { left: `${left}px`, bottom: `${vh - rect.top + 4}px`, maxHeight: `${Math.max(120, Math.floor(spaceAbove))}px`, overflowY: 'auto' }
  }
}
watch(() => props.disabled, (d) => { if (d) close() })
onUnmounted(close)
</script>
