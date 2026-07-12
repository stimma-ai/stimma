<template>
  <div>
    <!-- SVG gradient definition for Stimma Cloud branding -->
    <svg class="absolute w-0 h-0" aria-hidden="true">
      <defs>
        <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0d9488" />
          <stop offset="50%" stop-color="#06b6d4" />
          <stop offset="100%" stop-color="#6366f1" />
        </linearGradient>
      </defs>
    </svg>

    <!-- Filter box -->
    <div class="px-2.5 py-2 border-b border-edge-subtle">
      <div class="relative">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-content-muted">
          <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
        </svg>
        <input
          ref="searchInputRef"
          v-model="searchQuery"
          type="text"
          placeholder="Filter tools..."
          class="w-full bg-overlay-subtle border border-edge-subtle rounded-md px-2.5 py-1.5 pl-8 text-[13px] text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
          @mousedown.stop
          @click.stop
        />
      </div>
    </div>

    <!-- Open instances: eligible open tool tabs, targeted exactly. Shown at
         the top level and while filtering; gated behind showOpenInstances so
         settings-style pickers don't grow workspace rows. -->
    <template v-if="showOpenInstances && !selectedTaskType && filteredOpenInstances.length > 0">
      <div class="px-3.5 pt-2.5 pb-1 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
        Active Tools
      </div>
      <button
        v-for="row in filteredOpenInstances"
        :key="`instance-${row.tab.id}`"
        @click="handleInstanceClick(row, $event)"
        class="group w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-light flex items-center gap-2.5"
      >
        <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(row.tool) ? '' : 'text-content-tertiary'">
          <ToolIcon :tool="row.tool" size="xs" :bare="true" :ring="false" />
        </div>
        <span class="flex-1 min-w-0 truncate">{{ row.tab.customName || row.tab.displayName }}<svg v-if="shiftAdds && shiftHeld" class="inline-block w-3.5 h-3.5 ml-1.5 align-[-2px] text-green-400 opacity-0 group-hover:opacity-100" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg></span>
        <span
          v-if="row.tab.projectName"
          class="flex-shrink-0 text-[9px] text-content-tertiary bg-overlay-subtle rounded px-1 py-0.5 truncate max-w-[70px]"
        >{{ row.tab.projectName }}</span>
        <ToolProviderLabel :cloud="isStimmaCloudTool(row.tool)" :provider-name="row.tool.provider_name" class="pl-3" />
      </button>
      <div class="border-t border-edge-subtle my-1"></div>
    </template>

    <div v-if="loading" class="px-3 py-2 text-xs text-content-tertiary">
      Loading tools...
    </div>
    <div v-else-if="eligibleTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
      No compatible tools
    </div>
    <template v-else-if="searchQuery.trim()">
      <!-- Filtered results (flat) -->
      <div v-if="showAllToolsHeader && filteredTools.length > 0" class="px-3.5 pt-2.5 pb-1 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
        All Tools
      </div>
      <div v-if="filteredTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
        No matching tools
      </div>
      <button
        v-for="tool in filteredTools"
        :key="tool.full_tool_id"
        @click="handleToolClick(tool, getToolPrimaryTaskType(tool), $event)"
        class="group w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-light flex items-center gap-2.5"
      >
        <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
          <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
        </div>
        <span class="flex-1 min-w-0 truncate">{{ tool.name }}<svg v-if="shiftAdds && shiftHeld" class="inline-block w-3.5 h-3.5 ml-1.5 align-[-2px] text-green-400 opacity-0 group-hover:opacity-100" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg></span>
        <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
      </button>
    </template>
    <template v-else-if="!selectedTaskType">
      <!-- Task type category list -->
      <div v-if="showAllToolsHeader" class="px-3.5 pt-2.5 pb-1 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
        All Tools
      </div>
      <template v-for="taskType in taskTypeKeys" :key="taskType">
        <button
          @click="selectTaskType(taskType)"
          class="w-full px-3.5 py-2 text-left text-[13px] hover:bg-overlay-light flex items-center gap-2.5"
        >
          <svg class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(taskType)" />
          </svg>
          <span class="flex-1 font-medium text-content">{{ formatTaskTypeLabel(taskType) }}</span>
          <span class="text-[11.5px] text-content-muted tabular-nums">{{ groupedTools[taskType].length }}</span>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
            <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
          </svg>
        </button>
      </template>
    </template>
    <template v-else>
      <!-- Drilled-in tool list for selected task type -->
      <!-- Back header -->
      <button
        @click="selectedTaskType = null"
        class="w-full px-3.5 py-2 text-left text-[13px] hover:bg-overlay-light flex items-center gap-2.5 border-b border-edge-subtle"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
          <path fill-rule="evenodd" d="M11.78 5.22a.75.75 0 0 1 0 1.06L8.06 10l3.72 3.72a.75.75 0 1 1-1.06 1.06l-4.25-4.25a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0Z" clip-rule="evenodd" />
        </svg>
        <svg class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(selectedTaskType)" />
        </svg>
        <span class="flex-1 font-medium text-content">{{ formatTaskTypeLabel(selectedTaskType) }}</span>
      </button>

      <!-- Recent section -->
      <template v-if="recentToolsForSelectedTaskType.length > 0">
        <div class="px-3.5 pt-2.5 pb-1 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
          Recents
        </div>
        <button
          v-for="tool in recentToolsForSelectedTaskType"
          :key="`recent-${selectedTaskType}-${tool.full_tool_id}`"
          @click="handleToolClick(tool, selectedTaskType, $event)"
          class="group w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-light flex items-center gap-2.5"
        >
          <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
            <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
          </div>
          <span class="flex-1 min-w-0 truncate">{{ tool.name }}<svg v-if="shiftAdds && shiftHeld" class="inline-block w-3.5 h-3.5 ml-1.5 align-[-2px] text-green-400 opacity-0 group-hover:opacity-100" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg></span>
          <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
        </button>
        <div class="border-t border-edge-subtle my-1"></div>
      </template>

      <!-- All tools in this category -->
      <div
        v-if="recentToolsForSelectedTaskType.length > 0"
        class="px-3.5 pt-2.5 pb-1 text-[10px] font-semibold text-content-muted uppercase tracking-wider"
      >
        All Tools
      </div>
      <button
        v-for="tool in allToolsForSelectedTaskType"
        :key="`${selectedTaskType}-${tool.full_tool_id}`"
        @click="handleToolClick(tool, selectedTaskType, $event)"
        class="group w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-light flex items-center gap-2.5"
      >
        <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
          <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
        </div>
        <span class="flex-1 min-w-0 truncate">{{ tool.name }}<svg v-if="shiftAdds && shiftHeld" class="inline-block w-3.5 h-3.5 ml-1.5 align-[-2px] text-green-400 opacity-0 group-hover:opacity-100" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg></span>
        <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import type { ProviderTool } from '../composables/useProvidersApi'
