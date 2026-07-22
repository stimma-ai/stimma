<template>
  <div class="h-full flex flex-col bg-base" @contextmenu.self="handleEmptyContextMenu">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-edge-subtle">
      <h1 class="text-xl font-semibold leading-none text-content">Chats</h1>

      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          @click="createNewChat"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New</span>
        </button>
        <!-- Search -->
        <div class="relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input v-no-autocorrect
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            placeholder="Search chats..."
            class="bg-overlay-subtle border border-transparent rounded-md pl-9 pr-3 py-1.5 text-sm text-content placeholder:text-content-muted focus:outline-none focus:border-accent w-48"
          />
        </div>
      </div>
    </div>

    <!-- Content -->
    <div
      class="flex-1 overflow-y-auto"
      @contextmenu.self="handleEmptyContextMenu"
    >
      <!-- Connection Error -->
      <ConnectionError v-if="loadError" @retry="loadChats" />

      <!-- Loading -->
      <div v-else-if="loading" class="flex items-center justify-center h-64">
        <div class="text-content-muted">Loading chats...</div>
      </div>

      <!-- Empty state -->
      <div v-else-if="filteredChats.length === 0 && chats.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
        <svg class="w-16 h-16 text-content-muted mb-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
        </svg>
        <p class="text-content-muted mb-2">No chats yet</p>
        <p class="text-content-muted text-sm">Start a chat to generate, edit, and explore with Stimma.</p>
      </div>

      <!-- No search results -->
      <div v-else-if="filteredChats.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
        <svg class="w-16 h-16 text-content-muted mb-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <p class="text-content-muted mb-2">No chats match your search</p>
      </div>

      <!-- Chat list (messenger-style) -->
      <div v-else class="py-1">
        <div
          v-for="(chat, index) in filteredChats"
          :key="chat.id"
          :data-testid="`chat-row-${chat.id}`"
          class="flex items-center gap-4 px-6 py-3 transition-colors cursor-pointer group relative"
          :class="isSelected(chat.id)
            ? 'bg-selection/15'
            : 'hover:bg-overlay-subtle'"
          @click="handleCardClick($event, chat, index)"
          @contextmenu="handleCardContextMenu($event, chat)"
        >
          <!-- Selection checkbox (overlays thumbnail) -->
          <div
            class="absolute top-3.5 left-6 z-10 transition-opacity"
            :class="multiSelectMode || isSelected(chat.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
          >
            <button
              @click.stop="toggleSelection(chat.id)"
              class="w-5 h-5 rounded border flex items-center justify-center transition-colors"
              :class="isSelected(chat.id)
                ? 'bg-selection border-selection'
                : 'border-content-tertiary bg-black/55 hover:border-content-secondary'"
            >
              <svg v-if="isSelected(chat.id)" class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </button>
          </div>

          <!-- Thumbnail -->
          <div v-if="hasMedia(chat)" class="flex-shrink-0 w-10 h-10 rounded-media overflow-hidden">
            <MediaImage
              :media-id="chat.recent_media[0].media_id"
              :file-hash="chat.recent_media[0].file_hash"
              :thumbnail="true"
              :thumbnail-size="80"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full"
              class="w-full h-full object-cover"
            />
          </div>
          <div v-else class="flex-shrink-0 w-10 h-10 rounded-media bg-matte flex items-center justify-center">
            <svg class="w-5 h-5 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
            </svg>
          </div>

          <!-- Name + last message; time/counts share the same two lines -->
          <div class="flex-1 min-w-0">
            <!-- Name row -->
            <div class="flex items-center gap-3">
              <template v-if="editingChatId === chat.id">
                <input v-no-autocorrect
                  v-model="editingName"
                  @blur="saveChatName(chat)"
                  @keydown.enter="saveChatName(chat)"
                  @keydown.esc="cancelEdit"
                  @click.stop
                  class="text-sm text-content font-medium bg-surface-raised border border-edge rounded px-2 py-0.5 outline-none focus:border-accent flex-1 min-w-0"
                  placeholder="Name this chat..."
                  autofocus
                />
              </template>
              <template v-else>
                <span
                  v-if="chat.name"
                  @click.stop="startEditingChatName(chat)"
                  class="text-[14px] text-content font-medium truncate cursor-pointer hover:text-content"
                >
                  {{ chat.name }}
                </span>
                <span
                  v-else
                  @click.stop="startEditingChatName(chat)"
                  class="text-[14px] text-content-muted italic truncate cursor-pointer hover:text-content-secondary"
                >
                  New chat
                </span>
              </template>

              <!-- Generating indicator -->
              <div v-if="isChatGenerating(chat.id)" class="w-3 h-3 border-2 border-edge-strong border-t-white rounded-full animate-spin flex-shrink-0"></div>

              <span class="flex-1"></span>
              <span v-if="chat.updated_at" class="flex-shrink-0 text-xs font-mono tabular-nums text-content-tertiary whitespace-nowrap">
                {{ formatRelativeTime(chat.updated_at) }}
              </span>
            </div>

            <!-- Preview row -->
            <div class="flex items-center gap-3 mt-1">
              <p v-if="chat.last_message" class="flex-1 min-w-0 text-[13px] text-content-muted truncate">
                {{ chat.last_message }}
              </p>
              <p v-else-if="chat.generated_count > 0" class="flex-1 min-w-0 text-[13px] text-content-muted truncate">
                {{ chat.generated_count }} image{{ chat.generated_count !== 1 ? 's' : '' }} generated
              </p>
              <span v-else class="flex-1"></span>

              <span class="flex-shrink-0 flex items-center gap-2.5 text-[11px] font-mono tabular-nums text-content-muted">
                <span v-if="chat.message_count > 0" class="flex items-center gap-1">
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                  </svg>
                  {{ chat.message_count }}
                </span>
                <span v-if="chat.generated_count > 0" class="flex items-center gap-1">
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                  </svg>
                  {{ chat.generated_count }}
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Entity Context Menu -->
    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @delete-selected="handleDeleteSelected"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />

    <!-- Empty area context menu -->
    <Teleport to="body">
      <div
        v-if="emptyContextMenuVisible"
        ref="emptyMenuRef"
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1 min-w-[160px]"
        :style="{ top: emptyContextMenuY + 'px', left: emptyContextMenuX + 'px' }"
      >
        <button
          @click="handleSelectAll(); emptyContextMenuVisible = false"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <span class="w-4 h-4 flex-shrink-0"></span>
          <span>Select All</span>
        </button>
        <div class="border-t border-edge-subtle my-1"></div>
        <button
          @click="createNewChat(); emptyContextMenuVisible = false"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New Chat</span>
        </button>
      </div>
    </Teleport>

    <!-- Entity Selection Bar -->
    <EntitySelectionBar
      :visible="multiSelectMode"
      :selected-count="selectedIds.size"
      :total-count="filteredChats.length"
      entity-type="chat"
      @clear="clearSelection"
      @select-all="handleSelectAll"
      @delete="handleDeleteSelected"
    />

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, onDeactivated, onUnmounted, nextTick , watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWebSocket } from '../composables/useWebSocket'
import { useAgentActivity } from '../composables/useAgentActivity'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'
import ConnectionError from '../components/ConnectionError.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import EntitySelectionBar from '../components/EntitySelectionBar.vue'
import { MediaImage } from '../components/media'

