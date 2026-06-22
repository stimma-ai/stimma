<template>
  <Teleport to="body">
    <!-- SVG gradient definition for Stimma Cloud branding (must be inside Teleport to be accessible) -->
    <svg class="absolute w-0 h-0" aria-hidden="true">
      <defs>
        <linearGradient id="stimma-gradient-context" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0d9488" />
          <stop offset="50%" stop-color="#06b6d4" />
          <stop offset="100%" stop-color="#6366f1" />
        </linearGradient>
      </defs>
    </svg>
    <div
      v-if="contextMenu.state.value.visible"
      ref="menuRef"
      data-context-menu
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10020] py-1 min-w-[180px]"
      :style="menuPosition"
    >
      <!-- Loading state -->
      <div v-if="loadingItem" class="px-3 py-2 text-xs text-content-tertiary">
        Loading...
      </div>

      <!-- Trash View Actions -->
      <template v-else-if="isTrashed">
        <!-- Find Similar (works for trashed items too, up to 3 items) -->
        <button
          v-if="hasClipEmbedding && targetCount <= 3"
          @click="handleFindSimilar"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
          </svg>
          <span>Find Similar</span>
        </button>

        <div v-if="hasClipEmbedding && targetCount <= 3" class="border-t border-edge-subtle my-1"></div>

        <button
          v-if="hasFaceEmbeddings"
          @click="handleFindSimilarFaces"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M10 2a6 6 0 00-6 6v1.5A4.5 4.5 0 008.5 14h3A4.5 4.5 0 0016 9.5V8a6 6 0 00-6-6Zm-2 7a1 1 0 110-2 1 1 0 010 2Zm4 0a1 1 0 110-2 1 1 0 010 2Zm-3.8 2.4a.75.75 0 011.06-.1c.42.35 1.06.35 1.48 0a.75.75 0 11.96 1.16 2.65 2.65 0 01-3.4 0 .75.75 0 01-.1-1.06Z" />
            <path d="M15.25 14.25l2.5 2.5a.75.75 0 11-1.06 1.06l-2.5-2.5a.75.75 0 111.06-1.06Z" />
          </svg>
          <span>Find Similar Faces</span>
        </button>

        <button
          @click="handleRestore"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M7.793 2.232a.75.75 0 01-.025 1.06L3.622 7.25h10.003a5.375 5.375 0 010 10.75H10.75a.75.75 0 010-1.5h2.875a3.875 3.875 0 000-7.75H3.622l4.146 3.957a.75.75 0 01-1.036 1.085l-5.5-5.25a.75.75 0 010-1.085l5.5-5.25a.75.75 0 011.06.025z" clip-rule="evenodd" />
          </svg>
          <span>{{ isMultiple ? `Restore ${targetCount} Items` : 'Restore' }}</span>
        </button>

        <button
          @click="handlePermanentDelete"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
          </svg>
          <span>{{ isMultiple ? `Delete ${targetCount} Permanently` : 'Delete Permanently' }}</span>
        </button>

      </template>

      <!-- Normal View Actions -->
      <template v-else>
        <!-- Marker toggles row -->
        <div v-if="markers.length > 0" class="flex items-center gap-1 px-2 py-1.5 border-b border-edge-subtle">
          <button
            v-for="marker in markers"
            :key="marker.id"
            @click="handleToggleMarker(marker)"
            :title="hasMarker(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
            :class="[
              'w-6 h-6 rounded flex items-center justify-center transition-colors',
              hasMarker(marker.id) ? 'bg-overlay-light' : 'hover:bg-overlay-subtle'
            ]"
          >
            <span
              class="w-4 h-4 icon-container"
              :style="{ color: hasMarker(marker.id) ? marker.color : '#6b7280' }"
              v-html="sanitizeSvg(marker.icon_svg)"
            />
          </button>
        </div>

        <!-- Tags -->
        <button
          @click="handleEditTags"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M4.5 2A2.5 2.5 0 002 4.5v3.879a2.5 2.5 0 00.732 1.767l7.5 7.5a2.5 2.5 0 003.536 0l3.878-3.878a2.5 2.5 0 000-3.536l-7.5-7.5A2.5 2.5 0 008.38 2H4.5zM5 6a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
          </svg>
          <span>{{ isMultiple ? `Tags (${targetCount} items)` : 'Tags' }}</span>
        </button>

        <!-- Boards -->
        <div
          class="relative"
          @mouseenter="openSubmenu('board', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="boardTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
              <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
            </svg>
            <span class="flex-1">{{ isMultiple ? `Boards (${targetCount} items)` : 'Boards' }}</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <div
            v-if="activeSubmenu === 'board'"
            class="fixed z-[10020]"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />

          <div
            v-if="activeSubmenu === 'board'"
            ref="boardSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10021] py-1 min-w-[260px] max-h-[420px] flex flex-col"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <div class="px-2 py-1.5 border-b border-edge-subtle flex-shrink-0">
              <div class="relative">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted">
                  <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
                </svg>
                <input
                  ref="boardSearchInputRef"
                  v-model="boardSearchQuery"
                  type="text"
                  placeholder="Find a board"
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
                />
              </div>
            </div>

            <div class="overflow-y-auto flex-1">
              <button
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                :disabled="creatingBoardQuickAdd"
                @click="handleCreateBoardQuickAdd"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
                  <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
                </svg>
                <span>{{ creatingBoardQuickAdd ? 'Creating...' : 'New board' }}</span>
              </button>

              <div class="border-t border-edge-subtle my-1"></div>

              <div v-if="loadingBoards" class="px-3 py-2 text-xs text-content-tertiary">Loading boards...</div>
              <div v-else-if="filteredBoards.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No matching boards</div>

              <button
                v-for="board in filteredBoards"
                :key="board.id"
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                :disabled="savingBoardQuickAddId === board.id"
                @click="handleQuickAddToBoard(board.id)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
                  <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
                </svg>
                <div class="min-w-0 flex-1">
                  <div class="truncate" :class="board.name ? 'text-content' : 'italic text-content-muted'">{{ board.name || 'Name this board...' }}</div>
                  <div class="truncate text-[10px] text-content-muted">{{ formatBoardSubmenuSummary(board) }}</div>
                </div>
              </button>
            </div>

          </div>
        </div>

        <!-- Projects -->
        <div
          class="relative"
          @mouseenter="openSubmenu('project', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="projectTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
            </svg>
            <span class="flex-1">{{ isMultiple ? `Projects (${targetCount} items)` : 'Projects' }}</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <div
            v-if="activeSubmenu === 'project'"
            class="fixed z-[10020]"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />

          <div
            v-if="activeSubmenu === 'project'"
            ref="projectSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10021] py-1 min-w-[260px]"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <ProjectPickerSubmenu
              :media-ids="targetIds"
              mode="assign"
              @added="handleProjectAdded"
              @close="contextMenu.hide(); activeSubmenu = null"
            />
          </div>
        </div>

        <!-- Remove from Project (only when viewing project assets) -->
        <template v-if="inProject">
          <button
            @click="handleRemoveFromProject"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
            </svg>
            <span>{{ isMultiple ? `Remove ${targetCount} from Project` : 'Remove from Project' }}</span>
          </button>
        </template>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Board-specific section -->
        <template v-if="inBoard">
          <button
            @click="handleRemoveFromBoard"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
              <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
            </svg>
            <span>{{ isMultiple ? `Remove ${targetCount} from Board` : 'Remove from Board' }}</span>
          </button>

          <div class="border-t border-edge-subtle my-1"></div>
        </template>

        <!-- Find Similar (up to 3 items) -->
        <button
          v-if="hasClipEmbedding && targetCount <= 3"
          @click="handleFindSimilar"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
          </svg>
          <span>Find Similar</span>
        </button>

        <button
          v-if="hasFaceEmbeddings"
          @click="handleFindSimilarFaces"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M10 2a6 6 0 00-6 6v1.5A4.5 4.5 0 008.5 14h3A4.5 4.5 0 0016 9.5V8a6 6 0 00-6-6Zm-2 7a1 1 0 110-2 1 1 0 010 2Zm4 0a1 1 0 110-2 1 1 0 010 2Zm-3.8 2.4a.75.75 0 011.06-.1c.42.35 1.06.35 1.48 0a.75.75 0 11.96 1.16 2.65 2.65 0 01-3.4 0 .75.75 0 01-.1-1.06Z" />
            <path d="M15.25 14.25l2.5 2.5a.75.75 0 11-1.06 1.06l-2.5-2.5a.75.75 0 111.06-1.06Z" />
          </svg>
          <span>Find Similar Faces</span>
        </button>

        <!-- Compare (exactly 2 images) -->
        <button
          v-if="targetCount === 2 && !isVideo"
          @click="handleCompare"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M8 16.25a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 1 0 1.5h-2.5a.75.75 0 0 1-.75-.75ZM3 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5Zm2-.5a.5.5 0 0 0-.5.5v10a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5V5a.5.5 0 0 0-.5-.5H5Z" />
            <path d="M10 3v14" stroke="currentColor" stroke-width="1.5" />
          </svg>
          <span>Compare</span>
        </button>

        <!-- View Lineage (single item only) -->
        <button
          v-if="!isMultiple"
          @click="handleViewLineage"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <circle cx="6" cy="4.5" r="1.75" stroke-width="1.5" />
            <circle cx="14" cy="4.5" r="1.75" stroke-width="1.5" />
            <circle cx="10" cy="15.5" r="1.75" stroke-width="1.5" />
            <path d="M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75" stroke-width="1.5" stroke-linecap="round" />
          </svg>
          <span>View Lineage</span>
        </button>

        <!-- Edit Image (single image only) -->
        <button
          v-if="isImage && !isMultiple"
          @click="handleEditImage"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z" />
          </svg>
          <span>Edit Image</span>
        </button>

        <!-- Create Set (multiple atomic items only) -->
        <button
          v-if="canCreateSet"
          @click="handleCreateSet"
          :disabled="creatingSet"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2 disabled:opacity-50"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
          </svg>
          <span>{{ creatingSet ? 'Creating...' : `Create Set (${targetCount} items)` }}</span>
        </button>

        <!-- Remix (single item only, not grids) - with submenu -->
        <div
          v-if="!isMultiple && !isGrid"
          class="relative"
          @mouseenter="openSubmenu('generate', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="generateTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <span class="flex-1">Remix</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Invisible bridge to submenu - prevents mouseleave when traversing gap -->
          <div
            v-if="activeSubmenu === 'generate'"
            class="fixed z-[10020]"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />

          <!-- Generate submenu -->
          <div
            v-if="activeSubmenu === 'generate'"
            ref="generateSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10021] py-1 min-w-[220px] max-h-[400px] flex flex-col"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <!-- Filter box -->
            <div class="px-2 py-1.5 border-b border-edge-subtle flex-shrink-0">
              <div class="relative">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted">
                  <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
                </svg>
                <input
                  ref="generateSearchInputRef"
                  v-model="generateSearchQuery"
                  type="text"
                  placeholder="Filter tools..."
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
                />
              </div>
            </div>

            <div class="overflow-y-auto flex-1">
              <div v-if="loadingGenerateTools" class="px-3 py-2 text-xs text-content-tertiary">Loading tools...</div>
              <div v-else-if="generateMoreTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No tools available</div>
              <template v-else-if="generateSearchQuery.trim()">
                <!-- Filtered results (flat, no sections) -->
                <div v-if="filteredGenerateTools.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No matching tools</div>
                <button
                  v-for="tool in filteredGenerateTools"
                  :key="tool.full_tool_id"
                  @click="sendToGenerateTool(tool)"
                  class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                >
                  <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-context)' : 'currentColor'" overflow="visible">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                  </svg>
                  <div class="flex-1 min-w-0">
                    <div class="truncate">{{ tool.name }}</div>
                    <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
                  </div>
                </button>
              </template>
              <template v-else>
                <!-- Original tool section (if exists) -->
                <template v-if="originalTool">
                  <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
                    Original
                  </div>
                  <button
                    @click="sendToGenerateTool(originalTool)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                  >
                    <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(originalTool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(originalTool) ? 'url(#stimma-gradient-context)' : 'currentColor'" overflow="visible">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                    </svg>
                    <div class="flex-1 min-w-0">
                      <div class="truncate">{{ originalTool.name }}</div>
                      <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(originalTool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ originalTool.provider_name }}</div>
                    </div>
                  </button>
                </template>

                <!-- Recent tools section -->
                <template v-if="recentGenerateTools.length > 0">
                  <div v-if="originalTool" class="border-t border-edge-subtle my-1"></div>
                  <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
                    Recent
                  </div>
                  <button
                    v-for="tool in recentGenerateTools"
                    :key="`recent-${tool.full_tool_id}`"
                    @click="sendToGenerateTool(tool)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                  >
                    <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-context)' : 'currentColor'" overflow="visible">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                    </svg>
                    <div class="flex-1 min-w-0">
                      <div class="truncate">{{ tool.name }}</div>
                      <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
                    </div>
                  </button>
                </template>

                <!-- All tools section -->
                <div v-if="originalTool || recentGenerateTools.length > 0" class="border-t border-edge-subtle my-1"></div>
                <div class="px-3 py-1.5 text-[10px] font-semibold text-content-muted uppercase tracking-wider">
                  {{ originalTool ? 'All Tools' : 'Generate Image' }}
                </div>
                <button
                  v-for="tool in otherGenerateTools"
                  :key="tool.full_tool_id"
                  @click="sendToGenerateTool(tool)"
                  class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
                >
                  <svg class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'" fill="none" viewBox="0 0 24 24" stroke-width="2" :stroke="isStimmaCloudTool(tool) ? 'url(#stimma-gradient-context)' : 'currentColor'" overflow="visible">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                  </svg>
                  <div class="flex-1 min-w-0">
                    <div class="truncate">{{ tool.name }}</div>
                    <div class="truncate text-[10px] leading-tight" :class="isStimmaCloudTool(tool) ? 'stimma-gradient-text' : 'text-content-muted'">{{ tool.provider_name }}</div>
                  </div>
                </button>
              </template>
            </div>
          </div>
        </div>

        <!-- Send to Tool - with submenu (hidden when grids are selected) -->
        <div
          v-if="!hasGridInSelection"
          class="relative"
          @mouseenter="openSubmenu('tool', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="toolTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
            </svg>
            <span class="flex-1">Send to Tool</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Invisible bridge to submenu -->
          <div
            v-if="activeSubmenu === 'tool'"
            class="fixed z-[10020]"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />

          <!-- Tool submenu (accordion with task type expand/collapse) -->
          <div
            v-if="activeSubmenu === 'tool'"
            ref="toolSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10021] py-1 min-w-[220px] max-h-[400px] overflow-y-auto"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop="lockSubmenuOpen"
          >
            <TaskTypeToolList
              ref="toolListRef"
              :tools="sendToTools"
              :media-type="currentMediaType"
              :loading="loadingTools"
              gradient-id="stimma-gradient-context"
              @select="handleToolSelect"
            />
          </div>
        </div>

        <!-- Send to Chat - with submenu -->
        <div
          class="relative"
          @mouseenter="openSubmenu('chat', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="chatTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
            </svg>
            <span class="flex-1">Send to Chat</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Invisible bridge to submenu -->
          <div
            v-if="activeSubmenu === 'chat'"
            class="fixed z-[10020]"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />

          <!-- Chat submenu -->
          <div
            v-if="activeSubmenu === 'chat'"
            ref="chatSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10021] py-1 min-w-[200px] max-h-[400px] overflow-y-auto"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <div v-if="loadingChats" class="px-3 py-2 text-xs text-content-tertiary">Loading chats...</div>
            <template v-else>
              <!-- New chat option -->
              <button
                @click="sendToNewChat"
                :class="['w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2', chats.length > 0 ? 'border-b border-edge-subtle' : '']"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary">
                  <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
                </svg>
                <span class="font-medium">New Chat</span>
              </button>
              <!-- Existing chats -->
              <button
                v-for="chat in chats"
                :key="chat.id"
                @click="sendToChat(chat)"
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
                </svg>
                <span class="truncate flex-1">{{ chat.name || 'Untitled' }}</span>
              </button>
            </template>
          </div>
        </div>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Explode action - only for sets/grids -->
        <button
          v-if="!isMultiple && isSetOrGrid"
          @click="handleExplode"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M10 1a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 1zM5.05 3.05a.75.75 0 011.06 0l1.062 1.06A.75.75 0 116.11 5.173L5.05 4.11a.75.75 0 010-1.06zm9.9 0a.75.75 0 010 1.06l-1.06 1.062a.75.75 0 01-1.062-1.061l1.061-1.06a.75.75 0 011.06 0zM3 10a.75.75 0 01.75-.75h1.5a.75.75 0 010 1.5h-1.5A.75.75 0 013 10zm11 0a.75.75 0 01.75-.75h1.5a.75.75 0 010 1.5h-1.5A.75.75 0 0114 10zm-6.828 2.828a.75.75 0 010 1.061l-1.06 1.06a.75.75 0 01-1.061-1.06l1.06-1.06a.75.75 0 011.061 0zm5.656 0a.75.75 0 011.06 0l1.06 1.06a.75.75 0 01-1.06 1.061l-1.06-1.06a.75.75 0 010-1.061zM10 14a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 14z" />
          </svg>
          <span>Explode {{ isSet ? 'Set' : 'Grid' }}</span>
        </button>

        <!-- Share (single item only) -->
        <button
          v-if="!isMultiple"
          @click="handleShareToCloud"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M13 4.5a2.5 2.5 0 1 1 .702 1.737L6.97 9.604a2.518 2.518 0 0 1 0 .792l6.733 3.367a2.5 2.5 0 1 1-.671 1.341l-6.733-3.367a2.5 2.5 0 1 1 0-3.475l6.733-3.366A2.52 2.52 0 0 1 13 4.5Z" />
          </svg>
          <span>Share</span>
        </button>

        <!-- Move to Trash -->
        <button
          @click="handleMoveToTrash"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
          </svg>
          <span>{{ isMultiple ? `Move ${targetCount} to Trash` : 'Move to Trash' }}</span>
        </button>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Print -->
        <button
          @click="handlePrint"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path fill-rule="evenodd" d="M5 2.75C5 1.784 5.784 1 6.75 1h6.5c.966 0 1.75.784 1.75 1.75v3.552c.377.046.752.097 1.126.153A2.212 2.212 0 0118 8.653v4.097A2.25 2.25 0 0115.75 15h-.25v2.25A2.75 2.75 0 0112.75 20h-5.5A2.75 2.75 0 014.5 17.25V15h-.25A2.25 2.25 0 012 12.75V8.653c0-1.082.775-2.034 1.874-2.198.374-.056.75-.107 1.126-.153V2.75zm1.5 0v3.36a41.778 41.778 0 017 0V2.75a.25.25 0 00-.25-.25h-6.5a.25.25 0 00-.25.25zM6.135 12.5h7.73a.25.25 0 01.25.25v4.5c0 .69-.56 1.25-1.25 1.25H7.135c-.69 0-1.25-.56-1.25-1.25v-4.5a.25.25 0 01.25-.25z" clip-rule="evenodd" />
          </svg>
          <span>{{ isMultiple ? `Print ${targetCount}` : 'Print' }}</span>
        </button>

        <!-- Export -->
        <button
          @click="handleDownload"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
            <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
          </svg>
          <span>{{ isMultiple ? `Export ${targetCount}` : 'Export' }}</span>
        </button>
      </template>
    </div>

    <!-- Tag Editor Modal -->
    <BulkTagEditor
      :visible="showTagEditor"
      :media-ids="targetIds"
      :current-tag-counts="currentTagCounts"
      :selected-items="mediaItem ? [mediaItem] : []"
      @close="showTagEditor = false"
      @saved="handleTagsSaved"
    />


    <!-- Export Modal -->
    <ExportModal
      :show="showExportModal"
      :media-ids="exportMediaIds"
      :media-items="exportMediaItems"
      @close="showExportModal = false"
    />

    <!-- Share Dialog -->
    <ShareDialog
      v-model="showShareDialog"
      :media-item="shareMediaItem"
    />
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { setPendingMedia } from '../../composables/usePendingMedia'
import { useContextMenuPosition, computeSubmenuX, computeBridgeStyle } from '../../composables/useContextMenuPosition'
import { useMediaApi } from '../../composables/useMediaApi'
import { addToast } from '../../composables/useToasts'
import { useProvidersApi, type ProviderTool } from '../../composables/useProvidersApi'
import { useSendToTool } from '../../composables/useSendToTool'
import { getCurrentProfileId } from '../../composables/useProfile'
import BulkTagEditor from '../BulkTagEditor.vue'
import ProjectPickerSubmenu from '../ProjectPickerSubmenu.vue'
import ExportModal from '../ExportModal.vue'
import ShareDialog from '../ShareDialog.vue'
import TaskTypeToolList from '../TaskTypeToolList.vue'
import { isSelectionValidForTool } from '../../utils/toolSchemaUtils'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { makeStorageKey } from '../../utils/storageKeys'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { getEligibleTaskTypesForMediaType } from '../../utils/taskTypeIcons'
import { isImage as isImageType, getMediaType, MediaType } from '../../utils/mediaTypes'
import axios from 'axios'
import { useWorkspaceTabs } from '../../composables/useWorkspaceTabs'
import { usePrint } from '../../composables/usePrint'
import { useTelemetry } from '../../composables/useTelemetry'

const { track: trackTelemetry } = useTelemetry()

interface Chat {
  id: number
  name: string | null
  updated_at: string
}

interface Marker {
  id: number
  name: string
  color: string
  icon_svg: string
}

interface GenerateMoreTool {
  full_tool_id: string
  name: string
  task_type: string
  provider_id: string
  provider_name: string
  metadata: Record<string, any>
  subtitle?: string
  is_original: boolean
}

const router = useRouter()
const { nextEditorId } = useWorkspaceTabs()
const contextMenu = useMediaContextMenu()
const { printAssetDetail, printContactSheet } = usePrint()
const { deleteMedia, restoreFromTrash, permanentlyDeleteMedia, getMediaFileUrl, getMediaItem, getMediaFaces, getMarkers, addMarkerToMedia, removeMarkerFromMedia, downloadMedia, bulkDeleteMedia, bulkRestoreFromTrash, bulkPermanentlyDelete, bulkMarkerOperation, createSetFromMedia, getThumbnailUrl, getBoards, createBoard, addMediaToBoard, removeMediaFromProject } = useMediaApi()
const { listAllTools } = useProvidersApi()
const { sendToTool: sendToToolComposable } = useSendToTool()

const menuRef = ref<HTMLElement | null>(null)
const generateTriggerRef = ref<HTMLElement | null>(null)
const toolTriggerRef = ref<HTMLElement | null>(null)
const chatTriggerRef = ref<HTMLElement | null>(null)
const boardTriggerRef = ref<HTMLElement | null>(null)
const generateSubmenuRef = ref<HTMLElement | null>(null)
const toolSubmenuRef = ref<HTMLElement | null>(null)
const chatSubmenuRef = ref<HTMLElement | null>(null)
const boardSubmenuRef = ref<HTMLElement | null>(null)
const projectSubmenuRef = ref<HTMLElement | null>(null)
const projectTriggerRef = ref<HTMLElement | null>(null)

const activeSubmenu = ref<'generate' | 'tool' | 'chat' | 'board' | 'project' | null>(null)
const submenuCloseTimeout = ref<number | null>(null)
const submenuTriggerRect = ref<DOMRect | null>(null)
const submenuClickLockUntil = ref(0)

const toolListRef = ref<InstanceType<typeof TaskTypeToolList> | null>(null)

// Track mouse position to guard delayed-close callbacks
const lastMousePos = ref({ x: 0, y: 0 })

function trackMouse(e: MouseEvent) {
  lastMousePos.value = { x: e.clientX, y: e.clientY }
}

function isMouseOverElement(el: HTMLElement | null): boolean {
  if (!el) return false
  const rect = el.getBoundingClientRect()
  const { x, y } = lastMousePos.value
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
}

// Generate submenu search
const generateSearchInputRef = ref<HTMLInputElement | null>(null)
const generateSearchQuery = ref('')
const boardSearchInputRef = ref<HTMLInputElement | null>(null)
const boardSearchQuery = ref('')

// Recent generate tools tracking
const RECENT_GENERATE_KEY = 'generate-more' as const
const MAX_RECENT = 5

function getRecentGenerateToolIds(): string[] {
  try {
    const key = makeStorageKey(RECENT_GENERATE_KEY, 'recent')
    const stored = localStorage.getItem(key)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function addRecentGenerateToolId(toolId: string) {
  try {
    const key = makeStorageKey(RECENT_GENERATE_KEY, 'recent')
    const recent = getRecentGenerateToolIds().filter(id => id !== toolId)
    recent.unshift(toolId)
    localStorage.setItem(key, JSON.stringify(recent.slice(0, MAX_RECENT)))
  } catch {
    // Ignore storage errors
  }
}

// Media item data - fetched when menu opens
const loadingItem = ref(false)
const mediaItem = ref<any>(null)
const mediaFaces = ref<any[]>([])

// Tools data
const loadingTools = ref(false)
const tools = ref<ProviderTool[]>([])
const loadingGenerateTools = ref(false)
const generateMoreTools = ref<GenerateMoreTool[]>([])

// Split generate tools into original and others
const originalTool = computed(() => generateMoreTools.value.find(t => t.is_original))
const otherGenerateTools = computed(() => generateMoreTools.value.filter(t => !t.is_original))


// Chats data
const loadingChats = ref(false)
const chats = ref<Chat[]>([])
const loadingBoards = ref(false)
const boards = ref<any[]>([])
const lastBoardsProjectId = ref<number | undefined>(undefined)
const lastChatsProjectId = ref<number | undefined>(undefined)
const savingBoardQuickAddId = ref<number | null>(null)
const creatingBoardQuickAdd = ref(false)

// Markers data
const markers = ref<Marker[]>([])

// Modal visibility
const showTagEditor = ref(false)
const showExportModal = ref(false)
const exportMediaIds = ref<number[]>([])
const exportMediaItems = ref<any[]>([])
const showShareDialog = ref(false)
const shareMediaItem = ref<any>(null)

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'permanent-delete', mediaId: number): void
}>()

// Multi-selection computed properties
const targetIds = computed(() => contextMenu.state.value.mediaIds || [contextMenu.state.value.mediaId].filter(Boolean))
const selectedItems = computed(() => contextMenu.state.value.selectedItems || [])
const isMultiple = computed(() => targetIds.value.length > 1)
const targetCount = computed(() => targetIds.value.length)

// Computed properties from mediaItem (fetched from API)
const isVideo = computed(() => mediaItem.value?.is_video || false)
const isImage = computed(() => mediaItem.value ? isImageType(mediaItem.value) : false)
const isTrashed = computed(() => !!mediaItem.value?.deleted_at)
const hasClipEmbedding = computed(() => mediaItem.value?.has_clip_embedding || false)
const hasFaceEmbeddings = computed(() => (
  isImage.value &&
  !isMultiple.value &&
  mediaFaces.value.some((face: any) => face.has_embedding)
))

// Visibility state computed properties
const isSet = computed(() => mediaItem.value?.file_format === 'stimmaset.json')
const isGrid = computed(() => mediaItem.value?.file_format === 'stimmagrid.json')
const isSetOrGrid = computed(() => isSet.value || isGrid.value)
const inBoard = computed(() => contextMenu.state.value.inBoard || false)
const boardSectionId = computed(() => contextMenu.state.value.boardSectionId)
const inProject = computed(() => contextMenu.state.value.inProject || false)
const currentProjectId = computed(() => contextMenu.state.value.projectId)

// Can create set: multiple atomic items selected (not sets or grids)
const STRUCTURED_FORMATS = ['stimmaset.json', 'stimmagrid.json']
const canCreateSet = computed(() => {
  if (!isMultiple.value) return false
  // Check if any selected items are structured (sets or grids)
  const items = selectedItems.value
  if (items.length === 0) {
    // Fallback to mediaItem if selectedItems not populated
    if (mediaItem.value) {
      return !STRUCTURED_FORMATS.includes(mediaItem.value.file_format?.toLowerCase())
    }
    return false
  }
  return items.every(item => !STRUCTURED_FORMATS.includes(item.file_format?.toLowerCase()))
})

// Check if selection contains any grids (grids cannot be sent to tools)
const hasGridInSelection = computed(() => {
  // Single item case
  if (!isMultiple.value) {
    return isGrid.value
  }
  // Multi-select case
  const items = selectedItems.value
  return items.some(item => item.file_format?.toLowerCase() === 'stimmagrid.json')
})
const creatingSet = ref(false)
const filteredBoards = computed(() => {
  const query = boardSearchQuery.value.trim().toLowerCase()
  if (!query) return boards.value
  return boards.value.filter((board) => (board.name || '').toLowerCase().includes(query))
})

function formatBoardSubmenuSummary(board: any): string {
  const itemCount = board.asset_count || 0
  const sectionCount = board.section_count || 0
  const itemText = `${itemCount} ${itemCount === 1 ? 'item' : 'items'}`
  return sectionCount > 1 ? `${itemText} · ${sectionCount} sections` : itemText
}

// Check if media item has a specific marker
function hasMarker(markerId: number): boolean {
  const itemMarkers = mediaItem.value?.markers || []
  return itemMarkers.some((m: any) => m.id === markerId)
}

// Tag counts for BulkTagEditor (for single item, each tag is either 0 or 1)
const currentTagCounts = computed(() => {
  const counts: Record<number, number> = {}
  const itemTags = mediaItem.value?.tags || []
  for (const tag of itemTags) {
    counts[tag.id] = 1
  }
  return counts
})


// Determine set content type (image or video)
const setContentType = computed(() => {
  if (!isSet.value || !mediaItem.value?.raw_metadata) return null

  // Parse raw_metadata if it's a string
  let content: any = null
  if (typeof mediaItem.value.raw_metadata === 'string') {
    try {
      content = JSON.parse(mediaItem.value.raw_metadata)
    } catch (e) {
      return null
    }
  } else {
    content = mediaItem.value.raw_metadata
  }

  const items = content?.items || []
  if (items.length === 0) return null

  const IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif']
  const VIDEO_FORMATS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']

  const types = new Set<string>()
  for (const item of items) {
    const resolved = item.resolved
    if (!resolved) continue
    const format = (resolved.file_format || '').toLowerCase()
    if (IMAGE_FORMATS.includes(format)) types.add('image')
    else if (VIDEO_FORMATS.includes(format)) types.add('video')
  }

  if (types.size === 1) return types.has('image') ? 'image' : 'video'
  return null  // Mixed or unknown
})

// Determine the actual media type of the current item
const currentMediaType = computed((): MediaType => {
  // For sets, use set content type if available
  if (isSet.value && setContentType.value) {
    return setContentType.value as MediaType
  }
  // Otherwise derive from the media item
  if (mediaItem.value) {
    return getMediaType(mediaItem.value)
  }
  return 'image'
})

// Filter tools for "Send to Tool" (image/video input tools)
// Also filters by selection count validity for multi-selection
// A tool is eligible if ANY of its task_types match the eligible types
const sendToTools = computed(() => {
  const mediaType = currentMediaType.value
  const eligibleTaskTypes = getEligibleTaskTypesForMediaType(mediaType)

  // If no eligible task types (audio, text, grid), no tools are available
  if (eligibleTaskTypes.length === 0) return []

  const count = isSet.value ? 1 : targetCount.value  // Sets count as 1 input (will be expanded by backend)

  return tools.value.filter(t => {
    // Hide unavailable tools (disconnected/unconfigured)
    if (t.availability !== 'available') return false

    // Check if any of the tool's task types are eligible
    const toolTaskTypes = t.task_types?.length ? t.task_types : (t.task_type ? [t.task_type] : [])
    const hasEligibleTaskType = toolTaskTypes.some(tt => eligibleTaskTypes.includes(tt))
    if (!hasEligibleTaskType) return false

    // Check if selection count is valid for this tool
    const validation = isSelectionValidForTool(t, count, mediaType)
    return validation.valid
  })
})

// Filtered generate tools
const filteredGenerateTools = computed(() => {
  const query = generateSearchQuery.value.trim().toLowerCase()
  if (!query) return generateMoreTools.value
  return generateMoreTools.value.filter(t =>
    t.name.toLowerCase().includes(query) ||
    t.provider_name.toLowerCase().includes(query)
  )
})

// Recent generate tools (resolved from IDs to tool objects)
const recentGenerateTools = computed(() => {
  const recentIds = getRecentGenerateToolIds()
  if (recentIds.length === 0) return []
  const originalId = originalTool.value?.full_tool_id
  return recentIds
    .filter(id => id !== originalId)
    .map(id => generateMoreTools.value.find(t => t.full_tool_id === id))
    .filter((t): t is GenerateMoreTool => !!t)
})

// Viewport-aware main menu positioning (measures actual rendered size)
const menuCoords = computed(() => ({
  x: contextMenu.state.value.x,
  y: contextMenu.state.value.y,
  bottomY: contextMenu.state.value.bottomY,
}))
const menuVisible = computed(() => contextMenu.state.value.visible)
const { menuStyle: menuPosition } = useContextMenuPosition(menuRef, menuCoords, menuVisible)

// Submenu positioning — measured after render so actual width is used, never overlaps parent
const submenuPosition = ref<Record<string, string>>({ top: '0px', left: '0px' })
const submenuBridgeStyle = ref<Record<string, string>>({ display: 'none' })

// Resolve the active submenu's element ref for measurement
function getActiveSubmenuEl(): HTMLElement | null {
  switch (activeSubmenu.value) {
    case 'board': return boardSubmenuRef.value
    case 'generate': return generateSubmenuRef.value
    case 'tool': return toolSubmenuRef.value
    case 'chat': return chatSubmenuRef.value
    case 'project': return projectSubmenuRef.value
    default: return null
  }
}

function repositionSubmenu() {
  if (!submenuTriggerRect.value || !menuRef.value) {
    submenuPosition.value = { top: '0px', left: '0px' }
    submenuBridgeStyle.value = { display: 'none' }
    return
  }

  const padding = 8
  const triggerRect = submenuTriggerRect.value
  const menuRect = menuRef.value.getBoundingClientRect()

  // Measure actual submenu width (fall back to 260 before first render)
  const submenuEl = getActiveSubmenuEl()
  const submenuWidth = submenuEl ? submenuEl.getBoundingClientRect().width : 260
  const submenuHeight = submenuEl ? submenuEl.getBoundingClientRect().height : 400

  const { x, opensLeft } = computeSubmenuX(menuRect, submenuWidth)

  // Vertical: align to trigger, clamp to viewport
  let y = triggerRect.top
  if (y + submenuHeight > window.innerHeight - padding) {
    y = Math.max(padding, window.innerHeight - submenuHeight - padding)
  }

  submenuPosition.value = { top: `${y}px`, left: `${x}px` }
  submenuBridgeStyle.value = computeBridgeStyle(menuRect, triggerRect, opensLeft)
}

// Reposition after the submenu renders (so we can measure its actual size)
watch(activeSubmenu, async (menu) => {
  if (menu) {
    await nextTick()
    requestAnimationFrame(repositionSubmenu)
  } else {
    submenuBridgeStyle.value = { display: 'none' }
  }
})

// Fetch media item when menu opens
async function fetchMediaItem() {
  const mediaId = contextMenu.state.value.mediaId
  if (!mediaId) return

  // Always refetch - item state (e.g. deleted_at) may have changed since last open
  loadingItem.value = true
  try {
    // Include trashed items so we can show appropriate options
    mediaItem.value = await getMediaItem(mediaId, { includeTrashed: true })
  } catch (err) {
    console.error('Failed to load media item:', err)
    mediaItem.value = null
  } finally {
    loadingItem.value = false
  }
}

async function fetchMediaFaces() {
  const mediaId = contextMenu.state.value.mediaId
  mediaFaces.value = []
  if (!mediaId || isMultiple.value) return

  try {
    const response = await getMediaFaces(mediaId)
    mediaFaces.value = response.faces || []
  } catch (err) {
    console.error('Failed to load media faces:', err)
  }
}

// Load tools when submenu opens
async function loadTools() {
  if (tools.value.length > 0 || loadingTools.value) return
  loadingTools.value = true
  try {
    tools.value = await listAllTools()
  } catch (err) {
    console.error('Failed to load tools:', err)
  } finally {
    loadingTools.value = false
  }
}

// Load generate-more tools (with original tool prioritized) when submenu opens
async function loadGenerateMoreTools() {
  const mediaId = contextMenu.state.value.mediaId
  if (!mediaId || loadingGenerateTools.value) return
  loadingGenerateTools.value = true
  try {
    const response = await axios.get(`/api/tools/remix-tools/${mediaId}`)
    generateMoreTools.value = response.data
  } catch (err) {
    console.error('Failed to load generate-more tools:', err)
  } finally {
    loadingGenerateTools.value = false
  }
}

// Load chats when submenu opens
async function loadChats() {
  const projectChanged = lastChatsProjectId.value !== currentProjectId.value
  if (!projectChanged && (chats.value.length > 0 || loadingChats.value)) return
  lastChatsProjectId.value = currentProjectId.value
  loadingChats.value = true
  try {
    const params = new URLSearchParams()
    if (currentProjectId.value) params.set('project_id', String(currentProjectId.value))
    const url = `/api/chats${params.toString() ? '?' + params.toString() : ''}`
    const response = await fetch(url, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      const data = await response.json()
      chats.value = data.items || []
    }
  } catch (err) {
    console.error('Failed to load chats:', err)
  } finally {
    loadingChats.value = false
  }
}

async function loadBoardsList(force = false) {
  const projectChanged = lastBoardsProjectId.value !== currentProjectId.value
  if (!force && !projectChanged && (boards.value.length > 0 || loadingBoards.value)) return
  lastBoardsProjectId.value = currentProjectId.value
  loadingBoards.value = true
  try {
    boards.value = await getBoards(currentProjectId.value)
  } catch (err) {
    console.error('Failed to load boards:', err)
  } finally {
    loadingBoards.value = false
  }
}

// Load markers (cached, only fetches once unless force=true)
async function loadMarkers(force = false) {
  if (!force && markers.value.length > 0) return
  try {
    markers.value = await getMarkers()
  } catch (err) {
    console.error('Failed to load markers:', err)
  }
}

// Handle markers config change
function handleMarkersChanged() {
  loadMarkers(true)
}

function openSubmenu(menu: 'generate' | 'tool' | 'chat' | 'board' | 'project', event: MouseEvent) {
  cancelSubmenuClose()

  // Capture the trigger element's position for submenu positioning
  const target = event.currentTarget as HTMLElement
  if (target) {
    submenuTriggerRect.value = target.getBoundingClientRect()
  }

  const wasAlreadyOpen = activeSubmenu.value === menu
  activeSubmenu.value = menu
  if (menu === 'generate') {
    generateSearchQuery.value = ''
    loadGenerateMoreTools()
  } else if (menu === 'tool') {
    loadTools()
    // Only reset drill-down state on initial open, not on re-enter
    if (!wasAlreadyOpen) {
      nextTick(() => {
        toolListRef.value?.reset()
      })
    }
  } else if (menu === 'chat') {
    loadChats()
  } else if (menu === 'board') {
    boardSearchQuery.value = ''
    loadBoardsList()
  } else if (menu === 'project') {
    // ProjectPickerSubmenu loads data internally
  }
}

function closeSubmenuDelayed() {
  submenuCloseTimeout.value = window.setTimeout(() => {
    // Guard: don't close if a recent click happened (content may have resized)
    if (Date.now() < submenuClickLockUntil.value) return
    // Guard: don't close if mouse is still over any submenu
    if (
      isMouseOverElement(generateSubmenuRef.value) ||
      isMouseOverElement(toolSubmenuRef.value) ||
      isMouseOverElement(chatSubmenuRef.value) ||
      isMouseOverElement(boardSubmenuRef.value) ||
      isMouseOverElement(projectSubmenuRef.value)
    ) return
    activeSubmenu.value = null
  }, 300)
}

function lockSubmenuOpen() {
  cancelSubmenuClose()
  submenuClickLockUntil.value = Date.now() + 500
}

function cancelSubmenuClose() {
  if (submenuCloseTimeout.value) {
    clearTimeout(submenuCloseTimeout.value)
    submenuCloseTimeout.value = null
  }
}

// Close on click outside
function handleClickOutside(event: MouseEvent) {
  if (!contextMenu.state.value.visible) return
  const target = event.target as Element
  if (menuRef.value?.contains(target)) return
  // Check all submenu refs (they live in Teleport, outside menuRef)
  if (generateSubmenuRef.value?.contains(target)) return
  if (toolSubmenuRef.value?.contains(target)) return
  if (chatSubmenuRef.value?.contains(target)) return
  if (boardSubmenuRef.value?.contains(target)) return
  if (projectSubmenuRef.value?.contains(target)) return
  contextMenu.hide()
  activeSubmenu.value = null
}

// Close on escape
function handleKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    contextMenu.hide()
    activeSubmenu.value = null
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
  document.addEventListener('mousemove', trackMouse)
  window.addEventListener('markers-changed', handleMarkersChanged)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
  document.removeEventListener('mousemove', trackMouse)
  window.removeEventListener('markers-changed', handleMarkersChanged)
})

