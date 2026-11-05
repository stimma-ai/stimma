<template>
  <PageHeader tier="compact">
    <!-- Chat name. The compact header carries the name on phones. -->
    <template #title>
      <input v-no-autocorrect
        v-if="editingName"
        ref="nameInputRef"
        v-model="editedName"
        @blur="saveName"
        @keydown.enter="saveName"
        @keydown.escape="cancelEditName"
        class="w-64 max-w-full rounded-md border border-transparent bg-overlay-subtle px-2 py-1 text-base font-semibold text-content focus:outline-none focus:border-accent"
      />
      <span
        v-else-if="chatName"
        @dblclick="startEditName"
        class="cursor-pointer hover:text-content-secondary"
        title="Double-click to rename"
      >{{ chatName }}</span>
      <span
        v-else
        @click="startEditName"
        class="cursor-pointer text-content-muted hover:text-content-secondary"
      >Name this chat...</span>
    </template>

    <template v-if="mcpDriven && !editingName" #meta>
      <span
        class="shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10"
        title="Driven by a connected assistant over MCP"
      >MCP</span>
    </template>

    <template #actions>
      <!-- Settings Panel Toggle -->
      <IconButton
        size="lg"
        :active="settingsPanelVisible"
        title="Toggle settings panel"
        aria-label="Toggle settings panel"
        @click="$emit('toggle-settings-panel')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="h-icon-nav w-icon-nav">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75a4.5 4.5 0 0 1-4.884 4.484c-1.076-.091-2.264.071-2.95.904l-7.152 8.684a2.548 2.548 0 1 1-3.586-3.586l8.684-7.152c.833-.686.995-1.874.904-2.95a4.5 4.5 0 0 1 6.336-4.486l-3.276 3.276a3.004 3.004 0 0 0 2.25 2.25l3.276-3.276c.256.565.398 1.192.398 1.852Z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.867 19.125h.008v.008h-.008v-.008Z" />
        </svg>
      </IconButton>

      <!-- Artifact panel toggle. Always here and always live so it never hops
           or dead-ends; neutral-raised while the panel is open. -->
      <IconButton
        size="lg"
        :active="artifactOpen"
        :title="artifactOpen ? 'Hide preview panel' : 'Show preview panel'"
        :aria-label="artifactOpen ? 'Hide preview panel' : 'Show preview panel'"
        @click="$emit('toggle-artifact')"
      >
        <ArtifactPanelIcon />
      </IconButton>

      <!-- Open Workspace (dev mode only) -->
      <Button
        v-if="devModeRef"
        variant="ghost"
        size="sm"
        title="Open workspace folder in Finder"
        @click="openWorkspace"
      >
        <template #icon><FolderOpenIcon class="h-icon-inline w-icon-inline" /></template>
        Open Workspace
      </Button>

      <!-- Debug View (only in chat mode, dev mode only) -->
      <Button
        v-if="viewMode === 'chat' && devModeRef"
        variant="ghost"
        size="sm"
        title="Debug view"
        @click="$emit('toggle-view')"
      >
        <template #icon><BugAntIcon class="h-icon-inline w-icon-inline" /></template>
        Debug View
      </Button>

      <!-- Return to Chat (only when in raw/debug mode) -->
      <Button
        v-if="viewMode === 'raw'"
        variant="secondary"
        size="sm"
        @click="$emit('toggle-view')"
      >
        <template #icon><ArrowUturnLeftIcon class="h-icon-inline w-icon-inline" /></template>
        Return to Chat
      </Button>
    </template>

    <template #menu>
      <!-- Overflow menu -->
      <div class="relative" ref="menuContainerRef">
        <OverflowButton size="lg" @click="toggleMenu" />

        <!-- Dropdown menu -->
        <div
          v-if="showMenu"
          class="absolute right-0 mt-1 w-44 bg-surface border border-edge rounded-lg shadow-xl z-menu py-1"
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
          <button
            v-if="devModeRef"
            @click="handleCopyRawMessages"
            class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
            </svg>
            Copy raw chat messages
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
    </template>
  </PageHeader>
</template>

<script setup lang="ts">
import ArtifactPanelIcon from './ArtifactPanelIcon.vue'
import PageHeader from '../ui/PageHeader.vue'
import IconButton from '../ui/IconButton.vue'
import OverflowButton from '../ui/OverflowButton.vue'
import Button from '../ui/Button.vue'
import { ArrowUturnLeftIcon, BugAntIcon, FolderOpenIcon } from '@heroicons/vue/24/outline'
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { devModeRef } from '../../appConfig'

interface Props {
  chatName?: string
  mcpDriven?: boolean
  chatId: number
  viewMode: 'raw' | 'chat'
  settingsPanelVisible: boolean
  artifactOpen?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  chatName: '',
  mcpDriven: false,
  settingsPanelVisible: true,
  artifactOpen: false,
})

const emit = defineEmits<{
  (e: 'toggle-view'): void
  (e: 'toggle-settings-panel'): void
  (e: 'toggle-artifact'): void
  (e: 'delete'): void
  (e: 'clone'): void
  (e: 'clear'): void
  (e: 'copy-raw-messages'): void
  (e: 'rename', name: string): void
}>()

// Open workspace folder in Finder
async function openWorkspace() {
  try {
    const response = await fetch(`/api/chats/${props.chatId}/workspace-path`)
    if (!response.ok) return
    const { path } = await response.json()
    const { desktop } = await import('../../desktop')
    await desktop.openPath(path)
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

function handleCopyRawMessages() {
  showMenu.value = false
  emit('copy-raw-messages')
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
