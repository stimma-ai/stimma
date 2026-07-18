<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-modal flex items-center justify-center"
      @mousedown.self="close"
    >
      <!-- Backdrop -->
      <div class="absolute inset-0 bg-overlay-backdrop" />

      <!-- Modal panel -->
      <div class="relative max-w-md w-full mx-4 bg-surface rounded-lg border border-edge-subtle shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 pt-5 pb-1">
          <div>
            <h2 class="text-base font-semibold text-content">Share</h2>
            <p class="text-xs text-content-muted mt-0.5">Create a public link anyone can view</p>
          </div>
          <button
            class="text-content-muted hover:text-content transition-colors"
            @click="close"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Loading status check -->
        <div v-if="isCheckingStatus" class="px-5 pb-5 pt-3 min-h-[280px] flex items-center justify-center">
          <div class="flex items-center justify-center gap-2">
            <svg class="w-4 h-4 animate-spin text-content-muted" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span class="text-sm text-content-muted">Loading...</span>
          </div>
        </div>

        <!-- Identity setup roadbump -->
        <div v-else-if="identityRequired" class="px-5 pb-5 pt-3 min-h-[280px]">
          <div class="flex flex-col items-center gap-3 py-2">
            <div class="w-10 h-10 rounded-full bg-violet-500/15 flex items-center justify-center">
              <svg class="w-5 h-5 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
              </svg>
            </div>

            <div class="text-center">
              <p class="text-sm font-medium text-content">Set up your profile</p>
              <p class="text-xs text-content-muted mt-1">Choose a username to start sharing on Stimma</p>
            </div>

            <div class="w-full mt-1">
              <div class="relative">
                <input
                  v-model="usernameInput"
                  type="text"
                  placeholder="username"
                  maxlength="24"
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded-lg px-3 py-2 text-sm text-content placeholder-content-muted focus:outline-none focus:border-violet-500/50"
                  :class="{ 'pr-8': isCheckingUsername }"
                  :disabled="isSettingUpIdentity"
                  @input="handleUsernameInput"
                  @keydown.enter="handleSetupIdentity"
                />
                <div v-if="isCheckingUsername" class="absolute right-3 top-1/2 -translate-y-1/2">
                  <svg class="w-4 h-4 animate-spin text-content-muted" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                </div>
              </div>
              <p class="text-[11px] text-content-muted mt-1.5 px-0.5">3&ndash;24 characters, lowercase letters, numbers, hyphens, and underscores</p>
              <p v-if="usernameError" class="text-xs text-red-500 mt-1 px-0.5">{{ usernameError }}</p>
            </div>

            <div class="w-full flex items-center justify-end gap-2.5 mt-2">
              <button
                class="px-4 py-2 text-sm text-content-muted hover:text-content transition-colors"
                :disabled="isSettingUpIdentity"
                @click="close"
              >
                Cancel
              </button>
              <button
                class="px-5 py-2 rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-sm font-medium !text-white transition-all disabled:opacity-50 flex items-center gap-2"
                :disabled="isSettingUpIdentity || isCheckingUsername || !!usernameError || usernameInput.trim().length < 3"
                @click="handleSetupIdentity"
              >
                <svg
                  v-if="isSettingUpIdentity"
                  class="w-4 h-4 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {{ isSettingUpIdentity ? 'Setting up...' : 'Continue' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Success state -->
        <div v-else-if="shareResult" class="px-5 pb-5 pt-3 min-h-[280px]">
          <div class="flex flex-col items-center gap-3 py-2">
            <div class="w-10 h-10 rounded-full bg-green-500/15 flex items-center justify-center">
              <svg class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>

            <p class="text-sm text-content font-medium">
              {{ linkCopied ? 'Link copied to clipboard' : 'Link created' }}
            </p>

            <p
              v-if="shareResult.status === 'quarantined'"
              class="text-xs text-amber-500 text-center"
            >
              Your share is being reviewed and will be available shortly.
            </p>

            <div class="w-full flex items-center gap-2 bg-overlay-subtle rounded-lg px-3 py-2">
              <span class="text-sm text-content-secondary truncate flex-1">{{ shareResult.url }}</span>
              <button
                class="shrink-0 text-xs font-medium px-3 py-1.5 rounded-md bg-overlay-light hover:bg-overlay-medium text-content transition-colors"
                @click="doCopy"
              >
                {{ linkCopied ? 'Copied!' : 'Copy' }}
              </button>
            </div>

            <div class="w-full flex gap-2">
              <button
                class="flex-1 px-4 py-2.5 rounded-lg bg-overlay-light hover:bg-overlay-medium text-sm font-medium text-content transition-colors flex items-center justify-center gap-2"
                @click="openInBrowser"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                  <path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 0 0-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 0 0 .75-.75v-4a.75.75 0 0 1 1.5 0v4A2.25 2.25 0 0 1 12.75 17h-8.5A2.25 2.25 0 0 1 2 14.75v-8.5A2.25 2.25 0 0 1 4.25 4h5a.75.75 0 0 1 0 1.5h-5Z" clip-rule="evenodd" />
                  <path fill-rule="evenodd" d="M6.194 12.753a.75.75 0 0 0 1.06.053L16.5 4.44v2.81a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-.75-.75h-4.5a.75.75 0 0 0 0 1.5h2.553l-9.056 8.194a.75.75 0 0 0-.053 1.06Z" clip-rule="evenodd" />
                </svg>
                Open in Browser
              </button>
              <button
                class="flex-1 px-4 py-2.5 rounded-lg bg-overlay-light hover:bg-overlay-medium text-sm font-medium text-content transition-colors"
                @click="close"
              >
                Done
              </button>
            </div>
          </div>
        </div>

        <!-- Form state -->
        <div v-else class="px-5 pb-5 pt-3 min-h-[280px]">
          <!-- Thumbnail preview -->
          <div v-if="thumbnailUrl" class="mb-4 rounded-lg overflow-hidden bg-overlay-faint flex items-center justify-center">
            <AppImage
              :src="thumbnailUrl"
              class="max-h-48 w-auto object-contain"
              alt="Media preview"
            />
          </div>

          <!-- Title input -->
          <div class="mb-3 relative">
            <input
              v-model="title"
              type="text"
              placeholder="Add a title..."
              maxlength="100"
              :disabled="isSharing"
              class="w-full bg-overlay-subtle border border-edge-subtle rounded-lg px-3 py-2 text-sm text-content placeholder-content-muted focus:outline-none focus:border-edge-strong disabled:opacity-50"
              :class="{ 'pr-8': suggestingTitle }"
              @input="handleTitleInput"
            />
            <div v-if="suggestingTitle" class="absolute right-3 top-1/2 -translate-y-1/2">
              <svg class="w-4 h-4 animate-spin text-content-muted" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          </div>

          <!-- Description textarea -->
          <div class="mb-4">
            <textarea
              v-model="description"
              placeholder="Add a description..."
              maxlength="500"
              rows="3"
              :disabled="isSharing"
              class="w-full bg-overlay-subtle border border-edge-subtle rounded-lg px-3 py-2 text-sm text-content placeholder-content-muted focus:outline-none focus:border-edge-strong resize-none disabled:opacity-50"
            />
          </div>

          <!-- Moderation feedback — fixed-height slot to prevent layout shift -->
          <div class="mb-4 min-h-[36px]">
            <div v-if="isPreChecking" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-overlay-subtle">
              <svg class="w-4 h-4 animate-spin text-content-muted shrink-0" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span class="text-xs text-content-muted">Checking content...</span>
            </div>

            <!-- Blocked / rejected -->
            <div
              v-else-if="isBlocked"
              class="px-3 py-2.5 rounded-lg bg-red-500/10 border border-red-500/20"
            >
              <p class="text-xs text-red-500">{{ preCheckResult.reason }}</p>
            </div>

            <!-- Quarantined warning -->
            <div
              v-else-if="preCheckResult?.decision === 'quarantined'"
              class="px-3 py-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20"
            >
              <p class="text-xs text-amber-500">{{ preCheckResult.reason }}</p>
            </div>
          </div>

          <!-- NSFW detected badge -->
          <div
            v-if="preCheckResult?.nsfw && !isBlocked"
            class="mb-4 px-3 py-2 rounded-lg bg-violet-500/10 border border-violet-500/20"
          >
            <p class="text-xs text-violet-400">Content detected as NSFW &mdash; viewers will see a content warning.</p>
          </div>

          <!-- Creator identity + NSFW toggle row -->
          <div class="mb-4 flex items-center justify-between px-1">
            <div v-if="user" class="flex items-center gap-2">
              <img
                v-if="user.photoURL"
                :src="user.photoURL"
                class="w-5 h-5 rounded-full"
                alt=""
              />
              <div
                v-else
                class="w-5 h-5 rounded-full bg-overlay-light flex items-center justify-center text-[10px] text-content-muted"
              >
                {{ (user.displayName || user.email || '?').charAt(0).toUpperCase() }}
              </div>
              <span class="text-xs text-content-muted">
                {{ user.displayName || user.email }}
              </span>
            </div>

            <button
              v-if="!isBlocked && !isPreChecking"
              type="button"
              class="flex items-center gap-1.5 text-xs transition-colors"
              :class="[
                nsfwOverride ? 'text-violet-400' : 'text-content-muted hover:text-content-secondary',
                preCheckResult?.nsfw ? 'cursor-not-allowed' : 'cursor-pointer'
              ]"
              :disabled="preCheckResult?.nsfw"
              @click="toggleNsfw"
            >
              <span>{{ preCheckResult?.nsfw ? 'NSFW (auto)' : 'NSFW' }}</span>
              <span
                class="relative inline-flex h-4 w-7 shrink-0 rounded-full transition-colors duration-200"
                :class="nsfwOverride ? 'bg-violet-500' : 'bg-overlay-medium'"
              >
                <span
                  class="pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow transition duration-200 mt-0.5"
                  :class="nsfwOverride ? 'translate-x-3.5 ml-px' : 'translate-x-0.5'"
                />
              </span>
            </button>
          </div>

          <!-- Error state -->
          <div v-if="shareError" class="mb-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
            <p class="text-xs text-red-500">{{ shareError }}</p>
          </div>

          <!-- Action buttons -->
          <div class="flex items-center justify-end gap-2.5">
            <button
              class="px-4 py-2 text-sm text-content-muted hover:text-content transition-colors"
              :disabled="isSharing"
              @click="close"
            >
              Cancel
            </button>

            <button
              class="px-5 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium !text-white transition-all disabled:opacity-50 flex items-center gap-2"
              :disabled="isSharing || isBlocked"
              @click="handleShare"
            >
              <svg
                v-if="isSharing"
                class="w-4 h-4 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                <path d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z" />
                <path d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z" />
              </svg>
              {{ isSharing ? 'Creating link...' : isBlocked ? 'Cannot Share' : 'Create Link' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useShare } from '../composables/useShare'
import { useAuth } from '../composables/useAuth'
import { copyToClipboard } from '../utils/clipboard'
import AppImage from './media/AppImage.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  mediaItem: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue'])

