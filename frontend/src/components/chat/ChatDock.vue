<script setup lang="ts">
// The chat dock: docked chats along the bottom edge of the page, newest in
// the corner. Every docked chat is a real ChatView kept mounted (as a row it
// shows only its header), so its status, its queue and its attention rules
// stay live whether it's open, a row, or folded into "+N more". The chat on
// screen full size steps aside here and comes back when you leave it.
//
// On a phone there's no room for windows: the dock is one floating button
// with the chat glyph, a spinner on its corner while anything is working and
// a dot when a chat wants you. Tapping it opens that chat full screen.
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatBubbleOvalLeftEllipsisIcon } from '@heroicons/vue/24/outline'
import ChatView from '../../views/ChatView.vue'
import Spinner from '../ui/Spinner.vue'
import StatusDot from '../ui/StatusDot.vue'
import { useChatDock, selectionBarUp, visibleOpen, windowSizeFor, setWindowSize } from '../../composables/useChatDock'
import { useViewport } from '../../composables/useViewport'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { textClass } from '../../utils/statusColors'
import { DOCK_SIZES, clampWindowSize, fitDock } from '../../utils/chatDockState'

const dock = useChatDock()
const route = useRoute()
const router = useRouter()
const { isCompact } = useViewport()

const root = ref<HTMLElement | null>(null)
const width = ref(1200)
const height = ref(800)
let ro: ResizeObserver | null = null
onMounted(() => {
  const host = root.value?.parentElement
  if (!host) return
  ro = new ResizeObserver(([e]) => { width.value = e.contentRect.width; height.value = e.contentRect.height })
  ro.observe(host)
})
onBeforeUnmount(() => ro?.disconnect())

const onScreenId = computed(() => (route.name === 'chat' ? Number(route.params.id) : null))
// What can show here: everything docked except the chat on screen full size.
const visible = computed(() => dock.docked.value.filter(e => e.chatId !== onScreenId.value))

// Open windows take the size they were given (a drag on their top or left
// edge), kept inside the page.
const room = computed(() => ({ w: Math.min(900, width.value - DOCK_SIZES.edge * 2), h: height.value - 16 }))
function openSize(chatId: number) {
  const stored = windowSizeFor(chatId)
  const fallback = { w: DOCK_SIZES.open, h: Math.min(560, Math.round(height.value * 0.7)) }
  return clampWindowSize(stored ?? fallback, room.value)
}
const layout = computed(() => fitDock(
  visible.value.map(e => ({ chatId: e.chatId, win: e.win, width: e.win === 'open' ? openSize(e.chatId).w : undefined })),
  width.value,
))

// Dragging grows the window up and to the left: it's anchored bottom right.
const resizing = ref<number | null>(null)
function startResize(event: PointerEvent, chatId: number, axis: 'both' | 'w' | 'h') {
  const start = openSize(chatId)
  // Growing wider can't push this window, or one beside it, into "+N more":
  // it may take what the others on screen leave.
  const others = visible.value.filter(e => e.chatId !== chatId && shownIds.value.has(e.chatId))
  const othersWidth = others.reduce((sum, e) => sum + (e.win === 'open' ? openSize(e.chatId).w : layout.value.rowWidth) + DOCK_SIZES.gap, 0)
  const reserve = hidden.value.length ? DOCK_SIZES.more : 0
  // Floored: sizes are whole pixels, and rounding up could overflow the row.
  const limit = { w: Math.max(start.w, Math.floor(Math.min(room.value.w, width.value - DOCK_SIZES.edge * 2 - othersWidth - DOCK_SIZES.gap - reserve))), h: Math.floor(room.value.h) }
  const x0 = event.clientX
  const y0 = event.clientY
  resizing.value = chatId
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture?.(event.pointerId)
  const sizeAt = (e: PointerEvent) => clampWindowSize({
    w: axis === 'h' ? start.w : start.w + (x0 - e.clientX),
    h: axis === 'w' ? start.h : start.h + (y0 - e.clientY),
  }, limit)
  const move = (e: PointerEvent) => setWindowSize(chatId, sizeAt(e))
  const up = (e: PointerEvent) => {
    setWindowSize(chatId, sizeAt(e), true)
    resizing.value = null
    target.removeEventListener('pointermove', move)
    target.removeEventListener('pointerup', up)
    target.removeEventListener('pointercancel', up)
  }
  target.addEventListener('pointermove', move)
  target.addEventListener('pointerup', up)
  target.addEventListener('pointercancel', up)
}
const shownIds = computed(() => new Set(layout.value.shown))
const hidden = computed(() => visible.value.filter(e => !shownIds.value.has(e.chatId)))
// Seen means an open window actually on screen; on a phone there are none.
watchEffect(() => {
  visibleOpen.value = isCompact.value
    ? new Set()
    : new Set(visible.value.filter(e => e.win === 'open' && shownIds.value.has(e.chatId)).map(e => e.chatId))
})
onBeforeUnmount(() => { visibleOpen.value = new Set() })
function widthOf(entry: { chatId: number; win: 'row' | 'open' }) {
  return `${entry.win === 'open' ? openSize(entry.chatId).w : layout.value.rowWidth}px`
}