// Auto-focus search inputs when submenus open
watch(activeSubmenu, async (menu) => {
  if (menu === 'generate') {
    await nextTick()
    generateSearchInputRef.value?.focus()
  } else if (menu === 'board') {
    await nextTick()
    boardSearchInputRef.value?.focus()
  }
})

// Fetch media item and markers when menu becomes visible
watch(() => contextMenu.state.value.visible, (visible) => {
  if (visible) {
    fetchMediaItem()
    fetchMediaFaces()
    loadMarkers()
  } else {
    activeSubmenu.value = null
    submenuTriggerRect.value = null
    generateSearchQuery.value = ''
    boardSearchQuery.value = ''
    mediaFaces.value = []
  }
})

// Action handlers
function handleFindSimilar() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length > 0) {
    trackTelemetry('find_similar_used')
    // Navigate to browse with similar filter (comma-separated for multiple)
    router.push(`/browse?sim=${ids.join(',')}`)
  }
}

function handleFindSimilarFaces() {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  if (mediaId) {
    trackTelemetry('find_similar_faces_used')
    router.push(`/browse?fsim=${mediaId}`)
  }
}

function handleCompare() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 2) {
    trackTelemetry('compare_used')
    // Dispatch custom event for BrowseGridView to handle
    window.dispatchEvent(new CustomEvent('media-compare', {
      detail: { leftMediaId: ids[0], rightMediaId: ids[1] }
    }))
  }
}

