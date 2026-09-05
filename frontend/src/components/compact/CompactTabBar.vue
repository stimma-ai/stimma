<script setup lang="ts">
/**
 * The compact-viewport tab bar (DESIGN.md §1.11). Five hubs, nothing else:
 * Home · Library · Workspace · Boards · Chats. Persistent on hub and detail
 * routes; App.vue hides it for overlays. Tapping the active hub pops to its
 * root. Workspace is the desktop sidebar's zone 2 (pinned + open tabs) as a
 * hub; it also owns the Tools, Flows and Stimpacks landings as segments.
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  HomeIcon, Squares2X2Icon, Square3Stack3DIcon, RectangleStackIcon, ChatBubbleLeftIcon,
} from '@heroicons/vue/24/outline'
import {
  HomeIcon as HomeSolid, Squares2X2Icon as GridSolid, Square3Stack3DIcon as StackSolid,
  RectangleStackIcon as BoardsSolid, ChatBubbleLeftIcon as ChatSolid,
} from '@heroicons/vue/24/solid'
import { useWorkspaceTabs } from '../../composables/useWorkspaceTabs'
import { hubForRoute, type HubId } from '../../composables/useCompactChrome'

const HUBS: Array<{ id: HubId; label: string; to: string; icon: any; solid: any }> = [
  { id: 'home', label: 'Home', to: '/home', icon: HomeIcon, solid: HomeSolid },
  { id: 'library', label: 'Library', to: '/browse', icon: Squares2X2Icon, solid: GridSolid },
  { id: 'workspace', label: 'Workspace', to: '/workspace', icon: Square3Stack3DIcon, solid: StackSolid },
  { id: 'boards', label: 'Boards', to: '/boards', icon: RectangleStackIcon, solid: BoardsSolid },
  { id: 'chats', label: 'Chats', to: '/chats', icon: ChatBubbleLeftIcon, solid: ChatSolid },
]

const route = useRoute()
const router = useRouter()
const { openTabs, editorTabs } = useWorkspaceTabs()

const active = computed(() => hubForRoute(route.name))
// One dot, not a count: something is open that isn't the screen you're on.
const workspaceHasOpen = computed(() => openTabs.value.length + editorTabs.value.length > 0)

function go(hub: typeof HUBS[number]) {
  router.push(hub.to)
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
