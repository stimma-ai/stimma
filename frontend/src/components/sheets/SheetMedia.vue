<template>
  <figure
    v-if="mediaId != null"
    class="group/tile relative m-0 min-w-0"
    :class="rect ? '' : 'mb-3'"
    :style="outerStyle"
    :data-kid="kid"
  >
    <div
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

      <!-- Markers: the profile's own, drawn as OutputImage draws them. Icon and
           colour only; the name is the tooltip. Unset ones wait for hover. -->
      <div v-if="!small && availableMarkers.length && !sheet.readonly.value" class="absolute bottom-2 left-2 z-chrome flex gap-0.5">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          type="button"
          :class="[
            'flex h-7 w-7 items-center justify-center rounded-md border-2 transition-all coarse:h-11 coarse:w-11',
            hasMarker(mediaId, marker.id) ? 'bg-black/80' : 'border-transparent bg-black/40 text-white/50 hover:bg-black/60 hover:text-white',
            !hasMarker(mediaId, marker.id) ? 'opacity-0 group-hover/tile:opacity-100 [[data-pointer=coarse]_&]:hidden' : '',
          ]"
          :style="hasMarker(mediaId, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
          :title="hasMarker(mediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
          @click.stop="toggleMarker(mediaId, marker)"
        >
          <span class="icon-container flex h-4 w-4 items-center justify-center" v-html="sanitizeSvg(marker.icon_svg)" />
        </button>
      </div>
      <div v-else-if="small && setMarkers.length" class="pointer-events-none absolute bottom-1 left-1 z-chrome flex gap-0.5">
        <span
          v-for="marker in setMarkers"
          :key="marker.id"
          class="icon-container flex h-3.5 w-3.5 items-center justify-center drop-shadow"
          :style="{ color: marker.color }"
          v-html="sanitizeSvg(marker.icon_svg)"
        />
      </div>

      <div class="absolute right-1.5 top-1.5 z-chrome flex items-center gap-1">
        <span
          v-if="isNew"
          class="rounded-full bg-accent px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-wide text-white shadow"
          :class="small ? '!px-1 !text-[8px]' : ''"
        >new</span>
        <button
          v-if="!small && !sheet.readonly.value"
          type="button"
          class="flex h-7 items-center justify-center gap-1 rounded-md bg-black/40 px-1.5 text-white/80 transition-opacity hover:bg-black/60 hover:text-white coarse:h-11 coarse:min-w-11"
          :class="commentCount ? 'opacity-100' : 'opacity-0 group-hover/tile:opacity-100 coarse:opacity-100'"
          title="Comment"
          @click.stop="comment"
        >
          <ChatBubbleLeftIcon class="h-4 w-4" />
          <span v-if="commentCount" class="font-mono text-[11px] tabular-nums">{{ commentCount }}</span>
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
      v-if="at.caption && !small"
      class="truncate pt-1 text-[12px] leading-snug text-content-secondary"
      :title="String(at.caption)"
    >{{ at.caption }}</figcaption>
  </figure>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, type Ref } from 'vue'
import { ChatBubbleLeftIcon, PlayIcon } from '@heroicons/vue/24/outline'
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
