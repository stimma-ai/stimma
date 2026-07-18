<template>
  <input
    v-if="editing"
    ref="inputRef"
    :value="displayValue"
    type="text"
    class="w-16 text-sm font-mono tabular-nums text-content bg-overlay-subtle border border-transparent rounded-md px-2 py-0.5 text-right focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none"
    @blur="commit"
    @keydown.enter="commit"
    @keydown.escape="editing = false"
  />
  <span
    v-else
    :class="[
      'text-sm font-mono tabular-nums text-right select-none',
      disabled ? 'opacity-40 cursor-not-allowed text-content-tertiary'
               : 'cursor-ew-resize ' + (nonDefault ? 'text-accent-hi hover:text-accent' : 'text-content-secondary hover:text-content'),
    ]"
    :title="disabled ? undefined : title || 'Drag to adjust · click to type'"
    @pointerdown="onPointerDown"
  >{{ displayValue }}</span>
</template>

<script setup lang="ts">
// Atelier ScrubValue — the mock's param interaction: a mono value you drag
// horizontally to adjust (4px per step) or click to type. Replaces sliders
// in compact value rows; the full range stays reachable by typing.
import { nextTick, ref } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: number
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  /** Colored accent when the value differs from its default. */
  nonDefault?: boolean
  /** Custom display formatting (e.g. percent, seconds). */
  format?: (v: number) => string
  title?: string
}>(), { min: 0, max: 100, step: 1, disabled: false, nonDefault: false })

const emit = defineEmits<{ (e: 'update:modelValue', v: number): void }>()

const editing = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)

const displayValue = ref('')
function fmt(v: number): string {
  if (props.format) return props.format(v)
  const step = props.step
  if (step < 1) {
    const decimals = step.toString().split('.')[1]?.length || 1
    return Number(v).toFixed(decimals)
  }
  return String(v)
}
// Keep display in sync (simple function call in template would also work,
// but we snapshot for the edit field).
import { computed, watchEffect } from 'vue'
watchEffect(() => { displayValue.value = fmt(props.modelValue) })

function clamp(v: number): number {
  const c = Math.max(props.min, Math.min(props.max, v))
  return props.step >= 1 ? Math.round(c / props.step) * props.step : Math.round(c / props.step) * props.step
}

// --- Drag to scrub ----------------------------------------------------------
const PX_PER_STEP = 4
let startX = 0
let startValue = 0
let moved = false

function onPointerDown(e: PointerEvent) {
  if (props.disabled) return
  startX = e.clientX
  startValue = props.modelValue
  moved = false
  const el = e.target as HTMLElement
  el.setPointerCapture(e.pointerId)
  const onMove = (ev: PointerEvent) => {
    const dx = ev.clientX - startX
    if (!moved && Math.abs(dx) < 3) return
    moved = true
    const next = clamp(startValue + Math.round(dx / PX_PER_STEP) * props.step)
    if (next !== props.modelValue) emit('update:modelValue', next)
  }
  const onUp = (ev: PointerEvent) => {
    el.releasePointerCapture(e.pointerId)
    el.removeEventListener('pointermove', onMove)
    el.removeEventListener('pointerup', onUp)
    if (!moved) {
      editing.value = true
      nextTick(() => { inputRef.value?.focus(); inputRef.value?.select() })
    }
  }
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', onUp)
}

function commit(e: Event) {
  const raw = (e.target as HTMLInputElement).value.replace(/[^\d.eE+-]/g, '')
  const num = Number(raw)
  if (!isNaN(num) && raw !== '') emit('update:modelValue', clamp(num))
  editing.value = false
}
</script>
