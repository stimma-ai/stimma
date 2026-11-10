<script setup lang="ts">
// A docked chat's header: the row it shows when minimized, and its window's
// header when open. What you asked, what it's doing, a progress line while a
// batch runs, and what it made. Minimize, full size and close are the
// window's own (clicking the header minimizes and restores); the chat's
// management lives on the full chat. Close only takes the chat off the dock.
// Double-click the name to rename it.
import { computed, nextTick, ref, watch } from 'vue'
import { CheckIcon } from '@heroicons/vue/20/solid'
import { ArrowsPointingOutIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { useRouter } from 'vue-router'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import StatusDot from '../ui/StatusDot.vue'
import Tooltip from '../ui/Tooltip.vue'
import { MediaImage } from '../media'
import { useChatDock, type DockPresence } from '../../composables/useChatDock'
import { dotClass, textClass } from '../../utils/statusColors'

const props = defineProps<{
  chatId: number
  name: string
  win: 'row' | 'open'
  presence: DockPresence
}>()
const emit = defineEmits<{
  rename: [name: string]
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

    <!-- Clicking the header minimizes and restores. Open, full size shows;
         close appears on hover. A row shows both on hover. -->
    <div class="flex flex-none items-center" :class="open ? '' : 'hidden group-hover:flex'" @click.stop>
      <Tooltip text="Full size">
        <IconButton aria-label="Full size" @click="fullSize"><ArrowsPointingOutIcon class="h-4 w-4" /></IconButton>
      </Tooltip>
      <Tooltip text="Close" class="hidden group-hover:inline-flex">
        <IconButton aria-label="Close" @click="close"><XMarkIcon class="h-4 w-4" /></IconButton>
      </Tooltip>
    </div>

    <!-- Progress, along the row's bottom edge -->
    <div v-if="presence.busy && presence.progress != null" class="absolute inset-x-0 bottom-0 h-0.5 bg-overlay-subtle">
      <div class="h-full transition-[width] duration-300" :class="dotClass('running')" :style="{ width: `${Math.round(presence.progress * 100)}%` }"></div>
    </div>
  </div>
</template>
