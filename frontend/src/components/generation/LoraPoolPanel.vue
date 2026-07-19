<template>
  <div class="my-6">
    <!-- Header: label + count + compact icon strip (＋ · ⌕ · disable-all · RAW · ⋯) -->
    <div class="flex items-center gap-2 pb-1 mb-1.5">
      <span class="text-xs font-semibold text-content-secondary">LoRAs</span>
      <div class="ml-auto flex items-center gap-0.5">
        <button
          v-if="availableLoras.length > 0 || uploadConfig"
          @click="showModal = true"
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle transition-colors"
          title="Add LoRA"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
          </svg>
        </button>
        <button
          v-if="hasAnyItems"
          @click="toggleFilter"
          type="button"
          :class="['w-6 h-6 flex items-center justify-center rounded-md transition-colors', filterOpen ? 'bg-accent/12 text-accent-hi' : 'text-content-tertiary hover:text-content hover:bg-overlay-subtle']"
          title="Filter pool"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
          </svg>
        </button>
        <button
          v-if="hasAnyItems && enabledCount > 0"
          @click="disableAll"
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle transition-colors"
          title="Disable all — empty the palette (keeps the list)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3.5 h-3.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.636 5.636a9 9 0 1 0 12.728 0M12 3v9" />
          </svg>
        </button>
        <button
          v-if="hasAnyItems"
          @click="showRaw = !showRaw"
          type="button"
          :class="['h-6 px-1.5 flex items-center justify-center rounded-md font-mono text-[9px] tracking-wide transition-colors', showRaw ? 'bg-accent/12 text-accent-hi' : 'text-content-tertiary hover:text-content hover:bg-overlay-subtle']"
          title="Show raw file names"
        >RAW</button>
        <div v-if="hasAnyItems" class="relative">
          <button
            @click.stop="onHeaderMenuClick"
            type="button"
            class="w-6 h-6 flex items-center justify-center rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle transition-colors"
            title="More options"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M10 3a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM10 8.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM11.5 15.5a1.5 1.5 0 10-3 0 1.5 1.5 0 003 0z" />
            </svg>
          </button>
          <ActionMenu
            v-if="headerMenu.visible"
            :x="headerMenu.x"
            :y="headerMenu.y"
            :actions="headerMenuActions"
            @close="headerMenu.visible = false"
          />
        </div>
      </div>
    </div>

    <!-- Filter row (full width, only when open) -->
    <div v-if="filterOpen" class="flex items-center gap-2 mb-1.5 px-2 py-1 bg-overlay-subtle rounded-md">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted flex-shrink-0">
        <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
      </svg>
      <input v-no-autocorrect
        ref="filterInputRef"
        v-model="filterQuery"
        type="text"
        placeholder="Filter pool…"
        class="flex-1 min-w-0 bg-transparent border-0 outline-none text-xs text-content placeholder:text-content-muted select-text"
        @keydown.escape="toggleFilter"
      />
      <button @click="toggleFilter" type="button" class="text-content-muted hover:text-content-secondary">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
    </div>

    <!-- Main container -->
    <div class="relative transition-colors select-none">
      <div ref="outerContainerRef" class="flex flex-col gap-2">
        <!-- Groups -->
        <LoraGroupBox :chip-min-width="showRaw ? 400 : 300"
          v-for="(group, groupIndex) in displayGroups"
          :key="group.id"
          :group="group"
          :group-index="groupIndex"
          :data-group-id="group.id"
          :class="{ 'opacity-30': drag.type === 'group' && drag.groupId === group.id && drag.active }"
          @rename="onRenameGroup(group.id, $event)"
          @remove="onRemoveGroup(group.id)"
          @group-drag-intent="onGroupDragIntent"
        >
          <LoraChip
            v-for="item in filterItems(getPreviewItems(group.id, group.items))"
            :key="item.lora"
            :item="item"
            :display-name="getChipDisplayName(item.lora)"
            :show-raw="showRaw"
            :unavailable="isUnavailable(item.lora)"
            :group-id="group.id"
            :style="drag.type === 'chip' && drag.loraPath === item.lora && drag.active ? 'opacity: 0.3' : ''"
            @toggle="onToggle(item.lora, $event)"
            @update-weight="onUpdateWeight(item.lora, $event)"
            @remove="onRemove(item.lora)"
            @contextmenu="onChipContextMenu($event, item.lora)"
            @drag-intent="onChipDragIntent"
          />
        </LoraGroupBox>

        <!-- "Other" group (ungrouped items) — visible when has items, or as drop target during chip drag -->
        <LoraGroupBox :chip-min-width="showRaw ? 400 : 300"
          v-if="ungroupedPreview.length > 0 || (drag.type === 'chip' && drag.active && pool.groups.length > 0)"
          :group="otherGroup"
          :group-index="displayGroups.length"
          :hide-header="pool.groups.length === 0 && !(drag.type === 'chip' && drag.active)"
          :fixed-label="true"
          data-group-id=""
          @remove="() => {}"
          @group-drag-intent="() => {}"
        >
          <LoraChip
            v-for="item in ungroupedPreview"
            :key="item.lora"
            :item="item"
            :display-name="getChipDisplayName(item.lora)"
            :show-raw="showRaw"
            :unavailable="isUnavailable(item.lora)"
            :group-id="null"
            :style="drag.type === 'chip' && drag.loraPath === item.lora && drag.active ? 'opacity: 0.3' : ''"
            @toggle="onToggle(item.lora, $event)"
            @update-weight="onUpdateWeight(item.lora, $event)"
            @remove="onRemove(item.lora)"
            @contextmenu="onChipContextMenu($event, item.lora)"
            @drag-intent="onChipDragIntent"
          />
        </LoraGroupBox>

        <!-- Drop zone: "new group" target visible during chip drag -->
        <div
          v-if="drag.type === 'chip' && drag.active"
          data-new-group-zone
          :class="[
            'rounded-md border-2 border-dashed px-3 py-3 text-center text-xs transition-colors',
            drag.newGroupHover
              ? 'border-accent bg-accent/10 text-accent-hi'
              : 'border-edge-subtle text-content-muted/50'
          ]"
        >
          Drop to create new group
        </div>

        <!-- Empty state -->
        <div
          v-if="!hasAnyItems"
          class="py-2 text-sm text-content-muted"
        >
          {{ availableLoras.length === 0 ? 'No LoRAs available' : 'No LoRAs selected' }}
        </div>
      </div>
    </div>

    <!-- Drag ghost (teleported to body) -->
    <Teleport to="body">
      <div
        v-if="drag.active && drag.ghostHtml"
        ref="ghostRef"
        class="fixed z-top pointer-events-none opacity-80 rotate-1"
        :style="{ left: drag.ghostX + 'px', top: drag.ghostY + 'px', width: drag.ghostWidth + 'px' }"
        v-html="drag.ghostHtml"
      />
    </Teleport>

    <!-- LoRA Context Menu -->
    <ActionMenu
      v-if="contextMenu.visible"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :actions="contextMenuActions"
      @close="contextMenu.visible = false"
    />

    <!-- Picker Modal -->
    <LoraPickerModal
      v-if="showModal"
      :available-loras="availableLoras"
      :pool-loras="allItems"
      :is-refreshing="isRefreshing"
      :show-raw="showRaw"
      :model-name="modelName"
      :is-uploading="isUploading"
      :upload-progress="uploadProgress"
      :upload-file-name="uploadFileName"
      :upload-config="uploadConfig"
      @add="onAddLora"
      @remove="onRemoveLora"
      @close="showModal = false"
      @refresh-loras="$emit('refresh-loras')"
      @toggle-raw="showRaw = !showRaw"
      @upload="$emit('upload', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onUnmounted, nextTick } from 'vue'
