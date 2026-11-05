<template>
  <div class="w-52 flex-shrink-0 border-r border-edge py-3 flex flex-col overflow-y-auto">
    <nav class="flex flex-col gap-0.5 px-3 flex-1">
      <!-- Profile header with dropdown -->
      <div class="relative mb-2">
        <button
          @click="showProfileDropdown = !showProfileDropdown"
          class="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-content-secondary hover:text-content-tertiary transition-colors"
        >
          <span>{{ currentProfileName }}</span>
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <!-- Dropdown menu -->
        <div
          v-if="showProfileDropdown"
          class="absolute z-menu top-full left-3 mt-1 bg-surface border border-edge rounded-lg shadow-xl py-1 min-w-[140px] max-h-48 overflow-auto"
        >
          <button
            v-for="profile in profiles"
            :key="profile.id"
            @click="switchProfile(profile.id)"
            class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-surface-hover transition-colors"
            :class="profile.id === currentProfileId ? 'text-accent-hi' : 'text-content-secondary'"
          >
            <svg v-if="profile.id === currentProfileId" class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
            </svg>
            <span v-else class="w-4"></span>
            <span class="truncate">{{ profile.name }}</span>
          </button>
        </div>
      </div>

      <!-- Profile-scoped items -->
      <button
        v-for="section in profileSections"
        :key="section.id"
        @click="$emit('select', section.id)"
        :class="[navItemClass, activeSection === section.id ? navActiveClass : navIdleClass]"
      >
        <component :is="section.icon" class="w-icon-nav h-icon-nav shrink-0" :class="activeSection === section.id ? 'text-selection' : ''" />
        <span class="flex min-w-0 flex-1 items-center gap-2">
          <span>{{ section.label }}</span>
          <span v-if="section.id === 'mcp'" class="shrink-0 rounded border border-edge-subtle px-1 py-0.5 text-[10px] font-normal leading-none text-content-tertiary">Experimental</span>
        </span>
      </button>

      <!-- Global sections -->
      <template v-for="group in globalSectionGroups" :key="group.label">
        <div class="mb-2 mt-4 px-3 py-1">
          <span class="text-xs font-semibold text-content-secondary">{{ group.label }}</span>
        </div>

        <button
          v-for="section in group.sections"
          :key="section.id"
          @click="$emit('select', section.id)"
          :class="[navItemClass, activeSection === section.id ? navActiveClass : navIdleClass]"
        >
          <component
            :is="section.icon"
            class="h-icon-nav w-icon-nav shrink-0"
            :class="section.branded ? 'text-cyan-600 dark:text-cyan-400' : activeSection === section.id ? 'text-selection' : ''"
          />
          <span
            class="whitespace-nowrap"
            :class="section.branded ? 'bg-gradient-to-r from-teal-700 via-cyan-600 to-indigo-600 bg-clip-text text-transparent dark:from-teal-500 dark:via-cyan-400 dark:to-indigo-400' : ''"
          >{{ section.label }}</span>
          <span
            v-if="sectionNeedsSetup(section.id)"
            class="ml-auto h-2 w-2 shrink-0 rounded-full bg-amber-400"
            :title="section.id === 'ai-services' ? 'Chat model setup required' : 'Generation provider setup required'"
          ></span>
        </button>
      </template>

    </nav>

    <!-- Bottom area: easter egg click target / Developer button -->
    <div
      class="flex-shrink-0 px-3 pb-2"
      @click="handleEasterEggClick"
    >
      <button
        v-if="showDeveloper"
        @click.stop="$emit('select', 'developer')"
        :class="[navItemClass, 'w-full', activeSection === 'developer' ? navActiveClass : navIdleClass]"
      >
        <component :is="CodeBracketIcon" class="w-icon-nav h-icon-nav shrink-0" :class="activeSection === 'developer' ? 'text-selection' : ''" />
        <span>Developer</span>
      </button>
      <div v-else class="h-10 cursor-default select-none" />
    </div>
    <div class="pointer-events-none sticky bottom-0 h-8 flex-none bg-gradient-to-t from-surface to-transparent" aria-hidden="true"></div>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { devModeRef } from '../../appConfig'
import { ChatBubbleBottomCenterTextIcon, LinkIcon, WrenchScrewdriverIcon } from '@heroicons/vue/24/outline'
// Monochrome Stimma pinwheel (logo.svg as a currentColor mask), matching the
// treatment on the Generation Tools and Chat Models screens.
const AccountIcon = () => h('span', {
  'aria-hidden': 'true',
  class: "block bg-current [mask-image:url('/logo.svg')] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url('/logo.svg')] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]",
})

