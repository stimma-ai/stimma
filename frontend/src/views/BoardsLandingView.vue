<template>
  <div class="flex h-full flex-col bg-base">
    <div class="flex items-center justify-between border-b border-edge-subtle px-6 py-5">
      <h1 class="text-xl font-semibold leading-none text-content">Boards</h1>

      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          @click="createNewBoard"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New</span>
        </button>
        <div class="relative" ref="sortDropdownRef">
          <button
            class="flex items-center gap-2 rounded-lg border border-edge-subtle bg-overlay-subtle px-3 py-1.5 text-sm text-content-tertiary transition-colors hover:border-edge hover:text-content-secondary"
            @click="sortDropdownOpen = !sortDropdownOpen"
          >
            <span>{{ activeSortLabel }}</span>
            <svg class="h-4 w-4 transition-transform" :class="sortDropdownOpen ? 'rotate-180' : ''" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </button>

          <div
            v-if="sortDropdownOpen"
            class="absolute right-0 top-full z-menu mt-1 min-w-[190px] rounded-lg border border-edge-subtle bg-surface py-1 shadow-xl"
          >
            <button
              v-for="option in sortOptions"
              :key="option.value"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-overlay-subtle"
              :class="sortBy === option.value ? 'text-blue-500' : 'text-content-secondary'"
              @click="selectSort(option.value)"
            >
              <svg
                v-if="sortBy === option.value"
                class="h-4 w-4 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-4 flex-shrink-0"></span>
              <span>{{ option.label }}</span>
            </button>
          </div>
        </div>

        <div class="relative">
          <svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input v-no-autocorrect
            v-model="searchQuery"
            type="text"
            placeholder="Search boards..."
            class="w-48 rounded-lg border border-edge-subtle bg-overlay-subtle py-1.5 pl-9 pr-3 text-sm text-content-secondary placeholder-white/30 focus:border-accent focus:outline-none"
          />
        </div>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-6 pb-6">
      <div v-if="loading" class="py-20 text-center text-content-muted">Loading boards...</div>
      <div v-else-if="boards.length === 0" class="flex h-64 flex-col items-center justify-center text-center">
        <p class="mb-2 text-content-muted">No boards yet</p>
        <p class="text-sm text-content-muted">Create a board to curate a working set of assets.</p>
      </div>
      <div v-else-if="filteredBoards.length === 0" class="flex h-64 flex-col items-center justify-center text-center">
        <svg class="mb-4 h-16 w-16 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <p class="mb-2 text-content-muted">No boards match your search</p>
      </div>

      <div v-else class="grid grid-cols-1 gap-6 pt-6 sm:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="board in filteredBoards"
          :key="board.id"
          class="group text-left"
          @click="openBoard(board.id)"
          @contextmenu="handleBoardContextMenu($event, board)"
        >
          <!-- Contact-sheet cover: mini masonry on matte, 2px media-grid
               gutters, clipped by a fixed-height frame at radius-media.
               No card, no border — hover draws a hairline ring. -->
          <div class="relative h-56 overflow-hidden rounded-media bg-matte transition-shadow group-hover:ring-1 group-hover:ring-edge">
            <div
              v-if="getBoardPreviewItems(board).length > 0"
              class="h-full overflow-hidden p-0.5"
            >
              <div class="flex h-full items-start gap-0.5">
                <div
                  v-for="(column, columnIndex) in getBoardPreviewColumns(board)"
                  :key="`${board.id}-column-${columnIndex}`"
                  class="flex min-w-0 flex-1 flex-col gap-0.5"
                >
                  <div
                    v-for="(item, index) in column"
                    :key="`${board.id}-${columnIndex}-${item.id}-${index}`"
                    class="overflow-hidden bg-overlay-faint"
                    :style="getPreviewTileStyle(item)"
                  >
                    <MediaImage
                      :media-id="item.id"
                      :file-hash="item.file_hash"
                      :file-path="item.file_path"
                      :file-format="item.file_format"
                      :is-video="isVideo(item.file_format)"
                      thumbnail
                      :thumbnail-size="256"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="h-full w-full"
                      img-class="h-full w-full object-cover"
                    />
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="flex h-full items-center justify-center">
              <svg class="h-6 w-6 text-content-muted" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
              </svg>
            </div>
          </div>

          <!-- Print-label caption: name left, mono facts right, one baseline -->
          <div class="flex items-baseline gap-2.5 px-0.5 pt-2">
            <h2
              class="min-w-0 flex-1 truncate text-[13px] font-medium"
              :class="board.name ? 'text-content' : 'italic font-normal text-content-muted'"
            >
              {{ board.name || 'Name this board...' }}
            </h2>
            <p class="flex-none whitespace-nowrap font-mono text-[11px] tabular-nums text-content-tertiary">{{ board.asset_count || 0 }}<span v-if="board.updated_at"> · {{ formatRelativeTime(board.updated_at) }}</span></p>
          </div>
        </button>
      </div>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref , watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EntityContextMenu from '../components/EntityContextMenu.vue'
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
const { createBoard, deleteBoard, restoreBoard, getBoard, getBoards, updateBoard } = useMediaApi()
const { addToast } = useToasts()
const { on } = useWebSocket()

