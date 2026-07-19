<template>
  <div>
    <div class="mb-3">
      <div class="flex items-center gap-3">
        <h3 class="text-xs font-semibold text-content-secondary">Background Work</h3>
      </div>
      <p class="mt-1 max-w-xl text-xs leading-relaxed text-content-tertiary">
        Stimma analyzes your media in the background to support many of its features. Background work uses CPU and GPU resources and impacts your energy usage.
      </p>
    </div>

    <div class="mt-6 max-w-[680px]">
      <!-- Face Detection -->
      <SettingRow
        label="Face Detection"
        description="Automatically locates faces in your images. You can see detected faces on the Media Info pane, and face information is made available to the Chat system."
        :divider="false"
      >
        <label class="relative inline-flex flex-shrink-0 cursor-pointer items-center">
          <input
            type="checkbox"
            :checked="localSettings.face_detection.enabled"
            @change="updateSetting('face_detection', 'enabled', $event.target.checked)"
            class="sr-only peer"
          />
          <div class="w-9 h-5 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-accent"></div>
        </label>
      </SettingRow>

      <!-- Sub-settings read as children of the row above: indented, no rules
           fencing them off (hairlines are separators between peers). -->
      <div v-if="localSettings.face_detection.enabled" class="mb-2.5 pl-4 py-2 space-y-4">
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">
            Parallelism: {{ localSettings.face_detection.parallelism }}
          </label>
          <input
            type="range"
            min="1"
            max="16"
            :value="localSettings.face_detection.parallelism"
            @input="updateSetting('face_detection', 'parallelism', parseInt($event.target.value))"
            class="w-full accent-accent"
          />
        </div>
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">
            Confidence Threshold: {{ localSettings.face_detection.min_confidence.toFixed(2) }}
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            :value="localSettings.face_detection.min_confidence"
            @input="updateSetting('face_detection', 'min_confidence', parseFloat($event.target.value))"
            class="w-full accent-accent"
          />
        </div>
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">
            Max Faces to detect: {{ localSettings.face_detection.max_faces }}
          </label>
          <input
            type="range"
            min="1"
            max="50"
            :value="localSettings.face_detection.max_faces"
            @input="updateSetting('face_detection', 'max_faces', parseInt($event.target.value))"
            class="w-full accent-accent"
          />
        </div>
      </div>

      <!-- Visual Indexing -->
      <SettingRow
        label="Visual Indexing"
        description="Creates a visual fingerprint for each image. This enables natural language search and browsing similar images."
      >
        <label class="relative inline-flex flex-shrink-0 cursor-pointer items-center">
          <input
            type="checkbox"
            :checked="localSettings.clip.enabled"
            @change="updateSetting('clip', 'enabled', $event.target.checked)"
            class="sr-only peer"
          />
          <div class="w-9 h-5 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-accent"></div>
        </label>
      </SettingRow>
    </div>

    <!-- Saving indicator -->
    <div v-if="saving" class="mt-4 text-xs text-content-muted">
      Saving...
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import SettingRow from '../SettingRow.vue'

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
