<template>
  <div class="space-y-3">
    <!-- Header row with icon, content, and actions -->
    <div class="flex items-start gap-3">
      <!-- Icon -->
      <div class="w-10 h-10 flex items-center justify-center bg-accent/15 rounded-lg flex-shrink-0">
        <svg class="w-5 h-5 text-accent" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
        </svg>
      </div>

      <!-- Main content -->
      <div class="flex-1 min-w-0">
        <!-- Inline prompt with dropdown -->
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-content-tertiary text-sm">Use</span>

          <!-- Tool dropdown -->
          <div class="relative" ref="dropdownRef">
            <button
              @click="toggleDropdown"
              :disabled="loadingTools"
              class="flex items-center gap-1.5 bg-surface text-content text-sm border border-edge rounded-lg pl-3 pr-2 py-1.5 hover:border-edge transition-colors cursor-pointer"
            >
              <div v-if="loadingTools" class="text-content-muted">Loading...</div>
              <div v-else class="text-left">
                <div class="text-sm text-content">{{ selectedTool?.name || 'Select a tool' }}</div>
                <div
                  v-if="selectedTool"
                  class="text-[11px] leading-tight"
                  :class="isStimmaCloud(selectedTool) ? 'stimma-cloud-text' : 'text-content-muted'"
                >
                  {{ selectedTool.provider_name }}
                </div>
              </div>
              <svg class="w-4 h-4 text-content-muted flex-shrink-0 transition-transform ml-1" :class="dropdownOpen ? 'rotate-180' : ''" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </button>

            <!-- Dropdown menu -->
            <div
              v-if="dropdownOpen && !loadingTools"
              class="absolute left-0 top-full mt-1 bg-base border border-edge rounded-lg shadow-xl z-menu w-[280px] overflow-hidden"
            >
              <!-- Search input -->
              <div class="p-2 border-b border-edge">
                <input
                  ref="searchInputRef"
                  v-model="toolSearch"
                  type="text"
                  placeholder="Search tools..."
                  class="w-full bg-surface text-content text-sm border border-edge rounded-lg px-3 py-1.5 focus:outline-none focus:border-edge"
                  @click.stop
                />
              </div>
              <!-- Tool list -->
              <div class="max-h-52 overflow-y-auto py-1">
                <div v-if="filteredTools.length === 0" class="px-3 py-2 text-sm text-content-muted">
                  No tools match your search
                </div>
                <button
                  v-for="tool in filteredTools"
                  :key="tool.full_tool_id"
                  @click="selectTool(tool.full_tool_id)"
                  class="w-full px-3 py-2 text-left hover:bg-surface transition-colors"
                  :class="selectedToolId === tool.full_tool_id ? 'bg-surface' : ''"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-sm text-content">{{ tool.name }}</span>
                    <span
                      v-if="tool.full_tool_id === suggestedToolId"
                      class="text-[10px] px-1.5 py-0.5 rounded bg-accent/20 text-accent"
                    >
                      Suggested
                    </span>
                  </div>
                  <div
                    class="text-xs mt-0.5"
                    :class="isStimmaCloud(tool) ? 'stimma-cloud-text' : 'text-content-muted'"
                  >
                    {{ tool.provider_name }}
                  </div>
                </button>
              </div>
            </div>
          </div>

          <span class="text-content-tertiary text-sm">{{ actionText }}?</span>
        </div>
      </div>

    </div>

    <!-- Actions -->
    <div class="flex justify-end gap-3">
      <button
        @click="handleDeny"
        class="px-4 py-2 text-sm text-content-tertiary hover:text-content transition-colors"
      >
        Deny
      </button>
      <!-- Split button: Allow (primary = for this chat) + dropdown for alternatives -->
      <div class="relative flex" ref="allowMenuRef">
        <!-- Primary action: Allow (for this chat) -->
        <button
          @click="handleAllow('chat')"
          :disabled="!selectedToolId"
          class="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-l-md transition-colors"
        >
          Allow
        </button>
        <!-- Dropdown trigger -->
        <button
          @click.stop="allowMenuOpen = !allowMenuOpen"
          :disabled="!selectedToolId"
          class="px-2 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-r-md border-l border-overlay-medium transition-colors"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </button>
        <!-- Dropdown menu with all options -->
        <div
          v-if="allowMenuOpen"
          class="absolute right-0 top-full mt-1 w-44 bg-surface border border-edge-subtle rounded-lg shadow-lg overflow-hidden z-menu"
        >
          <button
            @click="handleAllow('once')"
            class="w-full px-3 py-2 text-left text-sm text-content hover:bg-overlay-light transition-colors"
          >
            Allow Once
          </button>
          <button
            @click="handleAllow('chat')"
            class="w-full px-3 py-2 text-left text-sm text-content bg-accent/20 hover:bg-accent/30 transition-colors flex items-center justify-between"
          >
            For this Chat
            <span class="text-[10px] text-accent">Default</span>
          </button>
          <button
            @click="handleAllow('always')"
            class="w-full px-3 py-2 text-left text-sm text-content hover:bg-overlay-light transition-colors"
          >
            Always Allow
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useProvidersApi, type ProviderTool } from '../../composables/useProvidersApi'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { formatTaskTypeLabel } from '../../utils/taskTypeIcons'

