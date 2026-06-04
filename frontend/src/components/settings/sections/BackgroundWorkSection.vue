<template>
  <div>
    <div class="flex items-center gap-3 mb-4">
      <h3 class="text-base font-medium text-content">Background Work</h3>
      <div class="flex items-center gap-1.5 text-xs text-blue-500 bg-blue-500/10 border border-blue-500/30 rounded-full px-2.5 py-1">
        <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
        <span>Applies to all profiles</span>
      </div>
    </div>
    <p class="text-sm text-content-tertiary mb-6">
      Stimma automatically analyzes your media in the background to support many of its features. Background work uses CPU and GPU resources and impacts your energy usage. This page lets you control which background tasks are enabled and how much resources they use.
    </p>

    <!-- Face Detection -->
    <div class="p-4 bg-surface-raised/50 rounded-lg mb-4">
      <div class="flex items-center justify-between mb-2">
        <div class="flex-1">
          <h4 class="text-sm font-medium text-content">Face Detection</h4>
          <p class="text-xs text-content-tertiary mt-1">
            Automatically locates faces in your images. You can see detected faces on the Media Info pane, and face information is made available to the Chat system.
          </p>
        </div>
        <label class="relative inline-flex items-center cursor-pointer ml-4 flex-shrink-0">
          <input
            type="checkbox"
            :checked="localSettings.face_detection.enabled"
            @change="updateSetting('face_detection', 'enabled', $event.target.checked)"
            class="sr-only peer"
          />
          <div class="w-9 h-5 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      <div v-if="localSettings.face_detection.enabled" class="space-y-3 mt-4 pt-4 border-t border-edge">
        <div>
          <label class="block text-xs text-content-tertiary mb-1">
            Parallelism: {{ localSettings.face_detection.parallelism }}
          </label>
          <input
            type="range"
            min="1"
            max="16"
            :value="localSettings.face_detection.parallelism"
            @input="updateSetting('face_detection', 'parallelism', parseInt($event.target.value))"
            class="w-full accent-blue-500"
          />
        </div>
        <div>
          <label class="block text-xs text-content-tertiary mb-1">
            Confidence Threshold: {{ localSettings.face_detection.min_confidence.toFixed(2) }}
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            :value="localSettings.face_detection.min_confidence"
            @input="updateSetting('face_detection', 'min_confidence', parseFloat($event.target.value))"
            class="w-full accent-blue-500"
          />
        </div>
        <div>
          <label class="block text-xs text-content-tertiary mb-1">
            Max Faces to detect: {{ localSettings.face_detection.max_faces }}
          </label>
          <input
            type="range"
            min="1"
            max="50"
            :value="localSettings.face_detection.max_faces"
            @input="updateSetting('face_detection', 'max_faces', parseInt($event.target.value))"
            class="w-full accent-blue-500"
          />
        </div>
      </div>
    </div>

    <!-- Visual Indexing -->
    <div class="p-4 bg-surface-raised/50 rounded-lg mb-4">
      <div class="flex items-center justify-between">
        <div class="flex-1">
          <h4 class="text-sm font-medium text-content">Visual Indexing</h4>
          <p class="text-xs text-content-tertiary mt-1">
            Creates a visual fingerprint for each image. This enables natural language search and browsing similar images.
          </p>
        </div>
        <label class="relative inline-flex items-center cursor-pointer ml-4 flex-shrink-0">
          <input
            type="checkbox"
            :checked="localSettings.clip.enabled"
            @change="updateSetting('clip', 'enabled', $event.target.checked)"
            class="sr-only peer"
          />
          <div class="w-9 h-5 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>
    </div>

    <!-- Saving indicator -->
    <div v-if="saving" class="mt-4 text-xs text-content-muted">
      Saving...
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  backgroundWork: {
    type: Object,
    default: () => ({
      face_detection: { enabled: true, parallelism: 2, min_confidence: 0.5, max_faces: 10 },
      clip: { enabled: true }
    })
  }
})

const emit = defineEmits(['update'])

const localSettings = ref({
  face_detection: { enabled: true, parallelism: 2, min_confidence: 0.5, max_faces: 10 },
  clip: { enabled: true }
})
const saving = ref(false)
let saveTimer = null

// Deep copy settings on mount/change
watch(() => props.backgroundWork, (newSettings) => {
  localSettings.value = JSON.parse(JSON.stringify(newSettings))
}, { immediate: true })

function updateSetting(category, field, value) {
  localSettings.value[category][field] = value
  debouncedSave()
}

function debouncedSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    saving.value = true
    try {
      // Build the update payload - only send changed categories
      const payload = {}

      if (JSON.stringify(localSettings.value.face_detection) !== JSON.stringify(props.backgroundWork.face_detection)) {
        payload.face_detection = localSettings.value.face_detection
      }
      if (JSON.stringify(localSettings.value.clip) !== JSON.stringify(props.backgroundWork.clip)) {
        payload.clip = localSettings.value.clip
      }

      if (Object.keys(payload).length > 0) {
        await emit('update', payload)
      }
    } finally {
      saving.value = false
    }
  }, 300)
}
</script>
