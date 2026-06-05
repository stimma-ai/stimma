<template>
  <div class="fixed inset-0 bg-black/80 flex items-center justify-center z-[10000] p-8" @click.self="close">
    <div class="bg-surface border border-edge rounded-xl w-full max-w-[600px] max-h-[80vh] flex flex-col shadow-[0_20px_25px_-5px_rgba(0,0,0,0.5)]">
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
          class="w-full bg-surface-raised border border-edge-strong rounded-lg py-3 pr-4 pl-11 text-content text-sm transition-all focus:outline-none focus:border-indigo-500 focus:bg-surface placeholder:text-content-muted"
          autofocus
        />
      </div>

      <!-- SVG gradient for Stimma Cloud branding -->
      <svg class="absolute w-0 h-0" aria-hidden="true">
        <defs>
          <linearGradient id="stimma-gradient-tool-modal" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0d9488" />
            <stop offset="50%" stop-color="#06b6d4" />
            <stop offset="100%" stop-color="#6366f1" />
          </linearGradient>
        </defs>
      </svg>

      <div class="flex-1 overflow-y-auto p-2 tool-list">
        <div
          v-for="tool in filteredTools"
          :key="tool.full_tool_id"
          @click="toggleTool(tool.full_tool_id)"
          :class="[
            'flex justify-between items-center py-3.5 px-4 mb-1 rounded-lg cursor-pointer transition-all',
            isSelected(tool.full_tool_id)
              ? 'bg-indigo-500/20 border border-indigo-500 hover:bg-indigo-500/30'
              : 'bg-transparent hover:bg-overlay-subtle'
          ]"
        >
          <span class="flex items-center gap-2">
            <span :class="[
              'text-[15px] font-medium',
              isSelected(tool.full_tool_id) ? 'text-indigo-300 font-semibold' : 'text-content'
            ]">{{ tool.name || tool.full_tool_id }}</span>
            <svg v-if="isStimmaCloud(tool)" class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="url(#stimma-gradient-tool-modal)" :title="tool.provider_name">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
            </svg>
            <span v-else-if="tool.provider_name" class="text-[11px] leading-none px-1.5 py-0.5 rounded-full text-content-muted bg-overlay-subtle">{{ tool.provider_name }}</span>
          </span>
          <span :class="[
            'text-[13px] font-normal',
            isSelected(tool.full_tool_id) ? 'text-indigo-400' : 'text-content-muted'
          ]">({{ tool.count }})</span>
        </div>

        <div v-if="filteredTools.length === 0" class="text-center py-12 px-4 text-content-muted text-sm">
          <span v-if="searchQuery">No tools found matching "{{ searchQuery }}"</span>
          <span v-else>No tools found</span>
        </div>
      </div>

      <div class="px-6 py-6 border-t border-edge flex justify-between items-center">
        <span class="text-sm text-content-muted">{{ tools.length }} tools</span>
        <button class="bg-indigo-500 text-white border-none py-3 px-8 rounded-lg text-[15px] font-semibold cursor-pointer transition-all hover:bg-indigo-600 hover:-translate-y-px hover:shadow-[0_4px_6px_-1px_rgba(99,102,241,0.3)] active:translate-y-0" @click="close">Done</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { STIMMA_CLOUD_PROVIDER_ID } from '../utils/stimmaCloud'

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
