<template>
  <div class="relative h-full flex flex-col bg-base">
    <!-- Slideshow Mode -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      @close="exitSlideshow"
      @update:current-media-id="updateCurrentMediaId"
    />

    <!-- Main content -->
    <div v-else class="h-full overflow-y-auto custom-scrollbar">
      <div class="min-h-full flex flex-col items-center px-8 lg:px-16" :class="loaded ? 'opacity-100' : 'opacity-0'" style="transition: opacity 0.15s ease-in">

        <!-- Hero area — centered in space above content -->
        <div class="flex-1 flex flex-col items-center justify-center w-full pt-24 pb-16">
          <h1 class="text-3xl font-semibold text-content mb-16">What would you like to create today?</h1>

          <div class="w-full max-w-[720px]">
            <ChatInputBox
              ref="chatInputBoxRef"
              v-model="inputText"
              :attachments="inputAttachments"
              :rows="3"
              :disabled="submitting"
              :agent-unavailable="agentModelUnavailable"
              @update:attachments="inputAttachments = $event"
              @submit="submitMessage"
            >
              <template v-if="newChatImageUnsupported" #context-header>
                <div class="px-4 pt-2 text-xs text-amber-500">{{ newChatImageUnsupported }}</div>
              </template>
              <template #model-picker>
                <ChatModelPicker
                  :model-slug="selectedNewChatModel"
                  @update:model-slug="selectedNewChatModel = $event"
                />
              </template>
            </ChatInputBox>
          </div>
        </div>

        <!-- Content sections -->
        <div ref="contentRef" class="w-full max-w-[960px] pb-12 space-y-10">

          <!-- Recents Media -->
          <div v-if="recentMedia.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">Recents</h2>
              <router-link to="/browse" class="text-xs text-content-muted hover:text-content-secondary transition-colors">
                View all
              </router-link>
            </div>
            <div class="grid gap-1.5" :style="{ gridTemplateColumns: `repeat(${mediaColumns}, 1fr)` }">
              <div
                v-for="(media, index) in visibleMedia"
                :key="media.id"
                class="aspect-square rounded-lg overflow-hidden cursor-pointer hover:opacity-80 transition-opacity"
                @click="openMediaSlideshow(index)"
              >
                <MediaImage
                  :media-id="mediaIdOf(media)"
                  :file-hash="media.file_hash"
                  :thumbnail="true"
                  :thumbnail-size="256"
                  container-class="w-full h-full"
                  class="w-full h-full object-cover"
                />
              </div>
            </div>
          </div>

          <!-- Boards -->
          <div v-if="recentBoards.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">Boards</h2>
              <router-link to="/boards" class="text-xs text-content-muted hover:text-content-secondary transition-colors">
                View all
              </router-link>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="board in visibleBoards"
                :key="board.id"
                @click="openBoard(board.id)"
                @contextmenu="handleBoardContextMenu($event, board)"
                @dragover.prevent="dragOverBoardId = board.id"
                @dragleave="dragOverBoardId === board.id && (dragOverBoardId = null)"
                @drop.prevent="handleBoardDrop(board.id, $event)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all text-left bg-transparent cursor-pointer"
                :class="dragOverBoardId === board.id ? 'border-blue-500 bg-blue-500/10' : 'border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle'"
              >
                <div class="flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden bg-overlay-subtle">
                  <div v-if="getBoardPreviewItems(board).length > 0" class="grid grid-cols-2 gap-[1px] w-full h-full">
                    <MediaImage
                      v-for="item in getBoardPreviewItems(board).slice(0, 4)"
                      :key="`${board.id}-${item.id}`"
                      :media-id="mediaIdOf(item)"
                      :file-hash="item.file_hash"
                      :thumbnail="true"
                      :thumbnail-size="64"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="w-full h-full"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <div v-else class="w-full h-full flex items-center justify-center text-content-muted">
                    <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
                    </svg>
                  </div>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-content font-medium truncate">{{ board.name || 'Untitled board' }}</div>
                  <div class="text-xs text-content-muted truncate mt-0.5">{{ formatBoardMeta(board) }}</div>
                </div>
              </button>
            </div>
          </div>

          <!-- Flows -->
          <div v-if="recentFlows.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">Flows</h2>
              <router-link to="/flows" class="text-xs text-content-muted hover:text-content-secondary transition-colors">
                View all
              </router-link>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="flow in visibleFlows"
                :key="flow.id"
                @click="openFlow(flow)"
                @contextmenu="handleFlowContextMenu($event, flow)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
              >
                <EntityIcon type="flow" size="md" />
                <div class="flex-1 min-w-0">
                  <div
                    v-if="flow.name"
                    class="text-sm text-content font-medium truncate"
                  >{{ flow.name }}</div>
                  <div
                    v-else
                    class="text-sm text-content-muted italic truncate"
                  >Name this flow...</div>
                  <FlowStatusPill
                    :flow-id="flow.id"
                    show-pending
                    text-class="truncate text-xs text-content-muted"
                    class="mt-0.5"
                  />
                </div>
              </button>
            </div>
          </div>

          <!-- Chats -->
          <div v-if="recentChats.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">Chats</h2>
              <router-link to="/chats" class="text-xs text-content-muted hover:text-content-secondary transition-colors">
                View all
              </router-link>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="chat in visibleChats"
                :key="chat.id"
                @click="openChat(chat)"
                @contextmenu="handleChatContextMenu($event, chat)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
              >
                <div v-if="hasChatMedia(chat)" class="flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden">
                  <MediaImage
                    :media-id="chat.recent_media[0].media_id"
                    :file-hash="chat.recent_media[0].file_hash"
                    :thumbnail="true"
                    :thumbnail-size="64"
                    :draggable="false"
                    :enable-context-menu="false"
                    container-class="w-full h-full"
                    class="w-full h-full object-cover"
                  />
                </div>
                <EntityIcon v-else type="chat" size="md" shape="rounded" />
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-content font-medium truncate">{{ chat.name || 'New chat' }}</div>
                  <div class="text-xs text-content-muted truncate mt-0.5">
                    <template v-if="chat.last_message">{{ chat.last_message }}</template>
                    <template v-else-if="chat.updated_at">{{ formatRelativeTime(chat.updated_at) }}</template>
                  </div>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />

    <MediaContextMenu />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MediaContextMenu, MediaImage } from '../components/media'
