<script setup>
// One image in a collection. The grid tile is OutputImage (status, markers, job
// info and the media menu all live there) with selection on top; the strip tile
// is the slideshow strip's cropped thumbnail.
import { computed, inject } from 'vue'
import { ExclamationCircleIcon, PaperClipIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { MediaImage, AppImage } from '../media'
import OutputImage from './OutputImage.vue'
import { CHAT_MEDIA_COLLECTIONS } from '../../composables/useChatMediaCollections'
import { workspaceMediaUrl } from '../../utils/workspaceMediaUrl'

const props = defineProps({
  row: { type: Object, required: true },
  index: { type: Number, required: true },
  itemId: { type: Number, required: true },
  total: { type: Number, required: true },
  universe: { type: Array, required: true },
  variant: { type: String, default: 'grid' }, // grid | strip
  current: { type: Boolean, default: false },
  overflow: { type: Number, default: 0 },
  showLabel: { type: Boolean, default: false },
  pixelSize: { type: Number, default: null },
  tabbable: { type: Boolean, default: false },
})
const emit = defineEmits(['activate', 'expand', 'view-image', 'retry', 'cancel', 'show-job-info'])

const collections = inject(CHAT_MEDIA_COLLECTIONS)
const { selection } = collections

const mediaId = computed(() => props.row.output?.media_id ?? null)
const status = computed(() => props.row.output?.status)
const pickable = computed(() => props.universe.includes(mediaId.value) && !props.overflow)
const selected = computed(() => pickable.value && selection.owner.value === props.itemId && selection.ids.has(mediaId.value))
const selecting = computed(() => selection.selecting.value && selection.owner.value === props.itemId)
const attached = computed(() => mediaId.value != null && collections.isAttached(mediaId.value))

const description = computed(() => {
  const n = props.index + 1
  if (props.overflow) return `Show all ${props.total} images`
  if (status.value === 'failed') return `Image ${n} of ${props.total}, failed`
  if (status.value === 'pending' || status.value === 'generating') return `Image ${n} of ${props.total}, generating`
  return `Image ${n} of ${props.total}`
})

function toggle(event) {
  selection.toggle(props.itemId, mediaId.value, props.universe, event?.shiftKey)
}

// Selection and the overflow tile take the click before OutputImage opens anything.
function onClickCapture(event) {
  if (event.target.closest('button,summary,details')) return
  if (props.overflow) {
    event.stopPropagation()
    emit('expand')
  } else if (pickable.value && (event.metaKey || event.ctrlKey || event.shiftKey || (props.variant === 'grid' && selecting.value))) {
    event.stopPropagation()
    toggle(event)
  } else if (props.variant === 'strip') {
    event.stopPropagation()
    emit('activate')
  }
}

// Tap = open, long-press = select (DESIGN.md §1.11). The press arrives as the
// synthetic contextmenu from utils/longPress. A real right-click, or a press on
// a tile that is already selected, reaches the media menu.
function onContextMenuCapture(event) {
  if (!event.stimmaSynthetic || !pickable.value || selected.value) return
  event.preventDefault()
  event.stopPropagation()
  toggle()
}

// Dragging a picked tile carries the whole selection to the composer.
function onDragStart(event) {
  if (!selected.value || selection.ids.size < 2) return
  const items = [...new Set(props.universe)].filter(id => selection.ids.has(id)).map(media_id => ({ media_id }))
  event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({ items }))
}
</script>

