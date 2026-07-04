<template>
  <div class="relative global-search-box">
    <!-- Search field -->
    <div
      class="flex items-center gap-1.5 h-[34px] w-[420px] rounded-lg border pl-2.5 pr-1 transition-colors"
      :class="isOpen
        ? 'bg-surface border-blue-500/50 shadow-[0_0_0_3px_rgba(59,130,246,0.12)]'
        : 'bg-overlay-subtle border-edge-subtle hover:border-edge'"
    >
      <svg class="w-3.5 h-3.5 flex-shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <!-- Project scope chip (seeded from the current project; ✕ or Backspace-on-empty removes) -->
      <button
        v-if="scopeProject"
        class="flex-shrink-0 flex items-center gap-1 max-w-[150px] pl-1.5 pr-1 py-[3px] rounded-md bg-blue-500/15 border border-blue-500/50 text-blue-400 text-[11px] leading-none cursor-pointer hover:bg-blue-500/25 transition-colors"
        title="Remove project scope (Backspace)"
        @click="clearScope"
      >
        <ArchiveBoxIcon class="w-3 h-3 flex-shrink-0" />
        <span class="truncate">{{ scopeProject.name || 'Untitled Project' }}</span>
        <svg class="w-2.5 h-2.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
      <input
        ref="inputRef"
        v-model="query"
        type="text"
        placeholder="Search or jump to…"
        class="flex-1 min-w-0 bg-transparent border-none outline-none text-[13px] text-content placeholder:text-content-muted"
        spellcheck="false"
        autocomplete="off"
        @focus="openDropdown"
        @blur="handleInputBlur"
        @keydown="handleKeydown"
        @keyup="handleKeyup"
      />
      <span
        v-if="!isOpen"
        class="flex-shrink-0 text-[10.5px] text-content-muted border border-edge bg-overlay-faint rounded px-1.5 py-px select-none"
      >{{ isMac ? '⌘K' : 'Ctrl K' }}</span>
      <VoiceInputButton
        ref="voiceBtn"
        :get-text="getQueryText"
        :set-text="setQueryText"
        :focus="focusInput"
        icon-class="w-4 h-4"
        surface="global_search"
      />
    </div>

    <!-- Dropdown -->
    <div
      v-if="isOpen && (sections.length > 0 || query.trim() || loading)"
      ref="dropdownRef"
      class="absolute top-[calc(100%+0.5rem)] left-1/2 -translate-x-1/2 w-[560px] max-h-[70vh] overflow-y-auto custom-scrollbar bg-surface border border-edge rounded-lg shadow-[0_16px_40px_rgba(0,0,0,0.55)] z-[10000]"
    >
      <template v-for="(section, sIdx) in sections" :key="section.title">
        <div v-if="sIdx > 0" class="border-t border-edge-subtle"></div>
        <div class="py-1.5">
          <div class="text-[10.5px] font-semibold uppercase tracking-wider text-content-muted px-3.5 pt-1 pb-0.5">
            {{ section.title }}
          </div>

          <!-- Asset thumbnail strip -->
          <div v-if="section.strip" class="flex gap-1.5 px-3.5 py-1.5">
            <button
              v-for="item in section.items"
              :key="item.key"
              :data-search-idx="item.index"
              class="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0 border transition-all cursor-pointer"
              :class="item.index === selectedIndex ? 'border-blue-500 ring-2 ring-blue-500/40' : 'border-edge-subtle hover:border-edge-strong'"
              @mouseenter="selectedIndex = item.index"
              @click="activateItem(item)"
            >
              <MediaImage
                :media-id="item.data.id"
                :file-hash="item.data.file_hash"
                :thumbnail="true"
                :thumbnail-size="128"
                :draggable="false"
                :enable-context-menu="false"
                container-class="w-full h-full"
                class="w-full h-full object-cover"
              />
            </button>
          </div>

          <!-- Standard rows -->
          <template v-else>
            <button
              v-for="item in section.items"
              :key="item.key"
              :data-search-idx="item.index"
              class="w-full flex items-center gap-2.5 px-3.5 py-2 text-left cursor-pointer transition-colors"
              :class="item.index === selectedIndex ? 'bg-blue-500/15' : 'hover:bg-overlay-subtle'"
              @mouseenter="selectedIndex = item.index"
              @click="activateItem(item)"
            >
              <!-- Icon: sidebar treatments — chat/board previews when present,
                   plain nav glyphs otherwise; cloud tool marks stay untinted
                   (brand colors) per TaskTypeToolList -->
              <div
                class="w-6 h-6 flex-shrink-0 flex items-center justify-center"
                :class="isEscapeKind(item.kind) ? 'text-blue-400'
                  : (item.kind === 'tool' && item.provider?.cloud) ? ''
                  : 'text-content-secondary'"
              >
                <div v-if="item.kind === 'chat' && item.data?.thumbnail" class="w-6 h-6 rounded-full overflow-hidden">
                  <MediaImage
                    :media-id="item.data.thumbnail.media_id"
                    :file-hash="item.data.thumbnail.file_hash || undefined"
                    :thumbnail="true"
                    :thumbnail-size="64"
                    :draggable="false"
                    :enable-context-menu="false"
                    container-class="w-full h-full"
                    class="w-full h-full object-cover"
                  />
                </div>
                <div v-else-if="item.kind === 'board' && item.data?.preview_items?.length" class="w-6 h-6 rounded overflow-hidden bg-overlay-subtle">
                  <div class="grid grid-cols-2 gap-px w-full h-full">
                    <MediaImage
                      v-for="preview in item.data.preview_items.slice(0, 4)"
                      :key="`${item.key}-${preview.media_id}`"
                      :media-id="preview.media_id"
                      :file-hash="preview.file_hash || undefined"
                      :thumbnail="true"
                      :thumbnail-size="64"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="w-full h-full"
                      class="w-full h-full object-cover"
                    />
                  </div>
                </div>
                <div v-else-if="item.kind === 'tool'" class="w-4 h-4">
                  <ToolIcon :tool="toolForIcon(item)" bare :ring="false" />
                </div>
                <svg v-else-if="item.kind === 'board'" class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
                </svg>
                <ArchiveBoxIcon v-else-if="item.kind === 'project'" class="w-4 h-4" />
                <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" :d="iconPathFor(item)" />
                </svg>
              </div>
              <!-- Text -->
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 min-w-0">
                  <div
                    class="text-[13px] truncate"
                    :class="isEscapeKind(item.kind) ? 'text-blue-400' : 'text-content'"
                  >
                    <template v-if="item.highlight">
                      <template v-for="(seg, i) in matchSegments(item.label, query)" :key="i"><span :class="seg.match ? 'text-blue-400 font-semibold' : ''">{{ seg.text }}</span></template>
                    </template>
                    <template v-else>{{ item.label }}</template>
                  </div>
                  <!-- Project tag: under scope, tool/preset rows open the project flavor -->
                  <span
                    v-if="(item.kind === 'tool' || item.kind === 'preset') && scopeProject"
                    class="flex-shrink-0 inline-flex items-center gap-1 rounded-full bg-overlay-subtle px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
                  >
                    <ArchiveBoxIcon class="w-3 h-3 flex-shrink-0" />
                    <span class="truncate max-w-[100px]">{{ scopeProject.name || 'Untitled Project' }}</span>
                  </span>
                </div>
                <div v-if="item.sub" class="text-[11.5px] text-content-tertiary truncate">{{ item.sub }}</div>
              </div>
              <span v-if="item.provider || item.meta" class="flex-shrink-0 text-[11.5px] pl-3">
                <span v-if="item.provider" :class="item.provider.cloud ? 'stimma-gradient-text' : 'text-content-muted'">{{ item.provider.name }}</span>
                <span v-if="item.provider && item.meta" class="text-content-muted"> · </span>
                <span v-if="item.meta" class="text-content-muted">{{ item.meta }}</span>
              </span>
            </button>
          </template>
        </div>
      </template>

      <div v-if="loading && sections.length === 0" class="px-3.5 py-4 text-[12.5px] text-content-muted">
        Searching…
      </div>

      <!-- Footer hints -->
      <div class="flex items-center gap-3.5 px-3.5 py-2 border-t border-edge-subtle bg-overlay-faint text-[11px] text-content-muted select-none">
        <span><kbd class="font-sans">↑↓</kbd> navigate</span>
        <span><kbd class="font-sans">↵</kbd> open</span>
        <span v-if="query.trim()"><kbd class="font-sans">{{ isMac ? '⌘↵' : 'Ctrl ↵' }}</kbd> all results</span>
        <span><kbd class="font-sans">esc</kbd> close</span>
        <span v-if="voiceSupported" class="ml-auto"><kbd class="font-sans">hold space</kbd> dictate</span>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, inject, nextTick, watch, onBeforeUnmount, type ComputedRef } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArchiveBoxIcon } from '@heroicons/vue/24/outline'
