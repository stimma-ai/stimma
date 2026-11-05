<script setup>
// An agent's output images in chat: one collection, two views (Grid, Preview),
// two homes (inline, or teleported into the artifact panel). State lives in
// useChatMediaCollections so it survives a transcript remount and the move.
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowsPointingOutIcon, CheckCircleIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon,
  EllipsisHorizontalIcon, MagnifyingGlassMinusIcon, MagnifyingGlassPlusIcon, PlusIcon, Square3Stack3DIcon, Squares2X2Icon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Sheet from '../ui/Sheet.vue'
import Tooltip from '../ui/Tooltip.vue'
import ArtifactPanelIcon from './ArtifactPanelIcon.vue'
import MediaCollectionTile from './MediaCollectionTile.vue'
import MediaSelectionBar from './MediaSelectionBar.vue'
import OutputImage from './OutputImage.vue'
import { MediaImage } from '../media'
import { CHAT_MEDIA_COLLECTIONS } from '../../composables/useChatMediaCollections'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { useMediaState } from '../../composables/useMediaState'
import { useViewport } from '../../composables/useViewport'
import { getMediaType } from '../../utils/mediaTypes'
import { consumeEscape } from '../../utils/escapeLayers'
import { COLLECTION_SIZES, gridColumns, heroHeight, startingView, stripTileSize, visibleTiles } from '../../utils/mediaCollectionLayout'

const props = defineProps({
  rows: { type: Array, required: true },
  itemId: { type: Number, required: true },
  title: { type: String, default: '' },
  showRole: { type: String, default: null },
  failedCount: { type: Number, default: 0 },
})
const emit = defineEmits(['view-image', 'retry', 'cancel', 'retry-all', 'show-job-info'])

const VIEWS = [{ label: 'Grid', value: 'grid' }, { label: 'Preview', value: 'preview' }]
const SIZES = [{ label: 'Small', value: 's' }, { label: 'Medium', value: 'm' }, { label: 'Large', value: 'l' }]

const collections = inject(CHAT_MEDIA_COLLECTIONS)
const { selection, panel } = collections
const { isCompact, isCoarsePointer } = useViewport()
const { getMediaItem } = useMediaApi()
const contextMenu = useMediaContextMenu()
const { mediaState } = useMediaState()

const state = collections.viewState(props.itemId, () => startingView(props.rows.length, isCompact.value))

const rootRef = ref(null)
const stripRef = ref(null)
const width = ref(0)
const chatHeight = ref(700)
const moreOpen = ref(false)
const jumping = ref(false)
const jumpValue = ref('')
const stripEdges = ref({ left: false, right: false })
const swipeX = ref(0)
const heroInfo = ref(null)

const count = computed(() => props.rows.length)
const hasHeader = computed(() => !!props.title || count.value > 1 || props.showRole === 'intermediate' || props.failedCount > 0)
const isSingle = computed(() => count.value === 1)
const view = computed(() => (isSingle.value ? 'preview' : state.view))
const inPanel = computed(() => panel.itemId.value === props.itemId && !!panel.target.value)
const activeIndex = computed(() => Math.min(state.active, Math.max(0, count.value - 1)))
const activeRow = computed(() => props.rows[activeIndex.value])
const activeMediaId = computed(() => activeRow.value?.output?.media_id ?? null)
const isTrashed = row => {
  const known = mediaState.value[row.output?.media_id]
  return known ? !!known.deleted_at : row.output?.status === 'trashed'
}
// What can be selected or attached: finished images that still exist.
const universe = computed(() => props.rows
  .filter(row => row.output?.status === 'complete' && row.output.media_id && !row.output.deleted && !isTrashed(row))
  .map(row => row.output.media_id))
const activePickable = computed(() => universe.value.includes(activeMediaId.value))
const activeSelected = computed(() => selection.owner.value === props.itemId && selection.ids.has(activeMediaId.value))
const selecting = computed(() => selection.selecting.value && selection.owner.value === props.itemId)
const hasLabels = computed(() => props.rows.some(row => row.input?.label))
const runningCount = computed(() => props.rows.filter(row => ['pending', 'generating'].includes(row.output?.status)).length)
const doneCount = computed(() => props.rows.filter(row => row.output?.status === 'complete').length)

