<template>
  <!-- Fluent: how Tool View sends a prompt to the image model. Fluent (the default)
       writes it the way this model understands it and varies it every image;
       Direct fills in lists and saved wildcards with no model; Raw sends it exactly as typed.
       The chip says which, at rest; with no chat model set up, runs are Direct and the chip
       says so. Status only shows when there's something to wait for or fix. -->
  <div class="relative flex items-center">
    <button
      ref="chip"
      type="button"
      data-fluent-chip
      :data-status="program.status.value"
      aria-haspopup="dialog"
      :aria-expanded="menuOpen"
      class="flex items-center gap-1.5 text-ctl transition-colors -mx-1.5 px-1.5 py-0.5 rounded-md outline-none focus-visible:ring-1 focus-visible:ring-selection/60 text-content bg-overlay-subtle"
      :title="chipTitle"
      @click="toggle"
    >
      <Spinner v-if="busy" size="sm" />
      <CodeBracketSquareIcon v-else-if="running === 'raw'" class="w-3.5 h-3.5" />
      <Bars3BottomLeftIcon v-else-if="running === 'direct'" class="w-3.5 h-3.5" />
      <WandSparklesIcon v-else class="w-3.5 h-3.5" />
      <span>{{ chipText }}</span>
      <LanguageIcon v-if="translating" class="w-3.5 h-3.5 opacity-70" :aria-label="`Translating to ${languageLabel}`" />
      <span v-if="failed" class="w-[6px] h-[6px] rounded-full bg-red-400" aria-label="Couldn’t read this prompt" />
      <Caret :open="menuOpen" class="opacity-70" />
    </button>

    <Teleport to="body">
      <div v-if="menuOpen" class="fixed inset-0 z-menu" @click="menuOpen = false">
        <div
          ref="menuEl"
          class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu w-80 max-w-[calc(100vw-16px)] overflow-y-auto"
          :style="menuStyle"
          data-fluent-menu
          role="dialog"
          aria-label="Prompting"
          @click.stop="languagesOpen = false"
        >
          <!-- What this menu is, and its two tools. -->
          <div class="pl-3 pr-2 pt-2 pb-2 flex items-center gap-1">
            <span class="flex-1 text-[11px] font-semibold text-content-tertiary">Prompting</span>
            <button type="button" class="p-1 rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle" title="Prompt tips" aria-label="Prompt tips"
              @click="menuOpen = false; emit('help', chip?.getBoundingClientRect() ?? null)">
              <QuestionMarkCircleIcon class="w-4 h-4" />
            </button>
            <button v-if="devModeRef && program.status.value !== 'off'" type="button" class="p-1 rounded-md text-amber-500 hover:text-amber-400 hover:bg-overlay-subtle" title="Show program (dev)" aria-label="Show program"
              @click="menuOpen = false; showProgram()">
              <CodeBracketIcon class="w-4 h-4" />
            </button>
            <button v-if="devModeRef" type="button" class="p-1 rounded-md text-amber-500 hover:text-amber-400 hover:bg-overlay-subtle" title="Vocabulary (dev)" aria-label="Show vocabulary"
              @click="menuOpen = false; vocabOpen = true">
              <BookOpenIcon class="w-4 h-4" />
            </button>
          </div>

          <!-- Two ways to send a prompt, as tabs; each tab holds its own line and settings. -->
          <div class="px-3">
            <SegmentedControl
              class="!flex !w-full [&>button]:flex-1 [&>button]:justify-center"
              :model-value="tab"
              :options="[{ label: BRAND, value: 'fluent', icon: WandSparklesIcon }, { label: 'Direct', value: 'direct', icon: Bars3BottomLeftIcon }, { label: 'Raw', value: 'raw', icon: CodeBracketSquareIcon }]"
              aria-label="How the prompt is sent"
              @update:model-value="(v) => pickWay(v as Way)"
            />
          </div>
          <div class="px-3 pt-2.5 pb-2.5 text-[12px] leading-snug text-content-secondary">{{ tagline }}</div>

          <template v-if="tab === 'fluent'">
            <div v-if="notice" :class="['mx-3 mb-2 rounded-md px-2.5 py-2 text-[12px] leading-snug', notice.tone === 'bad' ? 'bg-red-500/10 text-red-400' : 'bg-overlay-subtle text-content-secondary']">
              <div class="flex items-center gap-1.5 font-medium">
                <Spinner v-if="busy" size="sm" />{{ notice.head }}
              </div>
              <div v-if="notice.body" class="mt-0.5">{{ notice.body }}</div>
              <div v-if="notice.detail" class="mt-1 font-mono text-[10.5px] text-content-muted break-words">{{ notice.detail }}</div>
              <div v-if="notice.actions?.length" class="mt-1.5 flex gap-3">
                <button v-for="a in notice.actions" :key="a.label" type="button" class="text-[12px] font-medium text-content hover:underline" @click="a.run()">{{ a.label }}</button>
              </div>
            </div>
            <div class="border-t border-edge-subtle" />
            <!-- No chat model: Fluent's own settings can't apply, so they can't be reached either. -->
            <div
              v-if="!program.unsupported.value"
              :inert="llmUnconfigured || undefined"
              :aria-disabled="llmUnconfigured || undefined"
              :class="['flex items-center gap-3 px-3 py-2 coarse:py-3', llmUnconfigured ? 'opacity-40' : '']"
            >
              <span class="flex-1 text-[12px] coarse:text-[13px] text-content">Detail level</span>
              <SegmentedControl
                :model-value="enhance"
                :options="[{ label: 'Yours', value: 'off' }, { label: 'Medium', value: 'fill' }, { label: 'High', value: 'expand' }]"
                aria-label="Detail level"
                @update:model-value="(v) => emit('mode', v as EnhanceLevel)"
              />
            </div>
            <template v-if="hasLoras">
              <label class="flex items-center gap-3 px-3 py-2 coarse:py-3 hover:bg-overlay-subtle cursor-pointer">
                <span class="flex-1 text-[12px] coarse:text-[13px] text-content">LoRA trigger words</span>
                <Toggle :model-value="!!loraTriggers" label="LoRA trigger words" @update:model-value="(v) => emit('lora', 'loraTriggers', v)" />
              </label>
              <label
                :inert="llmUnconfigured || undefined"
                :aria-disabled="llmUnconfigured || undefined"
                :class="['flex items-center gap-3 px-3 py-2 coarse:py-3', llmUnconfigured ? 'opacity-40' : 'hover:bg-overlay-subtle cursor-pointer']"
              >
                <span class="flex-1 text-[12px] coarse:text-[13px] text-content">LoRA notes</span>
                <Toggle :model-value="!!loraNotes" label="LoRA notes" @update:model-value="(v) => emit('lora', 'loraNotes', v)" />
              </label>
            </template>
          </template>
          <!-- Direct has no model, so only the trigger words apply. -->
          <template v-else-if="tab === 'direct'">
            <div class="border-t border-edge-subtle" />
            <label v-if="hasLoras" class="flex items-center gap-3 px-3 py-2 coarse:py-3 hover:bg-overlay-subtle cursor-pointer">
              <span class="flex-1 text-[12px] coarse:text-[13px] text-content">LoRA trigger words</span>
              <Toggle :model-value="!!loraTriggers" label="LoRA trigger words" @update:model-value="(v) => emit('lora', 'loraTriggers', v)" />
            </label>
          </template>
          <!-- Translate: Raw sends the prompt as typed, so it applies to the other two.
               The row shows the language; the list opens in place. -->
          <template v-if="tab !== 'raw'">
            <button
              ref="translateRow"
              type="button"
              data-fluent-translate
              aria-haspopup="menu"
              :aria-expanded="languagesOpen"
              :disabled="llmUnconfigured"
              :class="['w-full text-left flex items-center gap-3 px-3 py-2 coarse:py-3 hover:bg-overlay-subtle', languagesOpen ? 'bg-overlay-subtle' : '', llmUnconfigured ? 'opacity-40 pointer-events-none' : '']"
              @click.stop="toggleLanguages()"
            >
              <span class="flex-1 text-[12px] coarse:text-[13px] text-content">Translate prompt</span>
              <span :class="['text-[12px] coarse:text-[13px]', translating ? 'text-content' : 'text-content-tertiary']">{{ translating ? languageLabel : 'Off' }}</span>
              <Caret :open="languagesOpen" class="opacity-70" />
            </button>
          </template>
          <button
            v-if="tab === 'fluent' && retake"
            type="button"
            class="w-full text-left flex items-center gap-2 px-3 py-2 coarse:py-3 text-[12px] coarse:text-[13px] text-content hover:bg-overlay-subtle"
            @click="menuOpen = false; program.rethink()"
          >
            <ArrowPathIcon class="w-3.5 h-3.5 text-content-tertiary" />{{ retake.label }}
          </button>
        </div>
        <!-- Translate's languages: a dropdown under the row, over the menu. -->
        <div
          v-if="languagesOpen"
          class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu w-56 overflow-y-auto"
          :style="languagesStyle"
          data-fluent-languages
          role="menu"
          aria-label="Translate prompt to"
          @click.stop
        >
          <button
            v-for="opt in languageOptions"
            :key="opt.code ?? 'off'"
            type="button"
            role="menuitemradio"
            :aria-checked="opt.picked"
            class="w-full text-left flex items-center gap-2 px-3 py-1.5 coarse:py-2.5 hover:bg-overlay-subtle"
            @click="emit('translate', opt.code); languagesOpen = false"
          >
            <span :class="['flex-1 text-[12px] coarse:text-[13px]', opt.picked ? 'text-content' : 'text-content-secondary']">{{ opt.label }}</span>
            <span v-if="opt.english" class="text-[10.5px] text-content-tertiary">{{ opt.english }}</span>
            <CheckIcon :class="['w-3.5 h-3.5 shrink-0', opt.picked ? 'text-content' : 'invisible']" />
          </button>
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
            <template v-else><span class="w-3 h-3 rounded-full border-2 border-accent-hi/25 border-t-accent-hi animate-spin" /> Preparing your prompt…</template>
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
    <!-- Dev: the vocabulary lists picks can draw from. -->
    <FluentVocabularyBrowser v-if="devModeRef" :show="vocabOpen" @close="vocabOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { CheckIcon, LanguageIcon } from '@heroicons/vue/24/solid'
