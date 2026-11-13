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
    <div v-else ref="scrollerRef" class="h-full overflow-y-auto custom-scrollbar">
      <!-- Fades in once the model check says which hero to show; recents and
           their artwork fill in below as they arrive. -->
      <div class="min-h-full flex flex-col items-center px-page" :class="heroReady ? 'opacity-100' : 'opacity-0'" style="transition: opacity 0.15s ease-in">

        <!-- Hero area — centered in space above content -->
        <!-- Spacing scale: top offset pt-20 (compact pt-8), hero to composer
             mb-8 (compact mb-6), composer to content pb-14 (compact pb-10).
             The hero only floats in spare height when there is nothing below it. -->
        <div class="relative flex flex-col items-center justify-center w-full pt-[var(--hub-top)] pb-[var(--hub-content-gap)]" :class="hasBelowHero ? 'flex-none' : 'flex-1'">
          <div class="relative mb-[var(--hub-hero-gap)] text-center">
            <h1 class="font-brand text-[length:var(--hub-hero-size)] compact:leading-tight font-medium tracking-tight text-content">{{ projectId ? 'What shall we make?' : (greetingParts.pre + greetingParts.word + greetingParts.post) }}</h1>
            <!-- Scope feedback stays with the Home content. -->
            <p v-if="projectId" class="mt-1.5 text-sm text-content-muted compact:hidden">{{ `In ${project.name || 'Untitled project'}` }}</p>
          </div>

          <div class="relative w-full max-w-[var(--hub-column)]">
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

            <div v-else class="rounded-lg">
              <ChatInputBox
                ref="chatInputBoxRef"
                v-model="inputText"
                :attachments="inputAttachments"
                :rows="1"
                :disabled="submitting"
                :agent-unavailable="agentModelUnavailable"
                                @update:attachments="inputAttachments = $event"
                @submit="submitMessage"
              >
                <template #context-header>
                  <!-- Inside a project the page already says where you are (heading, header). -->
                  <div v-if="newChatImageUnsupported" class="px-4 pt-2 text-xs text-amber-500">{{ newChatImageUnsupported }}</div>
                </template>
                <template #model-picker>
                  <ChatModelPicker
                    :project-id="projectId"
                    :model-slug="selectedNewChatModel"
                    @update:model-slug="selectedNewChatModel = $event"
                  />
                  <!-- Where the message lands, beside the model rather than on a line of its own,
                       so the empty composer is as tall as a project's. -->
                  <template v-if="!projectId">
                    <span class="mx-2 h-3 w-px shrink-0 bg-edge-subtle" aria-hidden="true"></span>
                    <span class="min-w-0 truncate text-[11px] text-content-muted" data-composer-context><span class="narrow:hidden">New chat · </span>No project</span>
                  </template>
                </template>
              </ChatInputBox>
            </div>

            <!-- Tool launchers docked to the prompt (recent tools, starter picks as cold-start fill) -->
            <div v-if="!showToolHero && !isFirstRun && launcherTools.length > 0" class="flex flex-wrap items-center justify-start gap-2 mt-4 compact:mt-2 compact:flex-nowrap compact:gap-1">
              <!-- On compact the shortcuts scroll and fade out under a soft trailing edge; All tools stays beside them, never inside the scroll. -->
              <div class="contents compact:flex compact:min-w-0 compact:flex-initial compact:gap-1.5 compact:-ml-page compact:pl-page compact:scroll-pl-page compact:pr-6 compact:overflow-x-auto compact:[mask-image:linear-gradient(to_right,#000_calc(100%-24px),transparent)] compact:overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <button
                  v-for="tool in launcherTools"
                  :key="tool.full_tool_id"
                  @click="openToolById(tool.full_tool_id)"
                  class="flex shrink-0 items-center gap-2 px-3 py-1.5 compact:gap-1.5 compact:px-2.5 compact:py-1 coarse:min-h-11 rounded-md bg-overlay-faint hover:bg-overlay-subtle transition-colors cursor-pointer"
                  :title="`${tool.name} · ${providerLabel(tool)}`"
                >
                  <div class="w-5 h-5 compact:w-4 compact:h-4 flex-shrink-0 text-content-secondary"><ToolIcon :tool="tool" bare :ring="false" /></div>
                  <span class="whitespace-nowrap text-[13px] compact:text-[12px] font-medium compact:font-normal text-content compact:text-content-secondary max-w-[180px] compact:max-w-none truncate">{{ tool.name }}</span>
                  <!-- A tool is always named with its provider. -->
                  <span class="whitespace-nowrap text-[11px] compact:text-[10px]" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ providerLabel(tool) }}</span>
                </button>
              </div>
              <router-link
                :to="contextRoute('all-tools', projectId)"
                class="flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 compact:px-2 compact:py-1 coarse:min-h-11 rounded-md text-[13px] compact:text-[12px] text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
              >
                All tools →
              </router-link>
            </div>
          </div>

          <!-- First run: recommended starting points instead of empty sections.
               Skipped when no chat model is configured — the hero grid above
               already fills this role. -->
          <div v-if="!showToolHero && isFirstRun && starterTools.length > 0" class="relative w-full max-w-[var(--hub-column)] mt-12">
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
        <div ref="contentRef" class="w-full max-w-[var(--hub-column)] pb-12 compact:pb-20 space-y-section" :data-recents-state="recentsState">

          <p v-if="failedRecentsLabel" class="text-center text-xs text-content-muted" data-recents-error>
            Couldn't load recent {{ failedRecentsLabel }}.
            <Button variant="link" size="sm" class="coarse:min-h-11" @click="refreshHome({ force: true })">Try again</Button>
          </p>

          <!-- Jump back in: collections, flows, and chats merged into one recency row -->
          <div v-if="jumpBackIn.length > 0">
            <div class="mb-2 flex items-center justify-between">
              <h2 class="text-xs font-semibold text-content-secondary">Jump back in</h2>
            </div>
            <div data-jump-grid class="grid" :class="jumpColumns === 1 ? 'grid-cols-1 divide-y divide-edge-subtle' : jumpColumns === 2 ? 'grid-cols-2 gap-3' : 'grid-cols-3 gap-3'">
              <button
                v-for="item in jumpBackIn"
                :key="`${item.type}-${item.id}`"
                @click="openJumpItem(item)"
                @contextmenu="handleJumpContextMenu($event, item)"
                @dragover.prevent="item.type === 'collection' && (dragOverCollectionId = item.id)"
                @dragleave="item.type === 'collection' && dragOverCollectionId === item.id && (dragOverCollectionId = null)"
                @drop.prevent="item.type === 'collection' && handleCollectionDrop(item.id, $event)"
                class="group flex min-w-0 w-full rounded-media text-left bg-transparent transition-colors cursor-pointer"
                :class="[jumpColumns === 1 ? 'flex-row items-center gap-3 py-3 hover:bg-overlay-subtle' : 'flex-col max-w-[360px]', item.type === 'collection' && dragOverCollectionId === item.id
                  ? 'ring-1 ring-accent/50 bg-accent/10'
                  : '']"
              >
                <!-- Art -->
                <div data-jump-cover class="relative shrink-0 overflow-hidden rounded-media transition-opacity group-hover:opacity-85" :class="[jumpColumns === 1 ? 'w-20 h-20' : 'w-full aspect-[3/2]', jumpHasArt(item) ? 'bg-matte' : 'bg-surface-raised']">
                  <!-- Collection: filmstrip of tiles at natural aspect, full strip
                       height, left-aligned on matte with 2px media-grid
                       gutters. Widths follow each item's aspect ratio so
                       sparse collections read as tiles on a shelf. -->
                  <div
                    v-if="item.type === 'collection' && getCollectionPreviewItems(item.collection).length > 0"
                    class="absolute inset-0 overflow-hidden p-0.5"
                  >
                    <div class="flex h-full gap-0.5">
                      <div
                        v-for="(previewItem, index) in getCollectionPreviewItems(item.collection)"
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
                          :thumbnail="jumpImageThumbnailSize(mediaIdOf(previewItem)) <= 1024"
                          :thumbnail-size="jumpImageThumbnailSize(mediaIdOf(previewItem))"
                          @load="rememberJumpAspect(mediaIdOf(previewItem), $event)"
                          thumbnail-mode="fit"
                          :object-position="faceObjectPosition(mediaIdOf(previewItem))"
                          :draggable="false"
                          :enable-context-menu="false"
                          background-class="bg-matte"
                          container-class="w-full h-full"
                          class="w-full h-full object-cover"
                        />
                      </div>
                    </div>
                  </div>
                  <!-- Flow: filmstrip of surfaced output media -->
                  <div
                    v-else-if="item.type === 'flow' && getFlowPreviewMedia(item.id).length > 0"
                    class="absolute inset-0 flex gap-0.5"
                  >
                    <div
                      v-for="media in getFlowPreviewMedia(item.id)"
                      :key="`${item.id}-${media.media_id}`"
                      class="flex-1 min-w-0 h-full overflow-hidden"
                    >
                      <MediaImage
                        :media-id="media.media_id"
                        :file-hash="media.file_hash || undefined"
                        :thumbnail="jumpImageThumbnailSize(media.media_id) <= 1024"
                        :thumbnail-size="jumpImageThumbnailSize(media.media_id)"
                        @load="rememberJumpAspect(media.media_id, $event)"
                        thumbnail-mode="fit"
                        :object-position="faceObjectPosition(media.media_id)"
                        :draggable="false"
                        :enable-context-menu="false"
                        background-class="bg-matte"
                        container-class="w-full h-full"
                        class="w-full h-full object-cover"
                      />
                    </div>
                  </div>
                  <div v-else-if="item.type === 'chat' && hasChatMedia(item.chat)" class="absolute inset-0">
                    <!-- Chat whose latest media is a set: drawn from its members -->
                    <SetStackPreview
                      v-if="chatCoverIsSet(item.chat)"
                      :media-id="item.chat.recent_media[0].media_id"
                      :thumbnail-size="jumpThumbnailSize"
                    />
                    <!-- Chat: latest media as cover -->
                    <MediaImage
                      v-else
                      :media-id="item.chat.recent_media[0].media_id"
                      :file-hash="item.chat.recent_media[0].file_hash"
                      :thumbnail="jumpImageThumbnailSize(item.chat.recent_media[0].media_id) <= 1024"
                      :thumbnail-size="jumpImageThumbnailSize(item.chat.recent_media[0].media_id)"
                      @load="rememberJumpAspect(item.chat.recent_media[0].media_id, $event)"
                      thumbnail-mode="fit"
                      :object-position="faceObjectPosition(item.chat.recent_media[0].media_id)"
                      :draggable="false"
                      :enable-context-menu="false"
                      background-class="bg-matte"
                      container-class="w-full h-full"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <!-- No art: the raised tile with the type's glyph. -->
                  <div v-if="!jumpHasArt(item)" class="absolute inset-0 flex items-center justify-center">
                    <EntityIcon :type="item.type" size="md" class="!h-5 !w-5 !border-0 !bg-transparent !text-content-tertiary" />
                  </div>
                </div>
                <!-- Body -->
                <div class="min-w-0" :class="jumpColumns === 1 ? 'flex-1' : 'w-full py-3'">
                  <!-- In a row the type label rides the preview line instead of costing a line of its own. -->
                  <div v-if="jumpKindsMixed && jumpColumns > 1" class="text-[11px] text-content-muted">{{ jumpKindLabel(item) }}</div>
                  <div class="text-sm font-medium" :class="[item.name ? 'text-content' : 'text-content-muted italic', jumpColumns === 1 ? 'line-clamp-2' : 'truncate', jumpKindsMixed && jumpColumns > 1 ? 'mt-1' : '']">
                    {{ item.name || jumpUntitledLabel(item) }}
                  </div>
                  <div class="flex items-baseline gap-1.5 min-w-0 mt-0.5">
                    <span v-if="jumpKindsMixed && jumpColumns === 1" class="shrink-0 text-[11px] text-content-muted">{{ jumpKindLabel(item) }}<span class="ml-1.5" aria-hidden="true">·</span></span>
                    <FlowStatusPill
                      v-if="item.type === 'flow'"
                      :flow-id="item.id"
                      show-pending
                      text-class="truncate text-xs text-content-muted"
                      class="min-w-0"
                    />
                    <div
                      v-else
                      class="text-xs truncate min-w-0"
                      :class="item.type === 'collection' ? 'font-mono tabular-nums text-content-tertiary' : 'text-content-muted'"
                    >{{ item.sub }}</div>
                  </div>
                </div>
              </button>
            </div>
          </div>

          <!-- Library strip -->
          <div v-if="recentMedia.length > 0">
            <div class="mb-2 flex items-center justify-between">
              <h2 class="text-xs font-semibold text-content-secondary">{{ projectId ? 'Fresh from this project' : 'Recent assets' }}</h2>
              <router-link :to="contextRoute('browse', projectId)" class="text-xs text-content-muted hover:text-content-secondary transition-colors coarse:inline-flex coarse:min-h-11 coarse:min-w-11 coarse:items-center coarse:px-2 coarse:-mr-2">
                View all
              </router-link>
            </div>
            <div ref="mediaGridRef" class="grid gap-0.5" :style="{ gridTemplateColumns: `repeat(${mediaColumns}, minmax(0, 1fr))` }">
              <div
                v-for="(media, index) in visibleMedia"
                :key="media.id"
                class="aspect-square rounded-media bg-matte overflow-hidden cursor-pointer hover:opacity-80 transition-opacity"
                @click="openMediaSlideshow(index)"
              >
                <MediaImage
                  :media-id="mediaIdOf(media)"
                  :file-hash="media.file_hash"
                  :thumbnail="true"
                  :thumbnail-size="256"
                  background-class="bg-matte"
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
import { flowsEnabled } from '../composables/useExperimentalFlows'
import { formatRelativeTime } from '../utils/timeFormat'
import { useEntityMove } from '../composables/useEntityMove'
import { fetchScopedJson } from '../utils/scopedList'
import { fetchHomeRecents } from '../utils/homeRecents'
import { tileColumns } from '../utils/tileGrid'
import { useViewport } from '../composables/useViewport'
import { ref, computed, nextTick, onMounted, onActivated, onDeactivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MediaContextMenu, MediaImage } from '../components/media'
import EntityIcon from '../components/EntityIcon.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import SetStackPreview from '../components/chat/SetStackPreview.vue'
import { useMediaState } from '../composables/useMediaState'
import ChatModelPicker from '../components/chat/ChatModelPicker.vue'
import { replacementFor } from '../utils/servedChange'
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
import { useToasts, reportActionError } from '../composables/useToasts'
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
const { getCollections, getCollection, addMediaToCollection, deleteCollection, restoreCollection, updateCollection } = useMediaApi()
// Face-aware framing for "Jump back in" cover art (see useFaceFocalPoints).
const { request: requestFaceFocalPoints, positionOf: faceObjectPosition } = useFaceFocalPoints()
const { fetchAssets, addToCollection: addAssetsToCollection } = useAssetApi()
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
// A model switch moves the draft's pick too, or the new chat would save the old model.
const stopFollowingModelSwitch = useWebSocket().on('llm_providers_updated', (data) => {
  const next = replacementFor(selectedNewChatModel.value, data?.replaces)
  if (next) selectedNewChatModel.value = next
})
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
const recentCollections = ref([])
const recentFlows = ref([])
const flowOutputMedia = ref(new Map()) // flow_id -> [{ media_id, file_hash? }, ...]
const collectionDetails = ref(new Map())
// The scope has collections, flows, or chats even though none made a card (the
// compact read skips empty ones), so this is not a first run.
const scopeHasEntities = ref(false)
// 'loading' until the recent chats/collections/flows/assets lists settle, then
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
const dragOverCollectionId = ref(null)
const contentWidth = ref(840)

