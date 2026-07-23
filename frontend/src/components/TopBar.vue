<template>
  <div class="relative flex items-center justify-between px-4 h-14 bg-surface border-b border-edge-subtle flex-shrink-0" data-tauri-drag-region>
    <!-- Left side: navigation buttons -->
    <div class="flex items-center gap-0.5">
      <button
        class="w-7 h-7 flex items-center justify-center rounded transition-colors"
        :class="canGoBack ? 'text-content-secondary hover:bg-overlay-subtle hover:text-content cursor-pointer' : 'text-content-muted/30 cursor-default'"
        :disabled="!canGoBack"
        @click="goBack"
        title="Go back"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
        </svg>
      </button>
      <button
        class="w-7 h-7 flex items-center justify-center rounded transition-colors"
        :class="canGoForward ? 'text-content-secondary hover:bg-overlay-subtle hover:text-content cursor-pointer' : 'text-content-muted/30 cursor-default'"
        :disabled="!canGoForward"
        @click="goForward"
        title="Go forward"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
      </button>
    </div>

    <!-- Center: global search omnibox -->
    <!-- z-30: the translate wrapper traps the dropdown's z-index in its own
         stacking context, which must outrank the view roots (relative, z-auto) -->
    <div class="absolute left-1/2 top-0 h-full -translate-x-1/2 flex items-center z-30">
      <GlobalSearchBox />
    </div>

    <!-- Right side: controls and progress -->
    <div class="flex items-center gap-2">
      <!-- Processing indicator (only shows when there's activity or errors) -->
      <div
        v-if="hasActiveWork"
        class="relative cursor-pointer select-none processing-indicator p-2"
        @click="toggleExpanded"
        :title="progressTitle"
      >
        <!-- Paused icon when paused with incomplete work -->
        <svg v-if="isPaused && hasIncompleteWork" class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
        </svg>
        <!-- Spinner when actively processing -->
        <Spinner v-else-if="(isActivelyProcessing && !isPaused) || isDeleteRunning" hue="border-t-white/80" />
        <!-- Red warning triangle when there are errors -->
        <svg v-else-if="totalFailed > 0 || hasDeleteFailed" class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
        </svg>
        <!-- Brief success state after permanent deletion completes -->
        <svg v-else-if="hasDeleteCompleted" class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
        </svg>
        <!-- Yellow warning triangle when only system warnings present -->
        <svg v-else-if="systemWarnings.length > 0 && totalPending === 0 && totalProcessing === 0" class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
        </svg>
        <!-- Amber pending indicator (pending but not processing) -->
        <Spinner v-else hue="border-t-amber-500" />

        <transition name="expand">
          <div v-if="isExpanded && statsLoading" class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge rounded-lg p-4 min-w-[400px] shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu">
            <div class="p-8 text-center text-content-muted text-sm">Loading progress data...</div>
          </div>
          <div v-else-if="isExpanded" class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge rounded-lg p-4 min-w-[400px] shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu">
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
                class="mt-3 px-3 py-1.5 rounded border border-accent/50 bg-accent/15 text-xs text-accent hover:bg-accent/25 disabled:opacity-50"
                :disabled="retryingDeletion"
                @click="retryDeletion"
              >
                {{ retryingDeletion ? 'Retrying…' : 'Retry deletion' }}
              </button>
            </div>

            <!-- System Warnings Section -->
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
                    class="text-content-tertiary hover:text-content-secondary shrink-0"
                    title="Dismiss"
                    @click.stop="dismissSystemWarning(warning.type)"
                  >
                    ×
                  </button>
                </div>
                <div class="text-content-tertiary">{{ warning.message }}</div>
                <a :href="warning.action_url" target="_blank" class="text-blue-500 hover:underline">
                  {{ warning.action_label || 'Installation instructions' }} →
                </a>
              </div>
            </div>

            <!-- Metadata Phase -->
            <div class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  Processing Media
                  <Spinner v-if="stats.metadata?.processing > 0" size="sm" hue="border-t-white/80" />
                </span>
                <span class="text-xs font-mono tabular-nums text-content-tertiary">
                  <span class="text-green-500 font-semibold">{{ stats.metadata?.completed || 0 }}</span> /
                  <span class="text-content-muted">{{ getTotalForPhase('metadata') }}</span>
                </span>
              </div>
              <div class="mb-2">
                <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-green-500 to-green-400 rounded transition-[width] duration-500" :style="{ width: getProgressPercent('metadata') + '%' }"></div>
                </div>
              </div>
              <div v-if="stats.metadata?.failed > 0" class="flex gap-2 flex-wrap">
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:opacity-80" @click.stop="showFailedItems('metadata')">
                  {{ stats.metadata.failed }} failed
                </span>
              </div>
            </div>

            <!-- CLIP Phase -->
            <div class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  Visual Indexing
                  <!-- Paused icon when paused with pending work -->
                  <svg v-if="isPaused && hasPendingWork('clip')" class="w-3 h-3 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
                  </svg>
                  <!-- Spinner when actively processing -->
                  <Spinner v-else-if="stats.clip?.processing > 0" size="sm" hue="border-t-white/80" />
                </span>
                <span class="text-xs font-mono tabular-nums text-content-tertiary">
                  <span class="text-green-500 font-semibold">{{ stats.clip?.completed || 0 }}</span> /
                  <span class="text-content-muted">{{ getTotalForPhase('clip') }}</span>
                </span>
              </div>
              <div class="mb-2">
                <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-green-500 to-green-400 rounded transition-[width] duration-500" :style="{ width: getProgressPercent('clip') + '%' }"></div>
                </div>
              </div>
              <div v-if="stats.clip?.failed > 0" class="flex gap-2 flex-wrap">
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:opacity-80" @click.stop="showFailedItems('clip')">
                  {{ stats.clip.failed }} failed
                </span>
              </div>
            </div>

            <!-- Face Detection Phase -->
            <div class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  Face Analysis
                  <!-- Paused icon when paused with pending work -->
                  <svg v-if="isPaused && hasPendingWork('face_detection')" class="w-3 h-3 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
                  </svg>
                  <!-- Spinner when actively processing -->
                  <Spinner v-else-if="stats.face_detection?.processing > 0" size="sm" hue="border-t-white/80" />
                </span>
                <span class="text-xs font-mono tabular-nums text-content-tertiary">
                  <span class="text-green-500 font-semibold">{{ stats.face_detection?.completed || 0 }}</span> /
                  <span class="text-content-muted">{{ getTotalForPhase('face_detection') }}</span>
                </span>
              </div>
              <div class="mb-2">
                <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-green-500 to-green-400 rounded transition-[width] duration-500" :style="{ width: getProgressPercent('face_detection') + '%' }"></div>
                </div>
              </div>
              <div v-if="stats.face_detection?.failed > 0" class="flex gap-2 flex-wrap">
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:opacity-80" @click.stop="showFailedItems('face_detection')">
                  {{ stats.face_detection.failed }} failed
                </span>
              </div>
            </div>

            <!-- Visual Analysis Phase (captions + keywords) -->
            <div v-if="captioningEnabledRef" class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  Visual Analysis
                  <!-- Paused icon when paused with pending work -->
                  <svg v-if="isPaused && hasPendingWork('vlm_caption')" class="w-3 h-3 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
                  </svg>
                  <!-- Spinner when actively processing -->
                  <Spinner v-else-if="stats.vlm_caption?.processing > 0" size="sm" hue="border-t-white/80" />
                </span>
                <span class="text-xs font-mono tabular-nums text-content-tertiary">
                  <span class="text-green-500 font-semibold">{{ stats.vlm_caption?.completed || 0 }}</span> /
                  <span class="text-content-muted">{{ getTotalForPhase('vlm_caption') }}</span>
                </span>
              </div>
              <div class="mb-2">
                <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-green-500 to-green-400 rounded transition-[width] duration-500" :style="{ width: getProgressPercent('vlm_caption') + '%' }"></div>
                </div>
              </div>
              <div v-if="stats.vlm_caption?.failed > 0" class="flex gap-2 flex-wrap">
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:opacity-80" @click.stop="showFailedItems('vlm_caption')">
                  {{ stats.vlm_caption.failed }} failed
                </span>
              </div>
            </div>

            <!-- Actions section -->
            <div class="mt-4 pt-4 border-t border-surface-raised flex gap-2">
              <button
                class="flex-1 px-3 py-2 text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content transition-colors flex items-center justify-center gap-2 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                @click.stop="handleRescan"
                :disabled="rescanning"
              >
                <svg v-if="!rescanning" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
                <Spinner v-else size="md" hue="border-t-white" />
                <span>Rescan files</span>
              </button>
              <button
                class="flex-1 px-3 py-2 text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content transition-colors flex items-center justify-center gap-2 rounded-md"
                @click.stop="handleTogglePause"
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
          </div>
        </transition>
      </div>

      <!-- Update affordance: compact icon pill that peeks open on state change and expands on hover -->
      <button
        v-if="updateState && !updatesBlockedByPrivacyLockdown"
        @click="onUpdatePillClick"
        @mouseenter="updatePillHover = true"
        @mouseleave="updatePillHover = false"
        class="flex items-center h-7 rounded-full border overflow-hidden whitespace-nowrap text-xs font-medium transition-[width,background-color] duration-200 ease-out select-none"
        :class="[
          updateState === 'restart'
            ? 'bg-green-500/15 border-green-500/50 text-green-400 hover:bg-green-500/25'
            : 'bg-accent/15 border-accent/50 text-accent-hi',
          updateState === 'available' || updateState === 'whatsnew' ? 'hover:bg-accent/25' : '',
          updateState === 'downloading' ? 'cursor-default' : '',
        ]"
        :style="{ width: updatePillExpanded ? updatePillWidth : '28px' }"
        :title="updatePillLabel"
      >
        <span class="flex-none w-[26px] flex items-center justify-center">
          <Spinner v-if="updateState === 'downloading'" size="sm" />
          <svg v-else-if="updateState === 'restart'" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          <svg v-else-if="updateState === 'whatsnew'" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
          </svg>
          <svg v-else class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
        </span>
        <span
          ref="updatePillLabelEl"
          class="pr-3 transition-opacity duration-150"
          :class="updatePillExpanded ? 'opacity-100 delay-75' : 'opacity-0'"
        >{{ updatePillLabel }}</span>
      </button>

      <!-- Profile picker: exists only when a second profile does -->
      <div v-if="profiles.length > 1" class="relative profile-menu">
        <!-- Ghost trigger, not a pill — bordered+filled chips aren't Atelier
             chrome; the menu carries the affordance. -->
        <button
          class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
          @click="toggleProfileMenu"
          title="Switch profile"
        >
          <span class="max-w-[140px] truncate">{{ currentProfileName }}</span>
          <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <transition name="menu">
          <div
            v-if="profileMenuOpen"
            class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu min-w-[220px] overflow-hidden"
          >
            <div class="py-1">
              <div
                v-for="profile in profiles"
                :key="profile.id"
                class="w-full px-3 py-2 text-left text-xs transition-colors flex items-center gap-2 cursor-pointer"
                :class="profile.id === currentProfileId ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'"
                @click="selectProfile(profile.id)"
              >
                <svg v-if="profile.id === currentProfileId" class="w-4 h-4 text-accent-hi flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
                <span v-else class="w-4 h-4 flex-shrink-0"></span>
                <span class="truncate flex-1">{{ profile.name }}</span>
                <!-- Unlocked icon - profile has PIN and is currently unlocked (cached) -->
                <button
                  v-if="profile.has_pin && hasCachedPin(profile.id)"
                  @click.stop="lockProfile(profile.id)"
                  class="p-1 -mr-1 rounded hover:bg-overlay-light transition-colors"
                  title="Lock profile"
                >
                  <svg class="w-3.5 h-3.5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 10.5V6.75a4.5 4.5 0 1 1 9 0v3.75M3.75 21.75h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                  </svg>
                </button>
                <!-- Locked icon - profile has PIN but is locked (not cached) -->
                <svg
                  v-else-if="profile.has_pin"
                  class="w-3.5 h-3.5 text-content-muted flex-shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="2"
                  stroke="currentColor"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                </svg>
              </div>
              <!-- Manage Profiles -->
              <button
                @click="openProfilesSettings"
                class="w-full px-3 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content flex items-center gap-2.5 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
                </svg>
                <span>Manage Profiles</span>
              </button>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <!-- Failed Items Modal -->
    <Modal :show="showModal" size="custom" custom-class="max-w-[800px] w-[90%] max-h-[80vh] flex flex-col" @close="closeModal">
      <template #header>
        <div class="flex justify-between items-center">
          <h2 class="m-0 text-xl font-semibold text-content">{{ modalTitle }}</h2>
          <div class="flex gap-3 items-center">
            <!-- Retry All button -->
            <button
              v-if="failedItems.length > 0 && !loadingFailed"
              class="flex items-center gap-2 bg-gradient-to-br from-green-500 to-green-600 border-none text-white px-4 py-2 rounded-md text-sm font-semibold cursor-pointer transition-all hover:from-green-600 hover:to-green-700 hover:shadow-[0_4px_12px_rgba(76,175,80,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
              @click="retryAll"
              :disabled="retrying || trashing"
            >
              <svg v-if="!retrying" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
              <span v-if="retrying">Retrying...</span>
              <span v-else>Retry All</span>
            </button>
            <!-- Move to Trash button -->
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
              <span>Trash All</span>
            </button>
            <button class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center transition-colors hover:text-content" @click="closeModal">
              <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      </template>

      <div class="p-6 overflow-y-auto flex-1">
        <div v-if="loadingFailed" class="text-center text-content-tertiary p-8 text-sm">Loading failed items...</div>
        <div v-else-if="failedItems.length === 0" class="text-center text-content-tertiary p-8 text-sm">No failed items found.</div>
        <div v-else class="flex flex-col gap-4">
          <div v-for="item in failedItems" :key="item.id" class="bg-overlay-subtle border border-edge rounded-lg p-4 flex gap-4">
            <!-- Thumbnail -->
            <div class="w-12 h-12 flex-shrink-0 rounded-md overflow-hidden bg-surface-raised">
              <img
                v-if="item.file_hash"
                :src="getThumbnailUrl(item.file_hash, 64)"
                :class="['w-full h-full object-cover', item.has_alpha !== false ? 'bg-checker' : '']"
                @error="$event.target.style.display = 'none'"
              />
              <div v-else class="w-full h-full flex items-center justify-center text-content-muted">
                <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
                </svg>
              </div>
            </div>
            <!-- Content -->
            <div class="flex-1 min-w-0">
              <div class="flex justify-between items-start gap-3 mb-2">
                <span class="font-semibold text-content text-sm">{{ getFileName(item.file_path) }}</span>
                <button
                  class="flex items-center gap-1.5 bg-gradient-to-br from-green-500 to-green-600 border-none text-white px-2.5 py-1.5 rounded text-xs font-medium cursor-pointer transition-all hover:from-green-600 hover:to-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                  @click="retryItem(item.id)"
                  :disabled="retrying || trashing"
                  title="Retry this item"
                >
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                  </svg>
                  Retry
                </button>
              </div>
              <div class="text-red-500 text-xs font-mono bg-red-500/10 px-2.5 py-1.5 rounded border-l-2 border-red-500 mb-2">{{ item.error || 'Unknown error' }}</div>
              <div class="text-xs text-content-muted font-mono truncate" :title="item.file_path">{{ item.file_path }}</div>
            </div>
          </div>
        </div>
      </div>
    </Modal>

    <WhatsNewModal
      :show="whatsNewOpen"
      :markdown="notesMarkdown"
      :version="notesVersion"
      @close="closeWhatsNew"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useDeleteOperations } from '../composables/useDeleteOperations'