import EntityIcon from '../components/EntityIcon.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import ChatModelPicker from '../components/chat/ChatModelPicker.vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import FlowStatusPill from '../components/flow/FlowStatusPill.vue'
import { useSlideshow } from '../composables/useSlideshow'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useFlowsApi } from '../composables/useFlowsApi'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'
import { getDroppedAssetRefs, getDroppedMediaIds } from '../composables/useDragPreview'
import { pendingMedia, consumePendingMedia } from '../composables/usePendingMedia'
import { useAgentModelAvailability } from '../composables/useAgentModelAvailability'
import { useAvailableModels } from '../composables/useAvailableModels'
import { mediaIdOf } from '../utils/assetIdentity'

const router = useRouter()
const { getBoards, getBoard, addMediaToBoard, deleteBoard, restoreBoard, updateBoard } = useMediaApi()
const { fetchAssets, addToBoard: addAssetsToBoard } = useAssetApi()
const { listFlows, updateFlow, deleteFlow, restoreFlow } = useFlowsApi()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()
const { agentModelUnavailable, checkAgentModels } = useAgentModelAvailability()
const { globalDefault, getSelectableModel } = useAvailableModels()

const chatInputBoxRef = ref(null)
const contentRef = ref(null)
const inputText = ref('')
const inputAttachments = ref([])
const selectedNewChatModel = ref(null)
const selectedNewChatModelInfo = computed(() => {
  const slug = selectedNewChatModel.value || globalDefault.value
  return getSelectableModel(slug)
})
const newChatImageUnsupported = computed(() => {
  if (inputAttachments.value.length === 0) return ''
  const model = selectedNewChatModelInfo.value
  if (!model || (model.input_modalities || ['text']).includes('image')) return ''
  return `${model.name} can't use images. Remove the image or choose another model.`
})
const submitting = ref(false)
const recentChats = ref([])
const recentMedia = ref([])
const recentBoards = ref([])
const recentFlows = ref([])
const boardDetails = ref(new Map())
const loaded = ref(false)
const dragOverBoardId = ref(null)
const contentWidth = ref(960)

