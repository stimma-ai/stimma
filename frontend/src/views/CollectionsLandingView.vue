<template>
  <div class="flex h-full flex-col bg-base">
    <PageHeader class="compact:hidden">
      <template #title>Collections</template>
      <template #actions>
        <div class="relative" ref="sortDropdownRef">
          <Select :label="activeSortLabel" :open="sortDropdownOpen" @click="sortDropdownOpen = !sortDropdownOpen" />

          <div
            v-if="sortDropdownOpen"
            class="absolute right-0 top-full z-menu mt-1 min-w-[190px] rounded-lg border border-edge-subtle bg-surface py-1 shadow-xl"
          >
            <button
              v-for="option in sortOptions"
              :key="option.value"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-overlay-subtle"
              :class="sortBy === option.value ? 'text-accent-hi' : 'text-content-secondary'"
              @click="selectSort(option.value)"
            >
              <svg
                v-if="sortBy === option.value"
                class="h-icon-nav w-icon-nav flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-icon-nav flex-shrink-0"></span>
              <span>{{ option.label }}</span>
            </button>
          </div>
        </div>
        <SearchField v-model="searchQuery" placeholder="Search collections..." class="w-48" />
        <Button variant="primary" @click="createNewCollection">
          <template #icon><PlusIcon class="h-icon-inline w-icon-inline" /></template>
          New
        </Button>
      </template>
    </PageHeader>

    <div class="flex-1 overflow-y-auto px-page pb-section">
      <div v-if="loading" class="py-20 text-center text-content-muted">Loading collections...</div>
      <div v-else-if="collections.length === 0" class="flex h-64 compact:h-full flex-col items-center justify-center text-center">
        <p class="mb-2 text-content-muted">No collections yet</p>
        <p class="text-sm text-content-muted">Create a collection to curate a working set of assets.</p>
      </div>
      <div v-else-if="filteredCollections.length === 0" class="flex h-64 flex-col items-center justify-center text-center">
        <svg class="mb-4 h-16 w-16 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <p class="mb-2 text-content-muted">No collections match your search</p>
      </div>

      <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-section pt-section compact:grid-cols-2 compact:gap-3 compact:pt-3">
        <button
          v-for="collection in filteredCollections"
          :key="collection.id"
          class="group text-left"
          @click="openCollection(collection.id)"
          @contextmenu="handleCollectionContextMenu($event, collection)"
        >
          <!-- Contact-sheet cover: 1, 2 or 4 tiles chosen by how many assets the
               collection holds, so a small collection never leaves empty matte. Fixed
               4:3 frame at radius-media on matte, 2px gutters, no card, no
               border - hover draws a hairline ring. -->
          <div class="relative aspect-[4/3] overflow-hidden rounded-media bg-matte transition-shadow group-hover:ring-1 group-hover:ring-edge">
            <div
              v-if="getCollectionCover(collection).length > 0"
              class="grid h-full w-full gap-0.5 p-0.5"
              :class="getCollectionCover(collection).length === 1 ? 'grid-cols-1' : getCollectionCover(collection).length === 2 ? 'grid-cols-2' : 'grid-cols-2 grid-rows-2'"
            >
              <div
                v-for="(item, index) in getCollectionCover(collection)"
                :key="`${collection.id}-${item.id}-${index}`"
                class="min-h-0 min-w-0 overflow-hidden rounded-media bg-matte"
              >
                <MediaImage
                  :media-id="item.id"
                  :file-hash="item.file_hash"
                  :file-path="item.file_path"
                  :file-format="item.file_format"
                  :is-video="isVideo(item.file_format)"
                  thumbnail
                  :thumbnail-size="512"
                  :draggable="false"
                  :enable-context-menu="false"
                  background-class="bg-matte"
                  container-class="h-full w-full"
                  img-class="h-full w-full object-cover"
                />
              </div>
            </div>
            <div v-else class="flex h-full items-center justify-center">
              <svg class="h-6 w-6 text-content-muted" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
              </svg>
            </div>
          </div>

          <!-- Print-label caption: the name owns its own line, so metadata can
               never cut it short; mono facts sit under it. -->
          <div class="px-0.5 pt-2">
            <h2
              class="truncate text-[13px] font-medium"
              :class="collection.name ? 'text-content' : 'font-normal text-content-muted'"
            >
              {{ collection.name || 'Name this collection...' }}
            </h2>
            <p class="mt-0.5 truncate font-mono text-[11px] tabular-nums text-content-tertiary">{{ collection.asset_count || 0 }} {{ (collection.asset_count || 0) === 1 ? 'asset' : 'assets' }}<span v-if="collection.updated_at"> · {{ formatRelativeTime(collection.updated_at) }}</span></p>
          </div>
        </button>
      </div>
    </div>

    <RenameSheet :show="renameTarget !== null" :name="renameTarget?.name || ''" label="Rename collection" @close="renameTarget = null" @save="renameFromSheet" />
    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />
  </div>
