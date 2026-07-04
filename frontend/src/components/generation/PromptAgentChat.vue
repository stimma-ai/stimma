<template>
  <div class="relative">
    <!-- Conversation panel (agent) — shows the real exchange + tool calls -->
    <div v-if="showDebug && agent" class="mb-3 bg-surface-overlay border border-surface-raised rounded-lg overflow-hidden">
      <div class="max-h-80 overflow-y-auto p-3 space-y-2">
        <div v-if="agentDebugEntries.length === 0 && debugHistory.length === 0" class="text-xs text-content-muted italic py-4 text-center">
          Send a message to see the conversation
        </div>
        <div
          v-for="entry in agentDebugEntries"
          :key="entry.id"
          :class="[
            'p-2.5 rounded-lg text-xs',
            entry.role === 'user'
              ? 'bg-blue-500/10 border border-blue-500/20'
              : entry.role === 'tool'
                ? 'bg-surface-raised border border-surface-raised'
                : 'bg-purple-500/10 border border-purple-500/20'
          ]"
        >
          <div :class="[
            'text-[10px] font-medium uppercase tracking-wide mb-1.5',
            entry.role === 'user' ? 'text-blue-500' : entry.role === 'tool' ? 'text-content-muted' : 'text-purple-500 dark:text-purple-400'
          ]">
            {{ entry.role === 'user' ? '→ You' : entry.role === 'tool' ? '⚙ Tool result' : '✦ Assistant' }}
          </div>
          <!-- Thinking trace (collapsed by default) -->
          <details v-if="entry.thinking" class="mb-1.5 group/think">
            <summary class="cursor-pointer select-none text-[10px] font-medium text-content-muted hover:text-content-secondary flex items-center gap-1">
              <LightBulbIcon class="w-3 h-3" />
              <span>Thinking</span>
            </summary>
            <div class="mt-1 pl-3 border-l-2 border-white/10 text-content-muted whitespace-pre-wrap font-mono text-[10px] leading-relaxed break-words italic">{{ entry.thinking }}</div>
          </details>
          <!-- Tool calls the assistant made -->
          <div v-if="entry.toolCalls.length" class="mb-1.5 space-y-1">
            <div
              v-for="(tc, ti) in entry.toolCalls"
              :key="ti"
              class="px-2 py-1 rounded bg-purple-500/10 border border-purple-500/20 font-mono text-[10px] text-purple-600 dark:text-purple-300 break-all"
            >
              {{ tc.name }}({{ prettyArgs(tc.args) }})
            </div>
          </div>
          <div v-if="entry.text" class="text-content-secondary whitespace-pre-wrap font-mono text-[11px] leading-relaxed break-words">{{ entry.text }}</div>
        </div>

        <!-- Quick edits (suggestion pills + auto-ideas) use the single-shot
             /enhance path, not the agent loop, so they're logged separately. -->
        <template v-if="debugHistory.length">
          <div class="pt-1 text-[10px] font-medium uppercase tracking-wide text-content-muted">Quick edits</div>
          <div
            v-for="entry in debugHistory"
            :key="'legacy-' + entry.id"
            :class="[
              'p-2.5 rounded-lg text-xs',
              entry.type === 'request'
                ? 'bg-blue-500/10 border border-blue-500/20'
                : 'bg-green-500/10 border border-green-500/20'
            ]"
          >
            <div :class="[
              'text-[10px] font-medium uppercase tracking-wide mb-1.5',
              entry.type === 'request' ? 'text-blue-500' : 'text-green-600 dark:text-green-500'
            ]">
              {{ entry.type === 'request' ? '→ Request' : '← Response' }}
            </div>
            <div v-if="entry.status" :class="[
              'mb-1.5 px-2 py-1 rounded text-[10px] font-medium',
              entry.status.startsWith('✓') ? 'bg-green-500/10 text-green-600 dark:text-green-500' : 'bg-red-500/10 text-red-500'
            ]">{{ entry.status }}</div>
            <div class="text-content-secondary whitespace-pre-wrap font-mono text-[11px] leading-relaxed break-words">{{ entry.content }}</div>
          </div>
        </template>
      </div>
      <div class="px-3 py-2 border-t border-surface-raised flex justify-end gap-3">
        <button
          v-if="debugHistory.length"
          @click="debugHistory = []"
          class="text-[10px] text-content-muted hover:text-red-500 transition-colors"
        >
          Clear quick edits
        </button>
        <button
          v-if="agent"
          @click="agent.clearHistory()"
          class="text-[10px] text-content-muted hover:text-red-500 transition-colors"
        >
          Clear conversation
        </button>
      </div>
    </div>

    <!-- Debug Panel (standalone, prompt-only) - shows actual requests/responses -->
    <div v-else-if="showDebug" class="mb-3 bg-surface-overlay border border-surface-raised rounded-lg overflow-hidden">
      <div class="max-h-80 overflow-y-auto p-3 space-y-3">
        <div v-if="debugHistory.length === 0" class="text-xs text-content-muted italic py-4 text-center">
          Start enhancing to see requests/responses
        </div>
        <div
          v-for="entry in debugHistory"
          :key="entry.id"
          :class="[
            'p-2.5 rounded-lg text-xs relative group',
            entry.type === 'request'
              ? 'bg-blue-500/10 border border-blue-500/20'
              : 'bg-green-500/10 border border-green-500/20'
          ]"
        >
          <div class="flex items-center justify-between mb-1.5">
            <span :class="[
              'text-[10px] font-medium uppercase tracking-wide',
              entry.type === 'request' ? 'text-blue-500' : 'text-green-500'
            ]">
              {{ entry.type === 'request' ? '→ Request' : '← Response' }}
            </span>
            <button
              @click="deleteDebugEntry(entry.id)"
              class="opacity-0 group-hover:opacity-100 text-content-muted hover:text-red-500 transition-all p-0.5"
              title="Delete this entry"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div v-if="entry.verbatimSegments && entry.verbatimSegments.length > 0" class="mb-2 p-1.5 bg-purple-500/10 rounded border border-purple-500/20">
            <div class="text-[10px] text-purple-500 font-medium mb-1">Verbatim substitutions:</div>
            <div v-for="seg in entry.verbatimSegments" :key="seg.placeholder" class="text-[10px] text-purple-500 font-mono">
              {{ seg.placeholder }} ← [{{ seg.original }}]
            </div>
          </div>

          <div v-if="entry.status" :class="[
            'mb-2 px-2 py-1 rounded text-[10px] font-medium',
            entry.status.startsWith('✓') ? 'bg-green-500/10 text-green-500 border border-green-500/20' : 'bg-red-500/10 text-red-500 border border-red-500/20'
          ]">
            {{ entry.status }}
          </div>

          <div class="text-content-secondary whitespace-pre-wrap font-mono text-[11px] leading-relaxed">{{ entry.content }}</div>
        </div>
      </div>
      <div class="px-3 py-2 border-t border-surface-raised flex justify-end">
        <button
          @click="resetConversation"
          class="text-[10px] text-content-muted hover:text-red-500 transition-colors"
        >
          Clear all
        </button>
      </div>
    </div>

    <!-- Wrap panel of transient agent receipts. Sits ABOVE the input so new
         nuggets grow upward into the page rather than shoving the box down.
         Newest is inserted at the front (left); each chip fades on its own
         timer. These are terse confirmations of what the agent did, not a
         back-and-forth transcript. -->
    <template v-if="agent">
      <TransitionGroup
        tag="div"
        class="mb-2 flex flex-wrap items-start gap-1"
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0 -translate-x-1"
        leave-active-class="transition duration-[600ms] ease-in"
        leave-to-class="opacity-0"
        move-class="transition-transform duration-200"
      >
        <div
          v-for="f in agentFlashes"
          :key="f.id"
          class="flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
          :class="f.kind === 'error'
            ? 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300'
            : 'border-purple-500/25 bg-purple-500/10 text-purple-700 dark:text-purple-200'"
        >
          <SparklesIcon v-if="f.kind === 'reply'" class="h-3 w-3 flex-shrink-0 text-purple-500 dark:text-purple-400" />
          <span class="whitespace-pre-wrap leading-snug">{{ f.text }}</span>
          <PromptAgentThumbButtons
            v-if="f.kind === 'reply'"
            :package-source="collectPromptAgentConversation"
          />
        </div>
      </TransitionGroup>
    </template>

    <!-- Per-tool settings drawer (toggled by the wrench in the toolbar below):
         Instructions (the user's standing guidance) + Memory (durable facts the
         agent records). Both co-edited by user + agent; ride the tool and any
         preset saved from it. Expands upward above the input with a height tween. -->
    <div
      v-if="agent"
      class="overflow-hidden transition-all duration-300 ease-out"
      :class="showSettings ? 'max-h-[640px] opacity-100 mb-2.5' : 'max-h-0 opacity-0 mb-0'"
    >
      <div class="bg-surface-overlay border border-edge rounded-xl p-3.5">
        <div class="flex items-center mb-3">
          <span class="text-xs font-semibold text-content-secondary">Agent settings</span>
          <button
            @click="showSettings = false"
            class="ml-auto w-6 h-6 flex items-center justify-center rounded text-content-muted hover:text-content-secondary hover:bg-white/[0.05] transition-colors"
            title="Close"
          >
            <ChevronUpIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- Instructions -->
        <div>
          <label class="block text-xs font-medium text-content-tertiary mb-1.5">Instructions</label>
          <textarea v-no-autocorrect
            v-model="instructionsText"
            rows="3"
            placeholder="Standing guidance for this tool — e.g. prefer portrait framing, keep skin texture realistic, avoid harsh lighting."
            class="w-full bg-surface border border-edge rounded-lg text-content text-xs px-3 py-2 focus:outline-none focus:border-blue-500/50 resize-y font-sans leading-relaxed"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- Feedback input box (mirrors ChatView's input: text on top, toolbar row) -->
    <div class="bg-surface border border-edge rounded-2xl overflow-hidden">
      <input v-no-autocorrect
        ref="feedbackInput"
        v-model="feedbackText"
        @keydown.enter.exact.prevent="enhance"
        @keydown.up.prevent="historyUp"
        @keydown.down.prevent="historyDown"
        @keydown="voiceBtn?.handleInputKeydown($event)"
        @keyup="voiceBtn?.handleInputKeyup($event)"
        type="text"
        :placeholder="inputPlaceholder"
        class="w-full bg-transparent text-content text-sm px-4 pt-3 pb-1 focus:outline-none font-sans"
      />

      <!-- Action bar: undo/redo/settings lower-left, send lower-right -->
      <div class="flex items-center justify-between px-2.5 pb-2 pt-2">
        <div class="flex items-center gap-0.5">
          <button
            @click="undo"
            :disabled="!canUndo()"
            class="w-8 h-8 flex items-center justify-center rounded-full text-content-muted hover:text-content-secondary hover:bg-white/[0.05] transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-content-muted"
            title="Undo"
          >
            <ArrowUturnLeftIcon class="w-4 h-4" />
          </button>
          <button
            @click="redo"
            :disabled="!canRedo()"
            class="w-8 h-8 flex items-center justify-center rounded-full text-content-muted hover:text-content-secondary hover:bg-white/[0.05] transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-content-muted"
            title="Redo"
          >
            <ArrowUturnRightIcon class="w-4 h-4" />
          </button>
          <VoiceInputButton ref="voiceBtn" icon-class="w-4 h-4" :get-text="getFeedbackText" :set-text="setFeedbackText" :focus="focusFeedback" surface="prompt_agent" />
          <!-- Agent settings (Instructions) — expands the drawer above. -->
          <button
            v-if="agent"
            @click="showSettings = !showSettings"
            class="w-8 h-8 flex items-center justify-center rounded-lg transition-colors"
            :class="showSettings ? 'text-blue-500 bg-blue-500/20 hover:bg-blue-500/30' : 'text-content-muted hover:text-content-secondary hover:bg-white/[0.05]'"
            title="Agent settings — Instructions"
          >
            <WrenchIcon class="w-4 h-4" />
          </button>
          <!-- Active skills — skills targeting this tool feed the agent automatically. -->
          <SkillsMenuButton v-if="agent" :skills="activeSkills" mode="view" />
        </div>

        <button
          @click="enhance"
          :disabled="feedbackBusy() || !feedbackText.trim()"
          class="w-8 h-8 flex items-center justify-center rounded-full bg-content text-surface transition-colors disabled:opacity-30"
          :title="feedbackBusy() ? 'Working…' : 'Send'"
        >
          <svg v-if="feedbackBusy()" class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
            <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)" />
          </svg>
        </button>
      </div>
    </div>

    <p v-if="error" class="mt-2 text-xs text-red-500">{{ error }}</p>

    <!-- Ideas container (BELOW input). Prompt-bound suggestions only show when a
         prompt editor is wired in; a prompt-less tool gets a tools-only chat. -->
    <div v-if="hasPrompt" class="mt-3 max-h-[300px] overflow-y-auto">
      <!-- Empty prompt state -->
      <div v-if="!prompt.trim()" class="py-4 flex items-center justify-center">
        <p class="text-xs text-content-muted italic">Enter a prompt to get suggestions</p>
      </div>

      <!-- Suggestion pills -->
      <div
        v-else-if="suggestions.length > 0 || isLoadingIdeas || isLoadingCategories"
        class="flex flex-wrap gap-1.5 py-0.5 px-0.5"
      >
        <!-- Fixed suggestions (always shown at front) -->
        <button
          v-for="item in FIXED_SUGGESTIONS"
          :key="'fixed-' + item.label"
          @click="handleSuggestionClick(item, $event)"
          :title="item.instruction"
          class="px-2.5 py-1 rounded-full text-xs transition-all duration-200 bg-surface-raised text-content hover:bg-surface-hover hover:text-content"
        >
          {{ item.label }}
        </button>
        <!-- Line break between fixed and dynamic -->
        <div class="w-full"></div>
        <!-- Dynamic dropdown suggestions from LLM -->
        <button
          v-for="item in suggestions"
          :key="item.label"
          @click="handleSuggestionClick(item, $event)"
          :disabled="loadingOptionsByCategory[item.category]"
          :title="loadingOptionsByCategory[item.category] ? 'Loading options...' : (item.subitems && item.subitems.length > 0 ? `${item.label} (click for options)` : item.instruction)"
          :class="[
            'px-2.5 py-1 rounded-full text-xs transition-all duration-200',
            loadingOptionsByCategory[item.category]
              ? 'bg-surface-raised text-content-muted animate-pulse cursor-wait'
              : activeSubmenu?.label === item.label
                ? 'bg-blue-500/30 ring-1 ring-blue-500 text-blue-500 relative z-[60]'
                : getCategoryClass(item.category)
          ]"
        >
          {{ item.label }}
          <svg v-if="loadingOptionsByCategory[item.category]" class="w-3 h-3 ml-0.5 inline animate-spin" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <ChevronDownIcon v-else-if="item.subitems && item.subitems.length > 0" class="w-3 h-3 ml-0.5 text-content-tertiary inline" />
        </button>
        <!-- Refresh pill at end — recomputes the sections AND their options. -->
        <button
          @click="refreshIdeasClick()"
          :disabled="isLoadingIdeas"
          class="px-2.5 py-1 rounded-full text-xs transition-colors bg-surface text-content-muted hover:text-content-muted hover:bg-surface-raised border border-surface-raised"
          title="Refresh ideas"
        >
          <ArrowPathIcon :class="['w-3 h-3 inline', (isLoadingIdeas || isRefreshingIdeas) ? 'animate-spin' : '']" />
        </button>
      </div>

      <!-- Refusal message from LLM -->
      <div v-else-if="refusalMessage" class="py-3 px-4 flex items-center gap-2 bg-amber-500/10 rounded-lg border border-amber-500/20">
        <svg class="w-4 h-4 text-amber-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p class="text-xs text-amber-500">{{ refusalMessage }}</p>
      </div>

      <!-- Error state -->
      <div v-else-if="ideasError" class="py-3 px-4 flex items-center gap-3 bg-red-500/10 rounded-lg border border-red-500/20">
        <svg class="w-4 h-4 text-red-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p class="text-xs text-red-500 flex-1">{{ ideasError }}</p>
        <button
          @click="refreshIdeasClick()"
          :disabled="isLoadingIdeas"
          class="px-3 py-1 text-xs bg-overlay-light hover:bg-overlay-medium rounded text-content-secondary hover:text-content transition-colors disabled:opacity-50"
        >
          <span v-if="isLoadingIdeas" class="flex items-center gap-1.5">
            <svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Retrying...
          </span>
          <span v-else>Retry</span>
        </button>
      </div>

      <!-- No ideas yet -->
      <div v-else class="py-4 flex items-center justify-center">
        <button
          @click="refreshIdeasClick()"
          class="text-xs text-content-muted hover:text-purple-500 transition-colors"
        >
          Click to load ideas
        </button>
      </div>
    </div>

    <!-- Submenu for grouped items -->
    <SuggestionSubmenu
      :visible="activeSubmenu !== null"
      :label="activeSubmenu?.label || ''"
      :items="activeSubmenu?.subitems || []"
      :loading="activeSubmenu ? !!loadingOptionsByCategory[activeSubmenu.category] : false"
      :position="submenuPosition"
      @select="handleSubmenuSelect"
      @refresh="handleSubmenuRefresh"
      @surprise="handleSubmenuSurprise"
      @wildcard="handleSubmenuWildcard"
      @close="closeSubmenu"
    />

    <!-- Floating debug button (dev mode only) -->
    <button
      v-if="devModeRef"
      @click="showDebug = !showDebug"
      :class="[
        'absolute bottom-0 right-0 p-1.5 rounded transition-colors z-10',
        showDebug
          ? 'text-purple-500 bg-purple-500/10'
          : 'text-content-muted hover:text-purple-500 hover:bg-purple-500/10'
      ]"
      title="Show conversation history"
    >
      <BugAntIcon class="w-4 h-4" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, inject, computed } from 'vue'
