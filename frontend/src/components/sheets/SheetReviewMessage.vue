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
    <ul class="m-0 list-none space-y-1.5 p-0">
      <li v-for="(item, index) in review.items" :key="index" class="flex items-start gap-2 text-[12.5px]">
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
            <ChatBubbleLeftIcon v-if="item.kind === 'comment' || item.kind === 'field'" class="h-3.5 w-3.5" />
            <StarIcon v-else-if="item.kind === 'rating'" class="h-3.5 w-3.5" />
            <CheckIcon v-else class="h-3.5 w-3.5" />
          </span>
        </span>
        <span class="min-w-0 flex-1">
          <span class="block break-words text-content">{{ primary(item) }}</span>
          <span v-if="secondary(item)" class="block break-words text-[11px] text-content-muted">{{ secondary(item) }}</span>
        </span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
// A sent contact sheet review, as a card. The message text underneath is what
// the agent reads; this is the same review for the person who sent it.
import { ChatBubbleLeftIcon, CheckIcon, RectangleGroupIcon } from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'
import { MediaImage } from '../media'

interface ReviewItem {
  kind: string
  id: string
  text?: string
  question?: string
  about?: string | null
  media_id?: number | null
}
defineProps<{ review: { asset_id: number; title?: string | null; items: ReviewItem[] } }>()
defineEmits<{ open: [] }>()

function primary(item: ReviewItem) {
  if (item.kind === 'comment') return `“${item.text}”`
  if (item.kind === 'check') return `${item.question}: ${item.text}`
  return item.kind === 'field' ? `“${item.text}”` : item.text || ''
}
function secondary(item: ReviewItem) {
  if (item.kind === 'comment' || item.kind === 'check') return item.about || ''
  return [item.question, item.about].filter(Boolean).join(' · ')
}
</script>
