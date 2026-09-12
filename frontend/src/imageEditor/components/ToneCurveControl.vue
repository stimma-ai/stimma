<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  TONE_CURVE_CHANNELS,
  TONE_CURVE_PRESETS,
  defaultToneCurve,
  toneCurvePointValue,
  toneCurveValueOf,
  type ToneCurve,
  type ToneCurveChannel,
  type ToneCurveHistogram,
  type ToneCurvePoint,
} from '../stack/toneCurve'

const props = defineProps<{
  value?: ToneCurve | null
  histogram?: ToneCurveHistogram
  disabled?: boolean
  label?: string
  /** Clipping overlays on the canvas — workspace state owned by the view. */
  clipShadows?: boolean
  clipHighlights?: boolean
  /** The host owns the channel (the phone's row picks it). */
  channel?: ToneCurveChannel
  /**
   * Just the plot, as wide as its host allows: the phone gives the curve a
   * level of its own, with the channels, presets and reset in the row.
   */
  plotOnly?: boolean
}>()

const emit = defineEmits<{
  input: [ToneCurve]
  commit: []
  clip: [{ shadows: boolean; highlights: boolean }]
}>()

function toggleClip(edge: 'shadows' | 'highlights') {
  emit('clip', {
    shadows: edge === 'shadows' ? !props.clipShadows : !!props.clipShadows,
    highlights: edge === 'highlights' ? !props.clipHighlights : !!props.clipHighlights,
  })
}

const plot = ref<HTMLDivElement | null>(null)
const channelRef = ref<ToneCurveChannel>('rgb')
const channel = computed(() => props.channel ?? channelRef.value)
const selectedIndex = ref<number | null>(null)
const dragging = ref<number | null>(null)

const curve = computed(() => toneCurveValueOf(props.value))
const points = computed(() => curve.value[channel.value])
const selectedPoint = computed(() =>
  selectedIndex.value === null ? null : points.value[selectedIndex.value] ?? null,
)

watch(channel, () => {
  selectedIndex.value = null
  dragging.value = null
})

const CHANNEL_LABELS: Record<ToneCurveChannel, string> = {
  rgb: 'RGB',
  red: 'Red',
  green: 'Green',
  blue: 'Blue',
}

const CHANNEL_TEXT: Record<ToneCurveChannel, string> = {
  rgb: 'text-content',
  red: 'text-red-400',
  green: 'text-green-400',
  blue: 'text-blue-400',
}

const CHANNEL_STROKE: Record<ToneCurveChannel, string> = {
  rgb: 'text-content',
  red: 'text-red-400',
  green: 'text-green-400',
  blue: 'text-blue-400',
}

const PRESETS: Record<string, ToneCurvePoint[]> = TONE_CURVE_PRESETS

function cloneCurve(): ToneCurve {
  const source = curve.value
  return Object.fromEntries(
    TONE_CURVE_CHANNELS.map(key => [
      key,
      source[key].map(point => [...point]),
    ]),
  ) as ToneCurve
}

function emitPoints(nextPoints: ToneCurvePoint[], commit = false) {
  if (props.disabled) return
  const next = cloneCurve()
  next[channel.value] = nextPoints
    .map(point => [
      Math.max(0, Math.min(1, point[0])),
      Math.max(0, Math.min(1, point[1])),
    ] as ToneCurvePoint)
    .sort((a, b) => a[0] - b[0])
  next[channel.value][0][0] = 0
  next[channel.value][next[channel.value].length - 1][0] = 1
  emit('input', next)
  if (commit) emit('commit')
}

function curvePath(curvePoints: ToneCurvePoint[]) {
  return Array.from({ length: 97 }, (_, index) => {
    const x = index / 96
    const y = toneCurvePointValue(x, curvePoints)
    return `${index === 0 ? 'M' : 'L'} ${x * 100} ${(1 - y) * 100}`
  }).join(' ')
}

