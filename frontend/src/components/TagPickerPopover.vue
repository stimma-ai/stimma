<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuRef"
      data-tag-picker
      class="fixed w-[280px] bg-surface border border-edge-subtle rounded-lg shadow-lg overflow-hidden flex flex-col"
      :class="isSubmenu ? 'z-submenu' : 'z-menu'"
      :style="menuStyle"
      @mousedown.stop
    >
      <!-- Filter / create field -->
      <div class="flex items-center gap-2 mx-2.5 mt-2.5 mb-1 px-2.5 py-1.5 bg-overlay-subtle rounded-md border border-transparent focus-within:border-accent transition-colors">
        <svg class="w-3.5 h-3.5 text-content-tertiary flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round">
          <circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5" />
        </svg>
        <input
          v-no-autocorrect
          ref="inputRef"
          v-model="filterText"
          type="text"
          class="flex-1 min-w-0 bg-transparent border-none outline-none text-content text-sm placeholder:text-content-muted"
          placeholder="Tag…"
          @keydown="onInputKeydown"
        />
      </div>

      <!-- Fixed-height list: filtering and the create row never resize the popover -->
      <div ref="listRef" class="overflow-y-auto custom-scrollbar" :style="{ height: listHeight + 'px' }">
        <div
          v-if="createVisible"
          class="flex items-center gap-2.5 px-3 h-8 cursor-pointer text-accent-hi text-sm"
          :class="{ 'bg-overlay-subtle': highlightIndex === 0 }"
          @mouseenter="highlightIndex = 0"
          @click="createAndApply"
        >
          <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span class="flex-1 truncate">Create “{{ filterText.trim() }}”</span>
          <span class="text-[10px] font-mono text-content-muted border border-edge-subtle rounded px-1">↩</span>
        </div>

        <div
          v-for="(tag, i) in filteredTags"
          :key="tag.id"
          class="flex items-center gap-2.5 px-3 h-8 cursor-pointer select-none"
          :class="{ 'bg-overlay-subtle': highlightIndex === i + createOffset }"
          @mouseenter="highlightIndex = i + createOffset"
          @click="toggleTag(tag)"
        >
          <span
            class="w-4 h-4 rounded flex-shrink-0 border-[1.5px] flex items-center justify-center text-white"
            :class="stateOf(tag.id) === 'all' ? 'bg-accent border-accent'
              : stateOf(tag.id) === 'some' ? 'border-accent text-accent-hi'
              : 'border-content-tertiary'"
          >
            <svg v-if="stateOf(tag.id) === 'all'" class="w-2.5 h-2.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 10.5l3.5 3.5 7.5-8" /></svg>
            <svg v-else-if="stateOf(tag.id) === 'some'" class="w-2.5 h-2.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 10h10" /></svg>
          </span>
          <span class="flex-1 text-sm text-content truncate">{{ tag.tag }}</span>
          <span v-if="stateOf(tag.id) === 'some'" class="text-[10px] font-mono tabular-nums text-content-tertiary">{{ someCounts[tag.id] }}/{{ targetIds.length }}</span>
          <span v-else-if="tag.usage_count" class="text-xs font-mono tabular-nums text-content-muted">{{ tag.usage_count }}</span>
        </div>

        <div v-if="!createVisible && filteredTags.length === 0" class="px-3 py-4 text-center text-xs text-content-muted">
          {{ loading ? 'Loading…' : 'No matching tags' }}
        </div>
      </div>

      <div v-if="error" class="px-3 py-1.5 text-xs text-red-400 border-t border-edge-subtle">{{ error }}</div>

      <!-- Key hints -->
      <div class="flex items-center gap-3 px-3 py-1.5 border-t border-edge-subtle text-[10.5px] text-content-muted">
        <span><span class="font-mono">↑↓</span> navigate</span>
        <span><span class="font-mono">↩</span> toggle</span>
        <span><span class="font-mono">esc</span> done</span>
        <span class="ml-auto font-mono tabular-nums">{{ targetIds.length }} item{{ targetIds.length !== 1 ? 's' : '' }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useAnchoredMenuPosition, useSubmenuPosition } from '../composables/useContextMenuPosition'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { shouldShowTagInPicker } from '../utils/tagPickerOptions'

