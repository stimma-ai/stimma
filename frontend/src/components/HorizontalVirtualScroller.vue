<template>
  <div class="horizontal-virtual-scroller" :style="{ height: `${height}px` }">
    <div
      ref="scrollContainer"
      class="scroll-container"
      @scroll="handleScroll"
      @wheel="handleWheel"
      :style="{ height: `${height}px` }"
    >
      <!-- Content sits centred in the row with a small gutter each side so a
           selection ring (which draws outside the item box) is never clipped
           at the row's top edge or at the first/last item. -->
      <div
        class="scroll-content"
        :style="{
          width: `${totalWidth + edgeGutter}px`,
          height: `${itemHeight}px`,
          marginTop: `${Math.max(0, (height - itemHeight) / 2)}px`,
          marginLeft: `${edgeGutter}px`
        }"
      >
        <div
          v-for="item in visibleItems"
          :key="item.id"
          class="scroll-item"
          :style="{
            position: 'absolute',
            left: `${item._position}px`,
            width: `${itemWidth}px`,
            height: `${itemHeight}px`
          }"
        >
          <slot :item="item" :index="item._index"></slot>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

const props = defineProps({
  // Total number of items in the data set
  totalCount: {
    type: Number,
    required: true
  },
  // Function to provide a page of items: (pageNumber, pageSize) => Promise<items[]>
  pageProvider: {
    type: Function,
    required: true
  },
  // Optional sync function to get item at index - reads directly from source of truth
  // When provided, the scroller won't cache items internally
  itemGetter: {
    type: Function, // (index: number) => item | null
    default: null
  },
  // Current active item index
  currentIndex: {
    type: Number,
    default: 0
  },
  // Item dimensions
  itemWidth: {
    type: Number,
    default: 140 // Width for ~100-120px height image
  },
  itemHeight: {
    type: Number,
    default: 120
  },
  // Gap between items
  itemGap: {
    type: Number,
    default: 12
  },
  // Breathing room at the row's start and end (px), for rings drawn outside
  // the first and last item
  gutter: {
    type: Number,
    default: 0
  },
  // Permit first/last thumbnails to occupy the center of a compact gallery.
  centerEdges: { type: Boolean, default: false },
  // Container height
  height: {
    type: Number,
    default: 160
  },
  // Number of items to load per chunk
  chunkSize: {
    type: Number,
    default: 50
  },
  // Buffer size (items to render outside visible area)
  bufferSize: {
    type: Number,
    default: 10
  },
  // Auto-center current item
  autoCenter: {
    type: Boolean,
    default: true
  }
})

const scrollContainer = ref(null)
const scrollLeft = ref(0)
const containerWidth = ref(0)
const edgeGutter = computed(() => props.centerEdges ? Math.max(props.gutter, (containerWidth.value - props.itemWidth) / 2) : props.gutter)
let resizeObserver
let scrollRequest = 0

// Cache for loaded items
const itemsCache = ref(new Map())
const loadingChunks = ref(new Set())

// Flag to skip scroll animation after prepend adjustment
const skipNextScroll = ref(false)

// Calculate total width
const totalWidth = computed(() => {
  return props.totalCount * (props.itemWidth + props.itemGap) - props.itemGap
})

// Calculate visible range
const visibleRange = computed(() => {
  const start = Math.floor((scrollLeft.value - edgeGutter.value) / (props.itemWidth + props.itemGap))
  const end = Math.ceil((scrollLeft.value + containerWidth.value - edgeGutter.value) / (props.itemWidth + props.itemGap))
  return {
    start: Math.max(0, start - props.bufferSize),
    end: Math.min(props.totalCount, end + props.bufferSize)
  }
})

// Get visible items - always include placeholders for items not yet loaded to prevent flicker
const visibleItems = computed(() => {
  const items = []
  for (let i = visibleRange.value.start; i < visibleRange.value.end; i++) {
    // Use itemGetter if provided (reads from source of truth), otherwise use internal cache
    const item = props.itemGetter ? props.itemGetter(i) : itemsCache.value.get(i)
    if (item) {
      items.push({
        ...item,
        _index: i,
        _position: i * (props.itemWidth + props.itemGap),
        _isPlaceholder: false
      })
    } else {
      // Show placeholder to prevent layout shift/flicker during loading
      items.push({
        id: `placeholder-${i}`,
        _index: i,
        _position: i * (props.itemWidth + props.itemGap),
        _isPlaceholder: true
      })
    }
  }
  return items
})