import { useWorkspaceTabs, type WorkspaceTab } from '../composables/useWorkspaceTabs'
import ToolIcon from './tools/ToolIcon.vue'
import ToolProviderLabel from './tools/ToolProviderLabel.vue'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { makeStorageKey } from '../utils/storageKeys'
import {
  getTaskTypeIconPath,
  formatTaskTypeLabel,
  TASK_TYPE_ORDER,
} from '../utils/taskTypeIcons'
import type { MediaType } from '../utils/mediaTypes'
import { planToolHandoff } from '../utils/toolHandoff'

const RECENT_STORAGE_KEY = 'send-to-tool' as const
const MAX_RECENT = 5

interface Props {
  tools: ProviderTool[]
  mediaType?: MediaType | null
  mediaTypes?: MediaType[]
  selectionCount?: number
  loading?: boolean
  gradientId?: string
  /** List eligible open tool-instance tabs first (send-to-tool surfaces). */
  showOpenInstances?: boolean
  /** Shift-click adds to the tool's inputs instead of replacing; shows a green
      + on the hovered row while shift is held (send-to-tool surfaces). */
  shiftAdds?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  mediaType: null,
  selectionCount: 1,
  loading: false,
  gradientId: 'stimma-gradient-tools',
  showOpenInstances: false,
  shiftAdds: false
})

