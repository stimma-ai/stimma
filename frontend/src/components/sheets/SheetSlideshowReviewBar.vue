<template>
  <div
    v-if="entry && !sheet.readonly.value"
    class="absolute left-1/2 z-chrome w-max max-w-[calc(100%-24px)] rounded-lg border border-edge-subtle bg-surface shadow-[0_8px_32px_rgba(0,0,0,0.3),0_4px_8px_rgba(0,0,0,0.2)] backdrop-blur-md"
    :style="{ bottom: `${bottomOffset}px`, transform: 'translateX(-50%)' }"
    @click.stop
  >
    <div class="flex items-center gap-3 overflow-x-auto px-4 py-2.5">
      <span class="flex-shrink-0 text-xs font-semibold text-content-secondary">Review</span>
      <span class="h-4 w-px flex-none bg-edge-subtle" />

      <template v-for="field in fields" :key="field.key">
        <div v-if="field.kind === 'rating'" class="flex flex-none items-center">
          <button
            v-for="n in 5"
            :key="n"
            type="button"
            class="flex h-6 w-5 items-center justify-center coarse:h-11 coarse:w-9"
            :title="`${n} of 5`"
            @click="setRating(field.id, n)"
          >
            <StarIcon class="h-4 w-4" :class="Number(answer(field.id) || 0) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
          </button>
        </div>
        <button
          v-else-if="field.kind === 'check'"
          type="button"
          class="flex flex-none items-center gap-2 rounded-md px-3 py-1 text-[11px] font-medium transition-colors coarse:min-h-11"
          :class="answer(field.id) ? 'bg-accent text-white hover:bg-accent/90' : 'bg-overlay-subtle text-content-secondary hover:bg-overlay-hover hover:text-content'"
          @click="sheet.setAnswer(field.id, !answer(field.id))"
        >
          <CheckIcon v-if="answer(field.id)" class="h-3 w-3" stroke-width="3" />{{ field.label }}
        </button>
        <span v-else class="flex flex-none items-center gap-2">
          <span class="text-[11px] text-content-muted compact:hidden">{{ field.question }}</span>
          <button
            type="button"
            class="flex items-center gap-2 rounded-md px-3 py-1 text-[11px] font-medium transition-colors coarse:min-h-11"
            :class="picked(field) ? 'bg-accent text-white hover:bg-accent/90' : 'bg-overlay-subtle text-content-secondary hover:bg-overlay-hover hover:text-content'"
            @click="pick(field)"
          >
            <CheckIcon v-if="picked(field)" class="h-3 w-3" stroke-width="3" />{{ field.label }}
          </button>
        </span>
      </template>

      <button
        type="button"
        class="flex flex-none items-center gap-1.5 rounded-md bg-overlay-subtle px-3 py-1 text-[11px] font-medium text-content-secondary transition-colors hover:bg-overlay-hover hover:text-content coarse:min-h-11"
        @click="comment"
      >
        <ChatBubbleLeftIcon class="h-3.5 w-3.5" />Comment
        <span v-if="commentCount" class="font-mono tabular-nums">{{ commentCount }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// Review chrome for the app's slideshow, where the flow approval bar sits and
// with its treatment. It carries only what the agent tied to the picture on
// screen (a rating or check with for=, a choice option that refs it) plus a
// comment, which every picture takes.
import { computed } from 'vue'
import { ChatBubbleLeftIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'
import { mediaIdOfRef, type SheetMediaEntry } from './sheetHtml'
import type { SheetContext } from './useContactSheet'

const props = withDefaults(defineProps<{ sheet: SheetContext; entry: SheetMediaEntry | null; bottomOffset?: number }>(), { bottomOffset: 24 })

interface Field { key: string; kind: 'rating' | 'check' | 'choice'; id: string; label: string; question?: string; value?: string; multiple?: boolean }

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
const commentCount = computed(() => (anchor.value ? props.sheet.commentsFor(anchor.value).length : 0))

function answer(id: string) { return props.sheet.answers.value[id]?.value }
function setRating(id: string, n: number) { props.sheet.setAnswer(id, Number(answer(id) || 0) === n ? 0 : n) }
function picked(field: Field) {
  const value = answer(field.id)
  return Array.isArray(value) ? value.map(String).includes(field.value!) : String(value ?? '') === field.value
}
function pick(field: Field) {
  if (field.multiple) {
    const current = answer(field.id)
    const next = new Set(Array.isArray(current) ? current.map(String) : [])
    next.has(field.value!) ? next.delete(field.value!) : next.add(field.value!)
    props.sheet.setAnswer(field.id, [...next])
  } else {
    props.sheet.setAnswer(field.id, picked(field) ? null : field.value)
  }
}
function comment(event: MouseEvent) {
  if (!anchor.value) return
  const r = (event.currentTarget as HTMLElement).getBoundingClientRect()
  props.sheet.commentFor.value = {
    id: anchor.value, label: props.entry?.caption || props.entry?.section || 'this picture',
    x: r.right, y: r.top - 8, up: true, mediaId: props.entry?.mediaId,
  }
}
</script>
