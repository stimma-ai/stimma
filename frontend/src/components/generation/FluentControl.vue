<template>
  <!-- Fluent: how Tool View sends a prompt to the image model. Fluent (the default)
       writes it the way this model understands it and varies it every image;
       Verbatim sends it exactly as typed. The chip says which, at rest. Status only
       shows when there's something to wait for or fix. -->
  <div class="relative flex items-center">
    <button
      ref="chip"
      type="button"
      data-fluent-chip
      :data-status="program.status.value"
      :aria-expanded="menuOpen"
      :class="['flex items-center gap-1.5 text-ctl transition-colors -mx-1.5 px-1.5 py-0.5 rounded-md outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
        llmUnconfigured && !raw ? 'text-content-muted hover:text-content-secondary' : 'text-content bg-overlay-subtle']"
      :title="chipTitle"
      @click="toggle"
    >
      <Spinner v-if="busy" size="sm" />
      <Bars3BottomLeftIcon v-else-if="raw" class="w-3.5 h-3.5" />
      <WandSparklesIcon v-else :class="['w-3.5 h-3.5', llmUnconfigured ? 'opacity-60' : '']" />
      <span>{{ chipText }}</span>
      <span v-if="failed" class="w-[6px] h-[6px] rounded-full bg-red-400" aria-label="Couldn’t read this prompt" />
      <Caret :open="menuOpen" class="opacity-70" />
    </button>

    <Teleport to="body">
      <div v-if="menuOpen" class="fixed inset-0 z-menu" @click="menuOpen = false">
        <div
          class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu w-80 max-w-[calc(100vw-16px)] overflow-y-auto"
          :style="menuStyle"
          data-fluent-menu
          role="menu"
          @click.stop
        >
          <!-- A little marketing: what Fluent is for. -->
          <div class="px-3 pt-2 pb-2.5">
            <div class="flex items-center gap-1.5 text-[13px] font-semibold text-content">
              <WandSparklesIcon class="w-3.5 h-3.5 text-accent" /> {{ BRAND }}
            </div>
            <div class="mt-0.5 text-[12px] leading-snug text-content-secondary">
              Your prompt, written the way {{ modelName || 'this model' }} understands it. {{ BRACES }} choices and # notes come alive, and every image gets a fresh take.
            </div>
          </div>

          <!-- Only when there's something to wait for or fix. -->
          <div v-if="notice" :class="['mx-3 mb-2 rounded-md px-2.5 py-2 text-[12px] leading-snug', notice.tone === 'bad' ? 'bg-red-500/10 text-red-400' : 'bg-overlay-subtle text-content-secondary']">
            <div class="flex items-center gap-1.5 font-medium">
              <Spinner v-if="busy" size="sm" />{{ notice.head }}
            </div>
            <div v-if="notice.body" class="mt-0.5 text-content-tertiary">{{ notice.body }}</div>
            <div v-if="notice.detail" class="mt-1 font-mono text-[10.5px] text-content-muted break-words">{{ notice.detail }}</div>
            <div v-if="notice.actions?.length" class="mt-1.5 flex gap-3">
              <button v-for="a in notice.actions" :key="a.label" type="button" class="text-[12px] font-medium text-content hover:underline" @click="a.run()">{{ a.label }}</button>
            </div>
          </div>

          <div class="border-t border-edge-subtle my-1" />
          <!-- Fluent (with its Add detail) or Verbatim: two positive choices. -->
          <button
                        type="button"
            role="menuitemradio"
            :aria-checked="way === ways[0].id"
            :disabled="ways[0].id === 'fluent' && llmUnconfigured"
            class="w-full text-left px-3 py-1.5 coarse:py-3 flex items-start gap-2.5 hover:bg-overlay-subtle disabled:opacity-40 disabled:pointer-events-none"
            @click="pickWay(ways[0].id)"
          >
            <span :class="['mt-[3px] shrink-0 w-3 h-3 rounded-full border flex items-center justify-center', way === ways[0].id ? 'border-accent' : 'border-edge-strong']">
              <span v-if="way === ways[0].id" class="w-1.5 h-1.5 rounded-full bg-accent" />
            </span>
            <span class="min-w-0">
              <span class="block text-[12px] coarse:text-[13px] text-content">{{ ways[0].label }}</span>
              <span class="block text-[11px] text-content-muted leading-snug">{{ ways[0].hint }}</span>
            </span>
          </button>

          <!-- Under Fluent: the one thing people are choosy about. -->
          <button
            v-if="way === 'fluent' && !program.unsupported.value"
            type="button"
            role="menuitemcheckbox"
            :aria-checked="elaborate"
            :disabled="llmUnconfigured"
            class="w-full text-left pl-[34px] pr-3 py-1.5 coarse:py-3 flex items-start gap-2.5 hover:bg-overlay-subtle disabled:opacity-40 disabled:pointer-events-none"
            @click="emit('mode', !elaborate)"
          >
            <span :class="['mt-[3px] shrink-0 w-3 h-3 rounded-[3px] border flex items-center justify-center', elaborate ? 'bg-accent border-accent text-white' : 'border-edge-strong']">
              <CheckIcon v-if="elaborate" class="w-2.5 h-2.5" />
            </span>
            <span class="min-w-0">
              <span class="block text-[12px] coarse:text-[13px] text-content">Add detail</span>
              <span class="block text-[11px] text-content-muted leading-snug">{{ elaborate ? 'Writes the fuller prompt this model does best with' : 'Off: your wording stays, only joined up' }}</span>
            </span>
          </button>
          <div v-if="way === 'fluent' && program.unsupported.value" class="pl-[34px] pr-3 pb-1 text-[11px] text-content-muted leading-snug">
            This model takes structured prompts, so Fluent writes one for each image; {{ BRACES }} choices aren’t available.
          </div>

          <button
                        type="button"
            role="menuitemradio"
            :aria-checked="way === ways[1].id"
            :disabled="ways[1].id === 'fluent' && llmUnconfigured"
            class="w-full text-left px-3 py-1.5 coarse:py-3 flex items-start gap-2.5 hover:bg-overlay-subtle disabled:opacity-40 disabled:pointer-events-none"
            @click="pickWay(ways[1].id)"
          >
            <span :class="['mt-[3px] shrink-0 w-3 h-3 rounded-full border flex items-center justify-center', way === ways[1].id ? 'border-accent' : 'border-edge-strong']">
              <span v-if="way === ways[1].id" class="w-1.5 h-1.5 rounded-full bg-accent" />
            </span>
            <span class="min-w-0">
              <span class="block text-[12px] coarse:text-[13px] text-content">{{ ways[1].label }}</span>
              <span class="block text-[11px] text-content-muted leading-snug">{{ ways[1].hint }}</span>
            </span>
          </button>
          <template v-if="retake">
            <div class="border-t border-edge-subtle my-1" />
            <button type="button" role="menuitem" class="w-full text-left px-3 py-1.5 coarse:py-3 hover:bg-overlay-subtle" @click="menuOpen = false; program.rethink()">
              <span class="block text-[12px] coarse:text-[13px] text-content">{{ retake.label }}</span>
              <span class="block text-[11px] text-content-muted leading-snug">{{ retake.hint }}</span>
            </button>
          </template>

          <div class="border-t border-edge-subtle my-1" />
          <button type="button" role="menuitem" class="w-full text-left px-3 py-1.5 coarse:py-3 text-[12px] coarse:text-[13px] text-content-secondary hover:bg-overlay-subtle hover:text-content" @click="menuOpen = false; emit('help', chip?.getBoundingClientRect() ?? null)">
            How to write for {{ BRAND }}
          </button>
          <button
            v-if="devModeRef && program.status.value !== 'off'"
            type="button"
            class="w-full text-left px-3 py-1.5 coarse:py-3 text-[12px] coarse:text-[13px] text-content-secondary hover:bg-overlay-subtle hover:text-content flex items-center justify-between"
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
          <div v-if="programText === ''" class="mx-4 mb-4 rounded-md border border-edge-subtle bg-surface-overlay px-3 py-6 text-[12px] text-content-secondary flex items-center justify-center gap-2">
            <template v-if="showError"><span class="text-red-400">{{ showError }}</span></template>
            <template v-else><span class="w-3 h-3 rounded-full border-2 border-accent-hi/25 border-t-accent-hi animate-spin" /> Reading your prompt…</template>
          </div>
          <template v-else>
          <div v-if="program.program.value?.warnings?.length" class="mx-4 mb-2 rounded-md bg-amber-500/10 px-3 py-2 text-[12px] text-amber-600 dark:text-amber-400">
            <div class="font-semibold mb-0.5">Accepted with problems</div>
            <div v-for="w in program.program.value.warnings" :key="w">{{ w }}</div>
          </div>
          <div v-if="enhancedText" class="mx-4 mb-2">
            <div class="text-xs font-semibold text-content-secondary mb-1">
              <template v-if="program.program.value?.elaborate === false">Your words, as kept <span class="font-normal text-content-muted">· {{ program.program.value?.mode }} format</span></template>
              <template v-else>Enhanced example <span class="font-normal text-content-muted">· {{ program.program.value?.mode }} style · {{ program.program.value?.upsample_seconds ?? '?' }}s</span></template>
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
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/solid'
import { Bars3BottomLeftIcon } from '@heroicons/vue/24/outline'
import type { PromptProgram } from '../../composables/usePromptProgram'
import { devModeRef } from '../../appConfig'
import ReadOnlyCode from '../viewers/ReadOnlyCode.vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import Spinner from '../ui/Spinner.vue'
import Caret from '../ui/Caret.vue'
import { PROMPT_BRAND as BRAND } from './promptBrand'

