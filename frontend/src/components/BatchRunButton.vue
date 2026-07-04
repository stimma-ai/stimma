<template>
  <div class="relative" ref="containerRef">
    <!-- Split button: main Run + caret -->
    <div
      class="flex rounded-lg overflow-hidden bg-blue-500"
      :class="disabled ? 'opacity-50' : ''"
    >
      <!-- Main run button -->
      <button
        data-testid="tool-run-button"
        @click="emit('run')"
        :disabled="disabled"
        class="px-4 py-2 text-white text-sm font-semibold transition-colors hover:bg-blue-600 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        :class="disabled ? 'cursor-not-allowed' : 'cursor-pointer'"
      >
        <span>{{ mediaBatchCount ? 'Run Batch' : 'Run' }}</span>
        <!-- Batch count badge when >1, else the keyboard hint -->
        <span
          v-if="mediaBatchCount"
          class="text-xs font-bold bg-white/20 rounded px-1.5 py-px leading-none"
        >{{ mediaBatchCount }}{{ batchSize > 1 ? ` ×${batchSize}` : '' }}</span>
        <span
          v-else-if="batchSize > 1"
          class="text-xs font-bold bg-white/20 rounded px-1.5 py-px leading-none"
        >×{{ batchSize }}</span>
        <span v-else class="text-xs opacity-70 font-normal">{{ isMac ? '⌘↵' : 'Ctrl+↵' }}</span>
      </button>

      <!-- Divider -->
      <div class="w-px bg-white/25"></div>

      <!-- Caret: opens batch-size popover -->
      <button
        @click.stop="togglePopover"
        class="px-2 py-2 text-white cursor-pointer transition-colors hover:bg-blue-600 flex items-center"
        title="Batch size"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
             class="w-3 h-3 transition-transform" :class="showPopover ? 'rotate-180' : ''">
          <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
    </div>

    <!-- Batch-size popover -->
    <div
      v-if="showPopover"
      class="absolute left-0 mt-2 w-60 bg-surface border border-edge rounded-xl shadow-lg z-50 p-3.5"
      @click.stop
    >
      <div class="text-sm font-semibold text-content">{{ mediaBatchCount ? 'Repeat batch' : 'Batch size' }}</div>
      <p class="text-xs text-content-muted mb-3.5">
        {{ mediaBatchCount ? `Run the ${mediaBatchCount}-item batch this many times.` : 'Queue this many generations per run.' }}
      </p>

      <!-- Stepper -->
      <div class="flex items-center justify-between gap-3">
        <span class="text-sm text-content-secondary">{{ mediaBatchCount ? 'Batch repeats' : 'Images per run' }}</span>
        <div class="flex items-center bg-base border border-edge rounded-lg overflow-hidden">
          <button
            @click="setSize(batchSize - 1)"
            :disabled="batchSize <= MIN"
            class="w-8 h-8 text-content-secondary text-lg leading-none transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >−</button>
          <input
            :value="batchSize"
            @change="commitInput"
            @keydown.enter="commitInput"
            type="number"
            :min="MIN" :max="MAX"
            class="w-11 h-8 bg-transparent text-content text-sm font-semibold text-center focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
          <button
            @click="setSize(batchSize + 1)"
            :disabled="batchSize >= MAX"
            class="w-8 h-8 text-content-secondary text-lg leading-none transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >+</button>
        </div>
      </div>

      <!-- Quick presets -->
      <div class="flex gap-1.5 mt-3.5">
        <button
          v-for="preset in PRESETS"
          :key="preset"
          @click="setSize(preset)"
          class="flex-1 h-7 rounded-lg text-xs font-semibold border transition-colors cursor-pointer"
          :class="batchSize === preset
            ? 'bg-blue-500/15 border-blue-500/50 text-blue-400'
            : 'bg-surface-raised border-edge-subtle text-content-secondary hover:bg-surface-hover hover:text-content'"
        >{{ preset }}</button>
      </div>

      <p class="text-[11px] text-content-muted mt-3.5 leading-snug">
        <template v-if="mediaBatchCount">
          Each repeat runs all {{ mediaBatchCount }} batch items with the current settings.
        </template>
        <template v-else>
          Each image is queued separately with a fresh seed — the same as pressing Run {{ batchSize > 1 ? batchSize : 'N' }} times. No grouping.
        </template>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const MIN = 1
const MAX = 8
const PRESETS = [1, 2, 4, 8]

interface Props {
  batchSize: number
  disabled?: boolean
  isMac?: boolean
  mediaBatchCount?: number
}
const props = withDefaults(defineProps<Props>(), {
  mediaBatchCount: 0,
})

const emit = defineEmits<{
  (e: 'run'): void
  (e: 'update:batchSize', value: number): void
}>()

const showPopover = ref(false)
const containerRef = ref<HTMLElement | null>(null)

function clamp(n: number) {
  if (!Number.isFinite(n)) return props.batchSize
  return Math.min(MAX, Math.max(MIN, Math.round(n)))
}

function setSize(n: number) {
  emit('update:batchSize', clamp(n))
}

function commitInput(event: Event) {
  const el = event.target as HTMLInputElement
  const next = clamp(Number(el.value))
  el.value = String(next)
  emit('update:batchSize', next)
}

function togglePopover() {
  showPopover.value = !showPopover.value
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  if (showPopover.value && containerRef.value && !containerRef.value.contains(target)) {
    showPopover.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>
