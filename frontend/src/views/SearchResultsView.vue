<template>
  <div class="relative h-full flex flex-col bg-base">
    <!-- Slideshow for asset results -->
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
      <div class="max-w-[960px] mx-auto px-8 py-8">
        <!-- Header (landing-page scale) -->
        <div class="flex items-center gap-2.5">
          <h1 class="text-xl font-semibold leading-none text-content">
            <template v-if="q">Results for “{{ q }}”</template>
            <template v-else>Search</template>
          </h1>
          <button
            v-if="scopeProjectId != null"
            class="flex items-center gap-1 max-w-[200px] pl-2 pr-1.5 py-1 rounded-md bg-blue-500/15 border border-blue-500/50 text-blue-400 text-xs cursor-pointer hover:bg-blue-500/25 transition-colors"
            title="Remove project scope"
            @click="clearScope"
          >
            <span class="truncate">in {{ scopeProjectName || 'project' }}</span>
            <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="text-sm text-content-tertiary mt-2 mb-8 min-h-[1.25rem]">
          <template v-if="loading">Searching…</template>
          <template v-else-if="q && totalCount > 0">{{ totalCount }} {{ totalCount === 1 ? 'match' : 'matches' }} across {{ matchedKindsLabel }}</template>
        </div>

        <!-- Skeleton while the first results for this query load -->
        <div v-if="showSkeleton" class="space-y-10 pb-12">
          <section v-for="s in 2" :key="`skc-${s}`">
            <div class="h-3 w-24 rounded bg-overlay-subtle animate-pulse mb-4"></div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              <div v-for="i in 3" :key="i" class="h-[62px] rounded-xl bg-overlay-subtle animate-pulse"></div>
            </div>
          </section>
          <section v-for="s in 2" :key="`ska-${s}`">
            <div class="h-3 w-32 rounded bg-overlay-subtle animate-pulse mb-4"></div>
            <div class="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1.5">
              <div v-for="i in 16" :key="i" class="aspect-square rounded-lg bg-overlay-subtle animate-pulse"></div>
            </div>
          </section>
        </div>

        <!-- Cold landing: no query yet -->
        <div v-else-if="!q" class="py-24">
          <EmptyState
            icon="search"
            title="Search Stimma"
            subtitle="Tools, chats, flows, boards, projects, and assets — press ⌘K anywhere"
          />
        </div>

        <!-- No matches at all: one empty state with the library escape hatches -->
        <div v-else-if="totalCount === 0" class="py-24 flex flex-col gap-6">
          <EmptyState
            icon="search"
            :title="`No matches for “${q}”`"
            subtitle="Nothing by that name — the library search casts a wider net"
          />
          <div class="flex items-center justify-center gap-8">
            <router-link
              :to="{ name: 'browse', query: browseQueryFor('pq') }"
              class="text-sm text-blue-400 hover:text-blue-300 transition-colors"
            >Search prompts in Browse →</router-link>
            <router-link
              :to="{ name: 'browse', query: browseQueryFor('stt') }"
              class="text-sm text-blue-400 hover:text-blue-300 transition-colors"
            >Search visually in Browse →</router-link>
          </div>
        </div>

        <div v-else class="space-y-10 pb-12">
          <!-- Tools -->
          <section v-if="toolResults.length > 0">
            <div class="flex items-baseline gap-2.5 mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">Tools</h2>
              <span class="text-[11px] text-content-muted/70">{{ toolResults.length }}</span>
              <router-link
                :to="{ name: 'all-tools', query: { q } }"
                class="ml-auto text-xs text-content-muted hover:text-content-secondary transition-colors"
              >View all</router-link>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              <button
                v-for="tool in toolResults"
                :key="tool.full_tool_id"
                @click="open('tool', tool)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
              >
                <ToolIcon :tool="tool" size="md" :ring="false" />
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <HighlightedName :text="tool.name" :query="q" />
                    <ProjectTag v-if="scopeProjectId != null" :name="scopeProjectName" />
                  </div>
                  <div
                    class="text-xs truncate mt-0.5"
                    :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'"
                  >{{ tool.provider_name }}</div>
                </div>
              </button>
            </div>
          </section>

          <!-- Entity sections -->
          <section v-for="section in entitySections" :key="section.title">
            <div class="flex items-baseline gap-2.5 mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">{{ section.title }}</h2>
              <span class="text-[11px] text-content-muted/70">{{ section.hits.length }}</span>
              <router-link
                v-if="section.viewAll"
                :to="section.viewAll"
                class="ml-auto text-xs text-content-muted hover:text-content-secondary transition-colors"
              >View all</router-link>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              <button
                v-for="hit in section.hits"
                :key="hit.id"
                @click="open(section.kind, hit)"
                @contextmenu="handleEntityContextMenu($event, section.kind, hit)"
                class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-edge-subtle hover:border-edge-strong hover:bg-overlay-subtle transition-all text-left bg-transparent cursor-pointer"
              >
                <!-- Chat/board previews, same treatment as the home screen & sidebar -->
                <div v-if="section.kind === 'chat' && hit.thumbnail" class="flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden">
                  <MediaImage
                    :media-id="hit.thumbnail.media_id"
                    :file-hash="hit.thumbnail.file_hash || undefined"
                    :thumbnail="true"
                    :thumbnail-size="64"
                    :draggable="false"
                    :enable-context-menu="false"
                    container-class="w-full h-full"
                    class="w-full h-full object-cover"
                  />
                </div>
                <div v-else-if="section.kind === 'board' && hit.preview_items?.length" class="flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden bg-overlay-subtle">
                  <div class="grid grid-cols-2 gap-[1px] w-full h-full">
                    <MediaImage
                      v-for="item in hit.preview_items.slice(0, 4)"
                      :key="`${hit.id}-${item.media_id}`"
                      :media-id="item.media_id"
                      :file-hash="item.file_hash || undefined"
                      :thumbnail="true"
                      :thumbnail-size="64"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="w-full h-full"
                      class="w-full h-full object-cover"
                    />
                  </div>
                </div>
                <EntityIcon v-else-if="section.entityIcon" :type="section.entityIcon" size="md" shape="rounded" />
                <div v-else class="w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center bg-overlay-faint border border-edge-subtle text-content-secondary">
                  <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" :d="PRESET_ICON" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <HighlightedName :text="hit.name || `Untitled ${section.kind}`" :query="q" />
                    <!-- Presets are part of tools: under scope they open the project flavor -->
                    <ProjectTag v-if="section.kind === 'preset' && scopeProjectId != null" :name="scopeProjectName" />
                  </div>
                  <div class="text-xs text-content-muted truncate mt-0.5">
                    <template v-if="section.kind === 'preset' && toolNameById.get(hit.tool_id)">{{ toolNameById.get(hit.tool_id) }}</template>
                    <template v-else-if="hit.updated_at">{{ formatRelativeTime(hit.updated_at) }}</template>
                  </div>
                </div>
              </button>
            </div>
          </section>

          <!-- Assets: the app's duality — prompt text matches vs CLIP visual
               matches. Empty flavors are hidden entirely (like the home
               screen's sections), never shown as dead bands. -->
          <section v-for="assetSection in assetSections" :key="assetSection.key">
            <div class="flex items-baseline gap-2.5 mb-3">
              <h2 class="text-xs font-medium text-content-muted uppercase tracking-wider">{{ assetSection.title }}</h2>
              <span class="text-[11px] text-content-muted/70">{{ assetSection.items.length }}</span>
              <router-link
                :to="{ name: 'browse', query: assetSection.browseQuery }"
                class="ml-auto text-xs text-content-muted hover:text-content-secondary transition-colors"
              >View all</router-link>
            </div>
            <div class="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1.5">
              <div
                v-for="(media, index) in assetSection.items"
                :key="media.id"
                class="aspect-square rounded-lg overflow-hidden cursor-pointer hover:opacity-80 transition-opacity"
                @click="openAssetFromGrid(assetSection.key, index)"
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
          </section>
        </div>
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

<script setup lang="ts">
import { ref, computed, watch, h, defineComponent, onActivated, type PropType } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArchiveBoxIcon } from '@heroicons/vue/24/outline'
import EmptyState from '../components/EmptyState.vue'
import EntityIcon from '../components/EntityIcon.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import { MediaImage } from '../components/media'
import SlideshowMode from '../components/SlideshowMode.vue'
import ToolIcon from '../components/tools/ToolIcon.vue'
import { useSlideshow } from '../composables/useSlideshow'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useFlowsApi } from '../composables/useFlowsApi'
import { useEntityContextMenu, type EntityType } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'
import {
  useGlobalSearch,
  openSearchResult,
  matchSegments,
  type EntitySearchResults,
  type EntitySearchHit,
  type MediaSearchHit,
  type SearchResultKind,
} from '../composables/useGlobalSearch'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { useTelemetry } from '../composables/useTelemetry'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { formatRelativeTime } from '../utils/timeFormat'
import { mediaIdOf } from '../utils/assetIdentity'

