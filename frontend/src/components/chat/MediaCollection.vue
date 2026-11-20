<script setup>
// An agent's output media in chat: one collection, two views (Grid, Preview),
// two homes (inline, or teleported into the artifact panel). State lives in
// useChatMediaCollections so it survives a transcript remount and the move.
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowsPointingOutIcon, CheckCircleIcon, ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon,
  EllipsisHorizontalIcon, InformationCircleIcon, Squares2X2Icon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Sheet from '../ui/Sheet.vue'
import Tooltip from '../ui/Tooltip.vue'
import ArtifactPanelIcon from './ArtifactPanelIcon.vue'
import MediaCollectionTile from './MediaCollectionTile.vue'
import MediaSelectionBar from './MediaSelectionBar.vue'
import OutputImage from './OutputImage.vue'
import ChatAddIcon from './ChatAddIcon.vue'
import VideoAuditionControl from '../viewers/VideoAuditionControl.vue'
import { useMarkers } from '../../composables/useMarkers'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { MediaImage } from '../media'
import { CHAT_MEDIA_COLLECTIONS } from '../../composables/useChatMediaCollections'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { useMediaState } from '../../composables/useMediaState'
import { useViewport } from '../../composables/useViewport'
import { getMediaType } from '../../utils/mediaTypes'
import { consumeEscape, hasEscapeLayer } from '../../utils/escapeLayers'
import { gridColumns, heroHeight, placeGrid, startingView, stripTileSize, visibleTiles } from '../../utils/mediaCollectionLayout'

const props = defineProps({
  rows: { type: Array, required: true },
  itemId: { type: Number, required: true },
  title: { type: String, default: '' },
  showRole: { type: String, default: null },
  failedCount: { type: Number, default: 0 },
})
const emit = defineEmits(['view-image', 'retry', 'cancel', 'retry-all', 'show-job-info'])

const VIEWS = [{ label: 'Grid', value: 'grid' }, { label: 'Preview', value: 'preview' }]

const collections = inject(CHAT_MEDIA_COLLECTIONS)
const { selection, panel } = collections
const { isCompact, isCoarsePointer } = useViewport()
const contextMenu = useMediaContextMenu()
const { mediaState, loadStateForMedia } = useMediaState()

const state = collections.viewState(props.itemId, () => startingView(props.rows.length, isCompact.value))

const rootRef = ref(null)
const stripRef = ref(null)
const width = ref(0)
const chatHeight = ref(700)
const moreOpen = ref(false)
const stripEdges = ref({ left: false, right: false })
const swipeX = ref(0)

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

const columns = computed(() => gridColumns({ count: count.value, width: width.value || 600 }))
// Each picture's own aspect, from the media facts chat already loads.
// Until they arrive (or while a picture is still generating) a tile is square.
const ratioOf = row => {
  const known = mediaState.value[row.output?.media_id]
  return known?.width && known?.height ? known.width / known.height : 1
}
const LABEL_HEIGHT = 20
const placement = computed(() => placeGrid({
  ratios: props.rows.map(ratioOf),
  width: width.value || 600,
  columns: columns.value,
  caption: hasLabels.value ? LABEL_HEIGHT : 0,
}))
const visible = computed(() => visibleTiles({ placement: placement.value, count: count.value, expanded: state.expanded || inPanel.value }))
const gridHeight = computed(() => Math.max(0, ...placement.value.rects.slice(0, visible.value).map(r => r.y + r.h)))
const canCollapse = computed(() => state.expanded && !inPanel.value)
// A collapsed grid can hide the active image (Preview had moved past the
// first rows); the last tile shown keeps the grid reachable by Tab.
const gridFocusIndex = computed(() => Math.min(activeIndex.value, visible.value - 1))
const stripSize = computed(() => stripTileSize({ width: width.value || 600, count: count.value }))
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
// A set's stack sits in a square with an even margin around the pile (about 8.5%
// of the square). The margin above the pile is dead space, so a lone set's hero
// is trimmed by all but a hairline of it and the square is drawn that much
// higher (a negative top gutter), which keeps the artwork the same size.
const activeIsSet = computed(() => {
  const format = mediaState.value[activeMediaId.value]?.file_format || activeRow.value?.output?.file_format
  return !!format && getMediaType({ file_format: format }) === 'set'
})
const STACK_MARGIN = 0.085
const STACK_KEEP = 12
const HERO_GUTTER_TOP = 40
const HERO_GUTTER_BOTTOM = 48
const heroGutters = computed(() => activeIsComposite.value && isCompact.value && width.value > 0 && width.value < 560)
const topBand = heroGutters
const heroSquare = computed(() => Math.min(width.value || 560, Math.max(200, Math.round(chatHeight.value * 0.7) - gutterBottom.value)))
const stackTrim = computed(() => (isSingle.value && activeIsSet.value && !topBand.value
  ? Math.max(0, Math.round(heroSquare.value * STACK_MARGIN) - STACK_KEEP)
  : 0))