const isCompact = computed(() => contentWidth.value < 700)
// Measure the available column, independently of the viewport/sidebar tier.
const JUMP_CARD_MIN = 264
const JUMP_CARD_MAX = 360
const jumpColumns = computed(() => Math.min(3, Math.max(1,
  Math.floor((contentWidth.value + 12) / (JUMP_CARD_MIN + 12)))))
const jumpCoverWidth = computed(() => jumpColumns.value === 1 ? 80
  : Math.min(JUMP_CARD_MAX, (contentWidth.value - (jumpColumns.value - 1) * 12) / jumpColumns.value))
const pixelRatio = ref(window.devicePixelRatio || 1)
const jumpThumbnailSize = computed(() => Math.ceil(jumpCoverWidth.value * pixelRatio.value))
// Fit thumbnails preserve the whole source. Their *long* edge must also
// cover the short edge of our crop; learn the source ratio from the image
// itself without another metadata read. Use the original above the API's
// 1024px thumbnail limit rather than requesting an invalid size.
const jumpSourceAspects = ref(new Map())
function rememberJumpAspect(id, event) {
  const image = event.target
  if (!image?.naturalWidth || !image.naturalHeight) return
  const ratio = image.naturalWidth / image.naturalHeight
  if (Math.abs((jumpSourceAspects.value.get(id) || 0) - ratio) > 0.01) {
    jumpSourceAspects.value = new Map(jumpSourceAspects.value).set(id, ratio)
  }
}
function jumpImageThumbnailSize(id) {
  const width = jumpCoverWidth.value
  const height = jumpColumns.value === 1 ? 80 : width * 2 / 3
  const ratio = jumpSourceAspects.value.get(id) || 1
  return Math.ceil(Math.max(width, height, height * ratio, width / ratio) * pixelRatio.value)
}
// With recents below, the hero sits at the top offset; alone, it centres in the spare height.
const hasBelowHero = computed(() => recentMedia.value.length > 0 || jumpBackIn.value.length > 0)

