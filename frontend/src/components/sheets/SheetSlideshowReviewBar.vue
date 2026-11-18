<template>
  <!-- Pill: the answers so far, in the compact dock. Tapping it opens the panel. -->
  <button
    v-if="part === 'pill' && active"
    type="button"
    class="flex h-11 min-w-0 flex-1 items-center gap-3 overflow-hidden whitespace-nowrap rounded-lg px-3 text-[12px] text-content-tertiary transition-colors"
    :class="open ? 'bg-overlay-light' : 'bg-overlay-subtle hover:bg-overlay-hover'"
    :aria-expanded="open"
    aria-label="Review"
    @click="$emit('toggle')"
  >
    <span class="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
      <span v-if="style === 'stars'" class="flex flex-none gap-px">
        <StarIcon v-for="n in 5" :key="n" class="h-3 w-3" :class="(review.stars || 0) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
      </span>
      <HandThumbUpSolid v-else-if="style === 'thumbs' && review.thumb === 'up'" class="h-4 w-4 flex-none text-accent-hi" />
      <HandThumbDownSolid v-else-if="style === 'thumbs' && review.thumb === 'down'" class="h-4 w-4 flex-none text-red-400" />
      <HandThumbUpIcon v-else-if="style === 'thumbs'" class="h-4 w-4 flex-none text-content-muted" />
      <span v-for="label in review.labels || []" :key="label" class="flex flex-none items-center gap-1 text-accent-hi"><CheckIcon class="h-3.5 w-3.5" stroke-width="2.5" />{{ label }}</span>
      <template v-for="field in fields" :key="field.key">
        <span v-if="isOn(field)" class="flex flex-none items-center gap-1 text-accent-hi"><CheckIcon class="h-3.5 w-3.5" stroke-width="2.5" />{{ field.label }}</span>
        <span v-else class="flex-none text-content-muted">{{ field.label }}?</span>
      </template>
      <span class="flex flex-none items-center gap-1 text-content-secondary">
        <ChatBubbleLeftIcon class="h-3.5 w-3.5" /><span v-if="thread.length" class="font-mono tabular-nums">{{ thread.length }}</span>
      </span>
    </span>
    <ChevronUpIcon class="h-4 w-4 flex-none text-content-muted transition-transform" :class="open ? 'rotate-180' : ''" />
  </button>

  <!-- Bar: small buttons in the slideshow's top band (desktop), styled like
       Close. A rating shows "3★" and opens a picker; Comment opens the same
       comment menu as the sheet. -->
  <template v-else-if="part === 'bar' && active">
    <div v-if="style === 'stars'" class="relative">
      <button
        type="button"
        :class="barButton"
        title="Rating"
        :aria-expanded="ratingMenu"
        @click="ratingMenu = !ratingMenu"
      >
        <span v-if="review.stars" class="font-mono text-[12px] tabular-nums text-content">{{ review.stars }}</span>
        <StarIcon v-if="review.stars" class="h-4 w-4 text-amber-400" />
        <StarOutlineIcon v-else class="h-icon-canvas w-icon-canvas" />
      </button>
      <template v-if="ratingMenu">
        <div class="fixed inset-0 z-menu" @click="ratingMenu = false" />
        <div class="absolute right-0 top-full z-menu mt-1 flex items-center rounded-lg border border-edge-subtle bg-surface p-1 shadow-lg">
          <SheetRate :sheet="sheet" :anchor="anchor" rating="stars" large />
        </div>
      </template>
    </div>
    <SheetRate v-else-if="style === 'thumbs'" :sheet="sheet" :anchor="anchor" rating="thumbs" large />
    <button
      v-for="label in labels"
      :key="label"
      type="button"
      :class="[barButton, hasLabel(label) ? 'text-accent-hi' : '']"
      :title="label"
      :aria-pressed="hasLabel(label)"
      @click="sheet.toggleLabel(anchor, label)"
    >
      <CheckIcon v-if="hasLabel(label)" class="h-4 w-4" stroke-width="2.5" /><span class="max-w-32 truncate text-[12px]">{{ label }}</span>
    </button>
    <button
      v-for="field in fields"
      :key="field.key"
      type="button"
      :class="[barButton, isOn(field) ? 'text-accent-hi' : '']"
      :title="field.question ? `${field.question} ${field.label}` : field.label"
      :aria-pressed="isOn(field)"
      @click="toggleField(field)"
    >
      <CheckIcon class="h-4 w-4" stroke-width="2.5" /><span class="max-w-32 truncate text-[12px]">{{ field.label }}</span>
    </button>
    <button
      type="button"
      :class="[barButton, thread.length ? 'text-content-secondary' : '']"
      :title="thread.length ? `${thread.length} ${thread.length === 1 ? 'comment' : 'comments'}` : 'Comment'"
      @click="openComments"
    >
      <ChatBubbleLeftIcon class="h-icon-canvas w-icon-canvas" />
      <span v-if="thread.length" class="font-mono text-[12px] tabular-nums">{{ thread.length }}</span>
    </button>
  </template>

  <!-- Panel: every field at full size, and the comments inline. -->
  <div v-else-if="part === 'panel' && active && open" class="flex flex-col gap-3 px-3 pb-2 pt-3">
    <div v-if="style !== 'none'" :class="rowClass">
      <span :class="keyClass">Rating</span>
      <SheetRate :sheet="sheet" :anchor="anchor" :rating="style" large />
    </div>
    <div v-if="labels.length" :class="rowClass">
      <span :class="keyClass">Labels</span>
      <SheetLabels :sheet="sheet" :anchor="anchor" :labels="labels" large />
    </div>
    <div v-for="field in fields" :key="field.key" :class="rowClass">
      <span :class="keyClass">{{ field.question || field.label }}</span>
      <button
        type="button"
        class="flex h-9 w-fit items-center gap-1.5 rounded-full px-3 text-[12px] transition-colors"
        :class="isOn(field) ? 'bg-accent/15 text-accent-hi ring-1 ring-inset ring-accent-hi/45' : 'text-content-secondary ring-1 ring-inset ring-edge-strong hover:text-content'"
        :aria-pressed="isOn(field)"
        @click="toggleField(field)"
      >
        <CheckIcon v-if="isOn(field)" class="h-3.5 w-3.5" stroke-width="2.5" />{{ field.label }}
      </button>
    </div>
    <ul v-if="thread.length" class="m-0 flex list-none flex-col gap-1.5 p-0 pl-[76px] compact:pl-0">
      <li v-for="item in thread" :key="item.id" class="group/comment flex items-start gap-1.5 text-[12.5px] leading-snug">
        <span class="min-w-0 flex-1 whitespace-pre-wrap break-words text-content-secondary">
          <span class="text-content-muted">{{ item.author?.name || 'You' }}{{ item.sent ? '' : ' · not sent' }} · </span>{{ item.value }}
        </span>
        <button
          v-if="!item.sent"
          type="button"
          class="flex h-5 w-5 flex-none items-center justify-center rounded text-content-muted opacity-0 hover:text-red-400 group-hover/comment:opacity-100 coarse:opacity-100"
          title="Delete comment"
          @click="sheet.deleteComment(item.id)"
        ><TrashIcon class="h-3.5 w-3.5" /></button>
      </li>
    </ul>
    <div :class="rowClass">
      <span :class="keyClass">Comment</span>
      <textarea
        v-model="draft"
        rows="1"
        placeholder="Comment for the agent"
        class="block min-h-9 w-full flex-1 resize-none rounded-lg border-0 bg-field px-2.5 py-2 text-[12.5px] text-content placeholder:text-content-muted focus:outline-none focus:ring-1 focus:ring-accent/60"
        @keydown.enter.exact.prevent="post"
        @keydown.stop
      />
    </div>
  </div>