const columns = computed(() => gridColumns({ count: count.value, width: width.value || 600, size: state.size, compact: isCompact.value }))
const visible = computed(() => visibleTiles({ count: count.value, columns: columns.value, expanded: state.expanded || inPanel.value }))
const canCollapse = computed(() => state.expanded && !inPanel.value)
const stripSize = computed(() => stripTileSize(state.size, isCompact.value))
const canResize = computed(() => !isSingle.value && (count.value > 4 || view.value === 'preview'))
// A set or grid is drawn on its own backdrop, so its hero shares one surface.
const activeIsComposite = computed(() => {
  const format = mediaState.value[activeMediaId.value]?.file_format || activeRow.value?.output?.file_format
  return !!format && ['set', 'grid'].includes(getMediaType({ file_format: format }))
})
// Only a grid still arrives on a baked backdrop; a set is drawn on the matte.
const activeIsGrid = computed(() => {
  const format = mediaState.value[activeMediaId.value]?.file_format || activeRow.value?.output?.file_format
  return !!format && getMediaType({ file_format: format }) === 'grid'
})
// On a phone the picture is as tall as it is wide, so the chips would sit on the
// artwork. A composite there gets a band above and below for them instead.
// A single result with a title carries its count and menu in that title row, so
// its picture needs no band of its own above it.
const HERO_GUTTER_TOP = 40
const HERO_GUTTER_BOTTOM = 48
const heroGutters = computed(() => activeIsComposite.value && isCompact.value && width.value > 0 && width.value < 560)
// Too narrow for the facts to share the bottom row with the markers and Add.
const factsTop = computed(() => width.value > 0 && width.value < 560)
const hostsHeroMenu = computed(() => isSingle.value && hasHeader.value && !!activeMediaId.value)
const topBand = computed(() => heroGutters.value && (!hostsHeroMenu.value || !!heroFacts.value))
const gutterTop = computed(() => (topBand.value ? HERO_GUTTER_TOP : 0))
const gutterBottom = computed(() => (heroGutters.value ? HERO_GUTTER_BOTTOM : 0))
// The whole presentation (header, bands, picture, strip) shares one budget of
// the visible conversation, so the band chips never push the picture past it.
const inlineHeroHeight = computed(() => {
  const extra = gutterTop.value + gutterBottom.value
  // Bands and picture together take at most 70% of the visible conversation.
  const room = Math.round(chatHeight.value * 0.7) - extra
  if (isSingle.value) return Math.min(width.value || 560, Math.max(200, room)) + extra
  return Math.min(heroHeight({ chatHeight: chatHeight.value - extra, width: width.value, size: state.size, stripSize: stripSize.value }), Math.max(200, room)) + extra
})
const rootWidthClass = computed(() => {
  if (inPanel.value) return 'h-full w-full bg-matte'
  const cap = isSingle.value ? 'max-w-[560px]' : count.value === 2 ? 'max-w-[720px]' : 'max-w-[880px]'
  return `w-full ${cap} rounded-lg bg-surface compact:max-w-none`
})
// Controls over artwork are black glass. A set or grid is drawn on a matte
// backdrop of its own, and glass over that reads as disabled in the light
// theme, so its controls take the theme's own resting treatment instead.
const ctl = computed(() => (activeIsComposite.value
  ? 'bg-overlay-light text-content hover:bg-overlay-medium'
  : 'bg-black/55 text-white backdrop-blur hover:bg-black/75'))
const memberCount = computed(() => (heroInfo.value?.id === activeMediaId.value ? heroInfo.value.members : 0))
const heroFacts = computed(() => {
  const label = activeRow.value?.input?.label
  if (label) return label
  const info = heroInfo.value
  return info?.id === activeMediaId.value && info.width && info.height ? `${info.width} × ${info.height}` : ''
})