// The same width rule as browse (utils/tileGrid.ts), so the strip's tiles match.
const mediaColumns = computed(() => tileColumns(contentWidth.value, 'browse'))

// Phones get two rows so the home screen has enough below the fold to
// scroll a little; every other home screen does, and a page that fits
// exactly reads as stuck.
const mediaRows = computed(() => Math.max(isCompact.value ? 2 : 1, fillRows.value))

// The strip takes as many rows as the fold has room for, so a tall window is
// not left with an empty band under the last row. The last row may run past the fold.
const scrollerRef = ref(null)
const mediaGridRef = ref(null)
const fillRows = ref(0)
function measureFillRows() {
  const scroller = scrollerRef.value
  const grid = mediaGridRef.value
  if (!scroller || !grid || !grid.clientWidth) return
  const columns = mediaColumns.value
  const tile = (grid.clientWidth - (columns - 1) * 2) / columns
  const top = grid.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
  const room = scroller.clientHeight - top
  fillRows.value = Math.max(1, Math.ceil((room + 2) / (tile + 2)))
}
let scrollerObserver = null

const visibleMedia = computed(() => recentMedia.value.slice(0, mediaColumns.value * mediaRows.value))

// Whether a Jump back in card has artwork (else it shows the quiet type glyph).
function jumpHasArt(item) {
  if (item.type === 'collection') return getCollectionPreviewItems(item.collection).length > 0
  if (item.type === 'flow') return getFlowPreviewMedia(item.id).length > 0
  return item.type === 'chat' && hasChatMedia(item.chat)
}

function hasChatMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

// A chat's cover that is a set is drawn from its members, as in the transcript.
const { mediaState, init: initMediaState, loadStateForMedia } = useMediaState()
function chatCoverIsSet(chat) {
  const format = mediaState.value[chat.recent_media[0].media_id]?.file_format
  return !!format && format.toLowerCase() === 'stimmaset.json'
}

// ==================== Greeting ====================

// True only after the first load with nothing to show: no chats, collections,
// flows, or library media — i.e. a fresh install right after onboarding.
const isFirstRun = computed(() =>
  recentsState.value === 'ready'
  && !scopeHasEntities.value
  && recentChats.value.length === 0
  && recentCollections.value.length === 0
  && (!flowsEnabled.value || recentFlows.value.length === 0)
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
  for (const collection of recentCollections.value) {
    if (!collection.name && !(collection.asset_count > 0)) continue
    items.push({ type: 'collection', id: collection.id, name: collection.name, sub: formatCollectionMeta(collection), updatedAt: collection.updated_at, collection })
  }
  for (const flow of flowsEnabled.value ? recentFlows.value : []) {
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
    .slice(0, jumpColumns.value === 3 ? 3 : 2)
})

// The kind word ("Chat") is said only where it tells cards apart.
const jumpKindsMixed = computed(() => new Set(jumpBackIn.value.map(item => item.type)).size > 1)

