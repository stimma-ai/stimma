<template>
  <Modal :show="true" size="custom" custom-class="max-w-[600px] w-full max-h-[80vh] flex flex-col overflow-hidden" @close="close">
    <template #header>
      <div class="flex justify-between items-center">
        <h2 class="m-0 text-[16px] font-semibold text-content">Tools</h2>
        <IconButton @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

      <div class="relative px-4 py-3 border-b border-edge-subtle">
        <svg class="absolute left-7 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input v-no-autocorrect
          type="text"
          v-model="searchQuery"
          placeholder="Search tools..."
          class="w-full bg-overlay-subtle border border-transparent rounded-md py-2 pr-3 pl-9 text-content text-sm focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40 placeholder:text-content-muted"
          autofocus
        />
      </div>

      <div class="flex-1 overflow-y-auto p-2 tool-list">
        <div
          v-for="tool in filteredTools"
          :key="tool.full_tool_id"
          @click="toggleTool(tool)"
          :class="[
            'flex justify-between items-center gap-2 py-1.5 px-3 rounded-md cursor-pointer transition-colors',
            isSelected(tool) ? 'bg-accent/10' : 'hover:bg-overlay-subtle'
          ]"
        >
          <span class="flex items-center gap-2 min-w-0">
            <ToolIcon :tool="tool" size="sm" :ring="false" />
            <span :class="[
              'text-[13px] truncate',
              isSelected(tool) ? 'text-accent-hi font-medium' : 'text-content-secondary'
            ]">{{ tool.name || tool.full_tool_id }}</span>
            <span v-if="isStimmaCloud(tool)" class="text-[10px] leading-none font-medium stimma-cloud-text">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
            <span v-else-if="tool.provider_name" class="text-[10px] leading-none px-1.5 py-0.5 rounded-full text-content-muted bg-overlay-subtle">{{ tool.provider_name }}</span>
          </span>
          <span :class="[
            'text-xs font-mono tabular-nums flex-shrink-0',
            isSelected(tool) ? 'text-content-tertiary' : 'text-content-muted'
          ]">({{ tool.count }})</span>
        </div>

        <div v-if="filteredTools.length === 0" class="text-center py-12 px-4 text-content-muted text-sm">
          <span v-if="searchQuery">No tools found matching "{{ searchQuery }}"</span>
          <span v-else>No tools found</span>
        </div>
      </div>

    <template #footer>
      <div class="w-full flex justify-between items-center">
        <span class="text-xs font-mono tabular-nums text-content-muted">{{ tools.length }} tools</span>
        <Button variant="primary" @click="close">Done</Button>
      </div>
    </template>
  </Modal>
</template>

<script setup>
import { ref, computed } from 'vue'
import Modal from './ui/Modal.vue'
import IconButton from './ui/IconButton.vue'
import Button from './ui/Button.vue'
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
    const identities = [t.full_tool_id, ...(t.lineage_tool_ids || [])]
      .join(' ')
      .toLowerCase()
    return name.includes(q) || provider.includes(q) || identities.includes(q)
  })
})

function toolIdentityIds(tool) {
  return [tool.full_tool_id, ...(tool.lineage_tool_ids || [])]
}

function isSelected(tool) {
  return toolIdentityIds(tool).some(id => props.selectedTools.includes(id))
}

function isStimmaCloud(tool) {
  return tool.provider_id === STIMMA_CLOUD_PROVIDER_ID
}

function toggleTool(tool) {
  emit('toggle-tool', tool)
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
