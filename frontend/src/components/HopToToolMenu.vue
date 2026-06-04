<template>
  <div class="relative" ref="containerRef">
    <!-- Tool name with dropdown chevron -->
    <button
      @click="toggleMenu"
      class="flex items-center gap-1 group cursor-pointer"
    >
      <h2 class="text-2xl font-semibold text-content">{{ toolName }}</h2>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        class="w-5 h-5 text-content-muted group-hover:text-content-secondary transition-colors"
        :class="{ 'rotate-180': showMenu }"
      >
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <Teleport to="body">
      <!-- SVG gradient definition for Stimma Cloud branding -->
      <svg class="absolute w-0 h-0" aria-hidden="true">
        <defs>
          <linearGradient id="stimma-gradient-hop" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0d9488" />
            <stop offset="50%" stop-color="#06b6d4" />
            <stop offset="100%" stop-color="#6366f1" />
          </linearGradient>
        </defs>
      </svg>
      <div
        v-if="showMenu"
        ref="menuRef"
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[9999] py-1 min-w-[220px] max-h-[400px] overflow-y-auto"
        :style="menuStyle"
      >
        <div v-if="loadingTools" class="px-3 py-2 text-xs text-content-tertiary">
          Loading tools...
        </div>
        <div v-else-if="Object.keys(groupedTools).length === 0" class="px-3 py-2 text-xs text-content-tertiary">
          No other compatible tools available
        </div>
        <template v-else>
          <!-- Tools grouped by task type -->
          <template v-for="(groupTools, taskType, groupIndex) in groupedTools" :key="taskType">
            <!-- Divider between groups -->
            <div v-if="groupIndex > 0" class="border-t border-edge-subtle my-1"></div>

            <!-- Group header -->
            <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
              {{ formatTaskTypeLabel(taskType as string) }}
            </div>

            <!-- Tools in this group -->
            <button
              v-for="tool in groupTools"
              :key="`${taskType}-${tool.full_tool_id}`"
              @click="hopToTool(tool)"
              class="w-full px-3 py-2 text-left text-sm text-content hover:bg-overlay-light flex items-center gap-2"
            >
              <svg class="w-4 h-4 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-hop)' : 'currentColor'" overflow="visible">
                <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(taskType as string)" />
              </svg>
              <span class="truncate flex-1">{{ tool.name }}</span>
            </button>
          </template>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import {
  getTaskTypeIconPath,
  formatTaskTypeLabel,
  TASK_TYPE_ORDER
} from '../utils/taskTypeIcons'

interface Props {
  sourceToolId: string
  toolName: string
  sourceTaskTypes: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'hop', tool: ProviderTool): void
}>()

const { fetchProvidersAndTools } = useProvidersApi()

const showMenu = ref(false)
const loadingTools = ref(false)
const tools = ref<ProviderTool[]>([])
const containerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const menuStyle = ref({})

// Group tools by task type, sorted within each group alphabetically
// Tools with multiple task_types appear in multiple groups
// Only shows task types that the source tool supports
const groupedTools = computed(() => {
  const groups: Record<string, ProviderTool[]> = {}
  const sourceTypes = new Set(props.sourceTaskTypes)

  // Sort tools alphabetically by name, excluding current tool
  const sortedTools = [...tools.value]
    .filter(t => t.full_tool_id !== props.sourceToolId)
    .sort((a, b) => a.name.localeCompare(b.name))

  // Group by all task types (tool may appear in multiple groups)
  for (const tool of sortedTools) {
    const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    for (const taskType of toolTaskTypes) {
      // Only include task types that the source tool supports
      if (!sourceTypes.has(taskType)) continue
      if (!groups[taskType]) {
        groups[taskType] = []
      }
      groups[taskType].push(tool)
    }
  }

  // Order groups by TASK_TYPE_ORDER
  const orderedGroups: Record<string, ProviderTool[]> = {}
  for (const taskType of TASK_TYPE_ORDER) {
    if (groups[taskType]) {
      orderedGroups[taskType] = groups[taskType]
    }
  }
  // Add any remaining task types not in TASK_TYPE_ORDER
  for (const taskType of Object.keys(groups)) {
    if (!orderedGroups[taskType]) {
      orderedGroups[taskType] = groups[taskType]
    }
  }

  return orderedGroups
})

async function toggleMenu() {
  if (showMenu.value) {
    showMenu.value = false
    return
  }

  // Position the menu
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    const menuWidth = 250
    const viewportWidth = window.innerWidth

    let left = rect.left
    if (left + menuWidth > viewportWidth - 16) {
      left = Math.max(16, rect.right - menuWidth)
    }

    menuStyle.value = {
      top: `${rect.bottom + 4}px`,
      left: `${left}px`,
      minWidth: `${Math.max(rect.width, 220)}px`
    }
  }

  showMenu.value = true
  loadingTools.value = true

  try {
    // Fetch all tools
    const { tools: allTools } = await fetchProvidersAndTools()
    tools.value = allTools
  } catch (err) {
    console.error('Failed to load tools:', err)
  } finally {
    loadingTools.value = false
  }
}

function hopToTool(tool: ProviderTool) {
  showMenu.value = false
  emit('hop', tool)
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