import { useWebSocket } from '../composables/useWebSocket'
import { useProfile, openProfileWindow } from '../composables/useProfile'
import { getSavedRouteForProfile } from '../composables/useRouteRestore'
import { useMediaApi } from '../composables/useMediaApi'
import { clearCachedPin, hasCachedPin } from '../composables/usePinLock'
import { makeGlobalKey } from '../utils/storageKeys'
import { useAppUpdater } from '../composables/useAppUpdater'
import { useReleaseNotes } from '../composables/useReleaseNotes'
import WhatsNewModal from './WhatsNewModal.vue'
import { captioningEnabledRef } from '../appConfig'
import GlobalSearchBox from './search/GlobalSearchBox.vue'
import Spinner from './ui/Spinner.vue'
import Modal from './ui/Modal.vue'
import { formatEta } from '../utils/timeFormat'

const router = useRouter()
const route = useRoute()

const emit = defineEmits(['open-settings'])

// Navigation history tracking
const navHistory = ref([])
const navIndex = ref(-1)
let isNavAction = false

const canGoBack = computed(() => navIndex.value > 0)
const canGoForward = computed(() => navIndex.value < navHistory.value.length - 1)

function goBack() {
  if (!canGoBack.value) return
  isNavAction = true
  navIndex.value--
  router.push(navHistory.value[navIndex.value])
}

