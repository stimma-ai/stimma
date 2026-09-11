<script setup lang="ts">
/**
 * The phone editor's dial: one parameter, the whole width, a ruler that
 * slides under a fixed needle (DESIGN.md §3.6a). A drag anywhere on it moves
 * the value by the drag's distance, never by jumping to the finger, so the
 * finger never has to land on a thumb; a double tap resets. The same
 * parameter is also driven by dragging on the picture, which is why this
 * reads a value it does not own: the host keeps the truth and passes it in.
 */
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{
  label: string
  value: number
  min: number
  max: number
  step?: number
  default?: number
  unit?: string
  /** A hue parameter: the ruler is a spectrum, no fill. */
  hue?: boolean
  disabled?: boolean
}>(), { step: 1, default: 0, unit: '', hue: false, disabled: false })

const emit = defineEmits<{
  /** Continuous, while dragging. */
  input: [number]
  /** The gesture ended. */
  commit: []
  reset: []
}>()

const TICK_PX = 6
const TICKS = 60
const range = computed(() => props.max - props.min)
const fraction = computed(() => range.value ? (props.value - props.min) / range.value : 0)
const zeroFraction = computed(() => props.min < 0 && props.max > 0 ? (0 - props.min) / range.value : 0)
const modified = computed(() => props.value !== props.default)
const rulerOffset = computed(() => -fraction.value * TICK_PX * TICKS)
const ticks = computed(() => Array.from({ length: TICKS + 1 }, (_, i) => {
  const at = props.min + range.value * i / TICKS
  const zero = props.min < 0 && Math.abs(at) < range.value / TICKS / 2
  return zero ? 'zero' : i % 5 === 0 ? 'big' : ''
}))
const fillStyle = computed(() => {
  const f = fraction.value, z = zeroFraction.value
  const a = (f - Math.min(f, z)) * TICK_PX * TICKS
  const b = (Math.max(f, z) - f) * TICK_PX * TICKS
  return { left: `calc(50% - ${a}px)`, width: `${a + b}px` }
})
const readout = computed(() => {
  const step = props.step
  const text = step < 1 ? props.value.toFixed(step < 0.1 ? 2 : 1) : String(Math.round(props.value))
  return (props.min < 0 && props.value > 0 ? '+' : '') + text + props.unit
})

const root = ref<HTMLElement | null>(null)
const dragging = ref(false)
let pointerId: number | null = null
let startX = 0
let startValue = 0
let moved = false
let lastTap = 0
function snap(value: number) {
  const step = props.step || 1
  return Math.min(props.max, Math.max(props.min, Math.round(value / step) * step))
}
function down(event: PointerEvent) {
  if (props.disabled || pointerId !== null || !event.isPrimary) return
  pointerId = event.pointerId
  root.value?.setPointerCapture(event.pointerId)
  startX = event.clientX
  startValue = props.value
  moved = false
  dragging.value = true
}
function move(event: PointerEvent) {
  if (pointerId !== event.pointerId) return
  const dx = event.clientX - startX
  if (Math.abs(dx) > 2) moved = true
  if (!moved) return
  event.preventDefault()
  emit('input', snap(startValue - dx / (TICK_PX * TICKS) * range.value))
}
function up(event: PointerEvent) {
  if (pointerId !== event.pointerId) return
  pointerId = null
  dragging.value = false
  const now = Date.now()
  if (!moved && now - lastTap < 320) { lastTap = 0; emit('reset'); return }
  lastTap = now
  if (moved) emit('commit')
}
</script>

<template>
  <div
    ref="root"
    class="relative h-[52px] -mx-3 px-3 overflow-hidden border-t border-edge-subtle select-none touch-pan-y cursor-ew-resize"
    :class="disabled && 'opacity-50'"
    role="slider"
    :aria-label="label"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :aria-valuenow="value"
    :aria-valuetext="readout"
    data-param-dial
    @pointerdown="down"
    @pointermove="move"
    @pointerup="up"
    @pointercancel="up"
  >
    <span class="absolute left-3.5 top-2 text-xs text-content-tertiary pointer-events-none">{{ label }}</span>
    <span
      class="absolute right-3.5 top-2 font-mono text-[13px] tabular-nums pointer-events-none"
      :class="modified ? 'text-accent-hi' : 'text-content-secondary'"
    >{{ readout }}</span>
    <template v-if="hue">
      <div
        class="absolute left-3 right-3 bottom-1.5 h-1.5 rounded-full pointer-events-none"
        style="background: linear-gradient(90deg, #f55, #ff5, #5f5, #5ff, #55f, #f5f, #f55)"
      />
    </template>
    <template v-else>
      <div
        class="absolute left-1/2 bottom-0 h-[22px] flex items-end gap-[5px] pointer-events-none will-change-transform"
        :style="{ transform: `translateX(${rulerOffset}px)` }"
      >
        <i
          v-for="(kind, index) in ticks"
          :key="index"
          class="block w-px shrink-0"
          :class="kind === 'zero' ? 'h-3.5 w-0.5 bg-accent' : kind === 'big' ? 'h-3 bg-content-tertiary' : 'h-[7px] bg-content-muted/60'"
        />
      </div>
      <div class="absolute bottom-0 h-0.5 bg-accent pointer-events-none" :style="fillStyle" />
    </template>
    <div
      class="absolute left-1/2 -translate-x-1/2 w-0.5 pointer-events-none"
      :class="[hue ? 'bottom-0.5 h-3.5' : 'bottom-0 h-[22px]', dragging ? 'bg-accent' : 'bg-content']"
    />
  </div>
</template>
