<template>
  <div class="relative flex h-full min-h-0 w-full flex-col bg-base">
    <!-- What changed since you looked, and the selection. Only when there is something to say. -->
    <div v-if="sheet.newCount.value || sheet.selected.value.size" class="flex flex-none items-center gap-2 border-b border-edge-subtle px-4 py-1.5 compact:px-3">
      <template v-if="sheet.selected.value.size">
        <span class="flex-1 font-mono text-xs tabular-nums text-selection">{{ sheet.selected.value.size }} selected</span>
        <Button variant="ghost" size="sm" @click="sheet.clearSelection()">Clear</Button>
        <Button v-if="collections" variant="primary" size="sm" @click="attachSelection">Add to message</Button>
      </template>
      <template v-else>
        <button
          type="button"
          class="flex h-7 items-center gap-1 rounded-full bg-accent px-2.5 text-[11.5px] font-semibold text-white transition-colors hover:bg-accent/90"
          @click="jumpToNew"
        >{{ sheet.newCount.value }} new since you looked</button>
        <button
          v-if="jumped"
          type="button"
          class="h-7 rounded-md px-2 text-[11.5px] text-content-secondary hover:bg-overlay-subtle hover:text-content"
          @click="markAllSeen"
        >Mark seen</button>
        <span class="flex-1" />
      </template>
    </div>

    <div ref="scroller" class="relative min-h-0 flex-1 overflow-y-auto custom-scrollbar">
      <div v-if="error" class="flex h-full items-center justify-center px-8 text-center text-sm text-content-muted">{{ error }}</div>
      <div v-else-if="!sheet.content.value" class="flex h-full items-center justify-center text-sm text-content-muted">Loading…</div>
      <SheetDocument v-else :key="mediaId ?? 0" :scope="scope" :css="css" class="mx-auto max-w-[1120px] px-8 pb-28 pt-7 compact:px-4 compact:pt-5" />
    </div>

    <!-- The review: it saves as you go; sending it is one step. -->
    <div
      v-if="sheet.pendingCount.value && !sheet.readonly.value"
      class="flex flex-none items-center gap-3 border-t border-edge-subtle bg-surface px-4 py-2.5 pb-safe compact:px-3"
    >
      <span class="h-1.5 w-1.5 flex-none rounded-full bg-accent" />
      <span class="min-w-0 flex-1 truncate text-[12.5px] text-content-secondary"><span class="text-content">Your review</span> · {{ pendingSummary }}</span>
      <Button v-if="sheet.chatId.value != null" variant="primary" size="sm" :disabled="sheet.sending.value" @click="sheet.send()">
        {{ sheet.sending.value ? 'Sending…' : 'Send to agent' }}
      </Button>
    </div>

    <SheetCommentPopover />
  </div>
</template>

<script setup lang="ts">
// The native contact sheet viewer. The agent's HTML renders as the app, with
// live tiles, review fields and comments.
import axios from 'axios'
import { computed, inject, onBeforeUnmount, ref, toRef, watch } from 'vue'
import Button from '../ui/Button.vue'
import { getApiBase } from '../../apiConfig'
import { CHAT_MEDIA_COLLECTIONS } from '../../composables/useChatMediaCollections'
import { mediaIdOfRef, parseSheet, type SheetContent } from './sheetHtml'
import SheetDocument from './SheetDocument.vue'
import SheetCommentPopover from './SheetCommentPopover.vue'
import { provideContactSheet } from './useContactSheet'

const props = withDefaults(defineProps<{
  mediaId: number | null
  chatId?: number | string | null
  readonly?: boolean
}>(), { chatId: null, readonly: false })

const scope = `s${Math.random().toString(36).slice(2, 9)}`
const sheet = provideContactSheet({ mediaId: toRef(props, 'mediaId'), chatId: toRef(props, 'chatId'), readonly: toRef(props, 'readonly') })
const collections = inject(CHAT_MEDIA_COLLECTIONS, null)
const scroller = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)
const css = ref('')

let loadToken = 0
watch(() => props.mediaId, async (mediaId, previous) => {
  // Leaving a version counts as having looked at it.
  if (previous != null && sheet.content.value) sheet.markSeen()
  error.value = null
  if (mediaId == null) {
    sheet.content.value = null
    sheet.root.value = null
    return
  }
  const token = ++loadToken
  try {
    const { data } = await axios.get<SheetContent>(`${getApiBase()}/media/${mediaId}/content`)
    if (token !== loadToken) return
    const parsed = parseSheet(data.html || '', `[data-sheet-scope="${scope}"]`)
    css.value = parsed.css
    sheet.root.value = parsed.root
    sheet.content.value = data
  } catch (e) {
    if (token !== loadToken) return
    console.error('Failed to load contact sheet:', e)
    error.value = "This contact sheet couldn't be loaded."
  }
}, { immediate: true })

onBeforeUnmount(() => { if (sheet.content.value) sheet.markSeen() })

const pendingSummary = computed(() => {
  const answers = sheet.pendingAnswerCount.value
  const comments = sheet.pendingCommentCount.value
  const parts = []
  if (answers) parts.push(`${answers} ${answers === 1 ? 'answer' : 'answers'}`)
  if (comments) parts.push(`${comments} ${comments === 1 ? 'comment' : 'comments'}`)
  return parts.join(' · ')
})

const jumped = ref(false)
function jumpToNew() {
  const ids = [...sheet.newIds.value]
  if (!ids.length) return
  sheet.flashIds.value = ids
  jumped.value = true
  requestAnimationFrame(() => {
    scroller.value?.querySelector(`[data-kid="${CSS.escape(ids[0])}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  setTimeout(() => { sheet.flashIds.value = [] }, 2600)
}
function markAllSeen() {
  sheet.markSeen()
  jumped.value = false
}

function attachSelection() {
  if (!collections) return
  const ids = [...sheet.selected.value]
    .map(id => mediaIdOfRef(sheet.refOf(id)))
    .filter((id): id is number => id != null)
  collections.attach([...new Set(ids)])
  sheet.clearSelection()
}
</script>
