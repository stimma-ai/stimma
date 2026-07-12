<template>
  <Teleport to="body">
    <!-- Click-catcher -->
    <div class="fixed inset-0 z-[10000]" @click="$emit('close')" />

    <div
      ref="panel"
      class="fixed z-[10001] w-[420px] bg-surface border border-edge rounded-lg shadow-xl flex flex-col overflow-hidden"
      :style="panelStyle"
    >
      <!-- Flat text tabs: color + underline carry the state -->
      <div class="flex gap-4 px-3 border-b border-edge-subtle">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          @click="activeTab = tab.key"
          class="text-[11.5px] py-2 -mb-px border-b-[1.5px] transition-colors cursor-pointer"
          :class="activeTab === tab.key
            ? 'text-blue-400 border-blue-500'
            : 'text-content-muted border-transparent hover:text-content-secondary'"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Fixed-height body: three tile rows regardless of tab content -->
      <div class="h-[258px] overflow-y-auto p-2.5">
        <div v-if="loading[activeTab]" class="h-full flex items-center justify-center">
          <div class="w-4 h-4 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
        </div>
        <div v-else-if="visibleTiles.length === 0" class="h-full flex items-center justify-center">
          <span class="text-xs text-content-muted">{{ activeTabDef.emptyHint }}</span>
        </div>
        <div v-else class="grid grid-cols-5 gap-1.5">
          <button
            v-for="tile in visibleTiles"
            :key="tile.mediaId"
            @click="onPick(tile)"
            class="relative aspect-square rounded-lg overflow-hidden border border-edge-subtle hover:border-edge-strong transition-all cursor-pointer"
            :title="tile.fileFormat.toUpperCase()"
          >
            <MediaImage
              :media-id="tile.mediaId"
              :file-hash="tile.fileHash"
              :thumbnail="true"
              :thumbnail-size="128"
              :is-audio="tile.kind === 'audio'"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full"
              class="w-full h-full object-cover"
            />
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
      </div>

      <!-- Footer: OS picker escape hatch -->
      <div class="flex items-center gap-2 px-2.5 py-2 border-t border-edge-subtle bg-overlay-faint">
        <button
          @click="$emit('browse')"
          class="flex items-center gap-1.5 text-[11.5px] text-content-secondary bg-white/[0.05] border border-white/10 rounded-md px-2.5 py-1 hover:text-content hover:border-edge-strong transition-colors cursor-pointer"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-3 h-3">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          Browse Files…
        </button>
        <span class="ml-auto text-[11px] text-content-muted">or drop a file</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import MediaImage from '../media/MediaImage.vue'
import MarkerBadges from '../MarkerBadges.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { recentMediaInputs, type RecentInputKind } from '../../composables/useRecentMediaInputs'
import { recordMediaPick, recentMediaPicks } from '../../composables/useRecentMediaPicks'
import { getMediaType } from '../../utils/mediaTypes'
import { makeProfileKey } from '../../utils/storageKeys'

/**
 * Anchored popover for filling a MediaPicker slot from library media instead
 * of the OS file dialog. Tabs are feeds the app already has (picks made here,
 * frecency-recent inputs, generated, added, marked); picking emits the mediaId
 * and the parent runs it through the same addFromMediaId path as a library
 * drag-drop.
 */

interface Props {
  accept: 'image' | 'video' | 'audio'
  anchorEl: HTMLElement | null
  /** mediaIds already in the picker's slots — hidden from the feeds. */
  excludeIds?: number[]
}

