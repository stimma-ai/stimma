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
        <div v-else-if="isActivelyProcessing && !isPaused" class="w-5 h-5 border-2 border-edge-strong border-t-white/80 rounded-full animate-spin"></div>
        <!-- Red warning triangle when there are errors -->
        <svg v-else-if="totalFailed > 0" class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
        </svg>
        <!-- Yellow warning triangle when only system warnings present -->
        <svg v-else-if="systemWarnings.length > 0 && totalPending === 0 && totalProcessing === 0" class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
        </svg>
        <!-- Yellow pending indicator (pending but not processing) -->
        <div v-else class="w-5 h-5 border-2 border-yellow-500/30 border-t-yellow-500 rounded-full animate-spin"></div>

        <transition name="expand">
          <div v-if="isExpanded && statsLoading" class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge rounded-lg p-4 min-w-[400px] shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-[10000]">
            <div class="p-8 text-center text-content-muted text-sm">Loading progress data...</div>
          </div>
          <div v-else-if="isExpanded" class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge rounded-lg p-4 min-w-[400px] shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-[10000]">
            <div v-if="activeDeleteOperation" class="mb-4 pb-4 border-b border-surface-raised">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  {{ activeDeleteOperation.status === 'completed' ? 'Deletion Complete' : activeDeleteOperation.status === 'failed' ? 'Deletion Failed' : 'Permanently Deleting' }}
                  <span v-if="activeDeleteOperation.status === 'running'" class="w-3 h-3 border-2 border-edge border-t-white/80 rounded-full animate-spin"></span>
                </span>
                <span class="text-xs text-content-tertiary">
                  <span class="text-red-400 font-semibold">{{ activeDeleteOperation.processed_items || 0 }}</span> /
                  <span class="text-content-muted">{{ activeDeleteOperation.total_items || 0 }}</span>
                </span>
              </div>
              <div class="mb-2">
                <div class="h-1.5 bg-surface-raised rounded overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-red-500 to-orange-400 rounded transition-[width] duration-500" :style="{ width: `${deleteProgressPercent}%` }"></div>
                </div>
              </div>
              <div class="flex items-center justify-between text-[0.6875rem] text-content-tertiary">
                <span>{{ deleteOperationLabel }}</span>
                <span v-if="activeDeleteOperation.eta_seconds">ETA {{ formatEta(activeDeleteOperation.eta_seconds) }}</span>
              </div>
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
                <div class="font-medium">{{ warning.title }}</div>
                <div class="text-content-tertiary">{{ warning.message }}</div>
                <a :href="warning.action_url" target="_blank" class="text-blue-500 hover:underline">
                  Installation instructions →
                </a>
              </div>
            </div>

            <!-- Metadata Phase -->
            <div class="mb-4 pb-4 border-b border-surface-raised last:mb-0 last:pb-0 last:border-b-0">
              <div class="flex justify-between items-center mb-2">
                <span class="flex items-center gap-2 text-sm font-semibold text-content">
                  Processing Media
                  <span v-if="stats.metadata?.processing > 0" class="w-3 h-3 border-2 border-edge border-t-white/80 rounded-full animate-spin"></span>
                </span>
                <span class="text-xs text-content-tertiary">
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
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:scale-105 hover:opacity-80" @click.stop="showFailedItems('metadata')">
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
                  <span v-else-if="stats.clip?.processing > 0" class="w-3 h-3 border-2 border-edge border-t-white/80 rounded-full animate-spin"></span>
                </span>
                <span class="text-xs text-content-tertiary">
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
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:scale-105 hover:opacity-80" @click.stop="showFailedItems('clip')">
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
                  <span v-else-if="stats.face_detection?.processing > 0" class="w-3 h-3 border-2 border-edge border-t-white/80 rounded-full animate-spin"></span>
                </span>
                <span class="text-xs text-content-tertiary">
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
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:scale-105 hover:opacity-80" @click.stop="showFailedItems('face_detection')">
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
                  <span v-else-if="stats.vlm_caption?.processing > 0" class="w-3 h-3 border-2 border-edge border-t-white/80 rounded-full animate-spin"></span>
                </span>
                <span class="text-xs text-content-tertiary">
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
                <span class="text-[0.6875rem] px-2 py-1 rounded bg-red-500/20 text-red-500 border border-red-500/30 font-medium cursor-pointer transition-all hover:scale-105 hover:opacity-80" @click.stop="showFailedItems('vlm_caption')">
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
                <div v-else class="w-4 h-4 border-2 border-edge-strong border-t-white rounded-full animate-spin"></div>
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

      <!-- Logo menu -->
      <div class="relative logo-menu">
        <button
          class="relative w-8 h-8 flex items-center justify-center rounded transition-all cursor-pointer hover:bg-overlay-subtle"
          @click="toggleLogoMenu"
          :title="wsConnected ? 'Connected to server' : 'Disconnected from server'"
        >
          <img
            src="/logo.png"
            alt="Stimma"
            class="w-7 h-7"
            :class="{ 'logo-disconnected': !wsConnected }"
          />
          <span
            v-if="hasUpdate"
            class="absolute -top-0.5 -right-0.5 w-3 h-3 bg-green-500 rounded-full border-2 border-base"
          />
        </button>

        <transition name="dropdown">
          <div
            v-if="logoMenuOpen"
            class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-[10000] min-w-[220px] overflow-hidden"
          >
            <!-- Profile list -->
            <div v-if="profiles.length > 0" class="py-1">
              <div
                v-for="profile in profiles"
                :key="profile.id"
                class="w-full px-3 py-2 text-left text-sm transition-colors flex items-center gap-2 cursor-pointer"
                :class="profile.id === currentProfileId ? 'bg-overlay-light text-content' : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'"
                @click="selectProfile(profile.id)"
              >
                <svg v-if="profile.id === currentProfileId" class="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
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

            <!-- Divider after profiles -->
            <div v-if="profiles.length > 0" class="border-t border-edge-subtle"></div>

            <!-- Theme switcher row -->
            <div class="px-3 py-2.5 flex items-center gap-1.5">
              <button
                @click.stop="selectTheme('light')"
                class="flex items-center justify-center w-8 h-8 rounded-md transition-all border"
                :class="currentTheme === 'light'
                  ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
                  : 'bg-surface-raised border-edge text-content-tertiary hover:text-content hover:border-edge-strong'"
                title="Light"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                </svg>
              </button>
              <button
                @click.stop="selectTheme('dark')"
                class="flex items-center justify-center w-8 h-8 rounded-md transition-all border"
                :class="currentTheme === 'dark'
                  ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
                  : 'bg-surface-raised border-edge text-content-tertiary hover:text-content hover:border-edge-strong'"
                title="Dark"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                </svg>
              </button>
              <button
                @click.stop="selectTheme('system')"
                class="flex items-center justify-center w-8 h-8 rounded-md transition-all border"
                :class="currentTheme === 'system'
                  ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
                  : 'bg-surface-raised border-edge text-content-tertiary hover:text-content hover:border-edge-strong'"
                title="System"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z" />
                </svg>
              </button>
            </div>

            <!-- Divider -->
            <div class="border-t border-edge-subtle"></div>

            <LogoFeedbackMenu
              @close-menu="closeLogoMenu"
              @ensure-menu-open="ensureLogoMenuOpen"
            />

            <!-- Settings -->
            <div class="py-1">
              <button
                @click="openSettings"
                class="w-full px-3 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content flex items-center gap-2.5 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                </svg>
                <span>Settings</span>
              </button>
            </div>

            <!-- Update available -->
            <template v-if="hasUpdate">
              <div class="border-t border-edge-subtle"></div>
              <div class="py-1">
                <template v-if="isDownloading">
                  <div class="w-full px-3 py-2 text-left text-sm text-content-tertiary flex items-center gap-2.5">
                    <div class="w-4 h-4 border-2 border-content-muted border-t-blue-500 rounded-full animate-spin"></div>
                    <span>Installing update...</span>
                  </div>
                </template>
                <template v-else>
                  <button
                    @click="handleInstallUpdate"
                    class="w-full px-3 py-2 text-left text-sm text-blue-500 hover:bg-overlay-subtle flex items-center gap-2.5 transition-colors"
                  >
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    <span>Update available</span>
                  </button>
                </template>
              </div>
            </template>
          </div>
        </transition>
      </div>
    </div>

    <!-- Failed Items Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="fixed inset-0 bg-black/80 flex items-center justify-center z-[20000]" @click="closeModal">
        <div class="bg-surface border border-edge rounded-lg max-w-[800px] w-[90%] max-h-[80vh] flex flex-col shadow-[0_20px_40px_rgba(0,0,0,0.5)]" @click.stop>
          <div class="flex justify-between items-center p-6 border-b border-edge">
            <h2 class="m-0 text-xl font-semibold text-content">{{ modalTitle }}</h2>
            <div class="flex gap-3 items-center">
              <!-- Retry All button -->
              <button
                v-if="failedItems.length > 0 && !loadingFailed"
                class="flex items-center gap-2 bg-gradient-to-br from-green-500 to-green-600 border-none text-white px-4 py-2 rounded-md text-sm font-semibold cursor-pointer transition-all hover:from-green-600 hover:to-green-700 hover:-translate-y-px hover:shadow-[0_4px_12px_rgba(76,175,80,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
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
                <div v-else class="w-4 h-4 border-2 border-edge-strong border-t-white rounded-full animate-spin"></div>
                <span>Trash All</span>
              </button>
              <button class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center transition-colors hover:text-content" @click="closeModal">
                <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
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
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onBeforeUnmount, watch } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useDeleteOperations } from '../composables/useDeleteOperations'
import { useWebSocket } from '../composables/useWebSocket'
import { useProfile } from '../composables/useProfile'
import { useMediaApi } from '../composables/useMediaApi'
import { clearCachedPin, hasCachedPin } from '../composables/usePinLock'
import { useTheme } from '../composables/useTheme'
import { useSettingsApi } from '../composables/useSettingsApi'
import { useAppUpdater } from '../composables/useAppUpdater'
import { captioningEnabledRef } from '../appConfig'
import LogoFeedbackMenu from '@stimma/logo-feedback-menu'
import GlobalSearchBox from './search/GlobalSearchBox.vue'

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
const { activeDeleteOperation, hasActiveDeleteOperation, deleteProgressPercent, refreshActiveDeleteOperation } = useDeleteOperations()

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
const { themePreference: currentTheme, setTheme } = useTheme()
const { updateTheme } = useSettingsApi()