const { user } = useAuth()
const {
  isSharing,
  shareResult,
  shareError,
  isPreChecking,
  preCheckResult,
  identityRequired,
  isSettingUpIdentity,
  nsfwOverride,
  shareMedia,
  preCheckMedia,
  checkShareStatus,
  checkUsername,
  setupIdentity,
  resetShare,
} = useShare()

const title = ref('')
const description = ref('')
const linkCopied = ref(false)
const suggestingTitle = ref(false)
const userHasTypedTitle = ref(false)
const isCheckingStatus = ref(false)
const usernameInput = ref('')
const usernameError = ref('')
const isCheckingUsername = ref(false)
let suggestAbortController = null
let preCheckAbortController = null
let usernameCheckTimeout = null

const thumbnailUrl = computed(() => {
  if (!props.mediaItem?.file_hash) return null
  return `/api/thumbnail/${props.mediaItem.file_hash}`
})

const isBlocked = computed(() => {
  return preCheckResult.value?.blocked || preCheckResult.value?.decision === 'rejected'
})

function handleTitleInput() {
  userHasTypedTitle.value = true
  // Cancel any in-flight suggestion
  if (suggestAbortController) {
    suggestAbortController.abort()
    suggestAbortController = null
    suggestingTitle.value = false
  }
}

