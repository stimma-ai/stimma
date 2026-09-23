<template>
  <!-- Always present once signed in. It used to hide until the account had a
       second server, but a control that appears out of nowhere the day a
       friend's machine shows up teaches nobody anything: with no other
       servers, the menu explains the feature and says where to turn it on.

       Two triggers, one menu. `footer` is the everyday home: a 32px icon in
       the sidebar footer strip beside feedback and settings, because picking
       a server is rare and belongs with the other occasional actions, and
       because it leaves the account chip's name and balance untouched. The
       presence dot on its corner carries the state you actually need at a
       glance; the name lives in the tooltip and the menu. `chip` (name +
       dot) survives for the connection screen, which has no sidebar.

       The list itself is DeviceMenuList, shared with the compact account
       sheet. At the compact tier the menu is a bottom sheet (DESIGN.md
       §1.11): an absolute panel hanging off the drawer's footer is clipped
       by the drawer and dismissed by the same tap that closes anything
       else, which stranded phones with no way to disconnect. -->
  <div class="device-menu" :class="isFooter ? 'contents' : 'relative'">
    <!-- Same kit Tooltip as the feedback and settings buttons beside it, so
         the footer's hover behaviour is one thing, not two. -->
    <Tooltip v-if="isFooter" :text="`Server: ${activeLabel}`" class="w-8 flex-shrink-0">
      <button
        data-tour="device-chip"
        class="relative w-8 h-8 flex-shrink-0 flex items-center justify-center rounded text-content-tertiary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle border-none bg-transparent"
        :class="menuOpen ? 'text-content bg-overlay-subtle' : ''"
        @click="toggleMenu"
      >
        <svg class="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25" />
        </svg>
        <!-- Presence dot rides the icon's corner; ringed in surface so it reads
             as a badge rather than part of the glyph. -->
        <span
          class="absolute right-1 bottom-1 w-2 h-2 rounded-full ring-2 ring-surface"
          :class="statusDotClass"
        />
      </button>
    </Tooltip>

    <!-- Ghost trigger, matching the profile picker: bordered+filled chips
         aren't Atelier chrome; the menu carries the affordance. -->
    <button
      v-else
      data-tour="device-chip"
      class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
      @click="toggleMenu"
      :title="`Server: ${activeLabel}`"
    >
      <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="statusDotClass" />
      <span class="max-w-[140px] truncate">{{ activeLabel }}</span>
      <svg
        class="w-3 h-3 flex-shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="2"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <Sheet v-if="isCompact" :show="menuOpen" title="Server" @close="setMenuOpen(false)">
      <DeviceMenuList class="pb-2" @done="setMenuOpen(false)" />
    </Sheet>

    <transition v-else name="menu">
      <!-- Footer: opens upward and spans the footer's width. A 300px panel
           hanging off a 32px icon at the sidebar's right edge would clip
           against the window, so the panel anchors to the footer container
           (the `contents` wrapper makes that the positioning parent). -->
      <div
        v-if="menuOpen"
        class="absolute bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu overflow-hidden"
        :class="isFooter
          ? 'bottom-[calc(100%+0.375rem)] left-2 right-2 origin-bottom'
          : 'top-[calc(100%+0.5rem)] right-0 min-w-[300px]'"
        role="menu"
      >
        <DeviceMenuList @done="setMenuOpen(false)" />
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useMultiDevice, THIS_MACHINE_LABEL } from '../composables/useMultiDevice'
import { useViewport } from '../composables/useViewport'
import DeviceMenuList from './DeviceMenuList.vue'
import Sheet from './ui/Sheet.vue'
import Tooltip from './ui/Tooltip.vue'

const props = defineProps({
  /** `footer`: sidebar-footer icon with a presence dot, menu opens upward.
   *  `chip`: name + dot for surfaces without a sidebar (connection screen). */
  variant: { type: String, default: 'chip' },
})
const isFooter = computed(() => props.variant === 'footer')
const { isCompact } = useViewport()

const {
  activeDeviceName,
  isRemote,
  connectionState,
  selfServing,
  refresh,
} = useMultiDevice()

const menuOpen = ref(false)

/** What the trigger calls the active server: a remote by name, the seat by role. */
const activeLabel = computed(() => (isRemote.value ? activeDeviceName.value : THIS_MACHINE_LABEL))

// Status colours are status-only per the design language: blue-500 is never
// an interactive accent, so it is the right token for "connected". Teal on
// the local dot means "this install is serving", which is the one fact worth
// showing without opening Settings.
const statusDotClass = computed(() => {
  if (connectionState.value === 'unreachable') return 'bg-red-500'
  if (connectionState.value === 'connecting') return 'bg-amber-500'
  if (isRemote.value) return 'bg-blue-500'
  return selfServing.value ? 'bg-accent-hi' : 'bg-content-muted'
})

function toggleMenu() {
  setMenuOpen(!menuOpen.value)
}

// The connection screen's "Choose another server" link opens this same menu
// rather than growing a second picker.
function setMenuOpen(open) {
  menuOpen.value = open
}

defineExpose({ openMenu: () => setMenuOpen(true) })

function onDocumentClick(event) {
  // The teleported Sheet owns outside-tap dismissal; its backdrop is outside
  // .device-menu and must not double as a close for the menu it belongs to.
  if (isCompact.value) return
  if (!event.target.closest('.device-menu')) menuOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  void refresh()
})
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>
