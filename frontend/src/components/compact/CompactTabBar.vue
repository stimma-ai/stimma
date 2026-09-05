<script setup lang="ts">
/**
 * The compact-viewport tab bar (DESIGN.md §1.11). Four hubs, nothing else:
 * Home · Chats · Assets · Tools. Persistent on hub and detail routes;
 * App.vue hides it for overlays. Tapping the active hub pops to its root.
 * The Tools hub owns Tools · Flows · Boards · Projects as segments. The
 * working set (open tools, chats, boards, edits) is not a hub: it is the
 * header's switcher, available everywhere.
 */
import { computed } from 'vue'
import {
  HomeIcon, Squares2X2Icon, WrenchScrewdriverIcon, ChatBubbleLeftIcon,
} from '@heroicons/vue/24/outline'
import {
  HomeIcon as HomeSolid, Squares2X2Icon as GridSolid, WrenchScrewdriverIcon as WrenchSolid,
  ChatBubbleLeftIcon as ChatSolid,
} from '@heroicons/vue/24/solid'
import { useWorkspaceTabs } from '../../composables/useWorkspaceTabs'
import { type HubId } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'

const HUBS: Array<{ id: HubId; label: string; to: string; icon: any; solid: any }> = [
  { id: 'home', label: 'Home', to: '/home', icon: HomeIcon, solid: HomeSolid },
  { id: 'chats', label: 'Chats', to: '/chats', icon: ChatBubbleLeftIcon, solid: ChatSolid },
  { id: 'library', label: 'Assets', to: '/browse', icon: Squares2X2Icon, solid: GridSolid },
  { id: 'workspace', label: 'Tools', to: '/tools', icon: WrenchScrewdriverIcon, solid: WrenchSolid },
]

const { openTabs, editorTabs } = useWorkspaceTabs()

// The nav store owns the per-hub stacks (useCompactNav); the bar only asks
// which hub is current and hands taps over.
const nav = useCompactNav()
const active = computed(() => nav.state.current)
// One dot, not a count: something is open that isn't the screen you're on.
const workspaceHasOpen = computed(() => openTabs.value.length + editorTabs.value.length > 0)

function go(hub: typeof HUBS[number]) {
  nav.goToHub(hub.id)
}
</script>

<template>
  <nav
    class="compact-tab-bar flex-none flex items-stretch border-t border-edge-subtle bg-surface pb-safe"
    aria-label="Primary"
  >
    <button
      v-for="hub in HUBS"
      :key="hub.id"
      type="button"
      class="relative flex-1 min-w-0 flex flex-col items-center justify-center gap-1 pt-2 pb-2.5 text-[10.5px] font-medium transition-colors border-none bg-transparent min-h-11"
      :class="active === hub.id ? 'text-accent-hi' : 'text-content-tertiary'"
      :aria-current="active === hub.id ? 'page' : undefined"
      @click="go(hub)"
    >
      <component :is="active === hub.id ? hub.solid : hub.icon" class="w-6 h-6" />
      <span>{{ hub.label }}</span>
      <span
        v-if="hub.id === 'workspace' && workspaceHasOpen && active !== 'workspace'"
        class="absolute top-1.5 right-[calc(50%-18px)] w-2 h-2 rounded-full bg-accent ring-2 ring-surface"
        aria-hidden="true"
      ></span>
    </button>
  </nav>
</template>