import LoraChip from './LoraChip.vue'
import LoraGroupBox from './LoraGroupBox.vue'
import LoraPickerModal from './LoraPickerModal.vue'
import ActionMenu from '../ActionMenu.vue'
import { useLoraPool } from '../../composables/useLoraPool'
import type { LoraOption, LoraPoolItem } from '../../composables/useLoraPool'
import { computeDisplayNames, getRawDisplayName, getRawFileName } from '../../composables/useLoraDisplayNames'
import type { LoraDisplayName } from '../../composables/useLoraDisplayNames'
import { makeProfileKey } from '../../utils/storageKeys'

interface UploadConfig {
  extensions: string[]
  max_size: number
}

interface Props {
  toolId: string | null
  modelName: string | null
  availableLoras: LoraOption[]
  isRefreshing?: boolean
  isUploading?: boolean
  uploadProgress?: number | null
  uploadFileName?: string | null
  uploadConfig?: UploadConfig | null
}

const props = withDefaults(defineProps<Props>(), {
  isRefreshing: false,
  isUploading: false,
  uploadProgress: null,
  uploadFileName: null,
  uploadConfig: null,
  modelName: null,
})

const emit = defineEmits<{
  (e: 'refresh-loras'): void
  (e: 'upload', files: File[]): void
}>()

