<template>
  <span
    ref="anchorRef"
    :class="[
      'text-xs font-mono tabular-nums text-right select-none',
      disabled ? 'opacity-40 cursor-not-allowed text-content-tertiary'
               : 'cursor-ew-resize ' + (nonDefault ? 'text-accent-hi hover:text-accent' : 'text-content-secondary hover:text-content'),
      open ? '!text-content' : '',
    ]"
    :title="disabled ? undefined : title || 'Drag to adjust · click to edit'"
    @pointerdown="onPointerDown"
  >{{ displayValue }}</span>

  <!-- Editor popover: slider + text entry (click-to-open) -->
  <Teleport to="body">
    <template v-if="open">
      <div class="fixed inset-0 z-menu" @click="open = false" @contextmenu.prevent="open = false"></div>
      <div
        class="fixed z-submenu w-64 bg-surface border border-edge-subtle rounded-lg shadow-lg p-3"
        :style="popoverStyle"
        @keydown.escape.stop="open = false"
      >
        <div class="flex items-center gap-2.5">
          <input
            ref="sliderRef"
            type="range"
            :value="modelValue"
            :min="min" :max="max" :step="step"
            @input="emitClamped(Number(($event.target as HTMLInputElement).value))"
            class="flex-1 h-1 bg-overlay-subtle rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-accent [&::-moz-range-thumb]:border-0"
          />
          <input
            ref="inputRef"
            :value="displayValue"
            type="text"
            class="w-16 text-xs font-mono tabular-nums text-content bg-overlay-subtle border border-transparent rounded-md px-2 py-1 text-right focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none"
            @change="commitText"
            @keydown.enter="commitText($event); open = false"
          />
        </div>
        <div class="flex justify-between mt-1.5 text-[10px] font-mono tabular-nums text-content-muted">
          <span>{{ fmt(min) }}</span>
          <span>{{ fmt(max) }}</span>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<script setup lang="ts">
// Atelier ScrubValue — compact mono value in the row; drag horizontally to
// scrub (4px/step), click to open a slider + text-entry popover.
import { computed, nextTick, ref, watchEffect } from 'vue'

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

const open = ref(false)
const anchorRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const sliderRef = ref<HTMLInputElement | null>(null)
const popoverStyle = ref<Record<string, string>>({})

function fmt(v: number): string {
  if (props.format) return props.format(v)
  const step = props.step
  if (step < 1) {
    const decimals = step.toString().split('.')[1]?.length || 1
    return Number(v).toFixed(decimals)
  }
  return String(v)
}
const displayValue = ref('')
watchEffect(() => { displayValue.value = fmt(props.modelValue) })

function clamp(v: number): number {
  const c = Math.max(props.min, Math.min(props.max, v))
  return Math.round(c / props.step) * props.step
}
function emitClamped(v: number) {
  const next = clamp(v)
  if (next !== props.modelValue) emit('update:modelValue', next)
}

function openPopover() {
  const r = anchorRef.value?.getBoundingClientRect()
  if (!r) return
  const W = 256, H = 64
  const left = Math.max(8, Math.min(window.innerWidth - W - 8, r.right - W))
  const top = r.bottom + H + 8 > window.innerHeight ? r.top - H - 8 : r.bottom + 6
  popoverStyle.value = { left: `${left}px`, top: `${top}px` }
  open.value = true
  nextTick(() => inputRef.value?.select())
}

// --- Drag to scrub; click (no movement) opens the editor ---------------------
const PX_PER_STEP = 4
function onPointerDown(e: PointerEvent) {
  if (props.disabled) return
  const startX = e.clientX
  const startValue = props.modelValue
  let moved = false
  const el = e.target as HTMLElement
  el.setPointerCapture(e.pointerId)
  const onMove = (ev: PointerEvent) => {
    const dx = ev.clientX - startX
    if (!moved && Math.abs(dx) < 3) return
    moved = true
    emitClamped(startValue + Math.round(dx / PX_PER_STEP) * props.step)
  }
  const onUp = () => {
    el.releasePointerCapture(e.pointerId)
    el.removeEventListener('pointermove', onMove)
    el.removeEventListener('pointerup', onUp)
    if (!moved) openPopover()
  }
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', onUp)
}

function commitText(e: Event) {
  const raw = (e.target as HTMLInputElement).value.replace(/[^\d.eE+-]/g, '')
  const num = Number(raw)
  if (!isNaN(num) && raw !== '') emitClamped(num)
}
</script>
