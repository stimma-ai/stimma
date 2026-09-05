<template>
  <!-- Body of the background-work popover (desktop) and sheet (compact):
       delete progress, system warnings, one block per processing phase,
       then Rescan / Pause. The failed-items modal rides along. -->
  <div>
    <div v-if="statsLoading" class="p-8 text-center text-content-muted text-sm">Loading progress data...</div>
    <template v-else>
      <div v-if="deleteSummary" class="mb-4 pb-4 border-b border-surface-raised">
        <div class="flex justify-between items-center mb-2">
          <span class="flex items-center gap-2 text-sm font-semibold text-content">
            {{ deleteSummary.status === 'completed' ? 'Deletion Complete' : deleteSummary.status === 'failed' ? 'Deletion Failed' : 'Permanently Deleting' }}
            <Spinner v-if="deleteSummary.status === 'running'" size="sm" hue="border-t-white/80" />
          </span>
          <span class="text-xs font-mono tabular-nums text-content-tertiary">
            <span class="text-red-400 font-semibold">{{ deleteDoneCount }}</span> /
            <span class="text-content-muted">{{ deleteTotalCount }}</span>
          </span>
        </div>
        <div class="mb-2">
          <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
            <div class="h-full bg-gradient-to-r from-red-500 to-orange-400 rounded transition-[width] duration-500" :style="{ width: `${deleteProgressPercent}%` }"></div>
          </div>
        </div>
        <div class="flex items-center justify-between text-[0.6875rem] text-content-tertiary">
          <span>{{ deleteOperationLabel }}</span>
          <span v-if="deleteSummary.eta_seconds">ETA {{ formatEta(deleteSummary.eta_seconds) }}</span>
        </div>
        <button
          v-if="deleteSummary.status === 'failed'"
          class="mt-3 px-3 py-1.5 coarse:min-h-[44px] rounded border border-accent/50 bg-accent/15 text-xs text-accent hover:bg-accent/25 disabled:opacity-50"
          :disabled="retryingDeletion"
          @click="retryDeletion"
        >
          {{ retryingDeletion ? 'Retrying…' : 'Retry deletion' }}
        </button>
      </div>

      <div v-if="systemWarnings.length > 0" class="mb-4 pb-4 border-b border-surface-raised">
        <div class="flex items-center gap-2 mb-2">
          <svg class="w-4 h-4 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
            <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
          </svg>
          <span class="text-sm font-semibold text-yellow-500">System Warnings</span>
        </div>
        <div v-for="warning in systemWarnings" :key="warning.type" class="text-xs text-content-secondary mb-2">
          <div class="flex items-start justify-between gap-2">
            <div class="font-medium">{{ warning.title }}</div>
            <button
              class="text-content-tertiary hover:text-content-secondary shrink-0 coarse:w-11 coarse:h-11 coarse:-mt-3 coarse:-mr-3 coarse:text-lg"
              title="Dismiss"
              @click.stop="dismissSystemWarning(warning.type)"
            >
              ×
            </button>
          </div>
          <div class="text-content-tertiary">{{ warning.message }}</div>
          <a
            :href="warning.action_url"
            target="_blank"
            rel="noopener noreferrer"
            class="text-blue-500 hover:underline"
            @click.stop.prevent="openSystemWarningAction(warning.action_url)"
          >
            {{ warning.action_label || 'Installation instructions' }} →
          </a>
        </div>
      </div>

      <div
        v-for="phase in phases"
        :key="phase.id"
        class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0"
      >
        <div class="flex justify-between items-center mb-2">
          <span class="flex items-center gap-2 text-sm font-semibold text-content">
            {{ phase.label }}
            <svg v-if="phase.pausable && isPaused && hasPendingWork(phase.id)" class="w-3 h-3 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
            </svg>
            <Spinner v-else-if="stats[phase.id]?.processing > 0" size="sm" hue="border-t-white/80" />
          </span>
          <span class="text-xs font-mono tabular-nums text-content-tertiary">
            <span class="text-green-500 font-semibold">{{ stats[phase.id]?.completed || 0 }}</span> /
            <span class="text-content-muted">{{ getTotalForPhase(phase.id) }}</span>
          </span>
        </div>
        <div class="mb-2">
          <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
            <div class="h-full bg-gradient-to-r from-green-500 to-green-400 rounded transition-[width] duration-500" :style="{ width: getProgressPercent(phase.id) + '%' }"></div>
          </div>
        </div>
        <div v-if="stats[phase.id]?.failed > 0" class="flex gap-2 flex-wrap">
          <span class="text-[0.6875rem] px-2 py-1 coarse:py-2.5 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:opacity-80" @click.stop="showFailedItems(phase.id)">
            {{ stats[phase.id].failed }} failed
          </span>
        </div>
      </div>

      <div class="mt-4 pt-4 border-t border-surface-raised flex gap-2">
        <button
          class="flex-1 px-3 py-2 coarse:min-h-[44px] text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content transition-colors flex items-center justify-center gap-2 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          @click.stop="triggerRescan"
          :disabled="rescanning"
        >
          <svg v-if="!rescanning" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          <Spinner v-else size="md" hue="border-t-white" />
          <span>Rescan files</span>
        </button>
        <button
          class="flex-1 px-3 py-2 coarse:min-h-[44px] text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content transition-colors flex items-center justify-center gap-2 rounded-md"
          @click.stop="togglePause"
        >
          <svg v-if="!isPaused" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25v13.5m-7.5-13.5v13.5" />
          </svg>
          <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
          </svg>
          <span>{{ isPaused ? 'Resume' : 'Pause' }}</span>
        </button>
      </div>
    </template>

    <!-- Failed Items -->
    <Modal :show="failedOpen" size="custom" custom-class="max-w-[800px] w-[90%] max-h-[80vh] flex flex-col" @close="closeFailedItems">
      <template #header>
        <div class="flex justify-between items-center gap-2">
          <h2 class="m-0 text-xl compact:text-base font-semibold text-content truncate">{{ failedTitle }}</h2>
          <div class="flex gap-3 compact:gap-1.5 items-center">
            <button
              v-if="failedItems.length > 0 && !loadingFailed"
              class="flex items-center gap-2 bg-gradient-to-br from-green-500 to-green-600 border-none text-white px-4 py-2 compact:px-3 rounded-md text-sm font-semibold cursor-pointer transition-all hover:from-green-600 hover:to-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
              @click="retryAll"
              :disabled="retrying || trashing"
            >
              <svg v-if="!retrying" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
              <span>{{ retrying ? 'Retrying...' : 'Retry All' }}</span>
            </button>
            <button
              v-if="failedItems.length > 0 && !loadingFailed"
              class="flex items-center gap-2 bg-overlay-subtle border border-edge text-content-secondary px-3 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-light hover:text-content hover:border-edge-strong disabled:opacity-50 disabled:cursor-not-allowed"
              @click="trashAll"
              :disabled="retrying || trashing"
              title="Move all failed items to trash"
            >
              <svg v-if="!trashing" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
              <Spinner v-else size="md" hue="border-t-white" />
              <span class="compact:hidden">Trash All</span>
            </button>
            <button class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 coarse:w-11 coarse:h-11 flex items-center justify-center transition-colors hover:text-content" @click="closeFailedItems">
              <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      </template>

      <div class="p-6 compact:p-3 overflow-y-auto flex-1">
        <div v-if="loadingFailed" class="text-center text-content-tertiary p-8 text-sm">Loading failed items...</div>
        <div v-else-if="failedItems.length === 0" class="text-center text-content-tertiary p-8 text-sm">No failed items found.</div>
        <div v-else class="flex flex-col gap-4">
          <div v-for="item in failedItems" :key="item.id" class="bg-overlay-subtle border border-edge rounded-lg p-4 compact:p-3 flex gap-4 compact:gap-3">
            <div class="w-12 h-12 flex-shrink-0 rounded-md overflow-hidden bg-surface-raised">
              <img
                v-if="item.file_hash"
                :src="getThumbnailUrl(item.file_hash, 64)"
                :class="['w-full h-full object-cover', item.has_alpha !== false ? 'bg-checker' : '']"
                @error="$event.target.style.display = 'none'"
              />
              <div v-else class="w-full h-full flex items-center justify-center text-content-muted">
                <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z" />
                </svg>
              </div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex justify-between items-start gap-3 mb-2">
                <span class="font-semibold text-content text-sm truncate">{{ getFileName(item.file_path) }}</span>
                <button
                  class="flex items-center gap-1.5 bg-gradient-to-br from-green-500 to-green-600 border-none text-white px-2.5 py-1.5 rounded text-xs font-medium cursor-pointer transition-all hover:from-green-600 hover:to-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                  @click="retryItem(item.id)"
                  :disabled="retrying || trashing"
                  title="Retry this item"
                >
                  Retry
                </button>
              </div>
              <div class="text-red-500 text-xs font-mono bg-red-500/10 px-2.5 py-1.5 rounded border-l-2 border-red-500 mb-2 break-words">{{ item.error || 'Unknown error' }}</div>
              <div class="text-xs text-content-muted font-mono truncate" :title="item.file_path">{{ item.file_path }}</div>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import Spinner from './ui/Spinner.vue'