// Keeps the picked point of the conversation still while the card changes height.
function keepAnchored(change) {
  const scroller = rootRef.value?.closest('[data-chat-scroller]')
  const top = rootRef.value?.getBoundingClientRect().top
  change()
  if (!scroller || inPanel.value) return
  nextTick(() => {
    const now = rootRef.value?.getBoundingClientRect().top
    if (top != null && now != null) scroller.scrollTop += now - top
  })
}
function setView(next) {
  keepAnchored(() => {
    state.view = next
    state.expanded = false
  })
}
function show(index) {
  state.active = Math.max(0, Math.min(count.value - 1, index))
}
function inspect(index) {
  show(index)
  if (state.view === 'grid') setView('preview')
}
function move(delta) {
  show(activeIndex.value + delta)
}
function changeSize(delta) {
  const next = COLLECTION_SIZES[COLLECTION_SIZES.indexOf(state.size) + delta]
  if (next) keepAnchored(() => { state.size = next })
}
function collapse() {
  state.expanded = false
  nextTick(() => rootRef.value?.scrollIntoView({ block: 'nearest' }))
}
function openFullView() {
  if (activeMediaId.value) emit('view-image', activeMediaId.value, activeIndex.value)
}
function togglePickActive(event) {
  selection.toggle(props.itemId, activeMediaId.value, universe.value, event?.shiftKey)
}

function jumpStart() {
  jumpValue.value = String(activeIndex.value + 1)
  jumping.value = true
  nextTick(() => rootRef.value?.querySelector('[data-collection-jump]')?.select())
}
function jumpCommit() {
  const n = parseInt(jumpValue.value, 10)
  if (!Number.isNaN(n)) show(n - 1)
  jumping.value = false
}

function openHeroMenu(event) {
  event.stopPropagation()
  if (!activeMediaId.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  contextMenu.showAt({
    x: rect.right,
    y: rect.bottom + 4,
    mediaId: activeMediaId.value,
    assetId: activeRow.value.output.asset_id || undefined,
  })
}

function centerActiveInStrip() {
  const strip = stripRef.value
  const tile = strip?.querySelector(`[data-tile="${activeIndex.value}"]`)
  if (!tile) return
  const left = Math.max(0, tile.offsetLeft - (strip.clientWidth - tile.clientWidth) / 2)
  strip.scrollTo({ left, behavior: 'smooth' })
}
function updateStripEdges() {
  const strip = stripRef.value
  if (!strip) return
  stripEdges.value = {
    left: strip.scrollLeft > 4,
    right: strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 4,
  }
}
function pageStrip(direction) {
  const strip = stripRef.value
  strip?.scrollBy({ left: direction * strip.clientWidth * 0.8, behavior: 'smooth' })
}

// Keyboard: arrows move the active image, Space picks, Enter opens.
function onKeydown(event) {
  if (event.target.matches?.('input,textarea,select,summary')) return
  const inGrid = view.value === 'grid'
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: inGrid ? -columns.value : 0, ArrowDown: inGrid ? columns.value : 0 }[event.key]
  if (step) {
    event.preventDefault()
    const last = (inGrid ? visible.value : count.value) - 1
    show(Math.min(last, Math.max(0, activeIndex.value + step)))
    nextTick(() => rootRef.value?.querySelector(`[data-tile="${activeIndex.value}"]`)?.focus())
  } else if (['Enter', ' '].includes(event.key) && event.target.closest?.('button,a,summary')) {
    // A control inside the card keeps its own keys.
  } else if (event.key === ' ' && activePickable.value) {
    event.preventDefault()
    togglePickActive(event)
  } else if (event.key === 'Enter' && event.target.closest?.('[data-tile]')) {
    event.preventDefault()
    inGrid ? inspect(activeIndex.value) : openFullView()
  } else if (event.key === 'Escape' && selecting.value) {
    consumeEscape(event)
    selection.clear()
  } else if (event.key === 'Escape' && inPanel.value) {
    consumeEscape(event)
    panel.close()
  }
}

