<template>
  <div class="relative" :style="sizeVars">
    <!-- Main Prompt Editor -->
    <div class="relative rounded-md border border-transparent bg-field focus-within:border-accent transition-colors [&_.cm-editor]:!bg-transparent">
      <div ref="editorMount"></div>
      <!-- Host-supplied extras: a row under the text. -->
      <slot name="below-editor" />
      <!-- Fluent: things the prompt doesn't mention that could vary. -->
      <PromptSlotAdds v-if="slotAdds.length" :adds="slotAdds" :adding="adding" @add="addSlot" />

      <!-- Words that could become a slot: a phrase Fluent underlined, or a selection. -->
      <Teleport to="body">
        <div v-if="offer" class="fixed z-menu" :style="offerStyle" data-slot-offer>
          <button
            type="button"
            class="flex items-center gap-1.5 px-2.5 py-1.5 coarse:px-3 coarse:py-2 text-xs coarse:text-[13px] rounded-lg bg-surface border border-edge-subtle shadow-lg text-content hover:bg-surface-hover transition-colors"
            data-vary
            @mousedown.prevent
            @click="varyOffer"
          ><ArrowsRightLeftIcon class="w-3.5 h-3.5 text-selection" />Vary this</button>
        </div>
      </Teleport>

      <!-- Bottom Action Bar (flows below textarea): a single quiet ghost row
           (DESIGN.md §3.3). Every control here is monochrome text/icons, 11px,
           no pills — the AI sparkle is the only colored glyph in the bar. -->
      <div class="px-3 py-1.5 flex items-center justify-between rounded-b-md">
        <!-- Left: generate-time prompt pipeline (hidden in flow context — flows
             execute the literal prompt, so rewriting it would diverge from the
             declared input). Reads left→right: Enhance Prompt → Translate Prompt.
             Enhance is family-aware (prose / keywords / cinematography / Ideogram
             JSON) — the style is chosen automatically from the tool's model. -->
        <div v-if="!hideAutoImprove" class="flex items-center gap-3">
          <!-- A host's own prompt control (Tool View's Fluent) replaces Enhance and Raw. -->
          <slot name="mode" :open-help="openHelp" />
          <!-- Enhance Prompt toggle. With no LLM configured the chip stays
               visible but inert — a quiet hint of what configuring one adds.
               The stored setting is untouched, so it resumes when a model
               appears. -->
          <button
            v-if="!hasMode"
            :disabled="llmUnconfigured"
            :aria-pressed="!llmUnconfigured && promptOptions.autoImprove.enabled"
            @click="updatePromptOption('autoImprove', { ...promptOptions.autoImprove, enabled: !promptOptions.autoImprove.enabled })"
            :class="[
              'flex items-center gap-1.5 text-ctl transition-colors -mx-1.5 px-1.5 py-0.5 rounded-md',
              llmUnconfigured
                ? 'text-content-muted opacity-50 cursor-not-allowed'
                : promptOptions.autoImprove.enabled
                  ? 'text-content bg-overlay-subtle'
                  : 'text-content-muted hover:text-content-secondary'
            ]"
            :title="llmUnconfigured
              ? 'Requires a chat model. Add one in Settings > Chat Models.'
              : 'Enhance the prompt with AI when generating'"
          >
            <WandSparklesIcon class="w-3.5 h-3.5" />
            <span>Enhance</span>
          </button>

          <!-- Translate Prompt chip: the whole chip opens the menu (one big hit target).
               On/off lives in the menu as the "Off" choice — same place you pick
               a language — so there's one obvious control surface. -->
          <!-- A host prompt control (Tool View's Fluent) carries Translate in its own menu. -->
          <div v-if="!hasMode" class="relative flex items-center" ref="translateMenuContainer">
            <button
              ref="translateButton"
              :disabled="llmUnconfigured"
              @click="toggleTranslateMenu"
              :class="[
                'flex items-center gap-1.5 text-ctl transition-colors',
                llmUnconfigured
                  ? 'text-content-muted opacity-50 cursor-not-allowed'
                  : translateActive
                    ? 'text-accent-hi'
                    : 'text-content-muted hover:text-content-secondary'
              ]"
              :title="llmUnconfigured
                ? 'Requires a chat model. Add one in Settings > Chat Models.'
                : translateActive
                  ? `Translating the prompt to ${activeLanguageLabel} before generating`
                  : 'Translate the prompt into another language before generating'"
            >
              <LanguageIcon class="w-3.5 h-3.5" />
              <span>{{ translateActive ? activeLanguageLabel : 'Translate' }}</span>
              <Caret :open="showTranslateMenu" class="opacity-70" />
            </button>

            <!-- Menu teleported to <body> with fixed positioning so it escapes
                 the editor's scroll/overflow clipping (which was cutting off the
                 top "Off" row). Anchored to the chip, above it when there is room. -->
            <Teleport to="body">
              <div
                v-if="showTranslateMenu"
                ref="translateMenuEl"
                class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu w-48 overflow-y-auto"
                :style="translateMenuPos"
              >
                <div class="px-3 pt-1 pb-1.5 text-ctl font-semibold text-content-secondary">
                  Translate prompt to
                </div>
                <button
                  @click="setTranslate(null)"
                  class="w-full text-left px-3 py-1.5 text-[12px] flex items-center justify-between gap-2 hover:bg-overlay-subtle transition-colors"
                  :class="!translateActive ? 'text-accent' : 'text-content-secondary'"
                >
                  <span>Off</span>
                  <CheckIcon v-if="!translateActive" class="w-3.5 h-3.5 shrink-0" />
                </button>
                <div class="border-t border-edge-subtle my-1"></div>
                <button
                  v-for="lang in PROMPT_LANGUAGES"
                  :key="lang.code"
                  @click="setTranslate(lang.code)"
                  class="w-full text-left px-3 py-1.5 flex items-center justify-between gap-2 hover:bg-overlay-subtle transition-colors"
                  :class="translateActive && activeLanguageCode === lang.code ? 'text-accent' : 'text-content-secondary'"
                >
                  <span class="flex flex-col leading-tight">
                    <span class="text-[12px]">{{ lang.label }}</span>
                    <span
                      class="text-[10px]"
                      :class="translateActive && activeLanguageCode === lang.code ? 'text-accent/70' : 'text-content-tertiary'"
                    >{{ lang.english }}</span>
                  </span>
                  <CheckIcon v-if="translateActive && activeLanguageCode === lang.code" class="w-3.5 h-3.5 shrink-0" />
                </button>
              </div>
            </Teleport>
          </div>
        </div>
        <span v-else></span>

        <!-- Right: Inline toggles + Help + AI Sparkle. Shown on phones too: the
             menu holds Send exactly as typed and the syntax help. -->
        <div class="flex items-center gap-1.5">
          <!-- Editor options: keybindings, font and syntax help live behind one
               quiet control (the labels Std / Sans / Help meant nothing on
               their own). -->
          <div class="relative flex items-center" ref="helpPopoverContainer">
            <OverflowButton
              label="Prompt editor options"
              :active="showEditorMenu || (showHelp && !helpFromHost)"
              @click="toggleEditorMenu"
            />
            <!-- Teleported with fixed positioning, like the Translate menu: inside the
                 phone's settings sheet an inline menu sits under the sheet backdrop. -->
            <Teleport to="body">
              <div
                v-if="showEditorMenu"
                data-prompt-editor-menu
                class="fixed py-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu w-56"
                :style="editorMenuPos"
                role="menu"
              >
                <button
                  role="menuitemcheckbox"
                  :aria-checked="vimEnabled"
                  class="w-full flex items-center gap-2 px-3 py-2 text-xs compact:hidden text-content-secondary hover:bg-overlay-subtle transition-colors"
                  :title="vimEnabled ? 'Switch to regular keybindings' : 'Switch to Vim keybindings'"
                  @click="toggleVim(); showEditorMenu = false"
                >
                  <span class="flex-1 text-left">Vim keybindings</span>
                  <CheckIcon v-if="vimEnabled" class="w-3.5 h-3.5 shrink-0 text-accent-hi" />
                </button>
                <button
                  role="menuitemcheckbox"
                  :aria-checked="monospaceEnabled"
                  class="w-full flex items-center gap-2 px-3 py-2 text-xs coarse:py-3 coarse:text-[13px] text-content-secondary hover:bg-overlay-subtle transition-colors"
                  :title="monospaceEnabled ? 'Switch to proportional font' : 'Switch to monospace font'"
                  @click="toggleMonospace(); showEditorMenu = false"
                >
                  <span class="flex-1 text-left">Monospace font</span>
                  <CheckIcon v-if="monospaceEnabled" class="w-3.5 h-3.5 shrink-0 text-accent-hi" />
                </button>
                <div v-if="!hasMode" class="my-1 border-t border-edge-subtle"></div>
                <button
                  v-if="!hasMode"
                  role="menuitem"
                  class="w-full flex items-center gap-2 px-3 py-2 text-xs coarse:py-3 coarse:text-[13px] text-content-secondary hover:bg-overlay-subtle transition-colors"
                  title="Prompt syntax help"
                  @click="showHelp = true; showEditorMenu = false"
                >
                  <span class="flex-1 text-left">Prompt syntax help</span>
                </button>
              </div>

              <!-- Help popover -->
              <div
                v-if="showHelp"
                data-prompt-editor-menu
                :class="['fixed p-4 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu max-w-[calc(100vw-16px)] overflow-y-auto overscroll-contain', hasMode ? 'w-96' : 'w-80']"
                :data-prompt-tips="hasMode || undefined"
                :style="editorMenuPos"
              >
                <div class="flex items-center justify-between mb-3">
                  <span v-if="hasMode" class="text-[13px] font-semibold text-content">Prompt tips</span>
                  <span v-else class="text-xs font-medium text-content-secondary">Prompt syntax</span>
                  <button @click="showHelp = false" aria-label="Close" class="text-content-muted hover:text-content-secondary p-0.5 coarse:p-3 coarse:-m-3">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                <!-- Tool View: what Fluent does, then one section per thing you can write, slots first.
                     Elsewhere: the same sections for what that editor reads (lists, saved names,
                     comment lines, exact text). -->
                <template v-if="hasMode">
                  <p v-if="tipsWay" class="mb-2.5 rounded-md bg-overlay-subtle px-2.5 py-2 text-xs text-content-secondary leading-relaxed" data-tips-way>{{ tipsWay }}</p>
                  <p class="text-xs text-content-secondary leading-relaxed">{{ fluentIntro }}</p>
                </template>
                <PromptTipSections :tips="shownTips" :ruled="hasMode" />
                <template v-if="!hasMode">
                <!-- Divider -->
                <div v-if="!hideAutoImprove" class="border-t border-edge-subtle my-3"></div>

                <!-- Enhance Prompt -->
                <div v-if="!hideAutoImprove">
                  <div class="flex items-center gap-1.5 mb-1">
                    <WandSparklesIcon class="w-3 h-3 text-accent" />
                    <span class="text-xs font-medium text-content-secondary">Enhance prompt</span>
                  </div>
                  <p class="text-xs text-content-tertiary leading-relaxed">
                    When enabled, your prompt is automatically enhanced by AI each time you generate. The original prompt stays in the editor; only the version sent to the generation tool is improved.
                  </p>
                </div>
                </template>
              </div>
            </Teleport>
          </div>

          <!-- AI Sparkle Button — toggles the inline prompt-only chat. Hidden when
               externalChat is set (ToolView renders a page-level chat in its dock,
               so a per-prompt sparkle would be redundant + visually awkward).
               The sparkle is the one colored (accent) glyph in this bar. -->
          <button
            v-if="!externalChat && !llmUnconfigured"
            @click="toggleExpanded"
            :class="[
              'p-1 rounded-md transition-colors',
              expanded
                ? 'text-accent bg-accent/15 hover:bg-accent/20'
                : 'text-content-muted hover:text-accent hover:bg-overlay-subtle'
            ]"
            title="AI Prompt Enhancement"
          >
            <SparklesIcon class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- Inline prompt-only chat (flow / image-edit). Toggled by the sparkle.
         ToolView sets external-chat and mounts its own page-level PromptAgentChat
         in the dock instead, so this branch never renders there. -->
    <div
      v-if="!externalChat && expanded"
      class="mt-2 p-3 bg-surface-overlay border border-edge-subtle rounded-md"
    >
      <PromptAgentChat
        :editor="selfHandle"
        :prompt="modelValue"
        :has-prompt="true"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted, useSlots } from 'vue'
