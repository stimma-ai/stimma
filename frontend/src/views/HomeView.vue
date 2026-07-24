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
        <div class="relative flex-1 flex flex-col items-center justify-center w-full pt-24 pb-16">
          <!-- Soft ambient halo, centered behind the greeting + prompt -->
          <div
            class="pointer-events-none absolute left-1/2 top-1/2 h-[480px] w-[880px] max-w-full -translate-x-1/2 -translate-y-1/2"
            style="background: radial-gradient(50% 60% at 45% 40%, rgba(45, 212, 191, 0.10), transparent 70%), radial-gradient(45% 55% at 58% 55%, rgba(129, 140, 248, 0.10), transparent 70%); filter: blur(12px)"
          ></div>

          <h1 class="relative font-brand text-[32px] font-bold tracking-tight text-content mb-2 text-center">{{ greetingParts.pre }}<span class="bg-gradient-to-br from-teal-400 via-cyan-400 to-indigo-400 bg-clip-text text-transparent">{{ greetingParts.word }}</span>{{ greetingParts.post }}</h1>
          <!-- Spacer where the greeting subtitle used to sit — keeps the hero rhythm -->
          <div class="relative h-[20px] mb-10" aria-hidden="true"></div>

          <div class="relative w-full max-w-[720px]">
            <div class="rounded-lg shadow-lg shadow-black/20">
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

            <!-- Tool launchers docked to the prompt (recent tools, starter picks as cold-start fill) -->
            <div v-if="!isFirstRun && launcherTools.length > 0" class="flex flex-wrap justify-center gap-2 mt-4">
              <button
                v-for="tool in launcherTools"
                :key="tool.full_tool_id"
                @click="openToolById(tool.full_tool_id)"
                class="flex items-center gap-2 px-3 py-1.5 rounded-md bg-overlay-faint hover:bg-overlay-subtle transition-colors cursor-pointer"
                :title="tool.name"
              >
                <div class="w-5 h-5 flex-shrink-0 text-content-secondary"><ToolIcon :tool="tool" bare :ring="false" /></div>
                <span class="text-[13px] font-medium text-content max-w-[180px] truncate">{{ tool.name }}</span>
                <span class="text-[11px]" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ providerLabel(tool) }}</span>
              </button>
              <router-link
                to="/tools"
                class="flex items-center px-3 py-1.5 rounded-md text-[13px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
              >
                All tools →
              </router-link>
            </div>
          </div>

          <!-- First run: recommended starting points instead of empty sections -->
          <div v-if="isFirstRun && starterTools.length > 0" class="relative w-full max-w-[720px] mt-12">
            <div class="flex items-center gap-4 mb-4">
              <div class="h-px flex-1 bg-edge-subtle"></div>
              <span class="text-xs font-semibold text-content-secondary">Or start with a tool</span>
              <div class="h-px flex-1 bg-edge-subtle"></div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <button
                v-for="pick in starterTools"
                :key="pick.tool.full_tool_id"
                @click="openToolById(pick.tool.full_tool_id)"
                class="flex items-start gap-3.5 rounded-lg p-3.5 text-left transition-all cursor-pointer"
                :class="isStimmaCloudTool(pick.tool)
                  ? 'bg-overlay-faint stimma-cloud-border hover:bg-overlay-subtle'
                  : 'bg-overlay-faint border border-edge-subtle hover:bg-overlay-subtle hover:border-edge'"
              >
                <ToolIcon :tool="pick.tool" size="lg" :ring="false" />
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-semibold text-content truncate">{{ pick.tool.name }}</div>
                  <p v-if="starterDescription(pick.tool)" class="text-xs text-content-secondary line-clamp-2 mt-1 leading-relaxed">{{ starterDescription(pick.tool) }}</p>
                  <div class="flex items-center gap-2 mt-2 overflow-hidden">
                    <span v-if="isStimmaCloudTool(pick.tool)" class="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full bg-teal-600/10 border border-teal-600/25 flex-shrink-0">
                      <span class="stimma-cloud-text">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
                    </span>
                    <span v-else class="px-2 py-0.5 text-[10px] font-medium rounded-full border border-edge text-content-secondary flex-shrink-0 truncate">
                      {{ providerLabel(pick.tool) }}
                    </span>
                    <span class="px-2 py-0.5 text-[10px] font-medium rounded-full border border-edge text-content-secondary flex-shrink-0">
                      {{ formatTaskTypeLabel(pick.taskType) }}
                    </span>
                  </div>
                </div>
              </button>
            </div>
            <div class="flex justify-center mt-4">
              <router-link
                to="/tools"
                class="px-3.5 py-1.5 rounded-full border border-edge-subtle text-[13px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle hover:border-edge transition-colors"
              >
                All tools →
              </router-link>
            </div>
          </div>
        </div>

        <!-- Content sections -->
        <div ref="contentRef" class="w-full max-w-[960px] pb-12 space-y-10">

          <!-- Jump back in: boards, flows, and chats merged into one recency row -->
          <div v-if="jumpBackIn.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Jump back in</h2>
            </div>
            <div class="grid gap-3" :class="isCompact ? 'grid-cols-2' : 'grid-cols-3'">
              <button
                v-for="item in jumpBackIn"
                :key="`${item.type}-${item.id}`"
                @click="openJumpItem(item)"
                @contextmenu="handleJumpContextMenu($event, item)"
                @dragover.prevent="item.type === 'board' && (dragOverBoardId = item.id)"
                @dragleave="item.type === 'board' && dragOverBoardId === item.id && (dragOverBoardId = null)"
                @drop.prevent="item.type === 'board' && handleBoardDrop(item.id, $event)"
                class="flex flex-col rounded-lg border overflow-hidden text-left bg-transparent transition-colors cursor-pointer"
                :class="item.type === 'board' && dragOverBoardId === item.id
                  ? 'border-transparent ring-1 ring-accent/50 bg-accent/10'
                  : 'border-edge-subtle hover:bg-overlay-faint'"
              >
                <!-- Art -->
                <div class="w-full h-28 bg-matte">
                  <!-- Board: filmstrip of tiles at natural aspect, full strip
                       height, left-aligned on matte with 2px media-grid
                       gutters. Widths follow each item's aspect ratio so
                       sparse boards read as tiles on a shelf. -->
                  <div
                    v-if="item.type === 'board' && getBoardPreviewItems(item.board).length > 0"
                    class="h-full overflow-hidden p-0.5"
                  >
                    <div class="flex h-full gap-0.5">
                      <div
                        v-for="(previewItem, index) in getBoardPreviewItems(item.board)"
                        :key="`${item.id}-${previewItem.id}-${index}`"
                        class="h-full flex-shrink-0 max-w-[55%] overflow-hidden bg-overlay-faint"
                        :style="getPreviewTileStyle(previewItem)"
                      >
                        <MediaImage
                          :media-id="mediaIdOf(previewItem)"
                          :file-hash="previewItem.file_hash"
                          :file-path="previewItem.file_path"
                          :file-format="previewItem.file_format"
                          :is-video="isVideoFormat(previewItem.file_format)"
                          :thumbnail="true"
                          :thumbnail-size="256"
                          thumbnail-mode="fit"
                          :object-position="faceObjectPosition(mediaIdOf(previewItem))"
                          :draggable="false"
                          :enable-context-menu="false"
                          container-class="w-full h-full"
                          class="w-full h-full object-cover"
                        />
                      </div>
                    </div>
                  </div>
                  <!-- Flow: filmstrip of surfaced output media -->
                  <div
                    v-else-if="item.type === 'flow' && getFlowPreviewMediaIds(item.id).length > 0"
                    class="flex w-full h-full gap-0.5"
                  >
                    <div
                      v-for="mid in getFlowPreviewMediaIds(item.id)"
                      :key="`${item.id}-${mid}`"
                      class="flex-1 min-w-0 h-full overflow-hidden"
                    >
                      <MediaImage
                        :media-id="mid"
                        :thumbnail="true"
                        :thumbnail-size="256"
                        thumbnail-mode="fit"
                        :object-position="faceObjectPosition(mid)"
                        :draggable="false"
                        :enable-context-menu="false"
                        container-class="w-full h-full"
                        class="w-full h-full object-cover"
                      />
                    </div>
                  </div>
                  <!-- Chat: latest media as cover -->
                  <MediaImage
                    v-else-if="item.type === 'chat' && hasChatMedia(item.chat)"
                    :media-id="item.chat.recent_media[0].media_id"
                    :file-hash="item.chat.recent_media[0].file_hash"
                    :thumbnail="true"
                    :thumbnail-size="256"
                    thumbnail-mode="fit"
                    :object-position="faceObjectPosition(item.chat.recent_media[0].media_id)"
                    :draggable="false"
                    :enable-context-menu="false"
                    container-class="w-full h-full"
                    class="w-full h-full object-cover"
                  />
                  <!-- Fallback: entity icon centered -->
                  <div v-else class="w-full h-full flex items-center justify-center">
                    <EntityIcon :type="item.type" size="lg" />
                  </div>
                </div>
                <!-- Body -->
                <div class="px-3.5 py-3">
                  <div class="text-xs font-semibold text-content-secondary">{{ jumpKindLabel(item) }}</div>
                  <div class="text-sm font-medium truncate mt-1" :class="item.name ? 'text-content' : 'text-content-muted italic'">
                    {{ item.name || jumpUntitledLabel(item) }}
                  </div>
                  <FlowStatusPill
                    v-if="item.type === 'flow'"
                    :flow-id="item.id"
                    show-pending
                    text-class="truncate text-xs text-content-muted"
                    class="mt-0.5"
                  />
                  <div
                    v-else
                    class="text-xs truncate mt-0.5"
                    :class="item.type === 'board' ? 'font-mono tabular-nums text-content-tertiary' : 'text-content-muted'"
                  >{{ item.sub }}</div>
                </div>
              </button>
            </div>
          </div>

          <!-- Library strip -->
          <div v-if="recentMedia.length > 0">
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-xs font-semibold text-content-secondary">Fresh from your library</h2>
              <router-link to="/browse" class="text-xs text-content-muted hover:text-content-secondary transition-colors">
                View all
              </router-link>
            </div>
            <div class="grid gap-0.5" :style="{ gridTemplateColumns: `repeat(${mediaColumns}, 1fr)` }">
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
        </div>
      </div>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />

    <MediaContextMenu @refresh="loadRecentMedia" />
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
import ToolIcon from '../components/tools/ToolIcon.vue'
import { useSlideshow } from '../composables/useSlideshow'
import { useProvidersApi } from '../composables/useProvidersApi'
import { recentEntities } from '../composables/useRecentEntities'
import { pickStarterTools } from '../utils/starterTools'
import { isStimmaCloudTool, toolProviderDisplayName, STIMMA_TOOL_PROVIDER_DISPLAY_NAME } from '../utils/stimmaCloud'
import { formatTaskTypeLabel } from '../utils/taskTypeIcons'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useFlowsApi } from '../composables/useFlowsApi'
import { computeFlowOutputs } from '../composables/useFlowOutputs'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'
import { getDroppedAssetRefs, getDroppedMediaIds } from '../composables/useDragPreview'
import { pendingMedia, consumePendingMedia } from '../composables/usePendingMedia'
import { useAgentModelAvailability } from '../composables/useAgentModelAvailability'
import { useAvailableModels } from '../composables/useAvailableModels'
import { mediaIdOf } from '../utils/assetIdentity'
import { useFaceFocalPoints } from '../composables/useFaceFocalPoints'
import { modelRejectsImageInput } from '../utils/settingsReadiness'