// Touch pages through the picture with a swipe; the picture follows the finger.
let swipe = null
let swiped = false
function onHeroPointerDown(event) {
  if (event.pointerType !== 'touch' || isSingle.value) return
  swipe = { x: event.clientX, y: event.clientY, axis: null }
  swiped = false
}
function onHeroPointerMove(event) {
  if (!swipe) return
  const dx = event.clientX - swipe.x
  const dy = event.clientY - swipe.y
  if (!swipe.axis && Math.hypot(dx, dy) > 8) swipe.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
  if (swipe.axis !== 'x') return
  swiped = true
  const atEdge = (dx > 0 && activeIndex.value === 0) || (dx < 0 && activeIndex.value === count.value - 1)
  swipeX.value = atEdge ? dx * 0.25 : dx
}
function onHeroPointerUp() {
  if (swipe?.axis === 'x' && Math.abs(swipeX.value) > 48) move(swipeX.value < 0 ? 1 : -1)
  swipe = null
  swipeX.value = 0
}
function onHeroClickCapture(event) {
  if (!swiped) return
  swiped = false
  event.stopPropagation()
}
function onHeroContextCapture(event) {
  if (!event.stimmaSynthetic || !activePickable.value || activeSelected.value) return
  event.preventDefault()
  event.stopPropagation()
  togglePickActive()
}
function onHeroDragStart(event) {
  if (!activeSelected.value || selection.ids.size < 2) return
  const items = [...new Set(universe.value)].filter(id => selection.ids.has(id)).map(media_id => ({ media_id }))
  event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({ items }))
}

watch(activeIndex, () => {
  jumping.value = false
  nextTick(centerActiveInStrip)
})
watch(view, () => nextTick(() => { centerActiveInStrip(); updateStripEdges() }))
// The button that opened the panel is gone; keep Escape and the arrows working.
watch(inPanel, entered => { if (entered) nextTick(() => rootRef.value?.focus()) })
watch(() => [state.size, count.value, inPanel.value], () => nextTick(() => { centerActiveInStrip(); updateStripEdges() }), { flush: 'post' })

// Dimensions are a fact of the picture on screen, so they load with it.
watch([activeMediaId, view], async ([id, nextView]) => {
  if (!id || nextView !== 'preview') return
  try {
    const item = await getMediaItem(id, { includeTrashed: true })
    if (id === activeMediaId.value) heroInfo.value = { id, width: item.width, height: item.height, members: item.member_count || 0 }
  } catch { /* the chip just omits what it can't read */ }
}, { immediate: true })

// A panel the collection has left, or a transcript that dropped it, shouldn't stay claimed.
onBeforeUnmount(() => {
  if (panel.itemId.value === props.itemId) panel.close()
})

let resizeObserver
let scrollerObserver
onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => {
    width.value = entry.contentRect.width
    updateStripEdges()
  })
  resizeObserver.observe(rootRef.value)
  const scroller = rootRef.value.closest('[data-chat-scroller]')
  if (scroller) {
    scrollerObserver = new ResizeObserver(([entry]) => { chatHeight.value = entry.contentRect.height })
    scrollerObserver.observe(scroller)
  }
  nextTick(() => { centerActiveInStrip(); updateStripEdges() })
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  scrollerObserver?.disconnect()
})
</script>

