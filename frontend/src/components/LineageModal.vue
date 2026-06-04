<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="lineageModal.state.value.visible && lineageModal.state.value.mediaId"
        class="fixed inset-0 z-[10005] flex flex-col bg-slideshow-matt"
        @keydown.esc.stop="lineageModal.close()"
        tabindex="-1"
        ref="modalRef"
      >
        <!-- Header — pl-20 reserves space for macOS traffic-light window controls -->
        <div class="relative flex items-center justify-center h-14 pl-20 pr-4 flex-shrink-0 border-b border-edge-subtle" data-tauri-drag-region>
          <!-- Centered title + stats -->
          <div class="flex items-center gap-2 pointer-events-none" data-tauri-drag-region>
            <h2 class="text-sm font-medium text-white/80" data-tauri-drag-region>Lineage</h2>
            <span
              v-if="lineageTreeRef && !lineageTreeRef.loading"
              class="text-xs text-white/30"
              data-tauri-drag-region
            >
              {{ lineageTreeRef.nodeCount }} {{ lineageTreeRef.nodeCount === 1 ? 'item' : 'items' }}
            </span>
          </div>
          <!-- Close button pinned right -->
          <button
            class="absolute right-4 w-8 h-8 flex items-center justify-center rounded-full text-white/50 hover:text-white hover:bg-white/10 transition-colors"
            @click="lineageModal.close()"
            title="Close (Esc)"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="relative flex-1 min-h-0">
          <!-- Lineage Tree -->
          <LineageTree
            ref="lineageTreeRef"
            :media-id="lineageModal.state.value.mediaId"
            class="absolute inset-0"
            @close="lineageModal.close()"
          />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useLineageModal } from '../composables/useLineageModal'
import LineageTree from './LineageTree.vue'

const lineageModal = useLineageModal()
const modalRef = ref(null)

// Focus the modal when it opens so Esc works
watch(() => lineageModal.state.value.visible, async (visible) => {
  if (visible) {
    await nextTick()
    modalRef.value?.focus()
  }
})

const lineageTreeRef = ref(null)

const dirMap = {
  ArrowRight: 'right', ArrowLeft: 'left', ArrowDown: 'down', ArrowUp: 'up',
  d: 'right', a: 'left', s: 'down', w: 'up'
}

function handleKeydown(e) {
  if (!lineageModal.state.value.visible) return

  // D-pad / WASD navigation
  const dir = dirMap[e.key]
  if (dir) {
    e.preventDefault()
    e.stopPropagation()
    lineageTreeRef.value?.navigateDpad?.(dir)
    return
  }

  // Enter: open/close detail modal for focused node
  if (e.key === 'Enter') {
    e.preventDefault()
    e.stopPropagation()
    if (lineageTreeRef.value?.hasDetailOpen?.()) {
      lineageTreeRef.value.closeDetail()
    } else {
      lineageTreeRef.value?.openDetail?.()
    }
    return
  }

  // Escape: close detail modal first, then lineage
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    if (lineageTreeRef.value?.hasDetailOpen?.()) {
      lineageTreeRef.value.closeDetail()
      return
    }
    lineageModal.close()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown, true)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>