function goForward() {
  if (!canGoForward.value) return
  isNavAction = true
  navIndex.value++
  router.push(navHistory.value[navIndex.value])
}

// Track route changes
router.afterEach((to) => {
  if (isNavAction) {
    isNavAction = false
    return
  }
  // Normal navigation: truncate forward history and push new entry
  navHistory.value = navHistory.value.slice(0, navIndex.value + 1)
  navHistory.value.push(to.fullPath)
  navIndex.value = navHistory.value.length - 1
})

// WebSocket connection
const { connected: wsConnected, on: wsOn } = useWebSocket()
const {
  deleteSummary,
  hasActiveDeleteOperation,
  deleteProgressPercent,
  refreshActiveDeleteOperation,
  retryFailedDeleteOperation,
} = useDeleteOperations()
const retryingDeletion = ref(false)

async function retryDeletion() {
  retryingDeletion.value = true
  try {
    await retryFailedDeleteOperation()
  } finally {
    retryingDeletion.value = false
  }
}

// Media API for thumbnails
const { getThumbnailUrl } = useMediaApi()

// Profile management
const {
  currentProfileId,
  profiles,
  isLoadingProfiles,
  setCurrentProfileId,
  loadProfiles,
} = useProfile()

// Theme

// Updates
const {
  hasUpdate,
  pendingRestart,
  isDownloading,
  updatesBlockedByPrivacyLockdown,
  downloadAndInstallUpdate,
  restartToApply,
} = useAppUpdater()