const PAGE_ENTITY_LIMIT = 24
const PAGE_TOOL_LIMIT = 12
// 16 = exactly two rows of the lg 8-column grid (the app window's minimum
// width guarantees lg); View all covers the rest.
const PAGE_MEDIA_LIMIT = 16

const PRESET_ICON = 'M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75'

const route = useRoute()
const router = useRouter()
const { searchEntities, searchTools, searchMediaByPrompt, searchMediaVisual } = useGlobalSearch()
const { fetchProvidersAndTools } = useProvidersApi()
const { getProject, deleteBoard, restoreBoard, updateBoard } = useMediaApi()
const { getAssetBrowserItem } = useAssetApi()
const { updateFlow, deleteFlow, restoreFlow } = useFlowsApi()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()
const { track } = useTelemetry()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()

const q = computed(() => String(route.query.q || '').trim())

// Project scope carried from the omnibox chip (?project=). Removable here too.
const scopeProjectId = computed<number | null>(() => {
  const raw = route.query.project
  if (!raw) return null
  const id = parseInt(String(Array.isArray(raw) ? raw[0] : raw), 10)
  return Number.isFinite(id) ? id : null
})
const scopeProjectName = ref('')

function clearScope() {
  const restQuery = { ...route.query }
  delete restQuery.project
  router.replace({ query: restQuery })
}