// Load chunks for visible range
async function loadVisibleChunks() {
  const { start, end } = visibleRange.value
  const startChunk = Math.floor(start / props.chunkSize)
  const endChunk = Math.floor(end / props.chunkSize)

  for (let chunkNum = startChunk; chunkNum <= endChunk; chunkNum++) {
    await loadChunk(chunkNum)
  }
}

// Load a specific chunk
async function loadChunk(chunkNum) {
  // Guard against invalid chunk numbers
  if (chunkNum < 0 || chunkNum * props.chunkSize >= props.totalCount) {
    return
  }

  const chunkKey = `chunk-${chunkNum}`

  // Don't reload if already loading
  if (loadingChunks.value.has(chunkKey)) {
    return
  }

  // When using itemGetter, we still call pageProvider to trigger loading in the source,
  // but we don't cache locally. Check if items are available via itemGetter.
  if (props.itemGetter) {
    const chunkStart = chunkNum * props.chunkSize
    const chunkEnd = Math.min(chunkStart + props.chunkSize, props.totalCount)
    let allLoaded = true
    for (let i = chunkStart; i < chunkEnd; i++) {
      if (!props.itemGetter(i)) {
        allLoaded = false
        break
      }
    }
    if (allLoaded) {
      return
    }

    loadingChunks.value.add(chunkKey)
    try {
      // Call pageProvider to trigger loading in the source - don't cache result
      await props.pageProvider(chunkNum, props.chunkSize)
    } catch (error) {
      console.error(`Failed to load chunk ${chunkNum}:`, error)
    } finally {
      loadingChunks.value.delete(chunkKey)
    }
    return
  }

  // Original behavior: check internal cache and store results
  const chunkStart = chunkNum * props.chunkSize
  const chunkEnd = Math.min(chunkStart + props.chunkSize, props.totalCount)
  let allLoaded = true
  for (let i = chunkStart; i < chunkEnd; i++) {
    if (!itemsCache.value.has(i)) {
      allLoaded = false
      break
    }
  }
  if (allLoaded) {
    return
  }

  loadingChunks.value.add(chunkKey)

  try {
    const items = await props.pageProvider(chunkNum, props.chunkSize)

    // Add items to cache
    items.forEach((item, idx) => {
      const globalIndex = chunkStart + idx
      itemsCache.value.set(globalIndex, item)
    })
  } catch (error) {
    console.error(`Failed to load chunk ${chunkNum}:`, error)
  } finally {
    loadingChunks.value.delete(chunkKey)
  }
}

// Handle scroll
function handleScroll(event) {
  scrollLeft.value = event.target.scrollLeft
  loadVisibleChunks()
  updateFirstVisibleItemId()
}

// Handle mousewheel for horizontal scrolling
function handleWheel(event) {
  // Prevent default vertical scroll
  event.preventDefault()

  // Use deltaY for vertical wheel movement to scroll horizontally
  // Also support deltaX for trackpads/horizontal scrolling
  const delta = event.deltaY !== 0 ? event.deltaY : event.deltaX

  scrollContainer.value.scrollLeft += delta
}

// Scroll to specific index
async function scrollToIndex(index, behavior = 'smooth') {
  const request = ++scrollRequest
  await nextTick()

  if (!scrollContainer.value || request !== scrollRequest) {
    return
  }

  // Loading must not delay the filmstrip's response to a swipe. Placeholders
  // preserve geometry while pages arrive, even across unloaded chunk boundaries.
  const chunkNum = Math.floor(index / props.chunkSize)
  void Promise.all([loadChunk(chunkNum), loadChunk(chunkNum - 1), loadChunk(chunkNum + 1)])
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) behavior = 'instant'
  const itemPosition = edgeGutter.value + index * (props.itemWidth + props.itemGap)

  if (props.autoCenter) {
    // Center the item
    const targetScroll = itemPosition - (containerWidth.value / 2) + (props.itemWidth / 2)
    scrollContainer.value.scrollTo({
      left: Math.max(0, targetScroll),
      behavior
    })
  } else {
    // Just ensure it's visible
    const currentScroll = scrollLeft.value
    const currentEnd = currentScroll + containerWidth.value

    if (itemPosition < currentScroll) {
      // Item is before visible area
      scrollContainer.value.scrollTo({
        left: itemPosition - props.itemGap,
        behavior
      })
    } else if (itemPosition + props.itemWidth > currentEnd) {
      // Item is after visible area
      scrollContainer.value.scrollTo({
        left: itemPosition + props.itemWidth - containerWidth.value + props.itemGap,
        behavior
      })
    }
  }
}