import ToolIcon from '../tools/ToolIcon.vue'
import { MediaImage } from '../media'
import VoiceInputButton from '../voice/VoiceInputButton.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import {
  useGlobalSearch,
  useGlobalSearchFocusSignal,
  openSearchResult,
  matchSegments,
  type EntitySearchResults,
  type MediaSearchHit,
  type SearchResultKind,
} from '../../composables/useGlobalSearch'
import { recentEntities, type RecentEntity } from '../../composables/useRecentEntities'
import { useProvidersApi, type ProviderTool } from '../../composables/useProvidersApi'
import { supported as voiceSupported } from '../../composables/useVoiceInput'
import { useTelemetry } from '../../composables/useTelemetry'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { formatRelativeTime } from '../../utils/timeFormat'

interface SelectableItem {
  key: string
  kind: SearchResultKind | 'asset' | 'browse-prompt' | 'browse-visual'
  label: string
  sub?: string
  meta?: string
  /** Provider treatment (tools): name with Stimma Cloud branding when cloud. */
  provider?: { name: string; cloud: boolean }
  /** Which asset flavor this thumbnail belongs to (assets only). */
  set?: 'prompt' | 'visual'
  highlight?: boolean
  data: any
  index: number
}

interface Section {
  title: string
  items: SelectableItem[]
  strip?: boolean
}