import { EditorView } from '@codemirror/view'
import { ArrowsRightLeftIcon } from '@heroicons/vue/24/outline'
import type { PromptEditorHandle } from '../../composables/promptEditorHandle'
import { SparklesIcon, LanguageIcon, CheckIcon } from '@heroicons/vue/24/solid'
import Caret from '../ui/Caret.vue'
import OverflowButton from '../ui/OverflowButton.vue'
import { useWildcards, useSegments } from '../../composables/useWildcards'
import { PROMPT_BRAND, fluentEnabled } from './promptBrand'
import PromptTipSections from './PromptTipSections.vue'
import { classicTips, fluentIntro, fluentTips } from './promptTips'
import type { PromptSyntaxMode } from '../../composables/useCodeMirrorPrompt'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import PromptAgentChat from './PromptAgentChat.vue'
import { useCodeMirrorPrompt } from '../../composables/useCodeMirrorPrompt'
import { slotEditing, wrapSlot, replaceDocument, rangeRect, setVaryEffect } from '../../composables/promptSlotEditing'
import { setSlotMarks, slotMarks as slotMarksExtension, type SlotMarks } from '../../composables/promptSlotMarks'
import { shownAdds, usePromptSuggestions, type ReadSlots } from '../../composables/usePromptSuggestions'
import { findSlots, slotAt, slotWrapRange, usableVaryPhrases } from '../../utils/promptSyntax'
import PromptSlotAdds from './PromptSlotAdds.vue'
import { useAgentModelAvailability } from '../../composables/useAgentModelAvailability'
import { useViewport } from '../../composables/useViewport'
import { PROMPT_LANGUAGES, promptLanguageByCode, DEFAULT_TRANSLATE_LANGUAGE } from './promptLanguages'

