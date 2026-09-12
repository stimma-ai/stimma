<script setup lang="ts">
/**
 * The phone editor's Adjust surface (DESIGN.md §3.6a): the selected step's
 * controls as a grid of parameter cells with the chosen one on a dial. The
 * desktop inspector stacks every slider of a group; a phone shows every VALUE
 * and one control, and lets the picture itself be the slider (the host drives
 * the same active parameter from a drag on the canvas, see `active`).
 *
 * Reads and writes the same params the desktop AdjustInspector does, through
 * the same change/commit events, so a step edited here and on a desktop is
 * one step. Groups with too many controls for one screen carry a segment row
 * above the grid: Mixer's channel, Grading's tonal range, and Detail's four
 * jobs (presence, sharpening, luminance noise, color noise) — the hierarchy
 * the desktop draws with section headers.
 *
 * Light's curve is one more cell, but too tall to share the panel with the
 * grid: choosing it asks the host for a level of its own (`curve`), where
 * the plot has the width and the row carries its channels.
 */
import { computed, ref, watch } from 'vue'
import type { AdjustSliderControl, PhotoAdjustmentGroupId } from '../stack/adjustSections'
import { levelEditById, MIXER_BANDS, MIXER_MODES, toneCurveValueOf } from '../stack/adjustSections'
import type { ToneCurveHistogram } from '../stack/toneCurve'
import DeckSegments from './DeckSegments.vue'
import ParamDeck from './ParamDeck.vue'
import type { DeckParam } from './ParamDeck.vue'
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
  /** The Curve cell: open the curve on its own level. */
  curve: []
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
] as const
const GRADE_LABELS: Record<string, string> = { Hue: 'Hue', Sat: 'Strength', Lum: 'Luminance' }

/** Detail's fifteen sliders as the four jobs they are; short names inside each. */
const DETAIL_GROUPS = [
  { id: 'presence', label: 'Presence', keys: ['texture', 'clarity', 'dehaze', 'moire', 'defringe'], short: {} as Record<string, string> },
  { id: 'sharpen', label: 'Sharpen', keys: ['sharpen', 'sharpenRadius', 'sharpenDetail', 'sharpenMasking'],
    short: { sharpen: 'Amount', sharpenRadius: 'Radius', sharpenDetail: 'Detail', sharpenMasking: 'Masking' } },
  { id: 'noise', label: 'Noise', keys: ['noiseReduction', 'noiseReductionDetail', 'noiseReductionContrast'],
    short: { noiseReduction: 'Amount', noiseReductionDetail: 'Detail', noiseReductionContrast: 'Contrast' } },
  { id: 'colorNoise', label: 'Color noise', keys: ['colorNoiseReduction', 'colorNoiseReductionDetail', 'colorNoiseReductionSmoothness'],
    short: { colorNoiseReduction: 'Amount', colorNoiseReductionDetail: 'Detail', colorNoiseReductionSmoothness: 'Smoothness' } },
] as const
type DetailGroupId = (typeof DETAIL_GROUPS)[number]['id']

/** Names that would truncate in a third of a phone's width. */
const SHORT_LABELS: Record<string, string> = { grainRoughness: 'Roughness', colorizeHue: 'Colorize hue' }

const levelEdit = computed(() => levelEditById(String(props.section)) ?? null)
const presentation = computed(() => levelEdit.value?.presentation)
const mixerMode = ref<'Hue' | 'Sat' | 'Lum'>('Hue')
const gradeRange = ref<'Shadow' | 'Mid' | 'Highlight'>('Mid')
const detailGroup = ref<DetailGroupId>('presence')

const sliders = computed<AdjustSliderControl[]>(() =>
  (levelEdit.value?.controls ?? []).filter((c): c is AdjustSliderControl => c.kind !== 'curve')
)
const curveControl = computed(() => (levelEdit.value?.controls ?? []).find(c => c.kind === 'curve') ?? null)

function isHue(key: string) { return /Hue$/.test(key) && !/Shift$/.test(key) }
function valueOf(control: AdjustSliderControl) {
  const value = props.params?.[control.key]
  return typeof value === 'number' ? value : control.default
}
function isModified(control: AdjustSliderControl) { return valueOf(control) !== control.default }
function toParam(control: AdjustSliderControl, label = SHORT_LABELS[control.key] ?? control.label, swatch?: string): DeckParam {
  return {
    key: control.key, label, swatch, value: valueOf(control),
    min: control.min, max: control.max, step: control.step, default: control.default, hue: isHue(control.key),
  }
}

/** The grid: the group's sliders, filtered by the segment for the groups that have one. */
const visible = computed<DeckParam[]>(() => {
  const all = sliders.value
  const byKey = (key: string) => all.find(c => c.key === key)
  if (presentation.value === 'mixer') {
    return MIXER_BANDS.map(band => toParam(byKey(`mixer${mixerMode.value}${band.id}`)!, band.label, band.swatch))
  }
  if (presentation.value === 'grade') {
    const ranged = ['Hue', 'Sat', 'Lum'].map(part => toParam(byKey(`grade${gradeRange.value}${part}`)!, GRADE_LABELS[part]))
    const mix = all.filter(c => c.key === 'gradeBlend' || c.key === 'gradeBalance').map(c => toParam(c))
    return [...ranged, ...mix]
  }
  if (presentation.value === 'point') {
    return all.filter(c => !['pointHue', 'pointSat', 'pointLum'].includes(c.key)).map(c => toParam(c))
  }
  if (levelEdit.value?.id === 'detail') {
    const group = DETAIL_GROUPS.find(g => g.id === detailGroup.value)!
    return group.keys.map(key => byKey(key)).filter((c): c is AdjustSliderControl => !!c)
      .map(c => toParam(c, (group.short as Record<string, string>)[c.key] ?? c.label))
  }
  return all.map(c => toParam(c))
})