const hasContent = computed(() => loaded.value && (recentChats.value.length > 0 || recentMedia.value.length > 0))

const isCompact = computed(() => contentWidth.value < 700)

const mediaColumns = computed(() => {
  if (isCompact.value) return 3
  return 6
})

const visibleMedia = computed(() => recentMedia.value.slice(0, mediaColumns.value))
const visibleChats = computed(() => isCompact.value ? recentChats.value.slice(0, 2) : recentChats.value.slice(0, 4))
const visibleBoards = computed(() => recentBoards.value.slice(0, 2))
const visibleFlows = computed(() => isCompact.value ? recentFlows.value.slice(0, 2) : recentFlows.value.slice(0, 4))

function hasChatMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

// ==================== Content width tracking ====================

let resizeObserver = null

function setupResizeObserver() {
  if (!contentRef.value) return
  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      contentWidth.value = entry.contentRect.width
    }
  })
  resizeObserver.observe(contentRef.value)
}

function cleanupResizeObserver() {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
}

// ==================== Data loading ====================

async function loadRecentChats() {
  try {
    const response = await fetch('/api/chats/previews?page=1&page_size=6')
    if (!response.ok) return
    const data = await response.json()
    recentChats.value = data.items || []
  } catch (err) {
    console.error('Failed to load recent chats:', err)
  }
}

async function loadRecentFlows() {
  try {
    const all = await listFlows()
    recentFlows.value = [...all]
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      .slice(0, 6)
  } catch (err) {
    console.error('Failed to load recent flows:', err)
  }
}

async function loadRecentMedia() {
  try {
    const response = await fetchAssets({ sort_by: 'created_desc', page: 1, page_size: 16 })
    recentMedia.value = response.items || []
  } catch (err) {
    console.error('Failed to load recent media:', err)
  }
}

async function openMediaSlideshow(index) {
  try {
    const items = [...recentMedia.value]
    const pageProvider = async (pageNumber, pageSize) => {
      const start = pageNumber * pageSize
      return items.slice(start, start + pageSize)
    }
    enterSlideshow({
      totalCount: items.length,
      startIndex: index,
      pageProvider
    })
  } catch (err) {
    console.error('Failed to open slideshow:', err)
  }
}

// ==================== Submit ====================

async function submitMessage() {
  if (agentModelUnavailable.value) return
  if (newChatImageUnsupported.value) {
    addToast(newChatImageUnsupported.value, 'error', 5000)
    return
  }
  const text = inputText.value.trim()
  const hasAttachments = inputAttachments.value.length > 0
  if (!text && !hasAttachments) return
  if (submitting.value) return

  submitting.value = true
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_slug: selectedNewChatModel.value })
    })
    if (!response.ok) throw new Error('Failed to create chat')
    const newChat = await response.json()

    const query = {}
    if (text) query.initialMessage = text
    if (hasAttachments) {
      query.attachmentIds = inputAttachments.value
        .filter(a => a.media_id)
        .map(a => a.media_id)
        .join(',')
    }

    inputText.value = ''
    inputAttachments.value = []
    router.push({
      name: 'chat',
      params: { id: newChat.id },
      query
    })
  } catch (err) {
    console.error('Failed to create chat:', err)
  } finally {
    submitting.value = false
  }
}

