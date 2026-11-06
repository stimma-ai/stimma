<template>
  <!-- One dot in the prompt card's corner: prepared (green), changed (amber),
       preparing (spinner), couldn't prepare (red). Click for the rare actions. -->
  <div v-if="program.status.value !== 'off'" class="absolute top-1.5 right-1.5 z-[1]">
    <button
      ref="btn"
      type="button"
      class="w-5 h-5 rounded-full flex items-center justify-center hover:bg-overlay-subtle coarse:w-9 coarse:h-9"
      :title="title"
      :aria-label="title"
      data-program-dot
      :data-status="program.status.value"
      @click="menuOpen = !menuOpen"
    >
      <span
        v-if="program.status.value === 'busy'"
        class="w-2.5 h-2.5 rounded-full border-2 border-accent-hi/25 border-t-accent-hi animate-spin"
      />
      <span v-else :class="['w-[7px] h-[7px] rounded-full', dotColor]" />
    </button>
    <Teleport to="body">
      <div v-if="menuOpen" class="fixed inset-0 z-menu" @click="menuOpen = false">
        <div
          class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu w-64"
          :style="menuStyle"
          @click.stop
        >
          <div class="px-3 pt-1.5 pb-2 text-[12px] leading-snug text-content-secondary">{{ statusText }}</div>
          <div class="border-t border-edge-subtle my-1" />
          <button
            type="button"
            class="w-full text-left px-3 py-1.5 text-[12px] text-content-secondary hover:bg-overlay-subtle disabled:opacity-50"
            :disabled="program.status.value === 'busy'"
            @click="menuOpen = false; program.prepare(true)"
          >Prepare from scratch</button>
          <button
            type="button"
            class="w-full text-left px-3 py-1.5 text-[12px] text-content-secondary hover:bg-overlay-subtle disabled:opacity-50"
            :disabled="!program.program.value"
            @click="menuOpen = false; showProgram()"
          >Show program</button>
        </div>
      </div>
      <div v-if="programText !== null" class="fixed inset-0 z-modal bg-overlay-backdrop flex items-center justify-center p-4" @click.self="programText = null">
        <div class="w-[760px] max-w-full rounded-lg bg-surface border border-edge p-4 shadow-xl">
          <div class="flex items-baseline gap-2 mb-1">
            <span class="text-[14px] font-semibold text-content">Program</span>
            <span class="text-[11px] text-content-muted">prepared in {{ program.program.value?.seconds ?? '?' }}s · running it needs no model call</span>
          </div>
          <pre class="mt-2 max-h-[65vh] overflow-auto rounded-md bg-surface-overlay border border-edge-subtle p-3 font-mono text-[11.5px] leading-relaxed text-content-secondary whitespace-pre">{{ programText }}</pre>
          <div v-if="program.program.value?.example" class="mt-3 text-[12px] text-content-tertiary">
            <span class="text-content-muted">One run: </span>{{ program.program.value.example }}
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PromptProgram } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const btn = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const programText = ref<string | null>(null)

const dotColor = computed(() => ({
  ready: 'bg-emerald-400',
  stale: 'bg-amber-400',
  error: 'bg-red-400',
}[props.program.status.value as 'ready' | 'stale' | 'error'] || 'bg-content-muted'))

const statusText = computed(() => ({
  ready: 'Prepared. Each run draws new choices without calling a model.',
  stale: 'Changed. Prepares when you run.',
  busy: 'Preparing…',
  error: props.program.error.value?.message || 'Couldn’t prepare this prompt.',
}[props.program.status.value as string] || ''))

const title = computed(() => ({ ready: 'Prepared', stale: 'Changed: prepares when you run', busy: 'Preparing…', error: 'Couldn’t prepare' }[props.program.status.value as string] || ''))

const menuStyle = computed(() => {
  const r = btn.value?.getBoundingClientRect()
  if (!r) return {}
  return { top: `${r.bottom + 4}px`, left: `${Math.max(8, Math.min(window.innerWidth - 264, r.right - 256))}px` }
})

async function showProgram() {
  try {
    programText.value = await props.program.fetchProgramText()
  } catch {
    programText.value = props.program.program.value?.program || '(not prepared)'
  }
}
</script>