interface PromptOptionSetting {
  enabled: boolean
  instructions: string
}

interface TranslateSetting {
  enabled: boolean
  language: string
}

interface PromptOptions {
  autoImprove: PromptOptionSetting
  varyPrompt: PromptOptionSetting
  translate?: TranslateSetting
  /** Tool View's prompt menu: sent exactly as typed. */
  raw?: boolean
  /** Tool View's prompt menu: the prompt as written, no model. */
  direct?: boolean
}

interface Props {
  modelValue: string
  rows?: number
  placeholder?: string
  expanded?: boolean
  promptOptions?: PromptOptions
  // Flow inputs run the literal prompt through the declared graph, so the
  // generate-time pipeline (which silently rewrites the prompt at submit time)
  // would break the execution model. Hide the affordances in those contexts.
  hideAutoImprove?: boolean
  /** The prompt runs as a prepared program (Tool View's Fluent with a chat model): its
      <slots> vary, and # lines are read whether Enhance is on or off. */
  programs?: boolean
  /** Extra fields for Fluent's Suggest and Add requests (the project, whose chat model answers). */
  suggestContext?: Record<string, unknown>
  /** What the prompt's slots were read as, once read: a photography add a slot already is
      isn't offered. */
  readSlots?: ReadSlots | null
  /** The host fills the `mode` slot with its own prompt control (Tool View's Fluent),
      replacing Enhance, Raw and the … help entry. A prop, not a slot check: slots
      aren't reactive, and the host can switch this at runtime. */
  promptControl?: boolean
  /** How each slot shows what is chosen for it (Fluent's marks); null: the plain slot look. */
  slotMarks?: SlotMarks | null
  // When set, this editor renders no chat affordance of its own (no sparkle, no
  // inline panel). The embedder (ToolView) owns a page-level PromptAgentChat and
  // drives this editor through the exposed handle.
  externalChat?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  rows: 19,
  placeholder: 'Describe the image you want to generate...',
  expanded: false,
  promptOptions: () => ({
    autoImprove: { enabled: false, instructions: '' },
    varyPrompt: { enabled: false, instructions: '' },
    translate: { enabled: false, language: DEFAULT_TRANSLATE_LANGUAGE },
  }),
  hideAutoImprove: false,
  externalChat: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:expanded', value: boolean): void
  (e: 'update:promptOptions', value: PromptOptions): void
  /** Vim :w / :wq / :x: the prompt is done. */
  (e: 'save'): void
  /** Open a slot's choices. `n` is its 1-based order among the prompt's slots (comment
      lines and [verbatim] left out, as the grammar finds them); `rect` is where its
      words are on screen. Sent when a slot is clicked and right after one is made. */
  (e: 'open-slot', value: { n: number; words: string; rect: DOMRect }): void
  /** The pointer is over a slot (its place and where it is), or over none (null). */
  (e: 'slot-hover', value: { n: number; rect: DOMRect } | null): void
}>()