const {
  getPool, getAllItems, addToPool, removeFromPool, toggleEnabled, updateWeight,
  moveToContainer, reorderInContainer,
  createGroup, renameGroup, explodeGroup, removeGroup, reorderGroups,
  soloEnable, clearPool, removeDisabled,
} = useLoraPool()

const showModal = ref(false)
const showRaw = ref(localStorage.getItem(makeProfileKey('lora', 'show_raw')) === 'true')

// Header strip state/actions (option D)
const filterOpen = ref(false)
const filterInputRef = ref<HTMLInputElement | null>(null)
const enabledCount = computed(() => allItems.value.filter(i => i.enabled).length)
function toggleFilter() {
  filterOpen.value = !filterOpen.value
  if (filterOpen.value) nextTick(() => filterInputRef.value?.focus())
  else filterQuery.value = ''
}
function disableAll() {
  if (!props.toolId) return
  for (const item of allItems.value) {
    if (item.enabled) toggleEnabled(props.toolId, item.lora)
  }
}
const filterQuery = ref('')

watch(showRaw, (v) => {
  localStorage.setItem(makeProfileKey('lora', 'show_raw'), String(v))
})

// Pool data
const pool = computed(() => getPool(props.toolId))
const allItems = computed(() => getAllItems(props.toolId))
const hasAnyItems = computed(() => allItems.value.length > 0)

// Availability: a pinned pool item is "unavailable" when its path is no longer in
// the tool's supported LoRA list (e.g. after restoring an old image whose LoRAs the
// current tool/model doesn't offer). Only evaluate once the available list is
// actually loaded — an empty list usually means the schema is still loading or
// refreshing, and we don't want to flash every chip as gone in that window.
const availablePathSet = computed(() => new Set(props.availableLoras.map(l => l.path)))
const availabilityKnown = computed(() => !props.isRefreshing && props.availableLoras.length > 0)

function isUnavailable(loraPath: string): boolean {
  if (!availabilityKnown.value) return false
  return !availablePathSet.value.has(loraPath)
}

const unavailableCount = computed(() =>
  availabilityKnown.value ? allItems.value.filter(i => !availablePathSet.value.has(i.lora)).length : 0
)

// Filter
function matchesFilter(loraPath: string): boolean {
  if (!filterQuery.value) return true
  const q = filterQuery.value.toLowerCase()
  const displayName = getChipDisplayName(loraPath)
  return displayName.primary.toLowerCase().includes(q) ||
    (displayName.secondary && displayName.secondary.toLowerCase().includes(q)) ||
    loraPath.toLowerCase().includes(q)
}

function filterItems(items: LoraPoolItem[]): LoraPoolItem[] {
  if (!filterQuery.value) return items
  return items.filter(i => matchesFilter(i.lora))
}

// Smart display names
const smartNames = computed(() => {
  return computeDisplayNames(allItems.value.map(item => item.lora), props.modelName || undefined)
})

function getChipDisplayName(path: string): LoraDisplayName {
  // If the pool item carries an explicit name (cloud LoRAs do — `lora` is an
  // opaque UUID and `name` holds the human filename), prefer it over the
  // path-derived heuristic which would otherwise show UUID chunks.
  //
  // A genuine display name never contains a path separator. Some providers
  // (e.g. ComfyUI for LoRAs nested in subdirectories) leak the full relative
  // path into `name`; treat those as absent and fall back to the smart
  // path-derived name so they get the same brief treatment as the picker.
  const item = allItems.value.find(i => i.lora === path)
  if (item?.name && !item.name.includes('/')) {
    const stripped = item.name.replace(/\.[^.]+$/i, '')
    return { primary: stripped, secondary: '' }
  }
  return smartNames.value[path] || { primary: getRawDisplayName(path), secondary: '' }
}