import { ArrowPathIcon, Bars3BottomLeftIcon, BookOpenIcon, CodeBracketIcon, CodeBracketSquareIcon, QuestionMarkCircleIcon } from '@heroicons/vue/24/outline'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Toggle from '../ui/Toggle.vue'
import type { EnhanceLevel, PromptProgram } from '../../composables/usePromptProgram'
import { devModeRef } from '../../appConfig'
import ReadOnlyCode from '../viewers/ReadOnlyCode.vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import Spinner from '../ui/Spinner.vue'
import Caret from '../ui/Caret.vue'
import FluentVocabularyBrowser from './FluentVocabularyBrowser.vue'
import { PROMPT_BRAND as BRAND } from './promptBrand'
import { PROMPT_LANGUAGES, promptLanguageByCode, DEFAULT_TRANSLATE_LANGUAGE } from './promptLanguages'
import { effectiveWay, type PromptWay } from '../../utils/fluentSubmit'

const props = defineProps<{
  program: PromptProgram
  /** Raw: sent exactly as typed. */
  raw: boolean
  /** Direct: lists and saved wildcards fill in, no model reads the prompt. */
  direct: boolean
  /** Detail level: off is Yours (your wording joined up), fill is Medium (plus what the model needs), expand is High. */
  enhance: EnhanceLevel
  /** No chat model is set up, so Fluent can't read prompts. */
  llmUnconfigured: boolean
  /** The image model's name, for the menu's one line of description. */
  modelName?: string
  /** The tool takes LoRAs, so the LoRA choices apply. */
  hasLoras?: boolean
  loraTriggers?: boolean
  loraNotes?: boolean
  /** Generate forever is running the last prepared version while this one prepares. */
  previousRunning?: boolean
  /** Translate the prompt before generating (not in Raw). */
  translate?: { enabled: boolean; language: string }
}>()
const emit = defineEmits<{
  (e: 'mode', level: EnhanceLevel): void
  (e: 'way', way: Way): void
  (e: 'help', anchor: DOMRect | null): void
  (e: 'lora', key: 'loraTriggers' | 'loraNotes', on: boolean): void
  /** A language code to translate into, or null for off. */
  (e: 'translate', code: string | null): void
}>()