const props = defineProps<{
  program: PromptProgram
  /** Verbatim: sent exactly as typed. */
  raw: boolean
  /** Fluent's Add detail (true), or just your wording joined up (false). */
  elaborate: boolean
  /** No chat model is set up, so Fluent can't read prompts. */
  llmUnconfigured: boolean
  /** The image model's name, for the menu's one line of description. */
  modelName?: string
}>()
const emit = defineEmits<{
  (e: 'mode', elaborate: boolean): void
  (e: 'raw', on: boolean): void
  (e: 'help', anchor: DOMRect | null): void
}>()

const chip = ref<HTMLElement | null>(null)
// Literal {{ }} for templates (a mustache can't contain one).
const BRACES = '{' + '{ }' + '}'
const menuOpen = ref(false)
const programText = ref<string | null>(null)

const way = computed(() => (props.raw ? 'verbatim' : 'fluent'))
const detail = computed(() => props.elaborate || props.program.unsupported.value)
const on = computed(() => !props.raw && !props.llmUnconfigured)
const busy = computed(() => on.value && props.program.status.value === 'busy')
const failed = computed(() => on.value && props.program.status.value === 'error')

const ways = [
  { id: 'fluent' as const, label: BRAND, hint: 'Written for this model, with fresh choices every image' },
  { id: 'verbatim' as const, label: 'Verbatim', hint: 'Exactly as typed: braces and # lines included, for a later step to handle' },
]