function isEscapeKind(kind: SelectableItem['kind']): boolean {
  return kind === 'browse-prompt' || kind === 'browse-visual'
}

const DROPDOWN_ENTITY_LIMIT = 5
const DROPDOWN_TOOL_LIMIT = 6
const DROPDOWN_MEDIA_LIMIT = 6
const DEBOUNCE_MS = 150

const router = useRouter()
const route = useRoute()
const { searchEntities, searchTools, searchMediaByPrompt, searchMediaVisual } = useGlobalSearch()
const { fetchProvidersAndTools } = useProvidersApi()
const { getProject } = useMediaApi()
const { track } = useTelemetry()
const focusSignal = useGlobalSearchFocusSignal()

// Result kinds are a closed enum; query text is never tracked.
function trackResultOpened(kind: string) {
  track('search_result_opened', {
    kind,
    surface: 'dropdown',
    scoped: !!scopeProject.value,
  }, 'feature')
}

const isMac = navigator.platform.toUpperCase().includes('MAC')

const inputRef = ref<HTMLInputElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)
const voiceBtn = ref<any>(null)
const query = ref('')
const isOpen = ref(false)
const loading = ref(false)
const selectedIndex = ref(0)

// Project scope chip. Seeded from the app-level project context (same
// resolution as the ProjectScopeBar) each time the dropdown opens fresh;
// removable per-session via the chip's ✕ or Backspace on an empty input.
const injectedProjectScope = inject<ComputedRef<{ id: number; name: string } | null>>(
  'searchProjectScope',
  computed(() => null),
)
const scopeProject = ref<{ id: number; name: string } | null>(null)

const entityResults = ref<EntitySearchResults | null>(null)
const toolResults = ref<ProviderTool[]>([])
const promptMediaResults = ref<MediaSearchHit[]>([])
const visualMediaResults = ref<MediaSearchHit[]>([])
const toolById = ref<Map<string, ProviderTool>>(new Map())
const recents = ref<RecentEntity[]>([])

