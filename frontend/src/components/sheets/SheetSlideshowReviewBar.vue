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
      <template v-for="field in fields" :key="field.key">
        <span v-if="field.kind === 'rating'" class="flex flex-none gap-px">
          <StarIcon v-for="n in 5" :key="n" class="h-3 w-3" :class="rating(field.id) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
        </span>
        <span v-else-if="isOn(field)" class="flex flex-none items-center gap-1 text-accent-hi"><CheckIcon class="h-3.5 w-3.5" stroke-width="2.5" />{{ field.label }}</span>
        <span v-else class="flex-none text-content-muted">{{ field.label }}?</span>
      </template>
      <span class="flex flex-none items-center gap-1 text-content-secondary">
        <ChatBubbleLeftIcon class="h-3.5 w-3.5" /><span v-if="thread.length" class="font-mono tabular-nums">{{ thread.length }}</span>
        <span v-else-if="!fields.length">Comment</span>
      </span>
    </span>
    <ChevronUpIcon class="h-4 w-4 flex-none text-content-muted transition-transform" :class="open ? 'rotate-180' : ''" />
  </button>

  <!-- Bar: small buttons in the slideshow's top band (desktop), styled like
       Close. A rating shows "3★" and opens a picker; Comment opens the same
       comment menu as the sheet. -->
  <template v-else-if="part === 'bar' && active">
    <template v-for="field in fields" :key="field.key">
      <div v-if="field.kind === 'rating'" class="relative">
        <button
          type="button"
          :class="barButton"
          :title="field.label"
          :aria-expanded="ratingMenu === field.id"
          @click="ratingMenu = ratingMenu === field.id ? null : field.id"
        >
          <span v-if="rating(field.id)" class="font-mono text-[12px] tabular-nums text-content">{{ rating(field.id) }}</span>
          <StarIcon v-if="rating(field.id)" class="h-4 w-4 text-amber-400" />
          <StarOutlineIcon v-else class="h-icon-canvas w-icon-canvas" />
        </button>
        <template v-if="ratingMenu === field.id">
          <div class="fixed inset-0 z-menu" @click="ratingMenu = null" />
          <div class="absolute right-0 top-full z-menu mt-1 flex items-center rounded-lg border border-edge-subtle bg-surface p-1 shadow-lg" @mouseleave="hover = 0">
            <button
              v-for="n in 5"
              :key="n"
              type="button"
              class="flex h-8 w-7 items-center justify-center"
              :title="`${n} of 5`"
              @mouseenter="hover = n"
              @click="pickRating(field.id, n)"
            >
              <StarIcon class="h-4 w-4 transition-colors" :class="(hover || rating(field.id)) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
            </button>
            <button v-if="rating(field.id)" type="button" class="ml-1 h-8 rounded-md px-2 text-[12px] text-content-tertiary hover:bg-overlay-subtle hover:text-content" @click="pickRating(field.id, 0)">Clear</button>
          </div>
        </template>
      </div>
      <button
        v-else
        type="button"
        :class="[barButton, isOn(field) ? 'text-accent-hi' : '']"
        :title="field.question ? `${field.question} ${field.label}` : field.label"
        :aria-pressed="isOn(field)"
        @click="toggleField(field)"
      >
        <CheckIcon class="h-4 w-4" stroke-width="2.5" /><span class="max-w-32 truncate text-[12px]">{{ field.label }}</span>
      </button>
    </template>
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
    <div v-for="field in fields" :key="field.key" :class="rowClass">
      <span :class="keyClass">{{ field.kind === 'rating' ? field.label : field.question || field.label }}</span>
      <div v-if="field.kind === 'rating'" class="flex">
        <button
          v-for="n in 5"
          :key="n"
          type="button"
          class="flex h-9 w-9 items-center justify-center"
          :title="`${n} of 5`"
          @click="setRating(field.id, n)"
        >
          <StarIcon class="h-5 w-5" :class="rating(field.id) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
        </button>
      </div>
      <button
        v-else
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
// part goes and whether the review is open. It carries only what the agent
// tied to the picture on screen (a rating or check with for=, a choice option
// that refs it) plus comments, which every picture takes.
import { computed, ref, watch } from 'vue'
import { ChatBubbleLeftIcon, CheckIcon, ChevronUpIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'
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

interface Field { key: string; kind: 'rating' | 'check' | 'choice'; id: string; label: string; question?: string; value?: string; multiple?: boolean }

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
  for (const tile of tileIds.value) {
    root.querySelectorAll(`stimma-rating[for="${CSS.escape(tile)}"]`).forEach(el => {
      if (el.id) out.push({ key: `r-${el.id}`, kind: 'rating', id: el.id, label: el.getAttribute('label') || 'Rating' })
    })
    root.querySelectorAll(`stimma-check[for="${CSS.escape(tile)}"]`).forEach(el => {
      if (el.id) out.push({ key: `c-${el.id}`, kind: 'check', id: el.id, label: (el.textContent || '').trim() || 'Yes' })
    })
  }
  // A rating or check with no for= belongs to the one picture it sits beside:
  // the nearest enclosing element that holds exactly one tile.
  root.querySelectorAll('stimma-rating:not([for]), stimma-check:not([for])').forEach(el => {
    if (!el.id || !tileIds.value.includes(soleTileNear(el) ?? '')) return
    if (el.tagName === 'STIMMA-RATING') out.push({ key: `r-${el.id}`, kind: 'rating', id: el.id, label: el.getAttribute('label') || 'Rating' })
    else out.push({ key: `c-${el.id}`, kind: 'check', id: el.id, label: (el.textContent || '').trim() || 'Yes' })
  })
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

function soleTileNear(el: Element): string | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const tiles = node.querySelectorAll('stimma-media, stimma-compare')
    if (tiles.length === 1) return tiles[0].id || null
    if (tiles.length > 1) return null
  }
  return null
}

const anchor = computed(() => tileIds.value[0] || props.entry?.id || '')
const thread = computed(() => (anchor.value ? props.sheet.commentsFor(anchor.value) : []))

const rowClass = 'flex items-center gap-3 compact:flex-col compact:items-start compact:gap-1'
const keyClass = 'w-16 flex-none truncate text-[11px] text-content-muted compact:w-auto'

function answer(id: string) { return props.sheet.answers.value[id]?.value }
function rating(id: string) { return Number(answer(id) || 0) }
function setRating(id: string, n: number) { props.sheet.setAnswer(id, rating(id) === n ? 0 : n) }
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
const ratingMenu = ref<string | null>(null)
const hover = ref(0)
watch(anchor, () => { ratingMenu.value = null })
function pickRating(id: string, n: number) {
  props.sheet.setAnswer(id, n)
  ratingMenu.value = null
  hover.value = 0
}
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