function jumpKindLabel(item) {
  return { collection: 'Collection', flow: 'Flow', chat: 'Chat' }[item.type] || item.type
}

function jumpUntitledLabel(item) {
  if (item.type === 'flow') return 'Name this flow...'
  if (item.type === 'chat') return 'New chat'
  return 'Untitled collection'
}

function openJumpItem(item) {
  if (item.type === 'collection') openCollection(item.id)
  else if (item.type === 'flow') openFlow(item.flow)
  else openChat(item.chat)
}

function handleJumpContextMenu(event, item) {
  if (item.type === 'collection') handleCollectionContextMenu(event, item.collection)
  else if (item.type === 'flow') handleFlowContextMenu(event, item.flow)
  else handleChatContextMenu(event, item.chat)
}

initMediaState()
watch(() => jumpBackIn.value, (cards) => {
  const ids = cards.filter(card => card.type === 'chat' && hasChatMedia(card.chat)).map(card => card.chat.recent_media[0].media_id)
  if (ids.length) loadStateForMedia(ids)
}, { immediate: true })
watch([contentWidth, mediaColumns, heroReady, () => recentMedia.value.length, () => jumpBackIn.value.length, () => failedRecentsLabel.value], measureFillRows, { flush: 'post' })

// ==================== Content width tracking ====================

