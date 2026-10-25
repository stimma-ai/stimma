<template>
  <!-- Touch: a visible chip in a 44px target. Tap opens the value sheet;
       nothing on a touch screen scrubs, because a finger that drifts while
       tapping (or starts near the screen edge) must never change the value. -->
  <span
    v-if="isCoarsePointer"
    ref="anchorRef"
    :class="[
      'inline-flex min-h-11 min-w-11 items-center justify-end select-none',
      disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
    ]"
    role="button"
    :tabindex="disabled ? -1 : 0"
    :aria-label="label ? `${label}: ${displayValue}` : undefined"
    :aria-disabled="disabled || undefined"
    @click.stop="!disabled && openPopover()"
  >
    <span
      class="h-8 min-w-[52px] px-2.5 rounded-md bg-overlay-subtle flex items-center justify-center text-[13px] font-mono tabular-nums"
      :class="nonDefault ? 'text-accent-hi' : 'text-content'"
    >{{ displayValue }}</span>
  </span>
  <span
    v-else
    ref="anchorRef"
    :class="[
      'text-xs font-mono tabular-nums text-right select-none touch-none',
      disabled ? 'opacity-40 cursor-not-allowed text-content-tertiary'
               : 'cursor-ew-resize ' + (nonDefault ? 'text-accent-hi hover:text-accent' : 'text-content-secondary hover:text-content'),
      open ? '!text-content' : '',
    ]"
    :title="disabled ? undefined : title || 'Drag to adjust · click to edit'"
    role="button"
    :tabindex="disabled ? -1 : 0"
    :aria-disabled="disabled || undefined"
    @keydown.enter.prevent="!disabled && openPopover()"
    @keydown.space.prevent="!disabled && openPopover()"
    @pointerdown="onPointerDown"
  >{{ displayValue }}</span>

  <!-- Touch editor: a kit sheet with the value large, −/+ (hold to repeat),
       a full-width slider with a finger-sized thumb, and reset. -->
  <Sheet v-if="isCoarsePointer" :show="open" :title="label" @close="closeSheet">
    <div class="px-4 pt-2 pb-4">
      <div class="flex items-center gap-3">
        <button
          type="button"
          class="w-12 h-12 flex-none rounded-lg bg-overlay-subtle text-content text-2xl leading-none flex items-center justify-center border-none disabled:opacity-40 touch-none select-none"
          aria-label="Decrease"
          :disabled="modelValue <= min"
          @pointerdown.prevent="startRepeat(-1)"
          @pointerup="stopRepeat" @pointerleave="stopRepeat" @pointercancel="stopRepeat"
          @contextmenu.prevent
        >−</button>
        <input
          ref="inputRef"
          :value="displayValue"
          type="text"
          inputmode="decimal"
          enterkeyhint="done"
          class="flex-1 min-w-0 h-12 text-center text-2xl font-mono tabular-nums bg-transparent border-b border-edge-subtle focus:border-accent outline-none rounded-none"
          :class="nonDefault ? 'text-accent-hi' : 'text-content'"
          @change="commitText"
          @keydown.enter="commitText($event); ($event.target as HTMLInputElement).blur()"
        />
        <button
          type="button"
          class="w-12 h-12 flex-none rounded-lg bg-overlay-subtle text-content text-2xl leading-none flex items-center justify-center border-none disabled:opacity-40 touch-none select-none"
          aria-label="Increase"
          :disabled="modelValue >= max"
          @pointerdown.prevent="startRepeat(1)"
          @pointerup="stopRepeat" @pointerleave="stopRepeat" @pointercancel="stopRepeat"
          @contextmenu.prevent
        >+</button>
      </div>
      <input
        type="range"
        :value="modelValue"
        :min="min" :max="max" :step="step"
        :aria-label="label || 'Value'"
        @input="emitClamped(Number(($event.target as HTMLInputElement).value))"
        @change="emit('commit')"
        class="value-sheet-slider block w-full h-11 mt-4 bg-transparent appearance-none cursor-pointer"
        :style="{ '--fill': `${fillPct}%` }"
      />
      <div class="flex justify-between text-[12px] font-mono tabular-nums text-content-muted">
        <span>{{ fmt(min) }}</span>
        <span>{{ fmt(max) }}</span>
      </div>
      <button
        v-if="defaultValue !== undefined"
        type="button"
        class="mt-3 w-full h-11 rounded-lg text-[14px] border-none transition-colors"
        :class="nonDefault ? 'bg-overlay-subtle text-content' : 'bg-transparent text-content-muted'"
        :disabled="!nonDefault"
        @click="emitClamped(defaultValue); emit('commit')"
      >Reset to {{ fmt(defaultValue) }}</button>
    </div>
  </Sheet>

  <!-- Editor popover: slider + text entry (click-to-open) -->
  <Teleport to="body">
    <template v-if="open && !isCoarsePointer">
      <div class="fixed inset-0 z-menu" @click="open = false" @contextmenu.prevent="open = false"></div>
      <div
        class="editor-picker fixed z-submenu w-64 bg-surface border border-edge-subtle rounded-lg shadow-lg p-3"
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
            @change="emit('commit')"
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
// scrub (4px/step), click to open a slider + text-entry popover. On a touch
// screen it is a tappable chip that opens a value sheet instead (no scrub).
import { computed, nextTick, onBeforeUnmount, ref, watchEffect } from 'vue'
import { useViewport } from '../../composables/useViewport'
import Sheet from './Sheet.vue'

