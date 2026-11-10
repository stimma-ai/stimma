<script setup lang="ts">
// A docked chat's header: the row it shows when minimized, and its window's
// header when open. What you asked, what it's doing, a progress line while a
// batch runs, and what it made. The chat's own management (rename, clone,
// clear, settings, delete) sits behind the overflow menu, as on the full
// chat's control strip; minimize, full size and close are the window's own.
// Close only takes the chat off the dock.
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { CheckIcon } from '@heroicons/vue/20/solid'
import { ArrowsPointingOutIcon, ChevronDownIcon, ChevronUpIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { useRouter } from 'vue-router'
import IconButton from '../ui/IconButton.vue'
import OverflowButton from '../ui/OverflowButton.vue'
import Spinner from '../ui/Spinner.vue'
import StatusDot from '../ui/StatusDot.vue'
import Tooltip from '../ui/Tooltip.vue'
import { MediaImage } from '../media'
import { useChatDock, type DockPresence } from '../../composables/useChatDock'
import { dotClass, textClass } from '../../utils/statusColors'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { devModeRef } from '../../appConfig'

const props = defineProps<{
  chatId: number
  name: string
  win: 'row' | 'open'
  presence: DockPresence
}>()
const emit = defineEmits<{
  rename: [name: string]
  clone: []
  clear: []
  delete: []
  settings: []
  'copy-raw-messages': []
}>()

const router = useRouter()
const dock = useChatDock()
const title = computed(() => props.name || 'New chat')
const open = computed(() => props.win === 'open')

function toggle() { dock.toggle(props.chatId) }
function fullSize() { router.push({ name: 'chat', params: { id: props.chatId } }) }
function close() { dock.undock(props.chatId) }

// A window that just folded to a row flashes once, so it can be found.
const flashing = ref(false)
watch(() => dock.foldedAt.get(props.chatId), (at) => {
  if (!at) return
  flashing.value = true
  setTimeout(() => { flashing.value = false; dock.foldedAt.delete(props.chatId) }, 1600)
}, { immediate: true })

// Inline rename, as the full chat's strip does it.
const editing = ref(false)
const draftName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
async function startRename() {
  menuOpen.value = false
  draftName.value = props.name
  editing.value = true
  await nextTick()
  nameInput.value?.select()
}
function commitRename() {
  if (!editing.value) return
  editing.value = false
  const next = draftName.value.trim()
  if (next && next !== props.name) emit('rename', next)
}

const menuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)
const menuPanel = ref<HTMLElement | null>(null)
function pick(action: () => void) { menuOpen.value = false; action() }
function onDocPointer(e: PointerEvent) {
  if (menuOpen.value && menuRef.value && !menuRef.value.contains(e.target as Node)) menuOpen.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !menuOpen.value || !menuPanel.value || !isTopmostEscapeLayer(menuPanel.value)) return
  menuOpen.value = false
  consumeEscape(e)
}
watch(menuOpen, (on) => {
  if (on) {
    document.addEventListener('pointerdown', onDocPointer, true)
    document.addEventListener('keydown', onKey, true)
  } else {
    document.removeEventListener('pointerdown', onDocPointer, true)
    document.removeEventListener('keydown', onKey, true)
  }
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocPointer, true)
  document.removeEventListener('keydown', onKey, true)
})

const statusClass = computed(() => props.presence.needsYou ? textClass('awaiting') : 'text-content-tertiary')
</script>

