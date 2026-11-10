<script setup lang="ts">
// The selection bar's Ask: a prompt aimed at what's selected. It opens above
// the bar, which keeps its own actions while you type. Enter starts a real
// chat that waits in the dock (⌘↵ opens its window straight away). Ideas for
// this kind of selection show as chips; past prompts stay out of sight until
// what you type matches one, or the clock lists them.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ClockIcon } from '@heroicons/vue/24/outline'
import AgentIcon from './icons/AgentIcon.vue'
import SendButton from './ui/SendButton.vue'
import Tooltip from './ui/Tooltip.vue'
import { MediaImage } from './media'
import { useViewport } from '../composables/useViewport'
import { ideasFor, matchesPrompt, recentPrompts, startQuickAsk, type AskKind } from '../composables/useQuickAsk'
import { consumeEscape } from '../utils/escapeLayers'

const props = defineProps<{
  mediaIds: number[]
  kind: AskKind
  projectId: number | null
  /** Text to start with (typing with a selection lands here). */
  seed?: string
}>()
const emit = defineEmits<{ close: []; sent: [chatId: number] }>()

const { allowsAutofocus } = useViewport()
const text = ref(props.seed || '')
const history = ref(false)
const active = ref(-1)
const sending = ref(false)
const input = ref<HTMLTextAreaElement | null>(null)
const MAX_THUMBS = 8

type Chip = { kind: 'idea' | 'recent'; label: string }
const chips = computed<Chip[]>(() => {
  const q = text.value.trim()
  const seen = new Set([q.toLowerCase()])
  const out: Chip[] = []
  const add = (kind: Chip['kind'], label: string) => {
    const k = label.toLowerCase()
    if (seen.has(k)) return
    seen.add(k)
    out.push({ kind, label })
  }
  if (!q) {
    if (history.value) recentPrompts(props.kind).forEach(r => add('recent', r))
    else ideasFor(props.kind, props.mediaIds.length).forEach(i => add('idea', i))
    return out.slice(0, 6)
  }
  recentPrompts(props.kind).filter(r => matchesPrompt(r, q)).forEach(r => add('recent', r))
  ideasFor(props.kind, props.mediaIds.length).filter(i => matchesPrompt(i, q)).forEach(i => add('idea', i))
  return out.slice(0, 5)
})
watch(text, () => { active.value = -1; if (text.value) history.value = false })

const placeholder = computed(() => props.mediaIds.length === 1 ? 'Do something with this…' : `Do something with these ${props.mediaIds.length}…`)

async function send(prompt = text.value, open = false) {
  if (!prompt.trim() || sending.value) return
  sending.value = true
  const chatId = await startQuickAsk({ prompt, mediaIds: props.mediaIds, projectId: props.projectId, kind: props.kind, open })
  sending.value = false
  if (chatId != null) emit('sent', chatId)
}

function onKey(e: KeyboardEvent) {
  const len = chips.value.length
  if (e.key === 'ArrowDown') {
    if (!text.value && !history.value) { e.preventDefault(); history.value = true; active.value = 0; return }
    if (len) { e.preventDefault(); active.value = active.value >= len - 1 ? -1 : active.value + 1 }
  } else if (e.key === 'ArrowUp' && len && active.value >= 0) {
    e.preventDefault()
    active.value = active.value - 1
  } else if (e.key === 'Tab' && active.value >= 0) {
    e.preventDefault()
    text.value = chips.value[active.value].label
  } else if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    const pick = active.value >= 0 ? chips.value[active.value].label : text.value
    send(pick, e.metaKey || e.ctrlKey)
  } else if (e.key === 'Escape') {
    consumeEscape(e)
    if (text.value) text.value = ''
    else if (history.value) history.value = false
    else emit('close')
  }
}

onMounted(async () => {
  await nextTick()
  if (allowsAutofocus.value || props.seed) {
    input.value?.focus()
    const end = text.value.length
    input.value?.setSelectionRange(end, end)
  }
})
</script>

<template>
  <div
    class="w-[460px] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-lg border border-edge-subtle bg-surface shadow-lg compact:w-auto"
    data-escape-layer
    data-quick-ask
  >
    <div class="flex items-center gap-1 px-3 pt-3">
      <MediaImage
        v-for="mediaId in mediaIds.slice(0, MAX_THUMBS)"
        :key="mediaId"
        :media-id="mediaId"
        :thumbnail="true"
        :thumbnail-size="128"
        :draggable="false"
        :enable-context-menu="false"
        container-class="h-9 w-9 flex-none overflow-hidden rounded-media bg-matte"
        img-class="h-full w-full object-cover"
      />
      <span v-if="mediaIds.length > MAX_THUMBS" class="ml-1 font-mono text-xs tabular-nums text-content-muted">+{{ mediaIds.length - MAX_THUMBS }}</span>
    </div>
    <textarea
      ref="input"
      v-model="text"
      v-no-autocorrect
      rows="2"
      :placeholder="placeholder"
      class="block w-full resize-none bg-transparent px-3 pt-2.5 text-sm leading-relaxed text-content placeholder:text-content-muted focus:outline-none"
      data-quick-ask-input
      @keydown="onKey"
    />
    <div v-if="chips.length" class="flex flex-wrap gap-1.5 px-3 pb-1 pt-1">
      <button
        v-for="(chip, i) in chips"
        :key="chip.kind + chip.label"
        type="button"
        class="flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors"
        :class="i === active ? 'border-accent/60 bg-accent/10 text-content' : 'border-edge-subtle text-content-secondary hover:border-edge hover:text-content'"
        @mousedown.prevent
        @click="send(chip.label)"
      >
        <ClockIcon v-if="chip.kind === 'recent'" class="h-3 w-3 text-content-muted" />
        <AgentIcon v-else class="h-3 w-3 text-content-muted" />
        {{ chip.label }}
      </button>
    </div>
    <div class="flex items-center justify-between px-2 pb-2 pt-1">
      <Tooltip text="Recent">
        <button
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          :class="history ? 'bg-overlay-light text-content' : 'text-content-muted hover:bg-overlay-subtle hover:text-content-secondary'"
          aria-label="Recent"
          :aria-pressed="history"
          @mousedown.prevent
          @click="history = !history; active = -1"
        >
          <ClockIcon class="h-4 w-4" />
        </button>
      </Tooltip>
      <SendButton title="Send" :disabled="!text.trim() || sending" @mousedown.prevent @click="send()" />
    </div>
  </div>
</template>