import type { PromptEditorAgent } from '../../composables/promptEditorAgentKey'
import { PROMPT_EDITOR_AGENT_KEY } from '../../composables/promptEditorAgentKey'
import type { PromptEditorHandle } from '../../composables/promptEditorHandle'
import { SparklesIcon, ArrowUturnLeftIcon, ArrowUturnRightIcon, BugAntIcon, ArrowPathIcon, ChevronDownIcon, LightBulbIcon } from '@heroicons/vue/24/solid'
import { WrenchIcon, ChevronUpIcon } from '@heroicons/vue/24/outline'
import axios from 'axios'
import { useTelemetry } from '../../composables/useTelemetry'
import { extractVerbatim, restoreVerbatim, verifyVerbatimPreserved } from '../../utils/promptProcessor'
import SuggestionSubmenu from './SuggestionSubmenu.vue'
import VoiceInputButton from '../voice/VoiceInputButton.vue'
import SkillsMenuButton from '../chat/SkillsMenuButton.vue'
import { devModeRef } from '../../appConfig'
import PromptAgentThumbButtons from '@stimma/prompt-agent-thumb-buttons'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

// Debug history entry - shows exactly what was sent/received
interface DebugEntry {
  id: number
  type: 'request' | 'response'
  content: string
  verbatimSegments?: { placeholder: string; original: string }[]
  status?: string
  timestamp: Date
}