<template>
  <div
    class="group relative flex h-12 flex-none cursor-pointer items-center gap-2.5 pl-3 pr-1.5 transition-shadow"
    :class="[open ? 'border-b border-edge-subtle' : '', flashing ? 'ring-2 ring-inset ring-accent' : '']"
    data-dock-header
    @click="toggle"
  >
    <div class="flex h-5 w-5 flex-none items-center justify-center">
      <Spinner v-if="presence.busy && !presence.needsYou" size="sm" />
      <StatusDot v-else-if="presence.needsYou" bucket="awaiting" :pulse="!open" class="!h-2.5 !w-2.5" />
      <CheckIcon v-else-if="presence.status" class="h-4 w-4" :class="textClass('done')" />
      <StatusDot v-else bucket="queued" />
    </div>

    <div class="min-w-0 flex-1">
      <input
        v-if="editing"
        ref="nameInput"
        v-model="draftName"
        v-no-autocorrect
        class="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-0.5 text-sm text-content outline-none focus:border-accent"
        placeholder="Name this chat..."
        @click.stop
        @keydown.enter.prevent="commitRename"
        @keydown.esc.stop.prevent="editing = false"
        @blur="commitRename"
      >
      <template v-else>
        <div class="flex min-w-0 items-center gap-1.5">
          <span class="truncate text-sm font-medium text-content" :class="name ? '' : 'italic text-content-muted'" @dblclick.stop="startRename">{{ title }}</span>
          <span v-if="presence.mcp" class="flex-shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10" title="Driven by a connected assistant over MCP">MCP</span>
        </div>
        <div v-if="presence.status" class="truncate text-xs" :class="statusClass">{{ presence.status }}</div>
      </template>
    </div>

    <!-- What it made (or what was sent), on the row -->
    <div v-if="!open && presence.peekMediaIds.length" class="flex flex-none -space-x-2 group-hover:hidden">
      <MediaImage
        v-for="mediaId in presence.peekMediaIds"
        :key="mediaId"
        :media-id="mediaId"
        :thumbnail="true"
        :thumbnail-size="64"
        :draggable="false"
        :enable-context-menu="false"
        container-class="h-6 w-6 overflow-hidden rounded-media ring-2 ring-surface bg-matte"
        img-class="h-full w-full object-cover"
      />
    </div>

    <div class="flex flex-none items-center" :class="open ? '' : 'hidden group-hover:flex'" @click.stop>
      <div v-if="open" ref="menuRef" class="relative">
        <OverflowButton @click="menuOpen = !menuOpen" />
        <div v-if="menuOpen" ref="menuPanel" data-escape-layer class="absolute right-0 top-full z-menu mt-1 w-44 rounded-lg border border-edge-subtle bg-surface py-1 shadow-lg">
          <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content hover:bg-overlay-light" @click="startRename">Rename</button>
          <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content hover:bg-overlay-light" @click="pick(() => emit('settings'))">Chat settings</button>
          <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content hover:bg-overlay-light" @click="pick(() => emit('clone'))">Clone chat</button>
          <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content hover:bg-overlay-light" @click="pick(() => emit('clear'))">Clear messages</button>
          <button v-if="devModeRef" class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-content hover:bg-overlay-light" @click="pick(() => emit('copy-raw-messages'))">Copy raw chat messages</button>
          <div class="my-1 border-t border-edge-subtle"></div>
          <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-400 hover:bg-red-500/10" @click="pick(() => emit('delete'))">Delete chat</button>
        </div>
      </div>
      <Tooltip :text="open ? 'Minimize' : 'Open'">
        <IconButton :aria-label="open ? 'Minimize' : 'Open'" @click="toggle">
          <ChevronDownIcon v-if="open" class="h-4 w-4" /><ChevronUpIcon v-else class="h-4 w-4" />
        </IconButton>
      </Tooltip>
      <Tooltip text="Full size">
        <IconButton aria-label="Full size" @click="fullSize"><ArrowsPointingOutIcon class="h-4 w-4" /></IconButton>
      </Tooltip>
      <Tooltip text="Close">
        <IconButton aria-label="Close" @click="close"><XMarkIcon class="h-4 w-4" /></IconButton>
      </Tooltip>
    </div>

    <!-- Progress, along the row's bottom edge -->
    <div v-if="presence.busy && presence.progress != null" class="absolute inset-x-0 bottom-0 h-0.5 bg-overlay-subtle">
      <div class="h-full transition-[width] duration-300" :class="dotClass('running')" :style="{ width: `${Math.round(presence.progress * 100)}%` }"></div>
    </div>
  </div>
</template>