// --- Voice wiring (standard hold-space contract) ---
function getQueryText() { return query.value }
function setQueryText(text: string) { query.value = text }
function focusInput() { inputRef.value?.focus() }

// --- Sections ---

const RECENT_TYPE_LABELS: Record<string, string> = {
  tool: 'Tool', chat: 'Chat', board: 'Board', project: 'Project', flow: 'Flow',
}

const sections = computed<Section[]>(() => {
  let index = 0
  const next = (item: Omit<SelectableItem, 'index'>): SelectableItem => ({ ...item, index: index++ })
  const result: Section[] = []

  if (!query.value.trim()) {
    if (recents.value.length > 0) {
      result.push({
        title: 'Recent',
        items: recents.value.map(r => {
          const time = formatRelativeTime(new Date(r.lastVisited).toISOString())
          if (r.type === 'tool') {
            const tool = toolById.value.get(r.id)
            return next({
              key: `recent:tool:${r.id}`,
              kind: 'tool',
              label: tool?.name || r.name,
              provider: tool ? { name: tool.provider_name, cloud: isStimmaCloudTool(tool) } : undefined,
              meta: time,
              data: { full_tool_id: r.id },
            })
          }
          return next({
            key: `recent:${r.type}:${r.id}`,
            kind: r.type,
            label: r.name,
            meta: `${RECENT_TYPE_LABELS[r.type]} · ${time}`,
            data: { id: r.id },
          })
        }),
      })
    }
    return result
  }

  const e = entityResults.value
  if (toolResults.value.length > 0) {
    result.push({
      title: 'Tools',
      items: toolResults.value.map(t => next({
        key: `tool:${t.full_tool_id}`,
        kind: 'tool',
        label: t.name,
        provider: { name: t.provider_name, cloud: isStimmaCloudTool(t) },
        highlight: true,
        data: t,
      })),
    })
  }
  const entitySections: Array<[string, SearchResultKind, keyof EntitySearchResults]> = [
    ['Chats', 'chat', 'chats'],
    ['Flows', 'flow', 'flows'],
    ['Boards', 'board', 'boards'],
    ['Projects', 'project', 'projects'],
    ['Presets', 'preset', 'presets'],
  ]
  for (const [title, kind, field] of entitySections) {
    const hits = (e?.[field] as any[]) || []
    if (!Array.isArray(hits) || hits.length === 0) continue
    result.push({
      title,
      items: hits.map((hit: any) => next({
        key: `${kind}:${hit.id}`,
        kind,
        label: hit.name || `Untitled ${kind}`,
        sub: kind === 'preset' ? (toolById.value.get(hit.tool_id)?.name || undefined) : undefined,
        meta: hit.updated_at ? formatRelativeTime(hit.updated_at) : undefined,
        highlight: true,
        data: hit,
      })),
    })
  }
  // The app's asset-search duality: prompt text vs CLIP visual similarity.
  if (promptMediaResults.value.length > 0) {
    result.push({
      title: 'Prompt matches',
      strip: true,
      items: promptMediaResults.value.map(m => next({
        key: `asset:prompt:${m.id}`,
        kind: 'asset',
        label: '',
        set: 'prompt',
        data: m,
      })),
    })
  }
  if (visualMediaResults.value.length > 0) {
    result.push({
      title: 'Visual matches',
      strip: true,
      items: visualMediaResults.value.map(m => next({
        key: `asset:visual:${m.id}`,
        kind: 'asset',
        label: '',
        set: 'visual',
        data: m,
      })),
    })
  }
  const scopeSuffix = scopeProject.value
    ? ` in ${scopeProject.value.name || 'this project'}`
    : ''
  result.push({
    title: 'Library',
    items: [
      next({
        key: 'browse-prompt',
        kind: 'browse-prompt',
        label: `View all prompt matches${scopeSuffix} for “${query.value.trim()}”`,
        meta: 'Browse',
        data: null,
      }),
      next({
        key: 'browse-visual',
        kind: 'browse-visual',
        label: `View all visual matches${scopeSuffix} for “${query.value.trim()}”`,
        meta: 'Browse',
        data: null,
      }),
    ],
  })
  return result
})

