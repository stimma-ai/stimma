<template>
  <div class="flex flex-col h-full min-h-0">
    <div class="flex flex-wrap items-center gap-1 p-2 text-xs">
      <Button variant="ghost" size="sm" @click="folder = ''">Archive</Button>
      <Button v-for="(part, i) in parts" :key="i" variant="ghost" size="sm" @click="folder = parts.slice(0, i + 1).join('/') + '/'">/ {{ part }}</Button>
      <a :href="fileUrl(chatId, file, 'content', true)" class="ml-auto text-accent p-2">Download archive</a>
    </div>
    <p v-if="error" class="p-4 text-content-muted">{{ error }}</p>
    <div v-else class="flex flex-1 min-h-0 compact:flex-col">
      <div class="w-48 shrink-0 overflow-auto compact:w-full compact:max-h-48 divide-y divide-edge-subtle">
        <button v-if="folder" class="w-full text-left p-2 text-sm hover:bg-overlay-subtle" @click="folder = parts.slice(0, -1).join('/') + (parts.length > 1 ? '/' : '')">../</button>
        <button v-for="entry in visible" :key="entry.path" class="w-full text-left px-3 py-2 hover:bg-overlay-subtle text-xs" :class="selected?.entry === entry.path ? 'bg-selection/15' : ''" @click="openEntry(entry)">
          <span class="block truncate">{{ entry.directory ? '▸ ' : '' }}{{ entry.name }}</span>
          <span v-if="!entry.directory" class="font-mono text-content-muted">{{ fileSize(entry.size) }}</span>
        </button>
        <p v-if="!visible.length" class="p-3 text-content-muted text-xs">{{ loading ? 'Loading…' : 'Empty folder' }}</p>
      </div>
      <div class="flex-1 min-w-0 min-h-0 flex flex-col">
        <template v-if="selected">
          <div class="flex flex-wrap items-center gap-1 p-2 text-xs">
            <span class="truncate flex-1 font-mono">{{ selected.name }}</span>
            <Button variant="ghost" size="sm" @click="$emit('attach', selected)">Attach to reply</Button>
            <Button variant="ghost" size="sm" @click="$emit('save', selected)">Save to library</Button>
            <a :href="fileUrl(chatId, selected, 'content', true)" class="p-2 text-accent">Download</a>
          </div>
          <FileViewer :url="fileUrl(chatId, selected)" :name="selected.name" :mime="selected.mime" :size="selected.size" class="flex-1 min-h-0" />
        </template>
        <p v-else class="m-auto text-content-muted text-sm p-4">Choose an entry to preview</p>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import Button from '../ui/Button.vue'
import FileViewer from './FileViewer.vue'
import { fileUrl, fileSize, type WorkspaceFile } from '../../utils/fileRefs'
const props = defineProps<{ chatId: number | string; file: WorkspaceFile }>()
defineEmits<{ attach: [file: WorkspaceFile]; save: [file: WorkspaceFile] }>()
const entries = ref<any[]>([]), folder = ref(''), selected = ref<WorkspaceFile | null>(null), error = ref(''), loading = ref(false)
const parts = computed(() => folder.value.split('/').filter(Boolean))
const visible = computed(() => {
  const result = new Map<string, any>()
  for (const entry of entries.value) {
    if (!entry.path.startsWith(folder.value)) continue
    const rest = entry.path.slice(folder.value.length)
    if (!rest) continue
    const name = rest.split('/')[0], path = folder.value + name
    result.set(path, rest.includes('/') ? { path, name, directory: true } : entry)
  }
  return [...result.values()].sort((a, b) => Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name))
})
function openEntry(entry: any) {
  if (entry.directory) folder.value = entry.path + '/'
  else selected.value = { ...props.file, entry: entry.path, name: entry.name, mime: entry.mime, size: entry.size }
}
watch(() => fileUrl(props.chatId, props.file, 'index'), async (url, _, cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort())
  folder.value = ''; selected.value = null; entries.value = []; error.value = ''; loading.value = true
  try { entries.value = (await axios.get(url, { signal: controller.signal })).data.entries }
  catch (e) { if (!controller.signal.aborted) error.value = 'Unable to preview this archive' }
  finally { if (!controller.signal.aborted) loading.value = false }
}, { immediate: true })
</script>
