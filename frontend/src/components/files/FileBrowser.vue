<template>
  <div class="flex flex-col flex-1 min-h-0">
    <Teleport :to="headerTarget || 'body'" :disabled="!headerTarget">
    <div v-show="!headerHidden" class="flex items-center gap-1 min-w-0 w-full compact:flex-wrap" :class="headerTarget ? '' : 'px-3 py-2 border-b border-edge-subtle'">
      <nav aria-label="Folder" class="flex items-center gap-1 min-w-0 flex-1 overflow-x-auto text-sm compact:basis-full">
        <button class="shrink-0 px-2 py-1 rounded hover:bg-overlay-subtle" :draggable="!!rootName" @dragstart="$emit('drag-root', $event)" @click="folder = ''">{{ rootName || 'Files' }}</button>
        <template v-for="(part, index) in parts" :key="index">
          <ChevronRightIcon class="w-3 h-3 shrink-0 text-content-muted" />
          <button class="shrink-0 px-2 py-1 rounded hover:bg-overlay-subtle" @click="folder = parts.slice(0, index + 1).join('/') + '/'">{{ part }}</button>
        </template>
      </nav>
      <div class="flex items-center gap-3 shrink-0" role="group" aria-label="Browser view">
        <SettingsDropdown v-model="sortOrder" :options="sortOptions" class="px-2" />
        <div class="flex items-center gap-0.5 p-0.5 rounded-md border border-edge-subtle bg-base" role="group" aria-label="View mode">
          <IconButton title="Grid view" aria-label="Grid view" :aria-pressed="mode === 'grid'" :class="mode === 'grid' ? 'bg-surface-raised text-content' : ''" @click="mode = 'grid'"><Squares2X2Icon class="w-4 h-4" /></IconButton>
          <IconButton title="List view" aria-label="List view" :aria-pressed="mode === 'list'" :class="mode === 'list' ? 'bg-surface-raised text-content' : ''" @click="mode = 'list'"><ListBulletIcon class="w-4 h-4" /></IconButton>
          <IconButton title="Columns view" aria-label="Columns view" :aria-pressed="mode === 'columns'" :class="mode === 'columns' ? 'bg-surface-raised text-content' : ''" @click="mode = 'columns'"><ViewColumnsIcon class="w-4 h-4" /></IconButton>
        </div>
      </div>
      <div v-if="$slots.actions" class="border-l border-edge-subtle pl-3 ml-2 shrink-0" role="group" aria-label="File actions"><slot name="actions" /></div>
    </div>
    </Teleport>
    <div v-if="mode === 'columns'" class="flex flex-1 min-h-0 overflow-auto">
      <div v-for="path in columnPaths" :key="path" class="w-56 shrink-0 overflow-auto p-2 border-r border-edge-subtle">
        <button v-for="entry in entriesAt(path)" :key="entry.path" class="flex items-center gap-2 px-2 py-2 w-full rounded-md text-left text-sm hover:bg-overlay-subtle" :class="folder.startsWith(entry.path + '/') ? 'bg-surface-raised' : ''" @click="entry.directory ? folder = entry.path.replace(/\/$/, '') + '/' : $emit('open', entry)" :draggable="!entry.directory" @dragstart="$emit('drag', $event, entry)">
          <component :is="entry.directory ? FolderIcon : DocumentIcon" class="w-4 h-4 shrink-0 text-content-muted" />
          <span class="truncate flex-1">{{ entry.name }}</span><ChevronRightIcon v-if="entry.directory" class="w-3 h-3 text-content-muted" />
        </button>
      </div>
    </div>
    <div v-else class="flex-1 min-h-0 overflow-auto p-3">
      <div :class="mode === 'grid' ? 'grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-3' : 'flex flex-col gap-0.5'">
        <button v-for="entry in visible" :key="entry.path" :aria-label="entry.name" class="rounded-lg text-left hover:bg-overlay-subtle focus-visible:ring-2 focus-visible:ring-accent outline-none min-w-0" :class="mode === 'grid' ? 'p-2 border border-edge-subtle' : 'flex items-center gap-3 px-3 py-2'" @click="entry.directory ? folder = entry.path.replace(/\/$/, '') + '/' : $emit('open', entry)" :draggable="!entry.directory" @dragstart="$emit('drag', $event, entry)">
          <div :class="mode === 'grid' ? 'h-24 flex items-center justify-center mb-2 bg-surface/50 rounded overflow-hidden' : 'w-5 h-5 shrink-0 text-content-muted'">
            <img v-if="mode === 'grid' && !entry.directory && entry.mime?.startsWith('image/') && thumbnail" :src="thumbnail(entry)" alt="" loading="lazy" class="w-full h-full object-contain" />
            <component v-else :is="entry.directory ? FolderIcon : DocumentIcon" :class="mode === 'grid' ? 'w-9 h-9 text-content-muted' : 'w-5 h-5'" />
          </div>
          <span class="block truncate flex-1 text-sm">{{ entry.name }}</span>
          <span class="block text-xs text-content-muted tabular-nums" :class="mode === 'grid' ? 'mt-1' : 'shrink-0'">{{ entry.directory ? 'Folder' : fileSize(entry.size) }}</span>
        </button>
      </div>
      <p v-if="!visible.length" class="p-8 text-center text-sm text-content-muted">{{ loading ? 'Loading…' : 'Empty folder' }}</p>
    </div>
    <div class="px-4 py-2 text-xs text-content-muted border-t border-edge-subtle">{{ visible.length }} items</div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { FolderIcon, DocumentIcon, ChevronRightIcon, ListBulletIcon, Squares2X2Icon, ViewColumnsIcon } from '@heroicons/vue/24/outline'
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import IconButton from '../ui/IconButton.vue'
import { fileSize } from '../../utils/fileRefs'
export interface BrowserEntry { path: string; name: string; directory: boolean; size: number; mime?: string }
const props = defineProps<{ headerTarget?: HTMLElement | null; headerHidden?: boolean; rootName?: string; entries: BrowserEntry[]; loading?: boolean; thumbnail?: (entry: BrowserEntry) => string }>()
defineEmits<{ 'drag-root': [event: DragEvent]; open: [entry: BrowserEntry]; drag: [event: DragEvent, entry: BrowserEntry] }>()
const folder = ref(''), mode = ref('grid'), sortOrder = ref('name_asc')
const sortOptions = [
  { value: 'name_asc', label: 'Name A–Z' },
  { value: 'name_desc', label: 'Name Z–A' },
  { value: 'size_desc', label: 'Largest first' },
  { value: 'size_asc', label: 'Smallest first' },
  { value: 'type_asc', label: 'Kind A–Z' },
  { value: 'type_desc', label: 'Kind Z–A' },
]
const sort = computed(() => sortOrder.value.split('_')[0])
const descending = computed(() => sortOrder.value.endsWith('_desc'))
const parts = computed(() => folder.value.split('/').filter(Boolean))
const columnPaths = computed(() => ['', ...parts.value.map((_, i) => parts.value.slice(0, i + 1).join('/') + '/')])
const visible = computed(() => entriesAt(folder.value))
function entriesAt(folderPath: string) {
  const result = new Map<string, BrowserEntry>()
  for (const entry of props.entries) {
    if (!entry.path.startsWith(folderPath)) continue
    const rest = entry.path.slice(folderPath.length)
    if (!rest) continue
    const name = rest.split('/')[0], path = folderPath + name
    result.set(path, rest.includes('/') ? { path, name, directory: true, size: 0 } : entry)
  }
  return [...result.values()].sort((a, b) => {
    const order = sort.value === 'size' ? a.size - b.size : sort.value === 'type' ? (a.mime || '').localeCompare(b.mime || '') : 0
    return Number(b.directory) - Number(a.directory) || (descending.value ? -1 : 1) * (order || a.name.localeCompare(b.name, undefined, { numeric: true }))
  })
}
</script>
