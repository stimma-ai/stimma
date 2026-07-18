<template>
  <div class="relative" ref="containerRef">
    <!-- Split button: always a contained control (a split dropdown needs a
         body); idle = secondary, armed = accent wash. -->
    <div
      :class="[
        'flex rounded-md overflow-hidden transition-colors',
        isActive ? 'bg-accent/15 ring-1 ring-accent/40' : 'bg-surface-raised'
      ]"
    >
      <!-- Main button (start/stop) -->
      <button
        @click="handleMainClick"
        :class="[
          'px-3 py-2 text-sm font-semibold cursor-pointer transition-colors',
          isActive ? 'text-accent-hi hover:bg-accent/20' : 'text-content-secondary hover:bg-surface-hover hover:text-content'
        ]"
        :title="isActive ? 'Stop forever mode' : 'Start forever mode'"
      >
        ∞
      </button>

      <!-- Divider -->
      <div :class="['w-px', isActive ? 'bg-accent/30' : 'bg-edge']"></div>

      <!-- Dropdown chevron (settings) -->
      <button
        @click.stop="handleChevronClick"
        :class="[
          'px-2 py-2 cursor-pointer transition-colors flex items-center',
          isActive ? 'text-accent-hi hover:bg-accent/20' : 'text-content-secondary hover:bg-surface-hover hover:text-content'
        ]"
        title="Forever mode settings"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
    </div>

    <!-- Settings Popover -->
    <div
      v-if="showPopover"
      class="absolute right-0 mt-2 w-72 bg-surface border border-surface-raised rounded-lg shadow-lg z-menu"
      @click.stop
    >
      <!-- Header -->
      <div class="px-4 py-3 border-b border-surface-raised">
        <div class="font-medium text-content">Forever Mode Settings</div>
        <p class="text-xs text-content-tertiary mt-1">
          Continuously generates images with randomized seeds until you stop it.
        </p>
      </div>

      <!-- Stimma Cloud Credits Warning -->
      <div v-if="isStimmaCloud" class="px-4 py-3 bg-[#6366f1]/10 border-b border-surface-raised flex gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 text-indigo-600 dark:text-[#8b5cf6] flex-shrink-0 mt-0.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <p class="text-xs text-indigo-700 dark:text-[#a5b4fc]">
          This can use significant <span class="stimma-cloud-text font-medium">Stimma credits</span> if left running. Monitor your usage.
        </p>
      </div>

      <!-- Concurrency Setting -->
      <div class="px-4 py-3">
        <label class="text-xs text-content-tertiary block mb-2">Max concurrent jobs</label>
        <select
          v-model="localConcurrency"
          @change="handleConcurrencyChange"
          class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-accent"
        >
          <option v-for="option in concurrencyOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <!-- Auto-stop Setting -->
      <div class="px-4 py-3 border-t border-surface-raised">
        <label class="text-xs text-content-tertiary block mb-2">Auto-stop after</label>
        <select
          v-model="localIdleLimit"
          @change="handleIdleLimitChange"
          class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-accent"
        >
          <option v-for="option in idleLimitOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <p class="text-xs text-content-muted mt-2">
          Auto-stops if no changes are made to the prompt or settings.
        </p>
      </div>

      <!-- Actions -->
      <div class="px-4 py-3 border-t border-surface-raised flex justify-end">
        <button
          @click="showPopover = false"
          class="px-3 py-1.5 text-sm text-content-tertiary hover:text-content transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

interface Props {
  isActive: boolean
  concurrency: number
  idleLimit: number
  isStimmaCloud?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'start', concurrency: number): void
  (e: 'update:concurrency', value: number): void
  (e: 'update:idleLimit', value: number): void
}>()

const showPopover = ref(false)
const containerRef = ref<HTMLElement | null>(null)
const localConcurrency = ref(props.concurrency)
const localIdleLimit = ref(props.idleLimit)

// Sync local values when props change
watch(() => props.concurrency, (newVal) => {
  localConcurrency.value = newVal
})
watch(() => props.idleLimit, (newVal) => {
  localIdleLimit.value = newVal
})

const concurrencyOptions = computed(() => {
  const options = [
    { label: 'Unlimited', value: 0 },
  ]
  for (let i = 1; i <= 10; i++) {
    options.push({ label: `${i}`, value: i })
  }
  return options
})

const idleLimitOptions = [
  { label: '10 images', value: 10 },
  { label: '20 images', value: 20 },
  { label: '50 images', value: 50 },
  { label: '100 images', value: 100 },
  { label: '250 images', value: 250 },
  { label: '500 images', value: 500 },
  { label: '1000 images', value: 1000 },
  { label: 'No limit', value: 0 },
]

function handleMainClick() {
  if (props.isActive) {
    // If active, stop forever mode
    emit('toggle')
  } else {
    // If not active, start immediately with current concurrency
    emit('start', props.concurrency)
  }
}

function handleChevronClick() {
  localConcurrency.value = props.concurrency
  localIdleLimit.value = props.idleLimit
  showPopover.value = !showPopover.value
}

function handleConcurrencyChange() {
  emit('update:concurrency', localConcurrency.value)
}

function handleIdleLimitChange() {
  emit('update:idleLimit', localIdleLimit.value)
}

// Close popover when clicking outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  if (showPopover.value && containerRef.value && !containerRef.value.contains(target)) {
    showPopover.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
