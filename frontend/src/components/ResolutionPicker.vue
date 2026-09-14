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
        <div class="flex items-center justify-between h-6 mb-1.5">
          <span class="text-[11px] font-semibold text-content-muted">Shape</span>
          <FollowSwitch v-if="hasImageInput" :on="policy.followShape" @toggle="toggleFollowShape" />
        </div>
        <div :class="['grid grid-cols-5 gap-1 transition-opacity', resolved.shapeFromImage ? 'opacity-40' : '']">
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
          <div
            v-if="customRatioLabel"
            :class="tileClass(true)"
            class="cursor-default"
          >
            <span class="w-5 h-5 grid place-items-center"><i class="block border-[1.5px] border-current rounded-media" :style="previewStyle(resolved.width, resolved.height, 18)"></i></span>
            <span class="text-[10px] leading-none">{{ customRatioLabel }}</span>
          </div>
        </div>

        <!-- Size -->
        <div class="flex items-center justify-between h-6 mt-3 mb-1.5">
          <span class="text-[11px] font-semibold text-content-muted">Size</span>
          <FollowSwitch v-if="hasImageInput" :on="policy.followSize" @toggle="toggleFollowSize" />
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
                  !resolved.sizeFromImage && resolved.tier === opt.tier ? 'bg-accent/15 text-accent' : 'text-content-muted hover:text-content-secondary'
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
                class="flex-1 h-1 bg-overlay-subtle rounded-full appearance-none cursor-pointer disabled:cursor-default [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-accent [&::-moz-range-thumb]:border-0"
                @input="onSlider(($event.target as HTMLInputElement).value)"
              >
              <span class="font-mono tabular-nums text-xs text-content-secondary min-w-[3.25rem] text-right">{{ formatMegapixels(resolved.mp) }}</span>
            </div>
            <div class="flex justify-between text-[10px] text-content-muted px-0.5 mt-0.5 pr-[3.75rem]">
              <span v-for="m in MP_TICKS" :key="m">{{ m }}</span>
            </div>
          </template>
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

        <!-- What following means right now -->
        <div v-if="explanation" class="mt-3 pt-2.5 border-t border-edge-subtle text-[11px] leading-relaxed" :class="resolved.cropWarning ? 'text-amber-400' : 'text-content-muted'">
          {{ explanation }}
        </div>
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

// "From image" switch that lives on the Shape / Size header lines.
const FollowSwitch = defineComponent({
  props: { on: { type: Boolean, required: true } },
  emits: ['toggle'],
  setup: (p, { emit: e }) => () => h('button', {
    type: 'button',
    role: 'switch',
    'aria-checked': p.on,
    class: 'flex items-center gap-1.5 group focus-visible:outline-none focus-visible:ring-2 ring-accent/60 rounded-md',
    onClick: () => e('toggle'),
  }, [
    h('span', { class: ['text-[11px] font-medium transition-colors', p.on ? 'text-accent' : 'text-content-muted group-hover:text-content-secondary'] }, 'From image'),
    h('span', { class: ['relative inline-block w-7 h-4 rounded-full transition-colors', p.on ? 'bg-accent' : 'bg-overlay-light'] }, [
      h('span', { class: ['absolute top-0.5 w-3 h-3 rounded-full bg-surface transition-transform', p.on ? 'translate-x-3.5' : 'translate-x-0.5'] }),
    ]),
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

function tileClass(on: boolean) {
  return [
    'aspect-square flex flex-col items-center justify-center gap-1 rounded-md border transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60',
    on ? 'bg-accent/15 border-accent/40 text-accent'
      : 'bg-overlay-subtle border-transparent text-content-secondary hover:bg-overlay-light hover:text-content',
  ]
}

// One sentence under the hairline that says what following does right now.
const explanation = computed(() => {
  if (!props.hasImageInput) return ''
  const r = resolved.value
  if (r.cropWarning) return `${r.cropWarning}. Turn on “From image” for shape to use the whole picture.`
  const p = props.policy
  if (!p.followShape && !p.followSize) return ''
  const name = props.image?.name ?? 'the image'
  if (props.armedText && !hasImage.value) return props.armedText
  if (!hasImage.value) {
    if (p.followShape && p.followSize) return 'These settings apply until an image is added; then its shape and size are used instead. Picking a shape or size while an image is present overrides it.'
    if (p.followShape) return `Until an image is added, ${p.ratio} is used. Once one is present, its shape is used at the size set here.`
    return `Until an image is added, ${sizeLabel.value} at ${p.ratio} is used. Once one is present, its size is kept and the shape set here is applied.`
  }
  if (p.followShape && p.followSize) return `Matching ${name} exactly. Pick a shape or size to override it; remove the image and the settings above come back.`
  if (p.followShape) return `Using ${name}'s shape at ${sizeLabel.value}. Pick a shape to override it.`
  return `Keeping ${name}'s size and applying ${r.ratioLabel}. Pick a size to override it.`
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
