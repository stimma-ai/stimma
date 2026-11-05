<script setup lang="ts">
/**
 * The output stage's size control, laid out for a ~300px column.
 *
 * Same elements as `UpscaleResolutionPicker` and the same schema-driven
 * constraints — mode, presets, a continuous value, the before/after — but a
 * layout designed for this width instead of squeezed into it. The wide control
 * puts its label and mode switch on one line, its presets on another that
 * wraps, and its result behind a rule; at sidebar width that reads as five
 * loose fragments rather than one control.
 *
 * The arrangement here is: the value belongs to the label (one header row),
 * the presets are the primary way to set it (one non-wrapping row of equal
 * chips), the slider is the fine adjustment under them, and the result is the
 * last line with nothing between it and the thing that produced it.
 *
 * Legality is not re-derived: factors snap through the same `snapScaleFactor`
 * the wide control uses, so a tool that only accepts 2× cannot be handed 2.5×
 * from here either.
 */
import { computed, watch } from 'vue'
import { snapScaleFactor } from '../../utils/resolutionControls'

const props = withDefaults(defineProps<{
  modelValue: {
    resolutionMode: 'relative' | 'pixels'
    scaleFactor: number
    targetResolution: number
  }
  inputWidth: number
  inputHeight: number
  supportScaleFactor?: boolean
  supportResolution?: boolean
  scaleMin?: number
  scaleMax?: number
  scaleStep?: number
  /** Discrete legal factors. When set, only these are offered. */
  scaleAllowedValues?: number[] | null
}>(), {
  supportScaleFactor: true,
  supportResolution: true,
  scaleMin: 0.5,
  scaleMax: 4,
  scaleStep: 0.1,
  scaleAllowedValues: null,
})

const emit = defineEmits<{
  'update:modelValue': [typeof props.modelValue]
}>()

const RESOLUTION_MIN = 480
const RESOLUTION_MAX = 4320

/** Bare numbers: the header says px, so "2160p (4K)" is width spent on nothing. */
const PIXEL_PRESETS = [720, 1080, 1440, 2160, 4320]
const DEFAULT_SCALE_PRESETS = [1, 1.5, 2, 3, 4]

const mode = computed<'relative' | 'pixels'>(() => {
  if (props.supportScaleFactor && !props.supportResolution) return 'relative'
  if (props.supportResolution && !props.supportScaleFactor) return 'pixels'
  return props.modelValue.resolutionMode
})

/** Only worth a switch when the tool actually offers both. */
const showsModes = computed(() => props.supportScaleFactor && props.supportResolution)

const scalePresets = computed(() =>
  props.scaleAllowedValues?.length
    ? props.scaleAllowedValues
    : DEFAULT_SCALE_PRESETS.filter(s => s >= props.scaleMin && s <= props.scaleMax)
)