interface Props {
  /**
   * Handle to the prompt editor this chat drives in prompt-only mode. Absent
   * (null) for a tools-only chat (e.g. a ToolView tool with no prompt input).
   */
  editor?: PromptEditorHandle | null
  /** Current prompt text — drives ideas + the empty state. */
  prompt?: string
  /** Whether a prompt editor is wired in (shows pills/ideas, enables prompt edits). */
  hasPrompt?: boolean
  /** Placeholder for the feedback input. */
  placeholder?: string
  /** Per-tool Instructions — standing guidance, co-edited by user + agent. */
  instructions?: string
  /** Skills auto-activated for this tool (by task_type match) — shown as an indicator. */
  activeSkills?: Array<{ qualified_name: string; display_name: string; description?: string }>
}

const props = withDefaults(defineProps<Props>(), {
  editor: null,
  prompt: '',
  hasPrompt: false,
  placeholder: '',
  instructions: '',
  activeSkills: () => [],
})

const emit = defineEmits<{
  (e: 'update:prompt', value: string): void
  (e: 'update:instructions', value: string): void
}>()

// Writable proxy for the per-tool Instructions panel. Edits flow up via v-model
// so they land in the tool's working state (and any preset saved from it); the
// agent edits the same field through set/edit_instructions.
const instructionsText = computed({
  get: () => props.instructions ?? '',
  set: (v: string) => emit('update:instructions', v),
})
// Settings drawer (wrench toggle) holds Instructions.
// Collapsed by default — an occasional field.
const showSettings = ref(false)