const activePath = computed(() => curvePath(points.value))
const inactivePaths = computed(() =>
  TONE_CURVE_CHANNELS
    .filter(key => key !== channel.value)
    .map(key => ({ channel: key, path: curvePath(curve.value[key]) })),
)

function histogramPath(values?: number[]) {
  if (!values?.length) return ''
  const body = values.map((value, index) => {
    const x = values.length === 1 ? 0 : index / (values.length - 1) * 100
    return `L ${x} ${(1 - value) * 100}`
  }).join(' ')
  return `M 0 100 ${body} L 100 100 Z`
}

function pointerPosition(event: PointerEvent) {
  const rect = plot.value?.getBoundingClientRect()
  if (!rect?.width || !rect.height) return { x: 0, y: 0 }
  return {
    x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    y: Math.max(0, Math.min(1, 1 - (event.clientY - rect.top) / rect.height)),
  }
}

/**
 * The phone drawer scrolls its body; a point drag that runs to the plot's
 * edge must not turn into a scroll. The plot is touch-none, and for good
 * measure the scrolling ancestor is frozen for the length of the drag.
 */
let frozenScroller: HTMLElement | null = null
function freezeScroller() {
  const scroller = plot.value?.closest<HTMLElement>('#editor-drawer-body') ?? null
  if (!scroller) return
  frozenScroller = scroller
  scroller.style.overflowY = 'hidden'
}
function releaseScroller() {
  if (!frozenScroller) return
  frozenScroller.style.overflowY = ''
  frozenScroller = null
}

function startPoint(event: PointerEvent, index: number) {
  if (props.disabled) return
  selectedIndex.value = index
  dragging.value = index
  plot.value?.setPointerCapture(event.pointerId)
  freezeScroller()
  event.preventDefault()
  event.stopPropagation()
}

function addPoint(event: PointerEvent) {
  if (props.disabled || points.value.length >= 16) return
  const position = pointerPosition(event)
  if (position.x < 0.015 || position.x > 0.985) return
  const next = points.value.map(point => [...point] as ToneCurvePoint)
  next.push([position.x, position.y])
  next.sort((a, b) => a[0] - b[0])
  const index = next.findIndex(point => point[0] === position.x)
  selectedIndex.value = index
  dragging.value = index
  plot.value?.setPointerCapture(event.pointerId)
  freezeScroller()
  emitPoints(next)
  event.preventDefault()
}

function movePoint(event: PointerEvent) {
  if (dragging.value === null) return
  const index = dragging.value
  const position = pointerPosition(event)
  const next = points.value.map(point => [...point] as ToneCurvePoint)
  const minimum = index === 0 ? 0 : next[index - 1][0] + 0.01
  const maximum = index === next.length - 1 ? 1 : next[index + 1][0] - 0.01
  next[index] = [
    index === 0 || index === next.length - 1
      ? next[index][0]
      : Math.max(minimum, Math.min(maximum, position.x)),
    position.y,
  ]
  emitPoints(next)
}

function finishPoint(event: PointerEvent) {
  releaseScroller()
  if (dragging.value === null) return
  movePoint(event)
  dragging.value = null
  emit('commit')
  if (plot.value?.hasPointerCapture(event.pointerId)) {
    plot.value.releasePointerCapture(event.pointerId)
  }
}

function removePoint(index = selectedIndex.value) {
  if (props.disabled || index === null || index === 0 || index === points.value.length - 1) return
  const next = points.value
    .filter((_, pointIndex) => pointIndex !== index)
    .map(point => [...point] as ToneCurvePoint)
  selectedIndex.value = null
  emitPoints(next, true)
}

