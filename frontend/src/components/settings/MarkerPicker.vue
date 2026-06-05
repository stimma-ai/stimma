<template>
  <div class="relative" ref="container">
    <!-- Trigger button showing icon in color -->
    <button
      @click="toggleOpen"
      class="w-8 h-8 flex items-center justify-center rounded-lg border border-edge hover:border-edge transition-colors"
      :style="{ backgroundColor: color + '20' }"
      :title="`${iconRef} - ${color}`"
    >
      <component
        :is="currentIconComponent"
        v-if="currentIconComponent"
        class="w-5 h-5"
        :style="{ color: color }"
      />
      <span v-else class="text-xs" :style="{ color: color }">?</span>
    </button>

    <!-- Dropdown picker -->
    <Teleport to="body">
      <div
        v-if="isOpen"
        class="fixed z-[10020] bg-surface border border-edge rounded-lg shadow-xl"
        :style="dropdownStyle"
      >
        <!-- Preview header -->
        <div class="px-4 py-3 border-b border-edge flex items-center gap-3">
          <div
            class="w-10 h-10 flex items-center justify-center rounded-lg"
            :style="{ backgroundColor: localColor + '20' }"
          >
            <component
              :is="previewIconComponent"
              v-if="previewIconComponent"
              class="w-6 h-6"
              :style="{ color: localColor }"
            />
          </div>
          <div class="text-sm text-content-tertiary">Preview</div>
        </div>

        <div class="p-4 space-y-4">
          <!-- Icon section -->
          <div>
            <label class="block text-xs text-content-tertiary font-medium mb-2">Icon</label>
            <div class="grid grid-cols-8 gap-1.5 max-h-36 overflow-y-auto p-0.5 -m-0.5">
              <button
                v-for="icon in availableIcons"
                :key="icon.ref"
                @click="selectIcon(icon.ref)"
                class="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-hover transition-colors"
                :class="{ 'bg-blue-500/20 ring-1 ring-blue-500': localIcon === icon.ref }"
                :title="icon.name"
              >
                <component :is="getIconComponent(icon.ref)" class="w-5 h-5 text-content-tertiary" />
              </button>
            </div>
            <!-- Custom SVG inline -->
            <div v-if="showCustomSvg" class="mt-2 flex gap-2" @click.stop>
              <input
                v-model="customSvg"
                type="text"
                placeholder="Paste SVG code..."
                class="flex-1 bg-surface-raised/50 border border-edge rounded-md px-2 py-1 text-xs text-content placeholder-content-muted focus:outline-none focus:border-blue-500"
                @keydown.stop
                @keydown.enter="applyCustomSvg"
              />
              <button
                @click="applyCustomSvg"
                :disabled="!customSvg.trim().startsWith('<svg')"
                class="px-2 py-1 text-xs text-content-tertiary hover:text-content disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Apply
              </button>
            </div>
            <button
              v-else
              @click.stop="showCustomSvg = true"
              class="mt-1.5 text-xs text-content-muted hover:text-content-tertiary transition-colors"
            >
              or paste custom SVG...
            </button>
          </div>

          <!-- Color section -->
          <div>
            <div class="flex items-center justify-between mb-2">
              <label class="text-xs text-content-tertiary font-medium">Color</label>
              <button
                @click="showColorSliders = !showColorSliders"
                class="text-xs text-content-muted hover:text-content-secondary flex items-center gap-1 transition-colors"
              >
                <span>Custom</span>
                <ChevronDownIcon
                  class="w-3.5 h-3.5 transition-transform"
                  :class="{ 'rotate-180': showColorSliders }"
                />
              </button>
            </div>
            <div class="flex gap-1.5 flex-wrap">
              <button
                v-for="c in presetColors"
                :key="c"
                @click="selectColor(c)"
                class="w-6 h-6 rounded-full border-2 transition-all flex-shrink-0"
                :class="localColor.toLowerCase() === c.toLowerCase() ? 'border-white scale-110' : 'border-transparent hover:scale-110'"
                :style="{ backgroundColor: c }"
              ></button>
            </div>

            <!-- HSV sliders (collapsible) -->
            <div v-if="showColorSliders" class="mt-3 space-y-2 pt-3 border-t border-edge">
              <div>
                <div class="flex justify-between text-xs text-content-muted mb-1">
                  <span>Hue</span>
                  <span>{{ Math.round(hsv.h) }}°</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="360"
                  :value="hsv.h"
                  @input="updateHue($event.target.value)"
                  class="w-full h-2 rounded-lg appearance-none cursor-pointer"
                  :style="hueSliderStyle"
                />
              </div>
              <div>
                <div class="flex justify-between text-xs text-content-muted mb-1">
                  <span>Saturation</span>
                  <span>{{ Math.round(hsv.s * 100) }}%</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  :value="hsv.s * 100"
                  @input="updateSaturation($event.target.value / 100)"
                  class="w-full h-2 rounded-lg appearance-none cursor-pointer"
                  :style="satSliderStyle"
                />
              </div>
              <div>
                <div class="flex justify-between text-xs text-content-muted mb-1">
                  <span>Brightness</span>
                  <span>{{ Math.round(hsv.v * 100) }}%</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  :value="hsv.v * 100"
                  @input="updateValue($event.target.value / 100)"
                  class="w-full h-2 rounded-lg appearance-none cursor-pointer"
                  :style="valSliderStyle"
                />
              </div>
            </div>
          </div>

        </div>

        <!-- Footer -->
        <div class="px-4 py-3 border-t border-edge flex justify-end gap-2">
          <button
            @click="cancel"
            class="px-3 py-1.5 bg-surface-raised hover:bg-surface-hover text-content text-sm rounded-md font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            @click="apply"
            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-md font-medium transition-colors"
          >
            Apply
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import * as SolidIcons from '@heroicons/vue/24/solid'
import { ChevronDownIcon } from '@heroicons/vue/20/solid'

