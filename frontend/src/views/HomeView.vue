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
      <!-- Fades in once the model check says which hero to show; recents and
           their artwork fill in below as they arrive. -->
      <div class="min-h-full flex flex-col items-center px-8 lg:px-16 compact:px-4" :class="heroReady ? 'opacity-100' : 'opacity-0'" style="transition: opacity 0.15s ease-in">

        <!-- Hero area — centered in space above content -->
        <div class="relative flex-1 flex flex-col items-center justify-center w-full pt-24 pb-16 compact:pt-12 compact:pb-12">
          <h1 class="relative font-brand text-[32px] compact:text-[26px] compact:leading-tight font-bold tracking-tight text-content mb-2 compact:mb-9 text-center">{{ projectId ? 'What shall we make?' : (greetingParts.pre + greetingParts.word + greetingParts.post) }}</h1>
          <!-- Scope feedback stays with the Home content. -->
          <p class="relative h-[20px] mb-10 text-sm text-content-muted compact:hidden">{{ projectId ? `In ${project.name || 'Untitled project'}` : '' }}</p>

          <div class="relative w-full max-w-[720px]">
            <!-- No chat model configured (deliberate opt-out): tools take the
                 hero slot instead of the composer, so home reads as the front
                 door to what works. The cutoff is one quiet footnote line.
                 A configured-but-broken model keeps the composer (and its
                 louder card) below — that user opted in and wants the remedy. -->
            <template v-if="showToolHero">
              <StarterToolGrid v-if="heroToolPicks.length > 0" :picks="heroToolPicks" @open="openToolById" />
              <div class="flex justify-center" :class="heroToolPicks.length > 0 ? 'mt-4' : ''">
                <router-link
                  :to="contextRoute('all-tools', projectId)"
                  class="px-3.5 py-1.5 rounded-full border border-edge-subtle coarse:inline-flex coarse:min-h-11 coarse:items-center text-[13px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle hover:border-edge transition-colors"
                >
                  All tools →
                </router-link>
              </div>
              <p class="mt-7 text-center text-xs text-content-muted">
                Chat is available once you
                <button
                  @click="openChatModelSettings"
                  class="font-medium text-accent-hi hover:text-accent transition-colors"
                >set up a chat model</button>.
              </p>
            </template>

            <div v-else class="rounded-lg shadow-lg shadow-black/20">
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
                <template #context-header>
                  <div class="px-4 pt-3 text-xs text-content-muted">{{ projectId ? `Working in ${project.name || 'Untitled project'}` : 'New chat · No project' }}</div>
                  <div v-if="newChatImageUnsupported" class="px-4 pt-2 text-xs text-amber-500">{{ newChatImageUnsupported }}</div>
                </template>
                <template #model-picker>
                  <ChatModelPicker
                    :project-id="projectId"
                    :model-slug="selectedNewChatModel"
                    @update:model-slug="selectedNewChatModel = $event"
                  />
                </template>
              </ChatInputBox>
            </div>

            <!-- Tool launchers docked to the prompt (recent tools, starter picks as cold-start fill) -->
            <div v-if="!showToolHero && !isFirstRun && launcherTools.length > 0" class="flex flex-wrap justify-center gap-2 mt-4 compact:hidden">
              <button
                v-for="tool in launcherTools"
                :key="tool.full_tool_id"
                @click="openToolById(tool.full_tool_id)"
                class="flex items-center gap-2 px-3 py-1.5 compact:gap-1.5 compact:px-2.5 compact:py-1 rounded-md bg-overlay-faint hover:bg-overlay-subtle transition-colors cursor-pointer"
                :title="tool.name"
              >
                <div class="w-5 h-5 compact:w-4 compact:h-4 flex-shrink-0 text-content-secondary"><ToolIcon :tool="tool" bare :ring="false" /></div>
                <span class="text-[13px] compact:text-[12px] font-medium text-content max-w-[180px] compact:max-w-[128px] truncate">{{ tool.name }}</span>
                <span class="text-[11px] compact:text-[10px]" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ providerLabel(tool) }}</span>
              </button>
              <router-link
                :to="contextRoute('all-tools', projectId)"
                class="flex items-center px-3 py-1.5 compact:px-2.5 compact:py-1 rounded-md text-[13px] compact:text-[12px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
              >
                All tools →
              </router-link>
            </div>
          </div>

          <!-- First run: recommended starting points instead of empty sections.
               Skipped when no chat model is configured — the hero grid above
               already fills this role. -->
          <div v-if="!showToolHero && isFirstRun && starterTools.length > 0" class="relative w-full max-w-[720px] mt-12">
            <div class="flex items-center gap-4 mb-4">
              <div class="h-px flex-1 bg-edge-subtle"></div>
              <span class="text-xs font-semibold text-content-secondary">Or start with a tool</span>
              <div class="h-px flex-1 bg-edge-subtle"></div>
            </div>
            <StarterToolGrid :picks="starterTools" @open="openToolById" />
            <div class="flex justify-center mt-4">
              <router-link
                :to="contextRoute('all-tools', projectId)"
                class="px-3.5 py-1.5 rounded-full border border-edge-subtle coarse:inline-flex coarse:min-h-11 coarse:items-center text-[13px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle hover:border-edge transition-colors"
              >
                All tools →
              </router-link>
            </div>
          </div>
        </div>

        <!-- Content sections -->
        <div ref="contentRef" class="w-full max-w-[960px] pb-12 compact:pb-20 space-y-10" :data-recents-state="recentsState">

          <p v-if="failedRecentsLabel" class="text-center text-xs text-content-muted" data-recents-error>
            Couldn't load recent {{ failedRecentsLabel }}.
            <Button variant="link" size="sm" class="coarse:min-h-11" @click="refreshHome({ force: true })">Try again</Button>
          </p>

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
                    v-else-if="item.type === 'flow' && getFlowPreviewMedia(item.id).length > 0"
                    class="flex w-full h-full gap-0.5"
                  >
                    <div
                      v-for="media in getFlowPreviewMedia(item.id)"
                      :key="`${item.id}-${media.media_id}`"
                      class="flex-1 min-w-0 h-full overflow-hidden"
                    >
                      <MediaImage
                        :media-id="media.media_id"
                        :file-hash="media.file_hash || undefined"
                        :thumbnail="true"
                        :thumbnail-size="256"
                        thumbnail-mode="fit"
                        :object-position="faceObjectPosition(media.media_id)"
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
              <h2 class="text-xs font-semibold text-content-secondary">{{ projectId ? 'Fresh from this project' : 'Recent assets' }}</h2>
              <router-link :to="contextRoute('browse', projectId)" class="text-xs text-content-muted hover:text-content-secondary transition-colors coarse:inline-flex coarse:min-h-11 coarse:min-w-11 coarse:items-center coarse:px-2">
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

    <MediaContextMenu @refresh="loadRecentMedia()" />
  </div>