const chip = ref<HTMLElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const programText = ref<string | null>(null)
const vocabOpen = ref(false)
const languagesOpen = ref(false)
watch(menuOpen, (open) => { if (!open) languagesOpen.value = false })
const translateRow = ref<HTMLElement | null>(null)
const languagesStyle = ref<Record<string, string>>({})
const LANG_W = 224
function toggleLanguages() {
  if (languagesOpen.value) { languagesOpen.value = false; return }
  const row = translateRow.value?.getBoundingClientRect()
  if (!row) return
  // Under the row, right-aligned with its value; above it when the row is low.
  const vw = window.innerWidth, vh = window.innerHeight
  const below = vh - row.bottom - 8, above = row.top - 8
  const down = below >= 260 || below >= above
  languagesStyle.value = {
    left: `${Math.max(8, Math.min(vw - LANG_W - 8, row.right - LANG_W - 4))}px`,
    maxHeight: `${down ? below : above}px`,
    ...(down ? { top: `${row.bottom + 2}px` } : { bottom: `${vh - row.top + 2}px` }),
  }
  languagesOpen.value = true
}

type Way = PromptWay
// What's chosen, what runs (no chat model: Direct), and the tab the menu shows. With no
// chat model, choosing the brand's tab shows why it can't run, and keeps it as the choice
// for when a model is set up.
const way = computed<Way>(() => (props.raw ? 'raw' : props.direct ? 'direct' : 'fluent'))
const running = computed<Way>(() => effectiveWay({ raw: props.raw, direct: props.direct, llmUnconfigured: props.llmUnconfigured }))
const peek = ref<Way | null>(null)
const tab = computed<Way>(() => peek.value ?? running.value)
watch([menuOpen, () => props.llmUnconfigured], () => { peek.value = null })
// What Fluent honestly does with the current setting: fresh choices always; the
// model's own style only when it upsamples.
const tagline = computed(() => {
  // Name the features plainly; don't explain them.
  const model = props.modelName || 'the model'
  if (tab.value === 'raw') return `Your prompt goes to ${model} exactly as you typed it.`
  if (tab.value === 'direct') return 'Fills in your lists and saved wildcards.'
  if (props.enhance === 'expand' || props.program.unsupported.value)
    return `AI fills in your wildcards, follows your comments, and expands your prompt into the detailed style ${model} works best with.`
  return props.enhance === 'fill'
    ? `AI fills in your wildcards and follows your comments, keeping your wording and adding only what ${model} needs.`
    : 'AI fills in your wildcards and follows your comments, keeping your wording.'
})
const translating = computed(() => !props.raw && !props.llmUnconfigured && !!props.translate?.enabled)
const languageCode = computed(() => props.translate?.language ?? DEFAULT_TRANSLATE_LANGUAGE)
const languageLabel = computed(() => promptLanguageByCode(languageCode.value)?.label ?? languageCode.value)
const languageOptions = computed(() => [
  { code: null as string | null, label: 'Off', english: '', picked: !translating.value },
  ...PROMPT_LANGUAGES.map(l => ({ code: l.code as string | null, label: l.label, english: l.english === l.label ? '' : l.english, picked: translating.value && languageCode.value === l.code })),
])
const detail = computed(() => props.enhance === 'expand' || props.program.unsupported.value)
const on = computed(() => running.value === 'fluent')
const busy = computed(() => on.value && props.program.status.value === 'busy')
const failed = computed(() => on.value && props.program.status.value === 'error')