// Updates
const { hasUpdate, isDownloading, downloadAndInstallUpdate } = useAppUpdater()

// Logo menu
const logoMenuOpen = ref(false)

function closeLogoMenu() {
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)
}

function ensureLogoMenuOpen() {
  if (!logoMenuOpen.value) toggleLogoMenu()
}

function toggleLogoMenu() {
  logoMenuOpen.value = !logoMenuOpen.value
  if (logoMenuOpen.value) {
    setTimeout(() => {
      document.addEventListener('click', handleLogoClickOutside)
    }, 0)
  } else {
    document.removeEventListener('click', handleLogoClickOutside)
  }
}

function handleLogoClickOutside(event) {
  const menu = event.target.closest('.logo-menu')
  if (!menu && logoMenuOpen.value) {
    closeLogoMenu()
  }
}

function selectTheme(theme) {
  setTheme(theme)
  // Fire-and-forget persist to server
  updateTheme(theme).catch(err => console.error('Failed to persist theme:', err))
}

function openSettings() {
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)
  emit('open-settings')
}

const { track: trackTelemetry } = useTelemetry()

function selectProfile(profileId) {
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)

  if (profileId === currentProfileId.value) return

  trackTelemetry('profile_switched', {}, 'settings')

  setCurrentProfileId(profileId)
  // Reload page - lock screen will show if profile requires PIN
  window.location.reload()
}