function handleViewLineage() {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  if (mediaId) {
    router.push({ name: 'lineage', params: { mediaId } })
  }
}

function handleEditImage() {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  trackTelemetry('edit_image_used')
  router.push({ name: 'edit-image', params: { editorId: nextEditorId(), mediaId } })
}



// Create Set handler
async function handleCreateSet() {
  const ids = targetIds.value
  if (ids.length < 2) return

  creatingSet.value = true
  try {
    const result = await createSetFromMedia(ids, null, currentProjectId.value || null)
    contextMenu.hide()
    // Emit refresh so the grid reloads with the new set
    emit('refresh')
  } catch (err: any) {
    console.error('Failed to create set:', err)
    const message = err?.response?.data?.detail || err?.message || 'Unknown error'
    addToast(`Failed to create set: ${message}`, 'error', 6000)
  } finally {
    creatingSet.value = false
  }
}

// Marker toggle handler
async function handleToggleMarker(marker: Marker) {
  const ids = targetIds.value
  if (ids.length === 0 || !mediaItem.value) return

  const hasIt = hasMarker(marker.id)

  // Optimistic update for displayed item
  if (hasIt) {
    mediaItem.value.markers = mediaItem.value.markers.filter((m: any) => m.id !== marker.id)
  } else {
    mediaItem.value.markers = [...(mediaItem.value.markers || []), marker]
  }

  // API call - use bulk API for multiple items
  try {
    if (ids.length > 1) {
      await bulkMarkerOperation(ids, marker.id, !hasIt)
    } else {
      if (hasIt) {
        await removeMarkerFromMedia(ids[0], marker.id)
      } else {
        await addMarkerToMedia(ids[0], marker.id)
      }
    }
    emit('refresh')
  } catch (err) {
    console.error('Failed to toggle marker:', err)
    // Revert on error
    if (hasIt) {
      mediaItem.value.markers = [...(mediaItem.value.markers || []), marker]
    } else {
      mediaItem.value.markers = mediaItem.value.markers.filter((m: any) => m.id !== marker.id)
    }
  }
}