const {
  notesMarkdown,
  notesVersion,
  hasUnseenNotes,
  whatsNewOpen,
  openWhatsNew,
  closeWhatsNew,
} = useReleaseNotes()

// Update pill: rests as a compact icon; peeks open for a few seconds when the
// state changes, and expands on hover. Width is measured from the label so the
// expand animation has a concrete px target.
const updateState = computed(() => {
  if (isDownloading.value) return 'downloading'
  if (pendingRestart.value) return 'restart'
  if (hasUpdate.value) return 'available'
  // Lowest priority: release notes for the version we're already running.
  if (hasUnseenNotes.value) return 'whatsnew'
  return null
})
const updatePillLabel = computed(() => {
  switch (updateState.value) {
    case 'downloading': return 'Updating…'
    case 'restart': return 'Restart to update'
    case 'available': return 'Update available'
    case 'whatsnew': return "What's new"
    default: return ''
  }
})
const updatePillLabelEl = ref(null)
const updatePillHover = ref(false)
const updatePillPeek = ref(false)
const updatePillWidth = ref('28px')
const updatePillExpanded = computed(() => updatePillHover.value || updatePillPeek.value)
let updatePillPeekTimer

watch(updateState, async (state) => {
  if (!state) {
    updatePillPeek.value = false
    return
  }
  await nextTick()
  const label = updatePillLabelEl.value
  // 26px icon well + label + 12px right padding + 2px borders
  if (label) updatePillWidth.value = `${26 + label.scrollWidth + 12 + 2}px`
  clearTimeout(updatePillPeekTimer)
  updatePillPeek.value = true
  updatePillPeekTimer = setTimeout(() => { updatePillPeek.value = false }, 3000)
}, { immediate: true })

