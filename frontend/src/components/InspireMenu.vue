<template>
  <div class="relative" ref="containerRef">
    <button
      @click="toggleMenu"
      class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-overlay-light hover:border-edge"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 flex-shrink-0">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 0 0-3.7-3.7 48.678 48.678 0 0 0-7.324 0 4.006 4.006 0 0 0-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 0 0 3.7 3.7 48.656 48.656 0 0 0 7.324 0 4.006 4.006 0 0 0 3.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3-3 3" />
      </svg>
      <span>Remix</span>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 ml-auto text-content-tertiary">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <Teleport to="body">
      <!-- SVG gradient definition for Stimma Cloud branding (must be inside Teleport to be accessible) -->
      <svg class="absolute w-0 h-0" aria-hidden="true">
        <defs>
          <linearGradient id="stimma-gradient-remix" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0d9488" />
            <stop offset="50%" stop-color="#06b6d4" />
            <stop offset="100%" stop-color="#6366f1" />
          </linearGradient>
        </defs>
      </svg>
      <div
        v-if="showMenu"
        ref="menuRef"
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[9999] py-1 min-w-[200px] max-h-[400px] overflow-y-auto"
        :style="menuStyle"
      >
        <!-- Filter box -->
        <div class="px-2 py-1.5 border-b border-edge-subtle">
          <div class="relative">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted">
              <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
            </svg>
            <input
              ref="searchInputRef"
              v-model="searchQuery"
              type="text"
              placeholder="Filter tools..."
              class="w-full bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
            />
          </div>
        </div>

        <!-- Original tool section (if exists) -->
        <template v-if="!searchQuery.trim() && originalTool">
          <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
            Original
          </div>
          <button
            @click="sendToTool(originalTool)"
            class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(originalTool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(originalTool) ? 'url(#stimma-gradient-remix)' : 'currentColor'" overflow="visible">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <div class="flex-1 min-w-0">
              <div class="truncate">{{ originalTool.name }}</div>
              <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(originalTool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ originalTool.provider_name }}</div>
            </div>
          </button>
          <div class="border-t border-edge-subtle my-1"></div>
        </template>

        <!-- Active tool instances: eligible open tool tabs (incl. renamed
             stations), targeted exactly. Mirrors Send to Tool's section. -->
        <template v-if="filteredOpenInstances.length > 0">
          <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
            Active Tools
          </div>
          <button
            v-for="row in filteredOpenInstances"
            :key="`instance-${row.tab.id}`"
            @click="sendToToolInstance(row)"
            class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(row.tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(row.tool) ? 'url(#stimma-gradient-remix)' : 'currentColor'" overflow="visible">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <div class="flex-1 min-w-0">
              <div class="truncate">{{ row.tab.customName || row.tab.displayName }}</div>
              <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(row.tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ row.tool.provider_name }}</div>
            </div>
            <span
              v-if="row.tab.projectName"
              class="flex-shrink-0 text-[9px] text-content-tertiary bg-overlay-subtle rounded px-1 py-0.5 truncate max-w-[70px]"
            >{{ row.tab.projectName }}</span>
          </button>
          <div class="border-t border-edge-subtle my-1"></div>
        </template>

        <div v-if="loadingTools" class="px-3 py-2 text-xs text-content-tertiary">
          Loading tools...
        </div>
        <div v-else-if="tools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
          No tools available
        </div>
        <template v-else-if="searchQuery.trim()">
          <!-- Filtered results (flat, no sections) -->
          <div v-if="filteredTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
            No matching tools
          </div>
          <button
            v-for="tool in filteredTools"
            :key="tool.full_tool_id"
            @click="sendToTool(tool)"
            class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-remix)' : 'currentColor'" overflow="visible">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <div class="flex-1 min-w-0">
              <div class="truncate">{{ tool.name }}</div>
              <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ tool.provider_name }}</div>
            </div>
          </button>
        </template>
        <template v-else>
          <!-- Recent tools section -->
          <template v-if="recentTools.length > 0">
            <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
              Recent
            </div>
            <button
              v-for="tool in recentTools"
              :key="`recent-${tool.full_tool_id}`"
              @click="sendToTool(tool)"
              class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-remix)' : 'currentColor'" overflow="visible">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
              </svg>
              <div class="flex-1 min-w-0">
                <div class="truncate">{{ tool.name }}</div>
                <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ tool.provider_name }}</div>
              </div>
            </button>
          </template>

          <!-- All tools section -->
          <div v-if="recentTools.length > 0" class="border-t border-edge-subtle my-1"></div>
          <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
            {{ originalTool ? 'All Tools' : 'Tools' }}
          </div>
          <button
            v-for="tool in otherTools"
            :key="tool.full_tool_id"
            @click="sendToTool(tool)"
            class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-remix)' : 'currentColor'" overflow="visible">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <div class="flex-1 min-w-0">
              <div class="truncate">{{ tool.name }}</div>
              <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'">{{ tool.provider_name }}</div>
            </div>
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { makeStorageKey } from '../utils/storageKeys'
import { useAnchoredMenuPosition } from '../composables/useContextMenuPosition'
import { useWorkspaceTabs, toolTabRoute, type WorkspaceTab } from '../composables/useWorkspaceTabs'