// Box height. Desktop rests at ~5 lines and grows to 408px; phones give the
// prompt a few lines (more on a roomy inner screen) and let it grow a little,
// so the parameters stay in view. 21px is one 14px line at 1.5.
const { isCompact, isRoomy } = useViewport()
const sizeVars = computed(() => {
  // Desktop rests at about five lines and grows with the text up to the
  // editor's own cap; the controls below stay close to the placeholder.
  if (!isCompact.value) return { '--prompt-min-h': `${Math.min(props.rows, 5) * 21 + 8}px` }
  const lines = Math.min(props.rows, isRoomy.value ? 4 : 3)
  return {
    '--prompt-min-h': `${lines * 21 + 8}px`,
    '--prompt-max-h': isRoomy.value ? '260px' : '160px',
  }
})

// Refs
const editorMount = ref<HTMLElement | null>(null)
const helpPopoverContainer = ref<HTMLElement | null>(null)
const showHelp = ref(false)
// Help opened from the host's control (Fluent), not from …, so … shouldn't look pressed.
const helpFromHost = ref(false)
const showEditorMenu = ref(false)
// Fixed coords for the teleported menu and help, anchored to the … button.
const editorMenuPos = ref<Record<string, string>>({})
function toggleEditorMenu() {
  const rect = helpPopoverContainer.value?.getBoundingClientRect()
  if (rect && !showEditorMenu.value) {
    const roomBelow = window.innerHeight - rect.bottom - 14
    const roomAbove = rect.top - 14
    const down = roomBelow >= 320 || roomBelow >= roomAbove
    editorMenuPos.value = {
      right: `${Math.max(8, Math.round(window.innerWidth - rect.right))}px`,
      maxHeight: `${Math.min(520, down ? roomBelow : roomAbove)}px`,
      ...(down
        ? { top: `${Math.round(rect.bottom + 4)}px` }
        : { bottom: `${Math.round(window.innerHeight - rect.top + 4)}px` }),
    }
  }
  showEditorMenu.value = !showEditorMenu.value
  showHelp.value = false
  helpFromHost.value = false
}
/** Open the syntax help on its own, anchored to the host's control that asked for it
    (or to … when there's none). */