// ── LoRA actions ────────────────────────────────────────────

function onToggle(loraPath: string, event?: MouseEvent) {
  if (!props.toolId) return
  const item = allItems.value.find(i => i.lora === loraPath)
  if (!item) return
  if (event?.shiftKey && !item.enabled) {
    soloEnable(props.toolId, loraPath)
  } else {
    toggleEnabled(props.toolId, loraPath)
  }
}

function onUpdateWeight(loraPath: string, weight: number) {
  if (!props.toolId) return
  updateWeight(props.toolId, loraPath, weight)
}

function onRemove(loraPath: string) {
  if (!props.toolId) return
  removeFromPool(props.toolId, loraPath)
}

// ── Group actions ───────────────────────────────────────────

function onRenameGroup(groupId: string, label: string) {
  if (!props.toolId) return
  renameGroup(props.toolId, groupId, label)
}

function onRemoveGroup(groupId: string) {
  if (!props.toolId) return
  removeGroup(props.toolId, groupId)
}

// ══════════════════════════════════════════════════════════════
// POINTER-BASED DRAG SYSTEM
// ══════════════════════════════════════════════════════════════

const DRAG_THRESHOLD = 4
const outerContainerRef = ref<HTMLElement | null>(null)
const ghostRef = ref<HTMLElement | null>(null)

const drag = reactive({
  // Common
  type: null as 'chip' | 'group' | null,
  active: false,      // true once threshold exceeded
  startX: 0,
  startY: 0,
  ghostHtml: '',
  ghostX: 0,
  ghostY: 0,
  ghostWidth: 0,
  ghostOffsetX: 0,
  ghostOffsetY: 0,
  sourceEl: null as HTMLElement | null,

  // Chip drag
  loraPath: null as string | null,
  sourceGroupId: null as string | null,
  targetGroupId: undefined as string | null | undefined, // undefined = no target
  targetIndex: -1,
  newGroupHover: false,

  // Group drag
  groupId: null as string | null,
  groupOverId: null as string | null,
})

function resetDrag() {
  document.body.style.userSelect = ''
  drag.type = null
  drag.active = false
  drag.loraPath = null
  drag.sourceGroupId = null
  drag.targetGroupId = undefined
  drag.targetIndex = -1
  drag.newGroupHover = false
  drag.groupId = null
  drag.groupOverId = null
  drag.ghostHtml = ''
  drag.sourceEl = null
}

// ── Chip drag ───────────────────────────────────────────────

function onChipDragIntent(event: PointerEvent, loraPath: string, groupId: string | null) {
  drag.type = 'chip'
  drag.loraPath = loraPath
  drag.sourceGroupId = groupId
  drag.startX = event.clientX
  drag.startY = event.clientY
  drag.sourceEl = (event.currentTarget as HTMLElement)

  document.addEventListener('pointermove', onPointerMove)
  document.addEventListener('pointerup', onPointerUp)
}

// ── Group drag ──────────────────────────────────────────────

function onGroupDragIntent(event: PointerEvent, groupId: string) {
  drag.type = 'group'
  drag.groupId = groupId
  drag.groupOverId = groupId
  drag.startX = event.clientX
  drag.startY = event.clientY
  drag.sourceEl = (event.currentTarget as HTMLElement).closest('[data-group-id]') as HTMLElement

  document.addEventListener('pointermove', onPointerMove)
  document.addEventListener('pointerup', onPointerUp)
}

// ── Shared pointer handlers ─────────────────────────────────

function onPointerMove(event: PointerEvent) {
  const dx = event.clientX - drag.startX
  const dy = event.clientY - drag.startY

  if (!drag.active) {
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return

    // Start drag
    drag.active = true
    document.body.style.userSelect = 'none'
    window.getSelection()?.removeAllRanges()

    // Create ghost from source element
    if (drag.sourceEl) {
      const rect = drag.sourceEl.getBoundingClientRect()
      drag.ghostWidth = rect.width
      drag.ghostOffsetX = event.clientX - rect.left
      drag.ghostOffsetY = event.clientY - rect.top
      drag.ghostHtml = drag.sourceEl.outerHTML
    }
  }

  // Move ghost
  drag.ghostX = event.clientX - drag.ghostOffsetX
  drag.ghostY = event.clientY - drag.ghostOffsetY

  // Calculate drop position
  if (drag.type === 'chip') {
    calcChipDropPosition(event.clientX, event.clientY)
  } else if (drag.type === 'group') {
    calcGroupDropPosition(event.clientY)
  }
}

