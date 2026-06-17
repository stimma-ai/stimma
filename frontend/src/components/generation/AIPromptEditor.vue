<template>
  <div class="relative">
    <!-- Main Prompt Editor -->
    <div class="relative rounded-md border border-surface-raised focus-within:border-blue-500 transition-colors">
      <div ref="editorMount"></div>

      <!-- Bottom Action Bar (flows below textarea) -->
      <div class="px-3 py-1.5 flex items-center justify-between bg-surface rounded-b-md border-t border-surface-raised">
        <!-- Left: Auto-improve toggle (hidden in flow context — flows
             execute the literal prompt, so an auto-rewrite would diverge
             from the declared input). -->
        <button
          v-if="!hideAutoImprove"
          @click="updatePromptOption('autoImprove', { ...promptOptions.autoImprove, enabled: !promptOptions.autoImprove.enabled })"
          :class="[
            'flex items-center gap-1.5 text-[11px] transition-colors',
            promptOptions.autoImprove.enabled
              ? 'text-purple-500'
              : 'text-content-muted hover:text-content-muted'
          ]"
          title="Automatically improve prompts when generating"
        >
          <BoltIcon class="w-3 h-3" />
          <span>Auto-Improve</span>
        </button>
        <span v-else></span>

        <!-- Right: Inline toggles + Help + AI Sparkle -->
        <div class="flex items-center gap-1.5">
          <!-- Vim/Reg toggle -->
          <button
            @click="toggleVim"
            :class="[
              'text-[10px] font-mono font-medium px-1.5 py-0.5 rounded transition-colors',
              vimEnabled
                ? 'text-green-500 bg-green-500/10'
                : 'text-content-muted hover:text-content-secondary'
            ]"
            :title="vimEnabled ? 'Switch to regular keybindings' : 'Switch to Vim keybindings'"
          >
            {{ vimEnabled ? 'VIM' : 'STD' }}
          </button>

          <!-- Mono/Sans toggle -->
          <button
            @click="toggleMonospace"
            :class="[
              'text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors',
              monospaceEnabled
                ? 'text-blue-500 bg-blue-500/10 font-mono'
                : 'text-content-muted hover:text-content-secondary'
            ]"
            :title="monospaceEnabled ? 'Switch to proportional font' : 'Switch to monospace font'"
          >
            {{ monospaceEnabled ? 'MONO' : 'SANS' }}
          </button>

          <!-- Help button -->
          <div class="relative flex items-center" ref="helpPopoverContainer">
            <button
              @click="showHelp = !showHelp"
              :class="[
                'text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors',
                showHelp ? 'text-content-secondary bg-surface-raised' : 'text-content-muted hover:text-content-secondary'
              ]"
              title="Prompt syntax help"
            >
              HELP
            </button>

            <!-- Help popover -->
            <div
              v-if="showHelp"
              class="absolute top-full right-0 mt-2 p-4 bg-surface border border-surface-raised rounded-lg shadow-xl z-20 w-80"
            >
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-1.5">
                  <svg class="w-3 h-3 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" /></svg>
                  <span class="text-xs font-medium text-content-secondary">Prompt Syntax</span>
                </div>
                <button @click="showHelp = false" class="text-content-muted hover:text-content-secondary p-0.5">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <!-- Wildcards -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-1">
                  <code class="text-green-600 bg-green-500/10 px-1.5 py-0.5 rounded text-xs">{red|blue|green}</code>
                </div>
                <p class="text-xs text-content-tertiary leading-relaxed">
                  Picks one option randomly each time you generate. Great for improving variety.
                </p>
              </div>

              <!-- Named Wildcards -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-1">
                  <code class="text-amber-600 bg-amber-500/10 px-1.5 py-0.5 rounded text-xs" v-text="'{{name}}'"></code>
                </div>
                <p class="text-xs text-content-tertiary leading-relaxed">
                  Picks a random value from a named wildcard list defined in Settings &gt; Wildcards.
                </p>
              </div>

              <!-- Comments -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-1">
                  <code class="text-gray-500 italic bg-zinc-500/10 px-1.5 py-0.5 rounded text-xs"># comment</code>
                </div>
                <p class="text-xs text-content-tertiary leading-relaxed">
                  Comments are visible to the prompt improvement model and can be used to provide instructions and guidance. They are not sent to the generation tools.
                </p>
              </div>

              <!-- Verbatim -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-1">
                  <code class="text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded text-xs">[verbatim text]</code>
                </div>
                <p class="text-xs text-content-tertiary leading-relaxed">
                  Text in brackets is invisible to the prompt improvement model and will be preserved as-is.
                </p>
              </div>

              <!-- Divider -->
              <div v-if="!hideAutoImprove" class="border-t border-surface-raised my-3"></div>

              <!-- Auto-Improve -->
              <div v-if="!hideAutoImprove">
                <div class="flex items-center gap-1.5 mb-1">
                  <BoltIcon class="w-3 h-3 text-purple-500" />
                  <span class="text-xs font-medium text-content-secondary">Auto-Improve</span>
                </div>
                <p class="text-xs text-content-tertiary leading-relaxed">
                  When enabled, your prompt is automatically enhanced by AI each time you generate. The original prompt is preserved in the editor &mdash; only the version sent to the generation tool is improved.
                </p>
              </div>
            </div>
          </div>

          <!-- AI Sparkle Button — toggles the inline prompt-only chat. Hidden when
               externalChat is set (ToolView renders a page-level chat in its dock,
               so a per-prompt sparkle would be redundant + visually awkward). -->
          <button
            v-if="!externalChat"
            @click="toggleExpanded"
            :class="[
              'p-1 rounded transition-colors',
              expanded
                ? 'text-purple-500 bg-purple-500/20 hover:bg-purple-500/30'
                : 'text-[#808080] hover:text-purple-500 hover:bg-surface-raised'
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
      class="mt-2 p-3 bg-surface-overlay border border-surface-raised rounded-md"
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
import { ref, watch, onMounted, onUnmounted } from 'vue'
import type { PromptEditorHandle } from '../../composables/promptEditorHandle'
import { SparklesIcon, BoltIcon } from '@heroicons/vue/24/solid'
import PromptAgentChat from './PromptAgentChat.vue'
import { useCodeMirrorPrompt } from '../../composables/useCodeMirrorPrompt'