function openHelp(anchor?: DOMRect | null) {
  showEditorMenu.value = false
  toggleEditorMenu()  // computes the position from …
  showEditorMenu.value = false
  if (anchor) {
    const below = window.innerHeight - anchor.bottom - 14
    const above = anchor.top - 14
    const down = below >= 320 || below >= above
    editorMenuPos.value = {
      left: `${Math.max(8, Math.min(window.innerWidth - 392, Math.round(anchor.left - 6)))}px`,
      maxHeight: `${Math.min(720, down ? below : above)}px`,
      ...(down ? { top: `${Math.round(anchor.bottom + 4)}px` } : { bottom: `${Math.round(window.innerHeight - anchor.top + 4)}px` }),
    }
  }
  // After this click finishes, or the outside-click handler would close it again.
  setTimeout(() => { showHelp.value = true; helpFromHost.value = true })
}
const translateMenuContainer = ref<HTMLElement | null>(null)
const translateButton = ref<HTMLElement | null>(null)
const translateMenuEl = ref<HTMLElement | null>(null)
const showTranslateMenu = ref(false)
// Fixed coords for the teleported menu, anchored above the chip (opens upward).
const translateMenuPos = ref<Record<string, string>>({})

// No LLM configured at all (deliberate opt-out) → the generate-time pipeline
// chips gray out and the inline chat affordance hides. A configured-but-broken
// LLM leaves everything interactive; failures surface at generate time.
const { llmUnconfigured, checkAgentModels } = useAgentModelAvailability()
void checkAgentModels()

function toggleTranslateMenu() {
  if (llmUnconfigured.value) return
  if (!showTranslateMenu.value) {
    const rect = translateButton.value?.getBoundingClientRect()
    if (rect) {
      // Opens upward unless the prompt sits too near the top of the window.
      const roomAbove = rect.top - 14
      const roomBelow = window.innerHeight - rect.bottom - 14
      const up = roomAbove >= 320 || roomAbove >= roomBelow
      translateMenuPos.value = {
        left: `${Math.round(rect.left)}px`,
        maxHeight: `${Math.min(320, up ? roomAbove : roomBelow)}px`,
        ...(up
          ? { bottom: `${Math.round(window.innerHeight - rect.top + 6)}px` }
          : { top: `${Math.round(rect.bottom + 6)}px` }),
      }
    }
  }
  showTranslateMenu.value = !showTranslateMenu.value
}