/** A dot on a segment whose parameters carry values. */
const mixerSegments = computed(() => MIXER_MODES.map(mode => ({
  ...mode, modified: MIXER_BANDS.some(band => { const c = sliders.value.find(s => s.key === `mixer${mode.id}${band.id}`); return !!c && isModified(c) }),
})))
const gradeSegments = computed(() => GRADE_RANGES.map(range => {
  const sat = props.params?.[`grade${range.id}Sat`] ?? 0
  return {
    ...range,
    modified: ['Hue', 'Sat', 'Lum'].some(part => { const c = sliders.value.find(s => s.key === `grade${range.id}${part}`); return !!c && isModified(c) }),
    // The tint each range carries, so the three ranges read as colors, not words.
    swatch: sat > 0 ? `hsl(${props.params?.[`grade${range.id}Hue`] ?? 0} ${Math.max(35, sat)}% 55%)` : null,
  }
}))
/** Detail is the one group whose segments hold different counts: hold its grid at the largest. */
const rows = computed(() => levelEdit.value?.id === 'detail' ? 2 : 0)
const detailSegments = computed(() => DETAIL_GROUPS.map(group => ({
  id: group.id, label: group.label,
  modified: group.keys.some(key => { const c = sliders.value.find(s => s.key === key); return !!c && isModified(c) }),
})))

const activeKey = ref<string | null>(null)
const active = computed(() => visible.value.find(c => c.key === activeKey.value) ?? visible.value[0] ?? null)
watch(active, a => {
  emit('active', a
    ? { key: a.key, label: a.label, min: a.min, max: a.max, step: a.step ?? 1, default: a.default ?? 0, hue: !!a.hue }
    : null)
}, { immediate: true })
// A new step starts on its first parameter and its first segment.
watch(() => props.section, () => {
  activeKey.value = null
  mixerMode.value = 'Hue'
  gradeRange.value = 'Mid'
  detailGroup.value = 'presence'
})

/**
 * A hue is invisible until its strength is up, so reaching for a Grading or
 * Colorize hue while its strength is zero brings the strength along: the
 * person asked to see a color, not to set an invisible number.
 */
function onChange(key: string, value: number) {
  const patch: Record<string, number> = { [key]: value }
  const partner = /^grade(Shadow|Mid|Highlight)Hue$/.test(key) ? key.replace(/Hue$/, 'Sat')
    : key === 'colorizeHue' ? 'colorizeAmount' : null
  if (partner && !(props.params?.[partner] > 0)) patch[partner] = 30
  emit('change', patch, `adjust:${key}`)
}
const curveModified = computed(() => {
  const value = props.params?.[curveControl.value?.key ?? 'curve']
  return value !== undefined && JSON.stringify(toneCurveValueOf(value)) !== JSON.stringify(toneCurveValueOf(undefined))
})
const pickedColor = computed(() => {
  const p = props.params || {}
  return typeof p.pointHue === 'number' ? `hsl(${p.pointHue} ${p.pointSat ?? 60}% ${p.pointLum ?? 55}%)` : null
})
</script>

<template>
  <div class="flex flex-col" data-adjust-deck>
    <!-- Which set of parameters the grid shows, for the groups that have more than one. -->
    <DeckSegments v-if="presentation === 'mixer'" v-model="mixerMode" :options="mixerSegments" aria-label="Mixer channel" />
    <DeckSegments v-else-if="presentation === 'grade'" v-model="gradeRange" :options="gradeSegments" aria-label="Tonal range" />
    <DeckSegments v-else-if="levelEdit?.id === 'detail'" v-model="detailGroup" :options="detailSegments" aria-label="Detail group" />
    <div v-else-if="presentation === 'point'" class="flex items-center gap-2 min-h-11">
      <span v-if="pickedColor" class="w-6 h-6 rounded-full border border-edge-subtle shrink-0" :style="{ background: pickedColor }" />
      <button
        type="button"
        class="min-h-11 px-2.5 rounded-md text-[13px] font-medium flex items-center gap-1.5"
        :class="picking ? 'bg-accent/15 text-accent-hi' : 'text-content-secondary'"
        :aria-pressed="picking"
        @click="emit('pick')"
      >
        <ToolIcon name="eyeDropper" :size="16" />
        {{ picking ? 'Picking…' : 'Pick color' }}
      </button>
    </div>

    <!-- The grid holds its height across a group's segments, so a segment
         tap never moves the segments; groups may differ from one another. -->
    <ParamDeck
      :params="visible"
      :active="activeKey"
      :rows="rows"
      :disabled="disabled"
      @update:active="activeKey = $event"
      @change="onChange"
      @commit="emit('commit')"
    >
      <button
        v-if="curveControl"
        type="button"
        class="min-w-0 min-h-11 px-2 rounded-md flex items-center justify-between gap-1.5 text-[13px] font-medium text-content-secondary transition-colors"
        data-param-chip="curve"
        @click="emit('curve')"
      >
        <span class="flex items-center gap-1.5 min-w-0">
          <ToolIcon name="histogram" :size="15" />
          <span class="truncate">Curve</span>
        </span>
        <span v-if="curveModified" class="w-1.5 h-1.5 rounded-full bg-accent shrink-0" aria-hidden="true" />
        <svg v-else viewBox="0 0 24 24" class="w-3.5 h-3.5 shrink-0 text-content-tertiary" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
      </button>
    </ParamDeck>
  </div>
</template>
