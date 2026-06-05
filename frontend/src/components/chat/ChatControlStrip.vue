<template>
  <div class="flex items-center gap-2 px-4 py-2 bg-base border-b border-edge">
    <!-- Chat Name (Left) -->
    <div class="flex items-center gap-2 flex-shrink-0">
      <input v-no-autocorrect
        v-if="editingName"
        ref="nameInputRef"
        v-model="editedName"
        @blur="saveName"
        @keydown.enter="saveName"
        @keydown.escape="cancelEditName"
        class="text-sm font-medium bg-surface text-content px-2 py-1 rounded border border-edge focus:outline-none focus:border-blue-500"
      />
      <span
        v-else-if="chatName"
        @dblclick="startEditName"
        class="text-sm font-medium text-content cursor-pointer hover:text-content-secondary"
        title="Double-click to rename"
      >
        {{ chatName }}
      </span>
      <span
        v-else
        @click="startEditName"
        class="text-sm font-medium text-content-muted italic cursor-pointer hover:text-content-secondary"
      >
        Name this chat...
      </span>
    </div>

    <!-- Spacer -->
    <div class="flex-1"></div>

    <!-- Right side controls -->
    <div class="flex items-center gap-1.5">
      <!-- Settings Panel Toggle -->
      <button
        @click="$emit('toggle-settings-panel')"
        class="w-7 h-7 flex items-center justify-center rounded transition-colors"
        :class="settingsPanelVisible
          ? 'text-blue-500 bg-blue-500/20 hover:bg-blue-500/30'
          : 'text-content-muted hover:text-content-secondary hover:bg-surface'"
        title="Toggle settings panel"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75a4.5 4.5 0 0 1-4.884 4.484c-1.076-.091-2.264.071-2.95.904l-7.152 8.684a2.548 2.548 0 1 1-3.586-3.586l8.684-7.152c.833-.686.995-1.874.904-2.95a4.5 4.5 0 0 1 6.336-4.486l-3.276 3.276a3.004 3.004 0 0 0 2.25 2.25l3.276-3.276c.256.565.398 1.192.398 1.852Z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.867 19.125h.008v.008h-.008v-.008Z" />
        </svg>
      </button>

      <!-- Open Workspace (dev mode only) -->
      <button
        v-if="devModeRef"
        @click="openWorkspace"
        class="flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium text-purple-500 hover:bg-purple-500/10 transition-colors"
        title="Open workspace folder in Finder"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
        </svg>
        Open Workspace
      </button>

      <!-- Debug View (only in chat mode, dev mode only) -->
      <button
        v-if="viewMode === 'chat' && devModeRef"
        @click="$emit('toggle-view')"
        class="flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium text-purple-500 hover:bg-purple-500/10 transition-colors"
        title="Debug view"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0 1 12 12.75Zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 0 1-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 0 0 2.248-2.354M12 12.75a2.25 2.25 0 0 1-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 0 0-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 0 1 .4-2.253M12 8.25a2.25 2.25 0 0 0-2.248 2.146M12 8.25a2.25 2.25 0 0 1 2.248 2.146M8.683 5a6.032 6.032 0 0 1-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0 1 15.318 5m0 0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 0 0-.575-1.752M4.921 6a24.048 24.048 0 0 0-.392 3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 0 1-5.223 1.082" />
        </svg>
        Debug View
      </button>

      <!-- Return to Chat (only when in raw/debug mode) -->
      <button
        v-if="viewMode === 'raw'"
        @click="$emit('toggle-view')"
        class="flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium bg-purple-500/20 text-purple-500 hover:bg-purple-500/30 transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3" />
        </svg>
        Return to Chat
      </button>

      <!-- 3-dot Menu -->
      <div class="relative" ref="menuContainerRef">
        <button
          @click="toggleMenu"
          class="w-7 h-7 flex items-center justify-center rounded text-content-muted hover:text-content-secondary hover:bg-surface transition-colors"
          title="More options"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
          </svg>
        </button>

        <!-- Dropdown menu -->
        <div
          v-if="showMenu"
          class="absolute right-0 mt-1 w-44 bg-surface border border-edge rounded-lg shadow-xl z-50 py-1"
        >
          <button
            @click="handleClone"
            class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
            </svg>
            Clone chat
          </button>
          <button
            @click="handleClear"
            class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Clear messages
          </button>
          <div class="border-t border-edge my-1"></div>
          <button
            @click="handleDelete"
            class="w-full px-3 py-1.5 text-left text-xs text-red-500 hover:bg-red-500/10 transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
            Delete chat
          </button>

        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { devModeRef } from '../../appConfig'

interface Props {
  chatName?: string
  chatId: number
  viewMode: 'raw' | 'chat'
  settingsPanelVisible: boolean
}

const props = withDefaults(defineProps<Props>(), {
  chatName: '',
  settingsPanelVisible: true,
})

const emit = defineEmits<{
  (e: 'toggle-view'): void
  (e: 'toggle-settings-panel'): void
  (e: 'delete'): void
  (e: 'clone'): void
  (e: 'clear'): void
  (e: 'rename', name: string): void
}>()

// Open workspace folder in Finder
async function openWorkspace() {
  try {
    const response = await fetch(`/api/chats/${props.chatId}/workspace-path`)
    if (!response.ok) return
    const { path } = await response.json()
    const { openPath } = await import('@tauri-apps/plugin-opener')
    await openPath(path)
  } catch (err) {
    console.error('Failed to open workspace:', err)
  }
}

// Name editing state
const editingName = ref(false)
const editedName = ref('')
const nameInputRef = ref<HTMLInputElement | null>(null)

function startEditName() {
  editedName.value = props.chatName || ''
  editingName.value = true
  nextTick(() => {
    nameInputRef.value?.focus()
    nameInputRef.value?.select()
  })
}

function cancelEditName() {
  editingName.value = false
  editedName.value = ''
}

function saveName() {
  if (editedName.value.trim() && editedName.value !== props.chatName) {
    emit('rename', editedName.value.trim())
  }
  cancelEditName()
}

// Menu state
const showMenu = ref(false)
const menuContainerRef = ref<HTMLElement | null>(null)

function toggleMenu() {
  showMenu.value = !showMenu.value
}

function handleClone() {
  console.log('handleClone called, emitting clone event')
  showMenu.value = false
  emit('clone')
}

function handleClear() {
  showMenu.value = false
  emit('clear')
}

function handleDelete() {
  showMenu.value = false
  emit('delete')
}

// Close menu when clicking outside
function handleClickOutside(event: MouseEvent) {
  if (showMenu.value && menuContainerRef.value && !menuContainerRef.value.contains(event.target as Node)) {
    showMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