function keyboardPoint(event: KeyboardEvent, index: number) {
  if (event.key === 'Delete' || event.key === 'Backspace') {
    removePoint(index)
    event.preventDefault()
    return
  }
  const point = points.value[index]
  const increment = event.shiftKey ? 5 / 255 : 1 / 255
  let x = point[0]
  let y = point[1]
  if (event.key === 'ArrowUp') y += increment
  else if (event.key === 'ArrowDown') y -= increment
  else if (event.key === 'ArrowRight') x += increment
  else if (event.key === 'ArrowLeft') x -= increment
  else return

  const next = points.value.map(candidate => [...candidate] as ToneCurvePoint)
  const minimum = index === 0 ? 0 : next[index - 1][0] + 0.01
  const maximum = index === next.length - 1 ? 1 : next[index + 1][0] - 0.01
  next[index] = [
    index === 0 || index === next.length - 1
      ? point[0]
      : Math.max(minimum, Math.min(maximum, x)),
    Math.max(0, Math.min(1, y)),
  ]
  emitPoints(next, true)
  event.preventDefault()
}

function setSelectedCoordinate(axis: 0 | 1, raw: string) {
  if (selectedIndex.value === null) return
  const value = Math.max(0, Math.min(255, Number(raw))) / 255
  const index = selectedIndex.value
  const next = points.value.map(point => [...point] as ToneCurvePoint)
  if (axis === 0 && index !== 0 && index !== next.length - 1) {
    next[index][0] = Math.max(
      next[index - 1][0] + 0.01,
      Math.min(next[index + 1][0] - 0.01, value),
    )
  } else if (axis === 1) {
    next[index][1] = value
  }
  emitPoints(next, true)
}

function applyPreset(preset: string) {
  const selected = PRESETS[preset]
  if (!selected) return
  selectedIndex.value = null
  emitPoints(selected.map(point => [...point]), true)
}

function reset() {
  if (props.disabled) return
  selectedIndex.value = null
  emit('input', defaultToneCurve())
  emit('commit')
}
</script>

