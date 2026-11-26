<template>
  <!-- Header: where to look (flat tabs) · narrow it (markers, search) · order -->
  <div class="flex items-center gap-4 px-3 border-b border-edge-subtle">
    <button
      v-for="tab in FEEDS"
      :key="tab.key"
      type="button"
      @click="feed = tab.key"
      class="text-[11.5px] py-2.5 -mb-px border-b-[1.5px] transition-colors cursor-pointer whitespace-nowrap"
      :class="feed === tab.key
        ? 'text-accent-hi border-accent'
        : 'text-content-muted border-transparent hover:text-content-secondary'"
    >
      {{ tab.label }}
    </button>

    <div class="ml-auto flex items-center gap-1 min-w-0">
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
        aria-label="Search elements"
        title="Search elements (/)"
        :class="query ? '!text-accent-hi' : ''"
        @click="searchOpen = !searchOpen"
      >
        <MagnifyingGlassIcon class="w-4 h-4" />
      </IconButton>
      <div class="pl-1 min-w-0 [&_button]:text-[11.5px]">
        <SettingsDropdown
          v-if="feed === 'used'"
          secondary
          disabled
          model-value="used"
          :options="USED_SORT"
        />
        <SettingsDropdown
          v-else
          secondary
          :model-value="sort"
          :options="SORTS"
          @update:model-value="(v: any) => sort = v"
        />
      </div>
    </div>
  </div>

  <div v-if="searchOpen || query" class="px-3 py-2 border-b border-edge-subtle">
    <SearchField v-model="query" placeholder="Search elements" />
  </div>

  <!-- Body -->
  <div class="h-[396px] compact:h-[min(396px,52dvh)] overflow-y-auto p-2.5 custom-scrollbar">
    <div v-if="loading && !all.length" class="h-full flex items-center justify-center"><Spinner size="sm" /></div>
    <div v-else-if="tiles.length === 0" class="h-full flex flex-col items-center justify-center gap-2">
      <span class="text-xs text-content-muted">{{ narrowed ? 'Nothing matches' : emptyText }}</span>
      <button v-if="narrowed" type="button" class="text-[11.5px] text-accent-hi hover:text-accent cursor-pointer" @click="clear">Show everything</button>
    </div>
    <div v-else class="grid grid-cols-4 compact:grid-cols-3 gap-x-1.5 gap-y-2.5">
      <button
        v-for="el in tiles"
        :key="el.asset_id"
        type="button"
        @click="!isAttached(el) && pick(el)"
        class="group text-left min-w-0"
        :class="isAttached(el) ? 'cursor-default' : 'cursor-pointer'"
        :aria-disabled="isAttached(el) || undefined"
        data-element-tile
      >
        <div
          class="relative aspect-square rounded-lg overflow-hidden border border-edge-subtle bg-matte transition-all"
          :class="isAttached(el) ? '' : 'group-hover:border-edge-strong'"
        >
          <MediaImage
            :media-id="el.cover_media_id || el.media_id"
            :thumbnail="true"
            :thumbnail-size="256"
            :draggable="false"
            :enable-context-menu="false"
            container-class="w-full h-full"
            class="w-full h-full object-cover"
            :class="isAttached(el) ? 'opacity-35' : ''"
          />
          <div
            v-if="isAttached(el)"
            class="absolute top-1 left-1 px-1.5 h-5 flex items-center bg-black/70 rounded text-[10px] font-semibold text-white pointer-events-none"
          >Added</div>
          <MarkerBadges
            v-if="markersOf(el).length"
            :markers="markersOf(el)"
            small
            class="absolute bottom-1 right-1 pointer-events-none"
          />
        </div>
        <div class="mt-1 px-0.5 flex items-center gap-1 min-w-0" :class="isAttached(el) ? 'opacity-50' : ''">
          <PuzzlePieceIcon class="w-3 h-3 flex-none text-content-muted" />
          <span class="truncate text-[12px] text-content">{{ el.name }}</span>
        </div>
        <div class="px-0.5 text-[11px] text-content-muted truncate" :class="isAttached(el) ? 'opacity-50' : ''">{{ kindLabel(el.kind) }}</div>
      </button>
    </div>
  </div>

  <!-- Footer: make one · what a pick does -->
  <div class="flex items-center gap-3 px-2.5 py-2 border-t border-edge-subtle bg-overlay-faint">
    <button
      type="button"
      class="flex items-center gap-1.5 text-[11.5px] text-content-secondary bg-overlay-light rounded-md px-2.5 py-1 hover:text-content transition-colors cursor-pointer"
      @click="$emit('new')"
    >
      <PlusIcon class="w-3 h-3" />
      New element…
    </button>
    <span class="ml-auto flex items-center gap-1.5 text-[11px] text-content-muted">
      <PlusIcon class="w-3.5 h-3.5" />
      Adds to this tool
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { MagnifyingGlassIcon, PlusIcon, PuzzlePieceIcon } from '@heroicons/vue/24/outline'
import MediaImage from '../media/MediaImage.vue'
import MarkerBadges from '../MarkerBadges.vue'
import SearchField from '../ui/SearchField.vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import { useMarkers } from '../../composables/useMarkers'
import { useAssetApi } from '../../composables/useAssetApi'
import { recentElementIds } from '../../composables/useToolElements'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { kindLabel } from '../elements/useElements'

