<template>
  <div class="relative flex h-full min-h-0 w-full flex-col bg-base">
    <!-- The selection, only while there is one. -->
    <div v-if="sheet.selected.value.size" class="flex flex-none items-center gap-2 border-b border-edge-subtle px-4 py-1.5 compact:px-3">
      <span class="flex-1 font-mono text-xs tabular-nums text-selection">{{ sheet.selected.value.size }} selected</span>
      <Button variant="ghost" size="sm" @click="sheet.clearSelection()">Clear</Button>
      <Button v-if="collections" variant="primary" size="sm" @click="attachSelection">Add to message</Button>
    </div>

    <div class="relative min-h-0 flex-1">
      <div ref="scroller" class="absolute inset-0 overflow-y-auto custom-scrollbar" @scroll.passive="placeNewPill">
        <div v-if="error" class="flex h-full items-center justify-center px-8 text-center text-sm text-content-muted">{{ error }}</div>
        <div v-else-if="!sheet.content.value" class="flex h-full items-center justify-center text-sm text-content-muted">Loading…</div>
        <SheetDocument v-else :key="mediaId ?? 0" :scope="scope" :css="css" class="mx-auto max-w-[1120px] px-8 pb-28 pt-7 compact:px-4 compact:pt-5" />
      </div>

      <!-- New work you haven't had on screen yet, and which way it is. -->
      <Transition enter-from-class="opacity-0" enter-active-class="transition-opacity duration-200" leave-active-class="transition-opacity duration-200" leave-to-class="opacity-0">
        <button
          v-if="newDirection"
          type="button"
          class="absolute left-1/2 z-chrome flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-full border border-edge-subtle bg-surface px-3 text-[12px] font-medium text-content shadow-lg hover:bg-overlay-hover coarse:h-11"
          :class="newDirection === 'up' ? 'top-3' : 'bottom-3'"
          @click="jumpToNew"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-accent" />
          {{ offscreenNew }} new
          <component :is="newDirection === 'up' ? ArrowUpIcon : ArrowDownIcon" class="h-3.5 w-3.5 text-content-secondary" />
        </button>
      </Transition>
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
import { computed, inject, nextTick, ref, toRef, watch } from 'vue'
import { ArrowDownIcon, ArrowUpIcon } from '@heroicons/vue/24/outline'
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
watch(() => props.mediaId, async mediaId => {
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

const pendingSummary = computed(() => {
  const answers = sheet.pendingAnswerCount.value
  const comments = sheet.pendingCommentCount.value
  const parts = []
  if (answers) parts.push(`${answers} ${answers === 1 ? 'answer' : 'answers'}`)
  if (comments) parts.push(`${comments} ${comments === 1 ? 'comment' : 'comments'}`)
  return parts.join(' · ')
})

// New tiles out of view, nearest first in the direction they lie. Tiles in a
// folded section count where the section's header is.
function newTargets() {
  const box = scroller.value?.getBoundingClientRect()
  const out = { above: [] as HTMLElement[], below: [] as HTMLElement[], count: 0 }
  if (!box) return out
  for (const id of sheet.newIds.value) {
    const el = scroller.value!.querySelector<HTMLElement>(`[data-kid="${CSS.escape(id)}"]`)
      ?? scroller.value!.querySelector<HTMLElement>(`[data-kid="${CSS.escape(sectionOf(id) || '')}"]`)
    if (!el) continue
    const r = el.getBoundingClientRect()
    if (r.bottom < box.top + 24) out.above.push(el)
    else if (r.top > box.bottom - 24) out.below.push(el)
    else continue
    out.count++
  }
  out.above.sort((x, y) => y.getBoundingClientRect().bottom - x.getBoundingClientRect().bottom)
  out.below.sort((x, y) => x.getBoundingClientRect().top - y.getBoundingClientRect().top)
  return out
}
/** The nearer of the closest new work above and below. */
function nearestNew() {
  const box = scroller.value?.getBoundingClientRect()
  const { above, below, count } = newTargets()
  if (!box) return { el: null, direction: null, count }
  const up = above[0] ? box.top - above[0].getBoundingClientRect().bottom : Infinity
  const down = below[0] ? below[0].getBoundingClientRect().top - box.bottom : Infinity
  if (up === Infinity && down === Infinity) return { el: null, direction: null, count }
  return down <= up ? { el: below[0], direction: 'down' as const, count } : { el: above[0], direction: 'up' as const, count }
}
function sectionOf(tileId: string) {
  return sheet.root.value?.querySelector(`[id="${CSS.escape(tileId)}"]`)?.closest('stimma-section')?.id ?? null
}
const newDirection = ref<'up' | 'down' | null>(null)
const offscreenNew = ref(0)
let placing = 0
function placeNewPill() {
  if (placing) return
  placing = requestAnimationFrame(() => {
    placing = 0
    const { direction, count } = nearestNew()
    newDirection.value = direction
    offscreenNew.value = count
  })
}
watch(() => sheet.newIds.value, () => nextTick(placeNewPill))
watch(() => sheet.content.value, () => setTimeout(placeNewPill, 300))

function jumpToNew() {
  const { el } = nearestNew()
  if (!el) return
  const id = el.dataset.kid || ''
  sheet.flashIds.value = [id]
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => { if (sheet.flashIds.value[0] === id) sheet.flashIds.value = [] }, 2000)
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
