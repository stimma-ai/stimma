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
import { useChatDock, selectionBarUp, visibleOpen } from '../../composables/useChatDock'
import { useViewport } from '../../composables/useViewport'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { textClass } from '../../utils/statusColors'
import { DOCK_SIZES, fitDock } from '../../utils/chatDockState'

const dock = useChatDock()
const route = useRoute()
const router = useRouter()
const { isCompact } = useViewport()

const root = ref<HTMLElement | null>(null)
const width = ref(1200)
let ro: ResizeObserver | null = null
onMounted(() => {
  const host = root.value?.parentElement
  if (!host) return
  ro = new ResizeObserver(([e]) => { width.value = e.contentRect.width })
  ro.observe(host)
})
onBeforeUnmount(() => ro?.disconnect())

const onScreenId = computed(() => (route.name === 'chat' ? Number(route.params.id) : null))
// What can show here: everything docked except the chat on screen full size.
const visible = computed(() => dock.docked.value.filter(e => e.chatId !== onScreenId.value))

const layout = computed(() => fitDock(visible.value, width.value))
const shownIds = computed(() => new Set(layout.value.shown))
const hidden = computed(() => visible.value.filter(e => !shownIds.value.has(e.chatId)))
// Seen means an open window actually on screen; on a phone there are none.
watchEffect(() => {
  visibleOpen.value = isCompact.value
    ? new Set()
    : new Set(visible.value.filter(e => e.win === 'open' && shownIds.value.has(e.chatId)).map(e => e.chatId))
})
onBeforeUnmount(() => { visibleOpen.value = new Set() })
function widthOf(win: 'row' | 'open') {
  return `${win === 'open' ? DOCK_SIZES.open : layout.value.rowWidth}px`
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
        class="pointer-events-auto flex flex-col overflow-hidden rounded-t-lg border border-b-0 bg-surface shadow-lg transition-[width,border-color] duration-200"
        :class="[
          entry.win === 'open' ? 'h-[min(560px,70vh)]' : '',
          dock.presence.get(entry.chatId)?.needsYou && entry.win === 'row' ? 'border-accent/60' : 'border-edge-subtle',
        ]"
        :style="{ width: widthOf(entry.win) }"
        :data-dock-chat="entry.chatId"
      >
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