interface RemixTool {
  full_tool_id: string
  name: string
  task_type: string
  provider_id: string
  provider_name: string
  metadata: Record<string, any>
  subtitle?: string
  is_original: boolean
}

interface Props {
  mediaId: number
}

const RECENT_STORAGE_KEY = 'remix' as const
const MAX_RECENT = 5

function getRecentTools(): string[] {
  try {
    const key = makeStorageKey(RECENT_STORAGE_KEY, 'recent')
    const stored = localStorage.getItem(key)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function addRecentTool(toolId: string) {
  try {
    const key = makeStorageKey(RECENT_STORAGE_KEY, 'recent')
    const recent = getRecentTools().filter(id => id !== toolId)
    recent.unshift(toolId)
    localStorage.setItem(key, JSON.stringify(recent.slice(0, MAX_RECENT)))
  } catch {
    // Ignore storage errors
  }
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'sent'): void
}>()

const router = useRouter()

const showMenu = ref(false)
const loadingTools = ref(false)
const tools = ref<RemixTool[]>([])
const containerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
// Viewport-aware placement below/above the trigger, clamped and height-capped
const anchorRect = ref<DOMRect | null>(null)
const { menuStyle: anchoredStyle } = useAnchoredMenuPosition(menuRef, anchorRect, showMenu)
const menuStyle = computed(() => ({
  ...anchoredStyle.value,
  minWidth: `${Math.max(anchorRect.value?.width ?? 0, 200)}px`,
}))
const searchQuery = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)

// Split tools into original and others
const originalTool = computed(() => tools.value.find(t => t.is_original))
const otherTools = computed(() => tools.value.filter(t => !t.is_original))

// Recent tools (from non-original tools, ordered by recency)
const recentTools = computed(() => {
  const recentIds = getRecentTools()
  if (recentIds.length === 0) return []
  const originalId = originalTool.value?.full_tool_id
  return recentIds
    .filter(id => id !== originalId)
    .map(id => tools.value.find(t => t.full_tool_id === id))
    .filter((t): t is RemixTool => !!t)
})

// Eligible open tool-instance tabs (incl. renamed stations), most-recently-
// active first. Eligibility = the tool appears in the remix tool list; each
// row targets its exact tab, which is the only way remix reaches named
// instances (instance resolution skips them by design).
const { tabs: workspaceTabs } = useWorkspaceTabs()
const openInstances = computed(() => {
  const toolById = new Map(tools.value.map(t => [t.full_tool_id, t]))
  return (workspaceTabs.value as WorkspaceTab[])
    .filter(t => t.type === 'tool' && !!t.instanceId && toolById.has(t.entityId))
    .sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0))
    .slice(0, 5)
    .map(tab => ({ tab, tool: toolById.get(tab.entityId)! }))
})

const filteredOpenInstances = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return openInstances.value
  return openInstances.value.filter(({ tab, tool }) =>
    (tab.customName || '').toLowerCase().includes(query) ||
    tab.displayName.toLowerCase().includes(query) ||
    tool.provider_name.toLowerCase().includes(query)
  )
})

// Filtered tools (search across all tools)
const filteredTools = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return tools.value
  return tools.value.filter(t =>
    t.name.toLowerCase().includes(query) ||
    t.provider_name.toLowerCase().includes(query)
  )
})

// Auto-focus search input when menu opens
watch(showMenu, async (visible) => {
  if (visible) {
    searchQuery.value = ''
    await nextTick()
    searchInputRef.value?.focus()
  }
})

async function toggleMenu() {
  if (showMenu.value) {
    showMenu.value = false
    return
  }

  if (containerRef.value) {
    anchorRect.value = containerRef.value.getBoundingClientRect()
  }
  showMenu.value = true
  loadingTools.value = true

  try {
    // Always fetch fresh - the endpoint sorts with original tool first
    const response = await axios.get(`/api/tools/remix-tools/${props.mediaId}`)
    tools.value = response.data
  } catch (err) {
    console.error('Failed to load tools:', err)
  } finally {
    loadingTools.value = false
  }
}

function sendToTool(tool: RemixTool) {
  showMenu.value = false
  addRecentTool(tool.full_tool_id)

  // Navigate immediately - ToolView will fetch the config and show loading state
  router.push({
    name: 'tool',
    params: { fullToolId: tool.full_tool_id },
    query: {
      remixFrom: props.mediaId.toString(),
      _ts: Date.now().toString()  // Force route change detection for KeepAlive'd components
    }
  })
  emit('sent')
}

function sendToToolInstance(row: { tab: WorkspaceTab; tool: RemixTool }) {
  showMenu.value = false

  // Instance rows target that exact tab (its project scope rides along).
  router.push(toolTabRoute(row.tab, {
    remixFrom: props.mediaId.toString(),
    _ts: Date.now().toString()
  }))
  emit('sent')
}

// Close menu when clicking outside
function handleClickOutside(event: MouseEvent) {
  if (!showMenu.value) return
  const target = event.target as Element
  if (containerRef.value?.contains(target)) return
  if (menuRef.value?.contains(target)) return
  showMenu.value = false
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