const router = useRouter()
const { getBoards, getBoard, addMediaToBoard, deleteBoard, restoreBoard, updateBoard } = useMediaApi()
// Face-aware framing for "Jump back in" cover art (see useFaceFocalPoints).
const { request: requestFaceFocalPoints, positionOf: faceObjectPosition } = useFaceFocalPoints()
const { fetchAssets, addToBoard: addAssetsToBoard } = useAssetApi()
const { listFlows, listEquations, updateFlow, deleteFlow, restoreFlow } = useFlowsApi()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()
const { agentModelUnavailable, checkAgentModels } = useAgentModelAvailability()
const { globalDefault, getSelectableModel } = useAvailableModels()
const { fetchProvidersAndTools, subscribeToProviderChanges } = useProvidersApi()

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
  if (!model || !modelRejectsImageInput(model)) return ''
  return `${model.name} can't use images. Remove the image or choose another model.`
})
const submitting = ref(false)
const recentChats = ref([])
const recentMedia = ref([])
const recentBoards = ref([])
const recentFlows = ref([])
const flowOutputMedia = ref(new Map()) // flow_id -> [media_id, ...] newest-first
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

function hasChatMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

// ==================== Greeting ====================

// True only after the first load with nothing to show: no chats, boards,
// flows, or library media — i.e. a fresh install right after onboarding.
const isFirstRun = computed(() =>
  loaded.value
  && recentChats.value.length === 0
  && recentBoards.value.length === 0
  && recentFlows.value.length === 0
  && recentMedia.value.length === 0
)

