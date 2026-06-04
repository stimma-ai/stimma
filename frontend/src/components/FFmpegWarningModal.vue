<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="dismiss"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl max-w-md w-full mx-4">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-edge">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center flex-shrink-0">
                <svg class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
                </svg>
              </div>
              <h3 class="text-lg font-semibold text-content">FFmpeg Required for Video Support</h3>
            </div>
          </div>

          <!-- Body -->
          <div class="px-6 py-4">
            <p class="text-content-secondary mb-4">{{ platformMessage }}</p>
            <div class="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
              <p class="text-sm text-red-500 font-medium">
                Video files cannot be processed until FFmpeg is installed and configured.
              </p>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex gap-3 justify-end">
            <button
              @click="dismiss"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Dismiss
            </button>
            <button
              @click="openInstallInstructions"
              class="px-4 py-2 bg-gradient-to-br from-red-500 to-red-600 hover:from-red-600 hover:to-red-700 text-white rounded-lg font-medium transition-all"
            >
              Install Instructions
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'
import { open } from '@tauri-apps/plugin-shell'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

const show = ref(false)
const { on } = useWebSocket()

let unsubscribe = null

// Detect platform and show appropriate message
const platformMessage = computed(() => {
  const platform = navigator.platform.toLowerCase()
  const userAgent = navigator.userAgent.toLowerCase()

  if (platform.includes('win') || userAgent.includes('windows')) {
    return "FFmpeg is required for video file support. Please install FFmpeg and add it to your system PATH."
  } else if (platform.includes('mac') || userAgent.includes('mac')) {
    return "FFmpeg is required for video file support. Install via Homebrew: brew install ffmpeg"
  } else if (platform.includes('linux') || userAgent.includes('linux')) {
    return "FFmpeg is required for video file support. Install via your package manager (apt install ffmpeg, yum install ffmpeg, etc.)"
  }

  return "FFmpeg is required for video file support. Please install FFmpeg and ensure it's available in your system PATH."
})

async function openInstallInstructions() {
  try {
    await open('https://stimma.ai/link/ffmpeg')
  } catch (error) {
    console.error('Failed to open install instructions:', error)
    // Fallback to window.open if Tauri shell fails
    window.open('https://stimma.ai/link/ffmpeg', '_blank')
  }
}

async function dismiss() {
  show.value = false

  // Mark warning as shown on backend
  try {
    await axios.post(`${API_URL}/api/system/warning-shown`, {
      warning_type: 'ffmpeg_missing'
    })
  } catch (error) {
    console.error('Failed to mark warning as shown:', error)
  }
}

function handleSystemWarning(data) {
  // Only show for ffmpeg_missing warnings
  if (data?.warning_type === 'ffmpeg_missing') {
    show.value = true
  }
}

onMounted(() => {
  // Subscribe to system_warning events
  unsubscribe = on('system_warning', handleSystemWarning)
})

onUnmounted(() => {
  if (unsubscribe) {
    unsubscribe()
  }
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .bg-surface,
.modal-leave-active .bg-surface {
  transition: transform 0.15s ease;
}

.modal-enter-from .bg-surface,
.modal-leave-to .bg-surface {
  transform: scale(0.95);
}
</style>