interface ElementRow {
  asset_id: number
  revision_id: number
  media_id: number
  cover_media_id: number | null
  name: string
  kind: string
  description: string
  created_at: string
  updated_at: string
  markers: number[]
}

const props = defineProps<{ attachedIds: number[]; projectId: number | null }>()
const emit = defineEmits<{ pick: [ElementRow]; new: []; changed: [] }>()

const FEEDS = [{ key: 'used', label: 'Used before' }, { key: 'all', label: 'All' }] as const
const SORTS = [
  { value: 'updated_desc', label: 'Recently changed', triggerLabel: 'Changed' },
  { value: 'created_desc', label: 'Newest first', triggerLabel: 'Newest' },
  { value: 'name', label: 'Name' },
]
const USED_SORT = [{ value: 'used', label: 'Last used' }]

const usedIds = recentElementIds()
const feed = ref<'used' | 'all'>(usedIds.length ? 'used' : 'all')
const sort = ref('updated_desc')
const query = ref('')
const searchOpen = ref(false)
const markerIds = ref<number[]>([])
const all = ref<ElementRow[]>([])
const loading = ref(true)

const { availableMarkers, init: initMarkers } = useMarkers()
initMarkers()
const markerToggles = computed(() => availableMarkers.value.map((m: any) => ({
  id: m.id, name: m.name, color: m.color, iconSvg: sanitizeSvg(m.icon_svg), on: markerIds.value.includes(m.id),
})))
function toggleMarker(id: number) {
  markerIds.value = markerIds.value.includes(id) ? markerIds.value.filter(x => x !== id) : [...markerIds.value, id]
}
const markersOf = (el: ElementRow) => el.markers.map(id => availableMarkers.value.find((m: any) => m.id === id)).filter(Boolean)

const { fetchAssets } = useAssetApi()
async function load() {
  loading.value = true
  try {
    const params = props.projectId != null ? { project_id: props.projectId } : {}
    const [{ data }, assets] = await Promise.all([
      axios.get('/api/elements', { params }),
      fetchAssets({ media_types: 'elements', page_size: 200 }).catch(() => ({ items: [] as any[] })),
    ])
    const markersByAsset = new Map<number, number[]>()
    for (const item of (assets as any).items ?? []) {
      const id = item.asset_id ?? item.id
      if (id != null) markersByAsset.set(id, (item.markers ?? []).map((m: any) => (typeof m === 'number' ? m : m.id)))
    }
    all.value = (data.elements ?? []).map((e: any) => ({ ...e, markers: markersByAsset.get(e.asset_id) ?? [] }))
  } catch (e) {
    console.error('Element picker: failed to load elements', e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

const narrowed = computed(() => !!query.value.trim() || markerIds.value.length > 0)
const emptyText = computed(() => (feed.value === 'used' ? 'Nothing used yet' : 'No elements yet'))

const tiles = computed(() => {
  let list: ElementRow[]
  if (feed.value === 'used') {
    const byId = new Map(all.value.map(e => [e.asset_id, e]))
    list = usedIds.map(id => byId.get(id)).filter((e): e is ElementRow => !!e)
  } else {
    list = [...all.value]
    if (sort.value === 'name') list.sort((a, b) => a.name.localeCompare(b.name))
    else if (sort.value === 'created_desc') list.sort((a, b) => b.created_at.localeCompare(a.created_at))
    else list.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  }
  if (markerIds.value.length) list = list.filter(e => e.markers.some(id => markerIds.value.includes(id)))
  const q = query.value.trim().toLowerCase()
  if (q) list = list.filter(e => `${e.name} ${e.kind} ${e.description}`.toLowerCase().includes(q))
  return list
})
watch(() => [searchOpen.value || !!query.value, tiles.value.length], () => emit('changed'))

const isAttached = (el: ElementRow) => props.attachedIds.includes(el.asset_id)
function pick(el: ElementRow) { emit('pick', el) }
function clear() { query.value = ''; searchOpen.value = false; markerIds.value = [] }
</script>
