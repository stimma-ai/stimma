<template>
  <figure
    v-if="mediaId != null"
    class="group/tile relative m-0 min-w-0"
    :class="rect ? '' : 'mb-3'"
    :style="outerStyle"
    :data-kid="kid"
  >
    <div
      ref="pictureEl"
      class="relative block w-full cursor-pointer select-none overflow-hidden rounded-media bg-matte"
      :class="flashing ? 'ring-2 ring-accent ring-offset-2 ring-offset-base' : ''"
      :style="rect ? { height: rect.h + 'px' } : { aspectRatio: aspectStyle }"
      role="button"
      tabindex="0"
      :aria-label="at.caption || 'Open in slideshow'"
      @click="onClick"
      @keydown.enter.prevent="sheet.openSlideshow(kid)"
      @mouseenter="hover(true)"
      @mouseleave="hover(false)"
    >
      <MediaImage
        v-if="member"
        :media-id="mediaId"
        :asset-id="member.asset_id ?? undefined"
        :file-hash="member.file_hash"
        :file-path="member.file_path"
        :file-format="member.file_format"
        :is-video="isVideoMember"
        :has-alpha="member.has_alpha"
        :thumbnail="true"
        :thumbnail-size="thumbnailSize"
        thumbnail-mode="fit"
        :contain="!!rect?.letterbox"
        container-class="h-full w-full"
        img-class="h-full w-full"
        :alt="at.caption || ''"
      />
      <div v-else class="flex h-full w-full items-center justify-center text-[11px] text-content-muted">Unavailable</div>
      <video
        v-if="isVideoMember && playing"
        :src="getMediaFileUrl(mediaId)"
        autoplay muted loop playsinline
        class="pointer-events-none absolute inset-0 h-full w-full object-contain"
      />
      <span v-if="selected" class="pointer-events-none absolute inset-0 z-chrome rounded-media ring-2 ring-inset ring-selection" />
      <span v-else-if="picked" class="pointer-events-none absolute inset-0 z-chrome rounded-media ring-2 ring-inset ring-accent" />

      <!-- Markers: the profile's own, icon and color only; the name is the
           tooltip. With a mouse, unset ones wait for hover. On touch and on
           small tiles only set ones show; they're set in the slideshow. -->
      <div v-if="!small && !coarse && availableMarkers.length && !sheet.readonly.value" class="absolute bottom-1.5 left-1.5 z-chrome flex gap-0.5">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          type="button"
          :class="[
            'flex h-6 w-6 items-center justify-center rounded-md transition-all',
            hasMarker(mediaId, marker.id) ? 'bg-black/55 backdrop-blur-md' : 'bg-black/40 text-white/60 opacity-0 hover:bg-black/60 hover:text-white group-hover/tile:opacity-100',
          ]"
          :style="hasMarker(mediaId, marker.id) ? { color: marker.color } : {}"
          :title="hasMarker(mediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
          @click.stop="toggleMarker(mediaId, marker)"
        >
          <span class="icon-container flex h-3.5 w-3.5 items-center justify-center" v-html="sanitizeSvg(marker.icon_svg)" />
        </button>
      </div>
      <div v-else-if="setMarkers.length" class="pointer-events-none absolute z-chrome flex gap-0.5" :class="small ? 'bottom-1 left-1' : 'bottom-1.5 left-1.5'">
        <span
          v-for="marker in setMarkers"
          :key="marker.id"
          class="icon-container flex items-center justify-center drop-shadow-[0_1px_2px_rgba(0,0,0,0.7)]"
          :class="small ? 'h-3.5 w-3.5' : 'h-4 w-4'"
          :style="{ color: marker.color }"
          v-html="sanitizeSvg(marker.icon_svg)"
        />
      </div>

      <!-- A picture a choice is asking about is picked here, where it is seen
           whole, with the browser's checkbox: a small mark in a hit area big
           enough for a finger. -->
      <div v-if="picks.length || (isNew && !showCaption)" class="absolute left-0 top-0 z-chrome flex items-start">
        <button
          v-for="pick in picks"
          :key="`${pick.choiceId}:${pick.value}`"
          type="button"
          class="group/pick flex items-start justify-start disabled:cursor-default"
          :class="small ? 'p-1' : 'p-1.5 coarse:pb-3 coarse:pr-3'"
          :aria-pressed="sheet.isPicked(pick.choiceId, pick.value)"
          :aria-label="pick.question ? `${pick.question} ${pick.label}` : pick.label"
          :title="pick.question ? `${pick.question} ${pick.label}` : pick.label"
          :disabled="sheet.readonly.value"
          @click.stop="sheet.togglePick(pick)"
        >
          <span
            class="flex items-center justify-center border-2 backdrop-blur-md transition-colors"
            :class="[
              small ? 'h-4 w-4' : 'h-5 w-5',
              pick.multiple ? 'rounded-md' : 'rounded-full',
              sheet.isPicked(pick.choiceId, pick.value) ? 'border-accent bg-accent text-on-accent' : 'border-white/60 bg-black/45 text-transparent group-hover/pick:border-white/90',
            ]"
          ><CheckIcon :class="small ? 'h-2.5 w-2.5' : 'h-3.5 w-3.5'" stroke-width="3" /></span>
        </button>
        <Transition leave-active-class="transition-opacity duration-700" leave-to-class="opacity-0">
          <span v-if="isNew && !showCaption" class="ml-1.5 mt-1.5 h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-base" title="New" />
        </Transition>
      </div>
      <!-- With a caption, Comment sits at the end of it, off the picture.
           Without one it waits for hover, or shows a quiet count on touch. -->
      <div v-if="!small && !showCaption && !sheet.readonly.value && (commentCount || !coarse)" class="absolute right-0 top-0 z-chrome">
        <button
          type="button"
          class="flex items-start justify-end p-1.5 transition-opacity coarse:pb-3 coarse:pl-3"
          :class="commentCount ? 'opacity-100' : 'opacity-0 group-hover/tile:opacity-100'"
          title="Comment"
          @click.stop="comment"
        >
          <span class="flex h-5 items-center gap-0.5 rounded bg-black/55 px-1 text-white/90 backdrop-blur-md">
            <ChatBubbleLeftIcon class="h-3 w-3" />
            <span v-if="commentCount" class="font-mono text-[10px] tabular-nums">{{ commentCount }}</span>
          </span>
        </button>
      </div>
      <span v-if="small && commentCount" class="pointer-events-none absolute bottom-1 right-1 flex items-center gap-0.5 rounded bg-black/55 px-1 font-mono text-[9px] text-white">
        <ChatBubbleLeftIcon class="h-2.5 w-2.5" />{{ commentCount }}
      </span>
      <span
        v-if="isVideoMember && !small && member?.duration"
        class="pointer-events-none absolute bottom-2 right-2 flex items-center gap-1 rounded bg-black/55 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-white backdrop-blur group-hover/tile:opacity-0"
      >
        <PlayIcon class="h-2.5 w-2.5" />{{ formatDuration(member.duration) }}
      </span>
    </div>
    <figcaption
      v-if="showCaption"
      ref="captionEl"
      class="flex items-start gap-1.5 pt-1 text-[12px] leading-snug text-content-secondary"
    >
      <span class="min-w-0 flex-1 break-words">
        <Transition leave-active-class="transition-opacity duration-700" leave-to-class="opacity-0">
          <span v-if="isNew" class="mb-px mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" title="New" />
        </Transition>{{ at.caption }}
      </span>
      <button
        v-if="!sheet.readonly.value"
        type="button"
        class="-my-1 -mr-1 flex flex-none items-center gap-0.5 rounded p-1 transition-opacity hover:text-content coarse:-my-2.5 coarse:py-2.5 coarse:pl-2.5"
        :class="commentCount ? 'text-content-secondary' : 'text-content-muted opacity-60 hover:opacity-100'"
        :title="commentCount ? `${commentCount} ${commentCount === 1 ? 'comment' : 'comments'}` : 'Comment'"
        @click.stop="comment"
      >
        <ChatBubbleLeftIcon class="h-3.5 w-3.5" />
        <span v-if="commentCount" class="font-mono text-[11px] tabular-nums">{{ commentCount }}</span>
      </button>
    </figcaption>
  </figure>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { ChatBubbleLeftIcon, CheckIcon, PlayIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import { useMarkers } from '../../composables/useMarkers'
import { useViewport } from '../../composables/useViewport'
import { useMediaApi } from '../../composables/useMediaApi'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { formatDuration, isVideo } from '../../utils/mediaTypes'
import { mediaIdOfRef } from './sheetHtml'
import { useSheetContext } from './useContactSheet'
import type { Placement, SheetSize } from './sheetLayout'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const { isCoarsePointer: coarse } = useViewport()
const placement = inject<Ref<Placement> | null>('sheetPlacement', null)
const reportCaption = inject<((id: string, height: number) => void) | null>('sheetCaptionHeight', null)
const groupSize = inject<Ref<SheetSize> | null>('sheetGroupSize', null)
const { getMediaFileUrl } = useMediaApi()
const { availableMarkers, init, loadMarkersForMedia, hasMarker, toggleMarker } = useMarkers()

const mediaId = computed(() => mediaIdOfRef(props.at.ref))
const member = computed(() => sheet.member(mediaId.value))
const kid = computed(() => props.kid || '')
const isVideoMember = computed(() => !!member.value && isVideo({ file_format: member.value.file_format }))
onMounted(async () => {
  await init()
  if (mediaId.value != null) loadMarkersForMedia([mediaId.value])
})

const inGroup = computed(() => !!placement && props.node?.parentElement?.tagName === 'STIMMA-MEDIA-GROUP')
const rect = computed(() => (inGroup.value ? placement!.value.rects[kid.value] ?? null : null))
const small = computed(() => inGroup.value && groupSize?.value === 's')
const outerStyle = computed(() => {
  if (!inGroup.value) return undefined
  const r = rect.value
  if (!r) return { display: 'none' }
  return { position: 'absolute' as const, left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px` }
})
const aspectStyle = computed(() => {
  const w = member.value?.width, h = member.value?.height
  return w && h ? `${w} / ${h}` : '4 / 3'
})
const thumbnailSize = computed(() => {
  const longest = rect.value ? Math.max(rect.value.w, rect.value.h) : 900
  return longest * (window.devicePixelRatio || 1) > 560 ? 1024 : 512
})
const setMarkers = computed(() => availableMarkers.value.filter(m => mediaId.value != null && hasMarker(mediaId.value, m.id)))
const commentCount = computed(() => sheet.commentsFor(kid.value).length)
const isNew = computed(() => sheet.newIds.value.has(kid.value))
const selected = computed(() => sheet.selected.value.has(kid.value))
const flashing = computed(() => sheet.flashIds.value.includes(kid.value))
const picks = computed(() => sheet.picksFor(mediaId.value))
const picked = computed(() => picks.value.some(pick => sheet.isPicked(pick.choiceId, pick.value)))
const showCaption = computed(() => !!props.at.caption && !small.value)

// New until it has actually been on screen.
const pictureEl = ref<HTMLElement | null>(null)
let stopSeen: (() => void) | null = null
watch([isNew, pictureEl], ([fresh, el]) => {
  stopSeen?.()
  stopSeen = fresh && el && mediaId.value != null ? sheet.watchSeen(el, () => [mediaId.value!]) : null
}, { immediate: true })

// A group places its tiles itself, so it needs to know how tall each wrapped caption is.
const captionEl = ref<HTMLElement | null>(null)
let captionObserver: ResizeObserver | null = null
watch(captionEl, el => {
  captionObserver?.disconnect()
  captionObserver = null
  if (!el || !reportCaption || !inGroup.value) return
  captionObserver = new ResizeObserver(() => reportCaption(kid.value, Math.ceil(el.offsetHeight)))
  captionObserver.observe(el)
}, { immediate: true })
onBeforeUnmount(() => { stopSeen?.(); captionObserver?.disconnect() })

function onClick(event: MouseEvent) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || (sheet.selected.value.size && !coarse.value)) {
    sheet.toggleSelect(kid.value)
    return
  }
  sheet.openSlideshow(kid.value)
}

function comment(event: MouseEvent) {
  const r = (event.currentTarget as HTMLElement).getBoundingClientRect()
  sheet.commentFor.value = { id: kid.value, label: String(props.at.caption || 'this picture'), x: r.right, y: r.bottom + 6, mediaId: mediaId.value }
}

const playing = ref(false)
function hover(on: boolean) {
  if (isVideoMember.value && !coarse.value) playing.value = on
}
</script>