// Split so the display voice can put the prism gradient on ONE word
// (the brand-moment budget from the v3 mock).
const greetingParts = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return { pre: "Good morning, let's make ", word: 'something', post: '.' }
  if (hour < 18) return { pre: 'Good afternoon, what are we ', word: 'making', post: '?' }
  return { pre: 'Good evening, what are we ', word: 'making', post: '?' }
})

// ==================== Tools ====================

const toolsList = ref([])
const recentToolEntities = ref([])

async function loadTools() {
  try {
    const { tools } = await fetchProvidersAndTools()
    toolsList.value = tools.filter(t => !t.metadata?.agent_only)
  } catch (err) {
    console.error('Failed to load tools:', err)
  }
  recentToolEntities.value = recentEntities(60).filter(e => e.type === 'tool')
}

const availableTools = computed(() => toolsList.value.filter(t => t.availability === 'available'))

// Cold-start recommendations: curated favorites fuzzy-matched against
// installed tools, constrained to t2i/i2i/i2v with task coverage.
const starterTools = computed(() => pickStarterTools(availableTools.value, 4))

// Launcher pills under the prompt: recently used tools first (frecency),
// starter picks fill the remaining slots when history is thin. Deduped by
// name as well as id so cloud + local copies of the same model don't both
// take a slot.
const launcherTools = computed(() => {
  const byId = new Map(availableTools.value.map(t => [t.full_tool_id, t]))
  const picked = []
  const seen = new Set()
  const tryAdd = (tool) => {
    const nameKey = `name:${(tool.name || '').toLowerCase().trim()}`
    if (seen.has(tool.full_tool_id) || seen.has(nameKey)) return
    seen.add(tool.full_tool_id)
    seen.add(nameKey)
    picked.push(tool)
  }
  for (const entity of recentToolEntities.value) {
    if (picked.length >= 3) break
    const tool = byId.get(entity.id)
    if (tool) tryAdd(tool)
  }
  for (const pick of starterTools.value) {
    if (picked.length >= 3) break
    tryAdd(pick.tool)
  }
  return picked
})