function toggleNsfw() {
  // Cannot turn off if cloud detected NSFW
  if (preCheckResult.value?.nsfw) return
  nsfwOverride.value = !nsfwOverride.value
}

async function suggestTitle(mediaId) {
  // Cancel previous request if any
  if (suggestAbortController) {
    suggestAbortController.abort()
  }
  suggestAbortController = new AbortController()
  suggestingTitle.value = true

  try {
    const response = await fetch('/api/share/suggest-title', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_id: mediaId }),
      signal: suggestAbortController.signal,
    })

    if (!response.ok) return

    const data = await response.json()

    // Only apply if user hasn't started typing
    if (!userHasTypedTitle.value && data.title) {
      title.value = data.title
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.warn('Title suggestion failed:', err)
    }
  } finally {
    suggestingTitle.value = false
    suggestAbortController = null
  }
}

// Reset state when dialog opens
watch(() => props.modelValue, async (open) => {
  if (open && props.mediaItem) {
    title.value = ''
    description.value = ''
    linkCopied.value = false
    userHasTypedTitle.value = false
    usernameInput.value = ''
    usernameError.value = ''
    resetShare()

    // Check share status first (determines if identity setup is needed)
    isCheckingStatus.value = true
    await checkShareStatus()
    isCheckingStatus.value = false

    // Only proceed with share flow if identity is set up
    if (!identityRequired.value) {
      suggestTitle(props.mediaItem.id)
      preCheckMedia(props.mediaItem.id)
    }
  } else if (!open) {
    // Cancel on close
    if (suggestAbortController) {
      suggestAbortController.abort()
      suggestAbortController = null
      suggestingTitle.value = false
    }
    if (usernameCheckTimeout) {
      clearTimeout(usernameCheckTimeout)
      usernameCheckTimeout = null
    }
  }
})