// "+N more": the hidden docked chats, wherever they belong.
const moreOpen = ref(false)
const moreRef = ref<HTMLElement | null>(null)
const morePanel = ref<HTMLElement | null>(null)
function openHidden(chatId: number) {
  moreOpen.value = false
  dock.open(chatId, { front: true })
}
function onDocPointer(e: PointerEvent) {
  if (moreOpen.value && moreRef.value && !moreRef.value.contains(e.target as Node)) moreOpen.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !moreOpen.value || !morePanel.value || !isTopmostEscapeLayer(morePanel.value)) return
  moreOpen.value = false
  consumeEscape(e)
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocPointer, true)
  document.addEventListener('keydown', onKey, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointer, true)
  document.removeEventListener('keydown', onKey, true)
})

// Phone: one button for the whole dock.
const anyBusy = computed(() => dock.docked.value.some(e => dock.presence.get(e.chatId)?.busy))
const anyWants = computed(() => dock.docked.value.some(e => dock.presence.get(e.chatId)?.needsYou))
function openFromButton() {
  const list = dock.docked.value
  const target = list.find(e => dock.presence.get(e.chatId)?.needsYou) || list[0]
  if (target) router.push({ name: 'chat', params: { id: target.chatId } })
}
</script>

<template>
  <div ref="root" class="contents">
    <!-- Desktop: windows and rows on the bottom edge -->
    <div
      v-if="!isCompact && dock.docked.value.length"
      class="pointer-events-none absolute bottom-0 right-4 z-chrome flex flex-row-reverse items-end gap-2"
      data-chat-dock
    >
      <div
        v-for="entry in dock.docked.value"
        v-show="shownIds.has(entry.chatId)"
        :key="entry.chatId"
        class="pointer-events-auto relative flex flex-col overflow-hidden rounded-t-lg border border-b-0 bg-surface shadow-lg"
        :class="[
          resizing === entry.chatId ? 'select-none' : 'transition-[width,border-color] duration-200',
          dock.presence.get(entry.chatId)?.needsYou && entry.win === 'row' ? 'border-accent/60' : 'border-edge-subtle',
        ]"
        :style="{ width: widthOf(entry), height: entry.win === 'open' ? `${openSize(entry.chatId).h}px` : undefined }"
        :data-dock-chat="entry.chatId"
      >
        <!-- Resize from the top and left edges (it grows up and to the left) -->
        <template v-if="entry.win === 'open'">
          <div class="absolute left-0 top-0 z-10 h-3 w-3 cursor-nwse-resize" data-dock-resize="both" @pointerdown.stop.prevent="startResize($event, entry.chatId, 'both')" @click.stop />
          <div class="absolute left-3 right-0 top-0 z-10 h-1.5 cursor-ns-resize" data-dock-resize="h" @pointerdown.stop.prevent="startResize($event, entry.chatId, 'h')" @click.stop />
          <div class="absolute bottom-0 left-0 top-3 z-10 w-1.5 cursor-ew-resize" data-dock-resize="w" @pointerdown.stop.prevent="startResize($event, entry.chatId, 'w')" @click.stop />
        </template>
        <ChatView :chat-id="entry.chatId" docked :dock-win="entry.win" />
      </div>

      <div v-if="hidden.length" ref="moreRef" class="pointer-events-auto relative mb-2">
        <button
          type="button"
          class="rounded-md border border-edge-subtle bg-surface px-2.5 py-1.5 text-xs text-content-secondary shadow-lg hover:text-content"
          @click="moreOpen = !moreOpen"
        >+{{ hidden.length }} more</button>
        <div v-if="moreOpen" ref="morePanel" data-escape-layer class="absolute bottom-full right-0 z-menu mb-1 w-64 rounded-lg border border-edge-subtle bg-surface py-1 shadow-lg">
          <button
            v-for="entry in hidden"
            :key="entry.chatId"
            class="flex w-full flex-col items-start px-3 py-2 text-left hover:bg-overlay-light"
            @click="openHidden(entry.chatId)"
          >
            <span class="w-full truncate text-xs text-content">{{ dock.presence.get(entry.chatId)?.name || 'New chat' }}</span>
            <span v-if="dock.presence.get(entry.chatId)?.status" class="w-full truncate text-[11px]" :class="dock.presence.get(entry.chatId)?.needsYou ? textClass('awaiting') : 'text-content-muted'">{{ dock.presence.get(entry.chatId)?.status }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Phone: docked chats stay live off screen; one button opens them -->
    <template v-if="isCompact">
      <div class="hidden" aria-hidden="true">
        <ChatView v-for="entry in dock.docked.value" :key="entry.chatId" :chat-id="entry.chatId" docked dock-win="row" />
      </div>
      <button
        v-if="dock.docked.value.length && route.name !== 'chat'"
        type="button"
        class="absolute right-4 z-chrome flex h-14 w-14 items-center justify-center rounded-lg bg-surface-raised text-content shadow-lg transition-[bottom] duration-200 active:opacity-80"
        :class="selectionBarUp ? 'bottom-[calc(5.5rem+var(--safe-bottom))]' : 'bottom-[calc(1rem+var(--safe-bottom))]'"
        aria-label="Chats"
        data-dock-button
        @click="openFromButton"
      >
        <ChatBubbleOvalLeftEllipsisIcon class="h-6 w-6" />
        <span v-if="anyBusy" class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-surface-raised shadow"><Spinner size="sm" /></span>
        <span v-else-if="anyWants" class="absolute -right-0.5 -top-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-surface-raised"><StatusDot bucket="awaiting" pulse class="!h-2.5 !w-2.5" /></span>
        <span v-if="dock.docked.value.length > 1" class="absolute -bottom-1 -left-1 min-w-[20px] rounded-full bg-base px-1 text-center font-mono text-[11px] leading-5 text-content-secondary shadow">{{ dock.docked.value.length }}</span>
      </button>
    </template>
  </div>
</template>
