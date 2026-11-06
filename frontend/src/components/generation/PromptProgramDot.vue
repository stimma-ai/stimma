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
            v-if="devModeRef"
            type="button"
            class="w-full text-left px-3 py-1.5 text-[12px] text-content-secondary hover:bg-overlay-subtle disabled:opacity-50 flex items-center justify-between"
            :disabled="!program.program.value"
            @click="menuOpen = false; showProgram()"
          >Show program <span class="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-md">Dev</span></button>
        </div>
      </div>
      <!-- Dev: the prepared program, how preparing went, and live sample runs. -->
      <div
        v-if="programText !== null"
        class="fixed inset-0 z-modal bg-overlay-backdrop flex items-center justify-center p-4"
        data-escape-layer
        @click.self="programText = null"
        @keydown.escape="programText = null"
      >
        <div class="w-[960px] max-w-full max-h-[92vh] flex flex-col rounded-lg bg-surface border border-edge shadow-xl" data-program-debug>
          <div class="flex items-center gap-2 px-4 pt-3 pb-2">
            <span class="text-[14px] font-semibold text-content">Program</span>
            <span class="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-md">Dev</span>
            <span class="text-[11px] text-content-muted font-mono">
              {{ program.program.value?.key?.slice(0, 10) }} · prepared in {{ program.program.value?.seconds ?? '?' }}s · {{ program.program.value?.attempts ?? 1 }} attempt(s) · {{ program.choices.value.length }} choices
            </span>
            <span class="flex-1" />
            <button type="button" class="text-[12px] text-content-tertiary hover:text-content px-2 py-1 rounded-md hover:bg-overlay-subtle" @click="copyProgram">{{ copied ? 'Copied' : 'Copy' }}</button>
            <button type="button" class="text-content-tertiary hover:text-content p-1 rounded-md hover:bg-overlay-subtle" aria-label="Close" @click="programText = null">✕</button>
          </div>
          <div v-if="program.program.value?.warnings?.length" class="mx-4 mb-2 rounded-md bg-amber-500/10 px-3 py-2 text-[12px] text-amber-600 dark:text-amber-400">
            <div class="font-semibold mb-0.5">Accepted with problems</div>
            <div v-for="w in program.program.value.warnings" :key="w">{{ w }}</div>
          </div>
          <div v-if="enhancedText" class="mx-4 mb-2">
            <div class="text-xs font-semibold text-content-secondary mb-1">
              Enhanced example <span class="font-normal text-content-muted">· {{ program.program.value?.mode }} style · {{ program.program.value?.upsample_seconds ?? '?' }}s</span>
            </div>
            <div class="max-h-[16vh] overflow-y-auto rounded-md bg-surface-overlay border border-edge-subtle px-3 py-2 text-[12px] leading-relaxed text-content-secondary whitespace-pre-wrap">{{ enhancedText }}</div>
          </div>
          <div class="mx-4 rounded-md border border-edge-subtle bg-surface-overlay h-[40vh] min-h-[200px] overflow-hidden">
            <ReadOnlyCode :text="programText" name="program.py" wrap />
          </div>
          <div class="px-4 pt-3 pb-4 overflow-y-auto min-h-0">
            <div class="flex items-center gap-2 mb-1.5">
              <span class="text-xs font-semibold text-content-secondary">Sample runs</span>
              <span class="text-[11px] text-content-muted">with your current pins</span>
              <span class="flex-1" />
              <button type="button" class="text-[12px] text-content-tertiary hover:text-content px-2 py-0.5 rounded-md hover:bg-overlay-subtle" @click="loadSamples">Draw again</button>
            </div>
            <div v-if="samplesError" class="text-[12px] text-red-400">{{ samplesError }}</div>
            <ol class="space-y-2">
              <li v-for="(r, i) in samples" :key="i" class="text-[12px] leading-relaxed">
                <div class="text-content-secondary">{{ r.prompt }}</div>
                <div class="font-mono text-[10.5px] text-content-muted">
                  {{ r.draws.map((d: any) => `${d.id}=${d.value}`).join(' · ') }}
                </div>
              </li>
            </ol>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PromptProgram } from '../../composables/usePromptProgram'
import { devModeRef } from '../../appConfig'
import ReadOnlyCode from '../viewers/ReadOnlyCode.vue'

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
  stale: 'Not prepared for this prompt yet. Prepares when you run.',
  busy: 'Preparing…',
  error: props.program.error.value?.message || 'Couldn’t prepare this prompt.',
}[props.program.status.value as string] || ''))

const title = computed(() => ({ ready: 'Prepared', stale: 'Not prepared: prepares when you run', busy: 'Preparing…', error: 'Couldn’t prepare' }[props.program.status.value as string] || ''))

const menuStyle = computed(() => {
  const r = btn.value?.getBoundingClientRect()
  if (!r) return {}
  return { top: `${r.bottom + 4}px`, left: `${Math.max(8, Math.min(window.innerWidth - 264, r.right - 256))}px` }
})

const samples = ref<any[]>([])
const samplesError = ref('')
const copied = ref(false)

const enhancedText = ref('')

async function showProgram() {
  try {
    const got = await props.program.fetchProgramText()
    if (!got.program) {
      // The server doesn't have it (anymore): the dot turns amber and the next run prepares.
      menuOpen.value = true
      return
    }
    programText.value = got.program
    enhancedText.value = got.enhanced
  } catch {
    programText.value = props.program.program.value?.program || '(not prepared)'
  }
  void loadSamples()
}

async function loadSamples() {
  samplesError.value = ''
  try {
    samples.value = await props.program.previewRuns(5)
  } catch (e: any) {
    samplesError.value = e?.response?.data?.detail?.message || e?.message || 'Couldn’t run the program.'
  }
}

async function copyProgram() {
  await navigator.clipboard?.writeText(programText.value || '')
  copied.value = true
  setTimeout(() => { copied.value = false }, 1200)
}
</script>
