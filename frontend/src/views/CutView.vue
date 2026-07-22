<template>
  <div class="w-full h-full flex flex-col bg-surface-overlay text-content-secondary min-h-0">
    <!-- Page header (PageHeader grammar, matching ToolView): plain, one hairline
         separates it from the workspace cards floating below. -->
    <div class="flex-none px-6 pt-4 pb-3 border-b border-edge-subtle">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0 flex items-center gap-3 flex-1">
          <div class="w-7 h-7 rounded-md bg-accent/12 flex items-center justify-center flex-shrink-0 text-accent-hi">
            <FilmIcon class="w-4 h-4" />
          </div>
          <input
            v-no-autocorrect
            ref="titleInputRef"
            v-model="titleDraft"
            placeholder="Name this cut..."
            class="min-w-0 flex-1 bg-transparent text-lg font-semibold text-content outline-none border-none placeholder:text-content-muted placeholder:italic placeholder:font-normal"
            @keydown.enter="$event.target.blur()"
            @blur="commitTitle"
          />
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <IconButton title="Undo" :disabled="!viewerRef?.canUndo" @click="viewerRef?.doUndo()">
            <ArrowUturnLeftIcon class="w-4 h-4" />
          </IconButton>
          <IconButton title="Redo" :disabled="!viewerRef?.canRedo" @click="viewerRef?.doRedo()">
            <ArrowUturnRightIcon class="w-4 h-4" />
          </IconButton>
          <button
            class="bg-surface-raised hover:bg-surface-hover text-content rounded-md px-3 py-1.5 text-sm transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="viewerRef?.saving"
            @click="viewerRef?.save()"
          >
            {{ viewerRef?.saving ? 'Saving…' : 'Save version' }}
          </button>
          <div class="relative">
            <button
              class="cursor-pointer transition-colors flex items-center justify-center px-3 py-2 rounded-md bg-surface-raised text-content-secondary hover:bg-surface-hover hover:text-content"
              title="Cut options"
              @click="menuOpen = !menuOpen"
            >
              <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><circle cx="10" cy="4" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="10" cy="16" r="1.5"/></svg>
            </button>
            <div v-if="menuOpen" class="fixed inset-0 z-menu" @click="menuOpen = false"></div>
            <div
              v-if="menuOpen"
              class="absolute right-0 top-full mt-1 bg-surface border border-edge-subtle rounded-lg shadow-lg py-1 min-w-[180px] z-menu"
            >
              <button
                class="w-full flex items-center gap-2 px-3 py-2 text-xs text-content-secondary hover:bg-overlay-subtle hover:text-content text-left"
                @click="menuOpen = false; showInLibrary()"
              >
                Show in library
              </button>
              <button
                class="w-full flex items-center gap-2 px-3 py-2 text-xs text-content-secondary hover:bg-overlay-subtle hover:text-content text-left"
                @click="menuOpen = false; startRename()"
              >
                Rename
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Workspace: sequencer card floats on base, chat dock card below —
         same two-card composition as ToolView's columns + agent dock. -->
    <div class="flex-1 min-h-0 flex flex-col">
      <div class="flex-1 min-h-0 m-3 rounded-lg border border-edge-subtle bg-surface overflow-hidden relative">
        <TimelineViewer
          v-if="assetIdNumber"
          ref="viewerRef"
          :key="assetIdNumber"
          :initial-asset-id="assetIdNumber"
          class="absolute inset-0"
          @loaded="onLoaded"
        />
      </div>

      <!-- Agent dock: the standard chat input (voice, attachments), send
           disabled until the cut agent is connected. -->
      <div class="flex-none mx-3 mb-3 rounded-lg border border-edge-subtle bg-surface px-4 pt-3 pb-4">
        <ChatInputBox
          v-model="agentDraft"
          :attachments="agentAttachments"
          placeholder="Ask the agent to plan, fill, or rearrange this cut..."
          voice-surface="main_chat"
          @update:attachments="agentAttachments = $event"
        >
          <template #actions>
            <button
              class="w-8 h-8 flex items-center justify-center rounded-full bg-content text-surface transition-colors disabled:opacity-30"
              disabled
              title="Agent not connected yet"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
                <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)" />
              </svg>
            </button>
          </template>
        </ChatInputBox>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUturnLeftIcon, ArrowUturnRightIcon, FilmIcon } from '@heroicons/vue/24/outline'
import TimelineViewer from '../components/viewers/TimelineViewer.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import IconButton from '../components/ui/IconButton.vue'
import { makeTabId, useWorkspaceTabs } from '../composables/useWorkspaceTabs'

const route = useRoute()
const router = useRouter()
const { updateTabName } = useWorkspaceTabs()

const viewerRef = ref(null)
const titleInputRef = ref(null)
const titleDraft = ref('')
const committedTitle = ref('')
const menuOpen = ref(false)
const agentDraft = ref('')
const agentAttachments = ref([])

const assetIdNumber = computed(() => {
  const id = parseInt(route.params.id, 10)
  return isNaN(id) ? null : id
})

function onLoaded(payload) {
  const title = payload?.title || ''
  committedTitle.value = title
  // Don't clobber an in-progress edit (e.g. the agent renames mid-typing)
  if (document.activeElement !== titleInputRef.value) {
    titleDraft.value = title
  }
}

async function commitTitle() {
  const title = titleDraft.value.trim()
  if (title === committedTitle.value) return
  await viewerRef.value?.setTitle(title)
  committedTitle.value = title
  if (assetIdNumber.value) {
    updateTabName(makeTabId('cut', String(assetIdNumber.value)), title)
  }
}

function startRename() {
  titleInputRef.value?.focus()
  titleInputRef.value?.select()
}

function showInLibrary() {
  router.push({ name: 'browse', query: { slideshowAsset: String(assetIdNumber.value) } })
}
</script>
