<script setup lang="ts">
/**
 * The phone editor's Adjust surface (DESIGN.md §3.6a): the selected step's
 * controls as one row of parameter chips, the chosen one on a dial. The
 * desktop inspector stacks every slider of a group; a phone shows one at a
 * time and lets the picture itself be the slider (the host drives the same
 * active parameter from a drag on the canvas, see `active`).
 *
 * Reads and writes the same params the desktop AdjustInspector does, through
 * the same change/commit events, so a step edited here and on a desktop is
 * one step. Mixer, Grading and Point color are the same plain sliders wearing
 * a segment (band mode, tonal range) instead of their custom desktop panels.
 * Light's curve is a chip that swaps the dial for the real ToneCurveControl.
 */
import { computed, ref, watch } from 'vue'
import type { AdjustSliderControl, PhotoAdjustmentGroupId, ToneCurve } from '../stack/adjustSections'
import { levelEditById, MIXER_BANDS, MIXER_MODES, toneCurveValueOf } from '../stack/adjustSections'
import type { ToneCurveHistogram } from '../stack/toneCurve'
import ParamDial from './ParamDial.vue'
import ToneCurveControl from './ToneCurveControl.vue'
import ToolIcon from './ToolIcon.vue'

const props = defineProps<{
  section: PhotoAdjustmentGroupId | string
  params: Record<string, any>
  histogram?: ToneCurveHistogram
  picking?: boolean
  clipShadows?: boolean
  clipHighlights?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{
  change: [Record<string, any>, string]
  commit: []
  pick: []
  clip: [{ shadows: boolean; highlights: boolean }]
  /** The parameter the picture drag should drive, or null. */
  active: [ActiveParam | null]
}>()

export interface ActiveParam {
  key: string
  label: string
  min: number
  max: number
  step: number
  default: number
  hue: boolean
}

const GRADE_RANGES = [
  { id: 'Shadow', label: 'Shadows' },
  { id: 'Mid', label: 'Midtones' },
  { id: 'Highlight', label: 'Highlights' },
]
const GRADE_LABELS: Record<string, string> = { Hue: 'Hue', Sat: 'Strength', Lum: 'Luminance' }

const levelEdit = computed(() => levelEditById(String(props.section)) ?? null)
const presentation = computed(() => levelEdit.value?.presentation)
const mixerMode = ref<'Hue' | 'Sat' | 'Lum'>('Hue')
const gradeRange = ref<'Shadow' | 'Mid' | 'Highlight'>('Mid')
const curveOpen = ref(false)

const sliders = computed<AdjustSliderControl[]>(() =>
  (levelEdit.value?.controls ?? []).filter((c): c is AdjustSliderControl => c.kind !== 'curve')
)
const curveControl = computed(() => (levelEdit.value?.controls ?? []).find(c => c.kind === 'curve') ?? null)

/** The chips: the group's sliders, filtered by the segment for the custom presentations. */
const visible = computed<Array<AdjustSliderControl & { short: string; swatch?: string }>>(() => {
  const all = sliders.value
  if (presentation.value === 'mixer') {
    return MIXER_BANDS.map(band => {
      const control = all.find(c => c.key === `mixer${mixerMode.value}${band.id}`)!
      return { ...control, short: band.label, swatch: band.swatch }
    })
  }
  if (presentation.value === 'grade') {
    const ranged = ['Hue', 'Sat', 'Lum'].map(part => {
      const control = all.find(c => c.key === `grade${gradeRange.value}${part}`)!
      return { ...control, short: GRADE_LABELS[part] }
    })
    const mix = all.filter(c => c.key === 'gradeBlend' || c.key === 'gradeBalance').map(c => ({ ...c, short: c.label }))
    return [...ranged, ...mix]
  }
  if (presentation.value === 'point') {
    return all.filter(c => !['pointHue', 'pointSat', 'pointLum'].includes(c.key)).map(c => ({ ...c, short: c.label }))
  }
  return all.map(c => ({ ...c, short: c.label }))
})

const activeKey = ref<string | null>(null)
const active = computed(() => visible.value.find(c => c.key === activeKey.value) ?? visible.value[0] ?? null)
watch([visible, () => props.section], () => {
  if (!visible.value.some(c => c.key === activeKey.value)) activeKey.value = visible.value[0]?.key ?? null
}, { immediate: true })
watch([active, curveOpen], () => {
  const a = active.value
  emit('active', a && !curveOpen.value
    ? { key: a.key, label: a.short, min: a.min, max: a.max, step: a.step, default: a.default, hue: isHue(a.key) }
    : null)
}, { immediate: true })
watch(() => props.section, () => { curveOpen.value = false })

function isHue(key: string) { return /Hue$/.test(key) && !/Shift$/.test(key) }
function valueOf(control: AdjustSliderControl) {
  const value = props.params?.[control.key]
  return typeof value === 'number' ? value : control.default
}
function readout(control: AdjustSliderControl) {
  const value = valueOf(control)
  const text = control.step < 1 ? value.toFixed(control.step < 0.1 ? 2 : 1) : String(Math.round(value))
  return (control.min < 0 && value > 0 ? '+' : '') + text
}
function set(control: AdjustSliderControl, value: number) {
  emit('change', { [control.key]: value }, `adjust:${control.key}`)
}
function curveValue(): ToneCurve { return toneCurveValueOf(props.params?.[curveControl.value?.key ?? 'curve']) }
const pickedColor = computed(() => {
  const p = props.params || {}
  return typeof p.pointHue === 'number' ? `hsl(${p.pointHue} ${p.pointSat ?? 60}% ${p.pointLum ?? 55}%)` : null
})
</script>

<template>
  <div class="flex flex-col gap-1" data-adjust-deck>
    <!-- Mode segments for the custom presentations: one underline, no fill. -->
    <div v-if="presentation === 'mixer'" class="flex" role="radiogroup" aria-label="Mixer channel">
      <button
        v-for="mode in MIXER_MODES"
        :key="mode.id"
        type="button"
        role="radio"
        class="relative flex-1 min-h-10 px-2 text-[13px] font-medium"
        :class="mixerMode === mode.id ? 'text-content' : 'text-content-secondary'"
        :aria-checked="mixerMode === mode.id"
        @click="mixerMode = mode.id"
      >
        {{ mode.label }}
        <span v-if="mixerMode === mode.id" class="absolute left-2 right-2 bottom-1 h-0.5 rounded-full bg-accent" />
      </button>
    </div>
    <div v-else-if="presentation === 'grade'" class="flex" role="radiogroup" aria-label="Tonal range">
      <button
        v-for="range in GRADE_RANGES"
        :key="range.id"
        type="button"
        role="radio"
        class="relative flex-1 min-h-10 px-2 text-[13px] font-medium"
        :class="gradeRange === range.id ? 'text-content' : 'text-content-secondary'"
        :aria-checked="gradeRange === range.id"
        @click="gradeRange = range.id as 'Shadow' | 'Mid' | 'Highlight'"
      >
        {{ range.label }}
        <span v-if="gradeRange === range.id" class="absolute left-2 right-2 bottom-1 h-0.5 rounded-full bg-accent" />
      </button>
    </div>
    <div v-else-if="presentation === 'point'" class="flex items-center gap-2 min-h-10">
      <span v-if="pickedColor" class="w-6 h-6 rounded-full border border-edge-subtle shrink-0" :style="{ background: pickedColor }" />
      <button
        type="button"
        class="min-h-10 px-2.5 rounded-md text-[13px] font-medium flex items-center gap-1.5"
        :class="picking ? 'bg-accent/15 text-accent-hi' : 'text-content-secondary'"
        :aria-pressed="picking"
        @click="emit('pick')"
      >
        <ToolIcon name="eyeDropper" :size="16" />
        {{ picking ? 'Tap the photo…' : pickedColor ? 'Pick again' : 'Pick a color' }}
      </button>
      <span class="text-xs text-content-tertiary">then shift it</span>
    </div>

    <template v-if="curveOpen && curveControl">
      <!-- The curve replaces the dial: channel segment, a way back to the sliders. -->
      <div class="flex items-center gap-1 -mx-1">
        <button
          type="button"
          class="min-h-10 px-2.5 rounded-md text-[13px] font-medium text-content-secondary flex items-center gap-1.5"
          @click="curveOpen = false"
        >
          <ToolIcon name="sliders" :size="16" />
          Sliders
        </button>
        <span class="flex-1" />
      </div>
      <div class="mx-auto w-full max-w-[280px] pb-1">
        <ToneCurveControl
          :label="curveControl.label"
          :value="curveValue()"
          :histogram="histogram"
          :disabled="disabled"
          :clip-shadows="clipShadows"
          :clip-highlights="clipHighlights"
          @input="emit('change', { [curveControl.key]: $event }, 'adjust:curve')"
          @commit="emit('commit')"
          @clip="emit('clip', $event)"
        />
      </div>
    </template>
    <template v-else>
      <!-- The parameters: bare text with a value, the active one wearing the row's one wash. -->
      <div class="flex gap-1 overflow-x-auto -mx-3 px-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" role="tablist" aria-label="Parameters">
        <button
          v-for="control in visible"
          :key="control.key"
          type="button"
          role="tab"
          class="flex-none min-h-10 h-10 px-2.5 rounded-md text-[13px] font-medium flex items-center gap-1.5 whitespace-nowrap transition-colors"
          :class="active?.key === control.key ? 'bg-accent/15 text-accent-hi' : 'text-content-secondary'"
          :aria-selected="active?.key === control.key"
          :data-param-chip="control.key"
          @click="activeKey = control.key"
        >
          <span v-if="control.swatch" class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ background: control.swatch }" />
          {{ control.short }}
          <span
            class="font-mono text-xs tabular-nums"
            :class="active?.key === control.key ? 'text-accent-hi' : valueOf(control) !== control.default ? 'text-accent-hi' : 'text-content-tertiary'"
          >{{ readout(control) }}</span>
        </button>
        <button
          v-if="curveControl"
          type="button"
          class="flex-none min-h-10 h-10 px-2.5 rounded-md text-[13px] font-medium flex items-center gap-1.5 whitespace-nowrap text-content-secondary"
          data-param-chip="curve"
          @click="curveOpen = true"
        >
          <ToolIcon name="histogram" :size="16" />
          Curve
        </button>
      </div>
      <ParamDial
        v-if="active"
        :label="active.short"
        :value="valueOf(active)"
        :min="active.min"
        :max="active.max"
        :step="active.step"
        :default="active.default"
        :hue="isHue(active.key)"
        :disabled="disabled"
        @input="set(active, $event)"
        @commit="emit('commit')"
        @reset="set(active, active.default); emit('commit')"
      />
    </template>
  </div>
</template>
