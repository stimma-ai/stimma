<template>
  <div ref="containerRef" class="relative inline-block max-w-full compact:block">
    <!-- ONE trigger everywhere (tool and flow forms): aspect glyph, size,
         chevron in a single filled control. When a reference image locks an
         axis, the lock rides inside the same control: it sits on the glyph's
         corner and its caption names the locked axis, so it reads as a state
         of this control rather than a neighbour. -->
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      class="inline-flex compact:flex compact:w-full items-center gap-2 h-9 pl-2 pr-2 max-w-full rounded-md bg-field hover:bg-overlay-light text-ctl font-medium text-content-secondary hover:text-content transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      :aria-label="`Aspect and size: ${triggerValue}${lockTag ? ', ' + lockTag + ' locked to the reference image' : ''}`"
    >
      <span class="relative flex-none w-6 h-6 grid place-items-center">
        <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor" aria-hidden="true">
          <!-- viewfinder corners: says "frame", never "checkbox" -->
          <path d="M2.5 7V3.5a1 1 0 0 1 1-1H7M17 2.5h3.5a1 1 0 0 1 1 1V7M21.5 17v3.5a1 1 0 0 1-1 1H17M7 21.5H3.5a1 1 0 0 1-1-1V17" stroke-width="1.5" stroke-linecap="round" opacity=".55" />
          <rect :x="glyph.x" :y="glyph.y" :width="glyph.w" :height="glyph.h" rx="1" fill="currentColor" fill-opacity=".22" stroke-width="1.5" />
        </svg>
        <svg v-if="lockTag" viewBox="0 0 16 16" fill="currentColor" class="absolute -right-1 -bottom-1 w-3 h-3 rounded-full p-px bg-surface text-accent-hi" aria-hidden="true">
          <path d="M8 1.5a3.5 3.5 0 0 0-3.5 3.5V7H4a1.5 1.5 0 0 0-1.5 1.5v5A1.5 1.5 0 0 0 4 15h8a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 12 7h-.5V5A3.5 3.5 0 0 0 8 1.5ZM6 5a2 2 0 1 1 4 0v2H6V5Z" />
        </svg>
      </span>
      <span :class="['font-mono tabular-nums text-xs text-content', lockTag ? 'compact:order-2' : '']">{{ triggerValue }}</span>
      <span v-if="lockTag" class="flex items-center gap-2 min-w-0 compact:order-1 compact:flex-1" :title="explanation">
        <span class="w-px h-4 bg-edge compact:hidden" aria-hidden="true"></span>
        <span :class="['text-xs font-semibold', lockArmed ? 'text-content-tertiary' : 'text-accent-hi']">{{ lockTag }}</span>
      </span>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" class="w-icon-inline h-icon-inline flex-none text-content-tertiary compact:order-3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <Teleport to="body">
      <div v-if="isOpen" class="fixed inset-0 z-menu" @click="close" />
      <div
        v-if="isOpen"
        ref="panelRef" data-escape-layer
        class="fixed z-menu w-[23rem] max-w-[calc(100vw-1rem)] rounded-lg border border-edge-subtle bg-surface p-4 shadow-lg"
        :style="panelStyle"
        role="dialog"
        @click.stop
      >
        <!-- Aspect -->
        <div class="flex items-center justify-between h-6 mb-2">
          <span class="text-ctl font-semibold text-content-secondary">Aspect</span>
          <label v-if="hasImageInput" class="flex items-center gap-1.5 cursor-pointer select-none">
            <span class="text-[11px] font-medium text-content-muted">{{ followLabel }}</span>
            <span class="relative inline-flex shrink-0 items-center">
              <input type="checkbox" role="switch" aria-label="Aspect follows the reference image" class="peer sr-only" :checked="policy.followShape" @change="toggleFollowShape" />
              <span class="peer h-4 w-7 rounded-full bg-surface-hover after:absolute after:left-[2px] after:top-[2px] after:h-3 after:w-3 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full" />
            </span>
          </label>
        </div>
        <div :class="['grid grid-cols-5 gap-1.5 transition-opacity', resolved.shapeFromImage ? 'opacity-40' : '']">
          <button
            v-for="r in ratioChoices"
            :key="r"
            type="button"
            :class="tileClass(!resolved.shapeFromImage && policy.ratio === r)"
            @click="pickRatio(r)"
          >
            <span class="w-5 h-5 grid place-items-center"><i class="block border-[1.5px] border-current rounded-media" :style="previewStyle(ratioValue(r), 1, 18)"></i></span>
            <span class="text-[10px] leading-none">{{ r }}</span>
          </button>
        </div>

        <!-- Size -->
        <div class="flex items-center justify-between h-6 mt-5 mb-2">
          <span class="text-ctl font-semibold text-content-secondary">Size</span>
          <label v-if="hasImageInput" class="flex items-center gap-1.5 cursor-pointer select-none">
            <span class="text-[11px] font-medium text-content-muted">{{ followLabel }}</span>
            <span class="relative inline-flex shrink-0 items-center">
              <input type="checkbox" role="switch" aria-label="Size follows the reference image" class="peer sr-only" :checked="policy.followSize" @change="toggleFollowSize" />
              <span class="peer h-4 w-7 rounded-full bg-surface-hover after:absolute after:left-[2px] after:top-[2px] after:h-3 after:w-3 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full" />
            </span>
          </label>
        </div>
        <div :class="['transition-opacity', resolved.sizeFromImage ? 'opacity-40' : '']">
          <template v-if="tiers">
            <div class="flex bg-overlay-subtle rounded-md p-0.5 gap-0.5">
              <button
                v-for="opt in sizeOptions"
                :key="opt.label"
                type="button"
                :class="[
                  'flex-1 px-2 py-1.5 rounded-md text-xs font-medium transition-colors duration-150',
                  !resolved.sizeFromImage && resolved.tier === opt.tier ? 'bg-surface-raised text-content' : 'text-content-muted hover:text-content-secondary'
                ]"
                @click="pickTier(opt.tier)"
              >{{ opt.label }}</button>
            </div>
          </template>
          <template v-else>
            <div class="flex items-center gap-3">
              <input v-no-autocorrect
                type="range"
                :min="sliderLog.lo"
                :max="sliderLog.hi"
                step="0.01"
                :value="Math.min(sliderLog.hi, Math.max(sliderLog.lo, Math.log2(resolved.mp)))"
                aria-label="Output size"
                :aria-valuetext="`${customSize ? 'Custom size, ' : ''}${formatMegapixels(resolved.mp)}`"
                :disabled="resolved.sizeFromImage"
                class="flex-1 h-1 bg-overlay-subtle rounded-full appearance-none cursor-pointer disabled:cursor-default [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-accent [&::-moz-range-thumb]:border-0"
                @input="onSlider(($event.target as HTMLInputElement).value)"
              >
              <span class="font-mono tabular-nums text-xs text-content-secondary min-w-[3.25rem] text-right">{{ formatMegapixels(resolved.mp) }}</span>
            </div>
            <div class="relative h-4 mt-0.5 mr-[3.75rem] text-[10px] text-content-muted">
              <span
                v-for="t in sliderTicks"
                :key="t.label"
                :class="['absolute top-0 whitespace-nowrap', t.pct <= 0 ? '' : t.pct >= 100 ? '-translate-x-full' : '-translate-x-1/2']"
                :style="{ left: `${t.pct}%` }"
              >{{ t.label }}</span>
            </div>
            <p v-if="customSize" class="mt-2 text-[11px] text-content-muted">Custom size · {{ formatMegapixels(resolved.mp) }}. The slider selects up to {{ formatMegapixels(sliderBounds.max) }}.</p>
            <p v-if="sizeReduced" class="mt-2 text-[11px] text-content-muted">Size reduced to {{ formatMegapixels(resolved.mp) }} to fit this tool’s dimension limits.</p>
          </template>
        </div>

        <!-- Exact dims -->
        <div class="flex items-center gap-2 mt-4">
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

        <!-- What following means right now -->
        <div v-if="explanation" class="mt-4 pt-3 border-t border-edge-subtle text-[11px] leading-relaxed" :class="resolved.cropWarning ? 'text-amber-400' : 'text-content-muted'">
          {{ explanation }}
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { consumeEscape, isTopmostEscapeLayer } from '../utils/escapeLayers'
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import {
  RATIO_CHOICES,
  resolveResolution,
  ratioValue,
  formatMegapixels,
  formatTier,
  tierGroups,
  megapixelSliderBounds,
  MP_UNIT,
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
  /** Kept for callers; the trigger looks the same everywhere. */
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

const followLabel = 'Match reference'

// A provider may offer a compact normal range while accepting larger custom
// dimensions. Providers without that hint keep their aspect-dependent range.
const activeRatio = computed(() => resolved.value.shapeFromImage && props.image
  ? props.image.width / props.image.height : ratioValue(props.policy.ratio))
const sliderBounds = computed(() => megapixelSliderBounds(props.schemaProps, activeRatio.value))
const customSize = computed(() => resolved.value.mp > sliderBounds.value.max * 1.03)
const sizeReduced = computed(() => {
  const requested = resolved.value.sizeFromImage && props.image
    ? props.image.width * props.image.height / MP_UNIT : props.policy.mp
  return resolved.value.mp < requested * 0.97
})
const sliderLog = computed(() => ({ lo: Math.log2(sliderBounds.value.min), hi: Math.log2(sliderBounds.value.max) }))
const sliderTicks = computed(() => {
  const { lo, hi } = sliderLog.value
  const span = hi - lo || 1
  const pct = (mp: number) => ((Math.log2(mp) - lo) / span) * 100
  const ticks: { label: string; pct: number }[] = []
  const ends = [sliderBounds.value.min, sliderBounds.value.max]
  for (const mp of [0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32]) {
    const x = pct(mp)
    if (x < 8 || x > 92) continue
    ticks.push({ label: String(mp), pct: x })
  }
  ticks.push({ label: formatMegapixels(ends[0]).replace('MP', ''), pct: 0 })
  ticks.push({ label: formatMegapixels(ends[1]).replace('MP', ''), pct: 100 })
  return ticks
})

const resolved = computed(() => resolveResolution(props.policy, props.image ?? null, props.schemaProps))
const allowed = computed(() => detectResolutionControls(props.schemaProps).allowedDimensions)
const tiers = computed(() => (allowed.value && allowed.value.length ? tierGroups(allowed.value) : null))
const ratioChoices = computed<readonly string[]>(() => tiers.value ? tiers.value.map(g => g.ratio) : RATIO_CHOICES)
function tierLabel(shortEdge: number, pair?: [number, number]): string {
  if (props.sizeStyle === 'tier') return formatTier(shortEdge)
  return formatMegapixels(pair ? (pair[0] * pair[1]) / MP_UNIT : resolved.value.mp)
}
/** Sizes offered at the current aspect, deduped by label. */
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
// Preset pairs have a useful shape/size name; flexible dimensions are clearer
// as the actual output pixels, without an approximate ratio or redundant area.
const triggerValue = computed(() => tiers.value
  ? `${resolved.value.ratioLabel} · ${sizeLabel.value.replace('MP', ' MP')}`
  : `${resolved.value.width} × ${resolved.value.height}`)
// The pill names the axis the reference image locks. With following armed but
// no image yet, it has no fill.
const lockTag = computed(() => {
  const r = resolved.value
  const p = props.policy
  const aspect = hasImage.value ? r.shapeFromImage : props.hasImageInput && p.followShape
  const size = hasImage.value ? r.sizeFromImage : props.hasImageInput && p.followSize
  if (aspect && size) return 'Aspect + Size'
  if (aspect) return 'Aspect'
  if (size) return 'Size'
  return ''
})
const lockAspect = computed(() => {
  const r = resolved.value
  return hasImage.value ? r.shapeFromImage : props.hasImageInput && props.policy.followShape
})
// The glyph draws the real output shape inside its 24px frame (min 7px side).
const glyph = computed(() => {
  const w = resolved.value.width, h = resolved.value.height
  const max = 15
  const [gw, gh] = !(w > 0) || !(h > 0) ? [max, max]
    : w >= h ? [max, Math.max(7, Math.round((h / w) * max))] : [Math.max(7, Math.round((w / h) * max)), max]
  return { w: gw, h: gh, x: 12 - gw / 2, y: 12 - gh / 2 }
})
const lockArmed = computed(() => !!lockTag.value && !hasImage.value)
const dimInputClass = 'w-full px-2.5 py-1.5 bg-field border border-transparent rounded-md text-content font-mono tabular-nums text-sm focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none disabled:opacity-50'


function tileClass(on: boolean) {
  return [
    'aspect-square flex flex-col items-center justify-center gap-1 rounded-md border transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60',
    on ? 'bg-accent/15 border-accent/40 text-accent'
      : 'bg-overlay-subtle border-transparent text-content-secondary hover:bg-overlay-light hover:text-content',
  ]
}

// One sentence under the hairline: what the reference image does to the size.
const explanation = computed(() => {
  if (!props.hasImageInput) return ''
  const r = resolved.value
  if (r.cropWarning) return `${r.cropWarning}.`
  const p = props.policy
  const size = sizeLabel.value
  if (!hasImage.value) {
    if (p.followShape && p.followSize) return 'When you add a reference image, the output will be the same size as it.'
    if (p.followShape) return `When you add a reference image, the output will take its aspect at ${size}.`
    if (p.followSize) return `When you add a reference image, the output will keep its pixel count at ${p.ratio}.`
    return ''
  }
  const name = props.image?.name ?? 'the reference image'
  if (p.followShape && p.followSize) return `Output is the same size as ${name}.`
  if (p.followShape) return `Output takes ${name}’s aspect at ${size}.`
  if (p.followSize) return `Output keeps ${name}’s pixel count at ${r.ratioLabel}.`
  return ''
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
  const { lo, hi } = sliderLog.value
  const x = Number(v)
  // Land exactly on the normal slider endpoints, including fractional limits.
  const mp = roundMp(x >= hi - 0.011 ? sliderBounds.value.max : x <= lo + 0.011 ? sliderBounds.value.min : Math.pow(2, x))
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
function onKeydown(e: KeyboardEvent) {
  if (!e.defaultPrevented && e.key === 'Escape' && isTopmostEscapeLayer(panelRef.value)) {
    consumeEscape(e)
    close()
  }
}
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