function set(patch: Partial<typeof props.modelValue>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

const value = computed(() =>
  mode.value === 'pixels' ? props.modelValue.targetResolution : props.modelValue.scaleFactor
)

const readout = computed(() =>
  mode.value === 'pixels' ? `${props.modelValue.targetResolution}px` : `${props.modelValue.scaleFactor}×`
)

const target = computed(() => {
  if (!props.inputWidth || !props.inputHeight) return null
  const scale = mode.value === 'pixels'
    ? props.modelValue.targetResolution / Math.min(props.inputWidth, props.inputHeight)
    : props.modelValue.scaleFactor
  return {
    width: Math.round(props.inputWidth * scale),
    height: Math.round(props.inputHeight * scale),
  }
})

// Same guard the wide control keeps: a factor carried in from another tool can
// be illegal for this one, and it must never be shown — or submitted — as if
// it were fine.
watch(
  () => [
    props.supportScaleFactor, props.scaleMin, props.scaleMax, props.scaleStep,
    props.scaleAllowedValues, props.modelValue.scaleFactor,
  ] as const,
  () => {
    if (!props.supportScaleFactor) return
    const legal = snapScaleFactor(
      {
        min: props.scaleMin,
        max: props.scaleMax,
        step: props.scaleStep,
        allowedValues: props.scaleAllowedValues ?? null,
      },
      props.modelValue.scaleFactor
    )
    if (legal !== props.modelValue.scaleFactor) set({ scaleFactor: legal })
  },
  { immediate: true }
)

// A tool that supports one mode only must not sit on the other one's value.
watch(
  () => [props.supportScaleFactor, props.supportResolution] as const,
  ([factor, pixels]) => {
    if (factor && !pixels && props.modelValue.resolutionMode !== 'relative') {
      set({ resolutionMode: 'relative' })
    } else if (pixels && !factor && props.modelValue.resolutionMode !== 'pixels') {
      set({ resolutionMode: 'pixels' })
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="space-y-2">
    <!-- The value belongs to the label, not to a row of its own. -->
    <div class="flex items-baseline justify-between gap-2">
      <span class="text-xs font-medium text-content-tertiary">
        {{ mode === 'pixels' ? 'Short edge' : 'Scale' }}
      </span>
      <span class="text-xs font-mono tabular-nums text-content-secondary">{{ readout }}</span>
    </div>

    <div v-if="showsModes" class="flex items-center rounded-md bg-overlay-light p-0.5 text-xs">
      <button
        type="button"
        class="flex-1 px-2 py-1 rounded transition-colors
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="mode === 'relative'
          ? 'bg-selection/15 text-content'
          : 'text-content-tertiary hover:text-content-secondary'"
        @click="set({ resolutionMode: 'relative' })"
      >
        Factor
      </button>
      <button
        type="button"
        class="flex-1 px-2 py-1 rounded transition-colors
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        title="Sets the shortest edge; aspect ratio is preserved"
        :class="mode === 'pixels'
          ? 'bg-selection/15 text-content'
          : 'text-content-tertiary hover:text-content-secondary'"
        @click="set({ resolutionMode: 'pixels' })"
      >
        Pixels
      </button>
    </div>

    <!-- Equal chips in one row that cannot wrap: the presets are how this gets
         set nine times out of ten, so they are the control, not a fallback
         behind a combo box. -->
    <div class="flex gap-1">
      <button
        v-for="preset in (mode === 'pixels' ? PIXEL_PRESETS : scalePresets)"
        :key="preset"
        type="button"
        class="flex-1 min-w-0 px-1 py-1 text-xs rounded-md tabular-nums transition-colors
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="value === preset
          ? 'bg-accent text-accent-on'
          : 'bg-overlay-subtle text-content-secondary hover:bg-overlay-light'"
        @click="mode === 'pixels'
          ? set({ targetResolution: preset })
          : set({ scaleFactor: preset })"
      >
        {{ mode === 'pixels' ? preset : `${preset}×` }}
      </button>
    </div>

    <!-- Fine adjustment under the presets it adjusts. Hidden for a tool with
         discrete factors, where an in-between value is not a legal thing to
         land on. -->
    <input
      v-if="mode === 'pixels' || !scaleAllowedValues"
      type="range"
      class="w-full h-1 bg-overlay-subtle rounded-full appearance-none cursor-pointer
             [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3
             [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full
             [&::-webkit-slider-thumb]:bg-accent"
      :min="mode === 'pixels' ? RESOLUTION_MIN : scaleMin"
      :max="mode === 'pixels' ? RESOLUTION_MAX : scaleMax"
      :step="mode === 'pixels' ? 1 : scaleStep"
      :value="value"
      @input="mode === 'pixels'
        ? set({ targetResolution: Number(($event.target as HTMLInputElement).value) })
        : set({ scaleFactor: Number(($event.target as HTMLInputElement).value) })"
    />

    <!-- The result, directly under what produced it. -->
    <p v-if="target" class="text-xs font-mono tabular-nums text-content-tertiary">
      {{ inputWidth }} × {{ inputHeight }}
      <span class="text-content-muted">→</span>
      <span class="text-accent">{{ target.width }} × {{ target.height }}</span>
    </p>
  </div>
</template>