</template>

<script setup lang="ts">
// Review chrome for the app's slideshow. It never sits on the picture: on
// compact screens a pill in the dock opens a panel above it, and on desktop the
// whole review sits in one row in the top band, always open. The slideshow owns where each
// part goes and whether the review is open. It carries what every picture
// takes (the rating, the sheet's labels, comments) plus what the agent tied
// to the picture on screen: a check with for=, a choice option that refs it.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChatBubbleLeftIcon, CheckIcon, ChevronUpIcon, HandThumbUpIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { HandThumbDownIcon as HandThumbDownSolid, HandThumbUpIcon as HandThumbUpSolid, StarIcon } from '@heroicons/vue/24/solid'
import SheetLabels from './SheetLabels.vue'
import SheetRate from './SheetRate.vue'
import { StarIcon as StarOutlineIcon } from '@heroicons/vue/24/outline'
import { mediaIdOfRef, type SheetMediaEntry } from './sheetHtml'
import type { SheetContext } from './useContactSheet'

const props = withDefaults(defineProps<{
  sheet: SheetContext
  entry: SheetMediaEntry | null
  part?: 'pill' | 'panel' | 'bar'
  open?: boolean
}>(), { part: 'pill', open: false })
defineEmits<{ toggle: [] }>()

interface Field { key: string; kind: 'check' | 'choice'; id: string; label: string; question?: string; value?: string; multiple?: boolean }