let resizeObserver = null

function measureContent() {
  const width = contentRef.value?.getBoundingClientRect().width
  // A cached/detached Home has no layout. Keep its last usable measurement.
  if (width > 0) contentWidth.value = width
  pixelRatio.value = window.devicePixelRatio || 1
  measureFillRows()
}

function setupResizeObserver() {
  cleanupResizeObserver()
  if (!active || !contentRef.value) return
  measureContent()
  resizeObserver = new ResizeObserver(measureContent)
  resizeObserver.observe(contentRef.value)
  if (scrollerRef.value) {
    scrollerObserver = new ResizeObserver(measureContent)
    scrollerObserver.observe(scrollerRef.value)
  }
}

function cleanupResizeObserver() {
  scrollerObserver?.disconnect()
  scrollerObserver = null
  resizeObserver?.disconnect()
  resizeObserver = null
}

// Slideshow replaces the v-else subtree; observe its new elements on return.
watch([contentRef, scrollerRef], setupResizeObserver, { flush: 'post' })
function handleVisibilityChange() {
  if (active && document.visibilityState === 'visible') void nextTick(measureContent)
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
  if (!flowsEnabled.value) { recentFlows.value = []; return true }
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

// The newest collections, flows, and chats with just their card artwork, chosen
// by the server. Resolves null when the server lacks this read.
async function loadCompactRecents(isCurrent) {
  try {
    const data = await withReadDeadline(signal => fetchHomeRecents(projectId.value, { limit: JUMP_BACK_IN_LIMIT, includeFlows: flowsEnabled.value, signal }))
    if (data === null) return null
    if (!isCurrent()) return true
    const collections = []
    const flows = []
    const chats = []
    const flowMedia = new Map()
    for (const item of data.items) {
      if (item.type === 'collection' && item.collection) collections.push(item.collection)
      else if (flowsEnabled.value && item.type === 'flow' && item.flow) {
        flows.push(item.flow)
        flowMedia.set(item.flow.id, item.flow.preview_media || [])
      } else if (item.type === 'chat' && item.chat) chats.push(item.chat)
    }
    recentCollections.value = collections
    recentFlows.value = flows
    recentChats.value = chats
    collectionDetails.value = new Map()
    flowOutputMedia.value = flowMedia
    scopeHasEntities.value = !!data.has_entities
    requestFaceFocalPoints([
      ...collections.flatMap((collection) => (collection.preview_items || []).map((it) => mediaIdOf(it))),
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
    if (loaded !== null) return loaded ? [] : ['chats', 'collections', 'flows']
    compactRecentsUnsupported.add(origin)
  }
  if (isCurrent()) scopeHasEntities.value = false
  const names = ['chats', 'collections', 'flows']
  const results = await Promise.all([loadRecentChats(isCurrent), loadRecentCollections(isCurrent), loadRecentFlows(isCurrent)])
  return names.filter((_, index) => !results[index])
}

// Reload the cards after this window changed one of them.
function reloadJumpBackIn(kind) {
  if (!compactRecentsUnsupported.has(backendKey())) return loadJumpBackIn(homeLoads.guard())
  if (kind === 'collection') return loadRecentCollections()
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
    reportActionError("Couldn't send.", err)
  } finally {
    submitting.value = false
  }
}

function openChat(chat) {
  router.push({ name: 'chat', params: { id: chat.id } })
}

async function loadRecentCollections(isCurrent = homeLoads.guard()) {
  try {
    const collections = await withReadDeadline(signal => getCollections(projectId.value, { signal }))
    if (!isCurrent()) return true
    recentCollections.value = collections.slice(0, 6)
    void loadCollectionArtwork(recentCollections.value, isCurrent)
    return true
  } catch (err) {
    console.error('Failed to load collections:', err)
    return false
  }
}

async function loadCollectionArtwork(collections, isCurrent) {
  const results = await Promise.allSettled(collections.map((collection) => withReadDeadline(signal => getCollection(collection.id, { signal }))))
  if (!isCurrent()) return
  const next = new Map()
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') next.set(collections[index].id, result.value)
  })
  collectionDetails.value = next
  requestFaceFocalPoints(
    [...next.values()].flatMap((detail) =>
      (detail?.sections || []).flatMap((s) => s.items || []).slice(0, 6).map((it) => mediaIdOf(it))
    )
  )
}

