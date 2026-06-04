<template>
  <div class="relative" ref="containerRef">
    <button
      @click="toggleMenu"
      class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-overlay-light hover:border-edge"
    >
      <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
      </svg>
      <span>Send to Tool</span>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 ml-auto text-content-tertiary">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <Teleport to="body">
      <div
        v-if="showMenu"
        ref="menuRef"
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[9999] py-1 min-w-[200px] max-h-[400px] overflow-y-auto"
        :style="menuStyle"
      >
        <TaskTypeToolList
          ref="toolListRef"
          :tools="tools"
          :media-type="mediaType"
          :loading="loading"
          gradient-id="stimma-gradient-sendtool"
          @select="handleSelect"
        />
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { useSendToTool } from '../composables/useSendToTool'
import type { MediaType } from '../utils/mediaTypes'
import TaskTypeToolList from './TaskTypeToolList.vue'

interface Props {
  mediaItem: {
    id: number
    file_hash: string
    file_path: string
    width?: number
    height?: number
  }
  mediaType: MediaType
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'sent'): void
}>()

const { listAllTools } = useProvidersApi()
const { sendToTool } = useSendToTool()

const showMenu = ref(false)
const loading = ref(false)
const tools = ref<ProviderTool[]>([])
const containerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const toolListRef = ref<InstanceType<typeof TaskTypeToolList> | null>(null)
const menuStyle = ref({})

// Reset tool list when menu opens
watch(showMenu, (visible) => {
  if (visible) {
    toolListRef.value?.reset()
  }
})

async function toggleMenu() {
  if (showMenu.value) {
    showMenu.value = false
    return
  }

  // Position the menu
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    const menuWidth = 220
    const viewportWidth = window.innerWidth

    let left = rect.left
    if (left + menuWidth > viewportWidth - 16) {
      left = Math.max(16, rect.right - menuWidth)
    }

    menuStyle.value = {
      top: `${rect.bottom + 4}px`,
      left: `${left}px`,
      minWidth: `${Math.max(rect.width, 200)}px`
    }
  }

  showMenu.value = true

  // Load tools if not already loaded
  if (tools.value.length === 0) {
    loading.value = true
    try {
      tools.value = await listAllTools()
    } catch (err) {
      console.error('Failed to load tools:', err)
    } finally {
      loading.value = false
    }
  }
}

async function handleSelect(tool: ProviderTool, taskType: string) {
  showMenu.value = false
  await sendToTool(props.mediaItem as any, tool, taskType)
  emit('sent')
}

// Close menu when clicking outside
// Use mousedown instead of click: when clicking a category inside TaskTypeToolList,
// the component re-renders and removes the clicked element from the DOM before the
// click event bubbles to the document. At that point contains() returns false
// because the target is detached, causing the menu to close prematurely.
function handleClickOutside(event: MouseEvent) {
  if (!showMenu.value) return
  const target = event.target as Element
  if (containerRef.value?.contains(target)) return
  if (menuRef.value?.contains(target)) return
  showMenu.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})
</script>