const boards = ref([])
const boardDetails = ref(new Map())
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
  { value: 'updated', label: 'Recently Updated' },
  { value: 'name', label: 'Name' }
]

const activeSortLabel = computed(() => {
  return sortOptions.find((option) => option.value === sortBy.value)?.label || 'Sort'
})

const filteredBoards = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const filtered = !query
    ? [...boards.value]
    : boards.value.filter((board) => {
        const name = (board.name || '').toLowerCase()
        const meta = formatBoardMeta(board).toLowerCase()
        return name.includes(query) || meta.includes(query)
      })

  filtered.sort((a, b) => {
    if (sortBy.value === 'name') {
      const aName = (a.name || '').trim() || 'Name this board...'
      const bName = (b.name || '').trim() || 'Name this board...'
      return aName.localeCompare(bName, undefined, { sensitivity: 'base' })
    }

    const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
    const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
    return bTime - aTime
  })

  return filtered
})

async function loadBoards() {
  loading.value = true
  try {
    boards.value = await getBoards(props.projectId)
    await loadBoardPreviews()
  } finally {
    loading.value = false
  }
}

async function loadBoardPreviews() {
  const results = await Promise.allSettled(
    boards.value.map((board) => getBoard(board.id))
  )

  const next = new Map()
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      next.set(boards.value[index].id, result.value)
    }
  })
  boardDetails.value = next
}

function upsertBoardSummary(board) {
  const summary = {
    id: board.id,
    name: board.name || '',
    asset_count: board.asset_count || 0,
    updated_at: board.updated_at
  }
  const index = boards.value.findIndex((entry) => entry.id === board.id)
  if (index === -1) {
    boards.value = [summary, ...boards.value]
  } else {
    boards.value[index] = {
      ...boards.value[index],
      ...summary
    }
    boards.value = [...boards.value]
  }
}

function applyBoardPayload(board) {
  if (!board) return
  upsertBoardSummary(board)
  boardDetails.value.set(board.id, board)
  boardDetails.value = new Map(boardDetails.value)
}

function removeBoard(boardId) {
  boards.value = boards.value.filter((board) => board.id !== boardId)
  if (boardDetails.value.has(boardId)) {
    boardDetails.value.delete(boardId)
    boardDetails.value = new Map(boardDetails.value)
  }
}

function getBoardPreviewItems(board) {
  const detail = boardDetails.value.get(board.id)
  if (!detail?.sections) return []

  return detail.sections
    .flatMap((section) => section.items || [])
    .slice(0, 9)
}

function getBoardPreviewColumns(board) {
  const items = getBoardPreviewItems(board)
  const columns = [[], [], []]
  items.forEach((item, index) => {
    columns[index % columns.length].push(item)
  })
  return columns
}