defineOptions({
  name: 'ChatsLandingView'
})

const props = defineProps({
  projectId: {
    type: Number,
    default: null
  }
})

const router = useRouter()
const { on } = useWebSocket()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()

const searchInputRef = ref(null)
const chats = ref([])
const loading = ref(true)
const loadError = ref(false)
const searchQuery = ref('')

// Global search "View all" handoff: seed the local filter from ?q= so the
// omnibox's per-type result caps never hide matches for good.
const route = useRoute()
watch(() => route.query.q, (q) => {
  if (typeof q === 'string' && q) searchQuery.value = q
}, { immediate: true })

// Inline editing state
const editingChatId = ref(null)
const editingName = ref('')

// Chat generation tracking (primed on load/reconnect, cleared on disconnect)
const { isChatGenerating } = useAgentActivity()

// Selection state
const selectedIds = ref(new Set())
const multiSelectMode = computed(() => selectedIds.value.size > 0)
const lastClickedIndex = ref(-1)

// Empty area context menu
const emptyContextMenuVisible = ref(false)
const emptyContextMenuX = ref(0)
const emptyContextMenuY = ref(0)
const emptyMenuRef = ref(null)

const filteredChats = computed(() => {
  if (!searchQuery.value.trim()) return chats.value
  const q = searchQuery.value.toLowerCase().trim()
  return chats.value.filter(c => (c.name || '').toLowerCase().includes(q))
})