// Track first visible item ID to detect prepends
const firstVisibleItemId = ref(null)

// Update tracked first visible item ID
function updateFirstVisibleItemId() {
  if (!props.itemGetter || scrollLeft.value === 0) {
    firstVisibleItemId.value = null
    return
  }
  const firstVisibleIndex = Math.max(0, Math.floor((scrollLeft.value - edgeGutter.value) / (props.itemWidth + props.itemGap)))
  const item = props.itemGetter(firstVisibleIndex)
  firstVisibleItemId.value = item?.id || null
}

// Watch totalCount to detect prepends and adjust scroll position immediately
// Uses flush: 'sync' to run before Vue batches render updates
watch(() => props.totalCount, (newCount, oldCount) => {
  // Only act if items were added, we have itemGetter, and we're not at the start
  if (newCount > oldCount && scrollContainer.value && scrollLeft.value > 0 && props.itemGetter) {
    const addedCount = newCount - oldCount
    // Check if items were prepended by seeing if first visible item ID changed
    const firstVisibleIndex = Math.max(0, Math.floor((scrollLeft.value - edgeGutter.value) / (props.itemWidth + props.itemGap)))
    const currentFirstItem = props.itemGetter(firstVisibleIndex)

    // If the item at our scroll position has a different ID, items were prepended
    if (firstVisibleItemId.value && currentFirstItem && currentFirstItem.id !== firstVisibleItemId.value) {
      // Items were prepended - adjust scroll to keep same items in view
      const adjustment = addedCount * (props.itemWidth + props.itemGap)
      const newScrollLeft = scrollContainer.value.scrollLeft + adjustment
      // Cancel any in-progress smooth scroll by doing an instant scroll to the new position
      scrollContainer.value.scrollTo({ left: newScrollLeft, behavior: 'instant' })
      scrollLeft.value = newScrollLeft
      skipNextScroll.value = true
    }
  }
  // Update tracked ID after potential adjustment
  updateFirstVisibleItemId()
}, { flush: 'sync' })

// Watch currentIndex and scroll to it
watch(() => props.currentIndex, (newIndex) => {
  // Skip if we just did a prepend adjustment (scroll position already correct)
  if (skipNextScroll.value) {
    skipNextScroll.value = false
    return
  }
  scrollToIndex(newIndex)
})

// Initialize
onMounted(async () => {
  if (scrollContainer.value) {
    containerWidth.value = scrollContainer.value.clientWidth

    // Add resize observer
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const changed = containerWidth.value !== entry.contentRect.width
        containerWidth.value = entry.contentRect.width
        if (changed && props.centerEdges) void scrollToIndex(props.currentIndex, 'instant')
      }
    })
    resizeObserver.observe(scrollContainer.value)
  }

  // Load initial chunks around current index
  await scrollToIndex(props.currentIndex, 'auto')
  await loadVisibleChunks()
  updateFirstVisibleItemId()
})

onBeforeUnmount(() => { scrollRequest++; resizeObserver?.disconnect() })

// Clear cache and reload all visible data
async function refresh() {
  itemsCache.value.clear()
  loadingChunks.value.clear()
  await loadVisibleChunks()
  await scrollToIndex(props.currentIndex, 'auto')
}

// Expose methods
defineExpose({
  scrollToIndex,
  refresh
})
</script>

<style scoped>
.horizontal-virtual-scroller {
  width: 100%;
  position: relative;
}

.scroll-container {
  width: 100%;
  height: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  position: relative;
}

.scroll-content {
  position: relative;
}

.scroll-item {
  position: absolute;
  top: 0;
}

/* Allow text selection to be disabled but don't prevent image dragging */
.scroll-item :deep(img) {
  user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

/* Chunky Google Photos-style scrollbar */
.scroll-container::-webkit-scrollbar {
  -webkit-appearance: none;
  height: 16px;
}

.scroll-container::-webkit-scrollbar-track {
  background: transparent;
  border-radius: 8px;
}

.scroll-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.3);
  border-radius: 8px;
  border: 2px solid rgba(20, 20, 20, 0.95);
  min-width: 100px;
}

.scroll-container::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.5);
}

/* Standard scrollbar - works in Safari 16.4+, Firefox */
.scroll-container {
  scrollbar-width: thick;
  scrollbar-color: rgba(255, 255, 255, 0.3) transparent;
  color-scheme: dark;
}
</style>