function openCollection(collectionId) {
  router.push({ name: 'collection-detail', params: { id: collectionId } })
}

function openFlow(flow) {
  router.push({ name: 'flow', params: { id: String(flow.id) } })
}

// ==================== Entity context menu ====================

function handleCollectionContextMenu(event, collection) {
  entityContextMenu.show({
    event,
    entityType: 'collection',
    entityId: collection.id,
    entityName: collection.name || 'Untitled',
    projectId: collection.project_id ?? null,
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
  if (entityType === 'collection') openCollection(entityId)
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) } })
  else if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId } })
}

function handleContextMenuRename(entityType, entityId) {
  if (entityType === 'collection') router.push({ name: 'collection-detail', params: { id: entityId }, query: { rename: '1' } })
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) }, query: { rename: '1' } })
  else if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId }, query: { rename: '1' } })
}

const moveEntityToProject = useEntityMove()
async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  if (!['collection', 'flow', 'chat'].includes(entityType)) return
  if (!await moveEntityToProject(entityType, entityId, projectId)) return
  await reloadJumpBackIn(entityType)
}

function handleContextMenuDelete(entityType, entityId) {
  if (entityType === 'collection') deleteCollectionEntry(entityId)
  else if (entityType === 'flow') deleteFlowEntry(entityId)
  else if (entityType === 'chat') deleteChatEntry(entityId)
}

async function deleteCollectionEntry(id) {
  const removed = recentCollections.value.find((b) => b.id === id)
  if (!removed) return
  recentCollections.value = recentCollections.value.filter((b) => b.id !== id)

  try {
    await deleteCollection(id)
  } catch (err) {
    console.error('Failed to delete collection:', err)
    recentCollections.value = [removed, ...recentCollections.value]
    addToast('Failed to delete collection', 'error', 5000)
    return
  }

  addToast('Deleted 1 collection', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!recentCollections.value.find((b) => b.id === id)) {
        recentCollections.value = [removed, ...recentCollections.value]
      }
      try {
        await restoreCollection(id)
      } catch (err) {
        console.error('Failed to restore collection:', err)
        recentCollections.value = recentCollections.value.filter((b) => b.id !== id)
        addToast('Failed to restore collection', 'error', 5000)
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

async function handleCollectionDrop(collectionId, event) {
  dragOverCollectionId.value = null
  const mediaIds = getDroppedMediaIds(event.dataTransfer)
  const assetIds = getDroppedAssetRefs(event.dataTransfer).map((item) => item.asset_id)
  if (mediaIds.length === 0) return
  try {
    if (assetIds.length > 0) await addAssetsToCollection(collectionId, assetIds)
    else await addMediaToCollection(collectionId, mediaIds)
    await reloadJumpBackIn('collection')
  } catch (err) {
    reportActionError("Couldn't add to collection.", err)
  }
}

function getCollectionPreviewItems(collection) {
  if (collection.preview_items) return collection.preview_items.slice(0, 6)
  const detail = collectionDetails.value.get(collection.id)
  if (!detail?.sections) return []

  return detail.sections
    .flatMap((section) => section.items || [])
    .slice(0, 6)
}

// Natural-aspect collection tiles follow the cover height, including compact rows.
function getPreviewTileStyle(item) {
  const ratio = Math.min(Math.max(item?.width || 1, 1) / Math.max(item?.height || 1, 1), 16 / 9)
  const height = jumpColumns.value === 1 ? 80 : jumpCoverWidth.value * 2 / 3
  return { width: `${(height - 4) * ratio}px` }
}

function isVideoFormat(fileFormat) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat)
}