const emit = defineEmits<{
  (e: 'select', tool: ProviderTool, taskType: string, event?: MouseEvent): void
  (e: 'select-instance', tab: WorkspaceTab, tool: ProviderTool, taskType: string, event?: MouseEvent): void
}>()

const searchQuery = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)
const selectedTaskType = ref<string | null>(null)
const effectiveMediaTypes = computed(() =>
  props.mediaTypes?.length ? props.mediaTypes : (props.mediaType != null ? [props.mediaType] : [])
)

// Live shift state: while held, hovered rows show a green + (shift-click adds
// to the tool's inputs instead of replacing them). Mirrors shift-drag on the
// sidebar. Reset on window blur so a stale "held" state can't stick.
const shiftHeld = ref(false)
function onShiftKey(e: KeyboardEvent) {
  if (e.key === 'Shift') shiftHeld.value = e.type === 'keydown'
}
function onWindowBlur() {
  shiftHeld.value = false
}
onMounted(() => {
  if (!props.shiftAdds) return
  window.addEventListener('keydown', onShiftKey)
  window.addEventListener('keyup', onShiftKey)
  window.addEventListener('blur', onWindowBlur)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onShiftKey)
  window.removeEventListener('keyup', onShiftKey)
  window.removeEventListener('blur', onWindowBlur)
})

// Filter tools based on media type (null = show all tools), hiding unavailable tools.
// Eligibility honors per-tool x-accept-media overrides (e.g. a video-only filter).
const eligibleTools = computed(() => {
  const available = props.tools.filter(t => t.availability === 'available')
  if (effectiveMediaTypes.value.length === 0) return available
  return available.filter(t => planToolHandoff({
    tool: t,
    mediaTypes: effectiveMediaTypes.value,
    count: props.selectionCount,
  }).eligible)
})

// Group tools by task type, sorted within each group
const groupedTools = computed(() => {
  const groups: Record<string, ProviderTool[]> = {}
  const sorted = [...eligibleTools.value].sort((a, b) => {
    // Pinned first if available, then alphabetical
    const aPinned = (a as any).pinned ? 1 : 0
    const bPinned = (b as any).pinned ? 1 : 0
    if (aPinned !== bPinned) return bPinned - aPinned
    return a.name.localeCompare(b.name)
  })
  for (const tool of sorted) {
    const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    for (const taskType of toolTaskTypes) {
      if (effectiveMediaTypes.value.length > 0 && !planToolHandoff({
        tool,
        mediaTypes: effectiveMediaTypes.value,
        count: props.selectionCount,
        requestedTaskType: taskType,
      }).eligible) continue
      if (!groups[taskType]) groups[taskType] = []
      groups[taskType].push(tool)
    }
  }
  const ordered: Record<string, ProviderTool[]> = {}
  for (const taskType of TASK_TYPE_ORDER) {
    if (groups[taskType]) ordered[taskType] = groups[taskType]
  }
  // Include any task types not in the predefined order
  for (const taskType of Object.keys(groups)) {
    if (!ordered[taskType]) ordered[taskType] = groups[taskType]
  }
  return ordered
})

const taskTypeKeys = computed(() => Object.keys(groupedTools.value))

// Filtered tools (flat search across all eligible tools)
const filteredTools = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return eligibleTools.value
  return eligibleTools.value.filter(t =>
    t.name.toLowerCase().includes(query) ||
    t.provider_name.toLowerCase().includes(query)
  )
})

