<script setup lang="ts">
/**
 * The tool view's Run on a phone, laid out like desktop: a Run split button
 * (tap runs with the current batch size; the caret opens the run sheet) and a
 * separate Forever button beside it. Forever armed: the ∞ button turns solid
 * magenta and a tap stops it; Run stays a plain Run, as on desktop, so a tap
 * queues another run. Long-pressing Run also opens the sheet. The badge shows
 * the batch size, so ×4 is never a surprise. The sheet (batch stepper, Forever
 * mode and its two settings) has no Run button of its own: it is settings. In
 * the phone drawer it also carries the output settings (auto-markers,
 * auto-delete), which have no room beside the controls; a small settings glyph
 * inside Run's fill says one of them is on, and the controls area shows the
 * state on the New outputs row, whose delete button opens this sheet.
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
function onClick() {
  cancelPress()
  if (longPressed) { longPressed = false; return }
  if (!props.canSubmit) return
  emit('run')
}

function step(delta: number) {
  const next = Math.min(50, Math.max(1, props.batchSize + delta))
  emit('update:batchSize', next)
}

function toggleForever() {
  if (props.foreverActive) emit('stopForever')
  else if (props.canSubmit) emit('startForever', props.concurrency)
}

const CONCURRENCY = [{ label: 'Unlimited', value: 0 }, ...Array.from({ length: 10 }, (_, i) => ({ label: String(i + 1), value: i + 1 }))]
const IDLE = [10, 20, 50, 100, 250, 500, 1000].map((n) => ({ label: `${n} images`, value: n })).concat([{ label: 'No limit', value: 0 }])
</script>

<template>
  <!-- Run split button + Forever, each a 44px target around a 36px fill; the
       Forever fill's right edge is the page margin. -->
  <div class="flex flex-none items-center">
    <!-- The fills are spans inside full-height buttons, so each half keeps a
         44px touch target while the pair reads as one 36px split button. -->
    <button
      type="button"
      data-testid="tool-run-button"
      class="group h-11 flex-none flex items-center border-none bg-transparent p-0 select-none touch-manipulation focus-visible:outline-none"
      :aria-label="`Run ×${batchSize}`"
      @pointerdown="onPointerDown"
      @pointerup="cancelPress"
      @pointerleave="cancelPress"
      @pointercancel="cancelPress"
      @contextmenu.prevent
      @click="onClick"
    >
      <span
        class="flex h-9 items-center justify-center gap-1.5 rounded-l-md max-[389px]:rounded-md bg-accent pl-3.5 pr-2.5 max-[389px]:pr-3.5 text-[15px] font-semibold text-accent-on group-focus-visible:ring-2 group-focus-visible:ring-accent/60"
        :class="!canSubmit ? 'opacity-45' : ''"
      >
        <span>Run</span>
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
    <!-- Under 390px the header has no room for the caret; long-press opens the sheet. -->
    <button
      type="button"
      data-testid="tool-run-options"
      class="group h-11 flex-none flex items-center border-none bg-transparent p-0 select-none touch-manipulation focus-visible:outline-none max-[389px]:hidden"
      aria-label="Run options"
      :aria-expanded="sheetOpen"
      @click="sheetOpen = true"
    >
      <span
        class="relative flex h-9 w-8 items-center justify-center rounded-r-md bg-accent text-accent-on group-focus-visible:ring-2 group-focus-visible:ring-accent/60"
        :class="!canSubmit ? 'opacity-45' : ''"
      >
        <span class="absolute left-0 inset-y-2 w-px bg-accent-on/25" aria-hidden="true"></span>
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
      </span>
    </button>
    <button
      type="button"
      data-testid="tool-forever-button"
      class="group h-11 w-11 max-[389px]:w-10 flex-none flex items-center justify-end border-none bg-transparent pl-1 pr-0 select-none touch-manipulation focus-visible:outline-none"
      :aria-label="foreverActive ? 'Stop forever mode' : 'Start forever mode'"
      :aria-pressed="foreverActive"
      @click="toggleForever"
    >
      <span
        class="flex h-9 w-10 max-[389px]:w-9 items-center justify-center rounded-md transition-colors group-focus-visible:ring-2 group-focus-visible:ring-accent/60"
        :class="[
          foreverActive ? 'bg-live text-accent-on' : 'bg-surface-raised text-content',
          !canSubmit && !foreverActive ? 'opacity-45' : '',
        ]"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M16.5 8.5c-2 0-3.3 1.6-4.5 3.5s-2.5 3.5-4.5 3.5a3.5 3.5 0 0 1 0-7c2 0 3.3 1.6 4.5 3.5s2.5 3.5 4.5 3.5a3.5 3.5 0 0 0 0-7z" /></svg>
      </span>
    </button>
  </div>

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
      <p class="px-4 pt-2 text-[13px] font-semibold text-content-secondary">New outputs</p>
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
