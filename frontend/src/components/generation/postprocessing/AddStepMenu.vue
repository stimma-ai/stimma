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

    <div class="max-h-72 overflow-y-auto py-1">
      <!-- STP tools -->
      <template v-if="filteredTools.length">
        <div class="px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-content-muted">
          STP tools <span class="text-purple-400 normal-case tracking-normal">image → image</span>
        </div>
        <button
          v-for="tool in filteredTools"
          :key="tool.full_tool_id"
          type="button"
          class="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-overlay-faint transition-colors"
          @click="$emit('add-tool', tool)"
        >
          <div class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 bg-purple-500/15 text-purple-400">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
              <path fill-rule="evenodd" d="M14.5 10a4.5 4.5 0 004.284-5.882c-.105-.324-.51-.391-.752-.15L15.34 6.66a.454.454 0 01-.493.11 3.01 3.01 0 01-1.618-1.616.455.455 0 01.11-.494l2.694-2.692c.24-.241.174-.647-.15-.752a4.5 4.5 0 00-5.873 4.575c.055.873-.128 1.808-.8 2.368l-7.23 6.024a2.724 2.724 0 103.837 3.837l6.024-7.23c.56-.672 1.495-.855 2.368-.8.096.007.193.01.291.01zM5 16a1 1 0 11-2 0 1 1 0 012 0z" clip-rule="evenodd" />
            </svg>
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content truncate">{{ tool.name }}</div>
            <div class="text-xs text-content-muted truncate">{{ tool.subtitle || taskTypeLabel(tool) }}</div>
          </div>
        </button>
      </template>

      <!-- Built-in filters -->
      <template v-if="filteredFilters.length">
        <div class="px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-content-muted">
          Filters <span class="text-green-500 normal-case tracking-normal">built-in</span>
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

function taskTypeLabel(tool: ProviderTool): string {
  const tts = tool.task_types?.length ? tool.task_types : [tool.task_type]
  return tts.join(', ')
}

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