const chipText = computed(() => {
  if (running.value === 'raw') return 'Raw'
  if (running.value === 'direct') return 'Direct'
  return props.enhance === 'off' && !props.program.unsupported.value ? `${BRAND} · your words` : BRAND
})
const chipTitle = computed(() => {
  const t = chipTitleBase.value
  return translating.value ? `${t} · translated to ${promptLanguageByCode(languageCode.value)?.english ?? languageLabel.value}` : t
})
const chipTitleBase = computed(() => {
  if (running.value === 'raw') return 'Raw: sent exactly as typed'
  if (running.value === 'direct') return props.llmUnconfigured && way.value === 'fluent'
    ? `Direct: ${BRAND} needs a chat model`
    : 'Direct: lists and saved wildcards filled in'
  if (busy.value) return `Preparing your prompt…${props.previousRunning ? ' Images use your previous prompt until it’s ready.' : ''}`
  if (failed.value) return `${BRAND} couldn’t read this prompt`
  return detail.value ? `${BRAND}, adding detail` : props.enhance === 'fill' ? `${BRAND}, adding a little detail` : `${BRAND}, in your own words`
})

type Action = { label: string; run: () => void }
type Notice = { head: string; body?: string; detail?: string; tone?: 'bad'; actions?: Action[] }
const useDirect: Action = { label: 'Use Direct', run: () => { menuOpen.value = false; emit('way', 'direct') } }
const notice = computed<Notice | null>(() => {
  if (tab.value !== 'fluent') return null
  if (props.llmUnconfigured) return {
    head: 'Needs a chat model',
    actions: [{ label: 'Set one up', run: () => { menuOpen.value = false; window.dispatchEvent(new CustomEvent('open-settings', { detail: 'ai-services' })) } }],
  }
  if (busy.value) return {
    head: 'Preparing your prompt…',
    body: props.previousRunning ? 'Images use your previous prompt until it’s ready.' : undefined,
  }
  if (failed.value) {
    const unreachable = props.program.error.value?.code === 'llm_unavailable'
    return {
      head: unreachable ? 'Can’t reach your chat model' : 'Couldn’t read this prompt',
      tone: 'bad',
      detail: devModeRef.value ? props.program.error.value?.message : undefined,
      actions: [{ label: 'Try again', run: () => { void props.program.prepare(true) } }, useDirect],
    }
  }
  return null
})