</template>

<script setup>
import { useEntityMove } from '../composables/useEntityMove'
import { fetchScopedJson } from '../utils/scopedList'
import { fetchHomeRecents } from '../utils/homeRecents'
import { useViewport } from '../composables/useViewport'
import { ref, computed, onMounted, onActivated, onDeactivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MediaContextMenu, MediaImage } from '../components/media'
import EntityIcon from '../components/EntityIcon.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import ChatModelPicker from '../components/chat/ChatModelPicker.vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import FlowStatusPill from '../components/flow/FlowStatusPill.vue'
import ToolIcon from '../components/tools/ToolIcon.vue'
import StarterToolGrid from '../components/StarterToolGrid.vue'
import { useSlideshow } from '../composables/useSlideshow'
import { useProvidersApi } from '../composables/useProvidersApi'
import { recentEntities } from '../composables/useRecentEntities'
import { pickStarterTools, toolTaskTypes } from '../utils/starterTools'
import { isStimmaCloudTool, toolProviderDisplayName } from '../utils/stimmaCloud'
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
import { contextRoute } from '../utils/workingContext'
import { makeStorageKey } from '../utils/storageKeys'
import { modelRejectsImageInput } from '../utils/settingsReadiness'
import { createScopedLoad, scopeKey } from '../utils/scopedLoad'
import { withReadDeadline } from '../utils/readDeadline'
import { getBackendOrigin } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { useWebSocket } from '../composables/useWebSocket'
import { PROJECT_ASSETS_CHANGED_EVENT } from '../utils/projectScope'
import Button from '../components/ui/Button.vue'

