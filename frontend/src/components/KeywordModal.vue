<template>
  <div class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal p-8" @click.self="close">
    <div class="bg-surface border border-edge rounded-lg w-full max-w-[600px] max-h-[80vh] flex flex-col shadow-[0_20px_25px_-5px_rgba(0,0,0,0.5)]">
      <div class="flex justify-between items-center px-6 py-6 border-b border-edge">
        <h2 class="m-0 text-xl font-semibold text-content">Keywords</h2>
        <button class="bg-transparent border-none text-content-tertiary cursor-pointer p-2 flex items-center justify-center rounded transition-all hover:bg-overlay-light hover:text-content" @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="relative px-6 py-6 border-b border-edge">
        <svg class="absolute left-8 top-1/2 -translate-y-1/2 w-5 h-5 text-content-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input v-no-autocorrect
          type="text"
          v-model="searchQuery"
          @input="handleSearchInput"
          placeholder="Search keywords..."
          class="w-full bg-surface-raised border border-edge-strong rounded-lg py-3 pr-4 pl-11 text-content text-sm transition-all focus:outline-none focus:border-accent focus:bg-surface placeholder:text-content-muted"
          autofocus
        />
      </div>

      <div
        ref="scrollContainer"
        class="flex-1 overflow-y-auto p-2 keyword-list"
        @scroll="handleScroll"
      >
        <!-- Initial loading skeleton -->
        <div v-if="isInitialLoading" class="space-y-1">
          <div v-for="i in 10" :key="`skeleton-${i}`" class="flex justify-between items-center py-3.5 px-4 rounded-lg bg-overlay-subtle animate-pulse">
            <div class="h-4 bg-overlay-light rounded w-32"></div>
            <div class="h-3 bg-overlay-light rounded w-12"></div>
          </div>
        </div>

        <!-- Keyword list -->
        <div v-else>
          <div
            v-for="kw in keywords"
            :key="kw.keyword"
            @click="toggleKeyword(kw.keyword)"
            :class="[
              'flex justify-between items-center py-3.5 px-4 mb-1 rounded-lg cursor-pointer transition-all',
              isSelected(kw.keyword)
                ? 'bg-selection/20 border border-selection hover:bg-selection/30'
                : 'bg-transparent hover:bg-overlay-subtle'
            ]"
          >
            <span :class="[
              'text-[15px] font-medium',
              isSelected(kw.keyword) ? 'text-selection font-semibold' : 'text-content'
            ]">{{ kw.keyword }}</span>
            <span :class="[
              'text-[13px] font-normal',
              isSelected(kw.keyword) ? 'text-selection' : 'text-content-muted'
            ]">({{ kw.count }})</span>
          </div>

          <!-- Loading indicator for pagination -->
          <div v-if="isLoading && !isInitialLoading" class="text-center py-4 text-content-muted">
            <div class="inline-block w-5 h-5 border-2 border-edge-strong border-t-indigo-500 rounded-full animate-spin"></div>
          </div>

          <!-- No results message -->
          <div v-if="!isLoading && keywords.length === 0" class="text-center py-12 px-4 text-content-muted text-sm">
            <span v-if="searchQuery">No keywords found matching "{{ searchQuery }}"</span>
            <span v-else>No keywords found</span>
          </div>

          <!-- End of results message -->
          <div v-if="!isLoading && hasMore === false && keywords.length > 0" class="text-center py-4 text-content-muted text-xs">
            Showing {{ keywords.length }} of {{ totalCount }} keywords
          </div>
        </div>
      </div>

      <div class="px-6 py-6 border-t border-edge flex justify-between items-center">
        <span class="text-sm text-content-muted">
          <span v-if="isInitialLoading">Loading keywords...</span>
          <span v-else>{{ totalCount }} total keywords</span>
        </span>
        <button class="bg-accent text-white border-none py-3 px-8 rounded-lg text-[15px] font-semibold cursor-pointer transition-all hover:bg-accent/90 hover:-translate-y-px hover:shadow-[0_4px_6px_-1px_rgba(99,102,241,0.3)] active:translate-y-0" @click="close">Done</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAssetApi } from '../composables/useAssetApi'

const props = defineProps({
  selectedKeywords: {
    type: Array,
    required: true,
    default: () => []
  },
  filterParams: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['toggle-keyword', 'close'])

const { getTopKeywords } = useAssetApi()

const keywords = ref([])
const searchQuery = ref('')
const isLoading = ref(false)
const isInitialLoading = ref(true)
const hasMore = ref(true)
const totalCount = ref(0)
const scrollContainer = ref(null)

const PAGE_SIZE = 50
let currentOffset = 0
let searchDebounceTimer = null

async function loadKeywords(reset = false) {
  if (isLoading.value || (!hasMore.value && !reset)) return

  isLoading.value = true

  if (reset) {
    currentOffset = 0
    keywords.value = []
    hasMore.value = true
  }

  try {
    const params = {
      ...props.filterParams,
      limit: PAGE_SIZE,
      offset: currentOffset,
      use_preview_counts: true
    }

    if (searchQuery.value) {
      params.search = searchQuery.value
    }

    const response = await getTopKeywords(params)

    if (reset) {
      keywords.value = response.keywords
    } else {
      keywords.value.push(...response.keywords)
    }

    totalCount.value = response.total_unique
    currentOffset += response.keywords.length

    // Check if we have more keywords to load
    hasMore.value = keywords.value.length < totalCount.value
  } catch (error) {
    console.error('Failed to load keywords:', error)
  } finally {
    isLoading.value = false
    isInitialLoading.value = false
  }
}

function handleScroll(event) {
  const container = event.target
  const scrollPercentage = (container.scrollTop + container.clientHeight) / container.scrollHeight

  // Load more when scrolled 80% down
  if (scrollPercentage > 0.8 && hasMore.value && !isLoading.value) {
    loadKeywords()
  }
}

function handleSearchInput() {
  clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    isInitialLoading.value = true // Show skeleton during search
    loadKeywords(true) // Reset and reload with search
  }, 300)
}

function isSelected(keyword) {
  return props.selectedKeywords.includes(keyword)
}

function toggleKeyword(keyword) {
  emit('toggle-keyword', keyword)
}

function close() {
  emit('close')
}

onMounted(() => {
  loadKeywords(true)
})
</script>

<style scoped>
/* Scrollbar styling */
.keyword-list::-webkit-scrollbar {
  -webkit-appearance: none;
  width: 8px;
}

.keyword-list::-webkit-scrollbar-track {
  background: var(--color-surface);
}

.keyword-list::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 4px;
}

.keyword-list::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}
</style>
