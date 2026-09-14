<template>
  <div class="flex flex-col h-full min-h-0">
    <p v-if="error" class="p-4 text-content-muted">{{ error }}</p>
    <FileBrowser v-show="!selected && !error" :header-target="headerTarget" :header-hidden="!!selected || !!error" :root-name="file.name" @drag-root="dragWorkspaceFile($event, chatId, file)" :key="indexUrl" :entries="entries" :loading="loading" :thumbnail="entry => fileUrl(chatId, asFile(entry))" @open="selected = asFile($event)" @drag="(event, entry) => dragWorkspaceFile(event, chatId, asFile(entry))" />
    <template v-if="selected">
      <Teleport :to="headerTarget || 'body'" :disabled="!headerTarget">
      <div class="flex items-center gap-2 min-w-0 w-full" :class="headerTarget ? '' : 'px-3 py-2 border-b border-edge-subtle'">
        <IconButton title="Back to files" aria-label="Back to files" @click="selected = null"><ArrowLeftIcon class="w-4 h-4" /></IconButton>
        <div class="min-w-0 flex-1" draggable="true" @dragstart="dragWorkspaceFile($event, chatId, selected)">
          <div class="text-sm truncate">{{ selected.name }}</div>
          <div class="text-xs text-content-muted truncate">{{ selected.entry }} · {{ fileSize(selected.size) }}</div>
        </div>
        <FileActions :file="selected" :url="fileUrl(chatId, selected, 'content', true)" @attach="$emit('attach', selected)" @save="$emit('save', selected)" />
      </div>
      </Teleport>
      <FileViewer :url="fileUrl(chatId, selected)" :name="selected.name" :mime="selected.mime" :size="selected.size" class="flex-1 min-h-0" />
    </template>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { ArrowLeftIcon } from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import FileActions from '../chat/FileActions.vue'
import FileBrowser, { type BrowserEntry } from '../files/FileBrowser.vue'
import FileViewer from './FileViewer.vue'
import { fileUrl, fileSize, dragWorkspaceFile, type WorkspaceFile } from '../../utils/fileRefs'
const props = defineProps<{ chatId: number | string; file: WorkspaceFile; headerTarget?: HTMLElement | null }>()
defineEmits<{ attach: [file: WorkspaceFile]; save: [file: WorkspaceFile] }>()
const entries = ref<BrowserEntry[]>([]), selected = ref<WorkspaceFile | null>(null), error = ref(''), loading = ref(false)
const indexUrl = computed(() => fileUrl(props.chatId, props.file, 'index'))
function asFile(entry: BrowserEntry): WorkspaceFile {
  return { ...props.file, entry: entry.path, name: entry.name, mime: entry.mime || '', size: entry.size }
}
watch(indexUrl, async (url, _, cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort())
  selected.value = null; entries.value = []; error.value = ''; loading.value = true
  try { entries.value = (await axios.get(url, { signal: controller.signal })).data.entries }
  catch { if (!controller.signal.aborted) error.value = 'Unable to preview this archive' }
  finally { if (!controller.signal.aborted) loading.value = false }
}, { immediate: true })
</script>