function providerLabel(tool) {
  return toolProviderDisplayName(tool, tool.provider_id || '')
}

function starterDescription(tool) {
  return tool.metadata?.description || tool.subtitle || ''
}

function openToolById(fullToolId) {
  router.push({ name: 'tool', params: { fullToolId } })
}

// ==================== Jump back in ====================

// An unnamed flow with no parsed program and no runtime state is a stray
// "New flow" click — not something worth jumping back into.
function isEmptyFlow(flow) {
  if (flow.name) return false
  if (flow.has_load_error) return false
  if ((flow.pending_task_count || 0) > 0) return false
  return Object.keys(flow.root_status_summary || {}).length === 0
}

const jumpBackIn = computed(() => {
  const items = []
  for (const board of recentBoards.value) {
    if (!board.name && !(board.asset_count > 0)) continue
    items.push({ type: 'board', id: board.id, name: board.name, sub: formatBoardMeta(board), updatedAt: board.updated_at, board })
  }
  for (const flow of recentFlows.value) {
    if (isEmptyFlow(flow)) continue
    items.push({ type: 'flow', id: flow.id, name: flow.name, sub: '', updatedAt: flow.updated_at, flow })
  }
  for (const chat of recentChats.value) {
    if (!chat.name && !(chat.message_count > 0)) continue
    const sub = chat.last_message || (chat.updated_at ? formatRelativeTime(chat.updated_at) : '')
    items.push({ type: 'chat', id: chat.id, name: chat.name, sub, updatedAt: chat.updated_at, chat })
  }
  return items
    .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
    .slice(0, isCompact.value ? 2 : 3)
})

