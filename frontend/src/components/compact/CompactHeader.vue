<script setup lang="ts">
/**
 * The compact header (DESIGN.md §1.11): Menu (hubs) or Back (details), title,
 * and the right-hand strip. One contextual action per screen: a hub's create
 * button, a detail's entity menu (or the tool view's Run). Hubs also carry
 * what the desktop top bar's right side carries — the transient
 * background-work indicator, provider managers (ComfyUI) — and a quiet
 * Search. On a detail route Search lives in the entity menu. Where the
 * drawer can dock, the left button is the dock toggle. The Library hub's
 * title opens the scope sheet; Workspace hub routes carry the Tools / Flows /
 * Boards / Projects segmented control.
 * The working set (open tools, chats, boards, edits) is the tab bar's
 * trailing switcher control, not a header action.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronLeftIcon, EllipsisHorizontalIcon, MagnifyingGlassIcon, PlusIcon } from '@heroicons/vue/24/outline'
import Caret from '../ui/Caret.vue'
import { compactIcon, compactIconButton, compactIconButtonOn, compactPrimaryCreate, compactTitle } from './headerStyles'
import { useCompactChrome, hubForRoute } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'
import { useBackgroundWork } from '../../composables/useBackgroundWork'
import Sheet from '../ui/Sheet.vue'
import LibraryScopeSheet from './LibraryScopeSheet.vue'
import BackgroundWorkIndicator from '../BackgroundWorkIndicator.vue'
import BackgroundWorkPanel from '../BackgroundWorkPanel.vue'
import ProviderManagerButton from '../ProviderManagerButton.vue'

const props = withDefaults(defineProps<{
  /** The drawer is docked beside the app (roomy compact chrome). */
  sidebarDocked?: boolean
  /** The drawer could dock here; the menu button pins/unpins instead of opening. */
  sidebarDockable?: boolean
}>(), { sidebarDocked: false, sidebarDockable: false })
const emit = defineEmits<{ openSettings: [section: string]; openMenu: [] }>()
const menuLabel = computed(() => props.sidebarDockable ? (props.sidebarDocked ? 'Hide sidebar' : 'Show sidebar') : 'Menu')

const route = useRoute()
const router = useRouter()
const { isHub, title, subtitle, subtitleBrand, titleAction, primaryAction, menuItems } = useCompactChrome(route)
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

// Search is a quiet icon on hubs. A detail with an entity menu carries it in
// that menu instead, ahead of the destructive rows, so the strip holds one
// action. A detail without a menu keeps the icon. The tool view's strip is
// Agent and Run, so it has none.
const detailHasMenu = computed(() => !isHub.value && menuItems.value.length > 0)
// The Tools hub carries its own filter field, its one search entry; global
// search stays reachable from the other hubs.
const hasOwnSearchField = computed(() => route.name === 'all-tools')
const showSearchButton = computed(() => route.name !== 'search' && route.name !== 'tool' && !detailHasMenu.value && !hasOwnSearchField.value)
const sheetItems = computed(() => {
  const items = [...menuItems.value]
  if (route.name === 'search') return items
  const at = items.findIndex((i) => i.destructive)
  const search = { label: 'Search', run: openSearch, destructive: false }
  items.splice(at < 0 ? items.length : at, 0, search)
  return items
})
</script>

<template>
  <header class="compact-header flex-none bg-surface pt-safe">
    <div class="h-header-mobile flex items-center gap-0.5 px-page">
      <!-- Left slot: the Menu (drawer) on every screen, as the multitasking
           switcher; a detail adds Back beside it. Where the drawer can dock,
           the Menu button is the dock toggle instead. -->
      <button
        type="button"
        :class="[compactIconButton, sidebarDockable && sidebarDocked ? compactIconButtonOn : '']"
        :aria-label="menuLabel"
        :aria-pressed="sidebarDockable ? sidebarDocked : undefined"
        @click="emit('openMenu')"
      >
        <svg v-if="sidebarDockable" :class="compactIcon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="2.5" y="4" width="15" height="12" rx="2" />
          <path d="M7.5 4v12" />
        </svg>
        <svg v-else :class="[compactIcon, '-translate-x-[3px]']" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true">
          <path d="M3 7h14M3 13h9" />
        </svg>
      </button>
      <button
        v-if="!isHub"
        type="button"
        :class="compactIconButton"
        aria-label="Back"
        @click="back"
      >
        <ChevronLeftIcon :class="[compactIcon, '-translate-x-1.5']" />
      </button>

      <button
        v-if="isLibrary"
        type="button"
        class="flex-1 min-w-[96px] h-11 px-1 flex items-center gap-1 text-left border-none bg-transparent overflow-hidden"
        aria-label="Assets scope"
        @click="scopeOpen = true"
      >
        <span class="min-w-0">
          <span class="block truncate" :class="compactTitle">{{ title }}</span>
          <span v-if="subtitle" class="block truncate text-[11px] text-content-tertiary leading-snug">{{ subtitle }}</span>
        </span>
        <Caret class="text-content-tertiary" />
      </button>
      <button v-else-if="titleAction" type="button" class="flex flex-1 min-w-[96px] h-11 px-1 items-center text-left border-none bg-transparent overflow-hidden" :aria-label="`Rename ${title}`" :title="title" @click="titleAction()">
        <h1 class="block min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap" :class="compactTitle">{{ title }}</h1>
      </button>
      <div v-else class="flex-1 min-w-[96px] overflow-hidden px-1">
        <h1 v-if="title" :title="title" class="truncate" :class="compactTitle">{{ title }}</h1>
        <p v-if="subtitle" class="truncate text-[11px] leading-snug" :class="subtitleBrand ? 'stimma-cloud-text font-medium' : 'text-content-tertiary'">{{ subtitle }}</p>
      </div>

      <!-- Transient: only while there is work or something to look at. -->
      <button
        v-if="isHub && hasActiveWork"
        type="button"
        :class="compactIconButton"
        :aria-label="progressTitle"
        @click="workOpen = true"
      >
        <BackgroundWorkIndicator />
      </button>
      <!-- Provider managers (ComfyUI and friends), as on the desktop top bar. -->
      <ProviderManagerButton v-if="isHub" />

      <!-- Screens with a primary control (the tool view's Run) teleport it here. -->
      <div id="compact-header-actions" class="flex flex-none items-center gap-1 empty:hidden"></div>
      <button
        v-if="showSearchButton"
        type="button"
        :class="compactIconButton"
        aria-label="Search"
        @click="openSearch"
      >
        <MagnifyingGlassIcon :class="compactIcon" />
      </button>
      <button
        v-if="primaryAction"
        type="button"
        :class="[compactIconButton, compactPrimaryCreate]"
        :aria-label="primaryAction.label"
        @click="primaryAction.run()"
      >
        <PlusIcon :class="compactIcon" />
      </button>
      <!-- Detail screens: the entity's menu (rename, ...). -->
      <button
        v-if="!isHub && menuItems.length"
        type="button"
        :class="compactIconButton"
        aria-label="More"
        @click="menuOpen = true"
      >
        <EllipsisHorizontalIcon :class="compactIcon" />
      </button>
    </div>


    <LibraryScopeSheet :show="scopeOpen" @close="scopeOpen = false" />
    <Sheet :show="menuOpen" @close="menuOpen = false">
      <div class="pb-2">
        <button
          v-for="item in sheetItems"
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
