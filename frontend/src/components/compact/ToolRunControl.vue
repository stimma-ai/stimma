<script setup lang="ts">
/**
 * The tool view's Run on a phone: one 44px header control.
 *
 * Tap runs with the current batch size. Long-press opens the run sheet
 * (batch stepper, Forever mode toggle button, its two settings). Forever
 * armed: magenta ∞, tap stops. While jobs run the button stays a plain Run,
 * as on desktop: progress lives in the filmstrip, and a tap queues another
 * run. The badge shows the batch size, so ×4 is never a surprise. The sheet
 * has no Run button of its own: it is settings, and Run is the control you
 * long-pressed.
 */
import { computed, ref } from 'vue'
import Sheet from '../ui/Sheet.vue'

const props = withDefaults(defineProps<{
  batchSize: number
  canSubmit: boolean
  foreverActive: boolean
  concurrency: number
  idleLimit: number
  isMac?: boolean
}>(), { isMac: false })

const emit = defineEmits<{
  run: []
  'update:batchSize': [value: number]
  startForever: [concurrency: number]
  stopForever: []
  'update:concurrency': [value: number]
  'update:idleLimit': [value: number]
}>()

const sheetOpen = ref(false)
let pressTimer: number | null = null
let longPressed = false

function onPointerDown() {
  longPressed = false
  pressTimer = window.setTimeout(() => { longPressed = true; sheetOpen.value = true }, 450)
}
function cancelPress() {
  if (pressTimer !== null) { window.clearTimeout(pressTimer); pressTimer = null }
}
function onClick() {
  cancelPress()
  if (longPressed) { longPressed = false; return }
  if (props.foreverActive) { emit('stopForever'); return }
  if (props.canSubmit) emit('run')
}

const state = computed<'idle' | 'forever'>(() => (props.foreverActive ? 'forever' : 'idle'))

function step(delta: number) {
  const next = Math.min(50, Math.max(1, props.batchSize + delta))
  emit('update:batchSize', next)
}

function toggleForever() {
  if (props.foreverActive) emit('stopForever')
  else emit('startForever', props.concurrency)
}

const CONCURRENCY = [{ label: 'Unlimited', value: 0 }, ...Array.from({ length: 10 }, (_, i) => ({ label: String(i + 1), value: i + 1 }))]
const IDLE = [10, 20, 50, 100, 250, 500, 1000].map((n) => ({ label: `${n} images`, value: n })).concat([{ label: 'No limit', value: 0 }])
</script>

<template>
  <button
    type="button"
    data-testid="tool-run-button"
    class="relative w-11 h-11 rounded-[10px] flex items-center justify-center border-none transition-colors select-none"
    :class="[
      state === 'forever' ? 'bg-live text-white' : 'bg-accent text-white',
      !canSubmit && state === 'idle' ? 'opacity-45' : '',
    ]"
    :aria-label="state === 'forever' ? 'Stop forever mode' : `Run ×${batchSize}`"
    @pointerdown="onPointerDown"
    @pointerup="cancelPress"
    @pointerleave="cancelPress"
    @pointercancel="cancelPress"
    @contextmenu.prevent
    @click="onClick"
  >
    <svg v-if="state === 'forever'" class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16.5 8.5c-2 0-3.3 1.6-4.5 3.5s-2.5 3.5-4.5 3.5a3.5 3.5 0 0 1 0-7c2 0 3.3 1.6 4.5 3.5s2.5 3.5 4.5 3.5a3.5 3.5 0 0 0 0-7z" /></svg>
    <svg v-else class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l13 8-13 8z" /></svg>
    <span
      v-if="batchSize > 1"
      class="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-surface border border-edge text-[10.5px] font-mono flex items-center justify-center"
      :class="state === 'forever' ? 'text-live' : 'text-accent-hi'"
    >×{{ batchSize }}</span>
  </button>

  <Sheet :show="sheetOpen" title="Run" @close="sheetOpen = false">
    <div class="flex items-center justify-between px-4 min-h-14">
      <span class="text-[15px] text-content">Batch size</span>
      <div class="flex items-center rounded-md bg-overlay-subtle overflow-hidden">
        <button type="button" class="w-11 h-10 text-lg text-content-secondary border-none bg-transparent" aria-label="Fewer" @click="step(-1)">−</button>
        <span class="w-12 h-10 flex items-center justify-center font-mono text-[15px] text-content bg-surface">{{ batchSize }}</span>
        <button type="button" class="w-11 h-10 text-lg text-content-secondary border-none bg-transparent" aria-label="More" @click="step(1)">+</button>
      </div>
    </div>
    <div class="mx-4 my-1 border-t border-edge-subtle"></div>
    <div class="px-4 pt-2">
      <button
        type="button"
        class="w-full h-11 rounded-lg flex items-center justify-center gap-2 text-[14.5px] font-medium border-none transition-colors"
        :class="foreverActive ? 'bg-live/15 text-live ring-1 ring-live/40' : 'bg-overlay-subtle text-content'"
        :aria-pressed="foreverActive"
        @click="toggleForever"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16.5 8.5c-2 0-3.3 1.6-4.5 3.5s-2.5 3.5-4.5 3.5a3.5 3.5 0 0 1 0-7c2 0 3.3 1.6 4.5 3.5s2.5 3.5 4.5 3.5a3.5 3.5 0 0 0 0-7z" /></svg>
        Forever mode
      </button>
    </div>
    <label class="flex items-center justify-between px-4 min-h-12 mt-1">
      <span class="text-[15px] text-content">Max concurrent jobs</span>
      <select class="bg-overlay-subtle rounded-md px-3 py-2 text-sm font-mono text-content border border-transparent focus:border-accent outline-none min-h-11" :value="concurrency" @change="emit('update:concurrency', Number(($event.target as HTMLSelectElement).value))">
        <option v-for="o in CONCURRENCY" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
    </label>
    <label class="flex items-center justify-between px-4 min-h-12 pb-2">
      <span class="text-[15px] text-content">Auto-stop after</span>
      <select class="bg-overlay-subtle rounded-md px-3 py-2 text-sm font-mono text-content border border-transparent focus:border-accent outline-none min-h-11" :value="idleLimit" @change="emit('update:idleLimit', Number(($event.target as HTMLSelectElement).value))">
        <option v-for="o in IDLE" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
    </label>
  </Sheet>
</template>