const chipText = computed(() => {
  if (props.raw) return 'Verbatim'
  if (props.llmUnconfigured) return `${BRAND} · set up`
  return detail.value ? BRAND : `${BRAND} · your words`
})
const chipTitle = computed(() => {
  if (props.raw) return 'Verbatim: sent exactly as typed'
  if (props.llmUnconfigured) return `${BRAND} needs a chat model`
  if (busy.value) return 'Reading your prompt…'
  if (failed.value) return `${BRAND} couldn’t read this prompt`
  return detail.value ? `${BRAND}, adding detail` : `${BRAND}, keeping your wording`
})

type Action = { label: string; run: () => void }
type Notice = { head: string; body?: string; detail?: string; tone?: 'bad'; actions?: Action[] }
const useVerbatim: Action = { label: 'Use Verbatim', run: () => { menuOpen.value = false; emit('raw', true) } }
const notice = computed<Notice | null>(() => {
  if (props.raw) return null
  if (props.llmUnconfigured) return {
    head: `${BRAND} needs a chat model`,
    body: 'Until then, {a|b} lists and saved wildcards still fill in, and # lines are left out.',
    actions: [{ label: 'Add one in Settings', run: () => { menuOpen.value = false; window.dispatchEvent(new CustomEvent('open-settings', { detail: 'ai-services' })) } }],
  }
  if (busy.value) return { head: 'Reading your prompt…', body: 'First run only, a few seconds.' }
  if (failed.value) {
    const unreachable = props.program.error.value?.code === 'llm_unavailable'
    return {
      head: unreachable ? `${BRAND} couldn’t reach your chat model` : `${BRAND} couldn’t make sense of this prompt`,
      body: unreachable ? 'Nothing runs until it can read the prompt.' : 'Try again, or simplify the # notes.',
      tone: 'bad',
      detail: devModeRef.value ? props.program.error.value?.message : undefined,
      actions: [{ label: 'Try again', run: () => { void props.program.prepare(true) } }, useVerbatim],
    }
  }
  return null
})