const loading = ref(false)
const showSkeleton = computed(() => loading.value && totalCount.value === 0)
const entityResults = ref<EntitySearchResults | null>(null)
const toolResults = ref<ProviderTool[]>([])
const promptResults = ref<MediaSearchHit[]>([])
const visualResults = ref<MediaSearchHit[]>([])
const toolNameById = ref<Map<string, string>>(new Map())

// Inline highlight renderer honoring the loose token matcher.
const HighlightedName = defineComponent({
  props: { text: { type: String, required: true }, query: { type: String, required: true } },
  setup(props) {
    return () =>
      h(
        'div',
        { class: 'text-sm text-content font-medium truncate' },
        matchSegments(props.text, props.query).map(seg =>
          seg.match ? h('span', { class: 'text-blue-400 font-semibold' }, seg.text) : seg.text,
        ),
      )
  },
})

// Project pill: under scope, tools/presets open the project flavor.
const ProjectTag = defineComponent({
  props: { name: { type: String as PropType<string>, default: '' } },
  setup(props) {
    return () =>
      h(
        'span',
        { class: 'flex-shrink-0 inline-flex items-center gap-1 rounded-full bg-overlay-subtle px-1.5 py-0.5 text-[10px] font-medium text-content-secondary' },
        [
          h(ArchiveBoxIcon, { class: 'w-3 h-3 flex-shrink-0' }),
          h('span', { class: 'truncate max-w-[100px]' }, props.name || 'Untitled Project'),
        ],
      )
  },
})

interface EntitySection {
  title: string
  kind: SearchResultKind
  hits: EntitySearchHit[]
  entityIcon: 'chat' | 'board' | 'project' | 'flow' | null
  viewAll: { name: string; query: Record<string, string> } | null
}

