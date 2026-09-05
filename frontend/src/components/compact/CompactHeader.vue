<script setup lang="ts">
/**
 * The compact header (DESIGN.md §1.11): avatar or back chevron, title, and
 * the right-hand strip. Hubs carry what the desktop top bar's right side
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
import { useAuth } from '../../composables/useAuth'
import { useCompactChrome, hubForRoute } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'
import { useBackgroundWork } from '../../composables/useBackgroundWork'
import Sheet from '../ui/Sheet.vue'
import AccountSheet from './AccountSheet.vue'
import LibraryScopeSheet from './LibraryScopeSheet.vue'
import BackgroundWorkIndicator from '../BackgroundWorkIndicator.vue'
import BackgroundWorkPanel from '../BackgroundWorkPanel.vue'
import ProviderManagerButton from '../ProviderManagerButton.vue'

const emit = defineEmits<{ openSettings: [section: string] }>()

const route = useRoute()
const router = useRouter()
const { isHub, title, subtitle, workspaceSegments, primaryAction, menuItems } = useCompactChrome(route)
const { user, isAuthenticated } = useAuth()
const backgroundWork = useBackgroundWork()
const { hasActiveWork, progressTitle } = backgroundWork
onMounted(() => backgroundWork.start())

const accountInitial = computed(() => {
  const email = user.value?.email || ''
  return (email.charAt(0) || '').toUpperCase()
})

const accountOpen = ref(false)
const scopeOpen = ref(false)
const workOpen = ref(false)
const menuOpen = ref(false)

// The Assets hub's title is a scope control: All assets, saved views, upload, trash.
const isLibrary = computed(() => isHub.value && hubForRoute(route.name) === 'library')

const SEGMENTS = [
  { label: 'Tools', to: '/tools', names: ['all-tools'] },
  { label: 'Flows', to: '/flows', names: ['flows'] },
  { label: 'Boards', to: '/boards', names: ['boards'] },
  { label: 'Projects', to: '/projects', names: ['projects'] },
]
const activeSegment = computed(() => SEGMENTS.find((s) => s.names.includes(String(route.name))) ?? null)

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
      <button
        v-if="isHub"
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md border-none bg-transparent"
        aria-label="Account and settings"
        @click="accountOpen = true"
      >
        <span
          class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold text-white"
          :class="isAuthenticated ? 'bg-gradient-to-br from-teal-600 via-cyan-500 to-indigo-500' : 'bg-overlay-light text-content-secondary'"
        >{{ isAuthenticated ? accountInitial : '' }}</span>
      </button>
      <button
        v-else
        type="button"
        class="w-11 h-11 flex items-center justify-center rounded-md text-content-secondary border-none bg-transparent"
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

    <div v-if="workspaceSegments" class="px-3 pb-2">
      <div class="flex gap-0.5 p-0.5 rounded-md bg-overlay-subtle" role="tablist">
        <button
          v-for="seg in SEGMENTS"
          :key="seg.label"
          type="button"
          role="tab"
          class="flex-1 h-11 rounded-md text-[13px] font-medium border-none bg-transparent transition-colors"
          :class="activeSegment === seg ? 'bg-accent/15 text-accent-hi' : 'text-content-tertiary'"
          :aria-selected="activeSegment === seg"
          @click="router.push(seg.to)"
        >{{ seg.label }}</button>
      </div>
    </div>

    <AccountSheet :show="accountOpen" @close="accountOpen = false" @open-settings="(s) => { accountOpen = false; emit('openSettings', s) }" />
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