// Injected page-wide mini-agent. Present → full-agent mode (drives the whole
// screen via tool calls); absent → prompt-only mode (single-shot /enhance).
const agent = inject<PromptEditorAgent | null>(PROMPT_EDITOR_AGENT_KEY, null)

// Telemetry: prompt_agent_action — UI clicks only, closed enum pinned to the
// actual controls: send | select_suggestion | select_option | surprise |
// wildcard | refresh_category | refresh_suggestions | undo | redo | reset.
// Never semantic suggestion categories (those derive from prompt content).
const { track: trackTelemetry } = useTelemetry()
function trackAction(action: string) {
  trackTelemetry('prompt_agent_action', { action }, 'prompt_agent')
}

function collectPromptAgentConversation() {
  let messages: { role: string; text: string }[]
  if (agent) {
    messages = agent.messages.value.map((m: any) => ({
      role: m.role,
      text: m.content || (m.tool_calls?.length
        ? m.tool_calls.map((tc: any) => `${tc.function.name}(${tc.function.arguments})`).join('\n')
        : ''),
    }))
  } else {
    messages = conversationHistory.value.map((m) => ({ role: m.role, text: m.content }))
  }
  return {
    messages: messages.filter((m) => m.text),
    prompt: props.prompt || '',
    instructions: props.instructions || '',
  }
}

// Extras sent on every suggestion request so ideas + dropdown options honor the
// tool's standing Instructions, exactly like the agent loop does.
function suggestionExtras() {
  return {
    instructions: props.instructions || '',
  }
}

const inputPlaceholder = computed(() => {
  if (props.placeholder) return props.placeholder
  return props.hasPrompt ? 'Make it more dramatic, add rain, …' : 'Ask or tell me to change a setting…'
})

// --- Prompt write helpers (prompt-only mode) -------------------------------
// In full-agent mode the chat never writes the prompt itself — the agent does
// it through tool calls — so these only fire in prompt-only mode.
function applyPrompt(text: string) {
  emit('update:prompt', text)
  props.editor?.setText(text)
}

// Transient toasts for agent replies/errors. New ones are inserted at the TOP
// and each evaporates on its own timer, so quick back-to-back commands let the
// conversation flow by.
interface AgentFlash { id: number; kind: 'reply' | 'error'; text: string }
const agentFlashes = ref<AgentFlash[]>([])
let agentFlashSeq = 0
const agentFlashTimers = new Set<ReturnType<typeof setTimeout>>()

function pushAgentFlash(kind: 'reply' | 'error', text: string, ms: number) {
  const id = agentFlashSeq++
  agentFlashes.value.unshift({ id, kind, text })
  const t = setTimeout(() => {
    agentFlashes.value = agentFlashes.value.filter((f) => f.id !== id)
    agentFlashTimers.delete(t)
  }, ms)
  agentFlashTimers.add(t)
}

if (agent) {
  watch(agent.lastReply, (v) => { if (v) pushAgentFlash('reply', v, 6000) })
  watch(agent.error, (v) => { if (v) pushAgentFlash('error', v, 10000) })
}

// The debug/conversation panel shows the agent's real exchange when injected
// (user turns, assistant text + tool calls, tool results), falling back to the
// legacy single-shot request/response log when standalone.
interface AgentDebugEntry {
  id: number
  role: 'user' | 'assistant' | 'tool'
  text: string
  thinking: string
  toolCalls: { name: string; args: string }[]
}
const agentDebugEntries = computed<AgentDebugEntry[]>(() => {
  if (!agent) return []
  return agent.messages.value.map((m, i) => ({
    id: i,
    role: m.role,
    text: m.content || '',
    thinking: m.thinking || '',
    toolCalls: (m.tool_calls || []).map(tc => ({ name: tc.function.name, args: tc.function.arguments })),
  }))
})
function prettyArgs(args: string): string {
  try { return JSON.stringify(JSON.parse(args)) } catch { return args }
}

// Refs
const feedbackInput = ref<HTMLInputElement | null>(null)
const voiceBtn = ref<any>(null)

// State
const feedbackText = ref('')

