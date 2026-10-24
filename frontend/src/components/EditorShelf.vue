<template>
  <!-- The parent sidebar supplies the section label and peer separator. -->
  <div v-if="ranked.length > 0" class="py-2.5">
    <!-- The drop ring hugs the chips rather than the sidebar's full width, so
         the negative margin cancels its own padding and capacity math (which
         measures the content box) is unaffected. -->
    <div class="px-3">
      <div
        ref="shelfEl"
        class="flex flex-wrap gap-1.5 rounded -m-1 p-1"
        :class="dropHover ? 'ring-1 ring-accent bg-accent/10' : ''"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      >
        <EditorShelfChip
          v-for="entry in visible"
          :key="entry.tabId"
          :entry="entry"
          :active="entry.assetId === activeAssetId"
          @open="open(entry)"
          @remove="$emit('remove', entry.tabId)"
          @contextmenu="$emit('contextmenu', { tabId: entry.tabId, event: $event })"
        />

        <!-- The door. Costs a slot rather than a row, so the shelf height is the
             same at nine open editors as at ninety. -->
        <button
          v-if="overflow.length > 0"
          ref="moreEl"
          class="relative w-12 h-12 rounded-media overflow-hidden cursor-pointer border-none p-0 bg-matte"
          :title="`${overflow.length} more`"
          @click.stop="toggleFlyout"
        >
          <span class="absolute inset-0 grid grid-cols-2 grid-rows-2">
            <MediaImage
              v-for="entry in mosaic"
              :key="entry.tabId"
              :media-id="Number(entry.mediaId)"
              :asset-id="Number(entry.assetId)"
              thumbnail
              :thumbnail-size="64"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </span>
          <span class="absolute inset-0 transition-colors" :class="flyoutOpen ? 'bg-matte/50' : 'bg-matte/70'"></span>
          <span class="absolute inset-0 flex items-center justify-center text-sm font-semibold tabular-nums text-content">
            +{{ overflow.length }}
          </span>
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="flyoutOpen"
        ref="flyoutEl" data-escape-layer
        class="fixed z-menu w-[300px] bg-surface-raised border border-edge-subtle rounded-lg shadow-lg p-3"
        :style="submenuStyle"
        @mousedown.stop
        @click.stop
      >
        <div class="text-xs font-semibold text-content mb-2">Editing</div>

        <div class="max-h-[268px] overflow-y-auto custom-scrollbar -mr-1 pr-1">
          <div class="flex flex-wrap gap-1.5">
            <EditorShelfChip
              v-for="entry in recent"
              :key="entry.tabId"
              :entry="entry"
              :active="entry.assetId === activeAssetId"
              @open="open(entry)"
              @remove="$emit('remove', entry.tabId)"
              @contextmenu="$emit('contextmenu', { tabId: entry.tabId, event: $event })"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * Open editors, as thumbnails.
 *
 * An editor tab is a shortcut to an Asset — the op stack persists against the
 * asset itself — so these entries need no names, and removing one costs
 * nothing. Names were the problem the shelf exists to solve: a column of rows
 * reading "Darkroom" six times identifies nothing, and auto-titling a batch of
 * near-identical generations does little better than the thumbnail already does.
 *
 * Capacity is measured, not assumed: the sidebar is resizable, so the shelf
 * counts the chips that fit its own width and lets SHELF_ROWS of them show.
 * Anything past that goes behind the +N chip rather than growing the sidebar —
 * a section that changes height under you is the one thing a stable map can't do.
 */
import { consumeEscape, isTopmostEscapeLayer } from '../utils/escapeLayers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import MediaImage from './media/MediaImage.vue'
import EditorShelfChip from './EditorShelfChip.vue'
import { useSubmenuPosition } from '../composables/useContextMenuPosition'
import { useEditorShelf } from '../composables/useEditorShelf'
import type { WorkspaceTab } from '../composables/useWorkspaceTabs'
import { orderByRecency, orderForDisplay, shelfColumns, splitShelf, SHELF_ROWS, type ShelfEntry } from '../utils/editorShelf'

const props = defineProps<{
  tabs: readonly WorkspaceTab[]
}>()

const emit = defineEmits<{
  open: [tabId: string]
  remove: [tabId: string]
  contextmenu: [payload: { tabId: string, event: MouseEvent }]
  mediaDrop: [event: DragEvent]
}>()

const route = useRoute()

const shelfEl = ref<HTMLElement | null>(null)
const moreEl = ref<HTMLElement | null>(null)
const flyoutEl = ref<HTMLElement | null>(null)
const flyoutOpen = ref(false)

const tabsRef = computed(() => props.tabs)
const { ranked } = useEditorShelf(tabsRef)

const activeAssetId = computed(() => (
  route.name === 'edit-image' && route.params.assetId ? String(route.params.assetId) : null
))

// Measured, because the sidebar resizes between 200 and 500px.
const shelfWidth = ref(0)
let observer: ResizeObserver | null = null
onMounted(() => {
  observer = new ResizeObserver((entries) => {
    for (const e of entries) shelfWidth.value = e.contentRect.width
  })
  if (shelfEl.value) observer.observe(shelfEl.value)
})
watch(shelfEl, (el) => {
  observer?.disconnect()
  if (el && observer) observer.observe(el)
})
onBeforeUnmount(() => observer?.disconnect())

const capacity = computed(() => shelfColumns(shelfWidth.value) * SHELF_ROWS)
const split = computed(() => splitShelf(ranked.value, capacity.value))
// Membership comes from rank; position is newest-opened first. Activating an
// existing chip therefore never makes the shelf rearrange under the cursor.
const visible = computed(() => orderForDisplay(split.value.visible))
const overflow = computed(() => split.value.overflow)

/** The four faces under the +N scrim: enough to read as "more images". */
const mosaic = computed(() => overflow.value.filter(e => e.mediaId).slice(0, 4))

/** Flyout contents: everything open, most recent first. */
const recent = computed(() => orderByRecency(ranked.value))

// The flyout hangs off the +N chip and clears the sidebar, like a submenu.
const anchorRect = ref<DOMRect | null>(null)
const sidebarEl = ref<HTMLElement | null>(null)
const { submenuStyle } = useSubmenuPosition(sidebarEl, anchorRect, flyoutEl, flyoutOpen)

function toggleFlyout() {
  if (flyoutOpen.value) {
    flyoutOpen.value = false
    return
  }
  sidebarEl.value = shelfEl.value?.closest('.navigation-sidebar') as HTMLElement | null
  anchorRect.value = moreEl.value?.getBoundingClientRect() ?? null
  flyoutOpen.value = true
}

function open(entry: ShelfEntry) {
  flyoutOpen.value = false
  emit('open', entry.tabId)
}

// Nothing behind the door anymore (removed, or promoted onto the shelf).
watch(overflow, (list) => { if (list.length === 0) flyoutOpen.value = false })

// Drop an image on the shelf to open its editor. WKWebView never fires
// dragenter reliably, so hover state comes from dragover, and dragleave only
// counts when the pointer actually left the shelf (not a child chip).
const dropHover = ref(false)
function onDragOver(e: DragEvent) {
  e.preventDefault()
  dropHover.value = true
}
function onDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (next && shelfEl.value?.contains(next)) return
  dropHover.value = false
}
function onDrop(e: DragEvent) {
  dropHover.value = false
  emit('mediaDrop', e)
}

function onDocumentClick() { flyoutOpen.value = false }
function onKeydown(e: KeyboardEvent) {
  if (!e.defaultPrevented && e.key === 'Escape' && isTopmostEscapeLayer(flyoutEl.value)) {
    consumeEscape(e)
    flyoutOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>