// Tags handler
function handleEditTags() {
  contextMenu.hide()
  showTagEditor.value = true
}

function handleTagsSaved() {
  showTagEditor.value = false
  emit('refresh')
}

// Boards handler
async function handleQuickAddToBoard(boardId: number) {
  if (savingBoardQuickAddId.value != null) return
  savingBoardQuickAddId.value = boardId
  try {
    await addMediaToBoard(boardId, targetIds.value as number[])
    contextMenu.hide()
    emit('refresh')
  } catch (err) {
    console.error('Failed to add media to board:', err)
  } finally {
    savingBoardQuickAddId.value = null
  }
}

async function handleCreateBoardQuickAdd() {
  if (creatingBoardQuickAdd.value) return
  creatingBoardQuickAdd.value = true
  try {
    const board = await createBoard('', currentProjectId.value)
    await addMediaToBoard(board.id, targetIds.value as number[])
    await loadBoardsList(true)
    contextMenu.hide()
    emit('refresh')
  } catch (err) {
    console.error('Failed to create board from context menu:', err)
  } finally {
    creatingBoardQuickAdd.value = false
  }
}

function sendToGenerateTool(tool: GenerateMoreTool) {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  if (!mediaId) return

  trackTelemetry('remix_used')
  addRecentGenerateToolId(tool.full_tool_id)

  // Navigate immediately - ToolView will fetch config and show loading state
  router.push({
    name: 'tool',
    params: { fullToolId: tool.full_tool_id },
    query: {
      remixFrom: mediaId.toString(),
      _ts: Date.now().toString()
    }
  })
}

