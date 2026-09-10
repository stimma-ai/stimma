<script setup lang="ts">
/**
 * The four outpaint edges, always spelled out — Top, Bottom, Left, Right.
 *
 * Each value is a ScrubValue: drag to scrub, click for the slider popover,
 * the same control grammar as every schema parameter in ToolView. The unit
 * toggle is display-only sugar — the canonical value is ALWAYS the integer
 * percent the contract defines, and pixel mode shows the exact pixels that
 * percent will produce (`floor(axis·pct/100)`), quantized to it, so the
 * number on screen is always the number the tool returns.
 */
import { computed, ref } from 'vue'
import ScrubValue from '../../components/ui/ScrubValue.vue'
import type { ExpandEdges } from '../stack/expandGeometry'
import { hasExpansion } from '../stack/expandGeometry'

const props = defineProps<{
  edges: ExpandEdges
  frameWidth: number
  frameHeight: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  update: [ExpandEdges]
}>()

const unit = ref<'percent' | 'pixels'>('percent')

const FIELDS: Array<{ edge: keyof ExpandEdges; label: string; axis: 'width' | 'height' }> = [
  { edge: 'top', label: 'Top', axis: 'height' },
  { edge: 'bottom', label: 'Bottom', axis: 'height' },
  { edge: 'left', label: 'Left', axis: 'width' },
  { edge: 'right', label: 'Right', axis: 'width' },
]

function axisSize(axis: 'width' | 'height'): number {
  return Math.max(1, axis === 'width' ? props.frameWidth : props.frameHeight)
}

function clampPct(value: number): number {
  const n = Math.floor(Number(value))
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0
}

/** What the ScrubValue holds in the current unit. */
function displayValue(field: (typeof FIELDS)[number]): number {
  const pct = props.edges[field.edge]
  if (unit.value === 'percent') return pct
  return Math.floor((axisSize(field.axis) * pct) / 100)
}

function setEdge(field: (typeof FIELDS)[number], value: number) {
  const pct = unit.value === 'percent'
    ? clampPct(value)
    : clampPct(Math.round((Number(value) * 100) / axisSize(field.axis)))
  emit('update', { ...props.edges, [field.edge]: pct })
}

/** One percent of the axis, so pixel scrubbing moves in real increments. */
function pixelStep(field: (typeof FIELDS)[number]): number {
  return Math.max(1, Math.round(axisSize(field.axis) / 100))
}

const changed = computed(() => hasExpansion(props.edges))
</script>

<template>
  <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
    <!-- 2×2 or 1×4 by the BAR's width (container query), not the viewport's:
         with the resizable sidebar next door the two are unrelated. -->
    <div class="grid grid-cols-2 gap-x-3 gap-y-1 @2xl:grid-cols-4 compact:w-full compact:gap-x-4">
      <label
        v-for="field in FIELDS"
        :key="field.edge"
        class="grid items-center text-xs text-content-tertiary compact:!grid-cols-[minmax(0,1fr)_auto] compact:gap-2"
        :class="unit === 'percent'
          ? 'grid-cols-[3.25rem_2rem]'
          : 'grid-cols-[3.25rem_3.5rem]'"
        :title="`New canvas on the ${field.edge} edge`"
      >
        <span>{{ field.label }}</span>
        <span class="text-right">
          <ScrubValue
            :model-value="displayValue(field)"
            :min="0"
            :max="unit === 'percent' ? 100 : axisSize(field.axis)"
            :step="unit === 'percent' ? 1 : pixelStep(field)"
            :disabled="disabled"
            :non-default="edges[field.edge] > 0"
            :format="v => unit === 'percent' ? `${v}%` : `${v}px`"
            @update:model-value="setEdge(field, $event)"
          />
        </span>
      </label>
    </div>

    <div class="flex shrink-0 items-center gap-3">
      <!-- Display unit only: the wire always carries the percents. -->
      <div class="flex items-center rounded-md bg-overlay-subtle p-0.5 text-[11px]">
        <button
          v-for="choice in (['percent', 'pixels'] as const)"
          :key="choice"
          type="button"
          class="px-1.5 py-0.5 rounded transition-colors
                 focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="unit === choice
            ? 'bg-selection/15 text-content'
            : 'text-content-tertiary hover:text-content-secondary'"
          @click="unit = choice"
        >
          {{ choice === 'percent' ? '%' : 'px' }}
        </button>
      </div>

      <!-- Present only when modified, inline with the values and unit toggle. -->
      <button
        v-if="changed"
        type="button"
        class="text-[11px] text-content-tertiary hover:text-content transition-colors
               disabled:opacity-40 disabled:hover:text-content-tertiary disabled:cursor-default
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60 rounded-md"
        :disabled="disabled"
        @click="emit('update', { top: 0, bottom: 0, left: 0, right: 0 })"
      >
        Reset
      </button>
    </div>
  </div>
</template>