function onPointerUp(_event: PointerEvent) {
  document.removeEventListener('pointermove', onPointerMove)
  document.removeEventListener('pointerup', onPointerUp)

  if (drag.active) {
    if (drag.type === 'chip') {
      commitChipDrag()
    } else if (drag.type === 'group') {
      commitGroupDrag()
    }
  }

  resetDrag()
}

// ── Chip drop position calculation ──────────────────────────

function calcChipDropPosition(mouseX: number, mouseY: number) {
  const container = outerContainerRef.value
  if (!container || !drag.loraPath) return

  // Check "new group" drop zone
  const newGroupZone = container.querySelector('[data-new-group-zone]')
  if (newGroupZone) {
    const rect = newGroupZone.getBoundingClientRect()
    drag.newGroupHover = mouseY >= rect.top && mouseY <= rect.bottom && mouseX >= rect.left && mouseX <= rect.right
    if (drag.newGroupHover) {
      drag.targetGroupId = undefined
      drag.targetIndex = -1
      return
    }
  }

  // Check all group boxes (including "Other" which has data-group-id="")
  const groupEls = container.querySelectorAll<HTMLElement>(':scope > [data-group-id]')
  for (const groupEl of groupEls) {
    const rawGid = groupEl.dataset.groupId ?? ''
    const gid: string | null = rawGid || null // Empty string = ungrouped (Other)
    const rect = groupEl.getBoundingClientRect()
    if (mouseY < rect.top || mouseY > rect.bottom) continue

    const gridEl = groupEl.querySelector('[data-lora-rows]')
    if (!gridEl) continue

    const slot = findVisualSlot(gridEl, mouseX, mouseY)
    const originalItems = gid === null
      ? pool.value.ungrouped
      : pool.value.groups.find(g => g.id === gid)?.items || []
    const idx = mapSlotToOriginalIndex(slot, gid, originalItems)

    drag.targetGroupId = gid
    drag.targetIndex = idx
    return
  }
}

/**
 * Find which visual slot (0..N) the mouse is at within a grid container.
 * Returns the index of the child element the cursor is over.
 * If cursor is between/past elements, returns the nearest slot.
 */
function findVisualSlot(gridEl: Element, mouseX: number, mouseY: number): number {
  const children = Array.from(gridEl.children) as HTMLElement[]
  if (children.length === 0) return 0

  // Find the element the cursor is directly over
  for (let i = 0; i < children.length; i++) {
    const rect = children[i].getBoundingClientRect()
    if (mouseX >= rect.left && mouseX <= rect.right && mouseY >= rect.top && mouseY <= rect.bottom) {
      return i
    }
  }

  // Not directly over any element — find nearest by distance to center
  let bestIdx = 0
  let bestDist = Infinity
  for (let i = 0; i < children.length; i++) {
    const rect = children[i].getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const dist = Math.hypot(mouseX - cx, mouseY - cy)
    if (dist < bestDist) {
      bestDist = dist
      bestIdx = i
    }
  }
  return bestIdx
}

/**
 * Map a visual slot index (in the preview array) back to an index in the original pool array.
 * The preview may have the dragged item removed from source and inserted at target.
 */
function mapSlotToOriginalIndex(visualSlot: number, groupId: string | null, originalItems: LoraPoolItem[]): number {
  const previewItems = getPreviewItems(groupId, originalItems)

  if (visualSlot >= previewItems.length) {
    return originalItems.length
  }

  const loraAtSlot = previewItems[visualSlot]
  if (!loraAtSlot) return originalItems.length

  // If the slot points at the dragged item itself, the current position is fine
  if (loraAtSlot.lora === drag.loraPath) {
    // Return current target to avoid state change
    if (drag.targetGroupId === groupId) return drag.targetIndex
    return originalItems.length
  }

  const origIdx = originalItems.findIndex(item => item.lora === loraAtSlot.lora)
  return origIdx >= 0 ? origIdx : originalItems.length
}