function handleToolSelect(tool: ProviderTool, targetTaskType: string) {
  contextMenu.hide()
  activeSubmenu.value = null

  // Use selectedItems for multi-selection, fall back to mediaItem for single
  const items = selectedItems.value.length > 0 ? selectedItems.value : (mediaItem.value ? [mediaItem.value] : [])
  if (items.length === 0) return

  trackTelemetry('send_to_tool_used')
  // Use the shared composable - supports both single and multiple items
  // Pass the target task type so tools with multiple task types use the correct input handling
  sendToToolComposable(items, tool, targetTaskType)
}

async function sendToNewChat() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  trackTelemetry('send_to_chat_used')
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      },
      body: JSON.stringify({ name: null, project_id: currentProjectId.value || null })
    })

    if (response.ok) {
      const newChat = await response.json()
      setPendingMedia('chat', ids, newChat.id)
      router.push({ name: 'chat', params: { id: newChat.id } })
    }
  } catch (err) {
    console.error('Failed to create chat:', err)
  }
}

function sendToChat(chat: Chat) {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  trackTelemetry('send_to_chat_used')
  setPendingMedia('chat', ids, chat.id)
  router.push({ name: 'chat', params: { id: chat.id } })
}

async function handleShareToCloud() {
  const id = targetIds.value[0]
  contextMenu.hide()
  if (!id) return

  try {
    const item = await getMediaItem(id)
    shareMediaItem.value = item
    showShareDialog.value = true
  } catch (err) {
    console.error('Failed to load media for sharing:', err)
  }
}