const flatItems = computed<SelectableItem[]>(() => sections.value.flatMap(s => s.items))

// --- Search execution ---

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let searchSeq = 0

watch(query, () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(runSearch, DEBOUNCE_MS)
})

async function runSearch() {
  const q = query.value.trim()
  const seq = ++searchSeq
  if (!q) {
    entityResults.value = null
    toolResults.value = []
    promptMediaResults.value = []
    visualMediaResults.value = []
    selectedIndex.value = 0
    return
  }
  loading.value = true
  try {
    // Entity + tool matches land together; the two asset flavors fill in
    // after so they never delay the navigational hits.
    const projectId = scopeProject.value?.id ?? null
    const [entities, tools] = await Promise.all([
      searchEntities(q, DROPDOWN_ENTITY_LIMIT, projectId).catch(() => null),
      searchTools(q, DROPDOWN_TOOL_LIMIT).catch(() => []),
    ])
    if (seq !== searchSeq) return
    entityResults.value = entities
    toolResults.value = tools
    selectedIndex.value = 0
    if (entities && entities.presets.length > 0) void ensureToolCatalog()
    searchMediaByPrompt(q, DROPDOWN_MEDIA_LIMIT, projectId).then(items => {
      if (seq === searchSeq) promptMediaResults.value = items
    }).catch(() => {})
    searchMediaVisual(q, DROPDOWN_MEDIA_LIMIT, projectId).then(items => {
      if (seq === searchSeq) visualMediaResults.value = items
    }).catch(() => {})
  } finally {
    if (seq === searchSeq) loading.value = false
  }
}

async function ensureToolCatalog() {
  if (toolById.value.size > 0) return
  try {
    const { tools } = await fetchProvidersAndTools()
    toolById.value = new Map(tools.map(t => [t.full_tool_id, t]))
  } catch {}
}

/** Resolve the full catalog tool for ToolIcon; sidebar-style fallback shape. */
function toolForIcon(item: SelectableItem): any {
  const id = item.data?.full_tool_id
  const catalogTool = id ? toolById.value.get(id) : undefined
  if (catalogTool) return catalogTool
  if (item.data?.provider_id) return item.data // search results carry the full ProviderTool
  return { id, full_tool_id: id, task_types: [] }
}

// --- Open/close ---

function openDropdown() {
  // Seed the scope chip from the current project on a fresh open only, so
  // removing it mid-session sticks until the dropdown is closed and reopened.
  // On the /search page itself there is no project chrome — inherit the
  // page's own scope (?project=) so the chip stays coherent with it.
  if (!isOpen.value) {
    const project = injectedProjectScope.value
    if (project) {
      scopeProject.value = { id: project.id, name: project.name || '' }
    } else if (route.name === 'search' && route.query.project) {
      const id = parseInt(String(route.query.project), 10)
      if (Number.isFinite(id)) {
        scopeProject.value = scopeProject.value?.id === id
          ? scopeProject.value
          : { id, name: '' }
        void resolveScopeName(id)
      } else {
        scopeProject.value = null
      }
    } else {
      scopeProject.value = null
    }
    track('search_opened', { scoped: !!scopeProject.value }, 'feature')
  }
  recents.value = recentEntities(8)
  isOpen.value = true
  selectedIndex.value = 0
  // Recents tool rows resolve display name / provider / mark from the catalog.
  void ensureToolCatalog()
}

function clearScope() {
  scopeProject.value = null
  inputRef.value?.focus()
  void runSearch()
}

async function resolveScopeName(id: number) {
  try {
    const project = await getProject(id)
    if (scopeProject.value?.id === id && project?.name) {
      scopeProject.value = { id, name: project.name }
    }
  } catch {}
}

function closeDropdown() {
  isOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
  if (!(event.target as HTMLElement).closest('.global-search-box')) closeDropdown()
}

watch(isOpen, open => {
  if (open) {
    setTimeout(() => document.addEventListener('click', handleClickOutside, true), 0)
  } else {
    document.removeEventListener('click', handleClickOutside, true)
  }
})