function commitChipDrag() {
  if (!props.toolId || !drag.loraPath) return

  // "New group" drop
  if (drag.newGroupHover) {
    const newGroupId = createGroup(props.toolId)
    if (newGroupId) {
      moveToContainer(props.toolId, drag.loraPath, newGroupId)
    }
    return
  }

  if (drag.targetGroupId === undefined || drag.targetIndex < 0) return

  if (drag.sourceGroupId === drag.targetGroupId) {
    // Reorder within same container
    const items = drag.targetGroupId === null
      ? pool.value.ungrouped
      : pool.value.groups.find(g => g.id === drag.targetGroupId)?.items
    if (items) {
      const fromIndex = items.findIndex(i => i.lora === drag.loraPath)
      if (fromIndex !== -1 && fromIndex !== drag.targetIndex) {
        reorderInContainer(props.toolId, drag.targetGroupId, fromIndex, drag.targetIndex)
      }
    }
  } else {
    moveToContainer(props.toolId, drag.loraPath, drag.targetGroupId, drag.targetIndex)
  }
}

// ── Preview computeds ───────────────────────────────────────

function getPreviewItems(containerGroupId: string | null, items: LoraPoolItem[]): LoraPoolItem[] {
  if (drag.type !== 'chip' || !drag.active || !drag.loraPath || drag.targetGroupId === undefined) {
    return items
  }

  const sourceGid = drag.sourceGroupId
  const targetGid = drag.targetGroupId
  const dragPath = drag.loraPath
  const targetIdx = drag.targetIndex

  const sourceItems = sourceGid === null ? pool.value.ungrouped
    : pool.value.groups.find(g => g.id === sourceGid)?.items || []
  const draggedItem = sourceItems.find(i => i.lora === dragPath)
  if (!draggedItem) return items

  if (containerGroupId === sourceGid && containerGroupId === targetGid) {
    const result = items.filter(i => i.lora !== dragPath)
    result.splice(Math.min(targetIdx, result.length), 0, draggedItem)
    return result
  } else if (containerGroupId === sourceGid) {
    return items.filter(i => i.lora !== dragPath)
  } else if (containerGroupId === targetGid) {
    const result = [...items]
    result.splice(Math.min(targetIdx, result.length), 0, draggedItem)
    return result
  }
  return items
}

const ungroupedPreview = computed(() => filterItems(getPreviewItems(null, pool.value.ungrouped)))

// Synthetic group object for the "Other" (ungrouped) section
const otherGroup = computed(() => ({
  id: '__other__',
  label: 'Other',
  items: pool.value.ungrouped,
}))

// ── Group drop position calculation ─────────────────────────

function calcGroupDropPosition(mouseY: number) {
  const container = outerContainerRef.value
  if (!container || !drag.groupId) return

  const groupEls = container.querySelectorAll<HTMLElement>(':scope > [data-group-id]')
  for (const el of groupEls) {
    const gid = el.dataset.groupId!
    if (!gid) continue // Skip "Other" group (not reorderable)
    if (gid === drag.groupId) continue // Skip the dragged group
    const rect = el.getBoundingClientRect()
    const centerY = rect.top + rect.height / 2
    if (mouseY < centerY) {
      // Mouse is above center → swap to this position
      if (gid !== drag.groupOverId) {
        drag.groupOverId = gid
      }
      return
    }
  }

  // Past all groups → move to end. Use the last non-dragged group as target.
  const groups = pool.value.groups
  for (let i = groups.length - 1; i >= 0; i--) {
    if (groups[i].id !== drag.groupId) {
      if (groups[i].id !== drag.groupOverId) {
        drag.groupOverId = groups[i].id
      }
      return
    }
  }
}

function commitGroupDrag() {
  if (!props.toolId || !drag.groupId || !drag.groupOverId || drag.groupId === drag.groupOverId) return

  const fromIndex = pool.value.groups.findIndex(g => g.id === drag.groupId)
  const toIndex = pool.value.groups.findIndex(g => g.id === drag.groupOverId)
  if (fromIndex !== -1 && toIndex !== -1) {
    reorderGroups(props.toolId, fromIndex, toIndex)
  }
}