// Voice input adapters
function getFeedbackText() {
  return feedbackText.value
}
function setFeedbackText(text: string) {
  feedbackText.value = text
}
function focusFeedback() {
  feedbackInput.value?.focus()
}
const conversationHistory = ref<Message[]>([])  // Sent to API for context
const debugHistory = ref<DebugEntry[]>([])  // Debug panel - shows actual requests/responses
let debugEntryId = 0
const lastAIPrompt = ref<string | null>(null)  // Track what AI last returned to detect human edits
const undoStack = ref<string[]>([])
const redoStack = ref<string[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const showDebug = ref(false)

// Queue for sequential enhancement operations
const enhanceQueue = ref<string[]>([])
let isProcessingQueue = false
const feedbackHistory = ref<string[]>([])
const historyIndex = ref(-1)
const tempFeedback = ref('')

// Suggestion item (supports grouping)
interface SuggestionItem {
  label: string
  category: string
  instruction?: string      // Simple items - click to apply
  subitems?: string[]       // Grouped items - shows submenu
  allowWildcard?: boolean   // Show "make wildcard" in submenu
}

// Unified pill style - no colorization
function getCategoryClass(_category: string): string {
  return 'bg-surface-raised text-content-tertiary hover:bg-surface-hover hover:text-content-secondary'
}

// Fixed suggestion items always shown at front (Title Case)
const FIXED_SUGGESTIONS: SuggestionItem[] = [
  { label: 'Clean Up', category: 'detail', instruction: 'clean up' },
  { label: 'Add Detail', category: 'detail', instruction: 'add more detail' },
  { label: 'Improve Prompt', category: 'detail', instruction: 'improve the prompt while preserving the original intent' },
  { label: 'Simplify Prompt', category: 'detail', instruction: 'simplify the prompt, make it more concise' },
  { label: 'Zoom In', category: 'framing', instruction: 'zoom in, make the subject larger in frame' },
  { label: 'Zoom Out', category: 'framing', instruction: 'zoom out, show more of the environment' },
]

// Suggestion state (new hierarchical format)
const suggestions = ref<SuggestionItem[]>([])
const isLoadingIdeas = ref(false)
const isLoadingCategories = ref(false)
const loadingOptionsByCategory = ref<Record<string, boolean>>({})
const previousOptionsByCategory = ref<Record<string, string[]>>({})  // for exclusion on refresh
const ideasError = ref<string | null>(null)
const isRefreshingIdeas = ref(false)  // True when refetching while old suggestions exist
const lastPromptForIdeas = ref<string>('')

// Category state for 2-phase flow
interface CategoryItem {
  label: string
  category: string
  allow_wildcard: boolean
}
const categories = ref<CategoryItem[]>([])

// Submenu state
const activeSubmenu = ref<SuggestionItem | null>(null)
const submenuPosition = ref({ x: 0, top: 0, bottom: 0 })

// Request management - prevent duplicate/stale requests
let ideasAbortController: AbortController | null = null
let ideasDebounceTimer: ReturnType<typeof setTimeout> | null = null
const IDEAS_DEBOUNCE_MS = 500

// Refusal message from LLM (e.g., content policy rejection)
const refusalMessage = ref<string | null>(null)

// Reset conversation history
function resetConversation() {
  conversationHistory.value = []
  debugHistory.value = []
  debugEntryId = 0
  lastAIPrompt.value = null
  feedbackText.value = ''
  error.value = null
}

// Delete a single debug entry
function deleteDebugEntry(id: number) {
  debugHistory.value = debugHistory.value.filter(e => e.id !== id)
}

// Navigate feedback history with up/down arrows
function historyUp() {
  if (feedbackHistory.value.length === 0) return
  if (historyIndex.value === -1) {
    tempFeedback.value = feedbackText.value
  }
  if (historyIndex.value < feedbackHistory.value.length - 1) {
    historyIndex.value++
    feedbackText.value = feedbackHistory.value[feedbackHistory.value.length - 1 - historyIndex.value]
  }
}

function historyDown() {
  if (historyIndex.value === -1) return
  historyIndex.value--
  if (historyIndex.value === -1) {
    feedbackText.value = tempFeedback.value
  } else {
    feedbackText.value = feedbackHistory.value[feedbackHistory.value.length - 1 - historyIndex.value]
  }
}

// Undo last change. With the agent injected, drive the shared full-content undo
// (reverts the whole last agent run / pill edit atomically). Prompt-only mode
// uses the local prompt stack written back through the editor handle.
function undo() {
  trackAction('undo')
  if (agent) {
    agent.undo()
    return
  }
  if (undoStack.value.length === 0) return
  const previousPrompt = undoStack.value.pop()!
  redoStack.value.push(props.prompt)
  applyPrompt(previousPrompt)
}

function redo() {
  trackAction('redo')
  if (agent) {
    agent.redo()
    return
  }
  if (redoStack.value.length === 0) return
  const nextPrompt = redoStack.value.pop()!
  undoStack.value.push(props.prompt)
  applyPrompt(nextPrompt)
}

// Button enable/loading state — agent when injected, legacy stacks otherwise.
const canUndo = () => (agent ? agent.canUndo.value : undoStack.value.length > 0)
const canRedo = () => (agent ? agent.canRedo.value : redoStack.value.length > 0)
const feedbackBusy = () => (agent ? agent.running.value : isLoading.value)

// Push current prompt to undo stack before making changes
function pushToUndoStack() {
  undoStack.value.push(props.prompt)
  redoStack.value = []
}

// Feedback box submit. When the mini-agent is provided (ToolView), the feedback
// box drives the tool-calling agent that operates the whole screen. Otherwise
// (prompt-only), fall back to the single-shot /enhance queue.
function enhance() {
  const text = feedbackText.value.trim()
  if (!text) {
    error.value = 'Enter what you want to change'
    return
  }

  trackAction('send')

  if (agent) {
    error.value = null
    feedbackHistory.value.push(text)
    feedbackText.value = ''
    historyIndex.value = -1
    tempFeedback.value = ''
    // Agent owns the run (undo snapshot, loop, state). Slash commands handled internally.
    agent.send(text)
    return
  }

  // --- Legacy single-shot path (prompt-only mode) ---
  if (!props.prompt.trim()) {
    error.value = 'Enter a prompt first'
    return
  }

  enhanceQueue.value.push(text)
  feedbackHistory.value.push(text)
  feedbackText.value = ''
  historyIndex.value = -1
  tempFeedback.value = ''
  processEnhanceQueue()
}

// Process queued enhancements one at a time
async function processEnhanceQueue() {
  if (isProcessingQueue) return
  if (enhanceQueue.value.length === 0) return

  isProcessingQueue = true
  isLoading.value = true
  error.value = null

  while (enhanceQueue.value.length > 0) {
    const feedback = enhanceQueue.value.shift()!
    await doEnhance(feedback)
  }

  isProcessingQueue = false
  isLoading.value = false
  feedbackInput.value?.focus()
}

// Actually perform the enhancement (prompt-only mode).
async function doEnhance(feedback: string) {
  try {
    const { processed: promptWithPlaceholders, segments } = extractVerbatim(props.prompt)

    const humanEdited = lastAIPrompt.value !== null &&
                        lastAIPrompt.value !== props.prompt &&
                        conversationHistory.value.length > 0

    let previousPromptWithPlaceholders: string | null = null
    if (humanEdited && lastAIPrompt.value) {
      const { processed } = extractVerbatim(lastAIPrompt.value)
      previousPromptWithPlaceholders = processed
    }

    let userMessageContent: string
    if (feedback) {
      if (humanEdited && previousPromptWithPlaceholders) {
        userMessageContent = `The user manually edited the prompt. Here is the before/after:

<previous_prompt>
${previousPromptWithPlaceholders}
</previous_prompt>

<prompt>
${promptWithPlaceholders}
</prompt>

IMPORTANT: The user's edits are INTENTIONAL. If they removed something, do NOT add it back. Work from <prompt>, not <previous_prompt>.

<feedback>${feedback}</feedback>`
      } else {
        userMessageContent = `<prompt>\n${promptWithPlaceholders}\n</prompt>\n\n<feedback>${feedback}</feedback>`
      }
    } else {
      userMessageContent = `Please improve this prompt:\n\n<prompt>\n${promptWithPlaceholders}\n</prompt>`
    }

    debugHistory.value.push({
      id: debugEntryId++,
      type: 'request',
      content: userMessageContent,
      verbatimSegments: segments.length > 0 ? segments : undefined,
      timestamp: new Date()
    })

    let enhancedPrompt: string | null = null
    const MAX_RETRIES = 3

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      const response = await axios.post('/api/prompt/enhance', {
        prompt: promptWithPlaceholders,
        feedback: feedback,
        conversation_history: conversationHistory.value,
        human_edited: humanEdited,
        previous_prompt: previousPromptWithPlaceholders
      })

      const candidatePrompt = response.data.enhanced_prompt
      const placeholdersPreserved = segments.length === 0 || verifyVerbatimPreserved(candidatePrompt, segments)

      debugHistory.value.push({
        id: debugEntryId++,
        type: 'response',
        content: candidatePrompt,
        status: segments.length > 0
          ? (placeholdersPreserved ? '✓ Placeholders preserved' : `✗ Attempt ${attempt + 1}/${MAX_RETRIES} - placeholders missing`)
          : undefined,
        timestamp: new Date()
      })

      if (segments.length === 0) {
        enhancedPrompt = candidatePrompt
        break
      }
      if (placeholdersPreserved) {
        enhancedPrompt = candidatePrompt
        break
      }
      console.warn(`Attempt ${attempt + 1}: AI removed verbatim placeholders, retrying...`)
    }

    if (enhancedPrompt === null) {
      console.warn('All retries failed to preserve verbatim text, skipping enhancement')
      error.value = 'Enhancement failed to preserve verbatim text'
      return
    }

    const finalPrompt = restoreVerbatim(enhancedPrompt, segments)
    const oldPrompt = props.prompt

    pushToUndoStack()
    lastAIPrompt.value = finalPrompt

    conversationHistory.value.push({ role: 'user', content: userMessageContent })
    conversationHistory.value.push({ role: 'assistant', content: enhancedPrompt })

    applyPrompt(finalPrompt)
    props.editor?.animateDiff(oldPrompt, finalPrompt)

  } catch (err: any) {
    console.error('Failed to enhance prompt:', err)
    const detail = err.response?.data?.detail
    error.value = typeof detail === 'string'
      ? detail
      : detail?.message || 'Failed to enhance prompt'
  }
}

