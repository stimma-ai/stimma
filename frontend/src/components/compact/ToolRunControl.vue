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
 * long-pressed. In the phone drawer it also carries the output settings
 * (auto-markers, auto-delete), which have no room beside the controls; a small
 * settings glyph inside Run's fill says one of them is on, and the controls area shows
 * the state on the Every new output row, whose delete button opens this sheet. Easter egg: a double tap starts Forever
 * mode (the first tap has already run, so that batch still goes).
 */
import { computed, ref } from 'vue'
import Sheet from '../ui/Sheet.vue'
import AutoMarkPicker from '../generation/AutoMarkPicker.vue'
import { AUTO_DELETE_OPTIONS } from '../AutoDeletePicker.vue'

interface Marker { id: number; name: string; icon_svg: string; color: string }

const props = withDefaults(defineProps<{
  batchSize: number
  canSubmit: boolean
  foreverActive: boolean
  concurrency: number
  idleLimit: number
  isMac?: boolean
  outputDestination?: string
  /** Carry auto-markers and auto-delete in the sheet (the phone drawer). */
  outputSettings?: boolean
  markers?: Marker[]
  autoMarkerIds?: number[]
  autoDelete?: string
}>(), { isMac: false, outputSettings: false, markers: () => [], autoMarkerIds: () => [], autoDelete: 'never' })

const emit = defineEmits<{
  run: []
  'update:batchSize': [value: number]
  startForever: [concurrency: number]
  stopForever: []
  'update:concurrency': [value: number]
  'update:idleLimit': [value: number]
  'update:autoMarkerIds': [value: number[]]
  'update:autoDelete': [value: string]
}>()

const outputSettingOn = computed(() => props.outputSettings && (props.autoMarkerIds.length > 0 || props.autoDelete !== 'never'))

const sheetOpen = ref(false)
defineExpose({ openSheet: () => { sheetOpen.value = true } })
let pressTimer: number | null = null
let longPressed = false

function onPointerDown() {
  longPressed = false
  pressTimer = window.setTimeout(() => { longPressed = true; sheetOpen.value = true }, 450)
}
function cancelPress() {
  if (pressTimer !== null) { window.clearTimeout(pressTimer); pressTimer = null }
}
const DOUBLE_TAP_MS = 300
let lastRunTap = 0

function onClick() {
  cancelPress()
  if (longPressed) { longPressed = false; return }
  if (props.foreverActive) { lastRunTap = 0; emit('stopForever'); return }
  if (!props.canSubmit) return
  const now = performance.now()
  if (now - lastRunTap < DOUBLE_TAP_MS) {
    lastRunTap = 0
    emit('startForever', props.concurrency)
    return
  }
  lastRunTap = now
  emit('run')
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
  <!-- A 44px target around a 36px fill; the fill's right edge is the page margin. -->
  <button
    type="button"
    data-testid="tool-run-button"
    class="h-11 min-w-11 flex-none flex items-center justify-center border-none bg-transparent pl-0 pr-1 select-none touch-manipulation focus-visible:outline-none"
    :aria-label="state === 'forever' ? 'Stop forever mode' : `Run ×${batchSize}`"
    @pointerdown="onPointerDown"
    @pointerup="cancelPress"
    @pointerleave="cancelPress"
    @pointercancel="cancelPress"
    @contextmenu.prevent
    @click="onClick"
  >
    <span
      class="flex h-9 min-w-14 items-center justify-center gap-1.5 rounded-md px-3.5 text-[15px] font-semibold transition-colors"
      :class="[
        state === 'forever' ? 'bg-live text-accent-on' : 'bg-accent text-accent-on',
        !canSubmit && state === 'idle' ? 'opacity-45' : '',
      ]"
    >
      <svg v-if="state === 'forever'" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16.5 8.5c-2 0-3.3 1.6-4.5 3.5s-2.5 3.5-4.5 3.5a3.5 3.5 0 0 1 0-7c2 0 3.3 1.6 4.5 3.5s2.5 3.5 4.5 3.5a3.5 3.5 0 0 0 0-7z" /></svg>
      <span>{{ state === 'forever' ? 'Stop' : 'Run' }}</span>
      <!-- Trailing marks live inside the fill so Run keeps one clean outline. -->
      <span v-if="batchSize > 1" class="font-mono text-[12.5px] font-medium opacity-70">×{{ batchSize }}</span>
      <svg
        v-if="outputSettingOn"
        class="h-4 w-4 opacity-70"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
        aria-hidden="true"
      ><title>Output settings on</title><path d="M4 8h9M17 8h3M4 16h3M11 16h9" /><circle cx="15" cy="8" r="2" /><circle cx="9" cy="16" r="2" /></svg>
    </span>
  </button>

  <Sheet :show="sheetOpen" title="Run" @close="sheetOpen = false">
    <p v-if="outputDestination" class="px-4 py-3 text-sm text-content-muted">Output: {{ outputDestination }}</p>
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
        <svg class="w-icon-nav h-icon-nav" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16.5 8.5c-2 0-3.3 1.6-4.5 3.5s-2.5 3.5-4.5 3.5a3.5 3.5 0 0 1 0-7c2 0 3.3 1.6 4.5 3.5s2.5 3.5 4.5 3.5a3.5 3.5 0 0 0 0-7z" /></svg>
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
    <template v-if="outputSettings">
      <div class="mx-4 my-1 border-t border-edge-subtle"></div>
      <p class="px-4 pt-2 text-[13px] font-semibold text-content-secondary">Every new output</p>
      <div v-if="markers.length > 0" class="flex items-center justify-between gap-3 px-4 min-h-14">
        <span class="text-[15px] text-content flex-none">Mark new results</span>
        <AutoMarkPicker
          class="flex-wrap justify-end"
          :markers="markers"
          :model-value="autoMarkerIds"
          @update:model-value="emit('update:autoMarkerIds', $event)"
        />
      </div>
      <label class="flex items-center justify-between px-4 min-h-12 pb-2">
        <span class="text-[15px] text-content">Auto-delete after</span>
        <select class="bg-overlay-subtle rounded-md px-3 py-2 text-sm font-mono text-content border border-transparent focus:border-accent outline-none min-h-11" :value="autoDelete" @change="emit('update:autoDelete', ($event.target as HTMLSelectElement).value)">
          <option v-for="o in AUTO_DELETE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
    </template>
  </Sheet>
</template>