const props = defineProps({
  activeSection: {
    type: String,
    required: true
  },
  profiles: {
    type: Array,
    default: () => []
  },
  currentProfileId: {
    type: String,
    default: ''
  },
  llmSetupRequired: {
    type: Boolean,
    default: false
  },
  generationSetupRequired: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['select', 'switch-profile'])

// One nav-row treatment: row-sized text (13px, 15px on compact like every
// other row), selection = the indigo wash DESIGN.md §1.8 prescribes.
const navItemClass = 'flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors compact:min-h-11 compact:text-[15px]'
const navActiveClass = 'bg-selection/15 text-content'
const navIdleClass = 'text-content-tertiary hover:bg-overlay-subtle hover:text-content'

const showProfileDropdown = ref(false)

const currentProfileName = computed(() => {
  const profile = props.profiles.find(p => p.id === props.currentProfileId)
  return profile?.name || 'Select profile'
})

function switchProfile(profileId) {
  showProfileDropdown.value = false
  if (profileId !== props.currentProfileId) {
    emit('switch-profile', profileId)
  }
}

function sectionNeedsSetup(sectionId) {
  if (sectionId === 'ai-services') return props.llmSetupRequired
  if (sectionId === 'tools') return props.generationSetupRequired
  return false
}

// Close dropdown when clicking outside
function handleClickOutside(e) {
  if (showProfileDropdown.value && !e.target.closest('.relative')) {
    showProfileDropdown.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

// Icon components as render functions
const FolderIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z' })
])

const TagIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z' }),
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M6 6h.008v.008H6V6z' })
])

const CpuIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z' })
])

const UserIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z' })
])

const AdjustmentsIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75' })
])

const ShieldCheckIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9 12.75 11.25 15 15 9.75' }),
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M12 21.75c5.176-1.333 9-6.03 9-11.623 0-1.31-.21-2.57-.598-3.75A11.959 11.959 0 0 1 12 3.09a11.959 11.959 0 0 1-8.402 3.286A11.99 11.99 0 0 0 3 10.127c0 5.592 3.824 10.29 9 11.623Z' })
])

const InformationCircleIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'm11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z' })
])

// The agent glyph (components/icons/AgentIcon.vue), as a render function for this nav.
const AgentGlyph = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
  h('path', { d: 'M12 8V4H8' }),
  h('rect', { width: '16', height: '12', x: '4', y: '8', rx: '2' }),
  h('path', { d: 'M2 14h2M20 14h2M15 13v2M9 13v2' })
])

const CodeBracketIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5' })
])

// Easter egg: click blank area 10 times to reveal Developer section
const easterEggClicks = ref(0)
const easterEggRevealed = ref(false)
let easterEggTimer = null

const showDeveloper = computed(() => easterEggRevealed.value || devModeRef.value)

function handleEasterEggClick() {
  if (showDeveloper.value) return
  easterEggClicks.value++
  clearTimeout(easterEggTimer)
  if (easterEggClicks.value >= 10) {
    easterEggRevealed.value = true
    emit('select', 'developer')
  } else {
    easterEggTimer = setTimeout(() => {
      easterEggClicks.value = 0
    }, 3000)
  }
}

// Profile-scoped sections (depends on current profile)
const WildcardIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('rect', { x: '5', y: '2', width: '14', height: '20', rx: '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }),
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M10 9.5a2 2 0 1 1 2.6 1.91c-.37.12-.6.48-.6.87V13' }),
  h('circle', { cx: '12', cy: '15.5', r: '1', fill: 'currentColor', stroke: 'none' })
])

// Desktop glyph, the same one the server picker uses in the sidebar footer.
const ServerIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25' })
])

// Plug glyph: MCP is about connecting an assistant, not a machine.
const PlugIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9 3v4.5M15 3v4.5M6.75 7.5h10.5v3a5.25 5.25 0 0 1-10.5 0v-3ZM12 15.75V21' })
])

const BookOpenIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25' })
])

const profileSections = [
  { id: 'folders', label: 'Folders', icon: FolderIcon },
  { id: 'markers', label: 'Markers', icon: TagIcon },
  { id: 'wildcards', label: 'Prompt variables', icon: WildcardIcon },
  { id: 'agent', label: 'Agent', icon: AgentGlyph },
  { id: 'mcp', label: 'MCP', icon: PlugIcon },
]

// Global settings (applies to all profiles)
const globalSectionGroups = [
  {
    label: 'App',
    sections: [
      { id: 'account', label: 'Stimma account', icon: AccountIcon },
      { id: 'shared-links', label: 'Shared links', icon: LinkIcon },
      { id: 'server', label: 'Stimma server', icon: ServerIcon },
      { id: 'tools', label: 'Generation tools', icon: WrenchScrewdriverIcon },
      { id: 'ai-services', label: 'Chat models', icon: ChatBubbleBottomCenterTextIcon },
      { id: 'model-preferences', label: 'Preferences', icon: AdjustmentsIcon },
      { id: 'profiles', label: 'Profiles', icon: UserIcon },
      { id: 'background', label: 'Background work', icon: CpuIcon },
      { id: 'stimpacks', label: 'Stimpacks', icon: BookOpenIcon },
      { id: 'privacy', label: 'Privacy', icon: ShieldCheckIcon },
      { id: 'updates', label: 'About', icon: InformationCircleIcon },
    ],
  },
]
</script>
