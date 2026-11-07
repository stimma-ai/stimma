<template>
  <Teleport to="body">
    <template v-if="target">
      <div class="fixed inset-0 z-menu" :class="coarse ? 'bg-overlay-backdrop' : ''" @click="close" />
      <div
        class="fixed z-menu flex w-[300px] flex-col rounded-lg border border-edge-subtle bg-surface shadow-lg compact:inset-x-0 compact:bottom-0 compact:w-auto compact:rounded-b-none compact:pb-safe"
        :style="position"
        role="dialog"
        aria-label="Comments"
        @keydown.esc.stop="close"
      >
        <div class="flex items-center gap-2 border-b border-edge-subtle px-3 py-2">
          <span v-if="target.mediaId != null" class="h-7 w-7 flex-none overflow-hidden rounded-media bg-matte">
            <MediaImage :media-id="target.mediaId" :thumbnail="true" :thumbnail-size="128" container-class="h-full w-full" :draggable="false" :enable-context-menu="false" />
          </span>
          <span class="min-w-0 flex-1 truncate text-[12px] text-content-secondary">On <span class="text-content">{{ target.label }}</span></span>
          <IconButton title="Close" @click="close"><XMarkIcon class="h-3.5 w-3.5" /></IconButton>
        </div>
        <ul v-if="thread.length" class="m-0 max-h-48 list-none space-y-2 overflow-y-auto p-3 custom-scrollbar">
          <li v-for="comment in thread" :key="comment.id" class="group/comment text-[12.5px]">
            <div class="flex items-center gap-1.5">
              <span class="font-semibold text-content">{{ comment.author.name || 'You' }}</span>
              <span class="text-content-muted">{{ comment.sent ? 'sent' : 'not sent yet' }}</span>
              <span class="flex-1" />
              <button
                v-if="!comment.sent"
                type="button"
                class="flex h-5 w-5 items-center justify-center rounded text-content-muted opacity-0 hover:bg-overlay-subtle hover:text-red-400 group-hover/comment:opacity-100 coarse:opacity-100"
                title="Delete comment"
                @click="sheet.deleteComment(comment.id)"
              ><TrashIcon class="h-3.5 w-3.5" /></button>
            </div>
            <div class="whitespace-pre-wrap break-words text-content">{{ comment.value }}</div>
          </li>
        </ul>
        <div class="p-2">
          <textarea
            ref="input"
            v-model="text"
            rows="2"
            placeholder="Comment for the agent…"
            class="block w-full resize-none rounded-md border border-edge bg-base px-2.5 py-1.5 text-[12.5px] text-content placeholder:text-content-muted focus:border-accent/60 focus:outline-none"
            @keydown.enter.exact.prevent="post"
          />
          <div class="mt-1.5 flex justify-end">
            <Button variant="primary" size="sm" :disabled="!text.trim()" @click="post">Comment</Button>
          </div>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { TrashIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'
import { MediaImage } from '../media'
import { useViewport } from '../../composables/useViewport'
import { useSheetContext } from './useContactSheet'

const sheet = useSheetContext()
const { isCoarsePointer: coarse, isCompact } = useViewport()
const target = computed(() => sheet.commentFor.value)
const thread = computed(() => (target.value ? sheet.commentsFor(target.value.id) : []))
const text = ref('')
const input = ref<HTMLTextAreaElement | null>(null)
watch(target, value => {
  text.value = ''
  if (value && !coarse.value) nextTick(() => input.value?.focus())
})
const position = computed(() => {
  const t = target.value
  if (!t || isCompact.value) return undefined
  const left = Math.max(8, Math.min(t.x - 300, window.innerWidth - 316))
  return t.up
    ? { left: `${left}px`, bottom: `${Math.max(8, window.innerHeight - t.y)}px` }
    : { left: `${left}px`, top: `${Math.min(t.y, window.innerHeight - 280)}px` }
})
function close() { sheet.commentFor.value = null }
async function post() {
  const t = target.value
  if (!t || !text.value.trim()) return
  const body = text.value.trim()
  text.value = ''
  await sheet.addComment(t.id, body)
}
</script>
