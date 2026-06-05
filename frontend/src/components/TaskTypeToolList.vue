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
          @mousedown.stop
          @click.stop
        />
      </div>
    </div>

    <div v-if="loading" class="px-3 py-2 text-xs text-content-tertiary">
      Loading tools...
    </div>
    <div v-else-if="eligibleTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
      No compatible tools
    </div>
    <template v-else-if="searchQuery.trim()">
      <!-- Filtered results (flat, no section headers) -->
      <div v-if="filteredTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
        No matching tools
      </div>
      <button
        v-for="tool in filteredTools"
        :key="tool.full_tool_id"
        @click="handleToolClick(tool, getToolPrimaryTaskType(tool))"
        class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? `url(#${gradientId})` : 'currentColor'" overflow="visible">
          <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(getToolPrimaryTaskType(tool))" />
        </svg>
        <div class="flex-1 min-w-0">
          <div class="truncate">{{ tool.name }}</div>
          <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
        </div>
      </button>
    </template>
    <template v-else-if="!selectedTaskType">
      <!-- Task type category list -->
      <template v-for="(taskType, index) in taskTypeKeys" :key="taskType">
        <div v-if="index > 0" class="border-t border-edge-subtle my-1"></div>

        <button
          @click="selectTaskType(taskType)"
          class="w-full px-3 py-1.5 text-left text-xs hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(taskType)" />
          </svg>
          <span class="flex-1 font-medium text-content">{{ formatTaskTypeLabel(taskType) }}</span>
          <span class="text-[10px] text-content-muted">{{ groupedTools[taskType].length }}</span>
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
        class="w-full px-3 py-1.5 text-left text-xs hover:bg-overlay-light flex items-center gap-2 border-b border-edge-subtle"
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
        <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
          Recents
        </div>
        <button
          v-for="tool in recentToolsForSelectedTaskType"
          :key="`recent-${selectedTaskType}-${tool.full_tool_id}`"
          @click="handleToolClick(tool, selectedTaskType)"
          class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? `url(#${gradientId})` : 'currentColor'" overflow="visible">
            <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(selectedTaskType)" />
          </svg>
          <div class="flex-1 min-w-0">
            <div class="truncate">{{ tool.name }}</div>
            <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
          </div>
        </button>
        <div class="border-t border-edge-subtle my-1"></div>
      </template>

      <!-- All tools in this category -->
      <div
        v-if="recentToolsForSelectedTaskType.length > 0"
        class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider"
      >
        All Tools
      </div>
      <button
        v-for="tool in allToolsForSelectedTaskType"
        :key="`${selectedTaskType}-${tool.full_tool_id}`"
        @click="handleToolClick(tool, selectedTaskType)"
        class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? `url(#${gradientId})` : 'currentColor'" overflow="visible">
          <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(selectedTaskType)" />
        </svg>
        <div class="flex-1 min-w-0">
          <div class="truncate">{{ tool.name }}</div>
          <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
        </div>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { ProviderTool } from '../composables/useProvidersApi'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { makeStorageKey } from '../utils/storageKeys'
import {
  getTaskTypeIconPath,
  formatTaskTypeLabel,
  TASK_TYPE_ORDER,
  getEligibleTaskTypesForMediaType
} from '../utils/taskTypeIcons'
import type { MediaType } from '../utils/mediaTypes'

const RECENT_STORAGE_KEY = 'send-to-tool' as const
const MAX_RECENT = 5

interface Props {
  tools: ProviderTool[]
  mediaType?: MediaType | null
  loading?: boolean
  gradientId?: string
}

const props = withDefaults(defineProps<Props>(), {
  mediaType: null,
  loading: false,
  gradientId: 'stimma-gradient-tools'
})

const emit = defineEmits<{
  (e: 'select', tool: ProviderTool, taskType: string): void
}>()

const searchQuery = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)
const selectedTaskType = ref<string | null>(null)

// Filter tools based on media type (null = show all tools), hiding unavailable tools
const eligibleTools = computed(() => {
  const available = props.tools.filter(t => t.availability === 'available')
  if (props.mediaType == null) return available
  const eligibleTaskTypes = getEligibleTaskTypesForMediaType(props.mediaType)
  if (eligibleTaskTypes.length === 0) return []
  return available.filter(t => {
    const toolTaskTypes = t.task_types?.length ? t.task_types : (t.task_type ? [t.task_type] : [])
    return toolTaskTypes.some(tt => eligibleTaskTypes.includes(tt))
  })
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
  const eligibleTaskTypes = props.mediaType != null ? getEligibleTaskTypesForMediaType(props.mediaType) : null
  for (const tool of sorted) {
    const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    for (const taskType of toolTaskTypes) {
      if (eligibleTaskTypes && !eligibleTaskTypes.includes(taskType)) continue
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

// Get the first eligible task type for a tool (used in flat search results)
function getToolPrimaryTaskType(tool: ProviderTool): string {
  const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
  if (props.mediaType == null) return toolTaskTypes[0] || tool.task_type || ''
  const eligibleTaskTypes = getEligibleTaskTypesForMediaType(props.mediaType)
  return toolTaskTypes.find(tt => eligibleTaskTypes.includes(tt)) || tool.task_type || ''
}

function selectTaskType(taskType: string) {
  selectedTaskType.value = taskType
}

function handleToolClick(tool: ProviderTool, taskType: string) {
  if (taskType) {
    addRecentToolForTaskType(taskType, tool.full_tool_id)
  }
  emit('select', tool, taskType)
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
