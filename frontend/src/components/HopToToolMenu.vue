<template>
  <div class="relative" ref="containerRef">
    <!-- Instance/tool name with dropdown chevron; double-click renames the
         instance (mirrors the sidebar row) -->
    <input
      v-if="editingName !== null"
      ref="renameInputRef"
      v-model="editingName"
      class="text-2xl font-semibold text-content bg-transparent border-b border-edge outline-none min-w-0 max-w-[420px]"
      :placeholder="toolName"
      spellcheck="false"
      @keydown.enter.prevent="saveRename"
      @keydown.escape.prevent="cancelRename"
      @blur="saveRename"
    />
    <button
      v-else
      @click="toggleMenu"
      @dblclick.stop="startRename"
      class="flex items-center gap-1 group cursor-pointer"
    >
      <h2 class="text-2xl font-semibold text-content">{{ customName || toolName }}</h2>
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
      <Transition name="menu">
      <div
        v-if="showMenu"
        ref="menuRef"
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu py-1 min-w-[220px] max-h-[400px] overflow-y-auto"
        :style="menuStyle"
      >
        <div v-if="loadingTools" class="px-3 py-2 text-xs text-content-tertiary">
          Loading tools...
        </div>
        <div v-else-if="Object.keys(groupedTools).length === 0 && openInstances.length === 0" class="px-3 py-2 text-xs text-content-tertiary">
          No other compatible tools available
        </div>
        <template v-else>
          <!-- Open instances (includes sibling instances of this same tool) -->
          <template v-if="openInstances.length > 0">
            <div class="px-3 py-1.5 text-xs font-semibold text-content-secondary">
              Open
            </div>
            <button
              v-for="row in openInstances"
              :key="`hop-instance-${row.tab.id}`"
              @click="hopToInstance(row)"
              class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
            >
              <div class="w-4 h-4 flex-shrink-0" :class="isStimmaCloudTool(row.tool) ? '' : 'text-content-tertiary'">
                <ToolIcon :tool="row.tool" size="xs" :bare="true" :ring="false" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="truncate">{{ row.tab.customName || row.tab.displayName }}</div>
                <div v-if="row.tab.customName" class="truncate text-[10px] leading-tight text-content-muted">{{ row.tab.displayName }}</div>
              </div>
              <span
                v-if="row.tab.projectName"
                class="flex-shrink-0 text-[9px] text-content-tertiary bg-overlay-subtle rounded px-1 py-0.5 truncate max-w-[70px]"
              >{{ row.tab.projectName }}</span>
              <span class="flex-shrink-0 rounded-full bg-blue-500/15 border border-blue-500/50 text-blue-400 px-1.5 py-0.5 text-[9px] font-semibold leading-none">Open</span>
            </button>
            <div v-if="Object.keys(groupedTools).length > 0" class="border-t border-edge-subtle my-1"></div>
          </template>

          <!-- Tools grouped by task type -->
          <template v-for="(groupTools, taskType, groupIndex) in groupedTools" :key="taskType">
            <!-- Divider between groups -->
            <div v-if="groupIndex > 0" class="border-t border-edge-subtle my-1"></div>

            <!-- Group header -->
            <div class="px-3 py-1.5 text-xs font-semibold text-content-secondary">
              {{ formatTaskTypeLabel(taskType as string) }}
            </div>

            <!-- Tools in this group -->
            <button
              v-for="tool in groupTools"
              :key="`${taskType}-${tool.full_tool_id}`"
              @click="hopToTool(tool)"
              class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
            >
              <div class="w-4 h-4 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
                <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
              </div>
              <span class="truncate flex-1">{{ tool.name }}</span>
            </button>
          </template>
        </template>
      </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { useWorkspaceTabs, type WorkspaceTab } from '../composables/useWorkspaceTabs'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { useAnchoredMenuPosition } from '../composables/useContextMenuPosition'
import ToolIcon from './tools/ToolIcon.vue'
import {
  formatTaskTypeLabel,
  TASK_TYPE_ORDER
} from '../utils/taskTypeIcons'

interface Props {
  sourceToolId: string
  toolName: string
  sourceTaskTypes: string[]
  /** This instance's user-given name (window title); toolName stays the tool. */
  customName?: string | null
  /** This instance's tab id — excluded from the Open list. */
  currentTabId?: string | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'hop', tool: ProviderTool): void
  (e: 'hop-instance', tab: WorkspaceTab, tool: ProviderTool): void
  (e: 'rename', name: string | null): void
}>()

const { fetchProvidersAndTools } = useProvidersApi()

const showMenu = ref(false)
const loadingTools = ref(false)
const tools = ref<ProviderTool[]>([])
const containerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)

// Viewport-aware placement below/above the trigger, clamped and height-capped
const anchorRect = ref<DOMRect | null>(null)
const { menuStyle: anchoredStyle } = useAnchoredMenuPosition(menuRef, anchorRect, showMenu)
const menuStyle = computed(() => ({
  ...anchoredStyle.value,
  minWidth: `${Math.max(anchorRect.value?.width ?? 0, 220)}px`,
}))

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

  if (containerRef.value) {
    anchorRect.value = containerRef.value.getBoundingClientRect()
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

function hopToInstance(row: { tab: WorkspaceTab; tool: ProviderTool }) {
  showMenu.value = false
  emit('hop-instance', row.tab, row.tool)
}

// Open tool-instance tabs compatible with this tool's task types — including
// sibling instances of the SAME tool (groupedTools deliberately excludes the
// tool itself, so without this section siblings would be unreachable).
const { tabs: workspaceTabs } = useWorkspaceTabs()
const openInstances = computed(() => {
  const byId = new Map(tools.value.map(t => [t.full_tool_id, t]))
  const sourceTypes = new Set(props.sourceTaskTypes)
  return (workspaceTabs.value as WorkspaceTab[])
    .filter(t => t.type === 'tool' && !!t.instanceId && t.id !== (props.currentTabId ?? undefined))
    .filter(t => {
      const tool = byId.get(t.entityId)
      if (!tool) return false
      if (tool.full_tool_id === props.sourceToolId) return true
      const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
      return toolTaskTypes.some(tt => sourceTypes.has(tt))
    })
    .sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0))
    .slice(0, 5)
    .map(tab => ({ tab, tool: byId.get(tab.entityId)! }))
})

// --- Inline rename (double-click the title, like the sidebar row) ---
const editingName = ref<string | null>(null)
const renameInputRef = ref<HTMLInputElement | null>(null)

function startRename() {
  showMenu.value = false
  editingName.value = props.customName || ''
  nextTick(() => {
    renameInputRef.value?.focus()
    renameInputRef.value?.select()
  })
}

function saveRename() {
  if (editingName.value === null) return
  const name = editingName.value.trim()
  editingName.value = null
  emit('rename', name || null)
}

function cancelRename() {
  editingName.value = null
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