// Fetch suggestion ideas using 2-phase approach with atomic swap
async function fetchIdeas(force = false) {
  if (!props.prompt.trim()) {
    suggestions.value = []
    categories.value = []
    isRefreshingIdeas.value = false
    return
  }

  if (!force && props.prompt === lastPromptForIdeas.value) {
    return
  }

  if (ideasDebounceTimer) {
    clearTimeout(ideasDebounceTimer)
    ideasDebounceTimer = null
  }

  if (!force) {
    ideasDebounceTimer = setTimeout(() => {
      ideasDebounceTimer = null
      fetchIdeas(true)
    }, IDEAS_DEBOUNCE_MS)
    return
  }

  if (ideasAbortController) {
    ideasAbortController.abort()
  }
  ideasAbortController = new AbortController()

  const hasExistingSuggestions = suggestions.value.length > 0

  if (!hasExistingSuggestions) {
    isLoadingIdeas.value = true
    isLoadingCategories.value = true
  } else {
    isRefreshingIdeas.value = true
  }

  ideasError.value = null
  refusalMessage.value = null
  lastPromptForIdeas.value = props.prompt

  try {
    const { processed: promptForIdeas } = extractVerbatim(props.prompt)

    // Phase 1: Get categories
    const catResponse = await axios.post('/api/prompt/suggest-categories', {
      prompt: promptForIdeas,
      ...suggestionExtras(),
      debug: showDebug.value
    }, {
      signal: ideasAbortController.signal
    })

    if (catResponse.data.message) {
      refusalMessage.value = catResponse.data.message
      if (!hasExistingSuggestions) {
        isLoadingCategories.value = false
        isLoadingIdeas.value = false
      }
      isRefreshingIdeas.value = false
      return
    }

    const newCategories: CategoryItem[] = catResponse.data.categories || []

    const tempSuggestions: SuggestionItem[] = newCategories.map(cat => ({
      label: cat.label,
      category: cat.category,
      subitems: [],
      allowWildcard: cat.allow_wildcard
    }))

    if (!hasExistingSuggestions) {
      categories.value = newCategories
      suggestions.value = tempSuggestions
      isLoadingCategories.value = false

      for (const cat of newCategories) {
        loadingOptionsByCategory.value[cat.category] = true
      }

      previousOptionsByCategory.value = {}

      await fetchOptionsForCategories(promptForIdeas, newCategories)
    } else {
      const results = await fetchOptionsBatch(promptForIdeas, newCategories, {})

      const newPreviousOptions: Record<string, string[]> = {}
      for (const result of results) {
        const category = result.category as string
        const subitems = (result.subitems || []) as string[]
        const tempItem = tempSuggestions.find(s => s.category === category)
        if (tempItem) {
          tempItem.subitems = subitems
        }
        newPreviousOptions[category] = [...subitems]
      }

      const finalSuggestions = tempSuggestions.filter(s => s.subitems && s.subitems.length > 0)

      if (finalSuggestions.length > 0) {
        categories.value = newCategories
        suggestions.value = finalSuggestions
        previousOptionsByCategory.value = newPreviousOptions
        loadingOptionsByCategory.value = {}
      }
    }

  } catch (err: any) {
    if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
      return
    }
    console.error('Failed to fetch suggestions:', err)
    if (suggestions.value.length === 0) {
      ideasError.value = err.response?.data?.detail || 'Failed to load suggestions'
    }
  } finally {
    isLoadingIdeas.value = false
    isLoadingCategories.value = false
    isRefreshingIdeas.value = false
    ideasAbortController = null
  }
}

// Fetch options for categories in one backend request (backend does LLM fan-out).
async function fetchOptionsForCategories(promptForIdeas: string, cats: CategoryItem[], excludeMap?: Record<string, string[]>) {
  for (const cat of cats) {
    loadingOptionsByCategory.value[cat.category] = true
  }

  try {
    const results = await fetchOptionsBatch(promptForIdeas, cats, excludeMap)
    const resultMap = new Map(results.map(item => [item.category as string, (item.subitems || []) as string[]]))

    for (const cat of cats) {
      const subitems = resultMap.get(cat.category) || []
      if (subitems.length === 0) {
        suggestions.value = suggestions.value.filter(s => s.category !== cat.category)
        continue
      }

      const idx = suggestions.value.findIndex(s => s.category === cat.category)
      if (idx !== -1) {
        suggestions.value[idx] = { ...suggestions.value[idx], subitems }
      }

      if (!previousOptionsByCategory.value[cat.category]) {
        previousOptionsByCategory.value[cat.category] = []
      }
      previousOptionsByCategory.value[cat.category].push(...subitems)
    }
  } catch (err: any) {
    if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return
    console.error('Failed to fetch options batch:', err)
    suggestions.value = suggestions.value.filter(s => s.subitems && s.subitems.length > 0)
    categories.value = categories.value.filter(cat =>
      suggestions.value.some(s => s.category === cat.category)
    )
    if (suggestions.value.length === 0) {
      ideasError.value = err.response?.data?.detail || 'Failed to load suggestion options'
    }
  } finally {
    for (const cat of cats) {
      loadingOptionsByCategory.value[cat.category] = false
    }
    const anyLoading = Object.values(loadingOptionsByCategory.value).some(v => v)
    if (!anyLoading) {
      isLoadingIdeas.value = false
    }
  }
}