function onUpdatePillClick() {
  if (updateState.value === 'available') downloadAndInstallUpdate()
  else if (updateState.value === 'restart') restartToApply()
  else if (updateState.value === 'whatsnew') openWhatsNew()
}

// Profile picker menu
const profileMenuOpen = ref(false)

const currentProfileName = computed(() => {
  const current = profiles.value.find(p => p.id === currentProfileId.value)
  return current?.name || 'Profile'
})

function closeProfileMenu() {
  profileMenuOpen.value = false
  document.removeEventListener('click', handleProfileClickOutside)
}

function toggleProfileMenu() {
  profileMenuOpen.value = !profileMenuOpen.value
  if (profileMenuOpen.value) {
    setTimeout(() => {
      document.addEventListener('click', handleProfileClickOutside)
    }, 0)
  } else {
    document.removeEventListener('click', handleProfileClickOutside)
  }
}

function handleProfileClickOutside(event) {
  const menu = event.target.closest('.profile-menu')
  if (!menu && profileMenuOpen.value) {
    closeProfileMenu()
  }
}

const { track: trackTelemetry } = useTelemetry()

async function selectProfile(profileId) {
  closeProfileMenu()

  if (profileId === currentProfileId.value) return

  trackTelemetry('profile_switched', {}, 'settings')

  // Desktop app: browser-style switching — each profile lives in its own
  // window, so open (or focus) the target profile's window and leave this
  // window on its current profile.
  if (await openProfileWindow(profileId)) return

  // Land on the target profile's last location (its own per-profile route),
  // not the current profile's URL — which points at objects that don't exist
  // in the profile we're switching to. This reloads to refresh profile-scoped
  // data; the lock screen still shows if the target profile requires a PIN.
  const targetRoute = getSavedRouteForProfile(profileId)
  setCurrentProfileId(profileId)
  window.location.href = targetRoute
}

function openProfilesSettings() {
  closeProfileMenu()
  emit('open-settings', 'profiles')
}