const props = defineProps({
  iconRef: {
    type: String,
    default: 'heroicons:tag'
  },
  color: {
    type: String,
    default: '#ef4444'
  }
})

const emit = defineEmits(['update:iconRef', 'update:color', 'change'])

const container = ref(null)
const isOpen = ref(false)
const dropdownStyle = ref({})
const customSvg = ref('')
const showColorSliders = ref(false)
const showCustomSvg = ref(false)

// Local state for editing
const localIcon = ref(props.iconRef)
const localColor = ref(props.color)

// HSV state
const hsv = ref({ h: 0, s: 1, v: 1 })

// Sync props to local state
watch(() => props.iconRef, (val) => { localIcon.value = val })
watch(() => props.color, (val) => {
  localColor.value = val
  hsv.value = hexToHsv(val)
})

// Initialize HSV from color
onMounted(() => {
  hsv.value = hexToHsv(props.color)
})

// Expanded icon list with solid variants
const availableIcons = [
  // Common
  { name: 'Heart', ref: 'heroicons:heart' },
  { name: 'Star', ref: 'heroicons:star' },
  { name: 'Bookmark', ref: 'heroicons:bookmark' },
  { name: 'Flag', ref: 'heroicons:flag' },
  { name: 'Tag', ref: 'heroicons:tag' },
  // Status
  { name: 'Check Circle', ref: 'heroicons:check-circle' },
  { name: 'X Circle', ref: 'heroicons:x-circle' },
  { name: 'Exclamation Circle', ref: 'heroicons:exclamation-circle' },
  { name: 'Information Circle', ref: 'heroicons:information-circle' },
  { name: 'Question Mark Circle', ref: 'heroicons:question-mark-circle' },
  // Actions
  { name: 'Plus Circle', ref: 'heroicons:plus-circle' },
  { name: 'Minus Circle', ref: 'heroicons:minus-circle' },
  { name: 'Arrow Up Circle', ref: 'heroicons:arrow-up-circle' },
  { name: 'Arrow Down Circle', ref: 'heroicons:arrow-down-circle' },
  // Objects
  { name: 'Bell', ref: 'heroicons:bell' },
  { name: 'Clock', ref: 'heroicons:clock' },
  { name: 'Calendar', ref: 'heroicons:calendar' },
  { name: 'Camera', ref: 'heroicons:camera' },
  { name: 'Photo', ref: 'heroicons:photo' },
  { name: 'Film', ref: 'heroicons:film' },
  { name: 'Video Camera', ref: 'heroicons:video-camera' },
  { name: 'Microphone', ref: 'heroicons:microphone' },
  { name: 'Musical Note', ref: 'heroicons:musical-note' },
  // Communication
  { name: 'Chat', ref: 'heroicons:chat-bubble-left' },
  { name: 'Chat Dots', ref: 'heroicons:chat-bubble-left-ellipsis' },
  { name: 'Envelope', ref: 'heroicons:envelope' },
  { name: 'Phone', ref: 'heroicons:phone' },
  // Files & Storage
  { name: 'Document', ref: 'heroicons:document' },
  { name: 'Document Text', ref: 'heroicons:document-text' },
  { name: 'Folder', ref: 'heroicons:folder' },
  { name: 'Folder Open', ref: 'heroicons:folder-open' },
  { name: 'Archive Box', ref: 'heroicons:archive-box' },
  { name: 'Inbox', ref: 'heroicons:inbox' },
  { name: 'Cloud', ref: 'heroicons:cloud' },
  // People & Body
  { name: 'User', ref: 'heroicons:user' },
  { name: 'User Circle', ref: 'heroicons:user-circle' },
  { name: 'Users', ref: 'heroicons:users' },
  { name: 'Hand Thumb Up', ref: 'heroicons:hand-thumb-up' },
  { name: 'Hand Thumb Down', ref: 'heroicons:hand-thumb-down' },
  { name: 'Hand Raised', ref: 'heroicons:hand-raised' },
  { name: 'Eye', ref: 'heroicons:eye' },
  { name: 'Eye Slash', ref: 'heroicons:eye-slash' },
  // Nature
  { name: 'Sun', ref: 'heroicons:sun' },
  { name: 'Moon', ref: 'heroicons:moon' },
  { name: 'Fire', ref: 'heroicons:fire' },
  { name: 'Sparkles', ref: 'heroicons:sparkles' },
  { name: 'Bolt', ref: 'heroicons:bolt' },
  // Tools
  { name: 'Wrench', ref: 'heroicons:wrench' },
  { name: 'Cog', ref: 'heroicons:cog-6-tooth' },
  { name: 'Pencil', ref: 'heroicons:pencil' },
  { name: 'Scissors', ref: 'heroicons:scissors' },
  { name: 'Key', ref: 'heroicons:key' },
  { name: 'Lock Closed', ref: 'heroicons:lock-closed' },
  { name: 'Lock Open', ref: 'heroicons:lock-open' },
  // Symbols
  { name: 'Light Bulb', ref: 'heroicons:light-bulb' },
  { name: 'Trophy', ref: 'heroicons:trophy' },
  { name: 'Gift', ref: 'heroicons:gift' },
  { name: 'Cake', ref: 'heroicons:cake' },
  { name: 'Beaker', ref: 'heroicons:beaker' },
  { name: 'Puzzle', ref: 'heroicons:puzzle-piece' },
  { name: 'Cube', ref: 'heroicons:cube' },
  { name: 'Shield Check', ref: 'heroicons:shield-check' },
  { name: 'Globe', ref: 'heroicons:globe-alt' },
  { name: 'Map Pin', ref: 'heroicons:map-pin' },
  { name: 'Home', ref: 'heroicons:home' },
  { name: 'Building', ref: 'heroicons:building-office' },
  // Arrows & Navigation
  { name: 'Arrow Right', ref: 'heroicons:arrow-right' },
  { name: 'Arrow Left', ref: 'heroicons:arrow-left' },
  { name: 'Chevron Right', ref: 'heroicons:chevron-right' },
  { name: 'Play', ref: 'heroicons:play' },
  { name: 'Pause', ref: 'heroicons:pause' },
  { name: 'Stop', ref: 'heroicons:stop' },
  // Misc
  { name: 'Trash', ref: 'heroicons:trash' },
  { name: 'Plus', ref: 'heroicons:plus' },
  { name: 'Minus', ref: 'heroicons:minus' },
  { name: 'Magnifying Glass', ref: 'heroicons:magnifying-glass' },
  { name: 'Funnel', ref: 'heroicons:funnel' },
  { name: 'Adjustments', ref: 'heroicons:adjustments-horizontal' },
  { name: 'Bars 3', ref: 'heroicons:bars-3' },
  { name: 'Squares', ref: 'heroicons:squares-2x2' },
  { name: 'QR Code', ref: 'heroicons:qr-code' },
  { name: 'Link', ref: 'heroicons:link' },
  { name: 'Paper Clip', ref: 'heroicons:paper-clip' },
  { name: 'Hashtag', ref: 'heroicons:hashtag' },
  { name: 'At Symbol', ref: 'heroicons:at-symbol' },
]