async function fetchOptionsBatch(promptForIdeas: string, cats: CategoryItem[], excludeMap?: Record<string, string[]>) {
  const response = await axios.post('/api/prompt/suggest-options/batch', {
    prompt: promptForIdeas,
    categories: cats.map(cat => ({
      label: cat.label,
      category: cat.category,
      allow_wildcard: cat.allow_wildcard
    })),
    exclude_by_category: excludeMap || {},
    ...suggestionExtras(),
    debug: showDebug.value
  }, {
    signal: ideasAbortController?.signal
  })
  return response.data.results || []
}

// Refresh options only (keep categories stable, exclude previous options)
// Handle click on a suggestion item
function handleSuggestionClick(item: SuggestionItem, event: MouseEvent) {
  if (loadingOptionsByCategory.value[item.category]) return

  trackAction('select_suggestion')

  if (item.subitems && item.subitems.length > 0) {
    if (activeSubmenu.value?.label === item.label) {
      activeSubmenu.value = null
    } else {
      const target = event.currentTarget as HTMLElement
      const rect = target.getBoundingClientRect()
      activeSubmenu.value = item
      submenuPosition.value = {
        x: rect.left + rect.width / 2,
        top: rect.top,
        bottom: rect.bottom
      }
    }
  } else if (item.instruction) {
    applyInstruction(item.instruction, item.label)
  }
}

// Apply an instruction (from simple item or submenu selection). Everything goes
// through the mini-agent when injected, so pills and the feedback box edit the
// prompt identically. Only prompt-only contexts fall back to /enhance.
function applyInstruction(instruction: string, _labelToRemove?: string) {
  if (agent) {
    agent.send(instruction)
    return
  }
  if (!props.prompt.trim()) {
    error.value = 'Enter a prompt first'
    return
  }
  enhanceQueue.value.push(instruction)
  processEnhanceQueue()
}

function handleSubmenuSelect(optionLabel: string, fromSurprise = false) {
  if (!fromSurprise) trackAction('select_option')
  if (activeSubmenu.value) {
    const category = activeSubmenu.value.label
    const instruction = `change only ${category.toLowerCase()} to ${optionLabel}`
    applyInstruction(instruction, activeSubmenu.value.label)
  }
  activeSubmenu.value = null
}

function handleSubmenuSurprise() {
  if (!activeSubmenu.value?.subitems?.length) return
  trackAction('surprise')
  const items = activeSubmenu.value.subitems
  const pick = items[Math.floor(Math.random() * items.length)]
  handleSubmenuSelect(pick, true)
}

function handleSubmenuWildcard() {
  if (!activeSubmenu.value?.subitems?.length) return
  trackAction('wildcard')
  const category = activeSubmenu.value.label
  const wildcard = `{${activeSubmenu.value.subitems.join('|')}}`
  const instruction = `insert this exact wildcard for ${category.toLowerCase()}: ${wildcard}`
  applyInstruction(instruction)
  activeSubmenu.value = null
}

// Refresh options for the currently open submenu category (atomic swap)
async function handleSubmenuRefresh() {
  if (!activeSubmenu.value) return
  trackAction('refresh_category')

  const cat = categories.value.find(c => c.category === activeSubmenu.value!.category)
  if (!cat) return

  const { processed: promptForIdeas } = extractVerbatim(props.prompt)
  const exclude = previousOptionsByCategory.value[cat.category] || []

  loadingOptionsByCategory.value[cat.category] = true

  try {
    const response = await axios.post('/api/prompt/suggest-options', {
      prompt: promptForIdeas,
      category: {
        label: cat.label,
        category: cat.category,
        allow_wildcard: cat.allow_wildcard
      },
      exclude: exclude,
      ...suggestionExtras(),
      debug: showDebug.value
    }, {
      signal: ideasAbortController?.signal
    })

    const newSubitems: string[] = response.data.subitems || []

    if (newSubitems.length > 0) {
      const idx = suggestions.value.findIndex(s => s.category === cat.category)
      if (idx !== -1) {
        suggestions.value[idx] = { ...suggestions.value[idx], subitems: newSubitems }
      }

      if (!previousOptionsByCategory.value[cat.category]) {
        previousOptionsByCategory.value[cat.category] = []
      }
      previousOptionsByCategory.value[cat.category].push(...newSubitems)

      const updated = suggestions.value.find(s => s.category === cat.category)
      if (updated) {
        activeSubmenu.value = updated
      }
    }
  } catch (err: any) {
    if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return
    console.error(`Failed to refresh options for ${cat.label}:`, err)
  } finally {
    loadingOptionsByCategory.value[cat.category] = false
  }
}

function closeSubmenu() {
  activeSubmenu.value = null
}

// Debounce timer for prompt changes
let promptChangeDebounceTimer: ReturnType<typeof setTimeout> | null = null
const PROMPT_CHANGE_DEBOUNCE_MS = 3000
const SIGNIFICANT_CHANGE_THRESHOLD = 0.7  // 70% change required to trigger refetch
const INSTRUCTIONS_CHANGE_DEBOUNCE_MS = 1500  // wait for the user to stop typing instructions

function calculatePromptDifference(a: string, b: string): number {
  if (!a || !b) return 1
  const wordsA = a.toLowerCase().split(/\s+/).filter(w => w.length > 2)
  const wordsB = b.toLowerCase().split(/\s+/).filter(w => w.length > 2)
  if (wordsA.length === 0 || wordsB.length === 0) return 1

  const setA = new Set(wordsA)
  const setB = new Set(wordsB)
  const intersection = [...setA].filter(w => setB.has(w)).length

  return 1 - (intersection / new Set([...wordsA, ...wordsB]).size)
}

// Watch for prompt changes and refresh ideas only on significant changes
watch(() => props.prompt, (newValue) => {
  if (!props.hasPrompt) return
  if (newValue === lastPromptForIdeas.value) return

  if (promptChangeDebounceTimer) {
    clearTimeout(promptChangeDebounceTimer)
  }

  promptChangeDebounceTimer = setTimeout(() => {
    promptChangeDebounceTimer = null
    if (!props.prompt.trim()) return
    if (props.prompt === lastPromptForIdeas.value) return

    const diff = calculatePromptDifference(props.prompt, lastPromptForIdeas.value)
    if (diff >= SIGNIFICANT_CHANGE_THRESHOLD) {
      previousOptionsByCategory.value = {}
      categories.value = []
      fetchIdeas(true)
    }
  }, PROMPT_CHANGE_DEBOUNCE_MS)
})