function lockProfile(profileId) {
  trackTelemetry('profile_locked', {}, 'settings')
  clearCachedPin(profileId)
  closeProfileMenu()
  // If locking the current profile, reload to trigger lock screen
  if (profileId === currentProfileId.value) {
    window.location.reload()
  }
}

const stats = ref({
  metadata: { pending: 0, processing: 0, completed: 0, failed: 0 },
  clip: { pending: 0, processing: 0, completed: 0, failed: 0 },
  face_detection: { pending: 0, processing: 0, completed: 0, failed: 0 },
  vlm_caption: { pending: 0, processing: 0, completed: 0, failed: 0 },
})

const systemWarnings = ref([])

const isExpanded = ref(false)
const showModal = ref(false)
const failedItems = ref([])
const loadingFailed = ref(false)
const retrying = ref(false)
const trashing = ref(false)
const rescanning = ref(false)
const isPaused = ref(false)
const currentPhase = ref('')
const statsLoading = ref(true)
let unsubscribeStats = null
let unsubscribeSystemWarning = null
let unsubscribeSystemWarningCleared = null

const API_URL = import.meta.env.VITE_API_URL || ''

const PHASE_NAMES = {
  'metadata': 'Reading Files',
  'clip': 'Visual Indexing',
  'face_detection': 'Face Analysis',
  'vlm_caption': 'Visual Analysis'
}

const modalTitle = computed(() => {
  return `${PHASE_NAMES[currentPhase.value] || currentPhase.value}`
})

async function fetchStats() {
  try {
    const response = await axios.get(`${API_URL}/api/processing/stats`)
    stats.value = response.data.phase_stats
    statsLoading.value = false
  } catch (error) {
    console.error('Failed to fetch processing stats:', error)
  }
}

function getTotalForPhase(phase) {
  const phaseStats = stats.value[phase]
  if (!phaseStats) return 0
  return (phaseStats.pending || 0) + (phaseStats.processing || 0) + (phaseStats.completed || 0) + (phaseStats.failed || 0)
}

function getProgressPercent(phase) {
  const total = getTotalForPhase(phase)
  if (total === 0) return 0
  const completed = stats.value[phase]?.completed || 0
  return Math.round((completed / total) * 100)
}

function hasPendingWork(phase) {
  const phaseStats = stats.value[phase]
  if (!phaseStats) return false
  // Has pending work if there are pending items or incomplete total
  const total = getTotalForPhase(phase)
  const completed = phaseStats.completed || 0
  return total > completed
}

const activePhases = computed(() => {
  return Object.entries(stats.value)
    .filter(([key]) => key !== 'vlm_caption' || captioningEnabledRef.value)
    .map(([, phase]) => phase)
})

const totalPending = computed(() => {
  return activePhases.value.reduce((sum, phase) => sum + (phase.pending || 0), 0)
})

const totalProcessing = computed(() => {
  return activePhases.value.reduce((sum, phase) => sum + (phase.processing || 0), 0)
})

const totalCompleted = computed(() => {
  return activePhases.value.reduce((sum, phase) => sum + (phase.completed || 0), 0)
})

const totalFailed = computed(() => {
  return activePhases.value.reduce((sum, phase) => sum + (phase.failed || 0), 0)
})

const statusClass = computed(() => {
  if (totalProcessing.value > 0) return 'processing'
  if (totalFailed.value > 0) return 'warning'
  if (totalPending.value > 0) return 'pending'
  return 'done'
})

// New computed properties for redesigned UI
const hasActiveWork = computed(() => {
  // Only show when there's actual work happening or errors to handle
  // Hide completely when idle (nothing pending, nothing processing, no failures)
  return totalPending.value > 0 || totalProcessing.value > 0 || totalFailed.value > 0 || systemWarnings.value.length > 0 || hasActiveDeleteOperation.value
})

const isDeleteRunning = computed(() => {
  return deleteSummary.value?.status === 'running'
})

const hasDeleteFailed = computed(() => {
  return deleteSummary.value?.status === 'failed'
})

const hasDeleteCompleted = computed(() => {
  return deleteSummary.value?.status === 'completed'
})

const deleteTotalCount = computed(() => {
  const summary = deleteSummary.value
  if (!summary) return 0
  return summary.total_assets || 0
})

const deleteDoneCount = computed(() => {
  const summary = deleteSummary.value
  if (!summary) return 0
  return summary.processed_assets || 0
})

const isActivelyProcessing = computed(() => {
  return totalProcessing.value > 0
})

