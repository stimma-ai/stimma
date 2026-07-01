<template>
  <div class="w-52 flex-shrink-0 border-r border-edge py-4 flex flex-col">
    <nav class="flex flex-col gap-0.5 px-3 flex-1">
      <!-- Profile header with dropdown -->
      <div class="relative mb-2">
        <button
          @click="showProfileDropdown = !showProfileDropdown"
          class="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-content-muted uppercase tracking-wider hover:text-content-tertiary transition-colors"
        >
          <span>{{ currentProfileName }}</span>
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <!-- Dropdown menu -->
        <div
          v-if="showProfileDropdown"
          class="absolute z-10 top-full left-3 mt-1 bg-surface border border-edge rounded-lg shadow-xl py-1 min-w-[140px] max-h-48 overflow-auto"
        >
          <button
            v-for="profile in profiles"
            :key="profile.id"
            @click="switchProfile(profile.id)"
            class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-surface-hover transition-colors"
            :class="profile.id === currentProfileId ? 'text-blue-500' : 'text-content-secondary'"
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
        class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer"
        :class="activeSection === section.id
          ? 'bg-overlay-light text-content'
          : 'text-content-tertiary hover:text-content hover:bg-overlay-hover'"
      >
        <component :is="section.icon" class="w-5 h-5" />
        <span>{{ section.label }}</span>
      </button>

      <!-- Settings header -->
      <div class="px-3 py-1 mt-4 mb-2">
        <span class="text-xs font-semibold text-content-muted uppercase tracking-wider">Settings</span>
      </div>

      <!-- Global settings items -->
      <button
        v-for="section in globalSections"
        :key="section.id"
        @click="$emit('select', section.id)"
        class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer"
        :class="[
          activeSection === section.id
            ? 'bg-overlay-light'
            : 'hover:bg-overlay-hover',
          section.branded
            ? (activeSection === section.id ? 'text-cyan-600 dark:text-cyan-300' : 'text-cyan-500/70 dark:text-cyan-400/70 hover:text-cyan-600 dark:hover:text-cyan-300')
            : (activeSection === section.id ? 'text-content' : 'text-content-tertiary hover:text-content')
        ]"
      >
        <component
          :is="section.icon"
          class="w-5 h-5"
          :class="section.branded ? 'text-cyan-600 dark:text-cyan-400' : ''"
        />
        <span
          :class="section.branded ? 'bg-gradient-to-r from-teal-700 via-cyan-600 to-indigo-600 dark:from-teal-500 dark:via-cyan-400 dark:to-indigo-400 bg-clip-text text-transparent' : ''"
        >{{ section.label }}</span>
      </button>

    </nav>

    <!-- Bottom area: easter egg click target / Developer button -->
    <div
      class="flex-shrink-0 px-3 pb-2"
      @click="handleEasterEggClick"
    >
      <button
        v-if="showDeveloper"
        @click.stop="$emit('select', 'developer')"
        class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer w-full"
        :class="activeSection === 'developer'
          ? 'bg-overlay-light text-content'
          : 'text-content-tertiary hover:text-content hover:bg-overlay-hover'"
      >
        <component :is="CodeBracketIcon" class="w-5 h-5" />
        <span>Developer</span>
      </button>
      <div v-else class="h-10 cursor-default select-none" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { devModeRef } from '../../appConfig'

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
  }
})

const emit = defineEmits(['select', 'switch-profile'])

const showProfileDropdown = ref(false)

const currentProfileName = computed(() => {
  const profile = props.profiles.find(p => p.id === props.currentProfileId)
  return profile?.name || 'Select Profile'
})

function switchProfile(profileId) {
  showProfileDropdown.value = false
  if (profileId !== props.currentProfileId) {
    emit('switch-profile', profileId)
  }
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

const WrenchIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z' })
])

const CpuIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z' })
])

const UserIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z' })
])

const UserCircleIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M17.982 18.725A7.488 7.488 0 0 0 12 15.75a7.488 7.488 0 0 0-5.982 2.975m11.963 0a9 9 0 1 0-11.963 0m11.963 0A8.966 8.966 0 0 1 12 21a8.966 8.966 0 0 1-5.982-2.275M15 9.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z' })
])

const CloudIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z' })
])

const CogIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z' }),
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z' })
])

const ShieldCheckIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9 12.75 11.25 15 15 9.75' }),
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M12 21.75c5.176-1.333 9-6.03 9-11.623 0-1.31-.21-2.57-.598-3.75A11.959 11.959 0 0 1 12 3.09a11.959 11.959 0 0 1-8.402 3.286A11.99 11.99 0 0 0 3 10.127c0 5.592 3.824 10.29 9 11.623Z' })
])

const ArrowDownTrayIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3' })
])

const SparklesIcon = () => h('svg', { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' }, [
  h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z' })
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

const profileSections = [
  { id: 'folders', label: 'Folders', icon: FolderIcon },
  { id: 'markers', label: 'Markers', icon: TagIcon },
  { id: 'wildcards', label: 'Prompt Variables', icon: WildcardIcon },
  { id: 'agent', label: 'Agent', icon: SparklesIcon },
]

// Global settings (applies to all profiles)
const globalSections = [
  { id: 'account', label: 'Stimma Cloud', icon: CloudIcon, branded: true },
  { id: 'profiles', label: 'Profiles', icon: UserIcon },
  { id: 'privacy', label: 'Privacy', icon: ShieldCheckIcon },
  { id: 'tools', label: 'Tools', icon: WrenchIcon },
  { id: 'updates', label: 'Updates', icon: ArrowDownTrayIcon },
  { id: 'background', label: 'Background Work', icon: CpuIcon },
  { id: 'ai-services', label: 'Advanced', icon: CogIcon },
]
</script>