// Selection helpers
function isSelected(id) {
  return selectedIds.value.has(id)
}

function toggleSelection(id) {
  const newSet = new Set(selectedIds.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  selectedIds.value = newSet
}

function clearSelection() {
  selectedIds.value = new Set()
  lastClickedIndex.value = -1
}

function handleSelectAll() {
  const allIds = new Set(filteredChats.value.map(c => c.id))
  selectedIds.value = allIds
}

function handleCardClick(event, chat, index) {
  // If editing, don't interfere
  if (editingChatId.value) return

  const isMeta = event.metaKey || event.ctrlKey
  const isShift = event.shiftKey

  if (isMeta) {
    // Cmd/Ctrl+Click: toggle selection
    toggleSelection(chat.id)
    lastClickedIndex.value = index
    return
  }

  if (isShift && lastClickedIndex.value >= 0) {
    // Shift+Click: range select
    const start = Math.min(lastClickedIndex.value, index)
    const end = Math.max(lastClickedIndex.value, index)
    const newSet = new Set(selectedIds.value)
    for (let i = start; i <= end; i++) {
      newSet.add(filteredChats.value[i].id)
    }
    selectedIds.value = newSet
    return
  }

  if (multiSelectMode.value) {
    // In multi-select mode, regular click toggles
    toggleSelection(chat.id)
    lastClickedIndex.value = index
    return
  }

  // Regular click: open chat
  openChat(chat)
}

function handleCardContextMenu(event, chat) {
  entityContextMenu.show({
    event,
    entityType: 'chat',
    entityId: chat.id,
    entityName: chat.name || 'Untitled',
    isSelected: isSelected(chat.id),
    selectedCount: selectedIds.value.size,
    projectId: chat.project_id
  })
}

function handleEmptyContextMenu(event) {
  // Only show when right-clicking on empty area (not on a card)
  event.preventDefault()
  entityContextMenu.hide()

  const menuWidth = 180
  const menuHeight = 100
  const padding = 8

  let x = event.clientX
  let y = event.clientY

  if (x + menuWidth > window.innerWidth - padding) {
    x = Math.max(padding, window.innerWidth - menuWidth - padding)
  }
  y = Math.min(y, window.innerHeight - menuHeight - padding)

  emptyContextMenuX.value = x
  emptyContextMenuY.value = y
  emptyContextMenuVisible.value = true
}

function handleContextMenuOpen(entityType, entityId) {
  router.push({ name: 'chat', params: { id: entityId } })
}

function handleContextMenuDelete(entityType, entityId) {
  performDelete([entityId])
}

async function handleContextMenuRename(entityType, entityId, entityName) {
  router.push({ name: 'chat', params: { id: entityId }, query: { rename: '1' } })
}

async function handleContextMenuMoveToProject(entityType, entityId, projectId) {
  try {
    await fetch(`/api/chats/${entityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId })
    })
    await loadChats()
  } catch (err) {
    console.error('Failed to move chat to project:', err)
  }
}

function handleDeleteSelected() {
  if (selectedIds.value.size === 0) return
  performDelete(Array.from(selectedIds.value))
}

async function performDelete(ids) {
  // Optimistic: remove from local list immediately
  const removedChats = chats.value.filter(c => ids.includes(c.id))
  if (removedChats.length === 0) return
  chats.value = chats.value.filter(c => !ids.includes(c.id))

  // Clear selection for deleted items
  const newSet = new Set(selectedIds.value)
  ids.forEach(id => newSet.delete(id))
  selectedIds.value = newSet

  const count = ids.length
  const label = count === 1 ? '1 chat' : `${count} chats`

  function reinsert() {
    const existing = new Set(chats.value.map(c => c.id))
    const missing = removedChats.filter(c => !existing.has(c.id))
    if (missing.length === 0) return
    chats.value = [...chats.value, ...missing]
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
  }

  try {
    if (ids.length === 1) {
      const response = await fetch(`/api/chats/${ids[0]}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('delete failed')
    } else {
      const response = await fetch('/api/chats/batch/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      })
      if (!response.ok) throw new Error('batch delete failed')
    }
  } catch (err) {
    console.error('Failed to delete chats:', err)
    reinsert()
    addToast(`Failed to delete ${label}`, 'error', 5000)
    return
  }

  addToast(`Deleted ${label}`, 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      reinsert()
      try {
        if (ids.length === 1) {
          const response = await fetch(`/api/chats/${ids[0]}/restore`, { method: 'POST' })
          if (!response.ok) throw new Error('restore failed')
        } else {
          const response = await fetch('/api/chats/batch/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids })
          })
          if (!response.ok) throw new Error('batch restore failed')
        }
      } catch (err) {
        console.error('Failed to restore chats:', err)
        chats.value = chats.value.filter(c => !ids.includes(c.id))
        addToast(`Failed to restore ${label}`, 'error', 5000)
      }
    }
  })
}