const active = computed(() => !!props.entry && !props.sheet.readonly.value)

const tileIds = computed(() => {
  const root = props.sheet.root.value
  if (!root || !props.entry) return []
  return Array.from(root.querySelectorAll('stimma-media, stimma-compare'))
    .filter(el => mediaIdOfRef(el.getAttribute('ref') || el.getAttribute('b')) === props.entry!.mediaId)
    .map(el => el.id)
    .filter(Boolean)
})

const fields = computed<Field[]>(() => {
  const root = props.sheet.root.value
  if (!root || !props.entry) return []
  const out: Field[] = []
  for (const check of props.sheet.checksFor(anchor.value)) out.push({ key: `c-${check.id}`, kind: 'check', id: check.id, label: check.label })
  root.querySelectorAll('stimma-option').forEach(el => {
    if (mediaIdOfRef(el.getAttribute('ref')) !== props.entry!.mediaId) return
    const choice = el.closest('stimma-choice')
    if (!choice?.id) return
    const value = el.getAttribute('value') || (el.textContent || '').trim()
    out.push({
      key: `o-${choice.id}-${value}`, kind: 'choice', id: choice.id, value,
      label: (el.textContent || '').trim() || value, question: choice.getAttribute('label') || '',
      multiple: choice.hasAttribute('multiple'),
    })
  })
  return out
})

const anchor = computed(() => tileIds.value[0] || props.entry?.id || '')
const thread = computed(() => (anchor.value ? props.sheet.commentsFor(anchor.value) : []))
const style = computed(() => props.sheet.ratingStyle(anchor.value))
const labels = computed(() => props.sheet.labelsFor(anchor.value))
const review = computed(() => props.sheet.reviewOf(anchor.value))
const hasLabel = (label: string) => !!review.value.labels?.includes(label)

const rowClass = 'flex items-center gap-3 compact:flex-col compact:items-start compact:gap-1'
const keyClass = 'w-16 flex-none truncate text-[11px] text-content-muted compact:w-auto'

function answer(id: string) { return props.sheet.answers.value[id]?.value }
function isOn(field: Field) {
  const value = answer(field.id)
  if (field.kind === 'check') return !!value
  return Array.isArray(value) ? value.map(String).includes(field.value!) : String(value ?? '') === field.value
}
function toggleField(field: Field) {
  if (field.kind === 'check') {
    props.sheet.setAnswer(field.id, !answer(field.id))
  } else if (field.multiple) {
    const current = answer(field.id)
    const next = new Set(Array.isArray(current) ? current.map(String) : [])
    next.has(field.value!) ? next.delete(field.value!) : next.add(field.value!)
    props.sheet.setAnswer(field.id, [...next])
  } else {
    props.sheet.setAnswer(field.id, isOn(field) ? null : field.value)
  }
}

// The top band's buttons share Close's look.
const barButton = 'flex h-9 min-w-9 items-center justify-center gap-1 rounded-md px-2 text-content-tertiary transition-colors hover:bg-overlay-light hover:text-content'
const ratingMenu = ref(false)
watch(anchor, () => { ratingMenu.value = false })
// Escape closes the picker, not the slideshow behind it.
function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !ratingMenu.value) return
  event.stopImmediatePropagation()
  event.preventDefault()
  ratingMenu.value = false
}
onMounted(() => window.addEventListener('keydown', onKey, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true))
function openComments(event: MouseEvent) {
  if (!anchor.value) return
  const r = (event.currentTarget as HTMLElement).getBoundingClientRect()
  props.sheet.commentFor.value = { id: anchor.value, label: props.entry?.caption || 'this picture', x: r.right, y: r.bottom + 6, mediaId: props.entry?.mediaId ?? null }
}

// A draft belongs to the picture it was written about.
const draft = ref('')
watch(anchor, () => { draft.value = '' })
async function post() {
  const text = draft.value.trim()
  if (!text || !anchor.value) return
  draft.value = ''
  await props.sheet.addComment(anchor.value, text)
}
</script>
