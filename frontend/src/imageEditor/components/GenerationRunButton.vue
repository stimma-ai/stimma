<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import Spinner from '../../components/ui/Spinner.vue'

const props = defineProps<{
  count: number
  disabled?: boolean
  loading?: boolean
  variations?: boolean
  /** Verb override: an iterating session says "Re-run", not "Run". */
  label?: string
}>()

const emit = defineEmits<{
  run: []
  'update:count': [number]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const COUNTS = [1, 2, 3, 4, 5, 6, 7, 8]

function choose(count: number) {
  emit('update:count', count)
}

function closeOutside(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', closeOutside))
onUnmounted(() => document.removeEventListener('click', closeOutside))
</script>

<template>
  <div ref="root" class="relative shrink-0">
    <div
      class="flex overflow-hidden rounded-md bg-accent text-white"
      :class="(disabled || loading) && 'opacity-50'"
    >
      <button
        type="button"
        class="inline-flex min-w-[4.75rem] items-center justify-center gap-1.5 px-2.5 py-1.5
               text-xs font-medium transition-colors hover:bg-accent/90
               disabled:cursor-not-allowed compact:min-h-11 compact:px-4 compact:text-[13px]"
        :disabled="disabled || loading"
        @click="emit('run')"
      >
        <Spinner v-if="loading" size="sm" />
        <template v-else>{{ label ?? 'Run' }}{{ variations !== false && count > 1 ? ` ×${count}` : '' }}</template>
      </button>
      <button
        v-if="variations !== false"
        type="button"
        class="grid w-7 place-items-center border-l border-white/20 transition-colors
               hover:bg-accent/90 disabled:cursor-not-allowed compact:w-11"
        :disabled="disabled || loading"
        aria-label="Choose variations"
        :aria-expanded="open"
        title="Variations"
        @click.stop="open = !open"
      >
        <svg viewBox="0 0 20 20" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2">
          <path d="m5 7.5 5 5 5-5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <div
      v-if="open && variations !== false"
      class="absolute right-0 top-full z-menu mt-1.5 w-64 rounded-lg border border-edge-subtle
             bg-surface p-3 shadow-lg"
      @click.stop
    >
      <p class="text-sm font-semibold text-content">
        Variations
      </p>
      <p class="mt-0.5 text-xs text-content-muted">
        Generate several alternatives at once.
      </p>

      <div class="mt-3 grid grid-cols-4 gap-0.5 rounded-md bg-overlay-faint p-0.5">
        <button
          v-for="option in COUNTS"
          :key="option"
          type="button"
          class="h-8 rounded-[5px] font-mono text-xs font-semibold tabular-nums
                 text-content-secondary transition-colors hover:text-content"
          :class="option === count
            ? 'bg-accent/15 text-accent-hi'
            : 'hover:bg-overlay-subtle'"
          :aria-label="`${option} ${option === 1 ? 'variation' : 'variations'}`"
          :aria-pressed="option === count"
          @click="choose(option)"
        >
          {{ option }}
        </button>
      </div>

      <p class="mt-3 text-[11px] leading-snug text-content-muted">
        Every result stays with the edit, ready to compare or use again later.
      </p>
    </div>
  </div>
</template>