<template>
  <div class="space-y-2.5">
    <div v-if="!plotOnly" class="flex items-center justify-between gap-2">
      <span class="text-xs font-semibold text-content-secondary">
        {{ label ?? 'Tone curve' }}
      </span>
      <button
        type="button"
        class="rounded-md px-2 py-1 text-[11px] text-content-tertiary
               hover:bg-overlay-subtle hover:text-content transition-colors duration-150
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60
               disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="disabled"
        @click="reset"
      >
        Reset
      </button>
    </div>

    <!-- The plot is capped, so the rows that belong to it are capped with it —
         a narrow graph between full-width rows reads as a mistake. -->
    <div class="mx-auto w-full space-y-2.5" :class="plotOnly ? 'max-w-[40vh]' : 'max-w-[264px]'">
      <div v-if="!plotOnly" class="grid grid-cols-[minmax(0,1fr)_32px] items-center gap-1.5">
        <div
          class="grid min-w-0 grid-cols-4 items-center gap-1"
          role="radiogroup"
          aria-label="Curve channel"
        >
          <button
            v-for="option in TONE_CURVE_CHANNELS"
            :key="option"
            type="button"
            class="min-w-0 rounded-md px-1.5 py-1 text-[11px] font-medium
                   transition-colors duration-150
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            :class="[
              CHANNEL_TEXT[option],
              channel === option ? 'bg-selection/15' : 'text-content-tertiary hover:bg-overlay-subtle',
            ]"
            :aria-checked="channel === option"
            role="radio"
            @click="channelRef = option"
          >
            {{ CHANNEL_LABELS[option] }}
          </button>
        </div>

        <span
          class="relative block h-7 w-8 rounded-md bg-surface-raised
                 focus-within:ring-2 ring-accent/60"
          title="Curve presets"
        >
          <select
            class="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0
                   focus-visible:outline-none disabled:cursor-not-allowed"
            aria-label="Curve presets"
            :disabled="disabled"
            value=""
            @change="applyPreset(($event.target as HTMLSelectElement).value);
                     ($event.target as HTMLSelectElement).value = ''"
          >
            <option value="" disabled class="text-content-secondary">Curve presets</option>
            <option value="linear" class="text-content-secondary">Linear</option>
            <option value="medium" class="text-content-secondary">Medium contrast</option>
            <option value="strong" class="text-content-secondary">Strong contrast</option>
          </select>
          <svg
            viewBox="0 0 20 20"
            fill="none"
            class="pointer-events-none absolute left-1/2 top-1/2 h-4 w-4
                   -translate-x-1/2 -translate-y-1/2 text-content-tertiary"
            aria-hidden="true"
          >
            <path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      </div>

      <!-- Square by construction: input and output share the 0–255 scale, so the
           identity diagonal has to read at 45°. -->
      <div class="w-full aspect-square rounded-md bg-matte p-2">
        <div
          ref="plot"
          class="tone-curve-plot relative h-full w-full cursor-crosshair touch-none"
          role="group"
          :aria-label="`${CHANNEL_LABELS[channel]} ${label ?? 'tone curve'}`"
          @pointerdown="addPoint"
          @pointermove="movePoint"
          @pointerup="finishPoint"
          @pointercancel="finishPoint"
        >
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            class="pointer-events-none absolute inset-0 h-full w-full"
            aria-hidden="true"
          >
            <path
              d="M 25 0 V 100 M 50 0 V 100 M 75 0 V 100 M 0 25 H 100 M 0 50 H 100 M 0 75 H 100"
              fill="none"
              stroke="currentColor"
              stroke-width="0.5"
              class="text-edge-subtle"
              vector-effect="non-scaling-stroke"
            />

            <path
              v-if="histogram"
              :d="histogramPath(histogram.luminance)"
              fill="currentColor"
              class="text-content-muted opacity-25"
            />
            <path
              v-if="histogram"
              :d="histogramPath(histogram.red)"
              fill="currentColor"
              class="text-red-400 opacity-10"
            />
            <path
              v-if="histogram"
              :d="histogramPath(histogram.green)"
              fill="currentColor"
              class="text-green-400 opacity-10"
            />
            <path
              v-if="histogram"
              :d="histogramPath(histogram.blue)"
              fill="currentColor"
              class="text-blue-400 opacity-10"
            />

            <path
              d="M 0 100 L 100 0"
              fill="none"
              stroke="currentColor"
              stroke-width="0.75"
              stroke-dasharray="3 3"
              class="text-content-muted opacity-70"
              vector-effect="non-scaling-stroke"
            />

            <path
              v-for="inactive in inactivePaths"
              :key="inactive.channel"
              :d="inactive.path"
              fill="none"
              stroke="currentColor"
              stroke-width="0.75"
              class="text-content-muted opacity-25"
              vector-effect="non-scaling-stroke"
            />
            <path
              :d="activePath"
              fill="none"
              stroke="currentColor"
              stroke-width="1.75"
              :class="CHANNEL_STROKE[channel]"
              vector-effect="non-scaling-stroke"
            />
          </svg>

          <!-- Clipping indicators: the histogram is already the tonal read-out,
               so its corners carry the warnings — shadows left, highlights
               right — toggling overlays on the canvas itself. -->
          <button
            type="button"
            class="absolute left-0 top-0 grid h-5 w-5 place-items-center rounded-md
                   compact:-left-3 compact:-top-3 compact:h-11 compact:w-11
                   transition-colors duration-150
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            :class="clipShadows
              ? 'text-blue-400'
              : 'text-content-muted hover:bg-overlay-subtle hover:text-content-tertiary'"
            :aria-pressed="clipShadows"
            aria-label="Show shadow clipping"
            title="Show shadow clipping"
            @pointerdown.stop
            @click.stop="toggleClip('shadows')"
          >
            <svg viewBox="0 0 10 10" class="h-2 w-2" aria-hidden="true">
              <path d="M5 1 L9 8 H1 Z" fill="currentColor" />
            </svg>
          </button>
          <button
            type="button"
            class="absolute right-0 top-0 grid h-5 w-5 place-items-center rounded-md
                   compact:-right-3 compact:-top-3 compact:h-11 compact:w-11
                   transition-colors duration-150
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            :class="clipHighlights
              ? 'text-red-400'
              : 'text-content-muted hover:bg-overlay-subtle hover:text-content-tertiary'"
            :aria-pressed="clipHighlights"
            aria-label="Show highlight clipping"
            title="Show highlight clipping"
            @pointerdown.stop
            @click.stop="toggleClip('highlights')"
          >
            <svg viewBox="0 0 10 10" class="h-2 w-2" aria-hidden="true">
              <path d="M5 1 L9 8 H1 Z" fill="currentColor" />
            </svg>
          </button>

          <button
            v-for="(point, index) in points"
            :key="`${channel}:${index}`"
            type="button"
            class="absolute grid h-3 w-3 -translate-x-1/2 -translate-y-1/2 place-items-center
                   cursor-move rounded-full border-0 bg-transparent
                   compact:h-11 compact:w-11
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60
                   ring-offset-1 ring-offset-matte
                   disabled:cursor-not-allowed disabled:opacity-50"
            :style="{ left: `${point[0] * 100}%`, top: `${(1 - point[1]) * 100}%` }"
            :disabled="disabled"
            role="slider"
            aria-valuemin="0"
            aria-valuemax="255"
            :aria-valuenow="Math.round(point[1] * 255)"
            :aria-label="`${CHANNEL_LABELS[channel]} curve point ${index + 1}`"
            @pointerdown="startPoint($event, index)"
            @dblclick.stop="removePoint(index)"
            @keydown="keyboardPoint($event, index)"
          >
            <span
              class="block h-3 w-3 rounded-full border-2 bg-matte transition-colors duration-150"
              :class="[
                channel === 'rgb' ? 'border-content' :
                  channel === 'red' ? 'border-red-400' :
                    channel === 'green' ? 'border-green-400' : 'border-blue-400',
                selectedIndex === index && (
                  channel === 'rgb' ? 'bg-content' :
                    channel === 'red' ? 'bg-red-400' :
                      channel === 'green' ? 'bg-green-400' : 'bg-blue-400'
                ),
              ]"
              aria-hidden="true"
            />
          </button>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-2">
        <label class="grid grid-cols-[auto_1fr] items-center gap-1.5 text-[11px]">
          <span class="text-content-tertiary">Input</span>
          <input
            type="number"
            min="0"
            max="255"
            step="1"
            :disabled="disabled || !selectedPoint || selectedIndex === 0 || selectedIndex === points.length - 1"
            :value="selectedPoint ? Math.round(selectedPoint[0] * 255) : ''"
            class="min-w-0 rounded-md bg-surface-raised px-2 py-1 text-right
                   font-mono tabular-nums text-content-secondary
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60
                   disabled:opacity-40"
            @change="setSelectedCoordinate(0, ($event.target as HTMLInputElement).value)"
          />
        </label>
        <label class="grid grid-cols-[auto_1fr] items-center gap-1.5 text-[11px]">
          <span class="text-content-tertiary">Output</span>
          <input
            type="number"
            min="0"
            max="255"
            step="1"
            :disabled="disabled || !selectedPoint"
            :value="selectedPoint ? Math.round(selectedPoint[1] * 255) : ''"
            class="min-w-0 rounded-md bg-surface-raised px-2 py-1 text-right
                   font-mono tabular-nums text-content-secondary
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60
                   disabled:opacity-40"
            @change="setSelectedCoordinate(1, ($event.target as HTMLInputElement).value)"
          />
        </label>
      </div>

      <p class="text-[11px] text-content-tertiary">
        Click the graph to add a point. Double-click a point to remove it.
      </p>
    </div>
  </div>
</template>