function openChat(chat) {
  router.push({ name: 'chat', params: { id: chat.id } })
}

async function loadRecentBoards() {
  try {
    const boards = await getBoards()
    recentBoards.value = boards.slice(0, 6)

    const results = await Promise.allSettled(
      recentBoards.value.map((board) => getBoard(board.id))
    )

    const next = new Map()
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        next.set(recentBoards.value[index].id, result.value)
      }
    })
    boardDetails.value = next
  } catch (err) {
    console.error('Failed to load boards:', err)
  }
}

function openBoard(boardId) {
  router.push({ name: 'board-detail', params: { id: boardId } })
}

function openFlow(flow) {
  router.push({ name: 'flow', params: { id: String(flow.id) } })
}

// ==================== Entity context menu ====================

function handleBoardContextMenu(event, board) {
  entityContextMenu.show({
    event,
    entityType: 'board',
    entityId: board.id,
    entityName: board.name || 'Untitled',
    projectId: board.project_id ?? null,
    isSelected: false,
    selectedCount: 0
  })
}

function handleFlowContextMenu(event, flow) {
  entityContextMenu.show({
    event,
    entityType: 'flow',
    entityId: flow.id,
    entityName: flow.name || 'Untitled',
    projectId: flow.project_id ?? null,
    isSelected: false,
    selectedCount: 0
  })
}

function handleChatContextMenu(event, chat) {
  entityContextMenu.show({
    event,
    entityType: 'chat',
    entityId: chat.id,
    entityName: chat.name || 'Untitled',
    projectId: chat.project_id ?? null,
    isSelected: false,
    selectedCount: 0
  })
}

function handleContextMenuOpen(entityType, entityId) {
  if (entityType === 'board') openBoard(entityId)
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) } })
  else if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId } })
}

function handleContextMenuRename(entityType, entityId) {
  if (entityType === 'board') router.push({ name: 'board-detail', params: { id: entityId }, query: { rename: '1' } })
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) }, query: { rename: '1' } })
  else if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId }, query: { rename: '1' } })
}

