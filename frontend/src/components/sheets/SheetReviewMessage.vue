<template>
  <div>
    <button
      type="button"
      class="mb-2 flex items-start gap-1.5 text-left text-[12px] font-semibold text-content hover:text-content-secondary"
      @click="$emit('open')"
    >
      <RectangleGroupIcon class="mt-0.5 h-3.5 w-3.5 flex-none text-content-secondary" />
      <span class="min-w-0 break-words">Review of {{ review.title || 'the contact sheet' }}</span>
    </button>
    <ul v-if="rows.length" class="m-0 list-none space-y-1.5 p-0">
      <li v-for="(item, index) in rows" :key="index" class="flex items-center gap-2 text-[12.5px]">
        <span class="h-8 w-8 flex-none overflow-hidden rounded-media bg-matte">
          <MediaImage
            v-if="item.media_id"
            :media-id="item.media_id"
            :thumbnail="true"
            :thumbnail-size="128"
            container-class="h-full w-full"
            :enable-context-menu="false"
            :draggable="false"
          />
          <span v-else class="flex h-full w-full items-center justify-center bg-overlay-subtle text-content-muted">
            <ChatBubbleLeftIcon v-if="item.kind === 'comment' || item.kind === 'field' || item.kind === 'feedback'" class="h-3.5 w-3.5" />
            <StarIcon v-else-if="item.kind === 'rating' || item.kind === 'stars'" class="h-3.5 w-3.5" />
            <CheckIcon v-else class="h-3.5 w-3.5" />
          </span>
        </span>
        <span class="min-w-0 flex-1">
          <span class="block break-words text-content">
            {{ primary(item) }}
            <span
              v-for="label in item.mark?.labels"
              :key="label"
              class="ml-1 inline-block rounded-full bg-accent/15 px-1.5 text-[10.5px] text-accent-hi"
            >{{ label }}</span>
          </span>
          <span v-if="secondary(item)" class="block break-words text-[11px] text-content-muted">{{ secondary(item) }}</span>
        </span>
        <RatingMark v-if="item.mark" :mark="item.mark" />
      </li>
    </ul>
    <div v-for="(group, index) in groups" :key="group.key" :class="{ 'mt-2.5': rows.length || index }">
      <div class="mb-1.5 flex items-center gap-1.5 text-[12px] text-content-secondary">
        <RatingMark :mark="group.mark" small />
        <span>{{ group.title ? `${group.title} · ` : '· ' }}{{ group.items.length }}</span>
      </div>
      <div class="flex flex-wrap gap-1">
        <span
          v-for="(item, index) in group.items"
          :key="index"
          class="h-10 w-10 flex-none overflow-hidden rounded-media bg-matte"
          :title="item.about || undefined"
        >
          <MediaImage
            v-if="item.media_id"
            :media-id="item.media_id"
            :thumbnail="true"
            :thumbnail-size="128"
            container-class="h-full w-full"
            :enable-context-menu="false"
            :draggable="false"
          />
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// A sent contact sheet review, as a card. The message text underneath is what
// the agent reads; this is the same review for the person who sent it.
// Rated pictures show the mark the person clicked (a thumb, or a star and its
// score), one row each; past REVIEW_GROUP_AFTER of them they collapse into strips,
// one per verdict.
import { computed, defineComponent, h, type PropType } from 'vue'
import { ChatBubbleLeftIcon, CheckIcon, RectangleGroupIcon } from '@heroicons/vue/24/outline'
import { HandThumbDownIcon, HandThumbUpIcon, StarIcon } from '@heroicons/vue/24/solid'
import { MediaImage } from '../media'
import { sentReviewLayout, type MediaReview, type SentReviewItem, type SentReviewRow } from './sheetReview'

const props = defineProps<{ review: { asset_id: number; title?: string | null; items: SentReviewItem[] } }>()
defineEmits<{ open: [] }>()

const layout = computed(() => sentReviewLayout(props.review.items))
const rows = computed(() => layout.value.rows)
const groups = computed(() => layout.value.groups)

function primary(item: SentReviewRow) {
  if (item.kind === 'rating') return item.about || 'Picture'
  if (item.kind === 'stars') return item.question || 'Rating'
  if (item.kind === 'comment') return `“${item.text}”`
  if (item.kind === 'check') return `${item.question}: ${item.text}`
  return item.kind === 'field' || item.kind === 'feedback' ? `“${item.text}”` : item.text || ''
}
function secondary(item: SentReviewRow) {
  if (item.kind === 'rating') return item.mark ? '' : 'Rating taken back'
  if (item.kind === 'stars') return item.mark ? '' : 'No rating'
  if (item.kind === 'comment' || item.kind === 'check') return item.about || ''
  if (item.kind === 'feedback') return 'Overall feedback'
  return [item.question, item.about].filter(Boolean).join(' · ')
}

// The same marks the sheet uses: teal thumb up, red thumb down, amber star.
const RatingMark = defineComponent({
  props: { mark: { type: Object as PropType<MediaReview>, required: true }, small: Boolean },
  setup(markProps) {
    return () => {
      const size = markProps.small ? 'h-3.5 w-3.5' : 'h-4 w-4'
      const marks = []
      if (markProps.mark.thumb === 'up') marks.push(h(HandThumbUpIcon, { class: `${size} text-accent-hi`, 'aria-label': 'Thumbs up' }))
      if (markProps.mark.thumb === 'down') marks.push(h(HandThumbDownIcon, { class: `${size} text-red-400`, 'aria-label': 'Thumbs down' }))
      if (markProps.mark.stars) {
        marks.push(h('span', { class: 'inline-flex items-center gap-0.5 tabular-nums text-content', 'aria-label': `${markProps.mark.stars} of 5 stars` }, [
          h(StarIcon, { class: `${markProps.small ? 'h-3 w-3' : 'h-3.5 w-3.5'} text-amber-400` }),
          String(markProps.mark.stars),
        ]))
      }
      return marks.length ? h('span', { class: 'flex flex-none items-center gap-1.5' }, marks) : null
    }
  },
})
</script>