<template>
  <!-- Left behind in the transcript while the collection is in the panel -->
  <button
    v-if="inPanel"
    type="button"
    class="flex max-w-[320px] items-center gap-2.5 rounded-lg border border-accent/50 bg-accent/10 px-2.5 py-2 text-left transition-colors hover:bg-accent/15"
    @click="panel.close"
  >
    <span class="flex flex-none gap-0.5">
      <span v-for="row in rows.slice(0, 3)" :key="row.id" class="h-11 w-11 overflow-hidden rounded-media bg-matte">
        <MediaImage v-if="row.output?.media_id" :media-id="row.output.media_id" :thumbnail="true" :thumbnail-size="128" :draggable="false" :enable-context-menu="false" container-class="h-full w-full" />
      </span>
    </span>
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-1.5">
        <span class="truncate text-[12px] font-semibold text-content">{{ title || 'Images' }}</span>
        <span class="flex-shrink-0 rounded-full border border-accent/40 px-1.5 py-px text-[9px] font-medium text-accent">in panel</span>
      </span>
      <span class="block font-mono text-[11px] tabular-nums text-content-muted">{{ count }} images</span>
    </span>
  </button>

  <Teleport :to="panel.target.value || 'body'" :disabled="!inPanel">
    <section
      ref="rootRef"
      tabindex="-1"
      class="media-display flex min-w-0 flex-col outline-none"
      :class="rootWidthClass"
      :aria-label="title || 'Images'"
      data-testid="media-collection"
      @keydown="onKeydown"
    >
      <header
        v-if="hasHeader"
        class="flex min-h-10 flex-none items-center gap-3 py-1 pl-3 pr-1.5 coarse:min-h-12"
        :class="[
          inPanel ? 'border-b border-edge-subtle bg-surface/60 pl-3.5' : 'rounded-t-lg',
          state.expanded && !inPanel ? 'sticky -top-4 z-chrome bg-surface compact:-top-3' : '',
        ]"
      >
        <div class="flex min-w-0 flex-1 items-center gap-2">
          <span v-if="title" class="min-w-0 break-words text-sm font-medium leading-snug text-content-secondary line-clamp-2">{{ title }}</span>
          <span v-if="!isSingle" class="flex-none font-mono text-xs tabular-nums text-content-muted">{{ count }}</span>
          <span v-if="runningCount" class="flex flex-none items-center gap-1.5 text-xs text-content-tertiary">
            <span class="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-blue-500"></span>
            <span class="font-mono tabular-nums">{{ doneCount }} done</span>
          </span>
          <button
            v-else-if="failedCount"
            type="button"
            class="flex-none rounded-md px-1.5 py-0.5 text-xs text-red-400 transition-colors hover:bg-red-500/10 coarse:min-h-11"
            @click="$emit('retry-all')"
          >Retry failed ({{ failedCount }})</button>
          <span
            v-if="showRole === 'intermediate'"
            class="flex-none text-[11px] text-content-muted"
            title="Kept with this chat, but not added to All Assets"
          >Working result</span>
        </div>

        <div class="flex flex-none items-center gap-1">
          <template v-if="hostsHeroMenu">
            <span v-if="activeIsComposite && memberCount" class="flex flex-none items-center gap-1 px-1 font-mono text-xs tabular-nums text-content-muted" :title="`${memberCount} items`">
              <Square3Stack3DIcon class="h-3.5 w-3.5" :stroke-width="1.75" />{{ memberCount }}
            </span>
            <IconButton aria-label="More actions" class="coarse:!h-11 coarse:!w-11" @click="openHeroMenu">
              <EllipsisHorizontalIcon class="h-4 w-4" />
            </IconButton>
          </template>
          <Tooltip v-if="canCollapse && !isCoarsePointer" text="Back to three rows">
            <button type="button" class="flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content" @click="collapse">
              <ChevronUpIcon class="h-3.5 w-3.5" />Show fewer
            </button>
          </Tooltip>
          <SegmentedControl
            v-if="!isSingle"
            :model-value="state.view"
            :options="VIEWS"
            aria-label="Collection view"
            class="coarse:[&_button]:min-h-11 coarse:[&_button]:px-3.5"
            @update:model-value="setView"
          />
          <template v-if="!isCoarsePointer && !isCompact">
            <div v-if="canResize" class="ml-1 flex items-center">
              <Tooltip text="Smaller images">
                <IconButton :disabled="state.size === 's'" aria-label="Smaller images" @click="changeSize(-1)">
                  <MagnifyingGlassMinusIcon class="h-4 w-4" />
                </IconButton>
              </Tooltip>
              <Tooltip text="Larger images">
                <IconButton :disabled="state.size === 'l'" aria-label="Larger images" @click="changeSize(1)">
                  <MagnifyingGlassPlusIcon class="h-4 w-4" />
                </IconButton>
              </Tooltip>
            </div>
            <Tooltip v-if="panel.available && !inPanel && count > 4" text="Open in panel">
              <IconButton aria-label="Open in panel" @click="panel.open(itemId)">
                <ArtifactPanelIcon />
              </IconButton>
            </Tooltip>
          </template>
          <IconButton v-else-if="!isSingle" aria-label="More options" class="!h-11 !w-11" @click="moreOpen = true">
            <EllipsisHorizontalIcon class="h-icon-nav w-icon-nav" />
          </IconButton>
          <Tooltip v-if="inPanel" text="Close panel">
            <IconButton aria-label="Close panel" class="coarse:!h-11 coarse:!w-11" @click="panel.close">
              <XMarkIcon class="h-4 w-4" />
            </IconButton>
          </Tooltip>
        </div>
      </header>

      <div class="flex min-h-0 flex-1 flex-col" :class="inPanel ? '' : ['overflow-hidden rounded-b-lg', hasHeader ? '' : 'rounded-t-lg']">
        <!-- Grid: one matte wall with 2px gutters -->
        <div v-if="view === 'grid'" class="min-h-0 flex-1 bg-matte" :class="inPanel ? 'custom-scrollbar overflow-y-auto' : ''">
          <div class="grid gap-0.5" :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }">
            <MediaCollectionTile
              v-for="(row, index) in rows.slice(0, visible)"
              :key="row.id ?? index"
              :row="row"
              :index="index"
              :item-id="itemId"
              :total="count"
              :universe="universe"
              :show-label="hasLabels"
              :tabbable="activeIndex === index"
              :overflow="index === visible - 1 && visible < count ? count - visible + 1 : 0"
              @view-image="inspect(index)"
              @expand="state.expanded = true"
              @retry="id => $emit('retry', id)"
              @cancel="id => $emit('cancel', id)"
              @show-job-info="id => $emit('show-job-info', id)"
            />
          </div>
          <div v-if="canCollapse && isCoarsePointer" class="flex justify-center py-2">
            <button type="button" class="flex min-h-11 items-center gap-1 rounded-md px-3 text-xs font-medium text-content-secondary" @click="collapse">
              <ChevronUpIcon class="h-3.5 w-3.5" />Show fewer
            </button>
          </div>
        </div>

        <!-- Preview: the picture, then the strip. All chrome is black glass on the matte (§3.3). -->
        <template v-else-if="activeRow">
          <div
            class="group/hero relative min-h-0 select-none overflow-hidden"
            :class="[inPanel ? 'flex-1' : 'flex-none', activeIsGrid ? 'bg-surface dark:bg-[#181818]' : 'bg-matte']"
            :style="inPanel ? null : { height: inlineHeroHeight + 'px' }"
            data-testid="media-collection-hero"
            @click.capture="onHeroClickCapture"
            @contextmenu.capture="onHeroContextCapture"
            @dragstart="onHeroDragStart"
            @pointerdown="onHeroPointerDown"
            @pointermove="onHeroPointerMove"
            @pointerup="onHeroPointerUp"
            @pointercancel="onHeroPointerUp"
          >
            <div
              class="absolute inset-0 touch-pan-y"
              :class="swipeX ? '' : 'transition-transform duration-150'"
              :style="swipeX ? { transform: `translateX(${swipeX}px)` } : null"
            >
              <OutputImage
                :key="activeRow.id ?? activeIndex"
                :row="activeRow"
                fill
                :use-thumbnail="false"
                :fit-thumbnail="isSingle ? null : 1024"
                :inset-left="topBand ? 48 : 36"
                :inset-right="72"
                :inset-bottom="heroGutters ? 2 : 8"
                :gutter-top="gutterTop"
                :gutter-bottom="gutterBottom"
                :hide-count-chip="hostsHeroMenu && activeIsComposite"
                :class="activeIsGrid ? '!rounded-media !bg-surface dark:!bg-[#181818]' : '!rounded-media !bg-matte'"
                style="aspect-ratio: auto; height: 100%"
                @view-image="openFullView"
                @retry="id => $emit('retry', id)"
                @cancel="id => $emit('cancel', id)"
                @show-job-info="id => $emit('show-job-info', id)"
              />
            </div>

            <span v-if="activeSelected && !isSingle" class="pointer-events-none absolute inset-0 ring-2 ring-inset ring-selection"></span>

            <template v-if="activePickable">
              <button
                type="button"
                role="checkbox"
                :aria-checked="activeSelected"
                aria-label="Select this image"
                class="absolute left-2 top-2 z-chrome flex transition-opacity duration-150 coarse:left-0 coarse:top-0 coarse:h-11 coarse:w-11 coarse:p-2"
                :class="activeSelected || selecting ? 'opacity-100' : 'opacity-0 focus-visible:opacity-100 group-hover/hero:opacity-100 [[data-pointer=coarse]_&]:hidden'"
                @click.stop="togglePickActive"
              >
                <span class="flex h-6 w-6 items-center justify-center rounded-md border-2 backdrop-blur-md transition-colors duration-150" :class="activeSelected ? 'border-selection bg-selection' : activeIsComposite ? 'border-edge-strong bg-overlay-subtle hover:border-content-secondary' : 'border-edge-strong bg-black/60 hover:border-content-secondary'">
                  <svg v-if="activeSelected" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor" data-stroke="own"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                </span>
              </button>
            </template>

            <div
              v-if="activeMediaId"
              class="absolute right-2 top-2 z-chrome flex items-center gap-1 transition-opacity duration-150 coarse:right-1 coarse:top-1"
              :class="isCoarsePointer ? 'opacity-100' : 'opacity-0 focus-within:opacity-100 group-hover/hero:opacity-100'"
            >
              <Tooltip v-if="!isCoarsePointer" text="Open slideshow">
                <button type="button" aria-label="Open slideshow" class="flex h-7 w-7 items-center justify-center rounded-md transition-colors" :class="ctl" @click.stop="openFullView">
                  <ArrowsPointingOutIcon class="h-4 w-4" />
                </button>
              </Tooltip>
              <button v-if="!hostsHeroMenu" type="button" aria-label="More actions" class="flex h-7 w-7 items-center justify-center rounded-md transition-colors coarse:h-11 coarse:w-11" :class="ctl" @click="openHeroMenu">
                <EllipsisHorizontalIcon class="h-4 w-4" />
              </button>
            </div>

            <!-- Edge paging. Touch swipes the picture instead. -->
            <template v-if="!isSingle && !isCoarsePointer">
              <button type="button" aria-label="Previous image" :disabled="activeIndex === 0" class="absolute left-2 top-1/2 z-chrome flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 focus-visible:opacity-100 disabled:!opacity-0 group-hover/hero:opacity-100" :class="ctl" @click.stop="move(-1)">
                <ChevronLeftIcon class="h-icon-nav w-icon-nav" />
              </button>
              <button type="button" aria-label="Next image" :disabled="activeIndex === count - 1" class="absolute right-2 top-1/2 z-chrome flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 focus-visible:opacity-100 disabled:!opacity-0 group-hover/hero:opacity-100" :class="ctl" @click.stop="move(1)">
                <ChevronRightIcon class="h-icon-nav w-icon-nav" />
              </button>
            </template>

            <!-- Facts. The position is editable, which matters at 200. -->
            <div v-if="!isSingle || heroFacts" class="absolute z-chrome flex h-7 items-center gap-1.5 rounded-md px-2 font-mono text-xs tabular-nums coarse:h-11"
              :class="[activeIsComposite ? 'bg-overlay-subtle text-content-secondary' : 'bg-black/55 text-white backdrop-blur', topBand ? 'left-12 top-0 max-w-[calc(100%-10rem)]' : factsTop ? 'left-10 top-2 max-w-[calc(100%-6.5rem)] coarse:left-12 coarse:top-0' : 'bottom-2 left-1/2 max-w-[40%] -translate-x-1/2']">
              <template v-if="!isSingle">
                <input
                  v-if="jumping"
                  v-model="jumpValue"
                  data-collection-jump
                  inputmode="numeric"
                  aria-label="Go to image number"
                  class="w-10 rounded-sm bg-transparent px-1 text-center outline-none ring-1 ring-white/50 focus:ring-white"
                  @keydown.enter.prevent.stop="jumpCommit"
                  @keydown.escape.stop="jumping = false"
                  @blur="jumpCommit"
                >
                <button v-else type="button" class="whitespace-nowrap rounded-sm hover:underline disabled:hover:no-underline coarse:min-h-11 coarse:min-w-11" :title="count > 8 ? 'Go to image number' : undefined" :disabled="count <= 8" @click.stop="jumpStart">{{ activeIndex + 1 }} / {{ count }}</button>
                <span v-if="heroFacts" class="opacity-50">·</span>
              </template>
              <span v-if="heroFacts" class="truncate">{{ heroFacts }}</span>
            </div>

            <button
              v-if="activePickable && collections.canAttach.value"
              type="button"
              class="absolute right-2 z-chrome flex h-7 items-center gap-1 rounded-md pl-1.5 pr-2 text-xs font-medium transition-colors coarse:h-11 coarse:pl-2.5 coarse:pr-3"
              :class="[heroGutters ? 'bottom-0.5' : 'bottom-2', activeIsComposite
                ? (collections.isAttached(activeMediaId) ? 'bg-overlay-light text-content hover:bg-overlay-medium' : 'text-content ring-1 ring-inset ring-edge-strong hover:bg-overlay-light')
                : (collections.isAttached(activeMediaId) ? 'bg-black/55 text-white backdrop-blur hover:bg-black/75' : 'bg-black/70 text-white backdrop-blur ring-1 ring-inset ring-white/35 hover:bg-black/85')]"
              @click.stop="collections.isAttached(activeMediaId) ? collections.detach(activeMediaId) : collections.attach([activeMediaId])"
            >
              <CheckIcon v-if="collections.isAttached(activeMediaId)" class="h-3.5 w-3.5 text-accent-hi" />
              <PlusIcon v-else class="h-3.5 w-3.5" />
              {{ collections.isAttached(activeMediaId) ? 'In message' : 'Add to message' }}
            </button>
          </div>

          <!-- Strip -->
          <div v-if="!isSingle" class="group/strip relative flex-none bg-matte">
            <div
              ref="stripRef"
              class="flex gap-0.5 overflow-x-auto overscroll-x-contain pt-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
              @scroll.passive="updateStripEdges"
            >
              <MediaCollectionTile
                v-for="(row, index) in rows"
                :key="row.id ?? index"
                :row="row"
                :index="index"
                :item-id="itemId"
                :total="count"
                :universe="universe"
                variant="strip"
                :pixel-size="stripSize"
                :current="activeIndex === index"
                :tabbable="activeIndex === index"
                @activate="show(index)"
              />
            </div>
            <template v-if="!isCoarsePointer">
              <button v-if="stripEdges.left" type="button" tabindex="-1" aria-label="Earlier images" class="absolute bottom-0 left-0 top-0.5 z-chrome flex w-7 items-center justify-center bg-black/55 text-white opacity-0 backdrop-blur transition-opacity duration-150 group-hover/strip:opacity-100" @click="pageStrip(-1)"><ChevronLeftIcon class="h-4 w-4" /></button>
              <button v-if="stripEdges.right" type="button" tabindex="-1" aria-label="Later images" class="absolute bottom-0 right-0 top-0.5 z-chrome flex w-7 items-center justify-center bg-black/55 text-white opacity-0 backdrop-blur transition-opacity duration-150 group-hover/strip:opacity-100" @click="pageStrip(1)"><ChevronRightIcon class="h-4 w-4" /></button>
            </template>
          </div>
        </template>
      </div>

      <!-- The panel covers the composer on a phone, so it carries its own bar. -->
      <MediaSelectionBar v-if="inPanel && isCompact && selecting" class="flex-none rounded-none border-x-0 border-t" />

      <Sheet v-if="isCoarsePointer || isCompact" :show="moreOpen" @close="moreOpen = false">
        <div class="sheet-section">Image size</div>
        <div class="px-4 pb-2">
          <SegmentedControl v-model="state.size" :options="SIZES" aria-label="Image size" class="coarse:[&_button]:min-h-11 coarse:[&_button]:px-4" />
        </div>
        <button type="button" class="sheet-row" @click="selection.start(itemId, universe); moreOpen = false"><CheckCircleIcon class="sheet-row-icon" /><span class="flex-1">Select images</span></button>
        <button type="button" class="sheet-row" @click="selection.selectAll(itemId, universe); moreOpen = false"><Squares2X2Icon class="sheet-row-icon" /><span class="flex-1">Select all</span><span class="sheet-row-detail">{{ universe.length }}</span></button>
        <button v-if="panel.available && !inPanel" type="button" class="sheet-row" @click="panel.open(itemId); moreOpen = false"><ArrowsPointingOutIcon class="sheet-row-icon" /><span class="flex-1">{{ isCompact ? 'Open full screen' : 'Open in panel' }}</span></button>
      </Sheet>
    </section>
  </Teleport>
</template>