const displayGroups = computed(() => {
  const groups = pool.value.groups
  if (drag.type !== 'group' || !drag.active || !drag.groupId || !drag.groupOverId) return groups
  const fromIndex = groups.findIndex(g => g.id === drag.groupId)
  const toIndex = groups.findIndex(g => g.id === drag.groupOverId)
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return groups
  const result = [...groups]
  const [dragged] = result.splice(fromIndex, 1)
  result.splice(toIndex, 0, dragged)
  return result
})

// Cleanup on unmount
onUnmounted(() => {
  document.removeEventListener('pointermove', onPointerMove)
  document.removeEventListener('pointerup', onPointerUp)
})

// ── Context menu ────────────────────────────────────────────

const contextMenu = ref({ visible: false, x: 0, y: 0, loraPath: '' })

const contextMenuActions = computed(() => {
  const actions: any[] = [
    {
      id: 'copy-name',
      label: 'Copy LoRA Filename',
      action: () => {
        navigator.clipboard.writeText(contextMenu.value.loraPath)
      }
    },
  ]

  if (pool.value.groups.length > 0) {
    actions.push({ id: 'divider-groups', divider: true })

    for (const group of pool.value.groups) {
      actions.push({
        id: `move-to-${group.id}`,
        label: `Move to ${group.label || 'Untitled group'}`,
        action: () => {
          if (props.toolId) {
            moveToContainer(props.toolId, contextMenu.value.loraPath, group.id)
          }
        }
      })
    }
  }

  actions.push({
    id: 'move-to-new-group',
    label: 'Move to new group',
    action: () => {
      if (props.toolId) {
        const newGroupId = createGroup(props.toolId)
        if (newGroupId) {
          moveToContainer(props.toolId, contextMenu.value.loraPath, newGroupId)
        }
      }
    }
  })

  actions.push({ id: 'divider', divider: true })
  actions.push({
    id: 'remove',
    label: 'Remove',
    danger: true,
    action: () => {
      onRemove(contextMenu.value.loraPath)
    }
  })

  return actions
})

function onChipContextMenu(event: MouseEvent, loraPath: string) {
  contextMenu.value = {
    visible: true,
    x: event.clientX,
    y: event.clientY,
    loraPath
  }
}

// ── Header overflow menu ───────────────────────────────────

const headerMenu = ref({ visible: false, x: 0, y: 0 })

function onHeaderMenuClick(event: MouseEvent) {
  const btn = event.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()
  headerMenu.value = {
    visible: !headerMenu.value.visible,
    x: rect.right,
    y: rect.bottom + 4,
  }
}

const hasDisabledItems = computed(() => allItems.value.some(i => !i.enabled))

const headerMenuActions = computed(() => {
  const actions: any[] = [
    {
      id: 'remove-unavailable',
      label: unavailableCount.value > 0 ? `Remove unavailable (${unavailableCount.value})` : 'Remove unavailable',
      disabled: unavailableCount.value === 0,
      action: () => {
        if (!props.toolId) return
        for (const item of allItems.value) {
          if (!availablePathSet.value.has(item.lora)) removeFromPool(props.toolId, item.lora)
        }
      }
    },
    {
      id: 'remove-disabled',
      label: 'Remove disabled',
      disabled: !hasDisabledItems.value,
      action: () => {
        if (props.toolId) removeDisabled(props.toolId)
      }
    },
    { id: 'divider-1', divider: true },
    {
      id: 'remove-all',
      label: 'Remove all',
      danger: true,
      action: () => {
        if (props.toolId) clearPool(props.toolId)
      }
    },
  ]
  return actions
})

// ── Modal actions ───────────────────────────────────────────

function onAddLora(lora: LoraOption) {
  if (!props.toolId) return
  if (allItems.value.some(item => item.lora === lora.path)) return
  addToPool(props.toolId, lora, 1.0, true)
}

function onRemoveLora(lora: LoraOption) {
  onRemove(lora.path)
}

function addLoraByPath(path: string, enabled = true, explicitName?: string) {
  if (!props.toolId) return
  if (allItems.value.some(item => item.lora === path)) return

  const lora = explicitName
    ? { path, name: explicitName }
    : props.availableLoras.find(l => l.path === path) || {
        path,
        name: path.split('/').pop()?.replace(/\.[^.]+$/i, '').replace(/_/g, ' ') || path,
      }
  addToPool(props.toolId, lora, 1.0, enabled)
  showModal.value = false
}

defineExpose({ addLoraByPath })
</script>