const props = defineProps({
  visible: { type: Boolean, default: false },
  /** HTMLElement to anchor to, or a {x, y} point. Null centers. */
  anchor: { type: [Object, HTMLElement], default: null },
  /**
   * Parent context-menu element. When set, the picker places itself like a
   * submenu of that menu (anchor = the trigger row) and the parent stays open.
   */
  submenuOf: { type: [Object, HTMLElement], default: null },
  mediaIds: { type: Array, default: () => [] },
  assetIds: { type: Array, default: () => [] },
  // Map of tag_id -> count of how many selected items have it
  currentTagCounts: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'changed'])

const { getTags, createTag, bulkTagOperation } = useMediaApi()
const { bulkTags: bulkAssetTags, getTags: getAssetTags } = useAssetApi()
const isAssetMode = computed(() => props.assetIds.length > 0)
const targetIds = computed(() => isAssetMode.value ? props.assetIds : props.mediaIds)

const menuRef = ref(null)
const inputRef = ref(null)
const listRef = ref(null)

const availableTags = ref([])
const tagStates = ref({})      // tag_id -> 'all' | 'some' | 'none'
const someCounts = ref({})     // tag_id -> count when state is 'some' (frozen at open)
const touched = ref(new Set()) // tags toggled this session stay visible regardless of usage
const filterText = ref('')
const highlightIndex = ref(0)
const listHeight = ref(160)
const loading = ref(false)
const busy = ref(false)
const error = ref(null)

const ROW_H = 32

// Anchor rect resolved once per open (element, point, or viewport center)
const anchorRect = ref(null)
function resolveAnchorRect() {
  const a = props.anchor
  if (a instanceof HTMLElement) {
    anchorRect.value = a.getBoundingClientRect()
  } else if (a && typeof a.x === 'number' && typeof a.y === 'number') {
    anchorRect.value = { left: a.x, right: a.x, top: a.y, bottom: a.y, width: 0, height: 0 }
  } else {
    const cx = window.innerWidth / 2 - 140
    const cy = window.innerHeight / 2 - 160
    anchorRect.value = { left: cx, right: cx, top: cy, bottom: cy, width: 0, height: 0 }
  }
}

const isSubmenu = computed(() => !!props.submenuOf)
const parentMenuRef = computed(() => props.submenuOf || null)
const anchoredActive = computed(() => props.visible && !isSubmenu.value)
const submenuActive = computed(() => props.visible && isSubmenu.value)
const { menuStyle: anchoredStyle } = useAnchoredMenuPosition(menuRef, anchorRect, anchoredActive, { gap: 6 })
const { submenuStyle } = useSubmenuPosition(parentMenuRef, anchorRect, menuRef, submenuActive)
const menuStyle = computed(() => isSubmenu.value ? submenuStyle.value : anchoredStyle.value)

const filteredTags = computed(() => {
  let tags = availableTags.value.filter(tag => (
    shouldShowTagInPicker(tag, touched.value.has(tag.id) ? 'add' : null)
  ))
  const q = filterText.value.trim().toLowerCase()
  if (q) tags = tags.filter(tag => tag.tag.toLowerCase().includes(q))
  return [...tags].sort((a, b) => {
    const ac = a.usage_count || 0
    const bc = b.usage_count || 0
    if (ac > 0 && bc > 0 && ac !== bc) return bc - ac
    if (ac > 0 && bc === 0) return -1
    if (ac === 0 && bc > 0) return 1
    return a.tag.localeCompare(b.tag)
  })
})

const createVisible = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return false
  return !availableTags.value.some(t => t.tag.toLowerCase() === q)
})
const createOffset = computed(() => createVisible.value ? 1 : 0)
const navCount = computed(() => filteredTags.value.length + createOffset.value)

watch([filteredTags, createVisible], () => {
  if (highlightIndex.value >= navCount.value) highlightIndex.value = Math.max(0, navCount.value - 1)
})
watch(filterText, () => { highlightIndex.value = 0 })

function stateOf(tagId) {
  return tagStates.value[tagId] || 'none'
}