// Keyboard shortcuts
function handleKeyDown(event) {
  // Don't handle shortcuts while the user is editing text.
  if (
    event.target?.tagName === 'INPUT' ||
    event.target?.tagName === 'TEXTAREA' ||
    event.target?.isContentEditable
  ) return

  // Close empty context menu on Escape
  if (event.key === 'Escape') {
    if (emptyContextMenuVisible.value) {
      emptyContextMenuVisible.value = false
      return
    }
    if (multiSelectMode.value) {
      clearSelection()
      return
    }
  }

  // Ctrl/Cmd+A: Select All
  if ((event.metaKey || event.ctrlKey) && event.key === 'a') {
    event.preventDefault()
    handleSelectAll()
    return
  }

  // Delete/Backspace: Delete selected
  if ((event.key === 'Delete' || event.key === 'Backspace') && multiSelectMode.value) {
    event.preventDefault()
    handleDeleteSelected()
    return
  }
}

// Close empty context menu on click outside
function handleEmptyMenuClickOutside(event) {
  if (!emptyContextMenuVisible.value) return
  if (emptyMenuRef.value?.contains(event.target)) return
  emptyContextMenuVisible.value = false
}

async function loadChats() {
  loading.value = true
  loadError.value = false
  try {
    const params = new URLSearchParams({ page: '1', page_size: '100' })
    if (props.projectId != null) params.set('project_id', String(props.projectId))
    const response = await fetch(`/api/chats/previews?${params.toString()}`)
    if (!response.ok) throw new Error('Failed to load chats')
    const data = await response.json()
    chats.value = data.items
  } catch (err) {
    console.error('Failed to load chats:', err)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function createNewChat() {
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: props.projectId
      })
    })
    if (!response.ok) throw new Error('Failed to create chat')
    const newChat = await response.json()
    router.push({ name: 'chat', params: { id: newChat.id } })
  } catch (err) {
    console.error('Failed to create chat:', err)
  }
}

function openChat(chat) {
  router.push({ name: 'chat', params: { id: chat.id } })
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'now'
  if (diffMins < 60) return `${diffMins}m`
  if (diffHours < 24) return `${diffHours}h`
  if (diffDays < 7) return `${diffDays}d`
  const opts = { month: 'short', day: 'numeric' }
  if (date.getFullYear() !== now.getFullYear()) opts.year = '2-digit'
  return date.toLocaleDateString(undefined, opts)
}

// Inline editing functions
function startEditingChatName(chat) {
  editingChatId.value = chat.id
  editingName.value = chat.name || ''
  nextTick(() => {
    const input = document.querySelector('input[autofocus]')
    if (input) {
      input.focus()
      input.select()
    }
  })
}

async function saveChatName(chat) {
  if (editingChatId.value !== chat.id) return

  const newName = editingName.value.trim()
  try {
    await fetch(`/api/chats/${chat.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName })
    })
    chat.name = newName
  } catch (err) {
    console.error('Failed to rename chat:', err)
  }

  editingChatId.value = null
  editingName.value = ''
}

function cancelEdit() {
  editingChatId.value = null
  editingName.value = ''
}

function hasMedia(chat) {
  return chat.recent_media && chat.recent_media.length > 0
}

// WebSocket listeners
on('chat_created', () => loadChats())
on('chat_updated', () => loadChats())
on('chat_deleted', () => loadChats())
on('chat_restored', () => loadChats())

onMounted(() => {
  loadChats()
  searchInputRef.value?.focus()
})

onActivated(() => {
  loadChats()
  searchInputRef.value?.focus()
  document.addEventListener('keydown', handleKeyDown)
  document.addEventListener('click', handleEmptyMenuClickOutside)
})

onDeactivated(() => {
  document.removeEventListener('keydown', handleKeyDown)
  document.removeEventListener('click', handleEmptyMenuClickOutside)
  emptyContextMenuVisible.value = false
  clearSelection()
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyDown)
  document.removeEventListener('click', handleEmptyMenuClickOutside)
})
</script>