// "Rewrite …": a fresh take on exactly what Fluent wrote (the choices' options and,
// with Add detail, the wording), named so it's clear what changes and what doesn't.
function listNames(names: string[]) {
  if (names.length <= 1) return names[0] || ''
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}
const retake = computed(() => {
  if (!on.value || props.program.status.value !== 'ready') return null
  const names = props.program.choices.value.filter(c => !c.hidden && c.kind === 'pick' && c.source !== 'list').map(c => c.label)
  const words = detail.value
  if (!names.length && !words) return null
  const label = names.length && words ? 'Rewrite choices and wording' : names.length ? 'Rewrite the choices' : 'Rewrite the wording'
  const what = [names.length ? `new options for ${listNames(names.slice(0, 4))}${names.length > 4 ? ' and more' : ''}` : '', words ? 'new wording' : '']
    .filter(Boolean).join(', and ')
  return { label, hint: `${what[0].toUpperCase()}${what.slice(1)}. Options you ticked or added stay, and so does your prompt.` }
})

function pickWay(id: 'fluent' | 'verbatim') {
  menuOpen.value = false
  if ((id === 'verbatim') !== props.raw) emit('raw', id === 'verbatim')
}

const menuStyle = ref<Record<string, string>>({})
function toggle() {
  if (!menuOpen.value) {
    const r = chip.value?.getBoundingClientRect()
    if (r) {
      const below = window.innerHeight - r.bottom - 12
      const above = r.top - 12
      const down = below >= 380 || below >= above
      menuStyle.value = {
        left: `${Math.max(8, Math.min(window.innerWidth - 296, r.left - 6))}px`,
        maxHeight: `${Math.max(200, down ? below : above)}px`,
        ...(down ? { top: `${r.bottom + 4}px` } : { bottom: `${window.innerHeight - r.top + 4}px` }),
      }
    }
  }
  menuOpen.value = !menuOpen.value
}

// Escape closes the dialog, then the menu. Both are teleported, so listen on the window.
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (programText.value !== null) programText.value = null
  else if (menuOpen.value) menuOpen.value = false
  else return
  e.preventDefault()
  e.stopPropagation()
}
watch(() => programText.value !== null || menuOpen.value, (open) => {
  if (open) window.addEventListener('keydown', onKey, true)
  else window.removeEventListener('keydown', onKey, true)
})
onUnmounted(() => window.removeEventListener('keydown', onKey, true))

// Dev: the program dialog ---------------------------------------------------------
const samples = ref<any[]>([])
const samplesError = ref('')
const copied = ref(false)
const enhancedText = ref('')
const showError = ref('')

/** Open the program, reading the prompt first if needed (the dialog shows the wait). */
async function showProgram() {
  programText.value = ''
  enhancedText.value = ''
  showError.value = ''
  samples.value = []
  try {
    if (!(await props.program.ensureReady())) {
      showError.value = props.program.error.value?.message || 'Couldn’t read this prompt.'
      return
    }
    const got = await props.program.fetchProgramText()
    if (programText.value === null) return  // closed while reading
    if (!got.program) {
      showError.value = 'Couldn’t load the program. Try again.'
      return
    }
    programText.value = got.program
    enhancedText.value = got.enhanced
  } catch (e: any) {
    if (programText.value !== null) showError.value = e?.response?.data?.detail?.message || 'Couldn’t load the program.'
    return
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
