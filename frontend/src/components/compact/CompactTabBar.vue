<script setup lang="ts">
/**
 * The compact-viewport tab bar (DESIGN.md §1.11). Four hubs and one
 * control: Home · Chats · [Open] · Assets · Studio. Persistent on hub and
 * detail routes; App.vue hides it for overlays. Tapping the active hub pops
 * to its root. Studio owns Tools · Flows · Boards · Projects as segments.
 * Open is the working set (open tools, chats, boards, edits): the raised
 * centre button, styled apart from the hubs, opening a sheet, never a route.
 */
import { computed, ref } from 'vue'
import {
  HomeIcon, Squares2X2Icon, Square3Stack3DIcon, ChatBubbleLeftIcon, Square2StackIcon,
} from '@heroicons/vue/24/outline'
import SwitcherSheet from './SwitcherSheet.vue'
import {
  HomeIcon as HomeSolid, Squares2X2Icon as GridSolid, Square3Stack3DIcon as StackSolid,
  ChatBubbleLeftIcon as ChatSolid,
} from '@heroicons/vue/24/solid'
import { useWorkspaceTabs } from '../../composables/useWorkspaceTabs'
import { type HubId } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'

const HUBS: Array<{ id: HubId; label: string; to: string; icon: any; solid: any }> = [
  { id: 'home', label: 'Home', to: '/home', icon: HomeIcon, solid: HomeSolid },
  { id: 'chats', label: 'Chats', to: '/chats', icon: ChatBubbleLeftIcon, solid: ChatSolid },
  { id: 'library', label: 'Assets', to: '/browse', icon: Squares2X2Icon, solid: GridSolid },
  { id: 'workspace', label: 'Studio', to: '/tools', icon: Square3Stack3DIcon, solid: StackSolid },
]

const { openTabs, editorTabs } = useWorkspaceTabs()

// The nav store owns the per-hub stacks (useCompactNav); the bar only asks
// which hub is current and hands taps over.
const nav = useCompactNav()
const active = computed(() => nav.state.current)
// The switcher: a fixed control at the bar's end, styled apart from the hubs
// (no active state, a count instead of a dot). It opens a sheet, never a route.
const switcherOpen = ref(false)
const openCount = computed(() => openTabs.value.length + editorTabs.value.length)

function go(hub: typeof HUBS[number]) {
  nav.goToHub(hub.id)
}
</script>

<template>
  <nav
    class="compact-tab-bar flex-none flex items-stretch border-t border-edge-subtle bg-surface pb-safe"
    aria-label="Primary"
  >
    <template v-for="(hub, i) in HUBS" :key="hub.id">
      <button
        type="button"
        class="relative flex-1 min-w-0 flex flex-col items-center justify-center gap-1 pt-2 pb-2.5 text-[10.5px] font-medium transition-colors border-none bg-transparent min-h-11"
        :class="active === hub.id ? 'text-accent-hi' : 'text-content-tertiary'"
        :aria-current="active === hub.id ? 'page' : undefined"
        @click="go(hub)"
      >
        <component :is="active === hub.id ? hub.solid : hub.icon" class="w-6 h-6" />
        <span>{{ hub.label }}</span>
      </button>
      <!-- Open: the working set, in the middle, raised. Not a hub, never "current". -->
      <div v-if="i === 1" class="flex-1 min-w-0 flex items-center justify-center">
        <button
          type="button"
          class="relative w-12 h-12 -mt-4 flex items-center justify-center rounded-xl border border-edge bg-surface-raised shadow-lg text-content-secondary"
          aria-label="Open items"
          @click="switcherOpen = true"
        >
          <Square2StackIcon class="w-6 h-6" />
          <span v-if="openCount" class="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-white text-[10px] font-semibold leading-[18px] text-center ring-2 ring-surface">{{ openCount }}</span>
        </button>
      </div>
    </template>
    <SwitcherSheet :show="switcherOpen" @close="switcherOpen = false" />
  </nav>
</template>
