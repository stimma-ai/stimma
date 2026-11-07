<template>
  <figure v-if="a != null && b != null" class="group/tile relative my-3 min-w-0" :data-kid="kid">
    <div
      ref="box"
      class="relative w-full cursor-ew-resize touch-none select-none overflow-hidden rounded-media bg-matte"
      :style="{ aspectRatio }"
      @pointerdown="drag"
    >
      <MediaImage :media-id="b" :thumbnail="true" :thumbnail-size="1024" thumbnail-mode="fit" :contain="true" container-class="absolute inset-0 h-full w-full" :draggable="false" />
      <div class="absolute inset-0" :style="{ clipPath: `inset(0 ${100 - split}% 0 0)` }">
        <MediaImage :media-id="a" :thumbnail="true" :thumbnail-size="1024" thumbnail-mode="fit" :contain="true" container-class="h-full w-full" :draggable="false" />
      </div>
      <span class="pointer-events-none absolute inset-y-0 w-px bg-white/80" :style="{ left: `${split}%` }" />
      <span class="pointer-events-none absolute top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/70 bg-black/50 backdrop-blur" :style="{ left: `${split}%` }" />
      <span class="pointer-events-none absolute bottom-1.5 left-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">Before</span>
      <span class="pointer-events-none absolute bottom-1.5 right-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">After</span>
      <button
        v-if="!sheet.readonly.value && kid"
        type="button"
        class="absolute right-1.5 top-1.5 z-chrome flex h-7 items-center gap-1 rounded-md bg-black/40 px-1.5 text-white/80 transition-opacity hover:bg-black/60 hover:text-white"
        :class="commentCount ? 'opacity-100' : 'opacity-0 group-hover/tile:opacity-100 coarse:opacity-100'"
        title="Comment"
        @pointerdown.stop
        @click.stop="comment"
      >
        <ChatBubbleLeftIcon class="h-4 w-4" />
        <span v-if="commentCount" class="font-mono text-[11px] tabular-nums">{{ commentCount }}</span>
      </button>
    </div>
    <figcaption v-if="at.caption" class="pt-1 text-[12px] text-content-secondary">{{ at.caption }}</figcaption>
  </figure>
</template>

<script setup lang="ts">
// <stimma-compare a="media:1" b="media:2" caption>: before and after on a slider.
import { computed, ref } from 'vue'
import { ChatBubbleLeftIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import { mediaIdOfRef } from './sheetHtml'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const a = computed(() => mediaIdOfRef(props.at.a))
const b = computed(() => mediaIdOfRef(props.at.b))
const aspectRatio = computed(() => {
  const m = sheet.member(b.value)
  return m?.width && m?.height ? `${m.width} / ${m.height}` : '4 / 3'
})
const split = ref(50)
const box = ref<HTMLElement | null>(null)
const commentCount = computed(() => (props.kid ? sheet.commentsFor(props.kid).length : 0))

function drag(event: PointerEvent) {
  const r = box.value!.getBoundingClientRect()
  const move = (e: PointerEvent) => { split.value = Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)) }
  move(event)
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

function comment(event: MouseEvent) {
  if (!props.kid) return
  const r = (event.currentTarget as HTMLElement).getBoundingClientRect()
  sheet.commentFor.value = { id: props.kid, label: String(props.at.caption || 'this comparison'), x: r.right, y: r.bottom + 6, mediaId: b.value }
}
</script>