const { allowsAutofocus } = useViewport()

const props = defineProps({ project: { type: Object, default: null } })
const projectId = computed(() => props.project?.id ?? null)
const router = useRouter()
const { getBoards, getBoard, addMediaToBoard, deleteBoard, restoreBoard, updateBoard } = useMediaApi()
// Face-aware framing for "Jump back in" cover art (see useFaceFocalPoints).
const { request: requestFaceFocalPoints, positionOf: faceObjectPosition } = useFaceFocalPoints()
const { fetchAssets, addToBoard: addAssetsToBoard } = useAssetApi()
const { listFlows, listEquations, updateFlow, deleteFlow, restoreFlow } = useFlowsApi()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()
const { agentModelUnavailable, llmUnconfigured, checkAgentModels } = useAgentModelAvailability()
const { globalDefault, roleDefaults, getSelectableModel } = useAvailableModels()
const { fetchProvidersAndTools, subscribeToProviderChanges } = useProvidersApi()

const chatInputBoxRef = ref(null)
const contentRef = ref(null)
const draftKey = makeStorageKey('home_draft', projectId.value == null ? 'library' : String(projectId.value))
let restoredDraft = {}
try { restoredDraft = JSON.parse(sessionStorage.getItem(draftKey) || '{}') } catch {}
const inputText = ref(restoredDraft.text || '')
const inputAttachments = ref(restoredDraft.attachments || [])
const selectedNewChatModel = ref(restoredDraft.model || null)
watch([inputText, inputAttachments, selectedNewChatModel], () => {
  try { sessionStorage.setItem(draftKey, JSON.stringify({ text: inputText.value, attachments: inputAttachments.value, model: selectedNewChatModel.value })) } catch {}
}, { deep: true })
const selectedNewChatModelInfo = computed(() => {
  const slug = selectedNewChatModel.value || roleDefaults.value?.chat?.project || globalDefault.value
  return getSelectableModel(slug)
})
const newChatImageUnsupported = computed(() => {
  if (inputAttachments.value.length === 0) return ''
  const model = selectedNewChatModelInfo.value
  if (!model || !modelRejectsImageInput(model)) return ''
  return `${model.name} can't use images. Remove the image or choose another model.`
})
const submitting = ref(false)
// No chat model configured puts tools in the hero slot. A composer the user
// has already typed into stays put when that answer arrives late.
const composerDirty = computed(() => inputText.value.trim() !== '' || inputAttachments.value.length > 0)
const showToolHero = computed(() => llmUnconfigured.value && !composerDirty.value)
const recentChats = ref([])
const recentMedia = ref([])
const recentBoards = ref([])
const recentFlows = ref([])
const flowOutputMedia = ref(new Map()) // flow_id -> [{ media_id, file_hash? }, ...]
const boardDetails = ref(new Map())
// The scope has boards, flows, or chats even though none made a card (the
// compact read skips empty ones), so this is not a first run.
const scopeHasEntities = ref(false)
// 'loading' until the recent chats/boards/flows/assets lists settle, then
// 'ready', or 'error' when any of them failed. Artwork is not part of it.
const recentsState = ref('loading')
// Which recents lists failed in the last load ('chats', 'assets', ...). Shown
// as a quiet retry line next to whatever did load.
const failedRecents = ref([])
const failedRecentsLabel = computed(() => {
  const names = failedRecents.value
  if (names.length <= 1) return names[0] || ''
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
})
// The model check decides which hero (composer or tool grid) to show. The
// page is revealed when it settles, when recents settle, or after a short
// wait, whichever is first; until the check answers, the composer shows.
const heroReady = ref(false)
const HERO_WAIT_MS = 1500
const dragOverBoardId = ref(null)
const contentWidth = ref(960)

const isCompact = computed(() => contentWidth.value < 700)

const mediaColumns = computed(() => {
  if (isCompact.value) return 3
  return 6
})

// Phones get two rows so the home screen has enough below the fold to
// scroll a little; every other home screen does, and a page that fits
// exactly reads as stuck.
const mediaRows = computed(() => (isCompact.value ? 2 : 1))

const visibleMedia = computed(() => recentMedia.value.slice(0, mediaColumns.value * mediaRows.value))

function hasChatMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

// ==================== Greeting ====================

// True only after the first load with nothing to show: no chats, boards,
// flows, or library media — i.e. a fresh install right after onboarding.
const isFirstRun = computed(() =>
  recentsState.value === 'ready'
  && !scopeHasEntities.value
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

// The tool catalog belongs to the server and profile (not the project) and
// has its own load policy, so a slow catalog never holds up recents.
const toolLoads = createScopedLoad({ freshMs: 30_000 })

function toolScope() {
  return scopeKey(getBackendOrigin() || window.location.origin, getCurrentProfileId())
}

function loadTools({ force = false } = {}) {
  const key = toolScope()
  // Never show one profile's tools under another.
  if (toolLoads.activeKey !== null && toolLoads.activeKey !== key) {
    toolsList.value = []
    recentToolEntities.value = []
  }
  return toolLoads.request(key, async (isCurrent) => {
    try {
      // The shared catalog, not a forced read: a tool or provider change has
      // already cleared it, and the sidebar reacting to the same change
      // joins this read instead of starting its own.
      const { tools } = await withReadDeadline(signal => fetchProvidersAndTools(false, { signal }))
      if (!isCurrent()) return
      toolsList.value = tools.filter(t => !t.metadata?.agent_only)
      return true
    } catch (err) {
      console.error('Failed to load tools:', err)
      return false
    } finally {
      if (isCurrent()) recentToolEntities.value = recentEntities(60).filter(e => e.type === 'tool')
    }
  }, { force })
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

function openToolById(fullToolId) {
  router.push({ name: 'tool', params: { fullToolId }, query: { project_id: projectId.value == null ? '0' : String(projectId.value) } })
}

function openChatModelSettings() {
  window.dispatchEvent(new CustomEvent('open-settings', { detail: 'ai-services' }))
}

// Hero grid shown instead of the composer when no chat model is configured:
// recently used tools first, starter picks as fill, shaped like starter picks
// ({tool, taskType}) so the grid can badge the task. Recents may not map to a
// starter task; an empty taskType just omits the badge.
const heroToolPicks = computed(() => {
  const picks = []
  const seen = new Set()
  const add = (tool, taskType) => {
    const nameKey = `name:${(tool.name || '').toLowerCase().trim()}`
    if (seen.has(tool.full_tool_id) || seen.has(nameKey)) return
    seen.add(tool.full_tool_id)
    seen.add(nameKey)
    picks.push({ tool, taskType })
  }
  const byId = new Map(availableTools.value.map(t => [t.full_tool_id, t]))
  for (const entity of recentToolEntities.value) {
    if (picks.length >= 4) break
    const tool = byId.get(entity.id)
    if (tool) add(tool, toolTaskTypes(tool)[0] || '')
  }
  for (const pick of starterTools.value) {
    if (picks.length >= 4) break
    add(pick.tool, pick.taskType)
  }
  return picks
})

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
  if (resizeObserver || !contentRef.value) return
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

// Each list loader takes the scope guard of the load that started it and
// drops its result once a newer scope has taken over, so a late response
// can't put another project's or profile's items on screen. They resolve
// false on failure. Card artwork loads afterwards and never blocks the list.

async function loadRecentChats(isCurrent = homeLoads.guard()) {
  try {
    // The top level shows only chats with no project.
    const data = await withReadDeadline(signal => fetchScopedJson('/api/chats/previews', new URLSearchParams({ page: '1', page_size: '6' }), projectId.value, { signal }))
    if (!isCurrent()) return true
    recentChats.value = data.items || []
    requestFaceFocalPoints(recentChats.value.map((c) => c.recent_media?.[0]?.media_id))
    return true
  } catch (err) {
    console.error('Failed to load recent chats:', err)
    return false
  }
}

async function loadRecentFlows(isCurrent = homeLoads.guard()) {
  try {
    const all = await withReadDeadline(signal => listFlows(projectId.value == null ? {} : { project_id: projectId.value }, { signal }))
    if (!isCurrent()) return true
    recentFlows.value = [...all]
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      .slice(0, 6)
    void loadFlowArtwork(recentFlows.value, isCurrent)
    return true
  } catch (err) {
    console.error('Failed to load recent flows:', err)
    return false
  }
}

// Card art: the flow list endpoint doesn't aggregate output media, so pull
// each flow's equations and derive outputs the same way FlowCard does.
async function loadFlowArtwork(flows, isCurrent) {
  const results = await Promise.allSettled(flows.map((flow) => withReadDeadline(signal => listEquations(flow.id, {}, { signal }))))
  if (!isCurrent()) return
  const next = new Map()
  results.forEach((result, index) => {
    if (result.status !== 'fulfilled') return
    const byKey = new Map()
    for (const eq of result.value) byKey.set(eq.equation_key, eq)
    next.set(flows[index].id, computeFlowOutputs(byKey).map((o) => ({ media_id: o.mediaId })))
  })
  flowOutputMedia.value = next
  requestFaceFocalPoints([...next.values()].flatMap((media) => media.slice(0, 3).map((m) => m.media_id)))
}

function getFlowPreviewMedia(flowId) {
  return (flowOutputMedia.value.get(flowId) || []).slice(0, 3)
}

// ==================== Compact recents ====================

// Cards "Jump back in" can show at once (three wide, two on phones).
const JUMP_BACK_IN_LIMIT = 3
// Servers (by origin) that predate the compact read; Home uses the general
// lists there. Forgotten when the connection drops, since a server can be
// updated while it is away.
const compactRecentsUnsupported = new Set()

function backendKey() {
  return getBackendOrigin() || window.location.origin
}

// The newest boards, flows, and chats with just their card artwork, chosen
// by the server. Resolves null when the server lacks this read.
async function loadCompactRecents(isCurrent) {
  try {
    const data = await withReadDeadline(signal => fetchHomeRecents(projectId.value, { limit: JUMP_BACK_IN_LIMIT, signal }))
    if (data === null) return null
    if (!isCurrent()) return true
    const boards = []
    const flows = []
    const chats = []
    const flowMedia = new Map()
    for (const item of data.items) {
      if (item.type === 'board' && item.board) boards.push(item.board)
      else if (item.type === 'flow' && item.flow) {
        flows.push(item.flow)
        flowMedia.set(item.flow.id, item.flow.preview_media || [])
      } else if (item.type === 'chat' && item.chat) chats.push(item.chat)
    }
    recentBoards.value = boards
    recentFlows.value = flows
    recentChats.value = chats
    boardDetails.value = new Map()
    flowOutputMedia.value = flowMedia
    scopeHasEntities.value = !!data.has_entities
    requestFaceFocalPoints([
      ...boards.flatMap((board) => (board.preview_items || []).map((it) => mediaIdOf(it))),
      ...[...flowMedia.values()].flatMap((media) => media.map((m) => m.media_id)),
      ...chats.map((chat) => chat.recent_media?.[0]?.media_id),
    ])
    return true
  } catch (err) {
    console.error('Failed to load recents:', err)
    return false
  }
}

// Loads the "Jump back in" lists and resolves the names of any that failed.
async function loadJumpBackIn(isCurrent) {
  const origin = backendKey()
  if (!compactRecentsUnsupported.has(origin)) {
    const loaded = await loadCompactRecents(isCurrent)
    if (loaded !== null) return loaded ? [] : ['chats', 'boards', 'flows']
    compactRecentsUnsupported.add(origin)
  }
  if (isCurrent()) scopeHasEntities.value = false
  const names = ['chats', 'boards', 'flows']
  const results = await Promise.all([loadRecentChats(isCurrent), loadRecentBoards(isCurrent), loadRecentFlows(isCurrent)])
  return names.filter((_, index) => !results[index])
}

// Reload the cards after this window changed one of them.
function reloadJumpBackIn(kind) {
  if (!compactRecentsUnsupported.has(backendKey())) return loadJumpBackIn(homeLoads.guard())
  if (kind === 'board') return loadRecentBoards()
  if (kind === 'flow') return loadRecentFlows()
  return loadRecentChats()
}

async function loadRecentMedia(isCurrent = homeLoads.guard()) {
  try {
    // Top-level Home shows top-level assets, like the top-level browser.
    const response = await withReadDeadline(signal => fetchAssets({ sort_by: 'created_desc', page: 1, page_size: 16, project_id: projectId.value ?? undefined, scope: projectId.value == null ? 'unfiled' : undefined }, { signal }))
    if (!isCurrent()) return true
    recentMedia.value = response.items || []
    return true
  } catch (err) {
    console.error('Failed to load recent media:', err)
    return false
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
      body: JSON.stringify({ model_slug: selectedNewChatModel.value, project_id: projectId.value })
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

async function loadRecentBoards(isCurrent = homeLoads.guard()) {
  try {
    const boards = await withReadDeadline(signal => getBoards(projectId.value, { signal }))
    if (!isCurrent()) return true
    recentBoards.value = boards.slice(0, 6)
    void loadBoardArtwork(recentBoards.value, isCurrent)
    return true
  } catch (err) {
    console.error('Failed to load boards:', err)
    return false
  }
}

async function loadBoardArtwork(boards, isCurrent) {
  const results = await Promise.allSettled(boards.map((board) => withReadDeadline(signal => getBoard(board.id, { signal }))))
  if (!isCurrent()) return
  const next = new Map()
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') next.set(boards[index].id, result.value)
  })
  boardDetails.value = next
  requestFaceFocalPoints(
    [...next.values()].flatMap((detail) =>
      (detail?.sections || []).flatMap((s) => s.items || []).slice(0, 6).map((it) => mediaIdOf(it))
    )
  )
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

const moveEntityToProject = useEntityMove()
async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  if (!['board', 'flow', 'chat'].includes(entityType)) return
  if (!await moveEntityToProject(entityType, entityId, projectId)) return
  await reloadJumpBackIn(entityType)
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
    await reloadJumpBackIn('board')
  } catch (err) {
    console.error('Failed to add media to board:', err)
  }
}

function getBoardPreviewItems(board) {
  if (board.preview_items) return board.preview_items.slice(0, 6)
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
  const ids = consumePendingMedia('home', null, projectId.value)
  if (!ids) return
  for (const id of ids) {
    if (!inputAttachments.value.some(a => a.media_id === id)) {
      inputAttachments.value = [...inputAttachments.value, { media_id: id }]
    }
  }
}

watch(pendingMedia, () => checkPendingMedia(), { flush: 'post' })

// ==================== Load policy ====================

// Mount, reactivation, retry and scope changes all go through refreshHome.
// One scope is read at most once at a time and is reused while fresh; server
// change events mark it stale so the next visit reloads. Home does not
// reload live while it is on screen.
const HOME_FRESH_MS = 30_000
const homeLoads = createScopedLoad({ freshMs: HOME_FRESH_MS })
// Every server broadcast that can change a chat preview (name, count,
// snippet, cover), a board or flow card, or the recent-assets strip.
const HOME_CHANGE_EVENTS = [
  'chat_created', 'chat_updated', 'chat_deleted', 'chat_restored', 'chat_cleared',
  'chat_item_created', 'chat_item_updated', 'chat_item_deleted',
  'board_created', 'board_updated', 'board_deleted', 'board_restored', 'board_items_changed',
  'board_section_created', 'board_section_updated', 'board_section_deleted',
  'flow_created', 'flow_updated', 'flow_deleted', 'flow_restored', 'flow_equation_updated',
  'asset_created', 'asset_deleted', 'asset_trashed', 'assets_trashed', 'assets_restored',
  'assets_permanently_deleted', 'asset_identities_deleted', 'asset_current_revision_changed', 'assets_updated',
  'media_added', 'media_updated', 'media_restored', 'media_bulk_restored', 'media_permanently_deleted',
  'project_assets_changed', 'trash_emptied',
]
// Changes this window makes itself, announced ahead of the server broadcast.
const HOME_LOCAL_CHANGE_EVENTS = [PROJECT_ASSETS_CHANGED_EVENT]

function homeScope() {
  return scopeKey(getBackendOrigin() || window.location.origin, getCurrentProfileId(), projectId.value)
}

function resetHomeData() {
  recentChats.value = []
  recentMedia.value = []
  recentBoards.value = []
  recentFlows.value = []
  flowOutputMedia.value = new Map()
  boardDetails.value = new Map()
  scopeHasEntities.value = false
  recentsState.value = 'loading'
  failedRecents.value = []
}

function refreshHome({ force = false } = {}) {
  const key = homeScope()
  // Never show one scope's items while another's are loading.
  if (homeLoads.activeKey !== null && homeLoads.activeKey !== key) resetHomeData()
  return homeLoads.request(key, async (isCurrent) => {
    if (recentsState.value === 'error') recentsState.value = 'loading'
    const [failedLists, assetsLoaded] = await Promise.all([loadJumpBackIn(isCurrent), loadRecentMedia(isCurrent)])
    const failed = assetsLoaded ? failedLists : [...failedLists, 'assets']
    if (isCurrent()) {
      failedRecents.value = failed
      recentsState.value = failed.length === 0 ? 'ready' : 'error'
    }
    return failed.length === 0
  }, { force })
}

async function checkModels() {
  try {
    await checkAgentModels(projectId.value)
  } finally {
    heroReady.value = true
  }
}

// Bound the wait for the model check: a stalled request must not keep the
// page hidden once there is something to show.
let heroTimer = null
function revealHeroSoon() {
  if (heroReady.value || heroTimer) return
  heroTimer = setTimeout(() => {
    heroTimer = null
    heroReady.value = true
  }, HERO_WAIT_MS)
}
watch(recentsState, (state) => {
  if (state !== 'loading') heroReady.value = true
})

// Providers connect and tools appear asynchronously (login, funding, first
// sync) — often after this screen has already rendered behind the setup
// wizard. Reload tools on provider/tool change events so the launcher pills
// and first-run starter grid fill in as soon as tools exist.
let unsubscribeFromProviderChanges = null
const { on: onServerEvent } = useWebSocket()
const unsubscribeFromServerEvents = []

// Under KeepAlive the initial mount fires both onMounted and onActivated;
// the active flag makes them one entry.
let active = false
function activate() {
  if (active) return
  active = true
  setupResizeObserver()
  void refreshHome()
  void loadTools()
  recentToolEntities.value = recentEntities(60).filter(e => e.type === 'tool')
  void checkModels()
  revealHeroSoon()
  checkPendingMedia()
  if (allowsAutofocus.value) chatInputBoxRef.value?.focus()
}

function handleProfileChanged() {
  if (!active) return
  void refreshHome()
  void loadTools()
  void checkModels()
}

function invalidateHome() {
  homeLoads.invalidate()
}

// Events can be missed only while the socket is down, so a reconnect after a
// disconnect invalidates; the first connect does not.
let socketWasDown = false

watch(projectId, () => {
  if (!active) return
  void refreshHome()
  void checkModels()
})

onMounted(() => {
  activate()
  unsubscribeFromProviderChanges = subscribeToProviderChanges(() => loadTools({ force: true }))
  for (const event of HOME_CHANGE_EVENTS) {
    unsubscribeFromServerEvents.push(onServerEvent(event, invalidateHome))
  }
  unsubscribeFromServerEvents.push(onServerEvent('websocket_disconnected', () => {
    socketWasDown = true
    compactRecentsUnsupported.clear()
    invalidateHome()
  }))
  // Retry right away only when the last load failed; otherwise the next
  // visit reloads.
  unsubscribeFromServerEvents.push(onServerEvent('websocket_reconnected', () => {
    if (socketWasDown) invalidateHome()
    socketWasDown = false
    if (active && recentsState.value === 'error') void refreshHome()
  }))
  for (const event of HOME_LOCAL_CHANGE_EVENTS) window.addEventListener(event, invalidateHome)
  window.addEventListener('stimma:transport-resumed', invalidateHome)
  window.addEventListener('profile-changed', handleProfileChanged)
})

onActivated(activate)

onDeactivated(() => {
  active = false
})

onUnmounted(() => {
  active = false
  cleanupResizeObserver()
  if (unsubscribeFromProviderChanges) {
    unsubscribeFromProviderChanges()
    unsubscribeFromProviderChanges = null
  }
  for (const unsubscribe of unsubscribeFromServerEvents.splice(0)) unsubscribe()
  for (const event of HOME_LOCAL_CHANGE_EVENTS) window.removeEventListener(event, invalidateHome)
  window.removeEventListener('stimma:transport-resumed', invalidateHome)
  if (heroTimer) clearTimeout(heroTimer)
  heroTimer = null
  window.removeEventListener('profile-changed', handleProfileChanged)
})
</script>