const { isCoarsePointer } = useViewport()

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
  /** The parameter's name: the touch sheet's title. */
  label?: string
  /** Offers "Reset to …" in the touch sheet. */
  defaultValue?: number
}>(), { min: 0, max: 100, step: 1, disabled: false, nonDefault: false, label: '', defaultValue: undefined })

const emit = defineEmits<{
  (e: 'update:modelValue', v: number): void
  (e: 'commit'): void
}>()

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

const fillPct = computed(() => {
  const span = props.max - props.min
  return span > 0 ? ((props.modelValue - props.min) / span) * 100 : 0
})

// −/+ in the touch sheet: one step per tap, repeating while held.
let repeatTimer: number | null = null
let repeated = false
function startRepeat(dir: 1 | -1) {
  stopRepeat()
  repeated = true
  emitClamped(props.modelValue + dir * props.step)
  let delay = 380
  const tick = () => {
    // A held button that reaches the end of the range goes disabled and
    // never sees its pointerup, so the repeat stops itself there.
    if (clamp(props.modelValue + dir * props.step) === props.modelValue) { stopRepeat(); return }
    emitClamped(props.modelValue + dir * props.step)
    delay = Math.max(40, delay * 0.8)
    repeatTimer = window.setTimeout(tick, delay)
  }
  repeatTimer = window.setTimeout(tick, delay)
}
function stopRepeat() {
  if (repeatTimer !== null) { window.clearTimeout(repeatTimer); repeatTimer = null }
  if (repeated) { repeated = false; emit('commit') }
}
function closeSheet() {
  stopRepeat()
  open.value = false
}
onBeforeUnmount(stopRepeat)

function openPopover() {
  if (isCoarsePointer.value) { open.value = true; return }
  const r = anchorRef.value?.getBoundingClientRect()
  if (!r) return
  const W = 256, H = 64
  const left = Math.max(8, Math.min(window.innerWidth - W - 8, r.right - W))
  const top = r.bottom + H + 8 > window.innerHeight ? r.top - H - 8 : r.bottom + 6
  popoverStyle.value = { left: `${left}px`, top: `${top}px` }
  open.value = true
  nextTick(() => { if (!isCoarsePointer.value) inputRef.value?.select() })
}

// --- Drag to scrub; click (no movement) opens the editor ---------------------
const PX_PER_STEP = 4
function onPointerDown(e: PointerEvent) {
  if (props.disabled || !e.isPrimary || e.button !== 0) return
  const startX = e.clientX
  const startValue = props.modelValue
  let moved = false
  const el = e.target as HTMLElement
  el.setPointerCapture(e.pointerId)
  const onMove = (ev: PointerEvent) => {
    if (ev.pointerId !== e.pointerId) return
    const dx = ev.clientX - startX
    if (!moved && Math.abs(dx) < 3) return
    moved = true
    emitClamped(startValue + Math.round(dx / PX_PER_STEP) * props.step)
  }
  const onUp = (ev: PointerEvent) => {
    if (ev.pointerId !== e.pointerId) return
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
    el.removeEventListener('pointermove', onMove)
    el.removeEventListener('pointerup', onUp)
    el.removeEventListener('pointercancel', onUp)
    if (moved) emit('commit')
    else if (ev.type !== 'pointercancel') openPopover()
  }
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', onUp)
  el.addEventListener('pointercancel', onUp)
}

defineExpose({ openEditor: () => { if (!props.disabled) openPopover() } })

function commitText(e: Event) {
  const raw = (e.target as HTMLInputElement).value.replace(/[^\d.eE+-]/g, '')
  const num = Number(raw)
  if (!isNaN(num) && raw !== '') {
    emitClamped(num)
    emit('commit')
  }
}
</script>

<style scoped>
/* The touch sheet's slider: a 4px track that fills to the value and a 28px
   thumb, inside a 44px-tall input so the whole strip takes the finger. */
.value-sheet-slider::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 9999px;
  background: linear-gradient(to right, rgb(var(--color-accent-rgb)) var(--fill), rgb(255 255 255 / 0.12) var(--fill));
}
.value-sheet-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 28px;
  height: 28px;
  margin-top: -12px;
  border-radius: 9999px;
  background: rgb(var(--color-accent-rgb));
  box-shadow: 0 1px 4px rgb(0 0 0 / 0.5);
}
.value-sheet-slider::-moz-range-track {
  height: 4px;
  border-radius: 9999px;
  background: rgb(255 255 255 / 0.12);
}
.value-sheet-slider::-moz-range-progress {
  height: 4px;
  border-radius: 9999px;
  background: rgb(var(--color-accent-rgb));
}
.value-sheet-slider::-moz-range-thumb {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 9999px;
  background: rgb(var(--color-accent-rgb));
}
</style>