async function handleExplode() {
  const id = targetIds.value[0]
  contextMenu.hide()
  if (!id) return

  try {
    await axios.post(`/api/media/${id}/explode`)
    emit('refresh')
  } catch (err) {
    console.error('Failed to ungroup set/grid:', err)
  }
}

async function handleMoveToTrash() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    if (ids.length > 1) {
      await bulkDeleteMedia(ids)
    } else {
      await deleteMedia(ids[0])
    }
    emit('refresh')
  } catch (err) {
    console.error('Failed to move to trash:', err)
  }
}

async function handleRestore() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    if (ids.length > 1) {
      await bulkRestoreFromTrash(ids)
    } else {
      await restoreFromTrash(ids[0])
    }
    emit('refresh')
  } catch (err) {
    console.error('Failed to restore:', err)
  }
}

async function handlePermanentDelete() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    let response
    if (ids.length > 1) {
      response = await bulkPermanentlyDelete(ids)
    } else {
      response = await permanentlyDeleteMedia(ids[0])
    }
    emit('refresh')
    const accepted = response?.accepted ?? ids.length
    addToast(`Queued permanent deletion for ${accepted} ${accepted === 1 ? 'item' : 'items'}`, 'info')
  } catch (err: any) {
    console.error('Failed to permanently delete:', err)
    const message = err?.response?.data?.detail || err?.message || 'Unknown error'
    addToast(`Failed to permanently delete: ${message}`, 'error')
  }
}

