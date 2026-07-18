<template>
  <div>
    <div class="mb-3">
      <h3 class="text-base font-medium text-content">Profiles</h3>
      <p class="mt-1 text-xs text-content-tertiary">
        Manage workspace profiles. Each profile has its own media library, markers, and settings.
      </p>
    </div>

    <!-- Profile list -->
    <div class="space-y-0.5">
      <div
        v-for="profile in profiles"
        :key="profile.id"
        class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-overlay-subtle"
        :class="{ 'cursor-pointer': profile.id !== currentProfileId }"
        @click="profile.id !== currentProfileId && switchToProfile(profile.id)"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center" :class="profile.id === currentProfileId ? 'text-accent' : 'text-content-secondary'">
          <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
          </svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium text-content">{{ profile.name }}</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">
            {{ profile.media_count?.toLocaleString() || 0 }} media file{{ profile.media_count !== 1 ? 's' : '' }}<template v-if="profile.has_pin"> · PIN</template>
          </div>
        </div>
        <div v-if="profile.id === currentProfileId" class="shrink-0 text-xs text-accent">Current</div>
        <button
          :ref="el => setMenuButtonRef(profile.id, el)"
          @click.stop="toggleProfileMenu(profile.id)"
          class="shrink-0 p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors"
          title="Profile options"
        >
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
          </svg>
        </button>
      </div>

      <!-- Empty state -->
      <div v-if="profiles.length === 0" class="text-center py-8 text-content-tertiary">
        No profiles configured
      </div>

      <!-- Create profile row -->
      <button type="button" @click="openCreateModal" class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-accent/[0.04]">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center text-accent">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-accent">Create Profile</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">Start a separate library with its own markers and settings.</div>
        </div>
      </button>
    </div>

    <!-- Create profile modal -->
    <Teleport to="body">
      <div
        v-if="showCreateModal"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closeCreateModal"
        @keydown.escape.stop="closeCreateModal"
        tabindex="-1"
        ref="createModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg p-6 w-[400px] max-w-[90vw]">
          <h3 class="text-lg font-medium text-content mb-4">Create Profile</h3>

          <!-- Name field -->
          <div class="mb-4">
            <label class="block text-xs text-content-tertiary mb-1">Name</label>
            <input
              v-model="newProfileName"
              ref="newProfileInput"
              type="text"
              placeholder="Profile name"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent"
              @keydown.enter="createProfile"
            />
            <p v-if="nameError" class="text-xs text-red-500 mt-1">{{ nameError }}</p>
          </div>

          <!-- Form actions -->
          <div class="flex justify-end gap-3">
            <button
              @click="closeCreateModal"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="createProfile"
              :disabled="!canCreate || saving"
              class="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md font-medium transition-colors"
            >
              {{ saving ? 'Creating...' : 'Create' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Rename profile modal -->
    <Teleport to="body">
      <div
        v-if="renameProfile"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closeRenameModal"
        @keydown.escape.stop="closeRenameModal"
        tabindex="-1"
        ref="renameModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg p-6 w-[400px] max-w-[90vw]">
          <h3 class="text-lg font-medium text-content mb-4">Rename Profile</h3>

          <!-- Name field -->
          <div class="mb-4">
            <label class="block text-xs text-content-tertiary mb-1">Name</label>
            <input
              v-model="renameProfileName"
              ref="renameProfileInput"
              type="text"
              placeholder="Profile name"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent"
              @keydown.enter="submitRename"
            />
            <p v-if="renameError" class="text-xs text-red-500 mt-1">{{ renameError }}</p>
          </div>

          <!-- Form actions -->
          <div class="flex justify-end gap-3">
            <button
              @click="closeRenameModal"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="submitRename"
              :disabled="!canRename || saving"
              class="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md font-medium transition-colors"
            >
              {{ saving ? 'Renaming...' : 'Rename' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete confirmation modal -->
    <Teleport to="body">
      <div
        v-if="deleteConfirm"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="deleteConfirm = null"
        @keydown.escape.stop="deleteConfirm = null"
        tabindex="-1"
        ref="deleteModalRef"
      >
        <div class="bg-surface border border-red-500/50 rounded-lg p-6 max-w-md">
          <!-- Warning header -->
          <div class="flex items-center gap-3 mb-4">
            <div class="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center flex-shrink-0">
              <svg class="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
              </svg>
            </div>
            <div>
              <h3 class="text-lg font-medium text-content">Delete Profile</h3>
              <p class="text-sm text-red-500">This action cannot be undone</p>
            </div>
          </div>

          <!-- Warning content -->
          <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4">
            <p class="text-sm text-content-secondary mb-2">
              You are about to permanently delete <strong class="text-content">{{ deleteConfirm.name }}</strong>.
            </p>
            <p class="text-sm text-content-tertiary">
              This will destroy:
            </p>
            <ul class="text-sm text-content-tertiary mt-2 ml-4 list-disc space-y-1">
              <li>All asset metadata and thumbnails</li>
              <li>Chat history and conversations</li>
              <li>Markers and boards</li>
              <li>Profile settings and folders</li>
            </ul>
          </div>

          <div class="flex justify-end gap-3">
            <button
              @click="deleteConfirm = null"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="deleteProfile"
              :disabled="saving"
              class="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg font-medium transition-colors"
            >
              {{ saving ? 'Deleting...' : 'Delete Forever' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- PIN settings modal -->
    <Teleport to="body">
      <div
        v-if="pinSettingsProfile"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closePinSettings"
        @keydown.escape.stop="closePinSettings"
        tabindex="-1"
        ref="pinSettingsModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg p-6 w-[400px] max-w-[90vw]">
          <h3 class="text-lg font-medium text-content mb-4">
            PIN Settings - {{ pinSettingsProfile.name }}
          </h3>

          <!-- PIN Status -->
          <div class="mb-4 p-3 bg-surface-raised/50 rounded-lg">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <svg
                  class="w-5 h-5"
                  :class="pinSettingsProfile.has_pin ? 'text-accent' : 'text-content-muted'"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                </svg>
                <span class="text-sm text-content">
                  {{ pinSettingsProfile.has_pin ? 'PIN enabled' : 'PIN not set' }}
                </span>
              </div>
              <button
                v-if="!pinSettingsProfile.has_pin"
                @click="showSetPinForm = true"
                class="px-3 py-1.5 bg-accent hover:bg-accent/90 text-white text-sm rounded-md font-medium transition-colors"
              >
                Set PIN
              </button>
              <div v-else class="flex gap-2">
                <button
                  @click="showChangePinForm = true"
                  class="px-3 py-1.5 bg-surface-hover hover:bg-surface-active text-content text-sm rounded font-medium transition-colors"
                >
                  Change
                </button>
                <button
                  @click="showRemovePinForm = true"
                  class="px-3 py-1.5 bg-red-600/80 hover:bg-red-600 text-white text-sm rounded font-medium transition-colors"
                >
                  Remove
                </button>
              </div>
            </div>
          </div>

          <!-- Set PIN form (inline) -->
          <div v-if="showSetPinForm" class="mb-4 p-3 bg-surface-raised/50 rounded-lg border border-edge">
            <label class="block text-xs text-content-tertiary mb-1">New PIN (4-20 characters)</label>
            <input
              v-model="newPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Enter new PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
              @keydown.enter="submitSetPin"
            />
            <label class="block text-xs text-content-tertiary mb-1">Confirm PIN</label>
            <input
              v-model="confirmPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Confirm PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
              @keydown.enter="submitSetPin"
            />
            <p v-if="pinError" class="text-xs text-red-500 mb-2">{{ pinError }}</p>
            <div class="flex gap-2 justify-end">
              <button
                @click="cancelPinForm"
                class="px-3 py-1.5 bg-surface-hover hover:bg-surface-active text-content text-sm rounded font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                @click="submitSetPin"
                :disabled="!canSetPin || savingPin"
                class="px-3 py-1.5 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-md font-medium transition-colors"
              >
                {{ savingPin ? 'Setting...' : 'Set PIN' }}
              </button>
            </div>
          </div>

          <!-- Change PIN form (inline) -->
          <div v-if="showChangePinForm" class="mb-4 p-3 bg-surface-raised/50 rounded-lg border border-edge">
            <label class="block text-xs text-content-tertiary mb-1">Current PIN</label>
            <input
              v-model="currentPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Enter current PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
            />
            <label class="block text-xs text-content-tertiary mb-1">New PIN (4-20 characters)</label>
            <input
              v-model="newPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Enter new PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
            />
            <label class="block text-xs text-content-tertiary mb-1">Confirm New PIN</label>
            <input
              v-model="confirmPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Confirm new PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
              @keydown.enter="submitChangePin"
            />
            <p v-if="pinError" class="text-xs text-red-500 mb-2">{{ pinError }}</p>
            <div class="flex gap-2 justify-end">
              <button
                @click="cancelPinForm"
                class="px-3 py-1.5 bg-surface-hover hover:bg-surface-active text-content text-sm rounded font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                @click="submitChangePin"
                :disabled="!canChangePin || savingPin"
                class="px-3 py-1.5 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-md font-medium transition-colors"
              >
                {{ savingPin ? 'Changing...' : 'Change PIN' }}
              </button>
            </div>
          </div>

          <!-- Remove PIN form (inline) -->
          <div v-if="showRemovePinForm" class="mb-4 p-3 bg-red-500/10 rounded-lg border border-red-500/30">
            <p class="text-sm text-content-secondary mb-3">Enter your current PIN to remove protection.</p>
            <label class="block text-xs text-content-tertiary mb-1">Current PIN</label>
            <input
              v-model="currentPin"
              type="password"
              inputmode="numeric"
              maxlength="20"
              placeholder="Enter current PIN"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent mb-2"
              @keydown.enter="submitRemovePin"
            />
            <p v-if="pinError" class="text-xs text-red-500 mb-2">{{ pinError }}</p>
            <div class="flex gap-2 justify-end">
              <button
                @click="cancelPinForm"
                class="px-3 py-1.5 bg-surface-hover hover:bg-surface-active text-content text-sm rounded font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                @click="submitRemovePin"
                :disabled="!currentPin || savingPin"
                class="px-3 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm rounded font-medium transition-colors"
              >
                {{ savingPin ? 'Removing...' : 'Remove PIN' }}
              </button>
            </div>
          </div>

          <!-- Idle timeout setting (only when PIN is set) -->
          <div v-if="pinSettingsProfile.has_pin && !showSetPinForm && !showChangePinForm && !showRemovePinForm" class="mb-4">
            <label class="block text-xs text-content-tertiary mb-2">Auto-lock after inactivity</label>
            <div class="flex items-center gap-3">
              <input
                type="range"
                :value="pinIdleTimeout"
                @input="pinIdleTimeout = parseInt($event.target.value)"
                @change="updateIdleTimeout"
                min="1"
                max="60"
                step="1"
                class="flex-1 h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer accent-accent"
              />
              <span class="text-sm text-content w-20 text-right">{{ pinIdleTimeout }} min</span>
            </div>
          </div>

          <!-- Close button -->
          <div class="flex justify-end">
            <button
              @click="closePinSettings"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Profile menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="openMenuId && menuPosition"
        data-profile-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 w-40 z-menu"
        :style="{ top: menuPosition.top + 'px', left: menuPosition.left + 'px' }"
      >
        <!-- Move Up -->
        <button
          @click.stop="moveProfile(openMenuId, -1)"
          :disabled="getProfileIndex(openMenuId) === 0"
          class="w-full px-3 py-1.5 text-left text-sm flex items-center gap-2 transition-colors"
          :class="getProfileIndex(openMenuId) === 0 ? 'text-content-muted cursor-not-allowed' : 'text-content hover:bg-surface-hover'"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
          </svg>
          Move Up
        </button>
        <!-- Move Down -->
        <button
          @click.stop="moveProfile(openMenuId, 1)"
          :disabled="getProfileIndex(openMenuId) === profiles.length - 1"
          class="w-full px-3 py-1.5 text-left text-sm flex items-center gap-2 transition-colors"
          :class="getProfileIndex(openMenuId) === profiles.length - 1 ? 'text-content-muted cursor-not-allowed' : 'text-content hover:bg-surface-hover'"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
          Move Down
        </button>
        <div class="border-t border-edge my-1"></div>
        <!-- Set/Change PIN -->
        <button
          @click.stop="openPinSettingsFromMenu()"
          class="w-full px-3 py-1.5 text-left text-sm text-content hover:bg-surface-hover flex items-center gap-2"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
          </svg>
          {{ getProfileById(openMenuId)?.has_pin ? 'Change PIN' : 'Set PIN' }}
        </button>
        <!-- Rename -->
        <button
          @click.stop="openRenameModalFromMenu()"
          class="w-full px-3 py-1.5 text-left text-sm text-content hover:bg-surface-hover flex items-center gap-2"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
          </svg>
          Rename
        </button>
        <template v-if="openMenuId !== currentProfileId">
          <div class="border-t border-edge my-1"></div>
          <!-- Delete -->
          <button
            @click.stop="confirmDeleteFromMenu()"
            class="w-full px-3 py-1.5 text-left text-sm text-red-400 hover:bg-surface-hover flex items-center gap-2"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
              <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
            </svg>
            Delete
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { getApiBase } from '../../../apiConfig'
import { cachePin } from '../../../composables/usePinLock'

const props = defineProps({
  profiles: {
    type: Array,
    default: () => []
  },
  currentProfileId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update', 'create', 'delete', 'switch', 'reorder'])

const saving = ref(false)

// 3-dot menu state
const openMenuId = ref(null)
const menuPosition = ref(null)
const menuButtonRefs = ref({})

function setMenuButtonRef(profileId, el) {
  if (el) {
    menuButtonRefs.value[profileId] = el
  } else {
    delete menuButtonRefs.value[profileId]
  }
}

function toggleProfileMenu(profileId) {
  if (openMenuId.value === profileId) {
    openMenuId.value = null
    menuPosition.value = null
  } else {
    const button = menuButtonRefs.value[profileId]
    if (button) {
      const rect = button.getBoundingClientRect()
      menuPosition.value = {
        top: rect.bottom + 4,
        left: rect.right - 160 // Align right edge of menu (w-40 = 160px) with button
      }
    }
    openMenuId.value = profileId
  }
}

function closeMenu() {
  openMenuId.value = null
  menuPosition.value = null
}

function getProfileIndex(profileId) {
  return props.profiles.findIndex(p => p.id === profileId)
}

function getProfileById(profileId) {
  return props.profiles.find(p => p.id === profileId)
}

// Menu action helpers (get profile from openMenuId and close menu)
function openPinSettingsFromMenu() {
  const profile = getProfileById(openMenuId.value)
  closeMenu()
  if (profile) openPinSettings(profile)
}

function openRenameModalFromMenu() {
  const profile = getProfileById(openMenuId.value)
  closeMenu()
  if (profile) openRenameModal(profile)
}

function confirmDeleteFromMenu() {
  const profile = getProfileById(openMenuId.value)
  closeMenu()
  if (profile) confirmDelete(profile)
}

async function moveProfile(profileId, direction) {
  const currentIndex = getProfileIndex(profileId)
  const newIndex = currentIndex + direction

  if (newIndex < 0 || newIndex >= props.profiles.length) return

  // Create new order by swapping
  const newOrder = props.profiles.map(p => p.id)
  ;[newOrder[currentIndex], newOrder[newIndex]] = [newOrder[newIndex], newOrder[currentIndex]]

  closeMenu()

  // Call the reorder API
  try {
    const response = await fetch(`${getApiBase()}/profiles/reorder`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': props.currentProfileId
      },
      body: JSON.stringify({ profile_ids: newOrder })
    })

    if (response.ok) {
      emit('reorder', newOrder)
    } else {
      console.error('[ProfilesSection] Failed to reorder profiles')
    }
  } catch (error) {
    console.error('[ProfilesSection] Reorder error:', error)
  }
}

// Close menu when clicking outside
function handleClickOutside(event) {
  if (openMenuId.value && !event.target.closest('[data-profile-menu]')) {
    closeMenu()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
const showCreateModal = ref(false)
const newProfileName = ref('')
const deleteConfirm = ref(null)
const createModalRef = ref(null)
const deleteModalRef = ref(null)
const newProfileInput = ref(null)

// Rename modal state
const renameProfile = ref(null)
const renameProfileName = ref('')
const renameModalRef = ref(null)
const renameProfileInput = ref(null)

// PIN settings modal state
const pinSettingsProfile = ref(null)
const pinSettingsModalRef = ref(null)
const showSetPinForm = ref(false)
const showChangePinForm = ref(false)
const showRemovePinForm = ref(false)
const currentPin = ref('')
const newPin = ref('')
const confirmPin = ref('')
const pinError = ref('')
const savingPin = ref(false)
const pinIdleTimeout = ref(30)

// Focus modals when opened
watch(showCreateModal, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    createModalRef.value?.focus()
    newProfileInput.value?.focus()
  }
})

watch(renameProfile, async (profile) => {
  if (profile) {
    await nextTick()
    renameModalRef.value?.focus()
    renameProfileInput.value?.focus()
    renameProfileInput.value?.select()
  }
})

watch(deleteConfirm, async (confirm) => {
  if (confirm) {
    await nextTick()
    deleteModalRef.value?.focus()
  }
})

// Validation
function isNameUnique(name, excludeId = null) {
  const normalizedName = name.trim().toLowerCase()
  return !props.profiles.some(p => p.name.toLowerCase() === normalizedName && p.id !== excludeId)
}

const nameError = computed(() => {
  if (!newProfileName.value.trim()) return null
  if (!isNameUnique(newProfileName.value)) return 'A profile with this name already exists'
  return null
})

const canCreate = computed(() => {
  if (!newProfileName.value.trim()) return false
  if (nameError.value) return false
  return true
})

const renameError = computed(() => {
  if (!renameProfileName.value.trim()) return null
  if (!isNameUnique(renameProfileName.value, renameProfile.value?.id)) return 'A profile with this name already exists'
  return null
})

const canRename = computed(() => {
  if (!renameProfileName.value.trim()) return false
  if (renameError.value) return false
  if (renameProfileName.value.trim() === renameProfile.value?.name) return false
  return true
})

// Rename modal functions
function openRenameModal(profile) {
  renameProfile.value = profile
  renameProfileName.value = profile.name
}

function closeRenameModal() {
  renameProfile.value = null
  renameProfileName.value = ''
}

async function submitRename() {
  if (!canRename.value || saving.value || !renameProfile.value) return

  saving.value = true
  try {
    emit('update', { profileId: renameProfile.value.id, data: { name: renameProfileName.value.trim() } })
    closeRenameModal()
  } finally {
    saving.value = false
  }
}

// Create modal functions
function openCreateModal() {
  newProfileName.value = ''
  showCreateModal.value = true
}

function closeCreateModal() {
  showCreateModal.value = false
  newProfileName.value = ''
}

async function createProfile() {
  if (!canCreate.value || saving.value) return

  saving.value = true
  try {
    emit('create', newProfileName.value.trim())
    closeCreateModal()
  } finally {
    saving.value = false
  }
}

// Switch profile
function switchToProfile(profileId) {
  emit('switch', profileId)
}

// Delete functions
function confirmDelete(profile) {
  deleteConfirm.value = profile
}

async function deleteProfile() {
  if (!deleteConfirm.value) return

  saving.value = true
  try {
    emit('delete', deleteConfirm.value.id)
    deleteConfirm.value = null
  } finally {
    saving.value = false
  }
}

// PIN settings functions
const canSetPin = computed(() => {
  if (!newPin.value || newPin.value.length < 4) return false
  if (newPin.value !== confirmPin.value) return false
  return true
})

const canChangePin = computed(() => {
  if (!currentPin.value) return false
  if (!newPin.value || newPin.value.length < 4) return false
  if (newPin.value !== confirmPin.value) return false
  return true
})

function openPinSettings(profile) {
  pinSettingsProfile.value = profile
  pinIdleTimeout.value = profile.pin_idle_timeout_minutes || 30
  resetPinForms()
}

function closePinSettings() {
  pinSettingsProfile.value = null
  resetPinForms()
}

function resetPinForms() {
  showSetPinForm.value = false
  showChangePinForm.value = false
  showRemovePinForm.value = false
  currentPin.value = ''
  newPin.value = ''
  confirmPin.value = ''
  pinError.value = ''
}

function cancelPinForm() {
  resetPinForms()
}

async function submitSetPin() {
  if (!canSetPin.value || savingPin.value || !pinSettingsProfile.value) return

  if (newPin.value !== confirmPin.value) {
    pinError.value = 'PINs do not match'
    return
  }

  savingPin.value = true
  pinError.value = ''

  try {
    const response = await fetch(`${getApiBase()}/profiles/${pinSettingsProfile.value.id}/pin`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': pinSettingsProfile.value.id
      },
      body: JSON.stringify({ new_pin: newPin.value })
    })

    if (response.ok) {
      // Cache the PIN immediately so user doesn't get locked out
      cachePin(pinSettingsProfile.value.id, newPin.value)
      // Update local profile state
      pinSettingsProfile.value = { ...pinSettingsProfile.value, has_pin: true }
      // Emit update to refresh profiles list
      emit('update', { profileId: pinSettingsProfile.value.id, data: { has_pin: true } })
      resetPinForms()
    } else {
      const data = await response.json().catch(() => ({}))
      pinError.value = data.detail || 'Failed to set PIN'
    }
  } catch (error) {
    pinError.value = 'Failed to set PIN'
    console.error('[ProfilesSection] Set PIN error:', error)
  } finally {
    savingPin.value = false
  }
}

async function submitChangePin() {
  if (!canChangePin.value || savingPin.value || !pinSettingsProfile.value) return

  if (newPin.value !== confirmPin.value) {
    pinError.value = 'PINs do not match'
    return
  }

  savingPin.value = true
  pinError.value = ''

  try {
    const response = await fetch(`${getApiBase()}/profiles/${pinSettingsProfile.value.id}/pin`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': pinSettingsProfile.value.id
      },
      body: JSON.stringify({ current_pin: currentPin.value, new_pin: newPin.value })
    })

    if (response.ok) {
      // Cache the new PIN so user doesn't get locked out
      cachePin(pinSettingsProfile.value.id, newPin.value)
      resetPinForms()
    } else {
      const data = await response.json().catch(() => ({}))
      pinError.value = data.detail || 'Failed to change PIN'
    }
  } catch (error) {
    pinError.value = 'Failed to change PIN'
    console.error('[ProfilesSection] Change PIN error:', error)
  } finally {
    savingPin.value = false
  }
}

async function submitRemovePin() {
  if (!currentPin.value || savingPin.value || !pinSettingsProfile.value) return

  savingPin.value = true
  pinError.value = ''

  try {
    const response = await fetch(`${getApiBase()}/profiles/${pinSettingsProfile.value.id}/pin`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': pinSettingsProfile.value.id
      },
      body: JSON.stringify({ current_pin: currentPin.value, new_pin: null })
    })

    if (response.ok) {
      // Update local profile state
      pinSettingsProfile.value = { ...pinSettingsProfile.value, has_pin: false }
      // Emit update to refresh profiles list
      emit('update', { profileId: pinSettingsProfile.value.id, data: { has_pin: false } })
      resetPinForms()
    } else {
      const data = await response.json().catch(() => ({}))
      pinError.value = data.detail || 'Failed to remove PIN'
    }
  } catch (error) {
    pinError.value = 'Failed to remove PIN'
    console.error('[ProfilesSection] Remove PIN error:', error)
  } finally {
    savingPin.value = false
  }
}

async function updateIdleTimeout() {
  if (!pinSettingsProfile.value) return

  try {
    const response = await fetch(`${getApiBase()}/profiles/${pinSettingsProfile.value.id}/pin-settings`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': pinSettingsProfile.value.id
      },
      body: JSON.stringify({ pin_idle_timeout_minutes: pinIdleTimeout.value })
    })

    if (response.ok) {
      // Update local profile state
      pinSettingsProfile.value = { ...pinSettingsProfile.value, pin_idle_timeout_minutes: pinIdleTimeout.value }
    } else {
      console.error('[ProfilesSection] Failed to update idle timeout')
    }
  } catch (error) {
    console.error('[ProfilesSection] Update idle timeout error:', error)
  }
}

// Focus PIN settings modal when opened
watch(pinSettingsProfile, async (profile) => {
  if (profile) {
    await nextTick()
    pinSettingsModalRef.value?.focus()
  }
})
</script>