function handleUsernameInput() {
  usernameError.value = ''
  if (usernameCheckTimeout) clearTimeout(usernameCheckTimeout)

  const val = usernameInput.value.toLowerCase().trim()
  if (!val || val.length < 3) return

  usernameCheckTimeout = setTimeout(async () => {
    isCheckingUsername.value = true
    const result = await checkUsername(val)
    isCheckingUsername.value = false
    if (result.error) {
      usernameError.value = result.error
    } else if (!result.available) {
      usernameError.value = 'Username is already taken'
    }
  }, 400)
}

async function handleSetupIdentity() {
  const username = usernameInput.value.toLowerCase().trim()
  if (!username || username.length < 3) {
    usernameError.value = 'Username must be at least 3 characters'
    return
  }

  usernameError.value = ''
  const result = await setupIdentity(username)

  if (!result.success) {
    usernameError.value = result.error || 'Failed to set up profile'
    return
  }

  // Identity set up — proceed to share flow
  if (props.mediaItem) {
    suggestTitle(props.mediaItem.id)
    preCheckMedia(props.mediaItem.id)
  }
}

function close() {
  emit('update:modelValue', false)
}

async function handleShare() {
  if (!props.mediaItem) return

  try {
    await shareMedia(props.mediaItem.id, {
      title: title.value,
      description: description.value,
    })
    // Auto-copy link to clipboard on success
    await doCopy()
  } catch {
    // Error is already captured in shareError
  }
}

async function doCopy() {
  if (!shareResult.value?.url) return
  const ok = await copyToClipboard(shareResult.value.url)
  if (ok) {
    linkCopied.value = true
    setTimeout(() => { linkCopied.value = false }, 5000)
  }
}

async function openInBrowser() {
  if (!shareResult.value?.url) return
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(shareResult.value.url)
  } catch {
    // Fallback for non-Tauri environments
    window.open(shareResult.value.url, '_blank')
  }
}
</script>
