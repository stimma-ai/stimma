<script setup lang="ts">
/**
 * The compact header (DESIGN.md §1.11): menu (the sidebar drawer) or back
 * chevron, title, and the right-hand strip. Hubs carry what the desktop top bar's right side
 * carries — the transient background-work indicator, provider managers
 * (ComfyUI), search — plus the hub's create action. Detail routes show a
 * back chevron. The Library hub's title opens the scope sheet; Workspace
 * hub routes carry the Tools / Flows / Boards / Projects segmented control.
 * The working set (open tools, chats, boards, edits) is the tab bar's
 * trailing switcher control, not a header action.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDownIcon, ChevronLeftIcon, EllipsisVerticalIcon, MagnifyingGlassIcon, PlusIcon } from '@heroicons/vue/24/outline'
import { useCompactChrome, hubForRoute } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'
import { useBackgroundWork } from '../../composables/useBackgroundWork'
import Sheet from '../ui/Sheet.vue'
import LibraryScopeSheet from './LibraryScopeSheet.vue'
import BackgroundWorkIndicator from '../BackgroundWorkIndicator.vue'
import BackgroundWorkPanel from '../BackgroundWorkPanel.vue'
import ProviderManagerButton from '../ProviderManagerButton.vue'

const emit = defineEmits<{ openSettings: [section: string]; openMenu: [] }>()

const route = useRoute()
const router = useRouter()
const { isHub, title, subtitle, primaryAction, menuItems } = useCompactChrome(route)
const backgroundWork = useBackgroundWork()
const { hasActiveWork, progressTitle } = backgroundWork
onMounted(() => backgroundWork.start())

const scopeOpen = ref(false)
const workOpen = ref(false)
const menuOpen = ref(false)

// The Assets hub's title is a scope control: All assets, saved views, upload, trash.
const isLibrary = computed(() => isHub.value && hubForRoute(route.name) === 'library')


const nav = useCompactNav()
function back() {
  nav.back()
}

function openSearch() {
  router.push({ name: 'search' })
}
</script>

<template>
  <header class="compact-header flex-none bg-base pt-safe">
    <div class="h-[60px] pt-2 flex items-center gap-0.5 px-3">
      <!-- The menu (the sidebar drawer: library, working set, account) is on
           every screen — it is the multitasking switcher. Details add a back
           chevron beside it. -->
      <button
        type="button"
        class="w-11 h-11 flex items-center justify-center border-none bg-transparent"
        aria-label="Menu"
        @click="emit('openMenu')"
      >
        <span class="w-9 h-9 rounded-full bg-overlay-subtle flex items-center justify-center text-content">
          <svg class="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <path d="M3 7h14M3 13h9" />
          </svg>
        </span>
      </button>
      <button
        v-if="!isHub"
        type="button"
        class="w-9 h-11 -ml-1 flex items-center justify-center rounded-md text-content-secondary border-none bg-transparent"
        aria-label="Back"
        @click="back"
      >
        <ChevronLeftIcon class="w-6 h-6" />
      </button>

      <button
        v-if="isLibrary"
        type="button"
        class="flex-1 min-w-0 h-11 px-1 flex items-center gap-1 text-left border-none bg-transparent"
        aria-label="Assets scope"
        @click="scopeOpen = true"
      >
        <span class="min-w-0">
          <span class="block truncate text-[17px] font-semibold tracking-tight text-content leading-tight">{{ title }}</span>
          <span v-if="subtitle" class="block truncate text-[11px] font-mono text-content-tertiary leading-tight">{{ subtitle }}</span>
        </span>
        <ChevronDownIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" />
      </button>
      <div v-else class="flex-1 min-w-0 px-1">
        <h1 class="truncate text-[17px] font-semibold tracking-tight text-content leading-tight">{{ title }}</h1>
        <p v-if="subtitle" class="truncate text-[11px] font-mono text-content-tertiary leading-tight">{{ subtitle }}</p>
      </div>

      <!-- Transient: only while there is work or something to look at. -->
      <button
        v-if="isHub && hasActiveWork"
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md border-none bg-transparent"
        :aria-label="progressTitle"
        @click="workOpen = true"
      >
        <BackgroundWorkIndicator />
      </button>
      <!-- Provider managers (ComfyUI and friends), as on the desktop top bar. -->
      <ProviderManagerButton v-if="isHub" />

      <!-- Screens with a primary control (the tool view's Run) teleport it here. -->
      <div id="compact-header-actions" class="flex items-center gap-1 empty:hidden"></div>
      <button
        v-if="route.name !== 'search' && route.name !== 'tool'"
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md text-content-secondary border-none bg-transparent"
        aria-label="Search"
        @click="openSearch"
      >
        <MagnifyingGlassIcon class="w-6 h-6" />
      </button>
      <button
        v-if="primaryAction"
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md text-accent-hi bg-accent/15 border-none"
        :aria-label="primaryAction.label"
        @click="primaryAction.run()"
      >
        <PlusIcon class="w-6 h-6" />
      </button>
      <!-- Detail screens: the entity's menu (rename, ...). -->
      <button
        v-if="!isHub && menuItems.length"
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md text-content-secondary border-none bg-transparent"
        aria-label="More"
        @click="menuOpen = true"
      >
        <EllipsisVerticalIcon class="w-6 h-6" />
      </button>
    </div>


    <LibraryScopeSheet :show="scopeOpen" @close="scopeOpen = false" />
    <Sheet :show="menuOpen" @close="menuOpen = false">
      <div class="pb-2">
        <button
          v-for="item in menuItems"
          :key="item.label"
          type="button"
          class="sheet-row"
          :class="item.destructive ? '!text-red-400' : ''"
          @click="menuOpen = false; item.run()"
        >{{ item.label }}</button>
      </div>
    </Sheet>
    <Sheet :show="workOpen" title="Background work" @close="workOpen = false">
      <div class="px-4 pb-4">
        <BackgroundWorkPanel />
      </div>
    </Sheet>
  </header>
</template>