// Curated color palette - vibrant colors only
const presetColors = [
  '#ef4444', // red
  '#f97316', // orange
  '#eab308', // yellow
  '#22c55e', // green
  '#14b8a6', // teal
  '#06b6d4', // cyan
  '#3b82f6', // blue
  '#6366f1', // indigo
  '#8b5cf6', // violet
  '#d946ef', // fuchsia
  '#ec4899', // pink
]

// Map heroicon ref to solid component
function getIconComponent(iconRef) {
  if (!iconRef?.startsWith('heroicons:')) return null
  const iconName = iconRef.replace('heroicons:', '')
  const componentName = iconName
    .split('-')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join('') + 'Icon'
  return SolidIcons[componentName] || null
}

const currentIconComponent = computed(() => getIconComponent(props.iconRef))
const previewIconComponent = computed(() => getIconComponent(localIcon.value))

// HSV <-> Hex conversion
function hexToHsv(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255

  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min

  let h = 0
  if (d !== 0) {
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6
    else if (max === g) h = ((b - r) / d + 2) / 6
    else h = ((r - g) / d + 4) / 6
  }

  const s = max === 0 ? 0 : d / max
  const v = max

  return { h: h * 360, s, v }
}

function hsvToHex(h, s, v) {
  const hh = h / 60
  const i = Math.floor(hh)
  const f = hh - i
  const p = v * (1 - s)
  const q = v * (1 - s * f)
  const t = v * (1 - s * (1 - f))

  let r, g, b
  switch (i % 6) {
    case 0: r = v; g = t; b = p; break
    case 1: r = q; g = v; b = p; break
    case 2: r = p; g = v; b = t; break
    case 3: r = p; g = q; b = v; break
    case 4: r = t; g = p; b = v; break
    case 5: r = v; g = p; b = q; break
  }

  const toHex = (n) => Math.round(n * 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

// Slider styles
const hueSliderStyle = computed(() => ({
  background: 'linear-gradient(to right, #ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)'
}))

const satSliderStyle = computed(() => {
  const gray = hsvToHex(hsv.value.h, 0, hsv.value.v)
  const full = hsvToHex(hsv.value.h, 1, hsv.value.v)
  return { background: `linear-gradient(to right, ${gray}, ${full})` }
})

const valSliderStyle = computed(() => {
  const dark = hsvToHex(hsv.value.h, hsv.value.s, 0)
  const full = hsvToHex(hsv.value.h, hsv.value.s, 1)
  return { background: `linear-gradient(to right, ${dark}, ${full})` }
})

function updateHue(h) {
  hsv.value.h = parseFloat(h)
  localColor.value = hsvToHex(hsv.value.h, hsv.value.s, hsv.value.v)
}

function updateSaturation(s) {
  hsv.value.s = s
  localColor.value = hsvToHex(hsv.value.h, hsv.value.s, hsv.value.v)
}

function updateValue(v) {
  hsv.value.v = v
  localColor.value = hsvToHex(hsv.value.h, hsv.value.s, hsv.value.v)
}

function selectIcon(iconRef) {
  localIcon.value = iconRef
}

function selectColor(color) {
  localColor.value = color
  hsv.value = hexToHsv(color)
}

function applyCustomSvg() {
  if (customSvg.value.trim().startsWith('<svg')) {
    localIcon.value = customSvg.value.trim()
    customSvg.value = ''
  }
}

function toggleOpen() {
  if (isOpen.value) {
    isOpen.value = false
  } else {
    localIcon.value = props.iconRef
    localColor.value = props.color
    hsv.value = hexToHsv(props.color)
    showColorSliders.value = false
    showCustomSvg.value = false
    if (container.value) {
      const rect = container.value.getBoundingClientRect()
      const viewportHeight = window.innerHeight
      const pickerHeight = 420

      // Position above or below depending on space
      let top = rect.bottom + 4
      if (top + pickerHeight > viewportHeight) {
        top = Math.max(8, rect.top - pickerHeight - 4)
      }

      dropdownStyle.value = {
        top: `${top}px`,
        left: `${Math.max(8, rect.left - 150)}px`,
        width: '360px'
      }
    }
    isOpen.value = true
  }
}

function cancel() {
  isOpen.value = false
}

function apply() {
  emit('update:iconRef', localIcon.value)
  emit('update:color', localColor.value)
  emit('change', { iconRef: localIcon.value, color: localColor.value })
  isOpen.value = false
}

// Close on click outside
function handleClickOutside(event) {
  if (container.value && !container.value.contains(event.target)) {
    const dropdowns = document.querySelectorAll('.fixed.z-\\[10020\\]')
    for (const dropdown of dropdowns) {
      if (dropdown.contains(event.target)) return
    }
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
input[type="range"] {
  -webkit-appearance: none;
}

input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  border: 2px solid #3b82f6;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

input[type="range"]::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  border: 2px solid #3b82f6;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
</style>