function formatCollectionMeta(collection) {
  const assetCount = collection.asset_count || 0
  const assetLabel = `${assetCount} ${assetCount === 1 ? 'asset' : 'assets'}`
  if (!collection.updated_at) return assetLabel
  return `${assetLabel} • ${formatRelativeTime(collection.updated_at)}`
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
// snippet, cover), a collection or flow card, or the recent-assets strip.
const HOME_CHANGE_EVENTS = [
  'chat_created', 'chat_updated', 'chat_deleted', 'chat_restored', 'chat_cleared',
  'chat_item_created', 'chat_item_updated', 'chat_item_deleted',
  'collection_created', 'collection_updated', 'collection_deleted', 'collection_restored', 'collection_items_changed',
  'collection_section_created', 'collection_section_updated', 'collection_section_deleted',
  'flow_created', 'flow_updated', 'flow_deleted', 'flow_restored', 'flow_equation_updated',
  'asset_created', 'asset_deleted', 'asset_trashed', 'assets_trashed', 'assets_restored',
  'assets_permanently_deleted', 'asset_identities_deleted', 'asset_current_revision_changed', 'assets_updated',
  'media_added', 'media_updated', 'media_restored', 'media_bulk_restored', 'media_permanently_deleted',
  'project_assets_changed', 'trash_emptied',
]
// Changes this window makes itself, announced ahead of the server broadcast.
const HOME_LOCAL_CHANGE_EVENTS = [PROJECT_ASSETS_CHANGED_EVENT]

function homeScope() {
  return scopeKey(getBackendOrigin() || window.location.origin, getCurrentProfileId(), projectId.value, String(flowsEnabled.value))
}

function resetHomeData() {
  recentChats.value = []
  recentMedia.value = []
  recentCollections.value = []
  recentFlows.value = []
  flowOutputMedia.value = new Map()
  collectionDetails.value = new Map()
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
  void nextTick(setupResizeObserver)
  void refreshHome()
  void loadTools()
  recentToolEntities.value = recentEntities(60).filter(e => e.type === 'tool')
  void checkModels()
  revealHeroSoon()
  checkPendingMedia()
  if (allowsAutofocus.value) chatInputBoxRef.value?.focusQuietly()
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

watch(flowsEnabled, () => { if (active) void refreshHome() })

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
  // Home on screen refreshes once the socket is back after a gap (or after a
  // failed load), keeping its cards visible meanwhile; a cached, inactive Home
  // reloads on its next visit. Returning the read lets optional reconnect
  // work wait for it.
  unsubscribeFromServerEvents.push(onServerEvent('websocket_reconnected', () => {
    const missedEvents = socketWasDown
    if (missedEvents) invalidateHome()
    socketWasDown = false
    if (active && (missedEvents || recentsState.value === 'error')) return refreshHome()
    return undefined
  }))
  for (const event of HOME_LOCAL_CHANGE_EVENTS) window.addEventListener(event, invalidateHome)
  window.addEventListener('stimma:transport-resumed', invalidateHome)
  window.addEventListener('profile-changed', handleProfileChanged)
  window.addEventListener('resize', measureContent)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onActivated(activate)

onDeactivated(() => {
  active = false
  cleanupResizeObserver()
})

onUnmounted(() => {
  stopFollowingModelSwitch()
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
  window.removeEventListener('resize', measureContent)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
