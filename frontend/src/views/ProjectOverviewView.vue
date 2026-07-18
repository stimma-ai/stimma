<template>
  <div class="relative h-full flex flex-col bg-base">
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      @close="exitSlideshow"
      @update:current-media-id="updateCurrentMediaId"
    />

    <div v-else class="h-full overflow-y-auto custom-scrollbar">
      <div class="min-h-full flex flex-col items-center px-8 lg:px-16 pt-8" :class="loaded ? 'opacity-100' : 'opacity-0'" style="transition: opacity 0.15s ease-in">

        <div class="flex-1 flex flex-col items-center justify-center w-full">
          <h1 class="text-3xl font-semibold text-content mb-10">{{ heroTitle }}</h1>

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
                  :project-id="props.project.id"
                  @update:model-slug="selectedNewChatModel = $event"
                />
              </template>
            </ChatInputBox>
          </div>
        </div>

        <div ref="contentRef" class="w-full max-w-[960px] pb-12 space-y-10">
          <div v-if="recentMedia.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Recents</h2>
              <button class="text-xs text-content-muted hover:text-content-secondary transition-colors" @click="openProjectAssets">
                View all
              </button>
            </div>

            <div class="grid gap-1.5" :style="{ gridTemplateColumns: `repeat(${mediaColumns}, 1fr)` }">
              <div
                v-for="(media, index) in visibleMedia"
                :key="media.id"
                class="aspect-square rounded-media overflow-hidden cursor-pointer hover:opacity-80 transition-opacity"
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

          <div v-if="recentBoards.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Boards</h2>
              <button class="text-xs text-content-muted hover:text-content-secondary transition-colors" @click="openProjectBoards">
                View all
              </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="board in visibleBoards"
                :key="board.id"
                @click="openBoard(board.id)"
                @dragover.prevent="dragOverBoardId = board.id"
                @dragleave="dragOverBoardId === board.id && (dragOverBoardId = null)"
                @drop.prevent="handleBoardDrop(board.id, $event)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all text-left bg-transparent cursor-pointer"
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

          <div v-if="recentFlows.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Flows</h2>
              <button class="text-xs text-content-muted hover:text-content-secondary transition-colors" @click="openProjectFlows">
                View all
              </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="flow in visibleFlows"
                :key="flow.id"
                @click="openFlow(flow)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
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

          <div v-if="recentChats.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Chats</h2>
              <button class="text-xs text-content-muted hover:text-content-secondary transition-colors" @click="openProjectChats">
                View all
              </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                v-for="chat in visibleChats"
                :key="chat.id"
                @click="openChat(chat)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
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

    <MediaContextMenu />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MediaContextMenu, MediaImage } from '../components/media'
import EntityIcon from '../components/EntityIcon.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import ChatModelPicker from '../components/chat/ChatModelPicker.vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import FlowStatusPill from '../components/flow/FlowStatusPill.vue'
import { useSlideshow } from '../composables/useSlideshow'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useFlowsApi } from '../composables/useFlowsApi'
import { getDroppedAssetRefs, getDroppedMediaIds } from '../composables/useDragPreview'
import { useAgentModelAvailability } from '../composables/useAgentModelAvailability'
import { useAvailableModels } from '../composables/useAvailableModels'
import { useToasts } from '../composables/useToasts'
import { mediaIdOf } from '../utils/assetIdentity'

const props = defineProps({
  project: {
    type: Object,
    required: true
  }
})

const router = useRouter()
const { getBoards, getBoard, addMediaToBoard } = useMediaApi()
const { fetchAssets, addToBoard: addAssetsToBoard } = useAssetApi()
const { listFlows } = useFlowsApi()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()
const { agentModelUnavailable, checkAgentModels } = useAgentModelAvailability()
const { globalDefault, getSelectableModel } = useAvailableModels()
const { addToast } = useToasts()

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

const isCompact = computed(() => contentWidth.value < 700)

const mediaColumns = computed(() => {
  if (isCompact.value) return 3
  return 6
})

const visibleMedia = computed(() => recentMedia.value.slice(0, mediaColumns.value))
const visibleChats = computed(() => isCompact.value ? recentChats.value.slice(0, 2) : recentChats.value.slice(0, 4))
const visibleBoards = computed(() => recentBoards.value.slice(0, 2))
const visibleFlows = computed(() => isCompact.value ? recentFlows.value.slice(0, 2) : recentFlows.value.slice(0, 4))
const heroTitle = computed(() => {
  const name = props.project?.name?.trim()
  if (!name) return 'What would you like to create today?'
  return `How can I help with ${name}?`
})

function hasChatMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

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

async function loadRecentChats() {
  try {
    const params = new URLSearchParams({
      page: '1',
      page_size: '6',
      project_id: String(props.project.id)
    })
    const response = await fetch(`/api/chats/previews?${params.toString()}`)
    if (!response.ok) return
    const data = await response.json()
    recentChats.value = data.items || []
  } catch (err) {
    console.error('Failed to load project chats:', err)
  }
}

async function loadRecentMedia() {
  try {
    const response = await fetchAssets({
      project_id: props.project.id,
      sort_by: 'created_desc',
      page: 1,
      page_size: 16,
    })
    recentMedia.value = response.items || []
  } catch (err) {
    console.error('Failed to load project media:', err)
  }
}

async function loadRecentFlows() {
  try {
    const all = await listFlows({ project_id: props.project.id })
    recentFlows.value = [...all]
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      .slice(0, 6)
  } catch (err) {
    console.error('Failed to load project flows:', err)
  }
}

async function loadRecentBoards() {
  try {
    const boards = await getBoards(props.project.id)
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
    console.error('Failed to load project boards:', err)
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
      body: JSON.stringify({
        project_id: props.project.id,
        model_slug: selectedNewChatModel.value,
      })
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
    console.error('Failed to create project chat:', err)
  } finally {
    submitting.value = false
  }
}

function openChat(chat) {
  router.push({ name: 'chat', params: { id: chat.id } })
}

function openBoard(boardId) {
  router.push({ name: 'board-detail', params: { id: boardId } })
}

function openFlow(flow) {
  router.push({ name: 'flow', params: { id: String(flow.id) } })
}

function openProjectChats() {
  router.push({ name: 'project-chats', params: { id: props.project.id } })
}

function openProjectBoards() {
  router.push({ name: 'project-boards', params: { id: props.project.id } })
}

function openProjectFlows() {
  router.push({ name: 'project-flows', params: { id: props.project.id } })
}

function openProjectAssets() {
  router.push({ name: 'project-assets', params: { id: props.project.id } })
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

async function loadAll() {
  await Promise.all([loadRecentChats(), loadRecentMedia(), loadRecentBoards(), loadRecentFlows()])
  loaded.value = true
}

watch(() => props.project.id, () => {
  loadAll()
  checkAgentModels(props.project.id)
}, { immediate: true })

onMounted(() => {
  setupResizeObserver()
  chatInputBoxRef.value?.focus()
})

onUnmounted(() => {
  cleanupResizeObserver()
})

onActivated(() => {
  setupResizeObserver()
  loadAll()
  checkAgentModels(props.project.id)
  chatInputBoxRef.value?.focus()
})
</script>