const props = defineProps<{
  prompt: string
  taskType: string
  suggestedToolId: string | null
  reason: string | null
}>()

type PermissionScope = 'once' | 'chat' | 'always'

const emit = defineEmits<{
  (e: 'respond', response: { approved: boolean; selected_tool_id: string | null; scope?: PermissionScope }): void
}>()

const { listAllTools } = useProvidersApi()

// State
const allTools = ref<ProviderTool[]>([])
const loadingTools = ref(false)
const selectedToolId = ref<string | null>(props.suggestedToolId)
const dropdownOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)
const toolSearch = ref('')
const allowMenuOpen = ref(false)
const allowMenuRef = ref<HTMLElement | null>(null)

// Computed
const compatibleTools = computed(() => {
  if (!props.taskType) return allTools.value
  return allTools.value.filter(tool =>
    tool.task_types.includes(props.taskType)
  )
})

const filteredTools = computed(() => {
  if (!toolSearch.value.trim()) return compatibleTools.value
  const search = toolSearch.value.toLowerCase()
  return compatibleTools.value.filter(tool =>
    tool.name.toLowerCase().includes(search) ||
    tool.provider_name.toLowerCase().includes(search)
  )
})

const selectedTool = computed(() => {
  if (!selectedToolId.value) return null
  return compatibleTools.value.find(t => t.full_tool_id === selectedToolId.value) || null
})

// Extract action text from prompt (e.g., "Use Flux.1 Dev for text-to-image?" -> "to generate images")
const actionText = computed(() => {
  // The prompt from backend is like "Use Flux.1 Dev for text-to-image?"
  // We want to extract and use the reason or task type to make it human-readable
  if (props.reason) {
    // Reason is usually like "The agent wants to generate images using this tool."
    // Try to extract the action
    const match = props.reason.match(/wants to (.+?) using/i)
    if (match) {
      return `to ${match[1]}`
    }
  }

  // Fall back to formatting the task type
  if (props.taskType) {
    return `for ${formatTaskType(props.taskType)}`
  }

  return 'for this task'
})

// Methods
function formatTaskType(taskType: string): string {
  if (!taskType) return 'this task'
  return formatTaskTypeLabel(taskType)
}

function isStimmaCloud(tool: ProviderTool): boolean {
  return isStimmaCloudTool(tool)
}

async function loadTools() {
  loadingTools.value = true
  try {
    allTools.value = await listAllTools()
    // Set suggested tool if provided and compatible
    if (props.suggestedToolId) {
      const compatible = compatibleTools.value.find(t => t.full_tool_id === props.suggestedToolId)
      if (compatible) {
        selectedToolId.value = props.suggestedToolId
      } else if (compatibleTools.value.length > 0) {
        selectedToolId.value = compatibleTools.value[0].full_tool_id
      }
    } else if (compatibleTools.value.length > 0) {
      selectedToolId.value = compatibleTools.value[0].full_tool_id
    }
  } catch (err) {
    console.error('Failed to load tools:', err)
  } finally {
    loadingTools.value = false
  }
}

function selectTool(toolId: string) {
  selectedToolId.value = toolId
  dropdownOpen.value = false
  toolSearch.value = ''
}

function toggleDropdown() {
  dropdownOpen.value = !dropdownOpen.value
  if (dropdownOpen.value) {
    // Focus search input after dropdown opens
    setTimeout(() => searchInputRef.value?.focus(), 0)
  } else {
    toolSearch.value = ''
  }
}

function handleClickOutside(e: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    dropdownOpen.value = false
    toolSearch.value = ''
  }
  if (allowMenuRef.value && !allowMenuRef.value.contains(e.target as Node)) {
    allowMenuOpen.value = false
  }
}

function handleAllow(scope: PermissionScope) {
  if (!selectedToolId.value) return
  allowMenuOpen.value = false
  emit('respond', {
    approved: true,
    selected_tool_id: selectedToolId.value,
    scope,
  })
}

function handleDeny() {
  emit('respond', {
    approved: false,
    selected_tool_id: null,
  })
}

// Load tools on mount
onMounted(() => {
  loadTools()
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
