<template>
  <div
    ref="menuRef"
    class="absolute z-50 left-0 right-0 mt-1 rounded-lg border border-edge bg-surface shadow-xl overflow-hidden"
  >
    <!-- Search -->
    <div class="relative border-b border-edge-subtle">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-content-muted/50 pointer-events-none">
        <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
      </svg>
      <input v-no-autocorrect
        ref="searchInput"
        v-model="query"
        type="text"
        placeholder="Search steps…"
        class="w-full pl-8 pr-3 py-2 bg-transparent text-sm text-content focus:outline-none select-text"
        @keydown.escape="$emit('close')"
      />
    </div>

    <div class="max-h-96 overflow-y-auto py-1">
      <!-- Built-in filters (highest priority) -->
      <template v-if="filteredFilters.length">
        <div class="px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-content-muted">
          Filters
        </div>
        <button
          v-for="filter in filteredFilters"
          :key="filter.id"
          type="button"
          class="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-overlay-faint transition-colors"
          @click="$emit('add-filter', filter)"
        >
          <div class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 bg-white/[0.06] text-content-tertiary">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
              <path d="M10 3.75a2 2 0 10-4 0 2 2 0 004 0zM17.25 4.5a.75.75 0 000-1.5h-5.5a.75.75 0 000 1.5h5.5zM5 3.75a.75.75 0 01-.75.75h-1.5a.75.75 0 010-1.5h1.5a.75.75 0 01.75.75zM4.25 17a.75.75 0 000-1.5h-1.5a.75.75 0 000 1.5h1.5zM17.25 17a.75.75 0 000-1.5h-5.5a.75.75 0 000 1.5h5.5zM9 10a.75.75 0 01-.75.75h-5.5a.75.75 0 010-1.5h5.5A.75.75 0 019 10zM17.25 10.75a.75.75 0 000-1.5h-1.5a.75.75 0 000 1.5h1.5zM14 16.25a2 2 0 10-4 0 2 2 0 004 0zM10 8a2 2 0 114 0 2 2 0 01-4 0z" />
            </svg>
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content truncate">{{ filter.label }}</div>
            <div class="text-xs text-content-muted truncate">{{ filter.description }}</div>
          </div>
        </button>
      </template>

      <!-- STP tools, grouped by category in priority order -->
      <template v-for="group in toolGroups" :key="group.label">
        <div class="px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-content-muted">
          {{ group.label }}
        </div>
        <button
          v-for="tool in group.tools"
          :key="tool.full_tool_id"
          type="button"
          class="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-overlay-faint transition-colors"
          @click="$emit('add-tool', tool)"
        >
          <div :class="['w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0', getTaskTypeGradientClass(chainTaskType(tool))]">
            <svg class="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" :d="getTaskTypeIconPath(chainTaskType(tool))" />
            </svg>
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content truncate">{{ tool.name }}</div>
            <div class="text-xs text-content-muted truncate">{{ tool.subtitle || tool.provider_name || tool.provider_id }}</div>
          </div>
        </button>
      </template>

      <div v-if="!filteredTools.length && !filteredFilters.length" class="px-3 py-4 text-center text-xs text-content-muted">
        No matching steps
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ProviderTool } from '../../../composables/useProvidersApi'
import type { ChainFilterDef } from '@stimma/image-editor'
import { getTaskTypeGradientClass, getTaskTypeIconPath } from '../../../utils/taskTypeIcons'
import { CHAIN_TOOL_TASK_TYPES } from '../../../utils/postProcessingChain'

const props = defineProps<{
  /** Candidate STP tool steps (already filtered to chain-compatible task types). */
  tools: ProviderTool[]
  /** Built-in filter defs offered for the current running media type. */
  filters: ChainFilterDef[]
}>()

const emit = defineEmits<{
  (e: 'add-tool', tool: ProviderTool): void
  (e: 'add-filter', filter: ChainFilterDef): void
  (e: 'close'): void
}>()

const query = ref('')
const menuRef = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)

const filteredTools = computed(() => {
  const q = query.value.toLowerCase().trim()
  if (!q) return props.tools
  return props.tools.filter(t =>
    t.name.toLowerCase().includes(q) ||
    (t.subtitle || '').toLowerCase().includes(q) ||
    t.full_tool_id.toLowerCase().includes(q)
  )
})

const filteredFilters = computed(() => {
  const q = query.value.toLowerCase().trim()
  if (!q) return props.filters
  return props.filters.filter(f =>
    f.label.toLowerCase().includes(q) || f.description.toLowerCase().includes(q)
  )
})

// The chain-relevant task type, for the standard task-type icon treatment.
function chainTaskType(tool: ProviderTool): string {
  const chainTypes = new Set<string>(CHAIN_TOOL_TASK_TYPES)
  const tts = tool.task_types?.length ? tool.task_types : [tool.task_type]
  return tts.find(tt => chainTypes.has(tt)) || tool.task_type
}

// Tool steps are grouped by category in the order people reach for them.
// Anything whose task type isn't listed falls into a trailing "Other" group.
const TOOL_CATEGORIES: { label: string; taskTypes: string[] }[] = [
  { label: 'Upscale', taskTypes: ['upscale-image', 'upscale-video'] },
  { label: 'Background Removal', taskTypes: ['remove-background'] },
  { label: 'Image Edit', taskTypes: ['image-to-image'] },
  { label: 'Image to Video', taskTypes: ['image-to-video'] },
]

const toolGroups = computed(() => {
  const buckets = TOOL_CATEGORIES.map(c => ({ label: c.label, tools: [] as ProviderTool[] }))
  const other = { label: 'Other', tools: [] as ProviderTool[] }
  for (const tool of filteredTools.value) {
    const tt = chainTaskType(tool)
    // Built-in filters are surfaced authoritatively by the Filters section
    // above; the provider also registers them as 'filter' STP tools, so skip
    // those here to avoid listing every filter twice.
    if (tt === 'filter') continue
    const idx = TOOL_CATEGORIES.findIndex(c => c.taskTypes.includes(tt))
    if (idx >= 0) buckets[idx].tools.push(tool)
    else other.tools.push(tool)
  }
  return [...buckets, other].filter(g => g.tools.length)
})

function onClickOutside(ev: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(ev.target as Node)) {
    emit('close')
  }
}

onMounted(() => {
  // Defer so the click that opened the menu doesn't immediately close it.
  setTimeout(() => document.addEventListener('mousedown', onClickOutside), 0)
  searchInput.value?.focus()
})

onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))
</script>