function handleDownload() {
  const ids = targetIds.value
  const items = selectedItems.value.length > 0 ? selectedItems.value : (mediaItem.value ? [mediaItem.value] : [])
  contextMenu.hide()

  if (ids.length > 0) {
    trackTelemetry('export_used')
    exportMediaIds.value = ids
    exportMediaItems.value = items
    showExportModal.value = true
  }
}

function handlePrint() {
  const items = contextMenu.state.value.selectedItems || []
  const item = mediaItem.value
  contextMenu.hide()

  trackTelemetry('print_used')
  if (items.length > 1) {
    printContactSheet(items, getThumbnailUrl)
  } else if (item) {
    const imageFormats = ['jpeg', 'jpg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg', 'avif', 'heic', 'heif']
    const isImg = item.file_format && imageFormats.includes(item.file_format.toLowerCase())
    const imageUrl = isImg ? getMediaFileUrl(item.id) : getThumbnailUrl(item.file_hash || item.id, 512)
    printAssetDetail(item, imageUrl)
  }
}

// Board-specific actions
async function handleRemoveFromBoard() {
  const ids = targetIds.value
  const sectionId = boardSectionId.value
  contextMenu.hide()
  if (ids.length === 0 || !sectionId) return

  try {
    await Promise.all(ids.map((id) => axios.delete(`/api/boards/sections/${sectionId}/items/${id}`)))
    emit('refresh')
  } catch (err) {
    console.error('Failed to remove from board:', err)
  }
}

function handleProjectAdded(projectId: number) {
  contextMenu.hide()
  activeSubmenu.value = null
  emit('refresh')
}

async function handleRemoveFromProject() {
  const ids = targetIds.value
  const projectId = currentProjectId.value
  contextMenu.hide()
  if (ids.length === 0 || !projectId) return

  try {
    await Promise.all(ids.map((id) => removeMediaFromProject(projectId, id)))
    emit('refresh')
  } catch (err) {
    console.error('Failed to remove from project:', err)
  }
}
</script>

<style scoped>
.stimma-gradient-text {
  background: linear-gradient(135deg, #0d9488, #06b6d4, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 500;
}
</style>