const entitySections = computed<EntitySection[]>(() => {
  const e = entityResults.value
  if (!e) return []
  // "View all" carries the query into each landing view's own filter, so the
  // per-type caps here never hide matches for good.
  const defs: Array<[string, SearchResultKind, EntitySearchHit[], EntitySection['entityIcon'], string | null]> = [
    ['Chats', 'chat', e.chats, 'chat', 'chats'],
    ['Flows', 'flow', e.flows, 'flow', 'flows'],
    ['Boards', 'board', e.boards, 'board', 'boards'],
    ['Projects', 'project', e.projects, 'project', 'projects'],
    ['Presets', 'preset', e.presets, null, null],
  ]
  return defs
    .filter(([, , hits]) => hits.length > 0)
    .map(([title, kind, hits, entityIcon, routeName]) => ({
      title,
      kind,
      hits,
      entityIcon,
      viewAll: routeName ? { name: routeName, query: { q: q.value } } : null,
    }))
})

interface AssetSection {
  key: 'prompt' | 'visual'
  title: string
  items: MediaSearchHit[]
  browseQuery: Record<string, string>
}

function browseQueryFor(param: 'pq' | 'stt'): Record<string, string> {
  const scope = scopeProjectId.value != null ? { prj: String(scopeProjectId.value) } : {}
  return { [param]: q.value, ...scope }
}

const assetSections = computed<AssetSection[]>(() => {
  if (!q.value) return []
  return [
    {
      key: 'prompt' as const,
      title: 'Prompt matches',
      items: promptResults.value,
      browseQuery: browseQueryFor('pq'),
    },
    {
      key: 'visual' as const,
      title: 'Visual matches',
      items: visualResults.value,
      browseQuery: browseQueryFor('stt'),
    },
  ].filter(section => section.items.length > 0)
})

const totalCount = computed(() => {
  const e = entityResults.value
  const entityTotal = e
    ? e.chats.length + e.flows.length + e.boards.length + e.projects.length + e.presets.length
    : 0
  return entityTotal + toolResults.value.length + promptResults.value.length + visualResults.value.length
})

const matchedKindsLabel = computed(() => {
  const kinds: string[] = []
  if (toolResults.value.length) kinds.push('tools')
  for (const s of entitySections.value) kinds.push(s.title.toLowerCase())
  if (promptResults.value.length || visualResults.value.length) kinds.push('assets')
  if (kinds.length <= 1) return kinds[0] || ''
  return kinds.slice(0, -1).join(', ') + ' and ' + kinds[kinds.length - 1]
})

let searchSeq = 0

async function runSearch() {
  const current = q.value
  const seq = ++searchSeq
  if (!current) {
    entityResults.value = null
    toolResults.value = []
    promptResults.value = []
    visualResults.value = []
    return
  }
  loading.value = true
  // A NEW query's load shows the skeleton instead of the previous query's
  // (now wrong) results; a same-query refresh keeps content in place.
  if (lastLoadedQuery.value !== current) {
    entityResults.value = null
    toolResults.value = []
    promptResults.value = []
    visualResults.value = []
  }
  try {
    const projectId = scopeProjectId.value
    const [entities, tools, prompt, visual] = await Promise.all([
      searchEntities(current, PAGE_ENTITY_LIMIT, projectId).catch(() => null),
      searchTools(current, PAGE_TOOL_LIMIT).catch(() => []),
      searchMediaByPrompt(current, PAGE_MEDIA_LIMIT, projectId).catch(() => []),
      searchMediaVisual(current, PAGE_MEDIA_LIMIT, projectId).catch(() => []),
    ])
    if (seq !== searchSeq) return
    entityResults.value = entities
    toolResults.value = tools
    promptResults.value = prompt
    visualResults.value = visual
    if (entities && entities.presets.length > 0) void ensureToolNames()
    lastLoadedQuery.value = current
    consumeSlideshowParam()
  } finally {
    if (seq === searchSeq) loading.value = false
  }
}