function openProfilesSettings() {
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)
  emit('open-settings', 'profiles')
}

function handleInstallUpdate() {
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)
  downloadAndInstallUpdate()
}

function lockProfile(profileId) {
  trackTelemetry('profile_locked', {}, 'settings')
  clearCachedPin(profileId)
  logoMenuOpen.value = false
  document.removeEventListener('click', handleLogoClickOutside)
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

const isActivelyProcessing = computed(() => {
  return totalProcessing.value > 0
})

const hasIncompleteWork = computed(() => {
  // Has incomplete work if there's anything pending or processing
  return totalPending.value > 0 || totalProcessing.value > 0
})

const progressTitle = computed(() => {
  if (hasActiveDeleteOperation.value) return 'Permanent delete in progress - click for details'
  if (isPaused.value && hasIncompleteWork.value) return 'Processing paused - click for details'
  if (isActivelyProcessing.value) return 'Processing in progress - click for details'
  if (totalFailed.value > 0) return `${totalFailed.value} failed items - click for details`
  if (totalPending.value > 0) return `${totalPending.value} items pending - click for details`
  return 'Click for processing details'
})

const deleteOperationLabel = computed(() => {
  const op = activeDeleteOperation.value
  if (!op) return ''
  if (op.status === 'queued') return 'Queued'
  if (op.current_phase === 'scrubbing_refs') return 'Scrubbing references'
  if (op.current_phase === 'purging_cache') return 'Purging cache'
  if (op.current_phase === 'deleting_media_row') return 'Deleting media rows'
  if (op.current_phase === 'claiming') return 'Claiming batch'
  if (op.failed_items > 0 && op.status === 'failed') return `${op.failed_items} failed`
  return 'Running'
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

async function fetchSystemWarnings() {
  // Broadcasts are missed if the websocket reconnects at the wrong moment,
  // so also check current state directly on mount.
  try {
    const response = await axios.get(`${API_URL}/api/processing/warnings`)
    for (const warning of response.data?.warnings || []) {
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
    // Add warning if not already present
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
  document.removeEventListener('click', handleLogoClickOutside)
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
/* Logo disconnected animation - pendulum swing (matches Tauri loading screen) */
.logo-disconnected {
  animation: logo-pendulum 2.4s ease-in-out infinite;
}

@keyframes logo-pendulum {
  0%, 100% { transform: rotate(-175deg); }
  50% { transform: rotate(175deg); }
}

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

/* Dropdown transition */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