</template>

<script setup>
import { formatRelativeTime } from '../utils/timeFormat'
import { useEntityMove } from '../composables/useEntityMove'
import { computed, onMounted, onUnmounted, ref, watch, onActivated } from 'vue'
import { setCompactPrimaryAction } from '../composables/useCompactChrome'
import { useRoute, useRouter } from 'vue-router'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import RenameSheet from '../components/compact/RenameSheet.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import Select from '../components/ui/Select.vue'
import SearchField from '../components/ui/SearchField.vue'
import Button from '../components/ui/Button.vue'
import { PlusIcon } from '@heroicons/vue/24/outline'
import { useViewport } from '../composables/useViewport'
import { MediaImage } from '../components/media'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useMediaApi } from '../composables/useMediaApi'
import { useToasts } from '../composables/useToasts'
import { useWebSocket } from '../composables/useWebSocket'

const props = defineProps({
  projectId: {
    type: Number,
    default: null
  }
})

const router = useRouter()
const entityContextMenu = useEntityContextMenu()
const { isCompact } = useViewport()
const { createCollection, deleteCollection, restoreCollection, getCollection, getCollections, updateCollection } = useMediaApi()
const { addToast } = useToasts()
const { on } = useWebSocket()

const collections = ref([])
const collectionDetails = ref(new Map())
const loading = ref(false)
const searchQuery = ref('')

// Global search "View all" handoff: seed the local filter from ?q= so the
// omnibox's per-type result caps never hide matches for good.
const route = useRoute()
watch(() => route.query.q, (q) => {
  if (typeof q === 'string' && q) searchQuery.value = q
}, { immediate: true })
const sortBy = ref('updated')
const sortDropdownOpen = ref(false)
const sortDropdownRef = ref(null)
const unsubscribers = []
const sortOptions = [
  { value: 'updated', label: 'Recently updated' },
  { value: 'name', label: 'Name' }
]

const activeSortLabel = computed(() => {
  return sortOptions.find((option) => option.value === sortBy.value)?.label || 'Sort'
})

const filteredCollections = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const filtered = !query
    ? [...collections.value]
    : collections.value.filter((collection) => {
        const name = (collection.name || '').toLowerCase()
        const meta = formatCollectionMeta(collection).toLowerCase()
        return name.includes(query) || meta.includes(query)
      })

  filtered.sort((a, b) => {
    if (sortBy.value === 'name') {
      const aName = (a.name || '').trim() || 'Name this collection...'
      const bName = (b.name || '').trim() || 'Name this collection...'
      return aName.localeCompare(bName, undefined, { sensitivity: 'base' })
    }

    const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
    const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
    return bTime - aTime
  })

  return filtered
})

async function loadCollections() {
  loading.value = true
  try {
    collections.value = await getCollections(props.projectId)
    await loadCollectionPreviews()
  } finally {
    loading.value = false
  }
}

async function loadCollectionPreviews() {
  const results = await Promise.allSettled(
    collections.value.map((collection) => getCollection(collection.id))
  )

  const next = new Map()
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      next.set(collections.value[index].id, result.value)
    }
  })
  collectionDetails.value = next
}

function upsertCollectionSummary(collection) {
  const summary = {
    id: collection.id,
    name: collection.name || '',
    asset_count: collection.asset_count || 0,
    updated_at: collection.updated_at
  }
  const index = collections.value.findIndex((entry) => entry.id === collection.id)
  if (index === -1) {
    collections.value = [summary, ...collections.value]
  } else {
    collections.value[index] = {
      ...collections.value[index],
      ...summary
    }
    collections.value = [...collections.value]
  }
}

function applyCollectionPayload(collection) {
  if (!collection) return
  upsertCollectionSummary(collection)
  collectionDetails.value.set(collection.id, collection)
  collectionDetails.value = new Map(collectionDetails.value)
}

function removeCollection(collectionId) {
  collections.value = collections.value.filter((collection) => collection.id !== collectionId)
  if (collectionDetails.value.has(collectionId)) {
    collectionDetails.value.delete(collectionId)
    collectionDetails.value = new Map(collectionDetails.value)
  }
}

function getCollectionPreviewItems(collection) {
  const detail = collectionDetails.value.get(collection.id)
  if (!detail?.sections) return []

  return detail.sections
    .flatMap((section) => section.items || [])
    .slice(0, 9)
}

// 1, 2 or 4 cover tiles: the largest layout the collection can fill completely.
function getCollectionCover(collection) {
  const items = getCollectionPreviewItems(collection)
  const count = items.length >= 4 ? 4 : items.length >= 2 ? 2 : items.length
  return items.slice(0, count)
}

function isVideo(fileFormat) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat)
}