async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  try {
    if (entityType === 'board') {
      await updateBoard(entityId, { project_id: projectId })
      await loadRecentBoards()
    } else if (entityType === 'flow') {
      await updateFlow(entityId, { project_id: projectId })
      await loadRecentFlows()
    } else if (entityType === 'chat') {
      await fetch(`/api/chats/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId })
      })
      await loadRecentChats()
    }
  } catch (err) {
    console.error(`Failed to move ${entityType} to project:`, err)
  }
}

function handleContextMenuDelete(entityType, entityId) {
  if (entityType === 'board') deleteBoardEntry(entityId)
  else if (entityType === 'flow') deleteFlowEntry(entityId)
  else if (entityType === 'chat') deleteChatEntry(entityId)
}

async function deleteBoardEntry(id) {
  const removed = recentBoards.value.find((b) => b.id === id)
  if (!removed) return
  recentBoards.value = recentBoards.value.filter((b) => b.id !== id)

  try {
    await deleteBoard(id)
  } catch (err) {
    console.error('Failed to delete board:', err)
    recentBoards.value = [removed, ...recentBoards.value]
    addToast('Failed to delete board', 'error', 5000)
    return
  }

  addToast('Deleted 1 board', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!recentBoards.value.find((b) => b.id === id)) {
        recentBoards.value = [removed, ...recentBoards.value]
      }
      try {
        await restoreBoard(id)
      } catch (err) {
        console.error('Failed to restore board:', err)
        recentBoards.value = recentBoards.value.filter((b) => b.id !== id)
        addToast('Failed to restore board', 'error', 5000)
      }
    }
  })
}

async function deleteFlowEntry(id) {
  const removed = recentFlows.value.find((r) => r.id === id)
  if (!removed) return
  recentFlows.value = recentFlows.value.filter((r) => r.id !== id)

  try {
    await deleteFlow(id)
  } catch (err) {
    console.error('Failed to delete flow:', err)
    recentFlows.value = [removed, ...recentFlows.value]
    addToast('Failed to delete flow', 'error', 5000)
    return
  }

  addToast('Deleted 1 flow', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!recentFlows.value.find((r) => r.id === id)) {
        recentFlows.value = [removed, ...recentFlows.value]
      }
      try {
        await restoreFlow(id)
      } catch (err) {
        console.error('Failed to restore flow:', err)
        recentFlows.value = recentFlows.value.filter((r) => r.id !== id)
        addToast('Failed to restore flow', 'error', 5000)
      }
    }
  })
}

async function deleteChatEntry(id) {
  const removed = recentChats.value.find((c) => c.id === id)
  if (!removed) return
  recentChats.value = recentChats.value.filter((c) => c.id !== id)

  try {
    const response = await fetch(`/api/chats/${id}`, { method: 'DELETE' })
    if (!response.ok) throw new Error('delete failed')
  } catch (err) {
    console.error('Failed to delete chat:', err)
    recentChats.value = [removed, ...recentChats.value]
    addToast('Failed to delete chat', 'error', 5000)
    return
  }

  addToast('Deleted 1 chat', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!recentChats.value.find((c) => c.id === id)) {
        recentChats.value = [removed, ...recentChats.value]
      }
      try {
        const response = await fetch(`/api/chats/${id}/restore`, { method: 'POST' })
        if (!response.ok) throw new Error('restore failed')
      } catch (err) {
        console.error('Failed to restore chat:', err)
        recentChats.value = recentChats.value.filter((c) => c.id !== id)
        addToast('Failed to restore chat', 'error', 5000)
      }
    }
  })
}

async function handleBoardDrop(boardId, event) {
  dragOverBoardId.value = null
  const mediaIds = getDroppedMediaIds(event.dataTransfer)
  const assetIds = getDroppedAssetRefs(event.dataTransfer).map((item) => item.asset_id)
  if (mediaIds.length === 0) return
  try {
    if (assetIds.length > 0) await addAssetsToBoard(boardId, assetIds)
    else await addMediaToBoard(boardId, mediaIds)
    await loadRecentBoards()
  } catch (err) {
    console.error('Failed to add media to board:', err)
  }
}

function getBoardPreviewItems(board) {
  const detail = boardDetails.value.get(board.id)
  if (!detail?.sections) return []

  return detail.sections
    .flatMap((section) => section.items || [])
    .slice(0, 4)
}

function formatBoardMeta(board) {
  const assetCount = board.asset_count || 0
  const assetLabel = `${assetCount} ${assetCount === 1 ? 'item' : 'items'}`
  if (!board.updated_at) return assetLabel
  return `${assetLabel} • ${formatRelativeTime(board.updated_at)}`
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

// Attach any media handed off to the home input (sidebar drag-drop).
// One-shot consumption from the store — see usePendingMedia for why this isn't
// a URL query param.
function checkPendingMedia() {
  const ids = consumePendingMedia('home')
  if (!ids) return
  for (const id of ids) {
    if (!inputAttachments.value.some(a => a.media_id === id)) {
      inputAttachments.value = [...inputAttachments.value, { media_id: id }]
    }
  }
}

watch(pendingMedia, () => checkPendingMedia(), { flush: 'post' })

async function loadAll() {
  await Promise.all([loadRecentChats(), loadRecentMedia(), loadRecentBoards(), loadRecentFlows()])
  loaded.value = true
}

onMounted(() => {
  setupResizeObserver()
  loadAll()
  checkAgentModels()
  checkPendingMedia()
  chatInputBoxRef.value?.focus()
})

onUnmounted(() => {
  cleanupResizeObserver()
})

onActivated(() => {
  setupResizeObserver()
  loadAll()
  checkAgentModels()
  checkPendingMedia()
  chatInputBoxRef.value?.focus()
})
</script>