// --- Translate state (generate-time pipeline) ---
const translateActive = computed(() => !!props.promptOptions.translate?.enabled)
const activeLanguageCode = computed(() => props.promptOptions.translate?.language ?? DEFAULT_TRANSLATE_LANGUAGE)
const activeLanguageLabel = computed(
  () => promptLanguageByCode(activeLanguageCode.value)?.label ?? 'Translate'
)

// Pick a target language from the menu (also turns translation on); passing
// null is the "Off" choice. This is the single control surface for translation.
function setTranslate(code: string | null) {
  updatePromptOption('translate', {
    enabled: !!code,
    language: code ?? activeLanguageCode.value,
  })
  showTranslateMenu.value = false
}

// --- Slots (Fluent): making one from written words, opening one ---
// A phrase Fluent underlined was clicked, or words were selected: "Vary this" sits under them.
const offer = ref<{ from: number; to: number; rect: DOMRect; phrase: boolean } | null>(null)
const { isCoarsePointer } = useViewport()
const offerStyle = computed(() => {
  const r = offer.value?.rect
  if (!r) return {}
  // On touch the selection handles hang under the words: clear them.
  let top = r.bottom + (isCoarsePointer.value ? 28 : 6)
  if (top + 44 > window.innerHeight) top = r.top - 44
  const left = Math.max(8, Math.min(window.innerWidth - 120, r.left))
  return { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` }
})
function showOffer(from: number, to: number, phrase: boolean) {
  const view = getView()
  const rect = view && rangeRect(view, from, to)
  offer.value = rect ? { from, to, rect, phrase } : null
}
/** Tell the host to open the slot around `pos`. */
function openSlotAt(pos: number) {
  const view = getView()
  if (!view) return
  const slot = slotAt(view.state.doc.toString(), pos)
  const rect = slot && rangeRect(view, slot.from, slot.to)
  if (slot && rect) emit('open-slot', { n: slot.n, words: slot.words, rect })
}
function varyOffer() {
  const view = getView()
  const o = offer.value
  offer.value = null
  if (!view || !o) return
  const at = wrapSlot(view, o.from, o.to)
  if (at != null) void nextTick(() => openSlotAt(at))
}
function hideOffer() { offer.value = null }
const slotExtensions = [
  slotEditing({
    enabled: () => fluentSlots.value,
    onSlotClick: (pos) => { offer.value = null; openSlotAt(pos) },
    onPhraseClick: (p) => showOffer(p.from, p.to, true),
    onSelection: ({ from, to }) => {
      if (from === to) {
        // The click that offered an underlined phrase leaves the cursor in it.
        const o = offer.value
        if (!(o?.phrase && from >= o.from && from <= o.to)) offer.value = null
        return
      }
      const at = slotWrapRange(getView()?.state.doc.toString() ?? '', from, to)
      if (at) showOffer(at[0], at[1], false)
      else offer.value = null
    },
    onWrapped: (from) => { offer.value = null; void nextTick(() => openSlotAt(from)) },
    onMoved: hideOffer,
  }),
  EditorView.domEventHandlers({
    keydown(e) { if (e.key === 'Escape') offer.value = null; return false },
  }),
  slotMarksExtension({
    onHover: (n, rect) => emit('slot-hover', n && rect && fluentSlots.value ? { n, rect } : null),
    // A slot's dot or thumbnail opens it, as its words do.
    onGlyph: (n) => {
      const view = getView()
      const at = view ? findSlots(view.state.doc.toString())[n - 1] : null
      if (at && fluentSlots.value) { offer.value = null; openSlotAt(at[0] + 1) }
    },
  }),
]

// CodeMirror composable
const { vimEnabled, monospaceEnabled, toggleVim, toggleMonospace, setContent, applyDiffDecorations, clearDiffDecorations, selectLine, setSyntax, getView } =
  useCodeMirrorPrompt({
    mountRef: editorMount,
    modelValue: () => props.modelValue,
    placeholder: props.placeholder,
    onChange: (value: string) => {
      emit('update:modelValue', value)
    },
    // Leaving the box asks Fluent for suggestions now rather than after the pause.
    onBlur: () => { offer.value = null; void suggestNow() },
    onSave: () => emit('save'),
    extensions: slotExtensions,
  })

// --- How the prompt will be read: Raw, by a model (a program, or Enhance), or plain (no model) ---
// Raw and the newer highlighting ship with Fluent (see promptBrand.ts). Raw is Tool
// View's (its prompt menu); other editors have no Raw.
// A host with its own prompt control (Tool View's Fluent, in the mode slot) owns Enhance,
// Raw and the syntax help's entry point.
const slots = useSlots()
const hasMode = computed(() => !!props.promptControl && !!slots.mode)
const rawMode = computed(() => fluentEnabled.value && hasMode.value && !!props.promptOptions.raw)
// Slots vary here: Tool View's Fluent, preparing programs (not Direct, Raw or a format it
// can't prepare).
const fluentSlots = computed(() => hasMode.value && !!props.programs && !rawMode.value && !props.promptOptions.direct)
watch(fluentSlots, on => { if (!on) offer.value = null })
// Fluent's marks follow what is chosen; off (Direct, Raw), slots keep their plain look.
function showMarks() {
  getView()?.dispatch({ effects: setSlotMarks.of(fluentSlots.value ? props.slotMarks ?? null : null) })
}
watch([() => props.slotMarks, fluentSlots], showMarks, { flush: 'post' })

// Suggest: phrases that could vary (underlined) and things worth adding (chips under the text).
const { answer, adding, suggestNow, add } = usePromptSuggestions({
  prompt: () => props.modelValue,
  active: () => fluentSlots.value,
  context: () => props.suggestContext,
})
watch([answer, fluentSlots, () => props.modelValue], () => {
  const view = getView()
  if (!view) return
  const text = view.state.doc.toString()
  if (!fluentSlots.value || !text.trim()) view.dispatch({ effects: setVaryEffect.of([]) })
  // A fresh answer for the text as it stands; between answers the marks follow the edits.
  else if (answer.value?.text === text) view.dispatch({ effects: setVaryEffect.of(usableVaryPhrases(text, answer.value.suggestions.vary)) })
}, { flush: 'post' })
const slotAdds = computed(() => {
  const text = props.modelValue
  if (!fluentSlots.value || !text.trim() || !answer.value) return []
  // Not something the prompt already has as a slot: by its words, or read as what it is; then capped.
  const have = new Set(findSlots(text).map(([from, to]) => text.slice(from + 1, to - 1).trim().toLowerCase()))
  return shownAdds(answer.value.suggestions.adds, props.readSlots, have)
})
/** Have Fluent write `name` into the prompt as a slot (one undo step), then open it. */
async function addSlot(name: string) {
  const r = await add(name)
  const view = getView()
  if (!r || !view || !slotAt(r.prompt, r.slot.from)) return
  offer.value = null
  replaceDocument(view, r.prompt)
  void nextTick(() => openSlotAt(r.slot.from))
}
// The tips panel in Tool View: what you can type, slots first, in the user's words. Each kind
// of mark wears its color in the editor (useCodeMirrorPrompt's theme).
const shownTips = computed(() => (hasMode.value ? fluentTips : classicTips))
// In Direct or Raw, a line on top says what this way does with the rest.
const tipsWay = computed(() =>
  rawMode.value ? `Raw sends your prompt exactly as typed. Choose ${PROMPT_BRAND} or Direct to use the rest.`
    : props.promptOptions.direct ? `Direct fills in lists and saved wildcards. Slots are sent as their words. Choose ${PROMPT_BRAND} to vary them.`
    : '')
const { wildcards } = useWildcards()
const { segments } = useSegments()
const syntaxMode = computed<PromptSyntaxMode>(() =>
  !fluentEnabled.value ? 'enhance'
    : rawMode.value ? 'raw'
    // Flow inputs don't run the prompt pipeline here; keep their highlighting as it was.
    : props.promptOptions.direct && hasMode.value ? 'plain'
    : props.hideAutoImprove || props.programs || (!llmUnconfigured.value && props.promptOptions.autoImprove?.enabled) ? 'enhance'
    : 'plain')
watch([syntaxMode, wildcards, segments], () => {
  setSyntax(syntaxMode.value, [...wildcards.value.map(w => w.name), ...segments.value.map(sg => sg.name)])
}, { immediate: true })

// Diff segment type (used by computeWordDiff)
interface DiffSegment {
  text: string
  type: 'added' | 'removed' | 'unchanged'
}

// Update prompt options helpers
function updatePromptOption<K extends keyof PromptOptions>(key: K, value: PromptOptions[K]) {
  emit('update:promptOptions', { ...props.promptOptions, [key]: value })
}

// Toggle the inline AI chat panel.
function toggleExpanded() {
  emit('update:expanded', !props.expanded)
}

/**
 * Compute a word-level diff between two strings.
 * Returns segments marking added, removed, and unchanged words.
 */
function computeWordDiff(oldText: string, newText: string): DiffSegment[] {
  const splitWithWhitespace = (text: string): string[] => {
    const result: string[] = []
    let current = ''
    let inWhitespace = false

    for (const char of text) {
      const isWs = /\s/.test(char)
      if (isWs !== inWhitespace && current) {
        result.push(current)
        current = ''
      }
      current += char
      inWhitespace = isWs
    }
    if (current) result.push(current)
    return result
  }

  const oldWords = splitWithWhitespace(oldText)
  const newWords = splitWithWhitespace(newText)

  const m = oldWords.length
  const n = newWords.length

  const dp: number[][] = Array(m + 1).fill(null).map(() => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldWords[i - 1] === newWords[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  const segments: DiffSegment[] = []
  let i = m, j = n

  const tempSegments: DiffSegment[] = []
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldWords[i - 1] === newWords[j - 1]) {
      tempSegments.unshift({ text: oldWords[i - 1], type: 'unchanged' })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      tempSegments.unshift({ text: newWords[j - 1], type: 'added' })
      j--
    } else {
      tempSegments.unshift({ text: oldWords[i - 1], type: 'removed' })
      i--
    }
  }

  for (const seg of tempSegments) {
    const last = segments[segments.length - 1]
    if (last && last.type === seg.type) {
      last.text += seg.text
    } else {
      segments.push({ ...seg })
    }
  }

  return segments
}

/**
 * Show animated diff decorations when prompt changes (driven by the chat after
 * a prompt-only enhance).
 */
function animateDiff(oldText: string, newText: string) {
  const segments = computeWordDiff(oldText, newText)
  const hasChanges = segments.some(s => s.type !== 'unchanged')
  if (!hasChanges) return

  applyDiffDecorations(segments)
  setTimeout(() => {
    clearDiffDecorations()
  }, 3200)
}

// Replace the entire prompt text (used by set_prompt / undo restore and the
// inline chat's prompt-only edits).
function setPromptText(text: string) {
  emit('update:modelValue', text)
  setContent(text)
}

// Handle the inline chat's prompt-only edits + diff animation through one stable
// object so PromptAgentChat doesn't depend on this component's internals.
const selfHandle: PromptEditorHandle = {
  getText: () => props.modelValue,
  setText: setPromptText,
  animateDiff,
}

// Click-outside handler for the popover menus
function handleClickOutside(event: MouseEvent) {
  // The menu and help are teleported to <body>: check them alongside the button.
  // By attribute, not ref: a menu item's own click may already have unmounted it.
  const path = event.composedPath()
  const inside = (!!helpPopoverContainer.value && path.includes(helpPopoverContainer.value))
    || path.some(n => n instanceof Element && n.hasAttribute('data-prompt-editor-menu'))
  if ((showHelp.value || showEditorMenu.value) && !inside) {
    showHelp.value = false
    showEditorMenu.value = false
  }
  // The menu is teleported to <body>, so check the button and the menu element
  // separately (it's no longer a DOM descendant of the chip container).
  if (
    showTranslateMenu.value &&
    !translateButton.value?.contains(event.target as Node) &&
    !translateMenuEl.value?.contains(event.target as Node)
  ) {
    showTranslateMenu.value = false
  }
}

// Sync external modelValue changes into CM6 editor
watch(() => props.modelValue, (newVal) => {
  setContent(newVal)
})

onMounted(() => {
  showMarks()
  document.addEventListener('click', handleClickOutside)
  // "Vary this" floats over the text: anything scrolling moves the words out from under it.
  window.addEventListener('scroll', hideOffer, true)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('scroll', hideOffer, true)
})

defineExpose({
  getText: () => props.modelValue,
  setPromptText,
  animateDiff,
  selectLine,
})
</script>

<style>
/* CM6 vim status bar — show pending operator / command line */
.cm-vim-panel {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--color-text-muted);
  background: var(--color-surface);
  border-top: 1px solid var(--color-border, rgba(255, 255, 255, 0.06));
  padding: 2px 12px;
  line-height: 1.5;
}
.cm-vim-panel input {
  font-family: inherit;
  font-size: inherit;
  color: var(--color-text-secondary);
  background: transparent;
  border: none;
  outline: none;
}

</style>
