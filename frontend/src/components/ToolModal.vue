<template>
  <div class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal p-8" @click.self="close">
    <div class="bg-surface border border-edge rounded-lg w-full max-w-[600px] max-h-[80vh] flex flex-col shadow-[0_20px_25px_-5px_rgba(0,0,0,0.5)]">
      <div class="flex justify-between items-center px-6 py-6 border-b border-edge">
        <h2 class="m-0 text-xl font-semibold text-content">Tools</h2>
        <button class="bg-transparent border-none text-content-tertiary cursor-pointer p-2 flex items-center justify-center rounded transition-all hover:bg-overlay-light hover:text-content" @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="relative px-6 py-6 border-b border-edge">
        <svg class="absolute left-8 top-1/2 -translate-y-1/2 w-5 h-5 text-content-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input v-no-autocorrect
          type="text"
          v-model="searchQuery"
          placeholder="Search tools..."
          class="w-full bg-surface-raised border border-edge-strong rounded-lg py-3 pr-4 pl-11 text-content text-sm transition-all focus:outline-none focus:border-accent focus:bg-surface placeholder:text-content-muted"
          autofocus
        />
      </div>

      <div class="flex-1 overflow-y-auto p-2 tool-list">
        <div
          v-for="tool in filteredTools"
          :key="tool.full_tool_id"
          @click="toggleTool(tool.full_tool_id)"
          :class="[
            'flex justify-between items-center py-3.5 px-4 mb-1 rounded-lg cursor-pointer transition-all',
            isSelected(tool.full_tool_id)
              ? 'bg-selection/20 border border-selection hover:bg-selection/30'
              : 'bg-transparent hover:bg-overlay-subtle'
          ]"
        >
          <span class="flex items-center gap-2">
            <ToolIcon :tool="tool" size="sm" :ring="false" />
            <span :class="[
              'text-[15px] font-medium',
              isSelected(tool.full_tool_id) ? 'text-selection font-semibold' : 'text-content'
            ]">{{ tool.name || tool.full_tool_id }}</span>
            <span v-if="isStimmaCloud(tool)" class="text-[11px] leading-none px-1.5 py-0.5 rounded-full bg-teal-600/10 border border-teal-600/25 font-medium stimma-cloud-text">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
            <span v-else-if="tool.provider_name" class="text-[11px] leading-none px-1.5 py-0.5 rounded-full text-content-muted bg-overlay-subtle">{{ tool.provider_name }}</span>
          </span>
          <span :class="[
            'text-[13px] font-normal',
            isSelected(tool.full_tool_id) ? 'text-selection' : 'text-content-muted'
          ]">({{ tool.count }})</span>
        </div>

        <div v-if="filteredTools.length === 0" class="text-center py-12 px-4 text-content-muted text-sm">
          <span v-if="searchQuery">No tools found matching "{{ searchQuery }}"</span>
          <span v-else>No tools found</span>
        </div>
      </div>

      <div class="px-6 py-6 border-t border-edge flex justify-between items-center">
        <span class="text-sm text-content-muted">{{ tools.length }} tools</span>
        <button class="bg-accent hover:bg-accent/90 text-white border-none py-3 px-8 rounded-lg text-[15px] font-semibold cursor-pointer transition-all active:translate-y-0" @click="close">Done</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import ToolIcon from './tools/ToolIcon.vue'
import { STIMMA_CLOUD_PROVIDER_ID, STIMMA_TOOL_PROVIDER_DISPLAY_NAME } from '../utils/stimmaCloud'

const props = defineProps({
  tools: {
    type: Array,
    required: true,
    default: () => []
  },
  selectedTools: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['toggle-tool', 'close'])

const searchQuery = ref('')

const filteredTools = computed(() => {
  if (!searchQuery.value) return props.tools
  const q = searchQuery.value.toLowerCase()
  return props.tools.filter(t => {
    const name = (t.name || t.full_tool_id || '').toLowerCase()
    const provider = (t.provider_name || '').toLowerCase()
    return name.includes(q) || provider.includes(q)
  })
})

function isSelected(fullToolId) {
  return props.selectedTools.includes(fullToolId)
}

function isStimmaCloud(tool) {
  return tool.provider_id === STIMMA_CLOUD_PROVIDER_ID
}

function toggleTool(fullToolId) {
  emit('toggle-tool', fullToolId)
}

function close() {
  emit('close')
}
</script>

<style scoped>
.tool-list::-webkit-scrollbar {
  -webkit-appearance: none;
  width: 8px;
}

.tool-list::-webkit-scrollbar-track {
  background: var(--color-surface);
}

.tool-list::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 4px;
}

.tool-list::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}
</style>
