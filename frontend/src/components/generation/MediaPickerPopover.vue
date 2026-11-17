<template>
  <Teleport to="body">
    <!-- Click-catcher -->
    <div class="fixed inset-0 z-menu" @click="$emit('close')" />

    <div
      ref="panel" data-escape-layer
      data-media-picker-popover
      class="fixed z-menu w-[min(640px,calc(100vw-16px))] bg-surface border border-edge-subtle rounded-lg shadow-lg flex flex-col overflow-hidden"
      :style="panelStyle"
    >
      <!-- Header: where to look (flat tabs) · narrow it (markers, prompt filter) · order -->
      <div class="flex items-center gap-4 px-3 border-b border-edge-subtle">
        <button
          v-for="tab in PICKER_FEEDS"
          :key="tab.key"
          type="button"
          @click="state.feed = tab.key"
          class="text-[11.5px] py-2.5 -mb-px border-b-[1.5px] transition-colors cursor-pointer whitespace-nowrap"
          :class="state.feed === tab.key
            ? 'text-accent-hi border-accent'
            : 'text-content-muted border-transparent hover:text-content-secondary'"
        >
          {{ tab.label }}
        </button>

        <div class="ml-auto flex items-center gap-1 min-w-0">
          <!-- Marker toggles: off = gray outline icon, no fill. On = filled in the
               marker's color, with a tinted fill and ring. Several on = any of them. -->
          <button
            v-for="m in markerToggles"
            :key="m.id"
            type="button"
            @click="toggleMarker(m.id)"
            class="h-7 w-7 flex-none rounded-md flex items-center justify-center transition-colors cursor-pointer"
            :class="m.on ? '' : 'text-content-muted hover:text-content-secondary hover:bg-overlay-subtle'"
            :style="m.on ? {
              color: m.color,
              background: `color-mix(in srgb, ${m.color} 16%, transparent)`,
              boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${m.color} 60%, transparent)`,
            } : undefined"
            :title="m.name"
            :aria-label="m.name"
            :aria-pressed="m.on"
          >
            <span
              class="w-3.5 h-3.5 [&_svg]:w-full [&_svg]:h-full"
              :class="m.on ? '' : '[&_*]:!fill-none [&_*]:stroke-current [&_*]:[stroke-width:1.75] [&_*]:[stroke-linejoin:round]'"
              v-html="m.iconSvg"
            />
          </button>
          <div v-if="markerToggles.length" class="w-px h-4 bg-edge-subtle mx-1 flex-none" />
          <IconButton
            aria-label="Filter prompts"
            title="Filter prompts (/)"
            :class="state.query ? '!text-accent-hi' : ''"
            @click="toggleSearch"
          >
            <MagnifyingGlassIcon class="w-4 h-4" />
          </IconButton>
          <div class="pl-1 min-w-0 [&_button]:text-[11.5px]">
            <SettingsDropdown
              v-if="state.feed === 'used'"
              secondary
              disabled
              model-value="used"
              :options="[{ value: 'used', label: 'Last used' }]"
            />
            <SettingsDropdown
              v-else
              secondary
              :model-value="state.sort"
              :options="PICKER_SORTS"
              @update:model-value="setSort"
            />
          </div>
        </div>
      </div>

      <!-- Prompt filter: the browser's spyglass. Stays open while it holds text. -->
      <div v-if="state.searchOpen || state.query" class="px-3 py-2 border-b border-edge-subtle">
        <SearchField
          ref="searchRef"
          v-model="queryInput"
          placeholder="Filter prompts"
        />
      </div>

      <!-- Body: the whole library, paged in as you scroll -->
      <div ref="body" class="h-[396px] overflow-y-auto p-2.5 custom-scrollbar" @scroll="onScroll">
        <div v-if="loading && tiles.length === 0" class="h-full flex items-center justify-center">
          <Spinner size="md" />
        </div>
        <div v-else-if="tiles.length === 0" class="h-full flex flex-col items-center justify-center gap-2">
          <template v-if="narrowed">
            <span class="text-xs text-content-muted">Nothing matches</span>
            <button type="button" class="text-[11.5px] text-accent-hi hover:text-accent cursor-pointer" @click="clearNarrowing">Show everything</button>
          </template>
          <span v-else class="text-xs text-content-muted">{{ emptyHint }}</span>
        </div>
        <template v-else>
          <div class="grid grid-cols-6 gap-1.5">
            <button
              v-for="tile in tiles"
              :key="tile.mediaId"
              type="button"
              @click="onPick(tile)"
              class="relative aspect-square rounded-lg overflow-hidden border border-edge-subtle transition-all"
              :class="slotOf(tile.mediaId) != null ? 'cursor-default' : 'hover:border-edge-strong cursor-pointer'"
              :aria-disabled="slotOf(tile.mediaId) != null || undefined"
              :title="tileTitle(tile)"
            >
              <MediaImage
                :media-id="tile.mediaId"
                :file-hash="tile.fileHash"
                :thumbnail="true"
                :thumbnail-size="256"
                :is-audio="tile.kind === 'audio'"
                :draggable="false"
                :enable-context-menu="false"
                container-class="w-full h-full"
                class="w-full h-full object-cover"
                :class="slotOf(tile.mediaId) != null ? 'opacity-35' : ''"
              />
              <div
                v-if="slotOf(tile.mediaId) != null"
                class="absolute top-1 left-1 px-1.5 h-5 flex items-center bg-black/70 rounded text-[10px] font-semibold text-white pointer-events-none"
              >
                {{ slotOf(tile.mediaId) === targetIndex ? 'Replacing' : `In ${slotOf(tile.mediaId)! + 1}` }}
              </div>
              <div
                v-if="tile.kind === 'video'"
                class="absolute bottom-1 left-1 w-4 h-4 bg-black/60 rounded flex items-center justify-center pointer-events-none"
              >
                <svg viewBox="0 0 24 24" fill="currentColor" class="w-2 h-2 text-white">
                  <polygon points="6 3 20 12 6 21 6 3" />
                </svg>
              </div>
              <MarkerBadges
                v-if="tile.markers.length > 0"
                :markers="tile.markers"
                small
                class="absolute bottom-1 right-1 pointer-events-none"
              />
            </button>
          </div>
          <div v-if="hasMore" class="py-3 flex justify-center"><Spinner size="sm" /></div>
        </template>
      </div>

      <!-- Footer: OS escape hatch · count · what a pick does -->
      <div class="flex items-center gap-3 px-2.5 py-2 border-t border-edge-subtle bg-overlay-faint">
        <button
          type="button"
          @click="$emit('browse')"
          class="flex items-center gap-1.5 text-[11.5px] text-content-secondary bg-overlay-light rounded-md px-2.5 py-1 hover:text-content transition-colors cursor-pointer"
        >
          <FolderIcon class="w-3 h-3" />
          Browse Files…
        </button>
        <span v-if="countText" class="text-[11px] text-content-muted tabular-nums">{{ countText }}</span>
        <span v-if="intentLabel" class="ml-auto flex items-center gap-1.5 text-[11px] text-content-muted">
          <ArrowsRightLeftIcon v-if="targetIndex != null" class="w-3.5 h-3.5" />
          <PlusIcon v-else class="w-3.5 h-3.5" />
          {{ intentLabel }}
        </span>
        <span v-else-if="showDropHint" class="ml-auto text-[11px] text-content-muted">or drop a file</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { MagnifyingGlassIcon, FolderIcon, PlusIcon, ArrowsRightLeftIcon } from '@heroicons/vue/24/outline'
import MediaImage from '../media/MediaImage.vue'
import MarkerBadges from '../MarkerBadges.vue'
import SearchField from '../ui/SearchField.vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import { useAssetApi } from '../../composables/useAssetApi'
import { recentMediaInputs, type RecentInputKind } from '../../composables/useRecentMediaInputs'
import { recordMediaPick, recentMediaPicks } from '../../composables/useRecentMediaPicks'
import { getMediaType } from '../../utils/mediaTypes'
import { makeStorageKey } from '../../utils/storageKeys'
import { syncedStorage } from '../../utils/workspaceStore'
import { mediaIdOf } from '../../utils/assetIdentity'
import { useMarkers } from '../../composables/useMarkers'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import {
  PICKER_FEEDS,
  PICKER_SORTS,
  defaultPickerState,
  mergeUsedBefore,
  parsePickerState,
  pickerViewKey,
  type PickerSort,
} from './mediaPickerState'

/**
 * Anchored popover for filling a media slot from the library instead of the
 * OS file dialog. Feeds (used before, all, generated, imported) combine with
 * marker toggles and the browser's prompt filter, page through the whole
 * library, and stick between opens. Picking emits the mediaId; the parent runs
 * it through the same path as a library drag-drop.
 */

interface Props {
  accept: 'image' | 'video' | 'audio'
  anchorEl: HTMLElement | null
  /** Media in the parent's slots, by slot index: shown dimmed ("In 2"), not pickable. */
  slotIds?: Array<number | null | undefined>
  /** The slot a pick replaces (null = a pick adds). Shown as "Replacing". */
  targetIndex?: number | null
  /** What a pick does, for the footer ("Adds image 3", "Replaces image 1"). */
  intentLabel?: string
  /** Image pickers normally accept a video frame too; strict image consumers can opt out. */
  allowVideoFrames?: boolean
  /** Parent actually exposes a drop target alongside this popover. */
  showDropHint?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  slotIds: () => [],
  targetIndex: null,
  intentLabel: undefined,
  allowVideoFrames: true,
  showDropHint: true,
})

const emit = defineEmits<{
  (e: 'pick', mediaId: number): void
  (e: 'browse'): void
  (e: 'close'): void
}>()

interface TileMarker {
  id: number
  name: string
  icon_svg: string
  color: string
}

interface Tile {
  mediaId: number
  fileHash: string
  fileFormat: string
  kind: RecentInputKind
  markers: TileMarker[]
  prompt?: string
}

const PAGE_SIZE = 60

const { fetchAssets } = useAssetApi()
const { availableMarkers, isInitialized: markersLoaded, init: initMarkers } = useMarkers()
initMarkers()

// "Used before" picks are scoped to the surrounding project (same convention
// as ToolView's projectScopeId); tool id and instance deliberately don't count.
const route = useRoute()
const projectId = computed<number | null>(() => {
  const raw = route.query.project_id
  if (raw == null) return null
  const parsed = parseInt(String(Array.isArray(raw) ? raw[0] : raw), 10)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
})

// Image slots accept videos too (a frame is grabbed on pick); an audio slot can
// take a video's sound. The feeds show everything the slot can take.
const acceptedKinds = computed<RecentInputKind[]>(() =>
  props.accept === 'image'
    ? (props.allowVideoFrames ? ['image', 'video'] : ['image'])
    : props.accept === 'audio' ? ['audio', 'video'] : [props.accept]
)
const mediaTypesParam = computed(() =>
  props.accept === 'image'
    ? (props.allowVideoFrames ? 'images,videos' : 'images')
    : props.accept === 'video' ? 'videos' : 'audio'
)

// --- Sticky view state: one per profile, shared by every picker ---
const STATE_KEY = makeStorageKey('media_picker', 'view')

function usedBeforeEntries() {
  const picks = recentMediaPicks(acceptedKinds.value, projectId.value, 60)
    .map(e => ({ mediaId: e.mediaId, fileHash: e.fileHash, fileFormat: e.fileFormat, kind: e.kind, usedAt: e.pickedAt }))
  const inputs = recentMediaInputs(acceptedKinds.value, 60)
    .map(e => ({ mediaId: e.mediaId, fileHash: e.fileHash, fileFormat: e.fileFormat, kind: e.kind, usedAt: e.lastUsed }))
  return mergeUsedBefore(picks, inputs)
}

function initialState() {
  let stored = null
  try { stored = parsePickerState(syncedStorage.getItem(STATE_KEY)) } catch { /* first run */ }
  // First run: start on what was used before when there is any.
  return stored ?? defaultPickerState(usedBeforeEntries().length > 0 ? 'used' : 'all')
}

const state = reactive(initialState())

let saveTimer: ReturnType<typeof setTimeout> | null = null
function saveState() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    try { syncedStorage.setItem(STATE_KEY, JSON.stringify(state)) } catch { /* best effort */ }
  }, 250)
}
function flushState() {
  if (!saveTimer) return
  clearTimeout(saveTimer)
  saveTimer = null
  try { syncedStorage.setItem(STATE_KEY, JSON.stringify(state)) } catch { /* best effort */ }
}
watch(state, saveState, { deep: true })

// --- Markers: toggles combined with the feed (any of the ones that are on) ---
const markerToggles = computed(() =>
  (availableMarkers.value as any[]).map(m => ({
    id: m.id as number,
    name: m.name as string,
    color: m.color as string,
    iconSvg: sanitizeSvg(m.icon_svg),
    on: state.markerIds.includes(m.id),
  }))
)

// A remembered marker that has since been deleted stops filtering.
watch([markersLoaded, availableMarkers], () => {
  if (!markersLoaded.value) return
  const known = new Set((availableMarkers.value as any[]).map(m => m.id))
  const kept = state.markerIds.filter(id => known.has(id))
  if (kept.length !== state.markerIds.length) state.markerIds = kept
}, { immediate: true })

function toggleMarker(id: number) {
  state.markerIds = state.markerIds.includes(id)
    ? state.markerIds.filter(m => m !== id)
    : [...state.markerIds, id]
}

// --- Prompt filter ---
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)
const queryInput = ref(state.query)
let queryTimer: ReturnType<typeof setTimeout> | null = null
watch(queryInput, value => {
  if (queryTimer) clearTimeout(queryTimer)
  queryTimer = setTimeout(() => { state.query = value }, 120)
})
watch(() => state.query, value => { if (value !== queryInput.value) queryInput.value = value })

async function openSearch() {
  state.searchOpen = true
  await nextTick()
  searchRef.value?.focus()
}

function closeSearch() {
  if (queryTimer) clearTimeout(queryTimer)
  queryInput.value = ''
  state.query = ''
  state.searchOpen = false
}

function toggleSearch() {
  if (state.query || state.searchOpen) closeSearch()
  else openSearch()
}

function clearNarrowing() {
  state.markerIds = []
  closeSearch()
}

function setSort(value: string) {
  state.sort = value as PickerSort
  // A fresh shuffle each time Random is chosen; paging and reopening keep it.
  if (value === 'random') state.seed = Date.now() % 2147483647
}

const narrowed = computed(() => state.markerIds.length > 0 || state.query.trim() !== '')

// --- Data ---
const tiles = ref<Tile[]>([])
const total = ref<number | null>(null)
const loading = ref(false)
const nextPage = ref(1)
const exhausted = ref(false)
let generation = 0

const hasMore = computed(() => state.feed !== 'used' && !exhausted.value && tiles.value.length > 0)


function slotOf(mediaId: number): number | null {
  const index = props.slotIds.indexOf(mediaId)
  return index < 0 ? null : index
}

function toTile(item: any): Tile {
  return {
    mediaId: mediaIdOf(item)!,
    fileHash: item.file_hash,
    fileFormat: item.file_format,
    kind: getMediaType(item) as RecentInputKind,
    markers: item.markers ?? [],
    prompt: item.extracted_prompt ?? undefined,
  }
}

function filterParams(): Record<string, unknown> {
  const params: Record<string, unknown> = { media_types: mediaTypesParam.value }
  if (state.markerIds.length) params.marker_ids = state.markerIds.join(',')
  const query = state.query.trim()
  if (query) params.prompt_query = query
  return params
}

function feedParams(): Record<string, unknown> {
  const params: Record<string, unknown> = { ...filterParams(), sort_by: state.sort }
  if (state.sort === 'random') params.random_seed = state.seed
  if (state.feed === 'generated') params.is_generated = true
  if (state.feed === 'imported') params.is_generated = false
  return params
}

async function loadUsedBefore(gen: number) {
  const entries = usedBeforeEntries()
  if (entries.length === 0) {
    tiles.value = []
    total.value = 0
    return
  }
  // The local history only knows ids; the server adds markers and applies the
  // marker and prompt filters, and the history keeps its last-used order.
  let byMedia = new Map<number, any>()
  let fetched = false
  try {
    const response = await fetchAssets({ ...filterParams(), media_ids: entries.map(e => e.mediaId).join(','), page_size: 200 })
    byMedia = new Map((response.items ?? []).map((item: any) => [mediaIdOf(item), item]))
    fetched = true
  } catch (e) {
    console.error('Media picker: failed to look up used-before media', e)
  }
  if (gen !== generation) return
  const list: Tile[] = []
  for (const entry of entries) {
    const item = byMedia.get(entry.mediaId)
    if (item) list.push(toTile(item))
    // Unfiltered, an entry the lookup missed (e.g. an older revision of an
    // edited image) still shows from what the history remembers.
    else if (!narrowed.value || !fetched) {
      list.push({ mediaId: entry.mediaId, fileHash: entry.fileHash, fileFormat: entry.fileFormat, kind: entry.kind, markers: [] })
    }
  }
  tiles.value = list
  total.value = list.length
}

async function loadPage(gen: number) {
  const page = nextPage.value
  const response = await fetchAssets({ ...feedParams(), page, page_size: PAGE_SIZE })
  if (gen !== generation) return
  const items: any[] = response.items ?? []
  const seen = new Set(tiles.value.map(t => t.mediaId))
  tiles.value = [...tiles.value, ...items.map(toTile).filter(t => !seen.has(t.mediaId))]
  total.value = typeof response.total === 'number' ? response.total : null
  nextPage.value = page + 1
  exhausted.value = items.length < PAGE_SIZE || (total.value != null && page * PAGE_SIZE >= total.value)
}

async function loadMore() {
  if (loading.value || exhausted.value || state.feed === 'used') return
  const gen = generation
  loading.value = true
  try {
    await loadPage(gen)
  } catch (e) {
    console.error('Media picker: failed to load more', e)
    if (gen === generation) exhausted.value = true
  } finally {
    if (gen === generation) loading.value = false
  }
  if (gen === generation) await nextTick(fillViewport)
}

/** Start the current view over; optionally page until `restoreTop` is reachable. */
async function reload(restoreTop = 0) {
  const gen = ++generation
  tiles.value = []
  total.value = null
  nextPage.value = 1
  exhausted.value = state.feed === 'used'
  loading.value = true
  try {
    if (state.feed === 'used') {
      await loadUsedBefore(gen)
    } else {
      await loadPage(gen)
      // Page in what the remembered scroll offset needs before restoring it.
      while (gen === generation && restoreTop > 0 && !exhausted.value) {
        await nextTick()
        const el = body.value
        if (!el || el.scrollHeight >= restoreTop + el.clientHeight) break
        await loadPage(gen)
      }
    }
  } catch (e) {
    console.error(`Media picker: failed to load the ${state.feed} feed`, e)
    if (gen === generation) { tiles.value = []; exhausted.value = true }
  } finally {
    if (gen === generation) loading.value = false
  }
  if (gen !== generation) return
  await nextTick()
  if (body.value) body.value.scrollTop = restoreTop
  state.scrollTop = restoreTop
  state.scrollKey = pickerViewKey(state, props.accept)
  fillViewport()
}

// Keep paging while the list doesn't yet fill the body (nothing to scroll).
function fillViewport() {
  const el = body.value
  if (!el || !hasMore.value || loading.value) return
  if (el.scrollHeight <= el.clientHeight + 200) loadMore()
}

const body = ref<HTMLElement | null>(null)
function onScroll() {
  const el = body.value
  if (!el) return
  state.scrollTop = Math.round(el.scrollTop)
  if (el.scrollTop + el.clientHeight > el.scrollHeight - 300) loadMore()
}

watch(
  () => [state.feed, state.markerIds.join(','), state.query.trim(), state.sort, state.seed],
  () => reload(0),
)

const kindNoun = computed(() => {
  if (props.accept === 'audio') return ['audio file', 'audio files']
  if (props.accept === 'video') return ['video', 'videos']
  return ['image', 'images']
})

const countText = computed(() => {
  if (total.value == null || (loading.value && tiles.value.length === 0)) return ''
  const n = total.value
  const noun = n === 1 ? kindNoun.value[0] : kindNoun.value[1]
  return `${n.toLocaleString()} ${noun}${narrowed.value ? ' match' : ''}`
})

const emptyHint = computed(() => {
  switch (state.feed) {
    case 'used': return 'Nothing used yet'
    case 'generated': return 'Nothing generated yet'
    case 'imported': return 'Nothing imported yet'
    default: return 'Nothing here yet'
  }
})

function tileTitle(tile: Tile): string {
  const slot = slotOf(tile.mediaId)
  if (slot != null) return slot === props.targetIndex ? 'Being replaced' : `Already ${kindNoun.value[0]} ${slot + 1}`
  return tile.prompt?.slice(0, 200) || tile.fileFormat.toUpperCase()
}

function onPick(tile: Tile) {
  if (slotOf(tile.mediaId) != null) return
  recordMediaPick(
    { mediaId: tile.mediaId, fileHash: tile.fileHash, fileFormat: tile.fileFormat, kind: tile.kind },
    projectId.value,
  )
  flushState()
  emit('pick', tile.mediaId)
}

// --- Positioning: below the anchor, clamped to the viewport; above if roomier ---
const panel = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({ visibility: 'hidden' })

function position() {
  if (!props.anchorEl || !panel.value) return
  const rect = props.anchorEl.getBoundingClientRect()
  const menuWidth = panel.value.offsetWidth
  const menuHeight = panel.value.offsetHeight
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - menuWidth - 8))
  const spaceBelow = window.innerHeight - rect.bottom - 12
  const spaceAbove = rect.top - 12
  let top: number
  if (menuHeight <= spaceBelow || spaceBelow >= spaceAbove) top = rect.bottom + 6
  else top = rect.top - 6 - menuHeight
  // A tall anchor (a filled slot) can leave no room on either side: overlap it.
  top = Math.max(8, Math.min(top, window.innerHeight - menuHeight - 8))
  panelStyle.value = { top: `${top}px`, left: `${left}px` }
}

watch(() => state.searchOpen || !!state.query, () => nextTick(position))

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

function onKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented) return
  if (e.key === 'Escape' && isTopmostEscapeLayer(panel.value)) {
    consumeEscape(e)
    // Escape in the filter field clears and closes the field, not the picker.
    // (Handled here rather than via SearchField's escape event: by the time
    // this listener runs, that handler may already have removed the field.)
    if (isTyping(e.target) && panel.value?.contains(e.target as Node)) {
      closeSearch()
      return
    }
    emit('close')
    return
  }
  if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target) && isTopmostEscapeLayer(panel.value)) {
    e.preventDefault()
    openSearch()
  }
}

onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', position)
  await nextTick()
  position()
  // Reopen where the last picker left off, scroll position included.
  const restoreTop = state.scrollKey === pickerViewKey(state, props.accept) ? state.scrollTop : 0
  await reload(restoreTop)
})

onUnmounted(() => {
  generation++
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', position)
  if (queryTimer) {
    clearTimeout(queryTimer)
    state.query = queryInput.value
  }
  flushState()
})
</script>