function openCollection(id) {
  router.push({ name: 'collection-detail', params: { id } })
}

function handleCollectionContextMenu(event, collection) {
  entityContextMenu.show({
    event,
    entityType: 'collection',
    entityId: collection.id,
    entityName: collection.name || 'Untitled',
    isSelected: false,
    selectedCount: 1,
    projectId: collection.project_id
  })
}

function handleContextMenuOpen(entityType, entityId) {
  if (entityType !== 'collection') return
  openCollection(entityId)
}

async function handleContextMenuDelete(entityType, entityId) {
  if (entityType !== 'collection') return
  const removedSummary = collections.value.find((b) => b.id === entityId)
  const removedDetail = collectionDetails.value.get(entityId)
  if (!removedSummary) return

  removeCollection(entityId)

  try {
    await deleteCollection(entityId)
  } catch (err) {
    console.error('Failed to delete collection:', err)
    upsertCollectionSummary(removedSummary)
    if (removedDetail) {
      collectionDetails.value.set(entityId, removedDetail)
      collectionDetails.value = new Map(collectionDetails.value)
    }
    addToast('Failed to delete collection', 'error', 5000)
    return
  }

  addToast('Deleted 1 collection', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!collections.value.find((b) => b.id === entityId)) {
        upsertCollectionSummary(removedSummary)
        if (removedDetail) {
          collectionDetails.value.set(entityId, removedDetail)
          collectionDetails.value = new Map(collectionDetails.value)
        }
      }
      try {
        await restoreCollection(entityId)
      } catch (err) {
        console.error('Failed to restore collection:', err)
        removeCollection(entityId)
        addToast('Failed to restore collection', 'error', 5000)
      }
    }
  })
}

async function handleContextMenuRename(entityType, entityId, entityName) {
  if (isCompact.value) { renameTarget.value = collections.value.find((b) => b.id === entityId) || { id: entityId, name: entityName }; return }
  router.push({ name: 'collection-detail', params: { id: entityId }, query: { rename: '1' } })
}

const renameTarget = ref(null)
async function renameFromSheet(name) {
  const collection = renameTarget.value
  renameTarget.value = null
  if (!collection) return
  try {
    const updated = await updateCollection(collection.id, { name })
    const idx = collections.value.findIndex((b) => b.id === collection.id)
    if (idx >= 0) collections.value[idx] = { ...collections.value[idx], name: updated?.name ?? name }
  } catch (err) {
    console.error('Failed to rename collection:', err)
  }
}

const moveEntityToProject = useEntityMove()
async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  if (await moveEntityToProject('collection', entityId, projectId)) await loadCollections()
}

function selectSort(value) {
  sortBy.value = value
  sortDropdownOpen.value = false
}

function handleDocumentClick(event) {
  const target = event.target
  if (sortDropdownRef.value?.contains(target)) return
  sortDropdownOpen.value = false
}

function formatCollectionMeta(collection) {
  const assetCount = collection.asset_count || 0
  const assetLabel = `${assetCount} ${assetCount === 1 ? 'asset' : 'assets'}`
  if (!collection.updated_at) return assetLabel
  return `${assetLabel} • Updated ${formatRelativeTime(collection.updated_at)}`
}

async function createNewCollection() {
  const collection = await createCollection('', props.projectId)
  router.push({ name: 'collection-detail', params: { id: collection.id } })
}

onMounted(loadCollections)
onMounted(() => {
  document.addEventListener('mousedown', handleDocumentClick)
})

unsubscribers.push(on('collection_created', (data) => {
  if (!data.collection) return
  if ((data.collection.project_id ?? null) !== (props.projectId ?? null)) return
  applyCollectionPayload(data.collection)
}))

unsubscribers.push(on('collection_updated', (data) => {
  if (!data.collection) return
  if ((data.collection.project_id ?? null) !== (props.projectId ?? null)) return
  applyCollectionPayload(data.collection)
}))

unsubscribers.push(on('collection_items_changed', (data) => {
  if (data.collection) applyCollectionPayload(data.collection)
}))

unsubscribers.push(on('collection_deleted', (data) => {
  if (data.collection_id != null) removeCollection(data.collection_id)
}))

unsubscribers.push(on('collection_restored', (data) => {
  if (!data.collection) return
  if ((data.collection.project_id ?? null) !== (props.projectId ?? null)) return
  applyCollectionPayload(data.collection)
}))

onUnmounted(() => {
  document.removeEventListener('mousedown', handleDocumentClick)
  unsubscribers.forEach((unsubscribe) => unsubscribe?.())
})

// Compact header: the hub's create action is the header plus button.
const compactCreate = { label: 'New collection', run: () => createNewCollection() }
onMounted(() => setCompactPrimaryAction(compactCreate))
onActivated(() => setCompactPrimaryAction(compactCreate))
</script>