function getRecentToolsByTaskType(taskType: string): string[] {
  try {
    const key = makeStorageKey(RECENT_STORAGE_KEY, taskType, 'recent')
    const stored = localStorage.getItem(key)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function addRecentToolForTaskType(taskType: string, toolId: string) {
  try {
    const key = makeStorageKey(RECENT_STORAGE_KEY, taskType, 'recent')
    const recent = getRecentToolsByTaskType(taskType).filter(id => id !== toolId)
    recent.unshift(toolId)
    localStorage.setItem(key, JSON.stringify(recent.slice(0, MAX_RECENT)))
  } catch {
    // Ignore storage errors
  }
}

const recentToolsForSelectedTaskType = computed(() => {
  if (!selectedTaskType.value) return []
  const taskType = selectedTaskType.value
  const toolList = groupedTools.value[taskType] || []
  const toolById = new Map(toolList.map(tool => [tool.full_tool_id, tool]))
  return getRecentToolsByTaskType(taskType)
    .map(id => toolById.get(id))
    .filter((tool): tool is ProviderTool => !!tool)
})

const allToolsForSelectedTaskType = computed(() => {
  if (!selectedTaskType.value) return []
  const taskType = selectedTaskType.value
  const tools = groupedTools.value[taskType] || []
  if (recentToolsForSelectedTaskType.value.length === 0) return tools
  const recentIds = new Set(recentToolsForSelectedTaskType.value.map(t => t.full_tool_id))
  return tools.filter(tool => !recentIds.has(tool.full_tool_id))
})

// Eligible open tool-instance tabs, most-recently-active first. Eligibility
// is the tool's (instances inherit their tool's schema).
const { tabs: workspaceTabs } = useWorkspaceTabs()
const eligibleOpenInstances = computed(() => {
  if (!props.showOpenInstances) return []
  const toolById = new Map(eligibleTools.value.map(t => [t.full_tool_id, t]))
  return (workspaceTabs.value as WorkspaceTab[])
    .filter(t => t.type === 'tool' && !!t.instanceId && toolById.has(t.entityId))
    .sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0))
    .slice(0, 5)
    .map(tab => ({ tab, tool: toolById.get(tab.entityId)! }))
})

const filteredOpenInstances = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return eligibleOpenInstances.value
  return eligibleOpenInstances.value.filter(({ tab, tool }) =>
    (tab.customName || '').toLowerCase().includes(query) ||
    tab.displayName.toLowerCase().includes(query) ||
    tool.provider_name.toLowerCase().includes(query)
  )
})

// Show an "All Tools" header on the catalog list only when the "Active Tools"
// section is present above it, so the two sections read as a pair.
const showAllToolsHeader = computed(() =>
  props.showOpenInstances && !selectedTaskType.value && filteredOpenInstances.value.length > 0
)

function handleInstanceClick(row: { tab: WorkspaceTab; tool: ProviderTool }, event?: MouseEvent) {
  emit('select-instance', row.tab, row.tool, getToolPrimaryTaskType(row.tool), event)
}

// Get the first eligible task type for a tool (used in flat search results)
function getToolPrimaryTaskType(tool: ProviderTool): string {
  const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
  if (effectiveMediaTypes.value.length === 0) return toolTaskTypes[0] || tool.task_type || ''
  return planToolHandoff({
    tool,
    mediaTypes: effectiveMediaTypes.value,
    count: props.selectionCount,
  }).taskType || tool.task_type || ''
}

function selectTaskType(taskType: string) {
  selectedTaskType.value = taskType
}

function handleToolClick(tool: ProviderTool, taskType: string, event?: MouseEvent) {
  if (taskType) {
    addRecentToolForTaskType(taskType, tool.full_tool_id)
  }
  emit('select', tool, taskType, event)
}

// Public method: reset state and focus search
function reset() {
  searchQuery.value = ''
  const keys = taskTypeKeys.value
  selectedTaskType.value = keys.length === 1 ? keys[0] : null
  nextTick(() => {
    searchInputRef.value?.focus()
  })
}

defineExpose({ reset })
</script>

<style scoped>
.stimma-gradient-text {
  background: linear-gradient(135deg, #0d9488, #06b6d4, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 500;
}
</style>