// The omnibox hands off asset clicks as ?slideshow=<mediaId>&sset=prompt|visual
// so the slideshow opens INLINE here (content area only — the sidebar stays
// visible; only 'f' fullscreen mode covers it) within the matching flavor's
// result set. The param is consumed into a pending ref and only opened once
// results for the CURRENT query have landed — the param watcher can fire
// before the q watcher's search starts.
const pendingSlideshow = ref<{ id: number; set: 'prompt' | 'visual' } | null>(null)
const lastLoadedQuery = ref<string | null>(null)

function consumeSlideshowParam() {
  const idParam = route.query.slideshow
  if (idParam) {
    const setParam = String(route.query.sset || 'prompt')
    const restQuery = { ...route.query }
    delete restQuery.slideshow
    delete restQuery.sset
    router.replace({ query: restQuery })
    const id = parseInt(String(Array.isArray(idParam) ? idParam[0] : idParam), 10)
    if (!isNaN(id)) {
      pendingSlideshow.value = { id, set: setParam === 'visual' ? 'visual' : 'prompt' }
    }
  }
  if (!pendingSlideshow.value) return
  if (lastLoadedQuery.value !== q.value) return // results not in yet; retried after runSearch
  const { id, set } = pendingSlideshow.value
  pendingSlideshow.value = null
  const list = set === 'visual' ? visualResults.value : promptResults.value
  const index = list.findIndex(m => m.id === id)
  if (index !== -1) {
    void openMediaSlideshow(set, index)
    return
  }
  // The clicked asset isn't in this page's window (results shifted between
  // the omnibox's fetch and ours) — open exactly that item rather than
  // silently showing a different one.
  void openSingleItemSlideshow(id)
}

watch(() => route.query.slideshow, (value) => {
  if (value) consumeSlideshowParam()
})

async function ensureToolNames() {
  if (toolNameById.value.size > 0) return
  try {
    const { tools } = await fetchProvidersAndTools()
    toolNameById.value = new Map(tools.map(t => [t.full_tool_id, t.name]))
  } catch {}
}

watch([q, scopeProjectId], () => {
  void runSearch()
  void loadScopeProjectName()
}, { immediate: true })
onActivated(runSearch) // KeepAlive: refresh when returning to a cached instance

async function loadScopeProjectName() {
  const id = scopeProjectId.value
  if (id == null) {
    scopeProjectName.value = ''
    return
  }
  try {
    const project = await getProject(id)
    scopeProjectName.value = project?.name || ''
  } catch {
    scopeProjectName.value = ''
  }
}

// Result kinds are a closed enum; query text is never tracked.
function trackResultOpened(kind: string) {
  track('search_result_opened', {
    kind,
    surface: 'page',
    scoped: scopeProjectId.value != null,
  }, 'feature')
}

function open(kind: SearchResultKind, result: any) {
  trackResultOpened(kind)
  openSearchResult(router, kind, result, scopeProjectId.value)
}

function openAssetFromGrid(set: 'prompt' | 'visual', index: number) {
  trackResultOpened('asset')
  void openMediaSlideshow(set, index)
}

// ==================== Entity context menu (chats/flows/boards only) ====================

type ManagedKind = 'chat' | 'flow' | 'board'

function sectionListFor(kind: ManagedKind): EntitySearchHit[] | null {
  const e = entityResults.value
  if (!e) return null
  if (kind === 'chat') return e.chats
  if (kind === 'flow') return e.flows
  if (kind === 'board') return e.boards
  return null
}

function handleEntityContextMenu(event: MouseEvent, kind: SearchResultKind, hit: EntitySearchHit) {
  if (kind !== 'chat' && kind !== 'flow' && kind !== 'board') return
  entityContextMenu.show({
    event,
    entityType: kind as EntityType,
    entityId: Number(hit.id),
    entityName: hit.name || 'Untitled',
    projectId: hit.project_id ?? null,
    isSelected: false,
    selectedCount: 0,
  })
}

function handleContextMenuOpen(entityType: string, entityId: number) {
  if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId } })
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) } })
  else if (entityType === 'board') router.push({ name: 'board-detail', params: { id: entityId } })
}

