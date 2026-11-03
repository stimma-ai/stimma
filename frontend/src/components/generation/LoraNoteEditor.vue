<template>
  <!-- Inline under its row, outside the row's pointer handlers, so typing can't
       toggle or drag the LoRA. -->
  <div
    class="my-1.5 rounded-md bg-overlay-subtle px-2.5 py-2.5 text-xs select-text cursor-auto"
    data-lora-note-editor
    @click.stop
    @pointerdown.stop
    @keydown.escape.stop="$emit('close')"
  >
    <div class="mb-2 font-mono text-[10px] leading-snug break-all text-content-muted">{{ value }}</div>

    <template v-if="showSeries">
      <label class="flex items-start gap-2 text-content cursor-pointer coarse:min-h-11 coarse:items-center">
        <input
          type="checkbox"
          class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-accent coarse:mt-0 coarse:h-5 coarse:w-5"
          :checked="sharedChecked"
          data-lora-note-series
          @change="onToggleSeries(($event.target as HTMLInputElement).checked)"
        />
        <span>
          Same note for all {{ seriesCount }} in this series
          <span class="block text-[11px] leading-snug text-content-muted">{{ seriesHint }}</span>
        </span>
      </label>
      <div v-if="conflicts" class="mt-1.5 ml-[22px] rounded bg-overlay-subtle px-2 py-1.5 text-content-secondary" data-lora-note-conflict>
        {{ conflicts === 1 ? '1 other file has a different note' : `${conflicts} other files have different notes` }}.
        Sharing this one replaces {{ conflicts === 1 ? 'it' : 'them' }}.
        <div class="mt-1 flex gap-3 font-semibold">
          <button type="button" class="text-accent-hi coarse:min-h-11" @click="confirmReplace">Replace</button>
          <button type="button" class="text-content-secondary hover:text-content coarse:min-h-11" @click="conflicts = 0">Keep separate</button>
        </div>
      </div>
      <div class="h-2.5"></div>
    </template>

    <label :for="triggerInputId" class="mb-1 block font-semibold text-content-secondary">Trigger words</label>
    <div class="mb-2.5 flex min-h-8 flex-wrap items-center gap-1 rounded-md border border-transparent bg-overlay-subtle p-1 focus-within:border-accent">
      <span
        v-for="(word, index) in triggers"
        :key="word"
        class="inline-flex items-center gap-1 rounded bg-overlay-light py-0.5 pr-0.5 pl-1.5 font-mono text-[11px] text-content"
      >
        {{ word }}
        <button
          type="button"
          class="flex h-4 w-4 items-center justify-center text-content-tertiary hover:text-content coarse:h-8 coarse:w-8"
          :aria-label="`Remove ${word}`"
          @click="removeTrigger(index)"
        >×</button>
      </span>
      <input
        :id="triggerInputId"
        ref="triggerInput"
        v-no-autocorrect
        v-model="draftTrigger"
        type="text"
        class="min-w-20 flex-1 border-0 bg-transparent px-1 font-mono text-xs text-content outline-none placeholder:text-content-muted coarse:min-h-9"
        :placeholder="triggers.length ? 'Add another' : 'Type and press Enter'"
        data-lora-note-trigger
        @keydown.enter.prevent="commitDraft"
        @keydown="onTriggerKey"
        @blur="commitDraft"
      />
    </div>

    <label :for="notesInputId" class="mb-1 block font-semibold text-content-secondary">Notes for the AI</label>
    <textarea
      :id="notesInputId"
      v-no-autocorrect
      v-model="notes"
      rows="3"
      maxlength="8000"
      class="block w-full resize-y rounded-md border border-transparent bg-overlay-subtle px-2 py-1.5 text-xs leading-snug text-content outline-none placeholder:text-content-muted focus:border-accent"
      placeholder="What is it for? What should the prompt do or avoid? What weight works?"
      data-lora-note-text
      @input="scheduleSave"
    ></textarea>

    <div class="mt-1.5 flex items-center justify-between text-[11px] text-content-muted">
      <span>Used by enhancement and the agent</span>
      <button type="button" class="font-semibold text-content-secondary hover:text-content coarse:min-h-11 coarse:px-2" @click="$emit('close')">Done</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import type { LoraNotes } from '../../composables/useLoraNotes'

const SAVE_DEBOUNCE_MS = 500

const props = defineProps<{
  value: string
  notesApi: LoraNotes
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const item = computed(() => props.notesApi.items.value[props.value])
const triggerInputId = useId()
const notesInputId = useId()

const triggers = ref<string[]>([...(item.value?.note?.trigger_words ?? [])])
const notes = ref(item.value?.note?.notes ?? '')
const draftTrigger = ref('')
const conflicts = ref(0)
const justUnshared = ref(false)
// Before a note exists the box is only an intention, applied on the first save.
const intendShared = ref(item.value?.series?.default_shared ?? false)
const dirty = ref(false)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let saving: Promise<void> = Promise.resolve()

const sharedChecked = computed(() => (item.value?.note ? item.value.note.shared : intendShared.value))
const showSeries = computed(() => !!item.value?.series || (item.value?.note?.linked_count ?? 0) > 1)
const seriesCount = computed(() => Math.max(item.value?.series?.size ?? 0, item.value?.note?.linked_count ?? 0))
const seriesHint = computed(() => {
  if (justUnshared.value) return 'Only this file keeps the note. Tick again to share it.'
  return sharedChecked.value ? 'New checkpoints join automatically.' : 'Found from matching names.'
})

function scheduleSave() {
  dirty.value = true
  justUnshared.value = false
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(flush, SAVE_DEBOUNCE_MS)
}

/** Writes pending text. Sharing runs only after this, so it never races a save. */
function flush(): Promise<void> {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  if (!dirty.value) return saving
  dirty.value = false
  const hadNote = !!item.value?.note
  const words = [...triggers.value]
  const text = notes.value
  saving = saving
    .then(() => props.notesApi.save(props.value, words, text))
    .then(async () => {
      if (!hadNote && intendShared.value && item.value?.note) {
        conflicts.value = await props.notesApi.share(props.value)
      }
    })
    .catch(() => {})
  return saving
}

function addTrigger(raw: string) {
  const word = raw.replace(/,/g, '').trim()
  draftTrigger.value = ''
  if (!word || triggers.value.includes(word)) return
  triggers.value = [...triggers.value, word]
  scheduleSave()
}

function commitDraft() {
  if (draftTrigger.value.trim()) addTrigger(draftTrigger.value)
}

function onTriggerKey(event: KeyboardEvent) {
  if (event.key === ',') {
    event.preventDefault()
    commitDraft()
  } else if (event.key === 'Backspace' && !draftTrigger.value && triggers.value.length) {
    removeTrigger(triggers.value.length - 1)
  }
}

function removeTrigger(index: number) {
  triggers.value = triggers.value.filter((_, i) => i !== index)
  scheduleSave()
}

async function onToggleSeries(checked: boolean) {
  conflicts.value = 0
  justUnshared.value = false
  await flush()
  if (!item.value?.note) {
    intendShared.value = checked
    return
  }
  if (checked) {
    conflicts.value = await props.notesApi.share(props.value)
  } else if (item.value.note.shared) {
    await props.notesApi.unshare(props.value)
    justUnshared.value = true
  }
}

async function confirmReplace() {
  conflicts.value = 0
  await props.notesApi.share(props.value, true)
}

onBeforeUnmount(() => {
  commitDraft()
  flush()
})
</script>