// "Try different …": a fresh take on exactly what was written (the choices' options and,
// at High, the wording), named for what changes.
const retake = computed(() => {
  if (!on.value || props.program.status.value !== 'ready') return null
  const names = props.program.choices.value.filter(c => !c.hidden && c.kind === 'pick' && c.source !== 'list').map(c => c.label)
  const words = detail.value
  if (!names.length && !words) return null
  // Phrased as why you'd want it: you don't like what you got.
  const label = names.length && words ? 'Try different choices and wording' : names.length ? 'Try different choices' : 'Try different wording'
  return { label }
})

function pickWay(id: Way) {
  // The menu stays open: choosing a tab shows its settings right under it.
  peek.value = id === 'fluent' && props.llmUnconfigured ? 'fluent' : null
  if (id !== way.value) emit('way', id)
}

const menuStyle = ref<Record<string, string>>({})
const MENU_W = 320  // w-80
function toggle() {
  if (!menuOpen.value) {
    const r = chip.value?.getBoundingClientRect()
    if (r) {
      const below = window.innerHeight - r.bottom - 12
      const above = r.top - 12
      const down = below >= 380 || below >= above
      menuStyle.value = {
        left: `${Math.max(8, Math.min(window.innerWidth - MENU_W - 8, r.left - 6))}px`,
        maxHeight: `${Math.max(200, down ? below : above)}px`,
        ...(down ? { top: `${r.bottom + 4}px` } : { bottom: `${window.innerHeight - r.top + 4}px` }),
      }
    }
  }
  menuOpen.value = !menuOpen.value
}

// Teleported to the end of the page, so focus moves in when the menu opens, Tab stays
// inside it, and focus goes back to the chip when it closes.
watch(menuOpen, (open) => {
  if (open) void nextTick(() => focusables()[0]?.focus())
  else if (!menuEl.value || menuEl.value.contains(document.activeElement) || document.activeElement === document.body) chip.value?.focus()
}, { flush: 'pre' })
function focusables(): HTMLElement[] {
  return [...(menuEl.value?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])]
    .filter(el => !el.closest('[inert]'))
}
function trapTab(e: KeyboardEvent) {
  const all = focusables()
  if (!all.length) return
  const i = all.indexOf(document.activeElement as HTMLElement)
  const next = e.shiftKey ? (i <= 0 ? all.length - 1 : i - 1) : (i === -1 || i === all.length - 1 ? 0 : i + 1)
  all[next].focus()
  e.preventDefault()
}

// Escape closes the dialog, then the menu. Both are teleported, so listen on the window.
function onKey(e: KeyboardEvent) {
  if (e.key === 'Tab' && menuOpen.value && programText.value === null && !languagesOpen.value) { trapTab(e); return }
  if (e.key !== 'Escape') return
  if (programText.value !== null) programText.value = null
  else if (languagesOpen.value) languagesOpen.value = false
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