const gutterTop = computed(() => (topBand.value ? HERO_GUTTER_TOP : -stackTrim.value))
// The pile's own margin below the cover already sits above the band, so a lone set
// reserves only what the pile does not.
const gutterBottom = computed(() => {
  if (!heroGutters.value) return 0
  if (!(isSingle.value && activeIsSet.value)) return HERO_GUTTER_BOTTOM
  const square = Math.min(width.value, Math.max(200, Math.round(chatHeight.value * 0.7) - HERO_GUTTER_BOTTOM))
  return Math.max(12, HERO_GUTTER_BOTTOM - Math.round(square * STACK_MARGIN) + 8)
})
// The whole presentation (header, bands, picture, strip) shares one budget of
// the visible conversation, so the band chips never push the picture past it.
const inlineHeroHeight = computed(() => {
  const extra = Math.max(0, gutterTop.value) + gutterBottom.value
  // Bands and picture together take at most 70% of the visible conversation.
  const room = Math.round(chatHeight.value * 0.7) - extra
  if (isSingle.value) return Math.min(width.value || 560, Math.max(200, room)) + extra - stackTrim.value
  return Math.min(heroHeight({ chatHeight: chatHeight.value - extra, width: width.value, stripSize: stripSize.value }), Math.max(200, room)) + extra
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
// The agent's label for the picture, if it gave one.
const heroLabel = computed(() => activeRow.value?.input?.label || '')
const activeIsVideo = computed(() => {
  const format = mediaState.value[activeMediaId.value]?.file_format || activeRow.value?.output?.file_format
  return !!format && getMediaType({ file_format: format }) === 'video'
})
const heroRef = ref(null)
const activeHasAudio = computed(() => activeIsVideo.value && !!mediaState.value[activeMediaId.value]?.has_audio)
const canAdd = computed(() => activePickable.value && collections.canAttach.value)
const hasToolbar = computed(() => !!activeMediaId.value || !!heroLabel.value)
const { loadMarkersForMedia, availableMarkers, hasMarker, toggleMarker } = useMarkers()
// The strip shows markers, and the grid needs every picture's size.
watch(universe, ids => {
  if (!ids.length) return
  loadMarkersForMedia(ids)
  loadStateForMedia(ids)
}, { immediate: true })

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


// The hero's ⋯ and its right-click open one menu: the picks when the picture
// is one of them, else the picture, in the chat's project.
function openHeroMenu(event) {
  event.stopPropagation()
  if (!activeMediaId.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  contextMenu.showAt({ x: rect.right, y: rect.bottom + 4, ...collections.menuTarget(props.itemId, activeMediaId.value) })
}
const unregisterRows = collections.registerRows(props.itemId, () => props.rows)
onBeforeUnmount(unregisterRows)

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
// Keys someone else already handled and chorded keys (they belong to the
// browser and app) are left alone. Widgets that use the arrows themselves (the
// view toggle, menus, sliders) keep them; any control keeps its Enter and Space.
const ARROW_WIDGETS = '[role="radio"],[role="radiogroup"],[role="tab"],[role="tablist"],[role="slider"],[role="menu"],[role="menuitem"],[role="listbox"],[role="option"]'
function onKeydown(event) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return
  if (event.target.matches?.('input,textarea,select,summary,[contenteditable]:not([contenteditable="false"])')) return
  const onWidget = !!event.target.closest?.(ARROW_WIDGETS)
  const onControl = onWidget || !!event.target.closest?.('button,a,summary')
  const inGrid = view.value === 'grid'
  const step = onWidget ? 0 : { ArrowLeft: -1, ArrowRight: 1, ArrowUp: inGrid ? -columns.value : 0, ArrowDown: inGrid ? columns.value : 0 }[event.key]
  if (step) {
    event.preventDefault()
    const last = (inGrid ? visible.value : count.value) - 1
    show(Math.min(last, Math.max(0, activeIndex.value + step)))
    nextTick(() => rootRef.value?.querySelector(`[data-tile="${activeIndex.value}"]`)?.focus())
  } else if (['Enter', ' '].includes(event.key) && onControl) {
    // A control inside the card keeps its own keys.
  } else if (event.key === ' ' && activePickable.value) {
    event.preventDefault()
    togglePickActive(event)
  } else if (event.key === 'Enter' && event.target.closest?.('[data-tile]')) {
    event.preventDefault()
    inGrid ? inspect(activeIndex.value) : openFullView()
  } else if (event.key === 'Escape' && hasEscapeLayer()) {
    // A menu or dialog over the page closes first; the picks and panel stay.
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
  if (event.target.closest?.('button,video')) return
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
  if (event.stimmaSynthetic && activePickable.value && !activeSelected.value) {
    event.preventDefault()
    event.stopPropagation()
    togglePickActive()
    return
  }
  // The picture's own menu; the hero's controls and inputs keep theirs.
  if (!activeMediaId.value || activeRow.value?.output?.deleted) return
  if (event.target.closest?.('button,input,textarea,select,a,[data-testid="media-collection-toolbar"]')) return
  event.stopPropagation()
  contextMenu.show({ event, ...collections.menuTarget(props.itemId, activeMediaId.value) })
}
function onHeroDragStart(event) {
  if (!activeSelected.value || selection.ids.size < 2) return
  const items = [...new Set(universe.value)].filter(id => selection.ids.has(id)).map(media_id => ({ media_id }))
  event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({ items }))
}

watch(activeIndex, () => nextTick(centerActiveInStrip))
watch(view, () => nextTick(() => { centerActiveInStrip(); updateStripEdges() }))
// The button that opened the panel is gone; keep Escape and the arrows working.
watch(inPanel, entered => { if (entered) nextTick(() => rootRef.value?.focus()) })
watch(() => [stripSize.value, count.value, inPanel.value], () => nextTick(() => { centerActiveInStrip(); updateStripEdges() }), { flush: 'post' })


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
      :data-collection-item="itemId"
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
          <Tooltip v-if="canCollapse && !isCoarsePointer" text="Back to three rows">
            <button type="button" class="flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content" @click="collapse">
              <ChevronUpIcon class="h-3.5 w-3.5" />Show fewer
            </button>
          </Tooltip>
          <SegmentedControl
            v-if="!isSingle"
            :model-value="state.view"
            :options="VIEWS"
            aria-label="Image layout"
            class="coarse:[&_button]:min-h-11 coarse:[&_button]:px-3.5"
            @update:model-value="setView"
          />
          <template v-if="!isCoarsePointer && !isCompact">
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
          <div class="relative" :style="{ height: gridHeight + 'px' }">
            <MediaCollectionTile
              v-for="(row, index) in rows.slice(0, visible)"
              :key="row.id ?? index"
              :row="row"
              :index="index"
              :item-id="itemId"
              :total="count"
              :universe="universe"
              :rect="placement.rects[index]"
              :tabbable="gridFocusIndex === index"
              :show-label="hasLabels"
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
            class="group/hero relative flex min-h-0 select-none flex-col overflow-hidden"
            :class="[inPanel ? 'flex-1' : 'flex-none', activeIsGrid ? 'bg-matte' : 'bg-matte']"
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
            <div class="relative min-h-0 flex-1">
              <div
                class="absolute inset-0 touch-pan-y"
                :class="swipeX ? '' : 'transition-transform duration-150'"
                :style="swipeX ? { transform: `translateX(${swipeX}px)` } : null"
              >
                <OutputImage
                  :key="activeRow.id ?? activeIndex"
                  ref="heroRef"
                  :row="activeRow"
                  fill
                  bare
                  hide-type-chip
                  :use-thumbnail="false"
                  playable
                  :fit-thumbnail="isSingle ? null : 1024"
                  :inset-left="topBand ? 48 : 36"
                  :inset-right="72"
                  :inset-bottom="heroGutters ? 2 : 8"
                  :gutter-top="gutterTop"
                  :gutter-bottom="gutterBottom"
                  :class="activeIsGrid ? '!rounded-media !bg-surface dark:!bg-[#181818]' : '!rounded-media !bg-matte'"
                  style="aspect-ratio: auto; height: 100%"
                  @view-image="openFullView"
                  @retry="id => $emit('retry', id)"
                  @cancel="id => $emit('cancel', id)"
                  @show-job-info="id => $emit('show-job-info', id)"
                />
              </div>

              <span v-if="activeSelected && !isSingle" class="pointer-events-none absolute inset-0 ring-2 ring-inset ring-selection"></span>

              <!-- Pick: on hover, top left. Touch picks with a long press, so the box shows only once picking. -->
              <button
                v-if="activePickable"
                type="button"
                role="checkbox"
                :aria-checked="activeSelected"
                aria-label="Select this image"
                class="absolute left-2 top-2 z-chrome flex transition-opacity duration-150 coarse:left-0 coarse:top-0 coarse:h-11 coarse:w-11 coarse:p-2"
                :class="activeSelected || selecting ? 'opacity-100' : 'opacity-0 focus-visible:opacity-100 group-hover/hero:opacity-100 [[data-pointer=coarse]_&]:hidden'"
                @click.stop="togglePickActive"
              >
                <span class="flex h-6 w-6 items-center justify-center rounded-md border-2 backdrop-blur-md transition-colors duration-150" :class="activeSelected ? 'border-selection bg-selection' : 'border-edge-strong bg-black/60 hover:border-content-secondary'">
                  <svg v-if="activeSelected" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor" data-stroke="own"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                </span>
              </button>


              <!-- Edge paging. Touch swipes the picture instead. -->
              <template v-if="!isSingle && !isCoarsePointer">
                <button type="button" aria-label="Previous image" :disabled="activeIndex === 0" class="absolute left-2 top-1/2 z-chrome flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 focus-visible:opacity-100 disabled:!opacity-0 group-hover/hero:opacity-100" :class="ctl" @click.stop="move(-1)">
                  <ChevronLeftIcon class="h-icon-nav w-icon-nav" />
                </button>
                <button type="button" aria-label="Next image" :disabled="activeIndex === count - 1" class="absolute right-2 top-1/2 z-chrome flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 focus-visible:opacity-100 disabled:!opacity-0 group-hover/hero:opacity-100" :class="ctl" @click.stop="move(1)">
                  <ChevronRightIcon class="h-icon-nav w-icon-nav" />
                </button>
              </template>

            </div>
            <!-- One row for the picture's controls: markers on the left, actions on the right. A click on the picture opens the slideshow. -->
            <div v-if="hasToolbar" class="flex h-10 flex-none items-center gap-0.5 bg-surface px-1.5 coarse:h-12" data-testid="media-collection-toolbar">
              <template v-if="activeMediaId && !activeRow.output?.deleted && !isTrashed(activeRow)">
                <button
                  v-for="marker in availableMarkers"
                  :key="marker.id"
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-overlay-subtle coarse:h-11 coarse:w-11"
                  :class="hasMarker(activeMediaId, marker.id) ? '' : 'text-content-tertiary hover:text-content'"
                  :style="hasMarker(activeMediaId, marker.id) ? { color: marker.color } : null"
                  :title="hasMarker(activeMediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
                  @click.stop="toggleMarker(activeMediaId, marker)"
                >
                  <span class="icon-container flex h-4 w-4 items-center justify-center" :class="hasMarker(activeMediaId, marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
                </button>
              </template>
              <span v-if="heroLabel" class="ml-1.5 min-w-0 truncate text-xs text-content-tertiary">{{ heroLabel }}</span>
              <span class="flex-1"></span>
              <VideoAuditionControl
                v-if="activeHasAudio && heroRef"
                quiet
                :active="heroRef.auditionActive"
                :progress="heroRef.auditionProgress"
                @toggle="heroRef.audition()"
              />
              <Tooltip v-if="canAdd" :text="collections.isAttached(activeMediaId) ? 'In your message' : 'Add to message'">
                <IconButton
                  :aria-label="collections.isAttached(activeMediaId) ? 'Remove from message' : 'Add to message'"
                  :class="collections.isAttached(activeMediaId) ? '!text-accent-hi' : ''"
                  @click.stop="collections.isAttached(activeMediaId) ? collections.detach(activeMediaId) : collections.attach([activeMediaId])"
                >
                  <ChatAddIcon :checked="collections.isAttached(activeMediaId)" class="h-[18px] w-[18px]" />
                </IconButton>
              </Tooltip>
              <Tooltip v-if="activeRow.output?.job_id" text="Generation details">
                <IconButton aria-label="Generation details" @click.stop="$emit('show-job-info', activeRow.output.job_id)">
                  <InformationCircleIcon class="h-4 w-4" />
                </IconButton>
              </Tooltip>
              <IconButton v-if="activeMediaId" aria-label="More actions" @click="openHeroMenu">
                <EllipsisHorizontalIcon class="h-4 w-4" />
              </IconButton>
            </div>
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
        <button type="button" class="sheet-row" @click="selection.start(itemId, universe); moreOpen = false"><CheckCircleIcon class="sheet-row-icon" /><span class="flex-1">Select images</span></button>
        <button type="button" class="sheet-row" @click="selection.selectAll(itemId, universe); moreOpen = false"><Squares2X2Icon class="sheet-row-icon" /><span class="flex-1">Select all</span><span class="sheet-row-detail">{{ universe.length }}</span></button>
        <button v-if="panel.available && !inPanel" type="button" class="sheet-row" @click="panel.open(itemId); moreOpen = false"><ArrowsPointingOutIcon class="sheet-row-icon" /><span class="flex-1">{{ isCompact ? 'Open full screen' : 'Open in panel' }}</span></button>
      </Sheet>
    </section>
  </Teleport>
</template>