const hasIncompleteWork = computed(() => {
  // Has incomplete work if there's anything pending or processing
  return totalPending.value > 0 || totalProcessing.value > 0
})

const progressTitle = computed(() => {
  if (hasDeleteFailed.value) return 'Permanent deletion failed - click for details'
  if (hasDeleteCompleted.value) return 'Permanent deletion complete - click for details'
  if (isDeleteRunning.value) return 'Permanent deletion in progress - click for details'
  if (isPaused.value && hasIncompleteWork.value) return 'Processing paused - click for details'
  if (isActivelyProcessing.value) return 'Processing in progress - click for details'
  if (totalFailed.value > 0) return `${totalFailed.value} failed items - click for details`
  if (totalPending.value > 0) return `${totalPending.value} items pending - click for details`
  return 'Click for processing details'
})

const deleteOperationLabel = computed(() => {
  const summary = deleteSummary.value
  if (!summary) return ''
  if (summary.status === 'completed') return 'Complete'
  if (summary.status === 'failed') return `${summary.failed_assets || 0} failed`
  const remaining = deleteTotalCount.value - deleteDoneCount.value
  return `${remaining} remaining`
})

const summaryText = computed(() => {
  // 1. Loading
  if (statsLoading.value) {
    return 'Loading…'
  }

  const total = totalPending.value + totalProcessing.value + totalCompleted.value + totalFailed.value

  // 8. No items at all
  if (total === 0) {
    return 'Ready'
  }

  // 1.5 Paused with incomplete work
  if (isPaused.value && hasIncompleteWork.value) {
    return 'Paused'
  }

  // 2. Actively processing (only show if not paused)
  if (totalProcessing.value > 0 && !isPaused.value) {
    return 'Processing…'
  }

  // 3. Nothing completed yet and failures > 0
  if (totalCompleted.value === 0 && totalFailed.value > 0) {
    return `${totalFailed.value} failed`
  }

  const percentDone = Math.round((totalCompleted.value / total) * 100)
  const allDone = totalPending.value === 0 && totalProcessing.value === 0

  if (allDone) {
    // 6. All work completed, no failures
    if (totalFailed.value === 0) {
      return 'Done'
    }
    // 7. All work completed with failures
    return `Done · ${totalFailed.value} failed`
  }

  // 4. Some completed, some still pending
  if (totalFailed.value === 0) {
    return `${percentDone}% complete`
  }

  // 5. Some completed with failures
  return `${percentDone}% complete · ${totalFailed.value} failed`
})

function toggleExpanded(event) {
  event.stopPropagation()
  isExpanded.value = !isExpanded.value

  if (isExpanded.value) {
    // Use capture phase to ensure we always get the event
    setTimeout(() => {
      document.addEventListener('click', handleClickOutside, true)
    }, 0)
  } else {
    document.removeEventListener('click', handleClickOutside, true)
  }
}

function handleClickOutside(event) {
  const progressWidget = event.target.closest('.processing-indicator')
  if (!progressWidget && isExpanded.value) {
    isExpanded.value = false
    document.removeEventListener('click', handleClickOutside, true)
  }
}

async function handleRescan() {
  await triggerRescan()
}

async function handleTogglePause() {
  await togglePause()
}

async function showFailedItems(phase) {
  currentPhase.value = phase
  showModal.value = true
  loadingFailed.value = true
  failedItems.value = []

  try {
    const response = await axios.get(`${API_URL}/api/processing/failed/${phase}`)
    failedItems.value = response.data.items
  } catch (error) {
    console.error('Failed to fetch failed items:', error)
  } finally {
    loadingFailed.value = false
  }
}

async function retryAll() {
  retrying.value = true
  try {
    const response = await axios.post(`${API_URL}/api/processing/retry/${currentPhase.value}`)
    console.log(`Retried ${response.data.retried_count} items`)
    await showFailedItems(currentPhase.value)
    await fetchStats()
  } catch (error) {
    console.error('Failed to retry items:', error)
  } finally {
    retrying.value = false
  }
}

async function retryItem(itemId) {
  retrying.value = true
  try {
    const response = await axios.post(`${API_URL}/api/processing/retry/${currentPhase.value}`, {
      item_ids: [itemId]
    })
    console.log(`Retried item ${itemId}`)
    await showFailedItems(currentPhase.value)
    await fetchStats()
  } catch (error) {
    console.error(`Failed to retry item ${itemId}:`, error)
  } finally {
    retrying.value = false
  }
}