async function open() {
  resolveAnchorRect()
  filterText.value = ''
  highlightIndex.value = 0
  error.value = null
  touched.value = new Set()
  loading.value = true
  try {
    availableTags.value = isAssetMode.value ? await getAssetTags(true) : await getTags(true)
  } catch (err) {
    console.error('Failed to load tags:', err)
    error.value = 'Failed to load tags'
    availableTags.value = []
  } finally {
    loading.value = false
  }

  const states = {}
  const counts = {}
  const total = targetIds.value.length
  for (const tag of availableTags.value) {
    const n = props.currentTagCounts[tag.id] || 0
    states[tag.id] = n === 0 ? 'none' : n === total ? 'all' : 'some'
    if (states[tag.id] === 'some') counts[tag.id] = n
  }
  tagStates.value = states
  someCounts.value = counts

  // Lock the list height for this open: filtering never resizes the popover
  const pickable = availableTags.value.filter(t => shouldShowTagInPicker(t)).length
  listHeight.value = Math.min(Math.max(pickable + 1, 4), 9) * ROW_H

  await nextTick()
  inputRef.value?.focus()
}

async function toggleTag(tag) {
  if (busy.value) return
  const prev = stateOf(tag.id)
  const next = prev === 'all' ? 'none' : 'all'
  const ids = [...targetIds.value]

  // Optimistic flip; usage_count tracks the delta so sorting/visibility follow
  const prevUsage = tag.usage_count || 0
  const affected = prev === 'all' ? ids.length
    : prev === 'some' ? ids.length - (someCounts.value[tag.id] || 0)
    : ids.length
  tagStates.value[tag.id] = next
  tag.usage_count = Math.max(0, prevUsage + (next === 'all' ? affected : -ids.length))
  touched.value.add(tag.id)
  error.value = null
  busy.value = true

  try {
    if (next === 'all') {
      if (isAssetMode.value) await bulkAssetTags(ids, [tag.tag], [])
      else await bulkTagOperation(ids, [tag.tag], [])
    } else {
      if (isAssetMode.value) await bulkAssetTags(ids, [], [tag.id])
      else await bulkTagOperation(ids, [], [tag.id])
    }
    emit('changed')
  } catch (err) {
    console.error('Failed to update tag:', err)
    tagStates.value[tag.id] = prev
    tag.usage_count = prevUsage
    error.value = err.response?.data?.detail || 'Failed to update tags'
  } finally {
    busy.value = false
  }
}

async function createAndApply() {
  const text = filterText.value.trim()
  if (!text || busy.value) return
  busy.value = true
  error.value = null
  try {
    const newTag = await createTag(text)
    newTag.usage_count = 0
    availableTags.value.push(newTag)
    tagStates.value[newTag.id] = 'none'
    busy.value = false
    filterText.value = ''
    await toggleTag(availableTags.value[availableTags.value.length - 1])
  } catch (err) {
    console.error('Failed to create tag:', err)
    error.value = err.response?.data?.detail || 'Failed to create tag'
    busy.value = false
  }
}

function onInputKeydown(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (navCount.value) highlightIndex.value = (highlightIndex.value + 1) % navCount.value
    scrollHighlightIntoView()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (navCount.value) highlightIndex.value = (highlightIndex.value - 1 + navCount.value) % navCount.value
    scrollHighlightIntoView()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const idx = highlightIndex.value
    if (createVisible.value && idx === 0) createAndApply()
    else {
      const tag = filteredTags.value[idx - createOffset.value]
      if (tag) toggleTag(tag)
    }
  } else if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    emit('close')
  }
}

function scrollHighlightIntoView() {
  nextTick(() => {
    const rows = listRef.value?.children
    const el = rows?.[highlightIndex.value]
    el?.scrollIntoView?.({ block: 'nearest' })
  })
}

function onDocMousedown(e) {
  if (menuRef.value && !menuRef.value.contains(e.target)) emit('close')
}
function onDocKeydown(e) {
  // Escape when focus has strayed from the input
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}

watch(() => props.visible, (v) => {
  if (v) {
    open()
    nextTick(() => {
      document.addEventListener('mousedown', onDocMousedown)
      document.addEventListener('keydown', onDocKeydown)
    })
  } else {
    document.removeEventListener('mousedown', onDocMousedown)
    document.removeEventListener('keydown', onDocKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMousedown)
  document.removeEventListener('keydown', onDocKeydown)
})
</script>