// Keep the keyboard selection visible in the scrollable dropdown.
watch(selectedIndex, async (idx) => {
  await nextTick()
  dropdownRef.value
    ?.querySelector(`[data-search-idx="${idx}"]`)
    ?.scrollIntoView({ block: 'nearest' })
})

// Close on navigation and when Cmd+K is pressed anywhere.
watch(() => route.fullPath, closeDropdown)
watch(focusSignal, () => {
  inputRef.value?.focus()
  inputRef.value?.select()
  openDropdown()
})

// --- Keyboard ---

function handleKeydown(e: KeyboardEvent) {
  // Hold-space dictation (quick space types normally).
  voiceBtn.value?.handleInputKeydown(e)
  if (e.defaultPrevented) return

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    if (!isOpen.value) { openDropdown(); return }
    const count = flatItems.value.length
    if (count === 0) return
    const delta = e.key === 'ArrowDown' ? 1 : -1
    selectedIndex.value = (selectedIndex.value + delta + count) % count
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const q = query.value.trim()
    if ((e.metaKey || e.ctrlKey) && q) {
      goToFullResults()
      return
    }
    const item = flatItems.value[selectedIndex.value]
    if (item) activateItem(item)
    else if (q) goToFullResults()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    closeDropdown()
    inputRef.value?.blur()
  } else if (e.key === 'Backspace' && !query.value && scopeProject.value) {
    e.preventDefault()
    clearScope()
  }
}

function handleKeyup(e: KeyboardEvent) {
  voiceBtn.value?.handleInputKeyup(e)
}

// --- Activation ---

function scopeQuery(): Record<string, string> {
  return scopeProject.value ? { project: String(scopeProject.value.id) } : {}
}

function goToFullResults() {
  const q = query.value.trim()
  if (!q) return
  trackResultOpened('all_results')
  cancelDictation()
  closeDropdown()
  inputRef.value?.blur()
  router.push({ name: 'search', query: { q, ...scopeQuery() } })
}

// Abort dictation whenever the input loses focus mid-hold — otherwise the
// space keyup never reaches the input and the mic keeps recording.
function cancelDictation() {
  voiceBtn.value?.cancel?.()
}

function handleInputBlur() {
  cancelDictation()
}

function activateItem(item: SelectableItem) {
  trackResultOpened(item.kind.replace('-', '_'))
  cancelDictation()
  if (item.kind === 'asset') {
    // Slideshows live inside the content area (sidebar stays visible) — hand
    // off to the search page, which opens its inline slideshow on this item
    // within the matching asset flavor's result set.
    const q = query.value.trim()
    closeDropdown()
    inputRef.value?.blur()
    router.push({
      name: 'search',
      query: { q, slideshow: String(item.data.id), sset: item.set || 'prompt', ...scopeQuery() },
    })
    return
  }
  closeDropdown()
  inputRef.value?.blur()
  if (isEscapeKind(item.kind)) {
    // Prompt matches → browse's prompt filter; visual matches → CLIP text
    // search. Scope carries into the filter cart as the project filter.
    const browseQuery: Record<string, string> =
      item.kind === 'browse-prompt'
        ? { pq: query.value.trim() }
        : { stt: query.value.trim() }
    if (scopeProject.value) browseQuery.prj = String(scopeProject.value.id)
    router.push({ name: 'browse', query: browseQuery })
    return
  }
  openSearchResult(router, item.kind as SearchResultKind, item.data, scopeProject.value?.id ?? null)
}

// --- Plain stroke glyphs, matching the sidebar's nav icons exactly ---

const CHAT_ICON = 'M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155'
const FLOW_ICON = 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z'
const PRESET_ICON = 'M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75'
const SEARCH_ICON = 'M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z'

function iconPathFor(item: SelectableItem): string {
  if (item.kind === 'chat') return CHAT_ICON
  if (item.kind === 'flow') return FLOW_ICON
  if (item.kind === 'preset') return PRESET_ICON
  return SEARCH_ICON
}

// --- Lifecycle ---

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  document.removeEventListener('click', handleClickOutside, true)
})
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
