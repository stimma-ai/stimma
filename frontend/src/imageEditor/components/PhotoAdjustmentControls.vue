<script setup lang="ts">
import type {
  AdjustControl,
  AdjustSliderControl,
  PhotoAdjustmentGroup,
  ToneCurve,
} from '../stack/adjustSections'
import type { ToneCurveHistogram } from '../stack/toneCurve'
import { toneCurveValueOf } from '../stack/adjustSections'
import ColorGradingControl from './ColorGradingControl.vue'
import HueMixerControl from './HueMixerControl.vue'
import PointColorControl from './PointColorControl.vue'
import ToneCurveControl from './ToneCurveControl.vue'

const props = defineProps<{
  controls: AdjustControl[]
  values: Record<string, any>
  histogram?: ToneCurveHistogram
  disabled?: boolean
  coalescePrefix: string
  /** A custom surface for the whole group; the keys stay plain sliders. */
  presentation?: PhotoAdjustmentGroup['presentation']
  /** Point color only: the canvas eyedropper is currently armed. */
  picking?: boolean
  clipShadows?: boolean
  clipHighlights?: boolean
}>()

const emit = defineEmits<{
  change: [Record<string, any>, string]
  commit: []
  /** Point color asks the host view to arm the canvas eyedropper. */
  pick: []
  clip: [{ shadows: boolean; highlights: boolean }]
}>()

function sliderValue(control: AdjustSliderControl) {
  const value = props.values?.[control.key]
  return typeof value === 'number' ? value : control.default
}

function curveValue(control: Extract<AdjustControl, { kind: 'curve' }>): ToneCurve {
  return toneCurveValueOf(props.values?.[control.key])
}

function setValue(key: string, value: number | ToneCurve) {
  emit('change', { [key]: value }, `${props.coalescePrefix}:${key}`)
}

function forwardChange(patch: Record<string, any>, coalesceKey: string) {
  emit('change', patch, `${props.coalescePrefix}:${coalesceKey}`)
}
</script>

<template>
  <HueMixerControl
    v-if="presentation === 'mixer'"
    :values="values"
    :disabled="disabled"
    @change="forwardChange"
    @commit="emit('commit')"
  />
  <PointColorControl
    v-else-if="presentation === 'point'"
    :values="values"
    :disabled="disabled"
    :picking="picking"
    @change="forwardChange"
    @commit="emit('commit')"
    @pick="emit('pick')"
  />
  <ColorGradingControl
    v-else-if="presentation === 'grade'"
    :values="values"
    :disabled="disabled"
    @change="forwardChange"
    @commit="emit('commit')"
  />
  <div v-else class="space-y-2">
    <template v-for="control in controls" :key="control.key">
      <ToneCurveControl
        v-if="control.kind === 'curve'"
        class="pt-1"
        :label="control.label"
        :value="curveValue(control)"
        :histogram="histogram"
        :disabled="disabled"
        :clip-shadows="clipShadows"
        :clip-highlights="clipHighlights"
        @input="setValue(control.key, $event)"
        @commit="emit('commit')"
        @clip="emit('clip', $event)"
      />
      <label
        v-else
        class="grid grid-cols-[88px_minmax(0,1fr)_32px] items-center gap-1.5 text-xs compact:grid-cols-[minmax(0,1fr)_auto]"
      >
        <span class="truncate text-content-tertiary compact:whitespace-normal compact:overflow-visible" :title="control.label">
          {{ control.label }}
        </span>
        <input
          type="range"
          class="min-w-0 compact:row-start-2 compact:col-span-2 compact:w-full compact:min-h-11"
          :min="control.min"
          :max="control.max"
          :step="control.step"
          :disabled="disabled"
          :value="sliderValue(control)"
          @input="setValue(
            control.key,
            Number(($event.target as HTMLInputElement).value),
          )"
          @change="emit('commit')"
        />
        <span class="text-right font-mono tabular-nums text-content-secondary">
          {{ sliderValue(control) }}
        </span>
      </label>
    </template>
  </div>
</template>