function getPreviewTileStyle(item) {
  const width = Math.max(item?.width || 1, 1)
  const height = Math.max(item?.height || 1, 1)
  return {
    aspectRatio: `${width} / ${height}`
  }
}

function isVideo(fileFormat) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat)
}

function openBoard(id) {
  router.push({ name: 'board-detail', params: { id } })
}

function handleBoardContextMenu(event, board) {
  entityContextMenu.show({
    event,
    entityType: 'board',
    entityId: board.id,
    entityName: board.name || 'Untitled',
    isSelected: false,
    selectedCount: 1,
    projectId: board.project_id
  })
}

function handleContextMenuOpen(entityType, entityId) {
  if (entityType !== 'board') return
  openBoard(entityId)
}

async function handleContextMenuDelete(entityType, entityId) {
  if (entityType !== 'board') return
  const removedSummary = boards.value.find((b) => b.id === entityId)
  const removedDetail = boardDetails.value.get(entityId)
  if (!removedSummary) return

  removeBoard(entityId)

  try {
    await deleteBoard(entityId)
  } catch (err) {
    console.error('Failed to delete board:', err)
    upsertBoardSummary(removedSummary)
    if (removedDetail) {
      boardDetails.value.set(entityId, removedDetail)
      boardDetails.value = new Map(boardDetails.value)
    }
    addToast('Failed to delete board', 'error', 5000)
    return
  }

  addToast('Deleted 1 board', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!boards.value.find((b) => b.id === entityId)) {
        upsertBoardSummary(removedSummary)
        if (removedDetail) {
          boardDetails.value.set(entityId, removedDetail)
          boardDetails.value = new Map(boardDetails.value)
        }
      }
      try {
        await restoreBoard(entityId)
      } catch (err) {
        console.error('Failed to restore board:', err)
        removeBoard(entityId)
        addToast('Failed to restore board', 'error', 5000)
      }
    }
  })
}

async function handleContextMenuRename(entityType, entityId, entityName) {
  router.push({ name: 'board-detail', params: { id: entityId }, query: { rename: '1' } })
}

async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  try {
    await updateBoard(entityId, { project_id: projectId })
    await loadBoards()
  } catch (err) {
    console.error('Failed to move board to project:', err)
  }
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

function formatBoardMeta(board) {
  const assetCount = board.asset_count || 0
  const assetLabel = `${assetCount} ${assetCount === 1 ? 'item' : 'items'}`
  if (!board.updated_at) return assetLabel
  return `${assetLabel} • Updated ${formatRelativeTime(board.updated_at)}`
}

function formatRelativeTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000))

  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`

  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d ago`

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric'
  })
}

async function createNewBoard() {
  const board = await createBoard('', props.projectId)
  router.push({ name: 'board-detail', params: { id: board.id } })
}

onMounted(loadBoards)
onMounted(() => {
  document.addEventListener('mousedown', handleDocumentClick)
})

unsubscribers.push(on('board_created', (data) => {
  if (!data.board) return
  if ((data.board.project_id ?? null) !== (props.projectId ?? null)) return
  applyBoardPayload(data.board)
}))

unsubscribers.push(on('board_updated', (data) => {
  if (!data.board) return
  if ((data.board.project_id ?? null) !== (props.projectId ?? null)) return
  applyBoardPayload(data.board)
}))

unsubscribers.push(on('board_items_changed', (data) => {
  if (data.board) applyBoardPayload(data.board)
}))

unsubscribers.push(on('board_deleted', (data) => {
  if (data.board_id != null) removeBoard(data.board_id)
}))

unsubscribers.push(on('board_restored', (data) => {
  if (!data.board) return
  if ((data.board.project_id ?? null) !== (props.projectId ?? null)) return
  applyBoardPayload(data.board)
}))

onUnmounted(() => {
  document.removeEventListener('mousedown', handleDocumentClick)
  unsubscribers.forEach((unsubscribe) => unsubscribe?.())
})
</script>
