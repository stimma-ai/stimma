<template>
  <div class="relative" ref="containerRef">
    <button
      @click="toggleMenu"
      class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-overlay-light hover:border-edge"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 flex-shrink-0">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
      </svg>
      <span>Send to Chat</span>
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
        <div v-if="loading" class="px-3 py-2 text-xs text-content-tertiary">
          Loading chats...
        </div>
        <template v-else>
          <!-- Create new chat option (always shown) -->
          <button
            @click="sendToNewChat"
            :class="[
              'w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2',
              chats.length > 0 ? 'border-b border-edge-subtle' : ''
            ]"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 flex-shrink-0 text-emerald-500">
              <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
            </svg>
            <span class="text-emerald-500 font-medium">New Chat</span>
          </button>

          <!-- Existing chats -->
          <button
            v-for="chat in chats"
            :key="chat.id"
            @click="sendToChat(chat)"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary">
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
            </svg>
            <span class="truncate flex-1">{{ chat.name || 'Untitled' }}</span>
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { getCurrentProfileId } from '../composables/useProfile'
import { setPendingMedia } from '../composables/usePendingMedia'
import { useAnchoredMenuPosition } from '../composables/useContextMenuPosition'

interface Chat {
  id: number
  name: string | null
  updated_at: string
}

interface Props {
  mediaId: number
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'sent'): void
}>()

const router = useRouter()

const showMenu = ref(false)
const loading = ref(false)
const chats = ref<Chat[]>([])
const containerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)

// Viewport-aware placement below/above the trigger, clamped and height-capped
const anchorRect = ref<DOMRect | null>(null)
const { menuStyle: anchoredStyle } = useAnchoredMenuPosition(menuRef, anchorRect, showMenu)
const menuStyle = computed(() => ({
  ...anchoredStyle.value,
  minWidth: `${Math.max(anchorRect.value?.width ?? 0, 200)}px`,
}))

async function loadChats() {
  loading.value = true
  try {
    const response = await fetch('/api/chats', {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      const data = await response.json()
      // API returns { items: [...], total, page, page_size }
      chats.value = data.items || []
    }
  } catch (err) {
    console.error('Failed to load chats:', err)
  } finally {
    loading.value = false
  }
}

async function toggleMenu() {
  if (showMenu.value) {
    showMenu.value = false
    return
  }

  if (containerRef.value) {
    anchorRect.value = containerRef.value.getBoundingClientRect()
  }
  showMenu.value = true

  // Load chats if not already loaded
  if (chats.value.length === 0) {
    await loadChats()
  }
}

async function sendToNewChat() {
  showMenu.value = false

  // Create new chat and navigate with media_id in query
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      },
      body: JSON.stringify({ name: null })
    })

    if (response.ok) {
      const newChat = await response.json()
      setPendingMedia('chat', [props.mediaId], newChat.id)
      router.push({ name: 'chat', params: { id: newChat.id } })
      emit('sent')
    }
  } catch (err) {
    console.error('Failed to create chat:', err)
  }
}

function sendToChat(chat: Chat) {
  showMenu.value = false

  setPendingMedia('chat', [props.mediaId], chat.id)
  router.push({ name: 'chat', params: { id: chat.id } })
  emit('sent')
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