async function trashAll() {
  trashing.value = true
  try {
    const response = await axios.post(`${API_URL}/api/processing/trash/${currentPhase.value}`)
    console.log(`Trashed ${response.data.trashed_count} items`)
    // Refresh stats first, then check if any items remain
    await fetchStats()
    // Refresh the failed items list - if empty, close modal
    await showFailedItems(currentPhase.value)
    if (failedItems.value.length === 0) {
      closeModal()
    }
  } catch (error) {
    console.error('Failed to trash items:', error)
  } finally {
    trashing.value = false
  }
}

function closeModal() {
  showModal.value = false
  failedItems.value = []
  currentPhase.value = ''
}

function getFileName(path) {
  return path.split('/').pop()
}

async function togglePause() {
  try {
    if (isPaused.value) {
      await axios.post(`${API_URL}/api/processing/resume`)
      isPaused.value = false
      console.log('Background processing resumed')
    } else {
      await axios.post(`${API_URL}/api/processing/pause`)
      isPaused.value = true
      console.log('Background processing paused')
    }
  } catch (error) {
    console.error('Failed to toggle pause:', error)
  }
}

async function fetchPauseStatus() {
  try {
    const response = await axios.get(`${API_URL}/api/processing/status`)
    isPaused.value = response.data.paused
  } catch (error) {
    console.error('Failed to fetch pause status:', error)
  }
}

function isSystemWarningDismissed(type) {
  return localStorage.getItem(makeGlobalKey('dismissed_warning', type)) === 'true'
}

function dismissSystemWarning(type) {
  localStorage.setItem(makeGlobalKey('dismissed_warning', type), 'true')
  systemWarnings.value = systemWarnings.value.filter(w => w.type !== type)
}

async function fetchSystemWarnings() {
  // Broadcasts are missed if the websocket reconnects at the wrong moment,
  // so also check current state directly on mount.
  try {
    const response = await axios.get(`${API_URL}/api/processing/warnings`)
    for (const warning of response.data?.warnings || []) {
      if (isSystemWarningDismissed(warning.type)) continue
      const exists = systemWarnings.value.some(w => w.type === warning.type)
      if (!exists) {
        systemWarnings.value.push(warning)
      }
    }
  } catch (error) {
    console.error('Failed to fetch system warnings:', error)
  }
}

async function triggerRescan() {
  rescanning.value = true
  try {
    const response = await axios.post(`${API_URL}/api/rescan`)
    console.log('Rescan triggered:', response.data)
    await fetchStats()
  } catch (error) {
    console.error('Failed to trigger rescan:', error)
  } finally {
    rescanning.value = false
  }
}

onMounted(() => {
  // Seed navigation history with current route
  if (navHistory.value.length === 0) {
    navHistory.value.push(route.fullPath)
    navIndex.value = 0
  }

  fetchStats()
  fetchPauseStatus()
  loadProfiles()
  refreshActiveDeleteOperation()
  fetchSystemWarnings()

  // WebSocket broadcasts aggregate stats across ALL profiles
  // Use it as a trigger to re-fetch profile-specific stats from API
  unsubscribeStats = wsOn('processing_stats', () => {
    fetchStats()
  })

  // Subscribe to system warnings
  unsubscribeSystemWarning = wsOn('system_warning', (data) => {
    // Add warning if not already present and not dismissed forever
    if (isSystemWarningDismissed(data.type)) return
    const exists = systemWarnings.value.some(w => w.type === data.type)
    if (!exists) {
      systemWarnings.value.push({
        type: data.type,
        title: data.title || 'System Warning',
        message: data.message || '',
        action_url: data.action_url || ''
      })
    }
  })

  // Subscribe to system warning cleared events
  unsubscribeSystemWarningCleared = wsOn('system_warning_cleared', (data) => {
    // Remove warning from array
    systemWarnings.value = systemWarnings.value.filter(w => w.type !== data.type)
  })
})

// Reload topbar data when websocket reconnects
// This handles the case where backend was down and comes back up
watch(wsConnected, (connected, wasConnected) => {
  if (connected && wasConnected === false) {
    console.log('[TopBar] WebSocket reconnected, reloading topbar data')
    fetchStats()
    fetchPauseStatus()
    refreshActiveDeleteOperation()
    loadProfiles()
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('click', handleProfileClickOutside)
})

onUnmounted(() => {
  if (unsubscribeStats) {
    unsubscribeStats()
  }
  if (unsubscribeSystemWarning) {
    unsubscribeSystemWarning()
  }
  if (unsubscribeSystemWarningCleared) {
    unsubscribeSystemWarningCleared()
  }
})
</script>

<style scoped>
/* Expand transition */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

</style>