interface PromptOptionSetting {
  enabled: boolean
  instructions: string
}

interface PromptOptions {
  autoImprove: PromptOptionSetting
  varyPrompt: PromptOptionSetting
}

interface Props {
  modelValue: string
  rows?: number
  placeholder?: string
  expanded?: boolean
  promptOptions?: PromptOptions
  // Flow inputs run the literal prompt through the declared graph, so
  // auto-improve (which silently rewrites the prompt at submit time) would
  // break the execution model. Hide the affordance in those contexts.
  hideAutoImprove?: boolean
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
    varyPrompt: { enabled: false, instructions: '' }
  }),
  hideAutoImprove: false,
  externalChat: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:expanded', value: boolean): void
  (e: 'update:promptOptions', value: PromptOptions): void
}>()

// Refs
const editorMount = ref<HTMLElement | null>(null)
const helpPopoverContainer = ref<HTMLElement | null>(null)
const showHelp = ref(false)

// CodeMirror composable
const { vimEnabled, monospaceEnabled, toggleVim, toggleMonospace, setContent, applyDiffDecorations, clearDiffDecorations } =
  useCodeMirrorPrompt({
    mountRef: editorMount,
    modelValue: () => props.modelValue,
    placeholder: props.placeholder,
    onChange: (value: string) => {
      emit('update:modelValue', value)
    },
    // Blur intentionally does nothing — suggestion refresh is debounce-driven.
    onBlur: () => {},
  })

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

// Click-outside handler for help popover
function handleClickOutside(event: MouseEvent) {
  if (showHelp.value && helpPopoverContainer.value && !helpPopoverContainer.value.contains(event.target as Node)) {
    showHelp.value = false
  }
}

// Sync external modelValue changes into CM6 editor
watch(() => props.modelValue, (newVal) => {
  setContent(newVal)
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

defineExpose({
  getText: () => props.modelValue,
  setPromptText,
  animateDiff,
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