// Instructions feed the suggestion prompts, so when they change — the user types
// in the drawer, or the agent edits them — re-run ideas so the sections and their
// options reflect the new guidance. Without this, suggestions only refresh on a
// prompt change and the instructions look ignored. Debounced so typing doesn't thrash.
let instructionsChangeTimer: ReturnType<typeof setTimeout> | null = null
watch(() => props.instructions, () => {
  if (!props.hasPrompt || !props.prompt.trim()) return
  if (instructionsChangeTimer) clearTimeout(instructionsChangeTimer)
  instructionsChangeTimer = setTimeout(() => {
    instructionsChangeTimer = null
    if (props.prompt.trim()) fetchIdeas(true)
  }, INSTRUCTIONS_CHANGE_DEBOUNCE_MS)
})

onMounted(() => {
  // The chat is only mounted while visible (flow: sparkle-toggled; ToolView:
  // always docked), so loading ideas on mount replaces the old expand watcher.
  if (props.hasPrompt && props.prompt.trim() && suggestions.value.length === 0) {
    fetchIdeas(true)
  }
})

onUnmounted(() => {
  agentFlashTimers.forEach(clearTimeout)
  agentFlashTimers.clear()
  if (promptChangeDebounceTimer) clearTimeout(promptChangeDebounceTimer)
  if (ideasDebounceTimer) clearTimeout(ideasDebounceTimer)
  ideasAbortController?.abort()
})

// ──────────────────────────────────────────────────────────────────────────
// Command surface for the page-wide mini-agent (called by ToolView.runTool):
// category management + ideas. Prompt text edits are applied by ToolView
// directly against the prompt editor; these cover the suggestion categories.
// ──────────────────────────────────────────────────────────────────────────

function slugifyKey(label: string): string {
  return label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'category'
}

function getCategoriesSnapshot() {
  return {
    categories: categories.value.map(c => ({ ...c })),
    suggestions: suggestions.value.map(s => ({ ...s, subitems: s.subitems ? [...s.subitems] : undefined })),
  }
}

function setCategoriesSnapshot(snap: { categories: CategoryItem[]; suggestions: SuggestionItem[] }) {
  categories.value = (snap?.categories || []).map(c => ({ ...c }))
  suggestions.value = (snap?.suggestions || []).map(s => ({ ...s, subitems: s.subitems ? [...s.subitems] : undefined }))
}

function getCategoriesForState() {
  return categories.value.map(cat => {
    const sug = suggestions.value.find(s => s.category === cat.category)
    return {
      key: cat.category,
      label: cat.label,
      allow_wildcard: !!cat.allow_wildcard,
      options: sug?.subitems || [],
    }
  })
}

function addCategoryCmd(args: { label: string; key?: string; allow_wildcard?: boolean; options?: string[] }): string {
  const label = (args.label || '').trim()
  if (!label) return 'Error: label is required'
  const key = (args.key || slugifyKey(label)).trim()
  if (categories.value.some(c => c.category === key)) {
    return `Category "${key}" already exists`
  }
  categories.value = [...categories.value, { label, category: key, allow_wildcard: !!args.allow_wildcard }]
  suggestions.value = [...suggestions.value, {
    label,
    category: key,
    allowWildcard: !!args.allow_wildcard,
    subitems: Array.isArray(args.options) ? [...args.options] : [],
  }]
  if (!args.options || args.options.length === 0) {
    if (props.prompt.trim()) {
      refreshCategoryCmd(key)
    }
    return `Added category "${label}" (generating options)`
  }
  return `Added category "${label}" with ${args.options.length} option(s)`
}

function removeCategoryCmd(key: string): string {
  if (!categories.value.some(c => c.category === key)) return `No category with key "${key}"`
  categories.value = categories.value.filter(c => c.category !== key)
  suggestions.value = suggestions.value.filter(s => s.category !== key)
  return `Removed category "${key}"`
}

function setCategoryOptionsCmd(key: string, options: string[]): string {
  const idx = suggestions.value.findIndex(s => s.category === key)
  if (idx === -1) return `No category with key "${key}"`
  suggestions.value[idx] = { ...suggestions.value[idx], subitems: [...(options || [])] }
  previousOptionsByCategory.value[key] = [...(options || [])]
  return `Set ${options?.length || 0} option(s) for "${key}"`
}

async function refreshCategoryCmd(key: string): Promise<string> {
  const cat = categories.value.find(c => c.category === key)
  if (!cat) return `No category with key "${key}"`
  if (!props.prompt.trim()) return 'Enter a prompt first'
  const { processed: promptForIdeas } = extractVerbatim(props.prompt)
  const exclude = previousOptionsByCategory.value[key] || []
  loadingOptionsByCategory.value[key] = true
  try {
    const response = await axios.post('/api/prompt/suggest-options', {
      prompt: promptForIdeas,
      category: { label: cat.label, category: cat.category, allow_wildcard: cat.allow_wildcard },
      exclude,
      ...suggestionExtras(),
    })
    const newSubitems: string[] = response.data.subitems || []
    if (newSubitems.length > 0) {
      const idx = suggestions.value.findIndex(s => s.category === key)
      if (idx !== -1) {
        suggestions.value[idx] = { ...suggestions.value[idx], subitems: newSubitems }
      }
      if (!previousOptionsByCategory.value[key]) previousOptionsByCategory.value[key] = []
      previousOptionsByCategory.value[key].push(...newSubitems)
    }
    return `Refreshed "${cat.label}" (${newSubitems.length} option(s))`
  } catch (err: any) {
    return `Error refreshing "${cat.label}": ${err?.response?.data?.detail || err?.message || 'failed'}`
  } finally {
    loadingOptionsByCategory.value[key] = false
  }
}

function refreshIdeasClick() {
  trackAction('refresh_suggestions')
  void fetchIdeas(true)
}

async function refreshIdeasCmd(): Promise<string> {
  if (!props.prompt.trim()) return 'Enter a prompt first'
  previousOptionsByCategory.value = {}
  categories.value = []
  await fetchIdeas(true)
  return `Refreshed ideas (${categories.value.length} categor${categories.value.length === 1 ? 'y' : 'ies'})`
}

defineExpose({
  getCategoriesForState,
  getCategoriesSnapshot,
  setCategoriesSnapshot,
  addCategory: addCategoryCmd,
  removeCategory: removeCategoryCmd,
  setCategoryOptions: setCategoryOptionsCmd,
  refreshCategory: refreshCategoryCmd,
  refreshIdeas: refreshIdeasCmd,
})
</script>