const props = withDefaults(defineProps<Props>(), {
  excludeIds: () => []
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
  ts: number
  markers: TileMarker[]
}

type TabKey = 'recents' | 'recent' | 'generated' | 'added' | 'marked'

const TABS: Array<{ key: TabKey; label: string; emptyHint: string }> = [
  { key: 'recents', label: 'Recents', emptyHint: 'Nothing picked yet' },
  { key: 'recent', label: 'All', emptyHint: 'Nothing here yet' },
  { key: 'generated', label: 'Generated', emptyHint: 'Nothing generated yet' },
  { key: 'added', label: 'Imported', emptyHint: 'Nothing imported yet' },
  { key: 'marked', label: 'Marked', emptyHint: 'Nothing marked yet' },
]

const PAGE_SIZE = 30

const { fetchMedia, getMarkers } = useMediaApi()

// Recents is scoped to the surrounding project (same convention as ToolView's
// projectScopeId) — tool id and instance deliberately don't factor in.
const route = useRoute()
const projectId = computed<number | null>(() => {
  const raw = route.query.project_id
  if (raw == null) return null
  const parsed = parseInt(String(Array.isArray(raw) ? raw[0] : raw), 10)
  return Number.isFinite(parsed) ? parsed : null
})

// Image slots accept videos too (a frame is grabbed on pick) — mirror the
// drop-zone rule so the feeds show everything the slot can take.
const acceptedKinds = computed<RecentInputKind[]>(() =>
  props.accept === 'image' ? ['image', 'video'] : [props.accept]
)

// One key for all pickers: the popover remembers the last tab globally.
const TAB_STORAGE_KEY = makeProfileKey('media_picker_popover', 'tab')

function initialTab(): TabKey {
  const stored = localStorage.getItem(TAB_STORAGE_KEY)
  const storedTab = TABS.some(t => t.key === stored) ? (stored as TabKey) : null
  const hasRecents = recentMediaPicks(acceptedKinds.value, projectId.value, 1).length > 0
  // The remembered tab wins, except landing on an empty Recents tab — fall
  // through to the default: Recents when it has something, otherwise All.
  if (storedTab && (storedTab !== 'recents' || hasRecents)) return storedTab
  return hasRecents ? 'recents' : 'recent'
}

const activeTab = ref<TabKey>(initialTab())
const activeTabDef = computed(() => TABS.find(t => t.key === activeTab.value)!)
const tiles = ref<Record<TabKey, Tile[] | null>>({ recents: null, recent: null, generated: null, added: null, marked: null })
const loading = ref<Record<TabKey, boolean>>({ recents: false, recent: false, generated: false, added: false, marked: false })
const mediaTypesParam = computed(() =>
  props.accept === 'image' ? 'images,videos' : props.accept === 'video' ? 'videos' : 'audio'
)

const visibleTiles = computed(() => {
  const excluded = new Set(props.excludeIds)
  return (tiles.value[activeTab.value] ?? []).filter(t => !excluded.has(t.mediaId))
})

// tsField picks which date ranks the item in the Recent blend: creation time
// for generated media, ingest time for imports (created_date on an imported
// photo is the shoot date, which would bury it).
function toTile(item: any, tsField: 'created_date' | 'indexed_date'): Tile {
  const kind = getMediaType(item) as RecentInputKind
  const ts = Date.parse(item[tsField] || item.indexed_date || '') || 0
  return { mediaId: item.id, fileHash: item.file_hash, fileFormat: item.file_format, kind, ts, markers: item.markers ?? [] }
}

async function fetchFeed(params: Record<string, unknown>, tsField: 'created_date' | 'indexed_date' = 'created_date'): Promise<Tile[]> {
  const response = await fetchMedia({
    page_size: PAGE_SIZE,
    media_types: mediaTypesParam.value,
    ...params,
  })
  return (response.items ?? []).map((item: any) => toTile(item, tsField))
}

async function loadTab(tab: TabKey) {
  if (tiles.value[tab] !== null || loading.value[tab]) return
  loading.value[tab] = true
  try {
    switch (tab) {
      case 'recents': {
        // Picks made through this popover, straight from the local store — no
        // fetch. Marker badges ride along only when a cached feed already
        // holds the same item.
        const markersById = new Map(
          [...(tiles.value.generated ?? []), ...(tiles.value.added ?? [])].map(t => [t.mediaId, t.markers])
        )
        tiles.value.recents = recentMediaPicks(acceptedKinds.value, projectId.value, PAGE_SIZE).map(e => ({
          mediaId: e.mediaId,
          fileHash: e.fileHash,
          fileFormat: e.fileFormat,
          kind: e.kind,
          ts: e.pickedAt,
          markers: markersById.get(e.mediaId) ?? [],
        }))
        break
      }
      case 'generated':
        tiles.value.generated = await fetchFeed({ is_generated: true, sort_by: 'created_desc' })
        break
      case 'added':
        // "Recently added" = recently ingested imports. (added_desc is
        // project-scoped — it sorts by ProjectMedia.added_at.)
        tiles.value.added = await fetchFeed({ is_generated: false, sort_by: 'indexed_desc' }, 'indexed_date')
        break
      case 'marked': {
        const markers = await getMarkers()
        const ids = (markers ?? []).map((m: any) => m.id).join(',')
        tiles.value.marked = ids ? await fetchFeed({ marker_ids: ids, sort_by: 'created_desc' }) : []
        break
      }
      case 'recent': {
        // Blend: inputs used before (frecency-ranked, from local store — no
        // fetch needed) merged with fresh generated/added, deduped, newest first.
        const [generated, added] = await Promise.all([
          fetchFeed({ is_generated: true, sort_by: 'created_desc' }),
          fetchFeed({ is_generated: false, sort_by: 'indexed_desc' }, 'indexed_date'),
        ])
        // The local store carries no marker info — borrow it from the fetched
        // feeds where the same item appears.
        const markersById = new Map([...generated, ...added].map(t => [t.mediaId, t.markers]))
        const used: Tile[] = recentMediaInputs(acceptedKinds.value, PAGE_SIZE).map(e => ({
          mediaId: e.mediaId,
          fileHash: e.fileHash,
          fileFormat: e.fileFormat,
          kind: e.kind,
          ts: e.lastUsed,
          markers: markersById.get(e.mediaId) ?? [],
        }))
        // Cache the side fetches — switching to those tabs is then instant.
        tiles.value.generated ??= generated
        tiles.value.added ??= added
        const seen = new Set<number>()
        tiles.value.recent = [...used, ...generated, ...added]
          .sort((a, b) => b.ts - a.ts)
          .filter(t => !seen.has(t.mediaId) && (seen.add(t.mediaId), true))
          .slice(0, PAGE_SIZE)
        break
      }
    }
  } catch (e) {
    console.error(`Media picker: failed to load ${tab} feed`, e)
    tiles.value[tab] = []
  } finally {
    loading.value[tab] = false
  }
}

watch(activeTab, tab => {
  loadTab(tab)
  localStorage.setItem(TAB_STORAGE_KEY, tab)
}, { immediate: true })

function onPick(tile: Tile) {
  recordMediaPick(
    { mediaId: tile.mediaId, fileHash: tile.fileHash, fileFormat: tile.fileFormat, kind: tile.kind },
    projectId.value,
  )
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
  if (menuHeight <= spaceBelow || spaceBelow >= rect.top - 12) {
    panelStyle.value = { top: `${rect.bottom + 6}px`, left: `${left}px` }
  } else {
    panelStyle.value = { bottom: `${window.innerHeight - rect.top + 6}px`, left: `${left}px` }
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  nextTick(position)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', position)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', position)
})
</script>