function jumpKindLabel(item) {
  return { board: 'Board', flow: 'Flow', chat: 'Chat' }[item.type] || item.type
}

function jumpUntitledLabel(item) {
  if (item.type === 'flow') return 'Name this flow...'
  if (item.type === 'chat') return 'New chat'
  return 'Untitled board'
}

function openJumpItem(item) {
  if (item.type === 'board') openBoard(item.id)
  else if (item.type === 'flow') openFlow(item.flow)
  else openChat(item.chat)
}

function handleJumpContextMenu(event, item) {
  if (item.type === 'board') handleBoardContextMenu(event, item.board)
  else if (item.type === 'flow') handleFlowContextMenu(event, item.flow)
  else handleChatContextMenu(event, item.chat)
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
    requestFaceFocalPoints(recentChats.value.map((c) => c.recent_media?.[0]?.media_id))
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

    // Card art: the flow list endpoint doesn't aggregate output media, so pull
    // each flow's equations and derive outputs the same way FlowCard does.
    const results = await Promise.allSettled(
      recentFlows.value.map((flow) => listEquations(flow.id))
    )
    const next = new Map()
    results.forEach((result, index) => {
      if (result.status !== 'fulfilled') return
      const byKey = new Map()
      for (const eq of result.value) byKey.set(eq.equation_key, eq)
      next.set(recentFlows.value[index].id, computeFlowOutputs(byKey).map((o) => o.mediaId))
    })
    flowOutputMedia.value = next
    requestFaceFocalPoints([...next.values()].flatMap((ids) => ids.slice(0, 3)))
  } catch (err) {
    console.error('Failed to load recent flows:', err)
  }
}

function getFlowPreviewMediaIds(flowId) {
  return (flowOutputMedia.value.get(flowId) || []).slice(0, 3)
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
    requestFaceFocalPoints(
      [...next.values()].flatMap((detail) =>
        (detail?.sections || []).flatMap((s) => s.items || []).slice(0, 6).map((it) => mediaIdOf(it))
      )
    )
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
    .slice(0, 6)
}

// Tile width is computed from the item's aspect ratio against the fixed strip
// height (h-28 card art minus py-2 padding = 6rem). aspect-ratio CSS can't be
// used here: in a flex row the width resolves before the stretched height, so
// the tile collapses. Wide panoramas are capped at 16:9, object-cover crops.
function getPreviewTileStyle(item) {
  const width = Math.max(item?.width || 1, 1)
  const height = Math.max(item?.height || 1, 1)
  const ratio = Math.min(width / height, 16 / 9)
  return {
    width: `${(6 * ratio).toFixed(3)}rem`
  }
}

function isVideoFormat(fileFormat) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat)
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
  await Promise.all([loadRecentChats(), loadRecentMedia(), loadRecentBoards(), loadRecentFlows(), loadTools()])
  loaded.value = true
}

// Providers connect and tools appear asynchronously (login, funding, first
// sync) — often after this screen has already rendered behind the setup
// wizard. Reload tools on provider/tool change events so the launcher pills
// and first-run starter grid fill in as soon as tools exist.
let unsubscribeFromProviderChanges = null

onMounted(() => {
  setupResizeObserver()
  loadAll()
  checkAgentModels()
  checkPendingMedia()
  chatInputBoxRef.value?.focus()
  unsubscribeFromProviderChanges = subscribeToProviderChanges(() => loadTools())
})

onUnmounted(() => {
  cleanupResizeObserver()
  if (unsubscribeFromProviderChanges) {
    unsubscribeFromProviderChanges()
    unsubscribeFromProviderChanges = null
  }
})

onActivated(() => {
  setupResizeObserver()
  loadAll()
  checkAgentModels()
  checkPendingMedia()
  chatInputBoxRef.value?.focus()
})
</script>
