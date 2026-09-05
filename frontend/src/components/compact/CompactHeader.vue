<script setup lang="ts">
/**
 * The 48px compact header (DESIGN.md §1.11): avatar or back chevron, title,
 * at most two actions. Hub routes show the avatar (account sheet) and search;
 * detail routes show a back chevron. Workspace-family routes carry the
 * Open / Tools / Flows / Stimpacks segmented control under the title row.
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronLeftIcon, MagnifyingGlassIcon, PlusIcon } from '@heroicons/vue/24/outline'
import { useAuth } from '../../composables/useAuth'
import { useCompactChrome } from '../../composables/useCompactChrome'
import { useCompactNav } from '../../composables/useCompactNav'
import AccountSheet from './AccountSheet.vue'

const emit = defineEmits<{ openSettings: [section: string] }>()

const route = useRoute()
const router = useRouter()
const { isHub, title, subtitle, workspaceSegments, primaryAction } = useCompactChrome(route)
const { user, isAuthenticated } = useAuth()

const accountInitial = computed(() => {
  const email = user.value?.email || ''
  return (email.charAt(0) || '').toUpperCase()
})

const accountOpen = ref(false)

const SEGMENTS = [
  { label: 'Open', to: '/workspace', names: ['workspace'] },
  { label: 'Tools', to: '/tools', names: ['all-tools'] },
  { label: 'Flows', to: '/flows', names: ['flows'] },
  { label: 'Stimpacks', to: '/stimpacks', names: ['stimpacks'] },
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
    <div class="h-12 flex items-center gap-1 px-2">
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

      <div class="flex-1 min-w-0 px-1">
        <h1 class="truncate text-[17px] font-semibold tracking-tight text-content leading-tight">{{ title }}</h1>
        <p v-if="subtitle" class="truncate text-[11px] font-mono text-content-tertiary leading-tight">{{ subtitle }}</p>
      </div>

      <button
        v-if="route.name !== 'search'"
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
  </header>
</template>