function handleContextMenuRename(entityType: string, entityId: number) {
  if (entityType === 'chat') router.push({ name: 'chat', params: { id: entityId }, query: { rename: '1' } })
  else if (entityType === 'flow') router.push({ name: 'flow', params: { id: String(entityId) }, query: { rename: '1' } })
  else if (entityType === 'board') router.push({ name: 'board-detail', params: { id: entityId }, query: { rename: '1' } })
}

async function handleContextMenuMoveToProject(entityType: string, entityId: number, projectId: number | null) {
  try {
    if (entityType === 'board') {
      await updateBoard(entityId, { project_id: projectId })
    } else if (entityType === 'flow') {
      await updateFlow(entityId, { project_id: projectId })
    } else if (entityType === 'chat') {
      await fetch(`/api/chats/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      })
    } else {
      return
    }
    await runSearch()
  } catch (err) {
    console.error(`Failed to move ${entityType} to project:`, err)
  }
}

async function callEntityDelete(kind: ManagedKind, id: number) {
  if (kind === 'board') {
    await deleteBoard(id)
  } else if (kind === 'flow') {
    await deleteFlow(id)
  } else {
    const response = await fetch(`/api/chats/${id}`, { method: 'DELETE' })
    if (!response.ok) throw new Error('delete failed')
  }
}

async function callEntityRestore(kind: ManagedKind, id: number) {
  if (kind === 'board') {
    await restoreBoard(id)
  } else if (kind === 'flow') {
    await restoreFlow(id)
  } else {
    const response = await fetch(`/api/chats/${id}/restore`, { method: 'POST' })
    if (!response.ok) throw new Error('restore failed')
  }
}

async function handleContextMenuDelete(entityType: string, entityId: number) {
  if (entityType !== 'chat' && entityType !== 'flow' && entityType !== 'board') return
  const kind = entityType as ManagedKind
  const list = sectionListFor(kind)
  if (!list) return
  const idx = list.findIndex(h => h.id === entityId)
  if (idx === -1) return
  const removed = list[idx]
  list.splice(idx, 1)

  try {
    await callEntityDelete(kind, entityId)
  } catch (err) {
    console.error(`Failed to delete ${kind}:`, err)
    const cur = sectionListFor(kind)
    if (cur && !cur.find(h => h.id === entityId)) cur.splice(idx, 0, removed)
    addToast(`Failed to delete ${kind}`, 'error', 5000)
    return
  }

  addToast(`Deleted 1 ${kind}`, 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      const cur = sectionListFor(kind)
      if (cur && !cur.find(h => h.id === entityId)) cur.splice(idx, 0, removed)
      try {
        await callEntityRestore(kind, entityId)
      } catch (err) {
        console.error(`Failed to restore ${kind}:`, err)
        const after = sectionListFor(kind)
        if (after) {
          const i = after.findIndex(h => h.id === entityId)
          if (i !== -1) after.splice(i, 1)
        }
        addToast(`Failed to restore ${kind}`, 'error', 5000)
      }
    }
  })
}

async function openMediaSlideshow(set: 'prompt' | 'visual', index: number) {
  const list = set === 'visual' ? visualResults.value : promptResults.value
  try {
    const items = [...list]
    enterSlideshow({
      totalCount: items.length,
      startIndex: index,
      pageProvider: async (pageNumber: number, pageSize: number) => {
        const start = pageNumber * pageSize
        return items.slice(start, start + pageSize)
      },
    })
  } catch (err) {
    console.error('[SearchResultsView] Failed to open slideshow:', err)
  }
}

async function openSingleItemSlideshow(assetId: number) {
  try {
    const item = await getAssetBrowserItem(assetId)
    if (!item) return
    enterSlideshow({
      totalCount: 1,
      startIndex: 0,
      pageProvider: async () => [item],
    })
  } catch (err) {
    console.error('[SearchResultsView] Failed to open slideshow item:', err)
  }
}
</script>

<style scoped>
/* Stimma Cloud provider treatment (same as TaskTypeToolList) */
.stimma-gradient-text {
  background: linear-gradient(135deg, #0d9488, #06b6d4, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 500;
}
</style>