import Modal from './ui/Modal.vue'
import { useBackgroundWork } from '../composables/useBackgroundWork'
import { useMediaApi } from '../composables/useMediaApi'
import { captioningEnabledRef } from '../appConfig'
import { formatEta } from '../utils/timeFormat'

const {
  stats, systemWarnings, statsLoading, isPaused, rescanning, retryingDeletion,
  deleteSummary, deleteProgressPercent, deleteTotalCount, deleteDoneCount, deleteOperationLabel,
  failedOpen, failedItems, loadingFailed, retrying, trashing, failedTitle,
  togglePause, triggerRescan, retryDeletion, getTotalForPhase, getProgressPercent, hasPendingWork,
  dismissSystemWarning, openSystemWarningAction, showFailedItems, closeFailedItems, retryAll, retryItem, trashAll,
} = useBackgroundWork()
const { getThumbnailUrl } = useMediaApi()

const phases = computed(() => [
  { id: 'metadata', label: 'Processing Media', pausable: false },
  { id: 'clip', label: 'Visual Indexing', pausable: true },
  { id: 'face_detection', label: 'Face Analysis', pausable: true },
  ...(captioningEnabledRef.value ? [{ id: 'vlm_caption', label: 'Visual Analysis', pausable: true }] : []),
])

function getFileName(path) {
  return String(path || '').split('/').pop()
}
</script>