<template>
  <div
    class="group relative min-w-0 rounded-media outline-2 -outline-offset-2 focus-visible:outline focus-visible:outline-accent/60"
    :class="variant === 'strip' ? 'flex-none' : ''"
    :style="pixelSize ? { width: pixelSize + 'px' } : null"
    :data-tile="index"
    role="button"
    :tabindex="tabbable ? 0 : -1"
    :aria-label="description"
    :aria-current="current ? 'true' : undefined"
    @click.capture="onClickCapture"
    @contextmenu.capture="onContextMenuCapture"
    @dragstart="onDragStart"
  >
    <!-- Strip -->
    <div
      v-if="variant === 'strip'"
      class="relative aspect-square w-full cursor-pointer overflow-hidden rounded-media bg-matte transition-opacity duration-150"
      :class="current ? '' : 'opacity-60 hover:opacity-100'"
    >
      <MediaImage v-if="mediaId && !row.output.deleted" :media-id="mediaId" :asset-id="row.output.asset_id || undefined" :thumbnail="true" :thumbnail-size="256" container-class="h-full w-full" :img-class="status === 'trashed' ? 'h-full w-full object-cover opacity-30' : 'h-full w-full object-cover'" />
      <AppImage v-else-if="row.output.workspace_url" :src="workspaceMediaUrl(row.output.workspace_url)" container-class="h-full w-full" img-class="h-full w-full object-cover" />
      <span v-else-if="status === 'pending' || status === 'generating'" class="absolute inset-0 flex items-center justify-center">
        <span class="h-1.5 w-1.5 rounded-full" :class="status === 'generating' ? 'animate-pulse-soft bg-blue-500' : 'bg-zinc-500'"></span>
      </span>
      <span v-else class="absolute inset-0 flex items-center justify-center text-red-400"><ExclamationCircleIcon class="h-5 w-5" /></span>
      <span v-if="status === 'trashed'" class="absolute inset-0 flex items-center justify-center text-amber-500"><TrashIcon class="h-5 w-5" /></span>
    </div>

    <!-- Grid -->
    <template v-else>
      <OutputImage
        :row="row"
        fill
        :fit-thumbnail="512"
        :inset-left="selecting || pickable ? 32 : 0"
        :inset-right="pickable ? 28 : 0"
        quiet-markers
        class="!rounded-media !bg-matte"
        @view-image="id => $emit('view-image', id)"
        @retry="id => $emit('retry', id)"
        @cancel="id => $emit('cancel', id)"
        @show-job-info="id => $emit('show-job-info', id)"
      />
      <span v-if="overflow" class="pointer-events-none absolute inset-0 flex items-center justify-center bg-matte/75 font-mono text-sm tabular-nums text-white">+{{ overflow }}</span>
      <p v-if="showLabel" class="truncate bg-matte px-1 pb-1 pt-0.5 text-[11px] text-content-tertiary">{{ row.input?.label || ' ' }}</p>
    </template>

    <span v-if="selected || current" class="pointer-events-none absolute inset-0 z-10 rounded-media ring-2 ring-inset ring-selection"></span>

    <!-- Selection checkbox: the browser grid's markup -->
    <button
      v-if="pickable && (variant === 'grid' || selected)"
      type="button"
      role="checkbox"
      tabindex="-1"
      :aria-checked="selected"
      :aria-label="`Select image ${index + 1}`"
      class="absolute left-1 top-1 z-chrome flex transition-opacity duration-150 coarse:left-0 coarse:top-0 coarse:h-11 coarse:w-11 coarse:p-1.5"
      :class="[
        selected || selecting ? 'opacity-100' : 'opacity-0 focus-visible:opacity-100 group-hover:opacity-100 [[data-pointer=coarse]_&]:hidden',
        variant === 'strip' ? 'pointer-events-none' : '',
      ]"
      @click.stop="toggle"
    >
      <span
        class="flex items-center justify-center rounded-md border-2 backdrop-blur-md transition-colors duration-150"
        :class="[
          variant === 'strip' ? 'h-4 w-4' : 'h-6 w-6',
          selected ? 'border-selection bg-selection' : 'border-edge-strong bg-black/60 hover:border-content-secondary',
        ]"
      >
        <svg v-if="selected" :class="variant === 'strip' ? 'h-3 w-3' : 'h-4 w-4'" class="text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </span>
    </button>

    <!-- One-click add, the single-image twin of select + Add -->
    <button
      v-if="pickable && variant === 'grid' && !attached && !selecting && collections.canAttach.value"
      type="button"
      tabindex="-1"
      title="Add to message"
      class="absolute right-1 top-1 z-chrome flex h-6 w-6 items-center justify-center rounded-md bg-black/55 text-white opacity-0 backdrop-blur transition-opacity duration-150 hover:bg-black/75 group-hover:opacity-100 [[data-pointer=coarse]_&]:hidden"
      @click.stop="collections.attach([mediaId])"
    >
      <PlusIcon class="h-3.5 w-3.5" />
    </button>

    <span
      v-if="attached && !overflow"
      class="pointer-events-none absolute right-1 top-1 z-chrome flex h-5 w-5 items-center justify-center rounded-md bg-black/55 text-white backdrop-blur"
      title="In your message"
    >
      <PaperClipIcon class="h-3 w-3" />
    </span>
  </div>
</template>
