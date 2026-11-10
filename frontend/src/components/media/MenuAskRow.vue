<script setup lang="ts">
// The context menu's one addition: a prompt aimed at what was right-clicked.
// It has focus when the menu opens, so right-click and type. Untyped, the
// menu below is the ordinary one. Typed, the menu shows only past prompts
// and ideas that match; with no match, one quiet line says what Enter does.
// The rest of a matching past prompt shows greyed inline; Tab or → takes it.
// The clock (or ↓ in an empty prompt) lists past prompts.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ClockIcon } from '@heroicons/vue/24/outline'
import AgentIcon from '../icons/AgentIcon.vue'
import { completionFor, ideasFor, matchesPrompt, recentPrompts, startQuickAsk, type AskKind } from '../../composables/useQuickAsk'

const props = defineProps<{
  mediaIds: number[]
  kind: AskKind
  projectId: number | null
}>()
const emit = defineEmits<{ sent: [chatId: number] }>()
const active = defineModel<boolean>('active', { default: false })

const text = ref('')
const history = ref(false)
const highlighted = ref(-1)
const input = ref<HTMLInputElement | null>(null)
const ghost = computed(() => completionFor(text.value, props.kind))

const rows = computed<{ kind: 'recent' | 'idea'; label: string }[]>(() => {
  const q = text.value.trim()
  if (!q) return history.value ? recentPrompts(props.kind).map(label => ({ kind: 'recent' as const, label })) : []
  const seen = new Set([q.toLowerCase()])
  const out: { kind: 'recent' | 'idea'; label: string }[] = []
  const add = (kind: 'recent' | 'idea', label: string) => {
    const k = label.toLowerCase()
    if (seen.has(k) || !matchesPrompt(label, q)) return
    seen.add(k)
    out.push({ kind, label })
  }
  recentPrompts(props.kind).forEach(r => add('recent', r))
  ideasFor(props.kind, props.mediaIds.length).forEach(i => add('idea', i))
  return out.slice(0, 5)
})
watch([text, history], () => {
  highlighted.value = text.value ? -1 : 0
  if (text.value) history.value = false
  active.value = !!text.value.trim() || history.value
})

const placeholder = computed(() => props.mediaIds.length === 1 ? 'Do something with this…' : `Do something with these ${props.mediaIds.length}…`)

async function send(prompt: string, open = false) {
  if (!prompt.trim()) return
  const chatId = await startQuickAsk({ prompt, mediaIds: props.mediaIds, projectId: props.projectId, kind: props.kind, open })
  if (chatId != null) emit('sent', chatId)
}

function onKey(e: KeyboardEvent) {
  const len = rows.value.length
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!text.value && !history.value) { history.value = true; return }
    if (len) highlighted.value = highlighted.value >= len - 1 ? (text.value ? -1 : 0) : highlighted.value + 1
  } else if (e.key === 'ArrowUp') {
    if (!len) return
    e.preventDefault()
    highlighted.value = highlighted.value <= (text.value ? -1 : 0) ? len - 1 : highlighted.value - 1
  } else if ((e.key === 'Tab' || (e.key === 'ArrowRight' && input.value?.selectionStart === text.value.length)) && ghost.value) {
    e.preventDefault()
    text.value += ghost.value
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const pick = highlighted.value >= 0 ? rows.value[highlighted.value]?.label : null
    send(pick ?? text.value, e.metaKey || e.ctrlKey)
  } else if (e.key === 'Escape') {
    // Clears the prompt first; an empty prompt lets the menu close.
    if (!text.value && !history.value) return
    e.preventDefault()
    text.value = ''
    history.value = false
  }
  // Keys typed here are the prompt's, not the menu's shortcuts.
  e.stopPropagation()
}

onMounted(async () => {
  await nextTick()
  input.value?.focus()
})
</script>

<template>
  <div class="mx-1 mb-1 flex items-center gap-2 rounded-md border py-1 pl-[7px] pr-1 transition-colors" :class="text ? 'border-accent/50 bg-base' : 'border-transparent bg-overlay-subtle'" data-menu-ask>
    <AgentIcon class="h-4 w-4 flex-shrink-0" :class="text ? 'text-accent-hi' : 'text-content-muted'" />
    <div class="relative min-w-0 flex-1">
      <div v-if="ghost" class="pointer-events-none absolute inset-0 truncate whitespace-pre text-xs leading-[22px]" aria-hidden="true"><span class="invisible">{{ text }}</span><span class="text-content-muted">{{ ghost }}</span></div>
      <input
        ref="input"
        v-model="text"
        v-no-autocorrect
        :placeholder="placeholder"
        class="relative block h-[22px] w-full bg-transparent text-xs leading-[22px] text-content placeholder:text-content-muted focus:outline-none"
        data-menu-ask-input
        @keydown="onKey"
      >
    </div>
    <button
      v-if="!text"
      type="button"
      class="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded transition-colors"
      :class="history ? 'bg-overlay-light text-content' : 'text-content-muted hover:bg-overlay-light hover:text-content-secondary'"
      aria-label="Recent"
      :aria-pressed="history"
      @mousedown.prevent
      @click="history = !history"
    >
      <ClockIcon class="h-3.5 w-3.5" />
    </button>
  </div>
  <template v-if="active">
    <button
      v-for="(row, i) in rows"
      :key="row.kind + row.label"
      type="button"
      class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content"
      :class="i === highlighted ? 'bg-overlay-subtle' : 'hover:bg-overlay-subtle'"
      @mouseenter="highlighted = i"
      @click="send(row.label)"
    >
      <ClockIcon v-if="row.kind === 'recent'" class="h-4 w-4 flex-shrink-0 text-content-muted" />
      <AgentIcon v-else class="h-4 w-4 flex-shrink-0 text-content-muted" />
      <span class="min-w-0 flex-1 truncate">{{ row.label }}</span>
    </button>
    <div v-if="text.trim() && !rows.length" class="flex items-center justify-between pb-1.5 pl-9 pr-3 pt-1 text-[11px] text-content-muted">
      <span>Ask about {{ mediaIds.length === 1 ? 'this' : `these ${mediaIds.length}` }}</span><span class="font-mono">↵</span>
    </div>
  </template>
</template>
