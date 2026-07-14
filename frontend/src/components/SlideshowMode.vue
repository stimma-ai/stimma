<template>
  <div
    ref="overlay"
    data-drop-zone
    :class="inline ? 'absolute inset-0 w-full h-full bg-slideshow-matt flex z-[9998]' : 'fixed inset-0 bg-slideshow-matt flex z-[9999]'"
    @dragover.prevent
    @drop.prevent
  >
    <!-- Draggable region for moving the window (below buttons at z-[10000]) -->
    <div
      data-tauri-drag-region
      class="absolute top-0 left-0 right-0 h-14 z-[9999]"
      style="-webkit-app-region: drag"
    />

    <!-- Right sidebar -->
    <SlideshowInfoPanel
      v-if="showSidebar"
      ref="infoPanelRef"
      :current-item="currentPayloadItem"
      :is-trash-view="isTrashView"
      :is-current-item-trashed="isCurrentItemTrashed"
      :available-markers="availableMarkers"
      :is-video="isVideo"
      :focus-mode="focusMode"
      :marker-update-trigger="markerUpdateTrigger"
      :media-projects="mediaProjects"
      :media-boards="mediaBoards"
      :descendants="descendants"
      :inspired-descendants="inspiredDescendants"
      :faces="faces"
      :chat-info="chatInfo"
      :chat-info-loading="chatInfoLoading"
      :generation-history="generationHistory"
      @delete="handleDeleteCurrentItem"
      @restore="handleRestoreCurrentItem"
      @permanent-delete="handlePermanentDeleteCurrentItem"
      @find-similar="findSimilar"
      @download="downloadMedia"
      @download-original="downloadMediaOriginal"
      @print="handlePrint"
      @add-to-board="addToBoard"
      @add-to-project="addToProject"
      @remove-from-project="removeFromProject"
      @remove-from-board="removeFromBoard"
      @manage-tags="manageTags"
      @filter-by-tag="filterByTag"
      @filter-by-keyword="filterByKeyword"
      @navigate-to-board="navigateToBoard"
      @navigate-to-project="navigateToProject"
      @navigate-to-source-media="navigateToSourceMedia"
      @view-in-tool="viewInTool"
      @jump-to-chat="jumpToChat"
      @toggle-marker="toggleMarker"
      @tags-saved="handleTagsSaved"
      @tags-updated="handleTagsUpdated"
      @compare-with-source="handleCompareWithSource"
      @edit-image="handleEditImage"
      @download-version="downloadVersion"
      @download-versions="downloadVersions"
      @view-lineage="handleViewLineage"
      @share-to-cloud="showShareDialog = true"
    />



    <!-- Back button (when viewing source image) -->
    <button
      v-if="!focusMode && isViewingSource"
      class="absolute top-4 left-4 bg-black/40 backdrop-blur-md border-none text-white text-sm px-4 h-12 rounded-full cursor-pointer z-[10000] transition-all hover:bg-black/60 flex items-center gap-2"
      @click="goBackFromSource"
      title="Back to original image"
    >
      <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
      </svg>
      Back
    </button>

    <!-- Exit Set button (when browsing inside a set) -->
    <button
      v-if="!focusMode && isViewingSet"
      class="absolute top-4 left-4 bg-black/40 backdrop-blur-md border-none text-white text-sm px-4 h-12 rounded-full cursor-pointer z-[10000] transition-all hover:bg-black/60 flex items-center gap-2"
      @click="exitSetView"
      title="Exit set and return to main slideshow"
    >
      <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
      </svg>
      Exit Set
    </button>

    <!-- Exit Grid Cell button (when viewing expanded cell in a grid) -->
    <!-- Visible even in focus mode so user can navigate back -->
    <button
      v-if="isViewingGrid"
      class="absolute top-4 left-4 bg-black/40 backdrop-blur-md border-none text-white text-sm px-4 h-12 rounded-full cursor-pointer z-[10000] transition-all hover:bg-black/60 flex items-center gap-2"
      @click="exitGridView"
      title="Return to grid overview (Esc)"
    >
      <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
      </svg>
      Back to Grid
    </button>

    <!-- Grid view title indicator (centered over image area, accounting for sidebar) -->
    <!-- Visible even in focus mode so user can see position and navigate back -->
    <div
      v-if="isViewingGrid && currentGridView"
      class="absolute top-4 -translate-x-1/2 z-[10000] flex flex-col items-center"
      :style="{ left: (showSidebar && !focusMode) ? 'calc(50% - 192px)' : '50%' }"
    >
      <!-- Compact pill indicator with editable title -->
      <div
        ref="gridTitleContainer"
        class="bg-black/40 backdrop-blur-md px-5 h-12 rounded-full flex items-center justify-center gap-2"
        :class="[
          !currentGridView.title ? 'cursor-text' : (isEditingGridTitle ? 'cursor-text' : 'cursor-pointer')
        ]"
        :style="{
          minWidth: gridTitleContainerWidth ? `${gridTitleContainerWidth}px` : undefined
        }"
        @dblclick.stop="startEditingGridTitle"
      >
        <!-- Editing mode -->
        <input
          v-if="isEditingGridTitle"
          v-model="editingGridTitle"
          @keydown.enter="saveGridTitle"
          @keydown.esc="cancelGridTitleEdit"
          @blur="saveGridTitle"
          @click.stop
          @dblclick.stop
          class="bg-transparent text-white text-sm font-medium outline-none border-none text-center w-full"
          placeholder="Name this grid..."
          ref="gridTitleInput"
        />
        <!-- Display mode with title -->
        <span
          v-else-if="currentGridView.title"
          class="text-white text-sm font-medium max-w-64 truncate"
        >{{ currentGridView.title }}</span>
        <!-- Display mode without title (placeholder) -->
        <span
          v-else
          class="text-white/50 text-sm italic"
          @click.stop="startEditingGridTitle"
        >Name this grid...</span>
      </div>

    </div>

    <!-- Set view title indicator (centered over image area, accounting for sidebar) -->
    <div
      v-if="!focusMode && isViewingSet && currentSetView"
      ref="setTitleContainer"
      class="absolute top-4 -translate-x-1/2 z-[10000] bg-black/40 backdrop-blur-md px-5 h-12 rounded-full flex items-center justify-center"
      :class="[
        !currentSetView.title ? 'cursor-text' : (isEditingSetTitle ? 'cursor-text' : 'cursor-pointer')
      ]"
      :style="{
        left: (showSidebar && !focusMode) ? 'calc(50% - 192px)' : '50%',
        minWidth: setTitleContainerWidth ? `${setTitleContainerWidth}px` : undefined
      }"
      @dblclick.stop="startEditingSetTitle"
    >
      <!-- Editing mode -->
      <input
        v-if="isEditingSetTitle"
        v-model="editingSetTitle"
        @keydown.enter="saveSetTitle"
        @keydown.esc="cancelSetTitleEdit"
        @blur="saveSetTitle"
        @click.stop
        @dblclick.stop
        class="bg-transparent text-white text-sm font-medium outline-none border-none text-center w-full"
        placeholder="Name this set..."
        ref="setTitleInput"
      />
      <!-- Display mode with title -->
      <span
        v-else-if="currentSetView.title"
        class="text-white text-sm font-medium max-w-64 truncate"
      >{{ currentSetView.title }}</span>
      <!-- Display mode without title (placeholder) -->
      <span
        v-else
        class="text-white/50 text-sm italic"
        @click.stop="startEditingSetTitle"
      >Name this set...</span>
    </div>

    <!-- Set overview title indicator (when viewing set overview, before entering) -->
    <div
      v-if="!focusMode && isSet && !isViewingSet"
      ref="setOverviewTitleContainer"
      class="absolute top-4 -translate-x-1/2 z-[10000] bg-black/40 backdrop-blur-md px-5 h-12 rounded-full flex items-center justify-center"
      :class="[
        !setOverviewData?.title ? 'cursor-text' : (isEditingSetOverviewTitle ? 'cursor-text' : 'cursor-pointer')
      ]"
      :style="{
        left: (showSidebar && !focusMode) ? 'calc(50% - 192px)' : '50%',
        minWidth: setOverviewTitleContainerWidth ? `${setOverviewTitleContainerWidth}px` : undefined
      }"
      @dblclick.stop="startEditingSetOverviewTitle"
    >
      <!-- Editing mode -->
      <input
        v-if="isEditingSetOverviewTitle"
        v-model="editingSetOverviewTitle"
        @keydown.enter="saveSetOverviewTitle"
        @keydown.esc="cancelSetOverviewTitleEdit"
        @blur="saveSetOverviewTitle"
        @click.stop
        @dblclick.stop
        class="bg-transparent text-white text-sm font-medium outline-none border-none text-center w-full"
        placeholder="Name this set..."
        ref="setOverviewTitleInput"
      />
      <!-- Display mode with title -->
      <span
        v-else-if="setOverviewData?.title"
        class="text-white text-sm font-medium max-w-64 truncate"
      >{{ setOverviewData.title }}</span>
      <!-- Display mode without title (placeholder) -->
      <span
        v-else
        class="text-white/50 text-sm italic"
        @click.stop="startEditingSetOverviewTitle"
      >Name this set...</span>
    </div>

    <!-- Grid overview title indicator (when viewing grid overview, before entering) -->
    <div
      v-if="!focusMode && isGrid && !isViewingGrid"
      ref="gridOverviewTitleContainer"
      class="absolute top-4 -translate-x-1/2 z-[10000] bg-black/40 backdrop-blur-md px-5 h-12 rounded-full flex items-center justify-center"
      :class="[
        !gridOverviewData?.title ? 'cursor-text' : (isEditingGridOverviewTitle ? 'cursor-text' : 'cursor-pointer')
      ]"
      :style="{
        left: (showSidebar && !focusMode) ? 'calc(50% - 192px)' : '50%',
        minWidth: gridOverviewTitleContainerWidth ? `${gridOverviewTitleContainerWidth}px` : undefined
      }"
      @dblclick.stop="startEditingGridOverviewTitle"
    >
      <!-- Editing mode -->
      <input
        v-if="isEditingGridOverviewTitle"
        v-model="editingGridOverviewTitle"
        @keydown.enter="saveGridOverviewTitle"
        @keydown.esc="cancelGridOverviewTitleEdit"
        @blur="saveGridOverviewTitle"
        @click.stop
        @dblclick.stop
        class="bg-transparent text-white text-sm font-medium outline-none border-none text-center w-full"
        placeholder="Name this grid..."
        ref="gridOverviewTitleInput"
      />
      <!-- Display mode with title -->
      <span
        v-else-if="gridOverviewData?.title"
        class="text-white text-sm font-medium max-w-64 truncate"
      >{{ gridOverviewData.title }}</span>
      <!-- Display mode without title (placeholder) -->
      <span
        v-else
        class="text-white/50 text-sm italic"
        @click.stop="startEditingGridOverviewTitle"
      >Name this grid...</span>
    </div>

    <!-- Compare button (when viewing grid overview) -->
    <div
      v-if="!focusMode && isGrid && !isViewingGrid"
      class="absolute top-4 h-12 z-[10000] flex items-center"
      :style="{ right: (showSidebar && !focusMode) ? '468px' : '84px' }"
    >
      <!-- Initial compare button (not in compare mode) -->
      <button
        v-if="!gridMultiSelectMode"
        class="bg-black/40 backdrop-blur-md border-none text-white text-xs px-3 h-8 rounded-full cursor-pointer transition-all hover:bg-black/60 flex items-center"
        @click="toggleGridMultiSelectMode"
        title="Select 2 cells to compare"
      >
        Compare
      </button>

      <!-- Compare mode controls (grouped pill) -->
      <div
        v-else
        class="bg-black/40 backdrop-blur-md border border-white/10 rounded-full h-9 flex items-center gap-2 pl-4 pr-2"
      >
        <!-- Label and count -->
        <span class="text-white/60 text-xs">
          Comparing
        </span>
        <span class="text-white text-xs font-medium">
          {{ gridSelectedCells.length }}/2
        </span>
        <!-- Compare action button (enabled when 2 selected) -->
        <button
          :disabled="gridSelectedCells.length !== 2"
          :class="[
            'border-none text-xs px-3 h-6 rounded-full transition-all flex items-center',
            gridSelectedCells.length === 2
              ? 'bg-blue-500 text-white cursor-pointer hover:bg-blue-600'
              : 'bg-white/10 text-white/40 cursor-not-allowed'
          ]"
          @click="compareGridCells"
          title="Compare selected cells"
        >
          Compare
        </button>
        <!-- Cancel button -->
        <button
          class="border-none text-white/60 hover:text-white h-6 w-6 rounded-full cursor-pointer transition-all hover:bg-white/10 flex items-center justify-center"
          @click="toggleGridMultiSelectMode"
          title="Cancel"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Close button -->
    <button class="absolute top-4 bg-black/40 backdrop-blur-md border-none text-white text-[2rem] w-12 h-12 rounded-full cursor-pointer z-[10002] transition-all hover:bg-black/60" :style="{ right: (showSidebar && !focusMode) ? '400px' : '16px' }" @click="handleCloseClick" title="Close slideshow">✕</button>

    <!-- Caption (bottom) -->
    <div v-if="currentItem && showCaption && currentItem.vlm_caption && captioningEnabledRef" class="absolute bottom-0 left-0 right-0 bg-black/60 backdrop-blur-md px-8 py-6 text-white text-sm leading-normal z-[10000]">
      {{ currentItem.vlm_caption }}
    </div>

    <!-- Media display -->
    <div
      ref="mediaContainer"
      class="flex-1 flex items-center justify-center relative transition-all duration-300"
      :style="{ marginBottom: (showImageStrip && !focusMode && !isViewingGrid) ? `${STRIP_HEIGHT}px` : '0px' }"
    >
      <div v-if="!displayItem" class="text-content">Loading...</div>
      <!-- Placeholder for deleted/trashed items (rare edge case) -->
      <div
        v-else-if="displayItem._placeholder"
        class="flex flex-col items-center justify-center gap-4 text-content-muted"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor" class="w-24 h-24">
          <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
        </svg>
        <span class="text-lg">Image no longer available</span>
      </div>

      <!-- Grid viewer (needs its own scrolling, uses absolute positioning to fill container) -->
      <!-- Only show when viewing grid overview (not when viewing an expanded cell) -->
      <GridViewer
        v-else-if="isGrid && !isViewingGrid"
        ref="gridViewerRef"
        :key="`grid-${displayItem?.id}-${refreshKey}`"
        :media-id="mediaIdOf(displayItem)"
        :multi-select-mode="gridMultiSelectMode"
        @back="close"
        @select-cell="handleGridCellSelect"
        @selection-change="handleGridSelectionChange"
        @loaded="handleGridOverviewLoaded"
        class="absolute inset-0 z-[1]"
      />

      <!-- Wrapper fills container; w-full h-full + object-contain scales to fit -->
      <div
        v-else
        ref="mediaContainerRef"
        class="relative w-full h-full flex items-center justify-center bg-slideshow-matt overflow-hidden touch-none"
        @wheel="handleWheel"
        @pointerdown="startPan"
        @pointermove="doPan"
        @pointerup="endPan"
        @pointercancel="endPan"
        @touchstart="handleTouchStart"
        @touchmove="handleTouchMove"
        @touchend="handleTouchEnd"
        @click="handleDoubleTap"
      >
        <!-- Audio player -->
        <AudioPlayer
          v-if="isAudio"
          :key="`audio-${displayItem?.id}-${refreshKey}`"
          :src="getMediaFileUrl(displayItem.file_hash)"
          :media-id="mediaIdOf(displayItem)"
          :title="displayItem.vlm_caption"
          :duration="displayItem.duration"
          autoplay
        />

        <!-- Markdown viewer -->
        <MarkdownViewer
          v-else-if="isText"
          :key="`markdown-${displayItem?.id}-${refreshKey}`"
          :media-id="mediaIdOf(displayItem)"
        />

        <!-- Set overview: show all items in a wrap panel (only when not already viewing a set) -->
        <SetOverview
          v-else-if="isSet && !isViewingSet"
          :key="`set-overview-${displayItem?.id}-${refreshKey}`"
          :media-id="mediaIdOf(displayItem)"
          @select-item="handleSetItemSelect"
          @loaded="handleSetOverviewLoaded"
          class="absolute inset-0 z-[1]"
        />

        <!-- Layout viewer -->
        <LayoutViewer
          v-else-if="isLayout"
          :key="`layout-${displayItem?.id}-${refreshKey}`"
          :media-id="mediaIdOf(displayItem)"
          class="absolute inset-0 z-[1]"
        />

        <!-- Video -->
        <!-- MSE presents repeated A/V fragments on one forward-moving timeline,
             so loop boundaries never trigger a media-element seek. -->
        <video
          v-else-if="isVideo"
          :key="`video-${displayItem?.id}-${refreshKey}`"
          :poster="getThumbnailUrl(displayItem.file_hash, 1024, { mode: 'fit' })"
          :muted="isMuted"
          @contextmenu="handleContextMenu($event, displayItem)"
          autoplay
          playsinline
          :class="[
            'w-full h-full object-contain select-none',
            zoomScale > 1 ? 'cursor-grabbing' : 'cursor-zoom-in'
          ]"
          :style="{
            transform: `translate(${panX}px, ${panY}px) scale(${zoomScale})`,
            transformOrigin: 'center center'
          }"
          ref="videoElement"
          draggable="true"
          @dragstart="handleDragStart"
          @dragend="handleDragEnd"
          @loadedmetadata="handleMediaLoad"
        >
        </video>

        <!-- Image (default) -->
        <div
          v-else
          :class="[
            displayItem.has_alpha !== false && mediaLoaded && hasExactDimensions ? 'bg-checker' : 'bg-slideshow-matt',
            zoomScale > 1 ? 'cursor-grabbing' : 'cursor-zoom-in'
          ]"
          :style="checkerOverlayStyle"
          @contextmenu="handleContextMenu($event, displayItem)"
        >
          <img
            :key="`img-${displayItem?.id}-${refreshKey}`"
            :src="getMediaFileUrl(displayItem.file_hash)"
            :alt="displayItem.vlm_caption"
            :class="['w-full h-full select-none', hasExactDimensions ? '' : 'object-contain']"
            draggable="true"
            @dragstart="handleDragStart"
            @dragend="handleDragEnd"
            @load="handleMediaLoad"
          />
        </div>
      </div>

      <!-- Face overlays -->
      <svg
        v-if="currentItem && faces.length > 0 && visibleFaceOverlays.size > 0"
        class="absolute inset-0 w-full h-full pointer-events-none"
        :viewBox="`0 0 ${currentItem.width || 1} ${currentItem.height || 1}`"
        preserveAspectRatio="xMidYMid meet"
        :style="{
          objectFit: 'contain',
          transform: `translate(${panX}px, ${panY}px) scale(${zoomScale})`,
          transformOrigin: 'center center'
        }"
      >
        <g v-for="face in faces.filter(f => visibleFaceOverlays.has(f.id))" :key="face.id">
          <!-- Bounding box -->
          <rect
            :x="face.bbox.x * (currentItem.width || 1)"
            :y="face.bbox.y * (currentItem.height || 1)"
            :width="face.bbox.width * (currentItem.width || 1)"
            :height="face.bbox.height * (currentItem.height || 1)"
            fill="none"
            stroke="currentColor"
            class="text-green-500"
            :stroke-width="Math.max(2, (currentItem.width || 1) * 0.003)"
            stroke-opacity="0.8"
          />

          <!-- Confidence label -->
          <text
            :x="face.bbox.x * (currentItem.width || 1) + 5"
            :y="face.bbox.y * (currentItem.height || 1) - 5"
            fill="currentColor"
            class="text-green-500"
            :font-size="Math.max(12, (currentItem.width || 1) * 0.02)"
            font-family="monospace"
            font-weight="bold"
          >
            {{ (face.confidence * 100).toFixed(1) }}%
          </text>

          <!-- Landmarks -->
          <g v-if="face.landmarks">
            <circle
              v-for="(point, idx) in parseLandmarks(face.landmarks)"
              :key="idx"
              :cx="point.x * (currentItem.width || 1)"
              :cy="point.y * (currentItem.height || 1)"
              :r="Math.max(4, (currentItem.width || 1) * 0.005)"
              fill="currentColor"
              class="text-red-500"
              fill-opacity="1"
            />
          </g>
        </g>
      </svg>

      <!-- Previous button (left side) -->
      <button
        v-if="!focusMode && !isViewingSource && canGoPrevious"
        @click.stop="userPrevious"
        @contextmenu="handleContextMenu($event, displayItem)"
        :class="[
          'absolute left-0 flex items-center justify-start cursor-pointer z-[9999] group bg-transparent border-none',
          isGrid ? 'w-12 h-24 top-1/2 -translate-y-1/2' : 'w-48 top-20 bottom-0'
        ]"
        title="Previous (← or A)"
      >
        <div class="w-12 h-24 flex items-center justify-center rounded-r-lg bg-transparent group-hover:bg-black/30 group-hover:backdrop-blur-md transition-all">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="w-8 h-8 text-white/0 group-hover:text-white transition-all">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </div>
      </button>

      <!-- Next button (right side) -->
      <button
        v-if="!focusMode && !isViewingSource && canGoNext"
        @click.stop="userNext"
        @contextmenu="handleContextMenu($event, displayItem)"
        :class="[
          'absolute right-0 flex items-center justify-end cursor-pointer z-[9999] group bg-transparent border-none',
          isGrid ? 'w-12 h-24 top-1/2 -translate-y-1/2' : 'w-48 top-20 bottom-0'
        ]"
        title="Next (→ or D)"
      >
        <div class="w-12 h-24 flex items-center justify-center rounded-l-lg bg-transparent group-hover:bg-black/30 group-hover:backdrop-blur-md transition-all">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="w-8 h-8 text-white/0 group-hover:text-white transition-all">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </div>
      </button>

      <!-- Floating approval bar — visible when the parent provides an
           approvalContext for the current media. Mirrors FlowView's
           approve/replace/unapprove treatment so the slideshow feels
           like the same widget. -->
      <SlideshowApprovalBar
        v-if="approvalContext"
        :state="approvalContext.state"
        @approve="emit('approve')"
        @reject="emit('reject')"
        @unapprove="emit('unapprove')"
      />
    </div>

    <!-- Image Strip (shows thumbnails from current dataset, or single source image when viewing source) -->
    <!-- Hidden when viewing an expanded grid cell (the grid cell navigation replaces the strip) -->
    <div
      v-if="showImageStrip && !focusMode && props.showThumbnailStrip && !isViewingGrid"
      :class="inline ? 'absolute' : 'fixed'"
      class="bottom-0 left-0 bg-surface-elevated backdrop-blur-[10px] border-t border-edge-subtle z-[9998] transition-all duration-300 py-2 px-2"
      :style="{
        height: `${STRIP_HEIGHT}px`,
        right: (showSidebar && !focusMode) ? `${SIDEBAR_WIDTH}px` : '0px'
      }"
    >
      <!-- When viewing a source image, show single centered thumbnail -->
      <div v-if="isViewingSource && currentItem" class="h-full flex items-center justify-center">
        <div
          class="flex items-center justify-center relative"
          :title="currentItem.vlm_caption || 'Source image'"
          style="height: 104px;"
          @contextmenu="handleContextMenu($event, currentItem)"
        >
          <div v-if="currentItem.file_hash" class="w-[96px] h-[96px] bg-black rounded overflow-hidden border border-edge ring-2 ring-blue-500 ring-offset-2 ring-offset-surface-elevated">
            <MediaImage
              :media-id="mediaIdOf(currentItem)"
              :file-hash="currentItem.file_hash"
              :file-path="currentItem.file_path"
              :file-format="currentItem.file_format"
              :alt="currentItem.vlm_caption"
              thumbnail
              :thumbnail-size="256"
              :draggable="false"
              :enable-context-menu="false"
              :has-alpha="currentItem.has_alpha"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </div>
          <!-- Marker badges -->
          <MarkerBadges
            v-if="currentItem.markers && currentItem.markers.length > 0"
            :markers="currentItem.markers"
            class="absolute bottom-1 left-1"
          />
        </div>
      </div>
      <!-- Set view mode: show set items in strip -->
      <div
        v-else-if="isViewingSet && currentSetView"
        class="flex items-center gap-2 h-full overflow-x-auto px-2"
      >
        <div
          v-for="(item, index) in currentSetView.items"
          :key="item.id"
          @click="setViewIndex = index"
          class="flex-shrink-0 cursor-pointer transition-all relative"
          :title="item.vlm_caption || `Item ${index + 1}`"
        >
          <div
            class="w-[96px] h-[96px] bg-black rounded overflow-hidden border border-edge transition-all"
            :class="index === setViewIndex ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-surface-elevated' : 'ring-2 ring-transparent hover:ring-blue-400 hover:brightness-110'"
          >
            <MediaImage
              :media-id="mediaIdOf(item)"
              :file-hash="item.file_hash"
              :file-path="item.file_path"
              :file-format="item.file_format"
              :alt="item.vlm_caption"
              draggable="true"
              @dragstart="handleStripDragStart($event, item)"
              @dragend="handleDragEnd"
              thumbnail
              :thumbnail-size="256"
              :enable-context-menu="false"
              :has-alpha="item.has_alpha"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </div>
          <!-- Marker badges -->
          <MarkerBadges
            v-if="item.markers && item.markers.length > 0"
            :markers="item.markers"
            class="absolute bottom-1 left-1"
          />
        </div>
      </div>
      <!-- Normal browsing: show full virtualized thumbnail strip -->
      <HorizontalVirtualScroller
        v-else-if="localTotalCount > 0 && !isViewingSet"
        ref="stripScrollerRef"
        :key="`${isRandomized}-${props.randomSeed}-${stripRefreshKey}`"
        :total-count="localTotalCount"
        :page-provider="stripPageProvider"
        :item-getter="stripItemGetter"
        :current-index="currentIndex"
        :item-width="104"
        :item-height="104"
        :item-gap="8"
        :height="120"
        :chunk-size="50"
        :buffer-size="10"
        :auto-center="true"
      >
        <template v-slot="{ item, index }">
          <div
            @click="!item._isPlaceholder && goToIndex(index)"
            @contextmenu="!item._isPlaceholder && handleContextMenu($event, item)"
            class="flex items-center justify-center transition-all relative"
            :class="item._isPlaceholder ? 'cursor-default' : 'cursor-pointer'"
            :title="item._isPlaceholder ? 'Loading...' : (item.vlm_caption || `Image ${index + 1}`)"
            style="height: 104px;"
          >
            <!-- Placeholder skeleton while loading -->
            <div
              v-if="item._isPlaceholder"
              class="w-[96px] h-[96px] bg-surface-raised rounded overflow-hidden border border-edge animate-pulse"
            />
            <!-- Real thumbnail -->
            <div
              v-else-if="item.file_hash"
              class="w-[96px] h-[96px] bg-black rounded overflow-hidden border border-edge transition-all"
              :class="index === currentIndex ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-surface-elevated' : 'ring-2 ring-transparent hover:ring-blue-400 hover:brightness-110'"
            >
              <MediaImage
                :media-id="mediaIdOf(item)"
                :file-hash="item.file_hash"
                :file-path="item.file_path"
                :file-format="item.file_format"
                :alt="item.vlm_caption"
                draggable="true"
                @dragstart="handleStripDragStart($event, item)"
                @dragend="handleDragEnd"
                thumbnail
                :thumbnail-size="256"
                :enable-context-menu="false"
                :has-alpha="item.has_alpha"
                container-class="w-full h-full"
                img-class="w-full h-full object-cover"
                @error="handleThumbnailError($event, item, index)"
              />
            </div>
            <!-- Marker badges -->
            <MarkerBadges
              v-if="item.markers && item.markers.length > 0"
              :markers="item.markers"
              class="absolute bottom-1 left-1"
            />
          </div>
        </template>
      </HorizontalVirtualScroller>
      <div v-else class="px-4 text-content-tertiary text-sm">
        No images available
      </div>
    </div>

    <!-- Grid Mini-Map (bottom-left corner, shows position within grid) -->
    <div
      v-if="isViewingGrid && miniMapConfig"
      class="absolute bottom-4 left-4 z-[10000] flex flex-col items-start gap-1"
    >
      <!-- Column header (above mini-map) -->
      <div
        v-if="currentColHeader"
        class="px-2 py-1 rounded bg-black/40 backdrop-blur-md border border-white/10 text-white text-xs max-w-48 truncate"
        :title="currentColHeader"
      >
        {{ currentColHeader }}
      </div>

      <div class="flex items-end gap-1">
        <!-- Mini-map grid -->
        <div
          class="p-2 rounded-lg bg-black/40 backdrop-blur-md border border-white/10 cursor-pointer"
          @click="handleMiniMapClick"
        >
          <div
            ref="miniMapGrid"
            class="grid"
            :style="{
              gridTemplateColumns: `repeat(${miniMapConfig.cols}, ${miniMapConfig.cellSize}px)`,
              gridTemplateRows: `repeat(${miniMapConfig.rows}, ${miniMapConfig.cellSize}px)`,
              gap: miniMapConfig.cellSize >= 6 ? '1px' : '0px'
            }"
          >
            <template v-for="row in miniMapConfig.rows" :key="'row-' + row">
              <div
                v-for="col in miniMapConfig.cols"
                :key="'cell-' + row + '-' + col"
                :class="[
                  'transition-colors',
                  row - 1 === gridViewRow && col - 1 === gridViewCol
                    ? 'bg-blue-500'
                    : getGridCellContent(row - 1, col - 1)?.resolved
                      ? 'bg-white/30'
                      : 'bg-white/10'
                ]"
                :style="{
                  width: miniMapConfig.cellSize + 'px',
                  height: miniMapConfig.cellSize + 'px'
                }"
              />
            </template>
          </div>
        </div>

        <!-- Row header (to the right of mini-map) -->
        <div
          v-if="currentRowHeader"
          class="px-2 py-1 rounded bg-black/40 backdrop-blur-md border border-white/10 text-white text-xs max-w-48 truncate"
          :title="currentRowHeader"
        >
          {{ currentRowHeader }}
        </div>
      </div>
    </div>

    <!-- Control Bar (default: vertical, upper-left; user-draggable) -->
    <div
      ref="controlBar"
      :class="[
        'absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-black/40 backdrop-blur-xl px-4 py-2 rounded-full border border-white/10 z-[10000] shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-200 select-none',
        { 'cursor-grabbing !transition-none': isDragging },
        { '!bg-black/60': isHovered },
        { 'cursor-grab': !isDragging },
        { 'flex-col px-2 py-4': controlBarOrientation === 'vertical' }
      ]"
      :style="controlBarStyle"
      @mousedown="startDrag"
      @mouseenter="isHovered = true"
      @mouseleave="isHovered = false"
      title="Drag to reposition"
    >
      <!-- Cluster 1 — Playback: shuffle · play/pause · loop · interval · volume -->
      <div :class="['flex gap-2', { 'flex-col': controlBarOrientation === 'vertical' }]">
        <!-- Shuffle button -->
        <button
          @click="toggleRandomize"
          :class="[
            'bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white',
            { '!text-[#ec4899] hover:!text-[#f472b6]': isRandomized }
          ]"
          title="Toggle Shuffle (r)"
        >
          <ArrowsRightLeftIcon class="w-5 h-5" />
        </button>

        <!-- Play / Pause (explicit) -->
        <button
          @click="toggleSlideshow"
          :class="[
            'bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white',
            { '!text-[#ec4899] hover:!text-[#f472b6]': isPlaying }
          ]"
          :title="isPlaying ? 'Pause (space)' : 'Play slideshow (space)'"
        >
          <PauseIcon v-if="isPlaying" class="w-5 h-5" />
          <PlayIcon v-else class="w-5 h-5" />
        </button>

        <!-- Loop -->
        <button
          @click="toggleLoop"
          :class="[
            'text-base text-white/60 cursor-pointer transition-all bg-transparent border-none p-1.5 rounded-md leading-none flex items-center justify-center w-8',
            { '!text-[#ec4899] hover:!text-[#f472b6]': loopEnabled },
            'hover:bg-white/10 hover:text-white'
          ]"
          title="Toggle Loop (l)"
        >
          ↻
        </button>

        <!-- Click speaker to mute/unmute; hover for the volume popup (video only) -->
        <div
          v-if="isVideo"
          class="relative"
          ref="volumeButtonRef"
          @mouseenter="onVolumeHoverEnter"
          @mouseleave="onVolumeHoverLeave"
        >
          <button
            @click="toggleMute"
            :class="[
              'bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all',
              { '!text-[#ec4899] hover:!text-[#f472b6]': !isMuted },
              'hover:bg-white/10 hover:text-white'
            ]"
            title="Mute/unmute (m) — hover for volume"
          >
            <SpeakerWaveIcon v-if="!isMuted && volume > 0.5" class="w-5 h-5" />
            <SpeakerWaveIcon v-else-if="!isMuted && volume > 0" class="w-5 h-5 scale-90" />
            <SpeakerXMarkIcon v-else class="w-5 h-5" />
          </button>
          <!-- Volume popup with mute + slider -->
          <div
            v-if="showVolumeSlider"
            ref="volumeSliderRef"
            :class="[
              'absolute bg-black/70 backdrop-blur-xl rounded-xl border border-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.4)] z-[10001]',
              controlBarOrientation === 'vertical'
                ? 'left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-2 flex items-center gap-2'
                : 'bottom-full mb-2 left-1/2 -translate-x-1/2 px-2 py-2 flex flex-col items-center gap-2'
            ]"
            @mousedown.stop
          >
            <template v-if="controlBarOrientation === 'vertical'">
              <button
                @click="toggleMute"
                :class="[
                  'bg-transparent border-none cursor-pointer p-1 flex items-center justify-center rounded-md transition-all',
                  isMuted ? 'text-white/40 hover:text-white' : 'text-[#ec4899] hover:text-[#f472b6]'
                ]"
              >
                <SpeakerXMarkIcon v-if="isMuted" class="w-4 h-4" />
                <SpeakerWaveIcon v-else class="w-4 h-4" />
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                :value="volume"
                @input="handleVolumeInput"
                class="volume-slider w-24"
              />
            </template>
            <template v-else>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                :value="volume"
                @input="handleVolumeInput"
                class="volume-slider-vertical h-24"
                orient="vertical"
              />
              <button
                @click="toggleMute"
                :class="[
                  'bg-transparent border-none cursor-pointer p-1 flex items-center justify-center rounded-md transition-all',
                  isMuted ? 'text-white/40 hover:text-white' : 'text-[#ec4899] hover:text-[#f472b6]'
                ]"
              >
                <SpeakerXMarkIcon v-if="isMuted" class="w-4 h-4" />
                <SpeakerWaveIcon v-else class="w-4 h-4" />
              </button>
            </template>
          </div>
        </div>
      </div>

      <!-- Interval — its own section, only while the slideshow is running -->
      <template v-if="isPlaying">
        <div :class="['bg-white/20 cursor-grab', controlBarOrientation === 'vertical' ? 'w-5 h-px' : 'w-px h-5']"></div>
        <button
          @click="cycleDuration"
          class="text-sm font-medium text-white/60 flex items-center justify-center cursor-pointer transition-all bg-transparent border-none p-1.5 rounded-md min-w-[42px] hover:bg-white/10 hover:text-white"
          title="Slideshow interval — click to change (or w/s)"
        >
          <span class="pointer-events-none">{{ currentDuration }}s</span>
        </button>
      </template>

      <div :class="['bg-white/20 cursor-grab', controlBarOrientation === 'vertical' ? 'w-5 h-px' : 'w-px h-5']"></div>

      <!-- Cluster 2 — Position -->
      <div
        class="text-xs font-semibold text-white cursor-grab"
        :class="controlBarOrientation === 'vertical' ? 'flex flex-col gap-0.5 items-center leading-none' : 'min-w-[80px] text-center'"
        @dblclick="toggleOrientation"
        :title="isViewingGrid ? 'Grid position | Arrow keys to navigate | Double-click to toggle orientation' : 'Position | Arrow keys / a/d to navigate | Double-click to toggle orientation'"
      >
        <!-- Grid view: show linear position in reading order -->
        <template v-if="isViewingGrid && currentGridView">
          <template v-if="controlBarOrientation === 'vertical'">
            <div class="text-sm font-semibold">{{ gridLinearPosition }}</div>
            <div class="text-xs opacity-50 font-medium">{{ gridTotalCells }}</div>
          </template>
          <template v-else>
            {{ gridLinearPosition }} / {{ gridTotalCells }}
          </template>
        </template>
        <!-- Normal mode: show linear position -->
        <template v-else-if="controlBarOrientation === 'vertical'">
          <div class="text-sm font-semibold">{{ effectiveIndex + 1 }}</div>
          <div class="text-xs opacity-50 font-medium">{{ effectiveTotalCount }}</div>
        </template>
        <template v-else>
          {{ effectiveIndex + 1 }} / {{ effectiveTotalCount }}
        </template>
      </div>

      <div :class="['bg-white/20 cursor-grab', controlBarOrientation === 'vertical' ? 'w-5 h-px' : 'w-px h-5']"></div>

      <!-- Cluster 3 — This image: focus · lineage · show in Finder · markers -->
      <div :class="['flex gap-2', { 'flex-col': controlBarOrientation === 'vertical' }]">
        <!-- Focus mode button -->
        <button
          @click="toggleFocusMode"
          :class="[
            'bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white',
            { '!text-[#ec4899] hover:!text-[#f472b6]': focusMode }
          ]"
          title="Toggle Focus Mode (f)"
        >
          <ArrowsPointingOutIcon class="w-5 h-5" />
        </button>

        <!-- Lineage button -->
        <button
          @click="handleViewLineage"
          class="bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white"
          title="View Lineage (t)"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" class="w-5 h-5">
            <circle cx="6" cy="4.5" r="1.75" stroke-width="1.5" />
            <circle cx="14" cy="4.5" r="1.75" stroke-width="1.5" />
            <circle cx="10" cy="15.5" r="1.75" stroke-width="1.5" />
            <path d="M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>

        <!-- File icon: click (or Shift+S) reveals the file in Finder.
             Dragging it out to export the file is an undocumented easter egg.
             @mousedown.stop keeps this from starting a control-bar reposition. -->
        <button
          v-if="isTauri && currentItem"
          draggable="true"
          @mousedown.stop
          @click="revealInFinder"
          @dragstart="handleExportDragStart"
          @dragend="handleDragEnd"
          class="bg-transparent border-none text-white/60 cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white"
          title="Show in Finder (⇧S)"
        >
          <DocumentIcon class="w-5 h-5 pointer-events-none" />
        </button>

        <!-- Marker toggles (own sub-group, divided from the view actions) -->
        <template v-if="availableMarkers.length > 0 && currentItem">
          <div :class="['bg-white/20 self-center', controlBarOrientation === 'vertical' ? 'w-5 h-px' : 'w-px h-5']"></div>
          <button
            v-for="marker in availableMarkers"
            :key="marker.id"
            @click.stop="toggleMarker(marker.id)"
            :class="[
              'bg-transparent border-none cursor-pointer p-1.5 flex items-center justify-center rounded-md transition-all hover:bg-white/10',
              isMarkerActive(marker.id) ? '' : 'text-white/60 hover:text-white'
            ]"
            :style="isMarkerActive(marker.id) ? { color: marker.color } : {}"
            :title="isMarkerActive(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
          >
            <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
          </button>
        </template>
      </div>
    </div>

    <!-- Video transport (bottom center, above the control bar's default spot).
         Filmstrip scrubber: the track is a frame-strip montage of the video with a
         live playhead, same treatment as the prep frame picker. Toggle with V. -->
    <div
      v-if="isVideo && showVideoTransport"
      class="absolute z-[10000] flex items-center gap-2 bg-black/40 backdrop-blur-xl border border-white/10 rounded-xl px-3 py-1.5 shadow-[0_4px_20px_rgba(0,0,0,0.3)] select-none w-[620px]"
      :style="transportBarStyle"
      @mousedown.stop
      @dblclick.stop
    >
      <!-- Play / Pause (the video, not the slideshow) -->
      <button
        @click="toggleVideoPlayback"
        class="bg-transparent border-none text-white/60 cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white flex-shrink-0"
        :title="videoPaused ? 'Play video' : 'Pause video'"
      >
        <PlayIcon v-if="videoPaused" class="w-5 h-5" />
        <PauseIcon v-else class="w-5 h-5" />
      </button>

      <!-- Filmstrip track -->
      <div
        class="relative flex-1 h-[34px] rounded-md overflow-hidden border border-white/10 bg-black/30 cursor-pointer select-none touch-none"
        @pointerdown="onTransportPointerDown"
        @pointermove="onTransportPointerMove"
        @pointerup="onTransportPointerUp"
        @pointercancel="onTransportPointerCancel"
        @dragstart.prevent
      >
        <img
          v-if="transportStripUrl && !transportStripFailed"
          :src="transportStripUrl"
          @load="transportStripReady = true"
          @error="transportStripFailed = true"
          class="absolute inset-0 w-full h-full object-fill pointer-events-none transition-opacity duration-300"
          :class="{ 'opacity-0': !transportStripReady }"
          draggable="false"
        />
        <!-- skeleton cells while the strip renders (best-effort; scrubbing works regardless) -->
        <div
          v-if="transportStripUrl && !transportStripFailed && !transportStripReady"
          class="absolute inset-0 flex gap-px p-px animate-pulse pointer-events-none"
        >
          <div v-for="i in 12" :key="i" class="flex-1 rounded-[3px] bg-white/[0.07]"></div>
        </div>
        <!-- progress reads as a dim over the not-yet-played region (no color haze) -->
        <div
          class="absolute inset-y-0 right-0 bg-black/35 pointer-events-none"
          :style="{ width: (100 - transportPercent) + '%' }"
        ></div>
        <div
          class="absolute top-0 bottom-0 w-0.5 bg-blue-400 pointer-events-none"
          style="box-shadow: 0 0 6px rgba(96,165,250,.8)"
          :style="{ left: transportPercent + '%' }"
        ></div>
      </div>

      <!-- Readout. Click toggles time ↔ frames (persisted, like the prep frame picker).
           Fixed min-width + right alignment: the ticking digits must not reflow the
           bar, or the text moves out from under the cursor mid-click. -->
      <button
        @pointerdown.stop="toggleTransportDisplayMode"
        :title="transportDisplayMode === 'frames' ? 'Show time' : 'Show frame number'"
        class="bg-transparent border-none text-[11px] text-blue-400 font-medium tabular-nums hover:text-blue-300 hover:bg-white/10 rounded-md cursor-pointer whitespace-nowrap flex-shrink-0 px-1.5 py-1 min-w-[96px] text-right"
      ><span class="pointer-events-none">{{ transportLabel }}</span></button>
    </div>

    <!-- Project Picker Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showProjectPicker" class="fixed inset-0 z-[10000] flex items-center justify-center bg-black/75 p-5" @click.self="closeProjectPicker">
          <div class="flex max-h-[80vh] w-full max-w-[400px] flex-col rounded-xl border border-edge-subtle bg-surface shadow-2xl">
            <div class="flex items-center justify-between border-b border-edge-subtle px-5 py-4">
              <h2 class="text-lg font-semibold text-content">Projects</h2>
              <button
                class="rounded p-1 text-content-tertiary transition-colors hover:bg-overlay-light hover:text-content"
                @click="closeProjectPicker"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-5 w-5">
                  <path d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="flex flex-col max-h-[420px]">
              <!-- Search -->
              <div class="px-4 py-3 border-b border-edge-subtle flex-shrink-0">
                <input
                  ref="projectPickerSearch"
                  v-model="projectPickerQuery"
                  type="text"
                  placeholder="Search projects..."
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded px-3 py-1.5 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
                />
              </div>
              <div class="overflow-y-auto flex-1 py-1">
                <div v-if="projectPickerLoading" class="px-4 py-3 text-xs text-content-tertiary">Loading...</div>
                <div v-else-if="filteredPickerProjects.length === 0" class="px-4 py-3 text-xs text-content-tertiary">No projects</div>
                <label
                  v-for="project in filteredPickerProjects"
                  :key="project.id"
                  class="flex items-center gap-3 px-4 py-2 hover:bg-overlay-light cursor-pointer transition-colors"
                  :class="{ 'opacity-50 pointer-events-none': projectPickerBusy.has(project.id) }"
                >
                  <input
                    type="checkbox"
                    :checked="projectPickerMembership.has(project.id)"
                    @change="toggleProjectMembership(project.id, $event.target.checked)"
                    class="accent-blue-500 w-3.5 h-3.5"
                  />
                  <span class="text-xs text-content" :class="project.name ? '' : 'italic text-content-muted'">{{ project.name || 'Untitled' }}</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Board Picker Modal -->
    <BoardPicker
      :visible="showBoardPicker"
      :media-ids="currentPayloadId ? [currentPayloadId] : []"
      :asset-ids="currentAssetId ? [currentAssetId] : []"
      @close="showBoardPicker = false"
      @saved="handleBoardAdded"
    />

    <!-- Export Modal -->
    <ExportModal
      :show="showExportModal"
      :media-ids="currentPayloadId ? [currentPayloadId] : []"
      :media-items="currentPayloadItem ? [currentPayloadItem] : []"
      @close="showExportModal = false"
    />

    <!-- Share Dialog -->
    <ShareDialog
      v-model="showShareDialog"
      :media-item="currentPayloadItem"
    />

    <!-- Context Menu (teleports to body) -->
    <MediaContextMenu />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useTelemetry } from '../composables/useTelemetry'
import { addToast } from '../composables/useToasts'
import { useProvidersApi } from '../composables/useProvidersApi'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { useWebSocket } from '../composables/useWebSocket'
import { useTauriDrag } from '../composables/useTauriDrag'
import { createDragPreview, preloadDragPreview, handleDragEnd } from '../composables/useDragPreview'
import { useGlobalKeyboardShortcuts } from '../composables/useGlobalKeyboardShortcuts'
import { useBrowseFilters } from '../composables/useBrowseFilters'
import { useMediaPlayback, useManagedMediaElement } from '../composables/useMediaPlayback'
import { usePrint } from '../composables/usePrint'
import axios from 'axios'
import {
  SpeakerWaveIcon,
  SpeakerXMarkIcon,
  ArrowsRightLeftIcon,
  ArrowsPointingOutIcon,
  DocumentIcon,
  PlayIcon,
  PauseIcon
} from '@heroicons/vue/24/solid'
import BoardPicker from './BoardPicker.vue'
import ExportModal from './ExportModal.vue'
import ShareDialog from './ShareDialog.vue'
import HorizontalVirtualScroller from './HorizontalVirtualScroller.vue'
import { captioningEnabledRef } from '../appConfig'
import MarkerBadges from './MarkerBadges.vue'
import SlideshowInfoPanel from './SlideshowInfoPanel.vue'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import SlideshowApprovalBar from './flow/SlideshowApprovalBar.vue'
import { MediaContextMenu, MediaImage } from './media'
import { formatRemainingTime, getRemainingTimeColor } from '../utils/timeFormat'
import { getMediaType, isVideo as isVideoType, isAudio as isAudioType, isStructured as isStructuredType, isLayout as isLayoutType } from '../utils/mediaTypes'
import { AudioPlayer, MarkdownViewer, GridViewer, SetOverview, LayoutViewer } from './viewers'
import { makeProfileKey, makeToolDbKey } from '../utils/storageKeys'
import { MseLoopPlayback } from '../utils/mseLoopPlayback'
import { useWorkspaceTabs, toolInstanceScopedId, toolInstanceRoute } from '../composables/useWorkspaceTabs'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'
import { getApiBase } from '../apiConfig'
import { assetIdOf, mediaIdOf, hasAssetIdentity } from '../utils/assetIdentity'
import {
  diffInsertedLiveIds,
  orderLiveAdvanceCandidates,
  orderLiveAdvanceKeys,
  shouldQueueLiveArrival
} from '../utils/slideshowLiveQueue'

const router = useRouter()
const { nextEditorId } = useWorkspaceTabs()
const { setKeywordFilter, setTagFilter, setSimilarFilter } = useBrowseFilters()

const props = defineProps({
  totalCount: {
    type: Number,
    default: 0
  },
  startIndex: {
    type: Number,
    default: 0
  },
  /**
   * Shared media list (preferred). When provided, uses the shared cache
   * for items, ensuring grid and slideshow always see the same order.
   */
  mediaList: {
    type: Object,
    default: null
  },
  /**
   * Page provider function (fallback). Used when mediaList is not provided.
   */
  pageProvider: Function,
  /**
   * Live provider-order item ids for pageProvider-backed streams
   * (generate-forever). Arrival pinning diffs successive values of this list,
   * so pins are 1:1 with items actually entering the provider order — the
   * completion WS event fires before the jobs manager exposes the job (it
   * prefetches media first), so an event-time index lookup would miss.
   */
  liveItemIds: {
    type: Array,
    default: null
  },
  randomSeed: Number,
  randomized: Boolean,
  autoAdvanceOnNew: Boolean,
  inline: {
    type: Boolean,
    default: false
  },
  isTrashView: {
    type: Boolean,
    default: false
  },
  // For nested slideshow (viewing source images)
  items: {
    type: Array,
    default: null
  },
  index: {
    type: Number,
    default: 0
  },
  showThumbnailStrip: {
    type: Boolean,
    default: true
  },
  // Optional approval context for the current item. When non-null, a
  // floating Approve/Replace/Unapprove bar appears at the bottom of the
  // image area (mirroring FlowView's approval treatment) and the
  // up/w approves+advances while awaiting and advances while approved.
  // down/s rejects while awaiting and unapproves while approved.
  // Parent handles the actual mutation via the
  // approve/reject/unapprove emits.
  approvalContext: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close', 'filterByKeyword', 'findSimilar', 'update:index', 'update:currentMediaId', 'update:randomized', 'update:randomSeed', 'navigate-to-media', 'compare-with-source', 'approve', 'reject', 'unapprove'])

const { getThumbnailUrl, getMediaFileUrl, getMseLoopUrls, getMediaItem, fetchMedia, deleteMedia, findMediaIndex, restoreFromTrash, permanentlyDeleteMedia, getMediaFaces, downloadMedia: downloadMediaApi, getProjects, addMediaToProject, removeMediaFromProject } = useMediaApi()
const {
  trash: trashAsset,
  restore: restoreAsset,
  permanentlyDelete: permanentlyDeleteAsset,
  addMarker: addMarkerToAsset,
  removeMarker: removeMarkerFromAsset,
  addToProject: addAssetsToProject,
  removeFromProject: removeAssetFromProject,
  removeFromBoardSection: removeAssetFromBoardSection,
  getProjects: getAssetProjects,
  getBoards: getAssetBoards,
} = useAssetApi()
const { on: onWebSocketEvent } = useWebSocket()
const { cachedTools, fetchProvidersAndTools } = useProvidersApi()
const { isTauri, handleDragStart: tauriDragStart, prewarmDragSnapshot } = useTauriDrag()

// Tooltip nudge for the (otherwise invisible) ⌥ drag-out modifier. Plain drag
// is an in-app transfer everywhere; the file-export modifier only applies in
// the native (Tauri) app.
const contextMenu = useMediaContextMenu()
const { printAssetDetail } = usePrint()

// Track IDs of items we're deleting to avoid double-handling via WebSocket
const deletingItemIds = ref(new Set())

// Track IDs of items removed locally (before server refresh) - strip will skip these
const localRemovedIds = ref(new Set())

// Face detection data
const faces = ref([])
const mediaContainer = ref(null)

// Info panel ref (for accessing face overlay visibility)
const infoPanelRef = ref(null)

// Computed: visible face overlays from the info panel
const visibleFaceOverlays = computed(() => {
  return infoPanelRef.value?.visibleFaceOverlays || new Set()
})

// Cache for metadata to avoid re-fetching when navigating back/forth
const metadataCache = ref(new Map()) // mediaId -> { faces, boards, job, chat }

// Flag to prevent watchers from firing during atomic transitions (infinity mode)
const isAtomicTransition = ref(false)

// --- Auto-advance engine (generate-forever) ---------------------------------
// In follow mode, NEW arrivals never swap the on-screen item. Arrivals shift the
// cache/currentIndex only to keep the displayed item's provider position honest,
// then enqueue stable live item keys. A dwell-gated stepper drains that queue one
// visible item at a time, so index churn cannot itself become an advance source.
//
// Minimum on-screen time before an auto-advance step (issue: don't blow past
// images during fast bursts). Videos additionally wait for a natural end.
const FOLLOW_MIN_DWELL_MS = 1500
// performance.now() timestamp when the currently-displayed item was shown. Drives
// the dwell floor for both follow-catch-up and the manual Play timer.
let currentShownAt = 0
// Pending dwell/floor timer (setTimeout handle) and serialization guard for the
// async preload+swap step. There is only ever one of each in flight.
let dwellTimer = null
let stepInFlight = false
let liveAdvanceEpoch = 0
// When true, the next logical MSE loop boundary performs the queued advance.
// False keeps the continuous A/V timeline looping in place.
const videoAdvanceArmed = ref(false)
const liveAdvanceQueue = ref([])

// WebSocket unsubscribe functions (cleaned up in onUnmounted)
const wsUnsubscribers = []

// Slideshow settings helpers (profile-scoped)
function getSettingsKey() {
  return makeProfileKey('slideshow', 'settings')
}

function loadSettings() {
  try {
    const saved = localStorage.getItem(getSettingsKey())
    return saved ? JSON.parse(saved) : {}
  } catch (e) {
    console.error('Failed to load slideshow settings:', e)
    return {}
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(getSettingsKey(), JSON.stringify(settings))
  } catch (e) {
    console.error('Failed to save slideshow settings:', e)
  }
}

// Load saved settings
const savedSettings = loadSettings()

// State
const currentIndex = ref(props.items ? props.index : props.startIndex)
const currentMediaId = ref(null) // Track by ID to survive list mutations (prepend/remove)
const isUserNavigating = ref(false) // Flag to distinguish user navigation from index drift
// True when the user is "riding the live stream" and should auto-advance through
// new arrivals. May be true while currentIndex > 0 (the stepper is catching up to
// the newest). The single source of truth for the auto-advance decision.
// INVARIANT: only an explicit user navigation landing on index 0 may set this
// true (synchronously, in the nav functions, so it can never go stale while a
// page loads or during an in-flight step). The baseCurrentItem backstop may only
// clear it. Browse mode (false) = no auto-advance; arrivals only pin.
const followStream = ref((props.items ? props.index : props.startIndex) === 0)
const localTotalCount = ref(props.items ? props.items.length : props.totalCount)
const refreshKey = ref(0) // Used to force image reload without index change
const isPlaying = ref(false)
const loopEnabled = ref(savedSettings.loopEnabled ?? false)
const showInfo = ref(false)
const showCaption = ref(false)
// Global video-channel mute/volume, shared with every video surface and
// persisted by the composable (so muting sticks across close/reopen).
const { videoMuted: isMuted, videoVolume: volume, toggleVideoMute } = useMediaPlayback()
const showVolumeSlider = ref(false)
const volumeSliderRef = ref(null)
const volumeButtonRef = ref(null)
const showSidebar = ref(true)
const controlBarOrientation = ref(savedSettings.controlBarOrientation ?? 'vertical')

// Image strip state (shows items from current dataset)
const showImageStrip = ref(savedSettings.showImageStrip ?? true)
const STRIP_HEIGHT = 136
const SIDEBAR_WIDTH = 384
const focusMode = ref(savedSettings.focusMode ?? false)
// Markers and boards state
const availableMarkers = ref([])
const mediaProjects = ref([])
const mediaBoards = ref([])
const showProjectPicker = ref(false)
const showBoardPicker = ref(false)
const showExportModal = ref(false)
const showShareDialog = ref(false)
const generationJob = ref(null)

// Chat source state (for "Jump to Chat" feature)
const chatInfo = ref(null)
const chatInfoLoading = ref(false)

// Descendants state (media derived from this item)
const descendants = ref([])
const inspiredDescendants = ref([])

// Randomization state
const shuffledIndices = ref([])
const isRandomized = ref(props.randomized ?? false)

// Set view stack - when viewing inside a set, this takes over the whole slideshow
// Each entry: { items: MediaItem[], title: string, returnToIndex: number }
const setViewStack = ref([])
const setViewIndex = ref(0) // Current index within the set view
const setViewLoading = ref(false)
const isViewingSet = computed(() => setViewStack.value.length > 0)

// Set title editing state
const isEditingSetTitle = ref(false)
const editingSetTitle = ref('')
const setTitleInput = ref(null)
const setTitleContainer = ref(null)
const setTitleContainerWidth = ref(null)

// Set overview data (when viewing SetOverview, before entering set view)
const setOverviewData = ref(null)

// Set overview title editing state
const isEditingSetOverviewTitle = ref(false)
const editingSetOverviewTitle = ref('')
const setOverviewTitleInput = ref(null)
const setOverviewTitleContainer = ref(null)
const setOverviewTitleContainerWidth = ref(null)

// Grid overview data (when viewing GridViewer, before entering grid view)
const gridOverviewData = ref(null)

// Grid overview title editing state
const isEditingGridOverviewTitle = ref(false)
const editingGridOverviewTitle = ref('')
const gridOverviewTitleInput = ref(null)
const gridOverviewTitleContainer = ref(null)
const gridOverviewTitleContainerWidth = ref(null)

// Grid view stack - when viewing a cell in a grid, shows full slideshow features for that cell
// Each entry: { rows, cols, title, cells, cellMap }
const gridViewStack = ref([])
const gridViewRow = ref(0)
const gridViewCol = ref(0)
const gridHeadersExpanded = ref(false)
const isViewingGrid = computed(() => gridViewStack.value.length > 0)

// Grid multi-select state for compare feature
const gridMultiSelectMode = ref(false)
const gridSelectedCells = ref([]) // Array of {row, col, mediaId, fileHash}

// Grid item view title editing state
const isEditingGridTitle = ref(false)
const editingGridTitle = ref('')
const gridTitleInput = ref(null)
const gridTitleContainer = ref(null)
const gridTitleContainerWidth = ref(null)

// Item cache for lazy loading
const itemsCache = ref(new Map())
const markerUpdateTrigger = ref(0) // Force re-render when markers change
const loadingPages = ref(new Map()) // Maps page number to loading promise
let pageProviderCacheRevision = 0
const displayItem = ref(null) // Item to display (stays visible while loading next)
const mediaLoaded = ref(false) // Track whether current media has finished loading
const stripRefreshKey = ref(0) // Force strip remount independently
const stripScrollerRef = ref(null) // Reference to HorizontalVirtualScroller for manual refresh

function invalidatePageProviderLoads() {
  if (props.mediaList) return
  pageProviderCacheRevision++
  loadingPages.value = new Map()
}

// Slideshow durations (in seconds)
const DURATIONS = [1, 2, 5, 10, 15, 20, 30, 60]
const currentDurationIndex = ref(savedSettings.durationIndex ?? 3) // Default to 10s
const slideshowTimer = ref(null)

const videoElement = ref(null)
let msePlayback = null
// Registry wiring: pause on KeepAlive deactivate, tear down on unmount/keyed
// swap (a removed element otherwise keeps playing its audio per spec).
useManagedMediaElement(videoElement)

// --- Video transport (filmstrip scrubber) ---
const showVideoTransport = ref(savedSettings.showVideoTransport ?? true)
const videoCurrentTime = ref(0)
const videoDuration = ref(0)
const videoPaused = ref(false)
const videoFps = ref(0)
const transportStripReady = ref(false)
const transportStripFailed = ref(false)
const transportScrubbing = ref(false)
// Readout mode (time vs frames), persisted in the same namespace as the prep
// frame picker so the click-to-toggle behavior matches everywhere.
const TRANSPORT_FRAME_MODE_KEY = 'slideshow'
const transportDisplayMode = ref('time')
try {
  transportDisplayMode.value =
    localStorage.getItem(makeProfileKey('frame-mode', TRANSPORT_FRAME_MODE_KEY)) === 'frames' ? 'frames' : 'time'
} catch { /* default to time */ }

function destroyMsePlayback() {
  msePlayback?.destroy()
  msePlayback = null
}

watch(
  [videoElement, () => (displayItem.value && isVideoType(displayItem.value) ? displayItem.value.file_hash : null)],
  ([element, fileHash]) => {
    destroyMsePlayback()
    if (!element || !fileHash) return

    element.muted = isMuted.value
    element.volume = volume.value
    const playback = new MseLoopPlayback(element, getMseLoopUrls(fileHash), {
      onBoundary: () => {
        if (videoAdvanceArmed.value) onVideoEnded()
      },
      onReady: (readyPlayback) => {
        if (msePlayback !== readyPlayback) return
        videoDuration.value = readyPlayback.duration
        mediaLoaded.value = true
      },
      onError: (error) => {
        if (msePlayback !== playback) return
        console.error('[SlideshowMode] Seamless video playback failed:', error)
        addToast('Could not prepare this video for seamless playback', 'error')
      },
      onMaintenanceError: (error) => {
        if (msePlayback === playback) {
          console.warn('[SlideshowMode] Seamless playback buffer maintenance deferred:', error)
        }
      },
    })
    msePlayback = playback
    void playback.start().catch(() => {})
  },
  { flush: 'post' },
)
const controlBar = ref(null)
const overlay = ref(null)
const gridViewerRef = ref(null)

// Cursor hiding state for focus mode
let cursorTimeout = null
const CURSOR_HIDE_DELAY = 3000 // 3 seconds

// Control bar dragging state
const isDragging = ref(false)
const isHovered = ref(false)
// Default position: upper-left, below the top chrome row (Back/Exit pills,
// title, close button sit at top-4 and are 48px tall → row ends at y=64).
const CONTROL_BAR_DEFAULT_LEFT = 24
const CONTROL_BAR_DEFAULT_TOP = 80
const controlBarEdgeAnchors = ref({
  horizontal: savedSettings.controlBarHorizontalEdge ?? 'left', // 'left' or 'right'
  vertical: savedSettings.controlBarVerticalEdge ?? 'top', // 'top' or 'bottom'
  horizontalDistance: savedSettings.controlBarHorizontalDistance ?? CONTROL_BAR_DEFAULT_LEFT,
  verticalDistance: savedSettings.controlBarVerticalDistance ?? CONTROL_BAR_DEFAULT_TOP
})
const dragStart = ref({ x: 0, y: 0 })
const dragDistance = ref(0)
const preventClick = ref(false)

// Zoom and pan state
const zoomScale = ref(1)
const panX = ref(0)
const panY = ref(0)
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0 })
const lastPan = ref({ x: 0, y: 0 })
const mediaContainerRef = ref(null)
// Touch pinch state
const touchStartDistance = ref(0)
const touchStartScale = ref(1)
const touchStartCenter = ref({ x: 0, y: 0 })
const isTouchPanning = ref(false)
const lastTouchCenter = ref({ x: 0, y: 0 })

// Container size tracking for checker overlay positioning
const containerSize = ref({ width: 0, height: 0 })
let containerResizeObserver = null

// Whether we have exact image dimensions for precise positioning
const hasExactDimensions = computed(() => {
  const cw = containerSize.value.width
  const ch = containerSize.value.height
  const item = displayItem.value
  return !!(cw && ch && item?.width && item?.height)
})

// Computed style for image wrapper - positions it exactly where the image renders
const checkerOverlayStyle = computed(() => {
  const cw = containerSize.value.width
  const ch = containerSize.value.height
  const item = displayItem.value

  // Fallback to full container when dimensions not yet known
  if (!hasExactDimensions.value) {
    return {
      width: '100%',
      height: '100%',
      transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoomScale.value})`,
      transformOrigin: 'center center'
    }
  }

  const iw = item.width
  const ih = item.height
  const containerAspect = cw / ch
  const imageAspect = iw / ih

  let renderW, renderH
  if (imageAspect > containerAspect) {
    // Image is wider - constrained by width
    renderW = cw
    renderH = cw / imageAspect
  } else {
    // Image is taller - constrained by height
    renderH = ch
    renderW = ch * imageAspect
  }

  const left = (cw - renderW) / 2
  const top = (ch - renderH) / 2

  return {
    position: 'absolute',
    left: `${left}px`,
    top: `${top}px`,
    width: `${renderW}px`,
    height: `${renderH}px`,
    transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoomScale.value})`,
    transformOrigin: 'center center'
  }
})

// Source image viewing state - pushes onto a stack so we can go back
const sourceViewStack = ref([]) // Stack of { item, returnToIndex }
const isViewingSource = computed(() => sourceViewStack.value.length > 0)

// Computed
const baseCurrentItem = computed(() => {
  // If items are provided directly (nested slideshow), use those
  if (props.items && props.items.length > 0) {
    return props.items[currentIndex.value] || null
  }

  // If using shared mediaList, get item skipping locally removed ones
  if (props.mediaList) {
    const removedIds = localRemovedIds.value
    const targetIndex = getActualIndex(currentIndex.value)

    // If no removed items, direct lookup
    if (removedIds.size === 0) {
      return props.mediaList.getItem(targetIndex) || null
    }

    // Find the targetIndex-th non-removed item
    let actualIndex = 0
    let validCount = 0
    while (validCount <= targetIndex) {
      const item = props.mediaList.getItem(actualIndex)
      if (!item) return null

      if (!removedIds.has(itemIdentity(item))) {
        if (validCount === targetIndex) {
          return item
        }
        validCount++
      }
      actualIndex++
    }
    return null
  }

  // Otherwise use local items cache from pageProvider
  // Need to skip locally removed items similar to mediaList path
  const removedIds = localRemovedIds.value
  const targetIndex = getActualIndex(currentIndex.value)

  // If no removed items, direct lookup
  if (removedIds.size === 0) {
    return itemsCache.value.get(targetIndex) || null
  }

  // Find the targetIndex-th non-removed item in the cache
  let actualIndex = 0
  let validCount = 0
  const maxCacheIndex = Math.max(...itemsCache.value.keys(), -1)

  while (actualIndex <= maxCacheIndex + removedIds.size) {
    const item = itemsCache.value.get(actualIndex)
    if (item && !removedIds.has(itemIdentity(item))) {
      if (validCount === targetIndex) {
        return item
      }
      validCount++
    }
    actualIndex++
  }
  return null
})

// currentItem respects view stacks - shows appropriate item based on context
const currentItem = computed(() => {
  // Grid view takes precedence - show current cell's resolved item
  if (isViewingGrid.value && currentGridView.value) {
    const cell = getGridCellContent(gridViewRow.value, gridViewCol.value)
    return cell?.resolved || null
  }
  // Set view - show current set item
  if (isViewingSet.value && currentSetView.value) {
    return currentSetView.value.items[setViewIndex.value] || null
  }
  // Source view - show source item
  if (sourceViewStack.value.length > 0) {
    return sourceViewStack.value[sourceViewStack.value.length - 1].item
  }
  // ToolView live generation keeps the visible media pinned while the provider
  // list prepends underneath it. In that mode, consumers of currentItem should
  // see the same item as the actual media element, not the moving index target.
  if (props.autoAdvanceOnNew && displayItem.value) {
    return displayItem.value
  }
  return baseCurrentItem.value
})
const currentAssetId = computed(() => (
  currentItem.value && hasAssetIdentity(currentItem.value)
    ? assetIdOf(currentItem.value)
    : null
))
const currentPayloadId = computed(() => mediaIdOf(currentItem.value || {}))
const currentPayloadItem = computed(() => (
  currentItem.value && currentPayloadId.value
    ? {
        ...currentItem.value,
        id: currentPayloadId.value,
      }
    : null
))

function itemIdentity(item) {
  return item ? assetIdOf(item) : null
}

function itemPayloadId(item) {
  return item ? mediaIdOf(item) : null
}
const isCurrentItemTrashed = computed(() => {
  return currentItem.value?.deleted_at != null
})
const currentDuration = computed(() => DURATIONS[currentDurationIndex.value])
const isVideo = computed(() => {
  // Use displayItem (not currentItem) to prevent video restart when currentItem
  // temporarily becomes null during reactive updates (cache changes, etc.)
  if (!displayItem.value) return false
  return isVideoType(displayItem.value)
})

const isAudio = computed(() => {
  if (!displayItem.value) return false
  return isAudioType(displayItem.value)
})

const isText = computed(() => {
  if (!displayItem.value) return false
  return displayItem.value.file_format?.toLowerCase() === 'md'
})

const isSet = computed(() => {
  if (!displayItem.value) return false
  return displayItem.value.file_format?.toLowerCase() === 'stimmaset.json'
})

const isGrid = computed(() => {
  if (!displayItem.value) return false
  return displayItem.value.file_format?.toLowerCase() === 'stimmagrid.json'
})

const isLayout = computed(() => {
  if (!displayItem.value) return false
  return isLayoutType(displayItem.value)
})

// Navigation availability (handles set view mode)
const canGoPrevious = computed(() => {
  if (isViewingSet.value) {
    return setViewIndex.value > 0
  }
  return currentIndex.value > 0
})

const canGoNext = computed(() => {
  if (isViewingSet.value) {
    return setViewIndex.value < currentSetView.value.items.length - 1
  }
  return currentIndex.value < localTotalCount.value - 1
})

const isStructured = computed(() => {
  if (!displayItem.value) return false
  return isStructuredType(displayItem.value)
})

const currentMediaType = computed(() => {
  if (!displayItem.value) return 'image'
  return getMediaType(displayItem.value)
})
const keywordsArray = computed(() => {
  if (!currentItem.value || !currentItem.value.keywords) return []
  if (Array.isArray(currentItem.value.keywords)) return currentItem.value.keywords
  // If it's a comma-separated string, split it
  return currentItem.value.keywords.split(',').map(k => k.trim()).filter(k => k)
})

const generationMetadata = computed(() => {
  if (!currentItem.value || !currentItem.value.generation_metadata) return null
  try {
    return JSON.parse(currentItem.value.generation_metadata)
  } catch (e) {
    console.error('Failed to parse generation metadata:', e)
    return null
  }
})

function getStepParameters(stepLike) {
  const params = { ...((stepLike && stepLike.parameters) || {}) }
  if (params.seed === undefined && stepLike?.seed !== undefined && stepLike?.seed !== null) {
    params.seed = stepLike.seed
  }
  return params
}

// Build full generation history: current step + all ancestors from lineage_trace
// Each step has the same structure for uniform display
const generationHistory = computed(() => {
  if (!currentItem.value) return []

  // For imported items with no generation_metadata, show a single "imported" entry
  if (!generationMetadata.value) {
    return [{
      media_id: currentPayloadId.value,
      task_type: null,  // Will display as "imported" via fallback
      is_imported: true,
      model: null,
      generator: null,
      prompt: currentItem.value.extracted_prompt || null,
      negative_prompt: null,
      parameters: {
        width: currentItem.value.width,
        height: currentItem.value.height
      },
      generated_at: currentItem.value.indexed_date,
      source_inputs: [],
      tool_id: null,
      raw_metadata: currentItem.value.raw_metadata || null
    }]
  }

  try {
    const history = []
    const meta = generationMetadata.value
    const stepParameters = getStepParameters(meta)

    // Build step from generation metadata
    const step = {
      media_id: currentPayloadId.value,
      task_type: meta.task_type,
      model: meta.model,
      generator: meta.generator,
      prompt: meta.prompt,
      negative_prompt: meta.negative_prompt || stepParameters.negative_prompt,
      parameters: stepParameters,
      generated_at: meta.generated_at,
      source_inputs: Array.isArray(meta.source_inputs) ? meta.source_inputs : [],
      tool_id: meta.tool_id || null
    }

    // External imports: preserve imported UI treatment + raw metadata link
    if (meta.source === 'external') {
      step.is_imported = true
      step.raw_metadata = currentItem.value.raw_metadata || null
      // Add LoRAs into parameters for display
      if (Array.isArray(meta.loras) && meta.loras.length > 0) {
        step.parameters.loras = meta.loras.map(l => ({
          lora: l?.name,
          weight: l?.weight
        }))
      }
    }

    history.push(step)

    // Add ancestor steps from lineage_trace (already in order: oldest first, so we reverse)
    // Lineage trace now contains full metadata for complete history display
    if (Array.isArray(meta.lineage_trace) && meta.lineage_trace.length > 0) {
      // lineage_trace is oldest-first, so reverse to show most recent first after current
      const ancestors = [...meta.lineage_trace].reverse()
      for (const ancestor of ancestors) {
        if (!ancestor) continue
        const ancestorParameters = getStepParameters(ancestor)
        history.push({
          media_id: ancestor.media_id,
          task_type: ancestor.task_type,
          model: ancestor.model,
          generator: ancestor.generator,
          // Use full prompt if available, fall back to prompt_preview for older data
          prompt: ancestor.prompt || ancestor.prompt_preview || null,
          negative_prompt: ancestor.negative_prompt || ancestorParameters.negative_prompt || null,
          parameters: ancestorParameters,
          generated_at: ancestor.generated_at,
          source_inputs: Array.isArray(ancestor.source_inputs) ? ancestor.source_inputs : [],
          tool_id: ancestor.tool_id || null
        })
      }
    }

    return history
  } catch (err) {
    console.error('Failed to build generation history:', err)
    return []
  }
})

const canSendToGenerate = computed(() => {
  if (!currentItem.value) return false
  return !!(currentItem.value.generation_metadata || currentItem.value.raw_metadata || currentItem.value.vlm_caption)
})

const hasRawMetadata = computed(() => {
  if (!currentItem.value) return false
  return !!(currentItem.value.raw_metadata && !currentItem.value.generation_metadata)
})

// Update displayItem when currentItem changes (but only if it's ready)
// Resolve the metadata-embedded drag snapshot for the shown item up front, so
// the control-strip "drag out" handle (and ⌥-drag) can start the native drag
// synchronously from cache. Embedding inline during dragstart awaits a
// round-trip that outlives the mouse gesture and crashes the macOS drag plugin.
watch(currentItem, (newItem) => {
  const mediaId = itemPayloadId(newItem)
  if (isTauri.value && mediaId != null && newItem.file_path) {
    prewarmDragSnapshot(mediaId)
  }
}, { immediate: true })

watch(currentItem, (newItem) => {
  console.log('[SlideshowDebug] current_item_watch', {
    newItemId: newItem?.id,
    file_format: newItem?.file_format,
    file_hash: newItem?.file_hash,
    isAtomicTransition: isAtomicTransition.value
  })

  // Skip during atomic transitions - we'll set displayItem manually
  if (isAtomicTransition.value) return

  // Lock the on-screen image unless a non-live slideshow is accepting an index
  // change. In live ToolView mode, currentItem itself resolves to displayItem, so
  // arrivals cannot flow through this watcher and must use the queued stepper.
  // In generate-forever mode the underlying list mutates constantly as new images
  // arrive; index/cache churn (arrival pins, page refetches, drift correction) must
  // never swap the display. Blessed display changes bypass this watcher entirely:
  // user navigation lands via the baseCurrentItem accept path / stepFromAnchor, and
  // follow catch-up steps via performFollowStep (isAtomicTransition).
  if (
    props.autoAdvanceOnNew &&
    !(followStream.value && currentIndex.value === 0) &&
    currentMediaId.value != null &&
    itemIdentity(newItem) !== currentMediaId.value
  ) {
    console.log(`[SlideshowDebug] display_item_locked itemId=${newItem?.id} pinned=${currentMediaId.value}`)
    return
  }

  // Generate-forever only: if we're already showing this exact image, skip reassignment
  // so we don't reset mediaLoaded and flash a reload. Page refetches during streaming
  // return fresh object instances with the same id/hash. Scoped to autoAdvanceOnNew so
  // other views still pick up in-place updates (e.g. caption/metadata) for the same item.
  if (
    props.autoAdvanceOnNew &&
    newItem && displayItem.value &&
    itemIdentity(newItem) === itemIdentity(displayItem.value) &&
    newItem.file_hash === displayItem.value.file_hash
  ) {
    return
  }

  // Accept items with file_hash, _placeholder flag, or valid id (for structured media)
  if (newItem && (newItem.file_hash || newItem._placeholder || newItem.id)) {
    console.log(`[SlideshowDebug] display_item_set_watch itemId=${newItem?.id} hasHash=${!!newItem?.file_hash}`)
    mediaLoaded.value = false // Reset loading state for new media
    displayItem.value = newItem
    // Preload drag preview thumbnail for faster drag start
    if (newItem.file_hash) {
      preloadDragPreview(getThumbnailUrl(newItem.file_hash, 128))
    }
  }
}, { immediate: true })

// Blessed display write for user-navigation acceptance. The currentItem watcher
// above locks all unblessed identity changes, so navigation must set the screen
// explicitly. Mirrors the watcher's display-set, including the same-id+hash skip
// so a re-fetched instance of the already-shown item doesn't flash a reload.
function applyDisplayItem(newItem) {
  if (!newItem || (!newItem.file_hash && !newItem._placeholder && !newItem.id)) return
  if (
    displayItem.value &&
    itemIdentity(newItem) === itemIdentity(displayItem.value) &&
    newItem.file_hash === displayItem.value.file_hash
  ) return
  mediaLoaded.value = false
  displayItem.value = newItem
  if (newItem.file_hash) preloadDragPreview(getThumbnailUrl(newItem.file_hash, 128))
}

function applyMediaPatchToLocalState(mediaId, updates) {
  if (!mediaId || !updates || Object.keys(updates).length === 0) return

  let cacheChanged = false
  const newCache = new Map(itemsCache.value)
  for (const [index, item] of itemsCache.value.entries()) {
    if (itemPayloadId(item) === mediaId) {
      newCache.set(index, { ...item, ...updates })
      cacheChanged = true
    }
  }
  if (cacheChanged) {
    itemsCache.value = newCache
  }

  if (props.mediaList?.updateItem) {
    const identity = currentItem.value && itemPayloadId(currentItem.value) === mediaId
      ? itemIdentity(currentItem.value)
      : mediaId
    props.mediaList.updateItem(identity, updates)
  }

  if (itemPayloadId(displayItem.value) === mediaId) {
    displayItem.value = { ...displayItem.value, ...updates }
  }

  for (const stackEntry of sourceViewStack.value) {
    if (itemPayloadId(stackEntry.item) === mediaId) {
      stackEntry.item = { ...stackEntry.item, ...updates }
    }
  }
}

function mediaUpdatePatch(fields = [], media = {}) {
  const patch = {}
  if (fields.includes('caption') || fields.includes('prompt') || fields.includes('metadata')) {
    Object.assign(patch, media)
  }
  if (fields.includes('markers')) {
    patch.markers = media.markers || []
  }
  if (fields.includes('tags')) {
    patch.tags = media.tags || []
  }
  return patch
}

// Single re-arm point: whenever the actually-displayed item changes identity
// (user navigation, a follow-step, a play-step, or initial load), stamp when it
// was shown, reset zoom for the new image, and (re)arm the advance scheduler for
// the new item. Pins (arrival-driven currentIndex++) do NOT change displayItem's
// id, so they never reset zoom or restart the dwell clock here.
watch(() => itemIdentity(displayItem.value), (newId, oldId) => {
  if (newId == null || newId === oldId) return
  currentShownAt = performance.now()
  resetZoom()
  scheduleAdvance()
})

// No auto-enter for sets - they behave like all other media types.
// Users see the set cover and can interact with it (markers, tags, etc).
// Click "View Set" button to enter and browse contents.

const hasOnlyCaption = computed(() => {
  if (!currentItem.value) return false
  return !!(currentItem.value.vlm_caption && !currentItem.value.generation_metadata && !currentItem.value.raw_metadata)
})

const controlBarStyle = computed(() => {
  const anchors = controlBarEdgeAnchors.value
  // In focus mode, treat sidebar as if it's not there
  const sidebarWidth = (showSidebar.value && !focusMode.value) ? SIDEBAR_WIDTH : 0
  // Account for image strip height when visible
  const relatedStripOffset = (showImageStrip.value && !focusMode.value) ? STRIP_HEIGHT : 0

  // If we have saved edge anchors, calculate position from edges
  if (anchors.horizontal !== null && anchors.vertical !== null) {
    const style = {}

    // Clamp distances to non-negative. A stale/corrupt persisted value
    // (e.g. from dragging the bar underneath the sidebar/strip before that
    // was prevented) could otherwise push the bar off-screen with no way
    // to get it back short of clearing localStorage.
    const horizontalDistance = Math.max(0, anchors.horizontalDistance)
    const verticalDistance = Math.max(0, anchors.verticalDistance)

    // Calculate horizontal position
    if (anchors.horizontal === 'left') {
      // When anchored to left, no sidebar adjustment needed (sidebar is on right)
      style.left = `${horizontalDistance}px`
      style.right = 'auto'
    } else {
      // When anchored to right, account for sidebar on right
      style.right = `${sidebarWidth + horizontalDistance}px`
      style.left = 'auto'
    }

    // Calculate vertical position
    if (anchors.vertical === 'top') {
      style.top = `${verticalDistance}px`
      style.bottom = 'auto'
    } else {
      // When anchored to bottom, account for related strip
      style.bottom = `${verticalDistance + relatedStripOffset}px`
      style.top = 'auto'
    }

    style.transform = 'none'
    return style
  }

  // Default: center in available space (accounting for sidebar on right)
  // Also account for related strip when visible
  const defaultStyle = {
    left: `calc((100% - ${sidebarWidth}px) / 2)`,
    transform: 'translateX(-50%)'
  }

  if (relatedStripOffset > 0) {
    defaultStyle.bottom = `${relatedStripOffset + 32}px` // 32px = default bottom-8
  }

  return defaultStyle
})

// Video transport bar: centered over the media area (sidebar-aware) and lifted
// above the image strip. Sits low (near the viewer bottom) — the control bar is
// user-draggable, so we don't reserve space for its default spot.
const transportBarStyle = computed(() => {
  const sidebarWidth = (showSidebar.value && !focusMode.value) ? SIDEBAR_WIDTH : 0
  const relatedStripOffset = (showImageStrip.value && !focusMode.value) ? STRIP_HEIGHT : 0
  return {
    left: `calc((100% - ${sidebarWidth}px) / 2)`,
    transform: 'translateX(-50%)',
    bottom: `${relatedStripOffset + 24}px`,
    maxWidth: `calc((100% - ${sidebarWidth}px) * 0.75)`
  }
})

// Watch currentIndex and emit updates for URL state.
// NOTE: arrival-driven pins (currentIndex++) also fire this watcher, so the
// view-disrupting side-effects below are gated to genuine USER navigation —
// otherwise every new image would exit an open set / clear overviews / etc.
// Zoom reset now lives on the displayItem identity watch above (only on a real
// image change, not on a pin). isUserNavigating is still true here because this
// watcher is registered before the baseCurrentItem watcher that clears it.
watch(currentIndex, (newIndex) => {
  emit('update:index', newIndex)

  if (!isUserNavigating.value) return

  // Exit set view mode when navigating to a different item in the main slideshow
  if (isViewingSet.value) {
    exitSetView()
  }
  // Reset grid multi-select mode when navigating to a different item
  if (gridMultiSelectMode.value) {
    gridMultiSelectMode.value = false
    gridSelectedCells.value = []
  }
  // Clear overview data when navigating away
  setOverviewData.value = null
  gridOverviewData.value = null
})

// Track currentMediaId from baseCurrentItem - updates when we navigate or item loads
// Also detects index drift (when items shift due to prepend/remove) and corrects it
watch(baseCurrentItem, (newItem) => {
  const newIdentity = itemIdentity(newItem)
  if (newIdentity) {
    // If user is navigating, always accept the new item
    if (isUserNavigating.value) {
      isUserNavigating.value = false
      // Backstop for the synchronous followStream set in the nav functions. This
      // may only DISABLE follow (the index moved off 0 while the nav was pending,
      // e.g. an arrival pinned it) — enabling follow happens exclusively in the
      // nav functions, from an explicit user landing on the newest item. Async
      // drift must never be able to turn auto-advance back on.
      if (currentIndex.value !== 0) followStream.value = false
      console.log(`[SlideshowMode] User navigation: setting currentMediaId = ${newIdentity} followStream=${followStream.value}`)
      currentMediaId.value = newIdentity
      emit('update:currentMediaId', newIdentity)
      // The currentItem watcher locks unblessed changes, so land the navigation
      // on the screen explicitly.
      applyDisplayItem(newItem)
      return
    }

    // If we have a tracked ID and the new item doesn't match, indices have shifted (drift)
    // Recalculate the correct index instead of accepting the wrong item.
    if (currentMediaId.value && newIdentity !== currentMediaId.value) {
      if (props.mediaList) {
        // mediaList path (browse / flow views) - original behavior, unchanged.
        // Special case: if we're at index 0 (viewing newest), accept the new item
        // This lets users "follow" the newest image as new ones are generated
        if (currentIndex.value === 0) {
          console.log(`[SlideshowMode] At index 0, accepting new newest item ${newIdentity} (was tracking ${currentMediaId.value})`)
          // Fall through to accept the new item
        } else {
          const correctIndex = props.mediaList.findIndex(currentMediaId.value)
          if (correctIndex >= 0 && correctIndex !== currentIndex.value) {
            console.log(`[SlideshowMode] Index drift detected! Item at index ${currentIndex.value} is ${newIdentity}, but we want ${currentMediaId.value} which is now at ${correctIndex}`)
            currentIndex.value = correctIndex
            return // Don't update currentMediaId - we corrected the index instead
          }
          // If we couldn't find our tracked item, it was probably deleted - accept the new item
          console.log(`[SlideshowMode] Tracked item ${currentMediaId.value} not found in list, accepting new item ${newIdentity}`)
        }
      } else if (props.autoAdvanceOnNew) {
        // pageProvider generate-forever path (ToolView): no mediaList, so locate the
        // pinned item by scanning itemsCache and correct the index instead of accepting
        // the wrong item. This protects against the list shifting under us as new images
        // stream in. Other pageProvider views (no autoAdvanceOnNew) keep original behavior
        // (no drift handling) by falling through.
        // Only "snap to newest" when actually caught up and no queued arrival is
        // draining. While following with a queue we are pinned to a specific older
        // item just like browse mode, so fall through to the scan-and-correct path
        // to keep tracking it; otherwise drift would yank us to the newest. The
        // stepper updates currentMediaId itself, so its decrements never reach here.
        if (followStream.value && currentIndex.value === 0 && liveAdvanceQueue.value.length === 0) {
          console.log(`[SlideshowMode] Caught up at index 0, accepting new newest item ${newIdentity} (was tracking ${currentMediaId.value})`)
          // Fall through to accept the new item
        } else {
          let correctIndex = -1
          for (const [index, item] of itemsCache.value.entries()) {
            if (item && itemIdentity(item) === currentMediaId.value) {
              correctIndex = index
              break
            }
          }
          if (correctIndex >= 0 && correctIndex !== currentIndex.value) {
            console.log(`[SlideshowMode] Index drift detected (pageProvider)! want ${currentMediaId.value} now at ${correctIndex}, currentIndex=${currentIndex.value}`)
            currentIndex.value = correctIndex
            return // Don't update currentMediaId - we corrected the index instead
          }
          if (correctIndex < 0) {
            // Not in cache yet. Keep the display pinned by ID (the displayItem lock
            // handles the screen); do not accept the wrong item.
            console.log(`[SlideshowMode] Tracked item ${currentMediaId.value} not in cache; keeping pinned, ignoring ${newIdentity}`)
            return
          }
        }
      }
      // else: other pageProvider views - fall through to accept (original behavior)
    }

    // Normal case: update currentMediaId to match current item
    console.log(`[SlideshowMode] Setting currentMediaId = ${newIdentity} (was ${currentMediaId.value})`)
    currentMediaId.value = newIdentity
    emit('update:currentMediaId', newIdentity)
    if (props.autoAdvanceOnNew && followStream.value && currentIndex.value === 0 && liveAdvanceQueue.value.length === 0) {
      applyDisplayItem(newItem)
    }
  }
}, { immediate: true })

// Seeded random number generator (mulberry32)
function seededRandom(seed) {
  return function() {
    seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Create shuffled indices array using Fisher-Yates with seeded random
function createShuffledIndices(count, seed) {
  const rng = seededRandom(seed)
  const indices = Array.from({ length: count }, (_, i) => i)

  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [indices[i], indices[j]] = [indices[j], indices[i]]
  }

  return indices
}

// Get actual index (maps display position to actual item index)
function getActualIndex(displayIndex) {
  if (isRandomized.value && shuffledIndices.value.length > 0) {
    // Clamp displayIndex to valid range to prevent accessing undefined indices
    const clampedIndex = Math.max(0, Math.min(displayIndex, shuffledIndices.value.length - 1))
    return shuffledIndices.value[clampedIndex] ?? displayIndex
  }
  return displayIndex
}

// Get display index from actual index
function getDisplayIndex(actualIndex) {
  if (isRandomized.value && shuffledIndices.value.length > 0) {
    return shuffledIndices.value.indexOf(actualIndex)
  }
  return actualIndex
}

// Base page provider that works with either mediaList or pageProvider
const basePageProviderForStrip = computed(() => {
  if (props.mediaList) {
    // Create a page provider that uses the shared mediaList
    return async (pageNumber, pageSize) => {
      const items = await props.mediaList.loadPage(pageNumber, pageSize)
      return items
    }
  }
  return props.pageProvider
})

// Page provider for strip that respects shuffle order
const stripPageProvider = computed(() => {
  if (!isRandomized.value || !shuffledIndices.value.length) {
    return basePageProviderForStrip.value
  }

  // Return a wrapper that translates display indices to actual indices
  return async (chunkNum, chunkSize) => {
    const startDisplayIndex = chunkNum * chunkSize
    const endDisplayIndex = Math.min(startDisplayIndex + chunkSize, localTotalCount.value)

    // For each display index, get the actual index
    const actualIndices = []
    for (let i = startDisplayIndex; i < endDisplayIndex; i++) {
      const actualIdx = shuffledIndices.value[i]
      // Skip if index is out of bounds (can happen during count transitions)
      if (actualIdx === undefined) continue
      actualIndices.push(actualIdx)
    }

    // If no valid indices, return empty
    if (actualIndices.length === 0) {
      return []
    }

    // Group by actual chunk to minimize API calls
    const actualChunkMap = new Map()
    for (let i = 0; i < actualIndices.length; i++) {
      const actualIdx = actualIndices[i]
      const actualChunk = Math.floor(actualIdx / chunkSize)
      if (!actualChunkMap.has(actualChunk)) {
        actualChunkMap.set(actualChunk, [])
      }
      actualChunkMap.get(actualChunk).push({ displayLocalIdx: i, actualIdx })
    }

    // Fetch needed chunks and assemble results in display order
    const results = new Array(actualIndices.length)
    for (const [actualChunkNum, indices] of actualChunkMap) {
      const items = await basePageProviderForStrip.value(actualChunkNum, chunkSize)
      for (const { displayLocalIdx, actualIdx } of indices) {
        const localIdx = actualIdx - (actualChunkNum * chunkSize)
        results[displayLocalIdx] = items[localIdx]
      }
    }

    return results
  }
})

// Item getter for strip - reads directly from mediaList or itemsCache, skipping locally removed items
const stripItemGetter = computed(() => {
  // Access localRemovedIds.value to make this reactive
  const removedIds = localRemovedIds.value

  if (props.mediaList) {
    return (displayIndex) => {
      // Translate display index to actual index, skipping removed items
      let actualIndex = 0
      let validCount = 0
      const targetIndex = getActualIndex(displayIndex)

      // If no removed items, direct lookup
      if (removedIds.size === 0) {
        return props.mediaList.getItem(targetIndex)
      }

      // Find the targetIndex-th non-removed item
      while (validCount <= targetIndex) {
        const item = props.mediaList.getItem(actualIndex)
        if (!item) return null // Past loaded items

        if (!removedIds.has(itemIdentity(item))) {
          if (validCount === targetIndex) {
            return item
          }
          validCount++
        }
        actualIndex++
      }
      return null
    }
  }

  // pageProvider path - use itemsCache and skip removed items
  return (displayIndex) => {
    const targetIndex = getActualIndex(displayIndex)

    // If no removed items, direct lookup
    if (removedIds.size === 0) {
      return itemsCache.value.get(targetIndex) || null
    }

    // Find the targetIndex-th non-removed item in the cache
    let actualIndex = 0
    let validCount = 0
    const maxCacheIndex = Math.max(...itemsCache.value.keys(), -1)

    while (actualIndex <= maxCacheIndex + removedIds.size) {
      const item = itemsCache.value.get(actualIndex)
      if (item && !removedIds.has(itemIdentity(item))) {
        if (validCount === targetIndex) {
          return item
        }
        validCount++
      }
      actualIndex++
    }
    return null
  }
})

// Load items on demand
async function ensureItemLoaded(index) {
  // Guard against NaN or invalid indices
  if (!Number.isFinite(index) || index < 0) {
    console.warn(`Invalid index for ensureItemLoaded: ${index}`)
    return
  }

  // If using shared mediaList, delegate to it
  if (props.mediaList) {
    // Check if already in shared cache
    if (props.mediaList.getItem(index)) {
      return
    }
    // Load via shared mediaList (uses smaller page size for slideshow)
    await props.mediaList.ensureItemLoaded(index)
    return
  }

  // Local loading logic (when no shared mediaList)
  const pageSize = 50
  const pageNumber = Math.floor(index / pageSize)

  for (let attempt = 0; attempt < 3; attempt++) {
    // If item is already cached, return immediately
    if (itemsCache.value.has(index)) {
      return
    }

    // If page is already being loaded, wait for it. It may have been invalidated
    // by a live list shift, so fall through and retry when it resolves without the item.
    const existingLoad = loadingPages.value.get(pageNumber)
    if (existingLoad) {
      await existingLoad
      if (itemsCache.value.has(index)) return
      continue
    }

    const requestRevision = pageProviderCacheRevision

    // Start loading the page
    const loadPromise = Promise.resolve().then(async () => {
      try {
        const items = await props.pageProvider(pageNumber, pageSize)

        if (requestRevision !== pageProviderCacheRevision) {
          console.debug(`Slideshow: Ignoring stale page ${pageNumber} load after live list shift`)
          return
        }

        const startIndex = pageNumber * pageSize
        items.forEach((item, i) => {
          itemsCache.value.set(startIndex + i, item)
        })

        // Detect stale totalCount - if we got fewer items than expected on a page,
        // the actual total is smaller than localTotalCount
        const expectedItemsOnPage = Math.min(pageSize, localTotalCount.value - startIndex)
        if (items.length < expectedItemsOnPage && items.length < pageSize) {
          const actualTotal = startIndex + items.length
          if (actualTotal < localTotalCount.value) {
            console.warn(`Slideshow: Adjusting totalCount from ${localTotalCount.value} to ${actualTotal} (page ${pageNumber} had ${items.length} items, expected ${expectedItemsOnPage})`)
            localTotalCount.value = actualTotal

            // If currentIndex is now out of bounds, clamp it
            if (currentIndex.value >= actualTotal && actualTotal > 0) {
              console.warn(`Slideshow: Clamping currentIndex from ${currentIndex.value} to ${actualTotal - 1}`)
              currentIndex.value = actualTotal - 1
            }
          }
        }
      } catch (error) {
        console.error(`Failed to load page ${pageNumber}:`, error)
        throw error
      } finally {
        if (loadingPages.value.get(pageNumber) === loadPromise) {
          loadingPages.value.delete(pageNumber)
        }
      }
    })

    loadingPages.value.set(pageNumber, loadPromise)
    await loadPromise
  }
}

// Preload nearby items for smooth navigation
async function preloadNearbyItems(displayIndex) {
  const range = 5 // Preload 5 items before and after
  for (let i = Math.max(0, displayIndex - range); i <= Math.min(localTotalCount.value - 1, displayIndex + range); i++) {
    const actualIndex = getActualIndex(i)
    ensureItemLoaded(actualIndex)
  }
}

// Navigation

// Index of the item the user is actually LOOKING at. currentIndex can briefly
// disagree with the on-screen item while arrival pins / drift correction are
// reconciling a mutating list (generate-forever), so relative navigation must
// step from the anchor's real position, not from a possibly-drifted index.
function displayAnchorIndex() {
  // A nav is already pending (target page still loading): chain from its
  // target so rapid keypresses each advance one step.
  if (isUserNavigating.value) return currentIndex.value
  if (props.items || props.mediaList || isRandomized.value) return currentIndex.value
  if (currentMediaId.value == null || localRemovedIds.value.size > 0) return currentIndex.value
  for (const [index, item] of itemsCache.value.entries()) {
    if (item && itemIdentity(item) === currentMediaId.value) return index
  }
  return currentIndex.value
}

// Step `delta` items from the on-screen anchor. Landing on index 0 (the newest)
// is the ONLY way follow mode turns on; landing anywhere else always leaves it.
// Returns false when the target is out of range (caller decides wrap/stop).
function stepFromAnchor(delta) {
  const target = displayAnchorIndex() + delta
  if (target < 0 || target >= localTotalCount.value) return false
  clearLiveAdvanceQueue()
  followStream.value = target === 0
  if (target === currentIndex.value) {
    // The index had drifted off the anchor and already points at the target.
    // Assigning the same value is reactively inert (no watcher would fire), so
    // accept the cached item directly and apply the user-nav side effects here.
    const item = baseCurrentItem.value
    if (item?.id) {
      const identity = itemIdentity(item)
      currentMediaId.value = identity
      emit('update:currentMediaId', identity)
      applyDisplayItem(item)
      if (gridMultiSelectMode.value) {
        gridMultiSelectMode.value = false
        gridSelectedCells.value = []
      }
      setOverviewData.value = null
      gridOverviewData.value = null
    } else {
      // Target not loaded yet: leave the index in place, kick the page load
      // (the currentIndex watcher won't fire for an unchanged index), and let
      // the accept path land it once the item arrives.
      isUserNavigating.value = true
      void ensureItemLoaded(getActualIndex(target))
    }
    return true
  }
  isUserNavigating.value = true
  currentIndex.value = target
  return true
}

function next() {
  // Handle set view navigation
  if (isViewingSet.value) {
    if (setViewIndex.value < currentSetView.value.items.length - 1) {
      setViewIndex.value++
    }
    return
  }

  if (stepFromAnchor(1)) {
    resetSlideshowTimer()
  } else if (loopEnabled.value) {
    clearLiveAdvanceQueue()
    isUserNavigating.value = true
    currentIndex.value = 0
    followStream.value = true
    resetSlideshowTimer()
  } else {
    stopSlideshow()
  }
}

function previous() {
  // Handle set view navigation
  if (isViewingSet.value) {
    if (setViewIndex.value > 0) {
      setViewIndex.value--
    }
    return
  }

  if (stepFromAnchor(-1)) {
    resetSlideshowTimer()
  }
}

function goToFirst() {
  clearLiveAdvanceQueue()
  isUserNavigating.value = true
  currentIndex.value = 0
  followStream.value = true
  resetSlideshowTimer()
}

function goToLast() {
  clearLiveAdvanceQueue()
  isUserNavigating.value = true
  currentIndex.value = localTotalCount.value - 1
  followStream.value = currentIndex.value === 0
  resetSlideshowTimer()
}

function goToIndex(index) {
  if (index >= 0 && index < localTotalCount.value) {
    clearLiveAdvanceQueue()
    isUserNavigating.value = true
    currentIndex.value = index
    followStream.value = currentIndex.value === 0
    resetSlideshowTimer()
  }
}

// Set view navigation - pushes a new slideshow context for set items
async function enterSetView(mediaId, startIndex = 0) {
  console.log('[enterSetView] Called with mediaId:', mediaId, 'startIndex:', startIndex, 'setViewLoading:', setViewLoading.value)

  // Guard against undefined/null mediaId
  if (!mediaId) {
    console.error('[enterSetView] Called with undefined/null mediaId')
    return
  }

  // Guard against duplicate calls while loading
  if (setViewLoading.value) {
    console.warn('[enterSetView] Already loading, ignoring duplicate call')
    return
  }

  setViewLoading.value = true

  // Timeout protection: reset stuck loading state after 10 seconds
  const timeout = setTimeout(() => {
    if (setViewLoading.value) {
      console.error('[enterSetView] Timed out, resetting loading state')
      setViewLoading.value = false
    }
  }, 10000)

  try {
    const response = await axios.get(`/api/media/${mediaId}/content`)
    const data = response.data
    console.log('[enterSetView] Got response:', { items: data.items?.length, title: data.title })

    // Filter to only resolved items (items that exist in the library)
    const resolvedItems = (data.items || [])
      .filter(item => item.resolved)
      .map(item => item.resolved)

    console.log('[enterSetView] Resolved items:', resolvedItems.length)
    if (resolvedItems.length === 0) {
      console.warn('Set has no resolved items')
      return
    }

    // Push new set view context onto stack
    setViewStack.value.push({
      items: resolvedItems,
      title: data.title || '',
      returnToIndex: currentIndex.value,
      setMediaId: mediaId  // Store the set's media ID for title editing
    })
    setViewIndex.value = startIndex // Start at specified item
    setOverviewData.value = null // Clear overview data since we're now inside the set
    console.log('[enterSetView] Pushed to setViewStack, length now:', setViewStack.value.length, 'startIndex:', startIndex)

    stopSlideshow() // Pause slideshow when entering set
  } catch (e) {
    console.error('Failed to load set content:', e)
  } finally {
    clearTimeout(timeout)
    setViewLoading.value = false
  }
}

function exitSetView() {
  if (setViewStack.value.length > 0) {
    setViewStack.value.pop()
    setViewIndex.value = 0 // Reset index
    // Re-arm the advance engine now that the sub-view is closed.
    scheduleAdvance()
  }
}

// Handle item selection from SetOverview component
function handleSetItemSelect(event) {
  const { index, item, setData } = event
  console.log('[handleSetItemSelect] index:', index, 'item:', item.resolved?.id)

  // Enter the set view at the clicked item's index
  // We need to use displayItem.id to get the set's mediaId
  if (displayItem.value) {
    enterSetView(itemPayloadId(displayItem.value), index)
  }
}

// Handle SetOverview loaded event to get title for the pill display
function handleSetOverviewLoaded(data) {
  setOverviewData.value = data
}

// Set title editing functions
async function startEditingSetTitle() {
  if (!currentSetView.value || isEditingSetTitle.value) return
  // Capture current width before switching to input
  if (setTitleContainer.value) {
    setTitleContainerWidth.value = setTitleContainer.value.offsetWidth
  }
  isEditingSetTitle.value = true
  editingSetTitle.value = currentSetView.value.title || ''
  await nextTick()
  setTitleInput.value?.focus()
  setTitleInput.value?.select()
}

async function saveSetTitle() {
  if (!isEditingSetTitle.value) return

  const newTitle = editingSetTitle.value.trim()

  // Get the media ID of the set from the view stack
  const setMediaId = currentSetView.value?.setMediaId

  if (setMediaId && currentSetView.value) {
    try {
      await axios.patch(`/api/media/${setMediaId}/content`, {
        title: newTitle || null
      })
      // Update the local title
      currentSetView.value.title = newTitle || ''
    } catch (e) {
      console.error('Failed to update set title:', e)
    }
  }

  isEditingSetTitle.value = false
  editingSetTitle.value = ''
  setTitleContainerWidth.value = null  // Reset width lock
}

function cancelSetTitleEdit() {
  isEditingSetTitle.value = false
  editingSetTitle.value = ''
  setTitleContainerWidth.value = null  // Reset width lock
}

// Set overview title editing functions (when viewing set overview, before entering)
async function startEditingSetOverviewTitle() {
  if (!displayItem.value || isEditingSetOverviewTitle.value) return
  // Capture current width before switching to input
  if (setOverviewTitleContainer.value) {
    setOverviewTitleContainerWidth.value = setOverviewTitleContainer.value.offsetWidth
  }
  isEditingSetOverviewTitle.value = true
  editingSetOverviewTitle.value = setOverviewData.value?.title || ''
  await nextTick()
  setOverviewTitleInput.value?.focus()
  setOverviewTitleInput.value?.select()
}

async function saveSetOverviewTitle() {
  if (!isEditingSetOverviewTitle.value) return

  const newTitle = editingSetOverviewTitle.value.trim()
  const setMediaId = itemPayloadId(displayItem.value)

  if (setMediaId) {
    try {
      await axios.patch(`/api/media/${setMediaId}/content`, {
        title: newTitle || null
      })
      // Update the local overview data
      if (setOverviewData.value) {
        setOverviewData.value.title = newTitle || ''
      } else {
        setOverviewData.value = { title: newTitle || '' }
      }
    } catch (e) {
      console.error('Failed to update set title:', e)
    }
  }

  isEditingSetOverviewTitle.value = false
  editingSetOverviewTitle.value = ''
  setOverviewTitleContainerWidth.value = null
}

function cancelSetOverviewTitleEdit() {
  isEditingSetOverviewTitle.value = false
  editingSetOverviewTitle.value = ''
  setOverviewTitleContainerWidth.value = null
}

// Grid overview title editing functions (when viewing grid overview, before entering)
async function startEditingGridOverviewTitle() {
  if (!displayItem.value || isEditingGridOverviewTitle.value) return
  // Capture current width before switching to input
  if (gridOverviewTitleContainer.value) {
    gridOverviewTitleContainerWidth.value = gridOverviewTitleContainer.value.offsetWidth
  }
  isEditingGridOverviewTitle.value = true
  editingGridOverviewTitle.value = gridOverviewData.value?.title || ''
  await nextTick()
  gridOverviewTitleInput.value?.focus()
  gridOverviewTitleInput.value?.select()
}

async function saveGridOverviewTitle() {
  if (!isEditingGridOverviewTitle.value) return

  const newTitle = editingGridOverviewTitle.value.trim()
  const gridMediaId = itemPayloadId(displayItem.value)

  if (gridMediaId) {
    try {
      await axios.patch(`/api/media/${gridMediaId}/content`, {
        title: newTitle || null
      })
      // Update the local overview data
      if (gridOverviewData.value) {
        gridOverviewData.value.title = newTitle || ''
      } else {
        gridOverviewData.value = { title: newTitle || '' }
      }
    } catch (e) {
      console.error('Failed to update grid title:', e)
    }
  }

  isEditingGridOverviewTitle.value = false
  editingGridOverviewTitle.value = ''
  gridOverviewTitleContainerWidth.value = null
}

function cancelGridOverviewTitleEdit() {
  isEditingGridOverviewTitle.value = false
  editingGridOverviewTitle.value = ''
  gridOverviewTitleContainerWidth.value = null
}

// Grid item view title editing functions (when viewing expanded cell)
async function startEditingGridTitle() {
  if (!currentGridView.value || isEditingGridTitle.value) return
  // Capture current width before switching to input
  if (gridTitleContainer.value) {
    gridTitleContainerWidth.value = gridTitleContainer.value.offsetWidth
  }
  isEditingGridTitle.value = true
  editingGridTitle.value = currentGridView.value.title || ''
  await nextTick()
  gridTitleInput.value?.focus()
  gridTitleInput.value?.select()
}

async function saveGridTitle() {
  if (!isEditingGridTitle.value) return

  const newTitle = editingGridTitle.value.trim()
  const gridMediaId = currentGridView.value?.gridMediaId

  if (gridMediaId && currentGridView.value) {
    try {
      await axios.patch(`/api/media/${gridMediaId}/content`, {
        title: newTitle || null
      })
      // Update the local title
      currentGridView.value.title = newTitle || ''
    } catch (e) {
      console.error('Failed to update grid title:', e)
    }
  }

  isEditingGridTitle.value = false
  editingGridTitle.value = ''
  gridTitleContainerWidth.value = null
}

function cancelGridTitleEdit() {
  isEditingGridTitle.value = false
  editingGridTitle.value = ''
  gridTitleContainerWidth.value = null
}

// Current set view context (top of stack)
const currentSetView = computed(() => {
  if (setViewStack.value.length === 0) return null
  return setViewStack.value[setViewStack.value.length - 1]
})

// Grid view navigation - pushes context for viewing expanded cell with full slideshow features
function enterGridView(gridData, row, col, gridMediaId) {
  gridViewStack.value.push({
    rows: gridData.rows,
    cols: gridData.cols,
    title: gridData.title,
    cells: gridData.cells,
    cellMap: gridData.cellMap,
    rowHeaders: gridData.rowHeaders,
    colHeaders: gridData.colHeaders,
    gridMediaId: gridMediaId  // Store the grid's media ID for title editing
  })
  gridViewRow.value = row
  gridViewCol.value = col
  gridOverviewData.value = null  // Clear overview data since we're now inside the grid
  resetZoom() // Reset zoom when entering grid cell view
  stopSlideshow() // Pause slideshow when entering grid view
}

function exitGridView() {
  if (gridViewStack.value.length > 0) {
    gridViewStack.value.pop()
    gridViewRow.value = 0
    gridViewCol.value = 0
    gridHeadersExpanded.value = false
    resetZoom()
    // Re-arm the advance engine now that the sub-view is closed.
    scheduleAdvance()
  }
}

// Current grid view context (top of stack)
const currentGridView = computed(() => {
  if (gridViewStack.value.length === 0) return null
  return gridViewStack.value[gridViewStack.value.length - 1]
})

// Current row/column header text for grid view position indicator
const currentRowHeader = computed(() => {
  return currentGridView.value?.rowHeaders?.[gridViewRow.value] || null
})
const currentColHeader = computed(() => {
  return currentGridView.value?.colHeaders?.[gridViewCol.value] || null
})
const fullPositionText = computed(() => {
  const row = currentRowHeader.value || `Row ${gridViewRow.value + 1}`
  const col = currentColHeader.value || `Col ${gridViewCol.value + 1}`
  return `${row} × ${col}`
})

// Linear position in reading order (row-major)
const gridLinearPosition = computed(() => {
  if (!currentGridView.value) return 1
  return (gridViewRow.value * currentGridView.value.cols) + gridViewCol.value + 1
})
const gridTotalCells = computed(() => {
  if (!currentGridView.value) return 1
  return currentGridView.value.rows * currentGridView.value.cols
})

// Mini-map configuration for grid position visualization
const miniMapGrid = ref(null)
const miniMapConfig = computed(() => {
  if (!currentGridView.value) return null
  const { rows, cols } = currentGridView.value
  const maxDimension = Math.max(rows, cols)

  // Calculate cell size based on grid dimension
  let cellSize
  if (maxDimension <= 20) cellSize = 10
  else if (maxDimension <= 50) cellSize = Math.max(4, Math.floor(200 / maxDimension))
  else cellSize = Math.max(2, Math.floor(200 / maxDimension))

  return {
    rows,
    cols,
    cellSize,
    width: cols * cellSize,
    height: rows * cellSize
  }
})

// Handle click on mini-map to navigate to cell
function handleMiniMapClick(event) {
  if (!miniMapGrid.value || !miniMapConfig.value) return

  const rect = miniMapGrid.value.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top

  const { cellSize, rows, cols } = miniMapConfig.value
  const gap = cellSize >= 6 ? 1 : 0
  const cellWithGap = cellSize + gap

  const col = Math.min(Math.max(0, Math.floor(x / cellWithGap)), cols - 1)
  const row = Math.min(Math.max(0, Math.floor(y / cellWithGap)), rows - 1)

  // Only navigate if cell has content
  if (getGridCellContent(row, col)?.resolved) {
    gridViewRow.value = row
    gridViewCol.value = col
  }
}

// Get cell content from current grid view
function getGridCellContent(row, col) {
  if (!currentGridView.value) return null
  const key = `${row}-${col}`
  return currentGridView.value.cellMap.get(key) || null
}

// Handle cell selection from GridViewer
function handleGridCellSelect({ row, col, cell, gridData }) {
  // Pass the current displayItem.id as the gridMediaId
  enterGridView(gridData, row, col, itemPayloadId(displayItem.value))
}

// Handle GridViewer loaded event to get title for the pill display
function handleGridOverviewLoaded(data) {
  gridOverviewData.value = data
}

// Handle selection change from GridViewer (multi-select mode)
function handleGridSelectionChange(selectedList) {
  gridSelectedCells.value = selectedList
}

// Toggle grid multi-select mode
function toggleGridMultiSelectMode() {
  gridMultiSelectMode.value = !gridMultiSelectMode.value
  if (!gridMultiSelectMode.value) {
    // Clear selections when exiting multi-select mode
    gridSelectedCells.value = []
    gridViewerRef.value?.clearSelection()
  }
}

// Clear grid selection
function clearGridSelection() {
  gridSelectedCells.value = []
  gridViewerRef.value?.clearSelection()
}

// Compare selected grid cells
function compareGridCells() {
  if (gridSelectedCells.value.length !== 2) return

  const [left, right] = gridSelectedCells.value
  emit('compare-with-source', {
    leftMediaId: left.mediaId,
    rightMediaId: right.mediaId
  })

  // Exit multi-select mode after starting compare
  gridMultiSelectMode.value = false
  gridSelectedCells.value = []
  gridViewerRef.value?.clearSelection()
}


// Effective total count - set items when viewing set, otherwise main count
const effectiveTotalCount = computed(() => {
  if (isViewingSet.value) {
    return currentSetView.value.items.length
  }
  return localTotalCount.value
})

// Effective current index - set index when viewing set, otherwise main index
const effectiveIndex = computed(() => {
  if (isViewingSet.value) {
    return setViewIndex.value
  }
  return currentIndex.value
})

// Handle thumbnail loading errors with retry
const thumbnailRetries = ref(new Map())
async function handleThumbnailError(event, item, index) {
  const retryKey = `${index}-${item.file_hash}`
  const retryCount = thumbnailRetries.value.get(retryKey) || 0

  if (retryCount < 3) {
    // Retry after a delay
    thumbnailRetries.value.set(retryKey, retryCount + 1)
    setTimeout(async () => {
      // Clear the cached item and reload it
      const actualIndex = getActualIndex(index)
      itemsCache.value.delete(actualIndex)

      // Clear the page from loading cache to allow re-fetch
      const pageNumber = Math.floor(actualIndex / 50)
      loadingPages.value.delete(pageNumber)

      // Reload the item
      await ensureItemLoaded(actualIndex)

      // Force re-render
      if (event.target) {
        const reloadedItem = itemsCache.value.get(actualIndex)
        if (reloadedItem?.file_hash) {
          event.target.src = `${getThumbnailUrl(reloadedItem.file_hash, 256)}&t=${Date.now()}`
        }
      }
    }, 1000 * (retryCount + 1)) // Exponential backoff: 1s, 2s, 3s
  } else {
    console.error(`Failed to load thumbnail for index ${index} after 3 retries`)
  }
}

// Slideshow controls
// Telemetry: slideshow_control_used — closed enum pinned to the actual
// controls: next | prev | play | pause | shuffle | loop | mute | unmute |
// timer_set | focus_mode.
const { track: trackTelemetry } = useTelemetry()
function trackControl(control) {
  trackTelemetry('slideshow_control_used', { control }, 'feature')
}

function toggleSlideshow() {
  if (preventClick.value) return
  isPlaying.value = !isPlaying.value
  trackControl(isPlaying.value ? 'play' : 'pause')
  scheduleAdvance()
}

function userNext() {
  trackControl('next')
  next()
}

function userPrevious() {
  trackControl('prev')
  previous()
}

// Retained names — both Play and follow-catch-up now flow through the single
// advance engine (scheduleAdvance), which paces per item (image dwell floor vs
// video natural-end) instead of a fixed interval. stopSlideshowTimer clears all
// arming; resetSlideshowTimer re-arms for the current item.
function stopSlideshowTimer() {
  if (dwellTimer) {
    clearTimeout(dwellTimer)
    dwellTimer = null
  }
  videoAdvanceArmed.value = false
  // Legacy interval handle (no longer used, cleared defensively).
  if (slideshowTimer.value) {
    clearInterval(slideshowTimer.value)
    slideshowTimer.value = null
  }
}

function resetSlideshowTimer() {
  scheduleAdvance()
}

function stopSlideshow() {
  // Turn off the manual Play timer, then re-evaluate: follow-catch-up may still
  // be active and should keep running (it is independent of Play).
  isPlaying.value = false
  scheduleAdvance()
}

function increaseDuration() {
  if (currentDurationIndex.value < DURATIONS.length - 1) {
    currentDurationIndex.value++
    resetSlideshowTimer()
  }
}

function decreaseDuration() {
  if (currentDurationIndex.value > 0) {
    currentDurationIndex.value--
    resetSlideshowTimer()
  }
}

// Click the interval pill to step through the preset durations (wraps around).
// Keyboard w/s still nudges up/down without wrapping.
function cycleDuration() {
  trackControl('timer_set')
  currentDurationIndex.value = (currentDurationIndex.value + 1) % DURATIONS.length
  resetSlideshowTimer()
}

// Toggle randomization
async function toggleRandomize() {
  if (preventClick.value) return
  trackControl('shuffle')
  const savedIndex = currentIndex.value
  clearLiveAdvanceQueue()

  if (isRandomized.value) {
    // Turn off randomization - keep same display index
    isRandomized.value = false
    shuffledIndices.value = []
    emit('update:randomized', false)
    emit('update:randomSeed', null)
  } else {
    // Turn on randomization with new seed - keep same display index
    const seed = Date.now()
    isRandomized.value = true
    shuffledIndices.value = createShuffledIndices(localTotalCount.value, seed)
    emit('update:randomized', true)
    emit('update:randomSeed', seed)
  }

  // Load the item at the new actual index
  const actualIndex = getActualIndex(savedIndex)
  await ensureItemLoaded(actualIndex)

  // Also preload the temp index item to avoid errors when we toggle
  const tempIndex = savedIndex === 0 ? Math.min(1, localTotalCount.value - 1) : 0
  const tempActualIndex = getActualIndex(tempIndex)
  await ensureItemLoaded(tempActualIndex)

  // Force reactivity by briefly changing index to trigger computed re-evaluation
  currentIndex.value = tempIndex
  await nextTick()
  currentIndex.value = savedIndex

  // Preload nearby items in background
  preloadNearbyItems(savedIndex)

  resetSlideshowTimer()
}

// Toggles
function toggleInfo() {
  showInfo.value = !showInfo.value
}

function toggleCaption() {
  showCaption.value = !showCaption.value
}

function toggleLoop() {
  if (preventClick.value) return
  loopEnabled.value = !loopEnabled.value
  trackControl('loop')
}

function toggleMute() {
  if (preventClick.value) return
  trackControl(isMuted.value ? 'unmute' : 'mute')
  if (isVideo.value) {
    toggleVideoMute()
    // Apply to the element immediately (the isMuted watcher also does this, but
    // setting it here keeps the DOM in lockstep with the toggle within the gesture).
    if (videoElement.value) {
      videoElement.value.muted = isMuted.value
      if (!isMuted.value) videoElement.value.volume = volume.value
    }
  }
}

let volumeHoverTimer = null
function onVolumeHoverEnter() {
  if (!isVideo.value) return
  if (volumeHoverTimer) {
    clearTimeout(volumeHoverTimer)
    volumeHoverTimer = null
  }
  showVolumeSlider.value = true
}
function onVolumeHoverLeave() {
  // Small delay so moving the cursor across the gap into the popup doesn't close it.
  if (volumeHoverTimer) clearTimeout(volumeHoverTimer)
  volumeHoverTimer = setTimeout(() => {
    showVolumeSlider.value = false
    volumeHoverTimer = null
  }, 200)
}

function handleVolumeInput(event) {
  const val = parseFloat(event.target.value)
  volume.value = val
  isMuted.value = val === 0
  // Apply immediately (see toggleMute) so dragging the slider updates audio live.
  if (videoElement.value) {
    videoElement.value.muted = isMuted.value
    videoElement.value.volume = val
  }
}

function closeVolumeSlider(event) {
  if (!showVolumeSlider.value) return
  if (volumeSliderRef.value?.contains(event.target)) return
  if (volumeButtonRef.value?.contains(event.target)) return
  showVolumeSlider.value = false
}

// --- Video transport (filmstrip scrubber) ---

// The track is the same server-rendered frame-strip montage the prep frame
// picker uses; profile/pin ride along as query params because it loads via <img>.
const transportStripUrl = computed(() => {
  if (!isVideo.value || !displayItem.value?.file_path) return ''
  const base = getApiBase()
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let u = `${base}/generate/frame-strip?source_path=${encodeURIComponent(displayItem.value.file_path)}&count=12&w=96&profile=${encodeURIComponent(profileId)}`
  if (pin) u += `&pin=${encodeURIComponent(pin)}`
  return u
})

watch(transportStripUrl, () => {
  transportStripReady.value = false
  transportStripFailed.value = false
})

const transportPercent = computed(() => {
  if (videoDuration.value <= 0) return 0
  return Math.min(100, Math.max(0, (videoCurrentTime.value / videoDuration.value) * 100))
})

const transportLabel = computed(() => {
  if (transportDisplayMode.value === 'frames' && videoFps.value > 0) {
    const total = Math.max(1, Math.round(videoDuration.value * videoFps.value))
    const idx = Math.min(total, Math.round(videoCurrentTime.value * videoFps.value) + 1)
    return `f ${idx}/${total}`
  }
  return `${formatTransportTime(videoCurrentTime.value)} / ${formatTransportTime(videoDuration.value)}`
})

function formatTransportTime(seconds) {
  const s = Math.max(0, seconds || 0)
  const m = Math.floor(s / 60)
  const rem = s - m * 60
  return `${m}:${rem.toFixed(1).padStart(4, '0')}`
}

function toggleTransportDisplayMode() {
  transportDisplayMode.value = transportDisplayMode.value === 'frames' ? 'time' : 'frames'
  try {
    localStorage.setItem(makeProfileKey('frame-mode', TRANSPORT_FRAME_MODE_KEY), transportDisplayMode.value)
  } catch { /* ignore */ }
}

function toggleVideoTransport() {
  showVideoTransport.value = !showVideoTransport.value
  trackControl(showVideoTransport.value ? 'video_transport_show' : 'video_transport_hide')
}

function toggleVideoPlayback() {
  const v = videoElement.value
  if (!v) return
  if (v.paused) {
    v.play().catch(() => { /* interrupted by teardown */ })
    trackControl('video_play')
  } else {
    v.pause()
    trackControl('video_pause')
  }
}

// Step one frame back/forward (, / .). Pauses playback, like every video editor.
function stepVideoFrame(dir) {
  const v = videoElement.value
  if (!v || videoDuration.value <= 0) return
  if (!v.paused) v.pause()
  const step = videoFps.value > 0 ? 1 / videoFps.value : 0.04
  // Land one frame short of the end — seeking exactly to duration can show black.
  const maxT = Math.max(0, videoDuration.value - step)
  const currentTime = msePlayback?.logicalCurrentTime ?? v.currentTime
  const target = Math.min(maxT, Math.max(0, currentTime + dir * step))
  if (msePlayback) msePlayback.seekLogical(target)
  else v.currentTime = target
  videoCurrentTime.value = target
}

function transportSeekFromPointer(e) {
  const el = e.currentTarget
  const r = el.getBoundingClientRect()
  const frac = r.width > 0 ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : 0
  const v = videoElement.value
  if (!v || videoDuration.value <= 0) return
  const target = frac * videoDuration.value
  if (msePlayback) msePlayback.seekLogical(target)
  else v.currentTime = target
  videoCurrentTime.value = target
}

function onTransportPointerDown(e) {
  e.preventDefault()
  e.stopPropagation()
  document.body.style.userSelect = 'none'
  e.currentTarget.setPointerCapture?.(e.pointerId)
  transportScrubbing.value = true
  transportSeekFromPointer(e)
}

function onTransportPointerMove(e) {
  if (!transportScrubbing.value) return
  e.preventDefault()
  transportSeekFromPointer(e)
}

function onTransportPointerUp(e) {
  if (!transportScrubbing.value) return
  transportScrubbing.value = false
  document.body.style.userSelect = ''
  transportSeekFromPointer(e)
  trackControl('video_scrub')
}

function onTransportPointerCancel() {
  transportScrubbing.value = false
  document.body.style.userSelect = ''
}

// Keep playhead/timecode live off the element itself (a rAF poll survives the
// keyed <video> remounts without re-wiring event listeners each swap).
let transportRaf = null
function transportTick() {
  const v = videoElement.value
  if (v) {
    if (!transportScrubbing.value) videoCurrentTime.value = msePlayback?.logicalCurrentTime ?? v.currentTime ?? 0
    if (msePlayback?.duration > 0) videoDuration.value = msePlayback.duration
    else if (Number.isFinite(v.duration) && v.duration > 0) videoDuration.value = v.duration
    videoPaused.value = v.paused
  }
  transportRaf = requestAnimationFrame(transportTick)
}

watch(videoElement, (v) => {
  if (v && transportRaf == null) {
    transportRaf = requestAnimationFrame(transportTick)
  } else if (!v && transportRaf != null) {
    cancelAnimationFrame(transportRaf)
    transportRaf = null
  }
}, { immediate: true })

// fps comes from a one-shot server probe (media rows only carry duration);
// frames mode falls back to time until it arrives.
watch(() => (isVideo.value ? displayItem.value?.file_path : null), async (fp) => {
  videoFps.value = 0
  videoCurrentTime.value = 0
  videoDuration.value = displayItem.value?.duration || 0
  if (!fp) return
  try {
    const { data } = await axios.get('/api/generate/video-info', { params: { source_path: fp } })
    if (displayItem.value?.file_path !== fp) return // navigated away mid-probe
    if (data.fps > 0) videoFps.value = data.fps
    if (data.duration > 0 && !(videoDuration.value > 0)) videoDuration.value = data.duration
  } catch { /* readout degrades to element-reported time */ }
}, { immediate: true })

function toggleFocusMode() {
  if (preventClick.value) return
  focusMode.value = !focusMode.value
  trackControl('focus_mode')
}

// Cursor hiding for focus mode
function showCursor() {
  document.body.classList.remove('slideshow-cursor-hidden')
}

function hideCursor() {
  document.body.classList.add('slideshow-cursor-hidden')
}

// Track the latest cursor position so the hide timeout can check what's
// actually under the pointer (the slideshow vs. a modal/popup on top).
let lastMouseX = 0
let lastMouseY = 0

// Only hide the cursor when the topmost element under the pointer belongs to
// the slideshow overlay. Modals/popups (settings, crash dialog, etc.) are
// teleported to <body> as siblings of the overlay, so when one is open the
// element under the cursor is the modal — and we keep the cursor visible.
function cursorOverSlideshow() {
  if (!overlay.value) return true
  const el = document.elementFromPoint(lastMouseX, lastMouseY)
  return !el || overlay.value.contains(el)
}

function resetCursorTimeout() {
  // Clear existing timeout
  if (cursorTimeout) {
    clearTimeout(cursorTimeout)
  }

  // Show cursor
  showCursor()

  // Set new timeout to hide cursor
  if (focusMode.value) {
    cursorTimeout = setTimeout(() => {
      // Don't hide if the pointer is over a modal/popup floating on top.
      if (cursorOverSlideshow()) {
        hideCursor()
      }
    }, CURSOR_HIDE_DELAY)
  }
}

function handleMouseMove(event) {
  if (event) {
    lastMouseX = event.clientX
    lastMouseY = event.clientY
  }
  if (focusMode.value) {
    resetCursorTimeout()
  }
}

function cleanupCursorTimeout() {
  if (cursorTimeout) {
    clearTimeout(cursorTimeout)
    cursorTimeout = null
  }
  showCursor()
}

function toggleOrientation() {
  if (preventClick.value) return
  controlBarOrientation.value = controlBarOrientation.value === 'horizontal' ? 'vertical' : 'horizontal'
  const settings = loadSettings()
  settings.controlBarOrientation = controlBarOrientation.value
  saveSettings(settings)
}

// Control bar dragging
function startDrag(event) {
  isDragging.value = true
  dragDistance.value = 0
  preventClick.value = false
  const rect = controlBar.value.getBoundingClientRect()

  // If no edge anchors are set yet, initialize them based on current visual position
  // This prevents the "hop" when transitioning from centered to edge-anchored positioning
  if (controlBarEdgeAnchors.value.horizontal === null || controlBarEdgeAnchors.value.vertical === null) {
    const sidebarWidth = (showSidebar.value && !focusMode.value) ? SIDEBAR_WIDTH : 0
    const containerRect = overlay.value.getBoundingClientRect()
    const containerWidth = containerRect.width
    const containerHeight = containerRect.height
    const controlBarWidth = controlBar.value.offsetWidth
    const controlBarHeight = controlBar.value.offsetHeight

    // Calculate current position relative to container
    const currentX = rect.left - containerRect.left
    const currentY = rect.top - containerRect.top

    // Calculate distances from edges (clamped non-negative in case the bar's
    // actual position is already behind the sidebar/strip from a stale state)
    const distanceFromLeft = Math.max(0, currentX)
    const distanceFromRight = Math.max(0, (containerWidth - sidebarWidth) - (currentX + controlBarWidth))
    const distanceFromTop = Math.max(0, currentY)
    // Account for image strip when calculating bottom distance (consistent with controlBarStyle)
    const relatedStripOffset = (showImageStrip.value && !focusMode.value) ? STRIP_HEIGHT : 0
    const distanceFromBottom = Math.max(0, containerHeight - relatedStripOffset - (currentY + controlBarHeight))

    // Set initial anchors
    controlBarEdgeAnchors.value = {
      horizontal: distanceFromLeft < distanceFromRight ? 'left' : 'right',
      vertical: distanceFromTop < distanceFromBottom ? 'top' : 'bottom',
      horizontalDistance: distanceFromLeft < distanceFromRight ? distanceFromLeft : distanceFromRight,
      verticalDistance: distanceFromTop < distanceFromBottom ? distanceFromTop : distanceFromBottom
    }
  }

  dragStart.value = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
    initialX: event.clientX,
    initialY: event.clientY
  }
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
  event.preventDefault()
}

function onDrag(event) {
  if (isDragging.value) {
    // Calculate drag distance
    const dx = event.clientX - dragStart.value.initialX
    const dy = event.clientY - dragStart.value.initialY
    dragDistance.value = Math.sqrt(dx * dx + dy * dy)

    // If dragged more than 5 pixels, prevent subsequent clicks and update position
    if (dragDistance.value > 5) {
      preventClick.value = true

      const containerRect = overlay.value.getBoundingClientRect()
      const x = event.clientX - containerRect.left - dragStart.value.x
      const y = event.clientY - containerRect.top - dragStart.value.y

      // In focus mode, treat sidebar/strip as if they're not there
      const sidebarWidth = (showSidebar.value && !focusMode.value) ? SIDEBAR_WIDTH : 0
      const relatedStripOffset = (showImageStrip.value && !focusMode.value) ? STRIP_HEIGHT : 0
      const containerWidth = containerRect.width
      const containerHeight = containerRect.height
      const controlBarWidth = controlBar.value.offsetWidth
      const controlBarHeight = controlBar.value.offsetHeight

      // Keep within container bounds, excluding the sidebar/strip so the bar
      // can never be dragged underneath them (which produced negative saved
      // distances that persisted after the sidebar closed — the bar would
      // then render off-screen).
      const maxX = containerWidth - sidebarWidth - controlBarWidth
      const maxY = containerHeight - relatedStripOffset - controlBarHeight

      const clampedX = Math.max(0, Math.min(x, maxX))
      const clampedY = Math.max(0, Math.min(y, maxY))

      // Determine horizontal edge (relative to viewing area, not full viewport)
      // Sidebar is on the right, so left distance is just clampedX
      const distanceFromLeft = clampedX
      // Right distance accounts for sidebar on right
      const distanceFromRight = (containerWidth - sidebarWidth) - (clampedX + controlBarWidth)

      // Determine vertical edge
      const distanceFromTop = clampedY
      // Account for image strip when calculating bottom distance (consistent with controlBarStyle)
      const distanceFromBottom = containerHeight - relatedStripOffset - (clampedY + controlBarHeight)

      // Update anchors based on nearest edges
      controlBarEdgeAnchors.value = {
        horizontal: distanceFromLeft < distanceFromRight ? 'left' : 'right',
        vertical: distanceFromTop < distanceFromBottom ? 'top' : 'bottom',
        horizontalDistance: distanceFromLeft < distanceFromRight ? distanceFromLeft : distanceFromRight,
        verticalDistance: distanceFromTop < distanceFromBottom ? distanceFromTop : distanceFromBottom
      }
    }
  }
}

function stopDrag() {
  if (isDragging.value) {
    isDragging.value = false
    document.removeEventListener('mousemove', onDrag)
    document.removeEventListener('mouseup', stopDrag)

    // Save edge anchors to localStorage
    const settings = loadSettings()
    settings.controlBarHorizontalEdge = controlBarEdgeAnchors.value.horizontal
    settings.controlBarVerticalEdge = controlBarEdgeAnchors.value.vertical
    settings.controlBarHorizontalDistance = controlBarEdgeAnchors.value.horizontalDistance
    settings.controlBarVerticalDistance = controlBarEdgeAnchors.value.verticalDistance
    // Clear old x/y settings
    delete settings.controlBarX
    delete settings.controlBarY
    saveSettings(settings)

    // Reset preventClick after a brief delay (after click events fire)
    setTimeout(() => {
      preventClick.value = false
    }, 100)
  }
}

// Keyboard handling
function handleKeydown(event) {
  // Don't handle keyboard shortcuts if user is typing in an input/textarea
  const activeElement = document.activeElement
  if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
    return
  }

  // Grid view mode: 4-directional navigation within grid
  if (isViewingGrid.value && currentGridView.value) {
    const grid = currentGridView.value
    switch (event.key) {
      case 'ArrowRight':
      case 'd':
        event.preventDefault()
        if (gridViewCol.value < grid.cols - 1) {
          // Check if next cell has content
          const nextCell = getGridCellContent(gridViewRow.value, gridViewCol.value + 1)
          if (nextCell?.resolved) {
            gridViewCol.value++
            resetZoom()
          }
        }
        return
      case 'ArrowLeft':
      case 'a':
        event.preventDefault()
        if (gridViewCol.value > 0) {
          // Check if prev cell has content
          const prevCell = getGridCellContent(gridViewRow.value, gridViewCol.value - 1)
          if (prevCell?.resolved) {
            gridViewCol.value--
            resetZoom()
          }
        }
        return
      case 'ArrowUp':
      case 'w':
        event.preventDefault()
        if (gridViewRow.value > 0) {
          // Check if cell above has content
          const upCell = getGridCellContent(gridViewRow.value - 1, gridViewCol.value)
          if (upCell?.resolved) {
            gridViewRow.value--
            resetZoom()
          }
        }
        return
      case 'ArrowDown':
      case 's':
        event.preventDefault()
        if (gridViewRow.value < grid.rows - 1) {
          // Check if cell below has content
          const downCell = getGridCellContent(gridViewRow.value + 1, gridViewCol.value)
          if (downCell?.resolved) {
            gridViewRow.value++
            resetZoom()
          }
        }
        return
      case 'Escape':
        event.preventDefault()
        event.stopImmediatePropagation()
        exitGridView()
        return
    }
    // Fall through to other key handlers (zoom, focus mode, etc.)
  }

  switch (event.key) {
    case ' ':
      event.preventDefault()
      toggleSlideshow()
      break
    case 'ArrowRight':
    case 'd':
      event.preventDefault()
      userNext()
      break
    case 'ArrowLeft':
    case 'a':
      event.preventDefault()
      userPrevious()
      break
    case 'ArrowUp':
    case 'w':
      event.preventDefault()
      // When the parent has wired up an approval context for the
      // current item, ↑/W approves and advances; otherwise it adjusts
      // the slideshow auto-advance interval (the existing behavior).
      if (props.approvalContext?.state === 'awaiting') {
        emit('approve')
        next()
      } else if (props.approvalContext?.state === 'approved') {
        next()
      } else {
        increaseDuration()
      }
      break
    case 'ArrowDown':
    case 's':
      event.preventDefault()
      if (props.approvalContext?.state === 'awaiting') {
        emit('reject')
      } else if (props.approvalContext?.state === 'approved') {
        emit('unapprove')
      } else {
        decreaseDuration()
      }
      break
    case 'Home':
      event.preventDefault()
      goToFirst()
      break
    case 'End':
      event.preventDefault()
      goToLast()
      break
    case 'r':
      // Don't intercept Cmd+R or Ctrl+R (browser refresh)
      if (!event.metaKey && !event.ctrlKey) {
        event.preventDefault()
        toggleRandomize()
      }
      break
    case 'i':
      event.preventDefault()
      showSidebar.value = !showSidebar.value
      break
    case 'C':
      if (event.shiftKey) {
        event.preventDefault()
        toggleCaption()
      }
      break
    case 'l':
      event.preventDefault()
      toggleLoop()
      break
    case 'm':
      event.preventDefault()
      toggleMute()
      break
    case 'h':
      event.preventDefault()
      showImageStrip.value = !showImageStrip.value
      break
    case '0':
      event.preventDefault()
      resetZoom()
      break
    case '=':
    case '+':
      event.preventDefault()
      zoomScale.value = Math.min(MAX_ZOOM, zoomScale.value * 1.25)
      clampPan()
      break
    case '-':
      event.preventDefault()
      zoomScale.value = Math.max(MIN_ZOOM, zoomScale.value / 1.25)
      clampPan()
      break
    case 'f':
      event.preventDefault()
      toggleFocusMode()
      break
    case 'v':
      // Toggle the video transport bar (only meaningful on videos, but the
      // preference itself is global so it sticks across items).
      if (!event.metaKey && !event.ctrlKey) {
        event.preventDefault()
        toggleVideoTransport()
      }
      break
    case ',':
    case '.':
      // Frame step (video-editor convention). Pauses the video.
      if (isVideo.value) {
        event.preventDefault()
        stepVideoFrame(event.key === ',' ? -1 : 1)
      }
      break
    case 't':
      event.preventDefault()
      handleViewLineage()
      break
    case 'o':
      event.preventDefault()
      openInSystemViewer()
      break
    case 'S':
      // Shift+S reveals the current file in Finder (lowercase 's' is taken
      // by duration/down-navigation).
      if (event.shiftKey) {
        event.preventDefault()
        revealInFinder()
      }
      break
    case 'Delete':
      event.preventDefault()
      handleDeleteCurrentItem()
      break
    case 'Escape':
      // Exit set view mode first, then close slideshow
      if (isViewingSet.value) {
        event.preventDefault()
        event.stopImmediatePropagation() // Prevent parent handlers from closing slideshow
        exitSetView()
        return
      }
      // Close slideshow directly - don't rely on parent having ESC handler
      event.preventDefault()
      close()
      break
  }
}

function close() {
  stopSlideshowTimer()
  emit('close')
}

// Handle close button click - exit nested views first, then close slideshow
function handleCloseClick() {
  if (isViewingGrid.value) {
    exitGridView()
    return
  }
  if (isViewingSet.value) {
    exitSetView()
    return
  }
  close()
}

async function openInSystemViewer() {
  if (!currentItem.value?.file_path) return

  if (isTauri.value) {
    try {
      const { openPath } = await import('@tauri-apps/plugin-opener')
      console.log('[Slideshow] Opening in system viewer:', currentItem.value.file_path)
      await openPath(currentItem.value.file_path)
    } catch (e) {
      console.error('Failed to open in system viewer:', e)
    }
  }
}

// Reveal the current file in Finder (selects it in its enclosing folder).
// Bound to the control-strip document icon (click) and Shift+S.
async function revealInFinder() {
  if (!currentItem.value?.file_path) return

  if (isTauri.value) {
    try {
      const { revealItemInDir } = await import('@tauri-apps/plugin-opener')
      await revealItemInDir(currentItem.value.file_path)
    } catch (e) {
      console.error('Failed to reveal in Finder:', e)
    }
  }
}

// Zoom and pan functions
const MIN_ZOOM = 1
const MAX_ZOOM = 10

function resetZoom() {
  zoomScale.value = 1
  panX.value = 0
  panY.value = 0
}

function clampPan() {
  // Clamp pan values to prevent image from going too far off-screen
  if (zoomScale.value <= 1) {
    panX.value = 0
    panY.value = 0
    return
  }

  const container = mediaContainerRef.value
  if (!container) return

  const rect = container.getBoundingClientRect()
  const maxPanX = (rect.width * (zoomScale.value - 1)) / 2
  const maxPanY = (rect.height * (zoomScale.value - 1)) / 2

  panX.value = Math.max(-maxPanX, Math.min(maxPanX, panX.value))
  panY.value = Math.max(-maxPanY, Math.min(maxPanY, panY.value))
}

function handleWheel(event) {
  // Only zoom if over the media container
  if (!mediaContainerRef.value?.contains(event.target)) return

  // Only zoom for images and videos, let other types (text, sets, grids) scroll naturally
  if (isAudio.value || isText.value || isSet.value || isGrid.value || isLayout.value) return

  event.preventDefault()

  const delta = event.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoomScale.value + delta * zoomScale.value))

  // Zoom toward cursor position
  if (newScale !== zoomScale.value) {
    const container = mediaContainerRef.value
    const rect = container.getBoundingClientRect()
    const cursorX = event.clientX - rect.left - rect.width / 2
    const cursorY = event.clientY - rect.top - rect.height / 2

    const scaleFactor = newScale / zoomScale.value
    panX.value = cursorX - (cursorX - panX.value) * scaleFactor
    panY.value = cursorY - (cursorY - panY.value) * scaleFactor

    zoomScale.value = newScale
    clampPan()
  }
}

// Mouse pan handlers
function startPan(event) {
  if (zoomScale.value <= 1 && event.button !== 1) return
  if (event.button !== 0 && event.button !== 1) return // Left or middle mouse button

  isPanning.value = true
  panStart.value = { x: event.clientX, y: event.clientY }
  lastPan.value = { x: panX.value, y: panY.value }
  event.target.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function doPan(event) {
  if (!isPanning.value) return

  const dx = event.clientX - panStart.value.x
  const dy = event.clientY - panStart.value.y

  panX.value = lastPan.value.x + dx
  panY.value = lastPan.value.y + dy
  clampPan()
}

function endPan(event) {
  if (isPanning.value && event.target.hasPointerCapture?.(event.pointerId)) {
    event.target.releasePointerCapture(event.pointerId)
  }
  isPanning.value = false
}

// Touch pinch-to-zoom handlers
function getTouchDistance(touches) {
  const dx = touches[0].clientX - touches[1].clientX
  const dy = touches[0].clientY - touches[1].clientY
  return Math.sqrt(dx * dx + dy * dy)
}

function getTouchCenter(touches) {
  return {
    x: (touches[0].clientX + touches[1].clientX) / 2,
    y: (touches[0].clientY + touches[1].clientY) / 2
  }
}

function handleTouchStart(event) {
  if (event.touches.length === 2) {
    // Pinch start
    event.preventDefault()
    touchStartDistance.value = getTouchDistance(event.touches)
    touchStartScale.value = zoomScale.value
    touchStartCenter.value = getTouchCenter(event.touches)
    lastTouchCenter.value = touchStartCenter.value
    isTouchPanning.value = false
  } else if (event.touches.length === 1 && zoomScale.value > 1) {
    // Single finger pan when zoomed
    event.preventDefault()
    isTouchPanning.value = true
    lastTouchCenter.value = { x: event.touches[0].clientX, y: event.touches[0].clientY }
    lastPan.value = { x: panX.value, y: panY.value }
  }
}

function handleTouchMove(event) {
  if (event.touches.length === 2) {
    // Pinch zoom
    event.preventDefault()

    const currentDistance = getTouchDistance(event.touches)
    const currentCenter = getTouchCenter(event.touches)

    // Calculate new scale
    const scale = currentDistance / touchStartDistance.value
    const newScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, touchStartScale.value * scale))

    if (newScale !== zoomScale.value) {
      const container = mediaContainerRef.value
      if (container) {
        const rect = container.getBoundingClientRect()
        const centerX = touchStartCenter.value.x - rect.left - rect.width / 2
        const centerY = touchStartCenter.value.y - rect.top - rect.height / 2

        const scaleFactor = newScale / zoomScale.value
        panX.value = centerX - (centerX - panX.value) * scaleFactor
        panY.value = centerY - (centerY - panY.value) * scaleFactor
      }

      zoomScale.value = newScale
    }

    // Pan during pinch
    const dx = currentCenter.x - lastTouchCenter.value.x
    const dy = currentCenter.y - lastTouchCenter.value.y
    panX.value += dx
    panY.value += dy
    lastTouchCenter.value = currentCenter

    clampPan()
  } else if (event.touches.length === 1 && isTouchPanning.value) {
    // Single finger pan
    event.preventDefault()

    const touch = event.touches[0]
    const dx = touch.clientX - lastTouchCenter.value.x
    const dy = touch.clientY - lastTouchCenter.value.y

    panX.value = lastPan.value.x + dx
    panY.value = lastPan.value.y + dy
    clampPan()
  }
}

function handleTouchEnd(event) {
  if (event.touches.length < 2) {
    touchStartDistance.value = 0

    if (event.touches.length === 1 && zoomScale.value > 1) {
      // Switch to single-finger pan mode
      isTouchPanning.value = true
      lastTouchCenter.value = { x: event.touches[0].clientX, y: event.touches[0].clientY }
      lastPan.value = { x: panX.value, y: panY.value }
    } else {
      isTouchPanning.value = false
    }
  }
}

// Double-tap to reset zoom
let lastTapTime = 0
function handleDoubleTap(event) {
  const now = Date.now()
  if (now - lastTapTime < 300) {
    // Double tap detected
    if (zoomScale.value > 1) {
      resetZoom()
    } else {
      // Zoom in to 2x centered on tap point
      const container = mediaContainerRef.value
      if (container) {
        const rect = container.getBoundingClientRect()
        const tapX = event.clientX - rect.left - rect.width / 2
        const tapY = event.clientY - rect.top - rect.height / 2

        zoomScale.value = 2
        panX.value = -tapX
        panY.value = -tapY
        clampPan()
      }
    }
    lastTapTime = 0
  } else {
    lastTapTime = now
  }
}

// Reconcile the slideshow total against the parent's authoritative count after a
// removal. Only the pageProvider/generate-forever path (ToolView) needs this: its
// parent count (totalCompletedCount) is capped at 50 and refilled from a backlog, so
// deleting an older image often does NOT lower it. Decrementing localTotalCount
// locally there made the count drift down permanently as `media_deleted` events
// arrived during generation — causing the visible count to tick down, spurious index
// clamps (the image "advancing" on its own), and eventually localTotalCount<=0 ->
// close() (the slideshow dismissing itself). Snapping to the parent count on the next
// tick (after the parent's reactive count settles) keeps it correct in every case.
async function reconcilePageProviderTotal() {
  await nextTick()
  localTotalCount.value = props.totalCount
  if (localTotalCount.value <= 0) {
    close()
    return
  }
  if (currentIndex.value >= localTotalCount.value) {
    currentIndex.value = localTotalCount.value - 1
  }
}

// Adjust the slideshow total after `removedCount` item(s) were removed.
// pageProvider path: the parent count is authoritative (capped/refilled), so reconcile
// to it rather than decrementing locally. mediaList path: keep the immediate optimistic
// decrement; the effectiveTotal watch reconciles it (that count is not capped).
function applyRemovalToCount(removedCount) {
  if (!props.mediaList) {
    void reconcilePageProviderTotal()
    return
  }
  localTotalCount.value -= removedCount
  if (localTotalCount.value <= 0) {
    close()
    return
  }
  if (currentIndex.value >= localTotalCount.value) {
    currentIndex.value = localTotalCount.value - 1
  }
}

function removeMediaIdsFromCache(removedIds) {
  let cacheChanged = false
  const newCache = new Map(itemsCache.value)
  for (const [index, item] of itemsCache.value.entries()) {
    if (item && removedIds.has(itemIdentity(item))) {
      newCache.delete(index)
      cacheChanged = true
    }
  }
  if (cacheChanged) {
    itemsCache.value = newCache
  }
}

function pruneLiveQueueForRemovedMediaIds(removedIds) {
  if (!props.autoAdvanceOnNew || removedIds.size === 0 || liveAdvanceQueue.value.length === 0) return

  const removedKeys = new Set()
  const collectRemovedKey = (item) => {
    if (!item || !removedIds.has(itemIdentity(item))) return
    const key = getLiveItemKey(item)
    if (key != null) removedKeys.add(key)
  }

  collectRemovedKey(displayItem.value)
  for (const item of itemsCache.value.values()) {
    collectRemovedKey(item)
  }

  if (removedKeys.size === 0) return

  const oldHead = liveAdvanceQueue.value[0]
  liveAdvanceQueue.value = liveAdvanceQueue.value.filter(key => !removedKeys.has(key))
  if (liveAdvanceQueue.value[0] !== oldHead) {
    liveAdvanceEpoch++
  }
}

async function replaceDisplayedItemAfterRemoval(removedIds) {
  if (!displayItem.value || !removedIds.has(itemIdentity(displayItem.value))) {
    scheduleAdvance()
    return
  }

  liveAdvanceEpoch++
  displayItem.value = null
  mediaLoaded.value = false
  currentMediaId.value = null
  visibleFaceOverlays.value.clear()

  await nextTick()
  if (localTotalCount.value <= 0) return

  const nextIndex = Math.max(0, Math.min(currentIndex.value, localTotalCount.value - 1))
  currentIndex.value = nextIndex
  await ensureItemLoaded(getActualIndex(nextIndex))

  const replacement = baseCurrentItem.value
  if (itemIdentity(replacement)) {
    dropLiveQueueKey(getLiveItemKey(replacement))
    const identity = itemIdentity(replacement)
    currentMediaId.value = identity
    emit('update:currentMediaId', identity)
    applyDisplayItem(replacement)
  }
  scheduleAdvance()
}

function handleRemovedMediaIdsLocally(removedIds) {
  pruneLiveQueueForRemovedMediaIds(removedIds)
  removeMediaIdsFromCache(removedIds)
  void replaceDisplayedItemAfterRemoval(removedIds)
}

async function handleDeleteCurrentItem() {
  if (!currentItem.value) return

  const deletedId = itemIdentity(currentItem.value)
  const removedIds = new Set([deletedId])

  try {
    // Mark as being deleted by us so websocket handler skips it
    deletingItemIds.value.add(deletedId)

    // Delete the item via API
    if (currentAssetId.value) await trashAsset(currentAssetId.value)
    else await deleteMedia(currentPayloadId.value)

    // Mark as locally removed so strip skips it
    localRemovedIds.value = new Set([...localRemovedIds.value, deletedId])

    // Also update shared mediaList so grid sees the removal
    if (props.mediaList) {
      props.mediaList.removeItem(deletedId)
    }

    // Reconcile the total (and close/clamp if needed). On the pageProvider path this
    // snaps to the authoritative parent count; otherwise stay at the same index and
    // the next item will appear here.
    applyRemovalToCount(1)
    handleRemovedMediaIdsLocally(removedIds)

  } catch (error) {
    console.error('Failed to delete media:', error)
    addToast('Failed to move item to trash', 'error')
  } finally {
    // Clean up after a delay to ensure websocket has processed
    setTimeout(() => {
      deletingItemIds.value.delete(deletedId)
    }, 2000)
  }
}

function downloadMedia() {
  if (!currentPayloadId.value) return
  showExportModal.value = true
}

async function downloadMediaOriginal() {
  if (!currentPayloadId.value) return
  try {
    await downloadMediaApi([currentPayloadId.value])
  } catch (error) {
    console.error('Failed to download media:', error)
  }
}

function handlePrint() {
  if (!currentItem.value) return
  const item = currentItem.value
  const imageUrl = isImageFormat(item.file_format)
    ? getMediaFileUrl(currentPayloadId.value)
    : getThumbnailUrl(item.file_hash || currentPayloadId.value, 512)
  printAssetDetail(currentPayloadItem.value, imageUrl)
}

function isImageFormat(format) {
  if (!format) return false
  const imageFormats = ['jpeg', 'jpg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg', 'avif', 'heic', 'heif']
  return imageFormats.includes(format.toLowerCase())
}

function handleEditImage(mediaId = null) {
  const targetMediaId = mediaId || currentPayloadId.value
  if (!targetMediaId) return
  router.push({ name: 'edit-image', params: { editorId: nextEditorId(), mediaId: targetMediaId } })
}

async function downloadVersion(mediaId) {
  if (!mediaId) return
  try {
    await downloadMediaApi([mediaId])
  } catch (error) {
    console.error('Failed to download asset version:', error)
  }
}

async function downloadVersions(mediaIds) {
  if (!mediaIds?.length) return
  try {
    await downloadMediaApi(mediaIds)
  } catch (error) {
    console.error('Failed to download asset versions:', error)
  }
}

function handleViewLineage() {
  if (!currentPayloadId.value) return
  router.push({ name: 'lineage', params: { mediaId: currentPayloadId.value } })
}

async function handleRestoreCurrentItem() {
  if (!currentItem.value) return

  const restoredId = itemIdentity(currentItem.value)

  try {
    // Mark as being handled by us so websocket handler skips it
    deletingItemIds.value.add(restoredId)

    // Restore the item via API
    if (currentAssetId.value) await restoreAsset(currentAssetId.value)
    else await restoreFromTrash(currentPayloadId.value)

    // Mark as locally removed so strip skips it (it's leaving trash view)
    localRemovedIds.value = new Set([...localRemovedIds.value, restoredId])

    // Also update shared mediaList so grid sees the removal
    if (props.mediaList) {
      props.mediaList.removeItem(restoredId)
    }

    // Reconcile the total (and close/clamp if needed)
    applyRemovalToCount(1)
    handleRemovedMediaIdsLocally(new Set([restoredId]))

  } catch (error) {
    console.error('Failed to restore media:', error)
    addToast('Failed to restore item', 'error')
  } finally {
    setTimeout(() => {
      deletingItemIds.value.delete(restoredId)
    }, 2000)
  }
}

async function handlePermanentDeleteCurrentItem() {
  if (!currentItem.value) return

  const deletedId = itemIdentity(currentItem.value)

  try {
    if (currentAssetId.value) await permanentlyDeleteAsset(currentAssetId.value)
    else await permanentlyDeleteMedia(currentPayloadId.value)
    addToast('Deleted 1 item permanently', 'info')

  } catch (error) {
    console.error('Failed to permanently delete media:', error)
    addToast('Failed to permanently delete item', 'error')
  }
}

function filterByKeyword(keyword) {
  // Set global filter state
  setKeywordFilter(keyword)

  // If already on Browse, close slideshow; otherwise navigate (which will unmount it)
  if (router.currentRoute.value.name === 'browse') {
    close()
  } else {
    router.push({ name: 'browse' })
  }
}

function findSimilar() {
  if (!currentItem.value) return

  // Set global filter state with current item for display
  setSimilarFilter(currentPayloadId.value, currentPayloadItem.value)

  // If already on Browse, close slideshow; otherwise navigate (which will unmount it)
  if (router.currentRoute.value.name === 'browse') {
    close()
  } else {
    router.push({ name: 'browse' })
  }
}

// Navigate to a tool with generation parameters from a history step
function viewInTool(step) {
  if (!step.tool_id) return

  const toolId = step.tool_id
  const params = step.parameters || {}

  // Build a flat generation config matching the API format expected by parseGenerationConfig
  // This flattens step.parameters to top-level keys (cfg, steps, sampler, etc.)
  const config = {
    // Prompt
    prompt: step.prompt || '',
    negative_prompt: step.negative_prompt || params.negative_prompt || '',
    // Model info
    generator_name: step.generator,
    model_name: step.model,
    // Flatten all parameters to top level (matching API /config-from-media format)
    ...params,
    // Source inputs for image-to-image or other tasks with inputs
    source_inputs: step.source_inputs || [],
    // Media ID for reference
    input_media_id: step.media_id,
    // Signal that seed should be preserved since this is exact reproduction
    preserve_seed: true,
    source_tool_id: step.tool_id,
  }

  // Target the most-recent open instance of the tool (or a fresh one) in the
  // current project context, and write the handoff under the matching
  // instance-scoped key — ToolView.vue's loadPendingGeneration() reads
  // scopedToolId(tool) + 'pending_generation'.
  const slideshowRoute = router.currentRoute.value
  const projectId = slideshowRoute.params.id && String(slideshowRoute.name || '').startsWith('project-')
    ? Number(slideshowRoute.params.id)
    : null
  const { resolveToolInstance } = useWorkspaceTabs()
  const { instanceId } = resolveToolInstance(toolId, projectId)
  const storageKey = makeToolDbKey(toolInstanceScopedId(toolId, projectId, instanceId), 'pending_generation')
  // Store flat config directly (not nested under 'config' key) to match parseGenerationConfig expectations
  sessionStorage.setItem(storageKey, JSON.stringify(config))

  // Navigate to the tool (use timestamp to force route change detection for KeepAlive'd components)
  router.push(toolInstanceRoute(toolId, projectId, instanceId, { loadGeneration: Date.now().toString() }))
}

// Project picker state
const projectPickerSearch = ref(null)
const projectPickerQuery = ref('')
const projectPickerLoading = ref(false)
const projectPickerAllProjects = ref([])
const projectPickerMembership = ref(new Set())
const projectPickerBusy = ref(new Set())

const filteredPickerProjects = computed(() => {
  const q = projectPickerQuery.value.trim().toLowerCase()
  if (!q) return projectPickerAllProjects.value
  return projectPickerAllProjects.value.filter(p => (p.name || '').toLowerCase().includes(q))
})

async function addToProject() {
  if (!currentItem.value) return
  showProjectPicker.value = true
  projectPickerQuery.value = ''
  projectPickerLoading.value = true
  projectPickerMembership.value = new Set(mediaProjects.value.map(p => p.id))
  try {
    projectPickerAllProjects.value = await getProjects()
  } catch (err) {
    console.error('Failed to load projects:', err)
  } finally {
    projectPickerLoading.value = false
  }
  await nextTick()
  projectPickerSearch.value?.focus()
}

async function toggleProjectMembership(projectId, checked) {
  if (!currentItem.value) return
  projectPickerBusy.value.add(projectId)
  try {
    if (checked) {
      if (currentAssetId.value) await addAssetsToProject(projectId, [currentAssetId.value])
      else await addMediaToProject(projectId, [currentPayloadId.value])
      projectPickerMembership.value.add(projectId)
    } else {
      if (currentAssetId.value) await removeAssetFromProject(currentAssetId.value, projectId)
      else await removeMediaFromProject(projectId, currentPayloadId.value)
      projectPickerMembership.value.delete(projectId)
    }
    // Refresh the info panel list
    metadataCache.value.delete(itemIdentity(currentItem.value))
    mediaProjects.value = currentAssetId.value
      ? await getAssetProjects(currentAssetId.value)
      : (await axios.get(`/api/media/${currentPayloadId.value}/projects`)).data
  } catch (err) {
    console.error('Failed to toggle project membership:', err)
    // Revert checkbox
    if (checked) {
      projectPickerMembership.value.delete(projectId)
    } else {
      projectPickerMembership.value.add(projectId)
    }
  } finally {
    projectPickerBusy.value.delete(projectId)
  }
}

function closeProjectPicker() {
  showProjectPicker.value = false
}

function navigateToProject(projectId) {
  router.push({ name: 'project-overview', params: { id: projectId } })
  close()
}

async function removeFromProject(projectId) {
  if (!currentItem.value) return
  try {
    if (currentAssetId.value) await removeAssetFromProject(currentAssetId.value, projectId)
    else await removeMediaFromProject(projectId, currentPayloadId.value)
    metadataCache.value.delete(itemIdentity(currentItem.value))
    mediaProjects.value = currentAssetId.value
      ? await getAssetProjects(currentAssetId.value)
      : (await axios.get(`/api/media/${currentPayloadId.value}/projects`)).data
  } catch (err) {
    console.error('Failed to remove from project:', err)
  }
}

async function removeFromBoard(boardId) {
  if (!currentItem.value) return
  try {
    // Find the board section this media belongs to
    const boardData = await axios.get(`/api/boards/${boardId}`)
    const sections = boardData.data?.sections || []
    for (const section of sections) {
      const items = section.items || []
      if (items.some(item => assetIdOf(item) === itemIdentity(currentItem.value))) {
        if (currentAssetId.value) await removeAssetFromBoardSection(section.id, currentAssetId.value)
        else await axios.delete(`/api/boards/sections/${section.id}/items/${currentPayloadId.value}`)
        break
      }
    }
    metadataCache.value.delete(itemIdentity(currentItem.value))
    mediaBoards.value = currentAssetId.value
      ? await getAssetBoards(currentAssetId.value)
      : (await axios.get(`/api/media/${currentPayloadId.value}/boards`)).data
  } catch (err) {
    console.error('Failed to remove from board:', err)
  }
}

function addToBoard() {
  if (!currentItem.value) return
  showBoardPicker.value = true
}

async function handleBoardAdded() {
  showBoardPicker.value = false
  // Reload boards to show the newly added board
  if (currentItem.value) {
    // Invalidate cache for this item so fresh data is fetched
    metadataCache.value.delete(itemIdentity(currentItem.value))
    if (currentAssetId.value) mediaBoards.value = await getAssetBoards(currentAssetId.value)
    else await fetchMediaBoards(currentPayloadId.value)
  }
}

function navigateToBoard(boardId) {
  router.push({ name: 'board-detail', params: { id: boardId } })
  close()
}

function filterByTag(tagId) {
  setTagFilter(tagId)

  const route = router.currentRoute.value
  const isProjectRoute = route.matched.some(r => r.path.startsWith('/projects/:id'))
  const projectId = route.params.id

  if (isProjectRoute && projectId) {
    if (route.name === 'project-assets') {
      close()
    } else {
      router.push({ name: 'project-assets', params: { id: projectId } })
    }
  } else {
    if (route.name === 'browse') {
      close()
    } else {
      router.push({ name: 'browse' })
    }
  }
}

function manageTags() {
  // TODO: Open a proper "Manage Tags" dialog
  // For now this is a placeholder - the inline editor handles add/remove directly
  console.log('Manage tags clicked - dialog TBD')
}

// Handle tags saved from info panel
async function handleTagsSaved(mediaId) {
  // Fetch updated media item to get the latest tags
  const response = await axios.get(`/api/media/${mediaId}`)
  applyMediaPatchToLocalState(mediaId, { tags: response.data.tags })
}

// Handle tags updated from inline editor (no redundant fetch needed)
function handleTagsUpdated(mediaId, tags) {
  applyMediaPatchToLocalState(mediaId, { tags })
}

// Handle compare with source - emit to parent with both IDs
function handleCompareWithSource(sourceMediaId) {
  console.log('[SlideshowMode] handleCompareWithSource called with:', sourceMediaId, 'currentItem:', currentItem.value?.id)
  if (!currentItem.value) {
    console.log('[SlideshowMode] currentItem is null, returning early')
    return
  }
  console.log('[SlideshowMode] emitting compare-with-source with:', { leftMediaId: sourceMediaId, rightMediaId: currentPayloadId.value })
  emit('compare-with-source', {
    leftMediaId: sourceMediaId,
    rightMediaId: currentPayloadId.value
  })
}

async function navigateToSourceMedia(mediaId) {
  // Fetch the media item and push onto view stack
  try {
    const item = await getMediaItem(mediaId)
    if (item) {
      sourceViewStack.value.push({
        item,
        returnToIndex: currentIndex.value
      })
    }
  } catch (e) {
    console.error('Failed to load media item:', e)
  }
}

function goBackFromSource() {
  if (sourceViewStack.value.length > 0) {
    sourceViewStack.value.pop()
    // Re-arm the advance engine now that the sub-view is closed.
    scheduleAdvance()
  }
}

// Drag and drop handler for thumbnail strip
function handleStripDragStart(event, item) {
  if (!item) return

  // Create a smaller drag preview image
  const thumbnailUrl = getThumbnailUrl(item.file_hash, 128)
  const fileFormat = item.file_format || ''
  const itemIsVideo = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat.toLowerCase())
  const mediaId = itemPayloadId(item)
  if (!mediaId) return
  createDragPreview(event, thumbnailUrl, mediaId, fileFormat, itemIsVideo)
  if (hasAssetIdentity(item)) {
    event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({
      items: [{
        asset_id: itemIdentity(item),
        revision_id: item.revision_id ?? null,
        media_id: mediaId,
      }],
    }))
  }
}

// Drag and drop handler.
//
// A plain drag is an *in-app transfer* (HTML5): it carries the media id so it
// can be dropped onto the sidebar, chats, tools, pickers, etc. Holding ⌥
// (Option) instead drags the *real file* out to Finder/desktop via the native
// Tauri drag. Native OS drag and HTML5 drag are mutually exclusive on
// WKWebView, so the modifier picks the lane synchronously up front rather than
// trying (and failing) to do both on one gesture.
async function handleDragStart(event) {
  if (!currentItem.value) return

  if (isTauri.value && event.altKey && currentItem.value.file_path) {
    await tauriDragStart(event, currentPayloadId.value, currentItem.value.file_path)
    return
  }

  // Plain drag → in-app transfer. createDragPreview sets the
  // application/x-media-id payload (read by the chat/tool/picker drop zones)
  // and a compact drag image, all synchronously within the dragstart gesture.
  const thumbnailUrl = getThumbnailUrl(currentItem.value.file_hash, 128)
  const fileFormat = currentItem.value.file_format || ''
  const itemIsVideo = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat.toLowerCase())
  createDragPreview(event, thumbnailUrl, currentPayloadId.value, fileFormat, itemIsVideo)
  if (currentAssetId.value) {
    event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({
      items: [{
        asset_id: currentAssetId.value,
        revision_id: currentItem.value.revision_id ?? null,
        media_id: currentPayloadId.value,
      }],
    }))
  }
}

// Drag handle on the control strip: an explicit "drag the file out" affordance
// so users don't have to know the ⌥ modifier. Always exports (native Tauri
// drag) — that's the whole point of the handle.
async function handleExportDragStart(event) {
  if (!currentItem.value || !currentItem.value.file_path) return
  await tauriDragStart(event, currentPayloadId.value, currentItem.value.file_path)
}

// === Auto-advance engine (generate-forever) ================================
// See the design note at the FOLLOW_MIN_DWELL_MS declaration. In short: arrivals
// only PIN the current image; a dwell-gated stepper walks currentIndex back toward
// 0 (newest), one image per >=1.5s window (videos wait for their natural end).

// A new item lands somewhere in provider order, shifting items at/after that
// index +1. Keep the currently displayed item steady when the insert is before it.
// In follow mode, an insert before/on the current item becomes lag++ (the stepper
// will catch up); inserts behind the current item do not pull the viewer backward.
function pinForArrival(insertIndex = 0) {
  if (!Number.isFinite(insertIndex) || insertIndex < 0) return
  invalidatePageProviderLoads()
  const oldCache = itemsCache.value
  const newCache = new Map()
  for (const [oldIndex, item] of oldCache) {
    newCache.set(oldIndex >= insertIndex ? oldIndex + 1 : oldIndex, item)
  }
  itemsCache.value = newCache
  if (currentIndex.value >= insertIndex) {
    currentIndex.value++
  }
}

function getLiveItemKey(item) {
  if (!item) return null
  return item._slideshowItemKey ?? item.id ?? null
}

function clearLiveAdvanceQueue() {
  if (liveAdvanceQueue.value.length > 0) {
    liveAdvanceQueue.value = []
  }
  liveAdvanceEpoch++
}

function enqueueLiveAdvances(candidates) {
  const ordered = orderLiveAdvanceCandidates(candidates)
  if (ordered.length === 0) return
  liveAdvanceQueue.value = [
    ...liveAdvanceQueue.value,
    ...ordered.map(candidate => candidate.key)
  ]
}

function liveIndexForKey(key) {
  return Array.isArray(props.liveItemIds) ? props.liveItemIds.indexOf(key) : -1
}

function dropLiveQueueHead(key) {
  if (liveAdvanceQueue.value[0] !== key) return
  liveAdvanceQueue.value = liveAdvanceQueue.value.slice(1)
}

function dropLiveQueueKey(key) {
  if (key == null || liveAdvanceQueue.value.length === 0) return
  const nextQueue = liveAdvanceQueue.value.filter(candidateKey => candidateKey !== key)
  if (nextQueue.length === liveAdvanceQueue.value.length) return
  liveAdvanceQueue.value = nextQueue
  liveAdvanceEpoch++
}

function sortLiveAdvanceQueue() {
  const oldHead = liveAdvanceQueue.value[0]
  const ordered = orderLiveAdvanceKeys(liveAdvanceQueue.value, props.liveItemIds)
  liveAdvanceQueue.value = ordered
  if (ordered[0] !== oldHead) {
    liveAdvanceEpoch++
  }
}

function clearProviderCacheSlot(actualIndex) {
  const pageSize = 50
  loadingPages.value.delete(Math.floor(actualIndex / pageSize))
  itemsCache.value.delete(actualIndex)
}

async function refreshLiveItemForKey(key) {
  const targetDisplayIndex = liveIndexForKey(key)
  if (targetDisplayIndex < 0) return null

  const actualIndex = getActualIndex(targetDisplayIndex)
  clearProviderCacheSlot(actualIndex)
  await ensureItemLoaded(actualIndex)

  const item = itemsCache.value.get(actualIndex) || null
  if (getLiveItemKey(item) === key) {
    return { index: targetDisplayIndex, actualIndex, item }
  }
  return null
}

// Arrival entry point: diff successive provider-order id lists and pin each
// inserted item at the index it actually landed. Watching the list (rather than
// the completion WS event) keeps pins exactly 1:1 with provider inserts: the
// jobs manager prefetches media before exposing a completed job, so at WS time
// the job is not in the list yet and an index lookup would drop every arrival.
// This also naturally covers post-processing chains (the job enters the list
// only when its final image is ready) and out-of-order completions.
watch(() => props.liveItemIds, (newIds, oldIds) => {
  if (!props.autoAdvanceOnNew || !Array.isArray(newIds) || !Array.isArray(oldIds)) return
  const arrivals = diffInsertedLiveIds(newIds, oldIds)
  if (arrivals.length === 0) {
    sortLiveAdvanceQueue()
    scheduleAdvance()
    return
  }
  // Ascending index order: pinForArrival works in final-list coordinates once
  // every earlier (newer) insert has been applied, so applying top-down after a
  // multi-insert flush shifts the cache exactly once per inserted item.
  const queueCandidates = []
  let pinned = 0
  for (const arrival of arrivals) {
    const shouldQueue = shouldQueueLiveArrival({
      currentIndex: currentIndex.value,
      insertIndex: arrival.index,
      followStream: followStream.value,
      randomized: isRandomized.value
    })
    pinForArrival(arrival.index)
    if (shouldQueue) queueCandidates.push(arrival)
    pinned++
  }
  if (!pinned) return
  enqueueLiveAdvances(queueCandidates)
  sortLiveAdvanceQueue()
  console.log(`[SlideshowDebug] live_inserts count=${pinned} queued=${queueCandidates.length} followStream=${followStream.value} currentIndex=${currentIndex.value}`)
  // Every visible arrival pins when it lands before/on the current item (never swaps
  // the screen). The stepper catches up if we follow.
  scheduleAdvance()
})

// --- scheduling -------------------------------------------------------------

// Is the follow-catch-up stepper the active advance source right now? Disabled in
// sub-views and under shuffle (where "newest" is meaningless). Takes precedence
// over the manual Play timer while live arrivals are queued.
function followActiveNow() {
  return props.autoAdvanceOnNew && followStream.value && !isRandomized.value && liveAdvanceQueue.value.length > 0
}

// Is the manual Play timer the active advance source right now?
function playActiveNow() {
  return isPlaying.value && (currentIndex.value < localTotalCount.value - 1 || loopEnabled.value)
}

// Re-validate at fire time — conditions may have changed during a dwell wait, an
// async preload, or a video playthrough (user navigated, entered a sub-view, etc).
function shouldStillAdvance(action) {
  if (isViewingSet.value || isViewingGrid.value || isViewingSource.value) return false
  if (action === performFollowStep) return followActiveNow()
  if (action === performPlayNext) return playActiveNow()
  return false
}

// Central scheduler. Idempotent: always clears prior arming, then arms the correct
// trigger for the current item (a dwell timer for images, the video's natural end
// for videos). Called after every shown item, every arrival, and on play/follow
// state changes.
function scheduleAdvance() {
  if (dwellTimer) { clearTimeout(dwellTimer); dwellTimer = null }
  videoAdvanceArmed.value = false

  // No auto-advance while a sub-view is open — arrivals still pin underneath, but
  // the view must never change out from under the user.
  if (isViewingSet.value || isViewingGrid.value || isViewingSource.value) return

  let action = null
  let floorMs = 0
  if (followActiveNow()) {
    action = performFollowStep
    floorMs = FOLLOW_MIN_DWELL_MS
  } else if (playActiveNow()) {
    action = performPlayNext
    floorMs = currentDuration.value * 1000
  } else {
    return
  }

  const elapsed = performance.now() - currentShownAt
  const remaining = Math.max(0, floorMs - elapsed)

  if (isVideo.value) {
    // Video: advance at the next logical MSE loop boundary, but never before the
    // floor. Below the floor the continuous timeline keeps looping in place.
    if (remaining <= 0) {
      videoAdvanceArmed.value = true
      ensureVideoPlaying()
    } else {
      dwellTimer = setTimeout(() => {
        dwellTimer = null
        if (shouldStillAdvance(action)) { videoAdvanceArmed.value = true; ensureVideoPlaying() }
      }, remaining)
    }
  } else {
    // Image / audio / other: advance once the floor elapses.
    dwellTimer = setTimeout(() => {
      dwellTimer = null
      if (shouldStillAdvance(action)) action()
    }, remaining)
  }
}

// An armed video must be playing to reach the next logical MSE boundary.
function ensureVideoPlaying() {
  const el = videoElement.value
  if (!el) return
  try {
    if (el.ended) el.currentTime = 0
    if (el.paused) void el.play()
  } catch (e) { /* ignore */ }
}

// Fired by the MSE controller at a logical loop boundary while armed. Perform the
// queued advance if it is still valid; otherwise continue looping and re-arm.
function onVideoEnded() {
  videoAdvanceArmed.value = false
  if (shouldStillAdvance(performFollowStep)) {
    performFollowStep()
  } else if (shouldStillAdvance(performPlayNext)) {
    performPlayNext()
  } else {
    const el = videoElement.value
    if (el) {
      try {
        if (!msePlayback) el.currentTime = 0
        void el.play()
      } catch (e) { /* ignore */ }
    }
    scheduleAdvance()
  }
}

// --- advance actions --------------------------------------------------------

// Resolve an image URL into a load promise (best-effort, never rejects).
function preloadImage(url) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve()
    img.onerror = () => resolve()
    img.src = url
    setTimeout(resolve, 5000)
  })
}

// Push cached metadata for `item` into the info-panel refs (extracted from the old
// atomic transition).
function applyMetadataFromCache(item) {
  const metadata = metadataCache.value.get(itemIdentity(item))
  if (!metadata) return
  faces.value = metadata.faces
  mediaProjects.value = metadata.projects || []
  mediaBoards.value = metadata.boards
  generationJob.value = metadata.job
  chatInfo.value = metadata.chat
  descendants.value = metadata.descendants || []
  inspiredDescendants.value = metadata.inspiredDescendants || []
}

// Follow-catch-up step: drain one queued live arrival, preloading first to avoid
// flicker, then swapping atomically. The queue stores stable provider item keys
// (ToolView job ids), so arrivals during awaits can shift indexes without changing
// the target media. Aborts without swapping if the user navigated away mid-preload.
async function performFollowStep() {
  if (stepInFlight) return
  if (!shouldStillAdvance(performFollowStep)) return
  const targetKey = liveAdvanceQueue.value[0]
  if (targetKey == null) return

  stepInFlight = true
  isAtomicTransition.value = true
  const stepEpoch = liveAdvanceEpoch
  let swapped = false
  try {
    let resolved = await refreshLiveItemForKey(targetKey)
    let targetDisplayIndex = resolved?.index ?? -1
    let actualIndex = resolved?.actualIndex ?? -1
    let target = resolved?.item || null
    if (targetDisplayIndex < 0) {
      dropLiveQueueHead(targetKey)
      return
    }

    // Brief retry if the file isn't ingested yet (rare; it usually arrived >=1.5s ago).
    let retries = 0
    while ((!target || (!target.file_hash && !target._placeholder)) && retries < 3) {
      await new Promise(r => setTimeout(r, 300))
      resolved = await refreshLiveItemForKey(targetKey)
      targetDisplayIndex = resolved?.index ?? -1
      actualIndex = resolved?.actualIndex ?? -1
      target = resolved?.item || null
      if (targetDisplayIndex < 0) break
      retries++
    }

    if (!target || (!target.file_hash && !target._placeholder)) {
      console.warn(`[SlideshowDebug] follow_step_target_not_ready key=${targetKey} actualIndex=${actualIndex} id=${target?.id}`)
      return // re-armed in finally
    }

    // Preload image file (for images) + metadata. Videos stream via the element.
    const preloads = [fetchAndCacheMetadata(target).catch(() => null)]
    if (target.file_hash && !isVideoType(target)) {
      preloads.push(preloadImage(getMediaFileUrl(target.file_hash)))
    }
    await Promise.all(preloads)

    // Re-validate AFTER the awaits: never yank a user who navigated away (issue 1b).
    if (
      stepEpoch !== liveAdvanceEpoch ||
      liveAdvanceQueue.value[0] !== targetKey ||
      !shouldStillAdvance(performFollowStep)
    ) {
      console.log('[SlideshowDebug] follow_step_aborted no_longer_following')
      return
    }

    // ---- synchronous swap section (no awaits) ----
    targetDisplayIndex = liveIndexForKey(targetKey)
    if (targetDisplayIndex < 0) {
      dropLiveQueueHead(targetKey)
      return
    }
    const currentActualIndex = getActualIndex(targetDisplayIndex)
    const cachedAtCurrentSlot = itemsCache.value.get(currentActualIndex)
    const swapItem = getLiveItemKey(cachedAtCurrentSlot) === targetKey ? cachedAtCurrentSlot : target
    mediaLoaded.value = false
    currentIndex.value = targetDisplayIndex
    displayItem.value = swapItem
    // Keep the drift tracker in sync so the baseCurrentItem watcher doesn't fight us.
    const identity = itemIdentity(swapItem)
    currentMediaId.value = identity
    emit('update:currentMediaId', identity)
    dropLiveQueueHead(targetKey)
    applyMetadataFromCache(swapItem)
    visibleFaceOverlays.value.clear()
    if (swapItem.file_hash) preloadDragPreview(getThumbnailUrl(swapItem.file_hash, 128))
    swapped = true
    console.log(`[SlideshowDebug] follow_step_swap index=${targetDisplayIndex} id=${swapItem.id} queuedRemaining=${liveAdvanceQueue.value.length}`)
    if (stripScrollerRef.value?.refresh) void stripScrollerRef.value.refresh()
  } finally {
    isAtomicTransition.value = false
    stepInFlight = false
    // On a swap, the displayItem identity watch stamps currentShownAt and re-arms.
    // On an abort/give-up (no swap), re-arm here so we retry on the next tick.
    if (!swapped) scheduleAdvance()
  }
}

// Manual Play timer step: walk toward older items (wraps with loopEnabled).
function performPlayNext() {
  if (!playActiveNow()) return
  next()
  // Re-arm with a fresh dwell. For an item change the displayItem watch also re-arms
  // (idempotent); for a no-op (e.g. single-item loop) this avoids a busy loop.
  currentShownAt = performance.now()
  scheduleAdvance()
}

// Lifecycle
// Global keyboard shortcuts for slideshow
useGlobalKeyboardShortcuts({
  onKeydown: handleKeydown
})

// Capture-phase Escape handler to intercept before parent view's handler
// This is needed because parent view (BrowseGridView) has its own Escape handler
// that closes the slideshow, but we want to exit set view first
function handleEscapeCapture(event) {
  if (event.key === 'Escape') {
    // Grid view takes precedence - exit cell view back to grid overview
    if (isViewingGrid.value) {
      event.preventDefault()
      event.stopImmediatePropagation()
      exitGridView()
      return
    }
    // Then check set view
    if (isViewingSet.value) {
      event.preventDefault()
      event.stopImmediatePropagation()
      exitSetView()
    }
  }
}

// WebSocket handler: media_deleted (external deletion)
function handleMediaDeletedWs(data) {
  const { media_id } = data
  if (!media_id) return

  // If we initiated this delete, skip handling (already handled in handleDeleteCurrentItem)
  if (deletingItemIds.value.has(media_id)) return
  const removedIds = new Set([media_id])

  // External deletion - mark as removed and advance
  localRemovedIds.value = new Set([...localRemovedIds.value, media_id])

  // Update shared mediaList so grid sees the removal
  if (props.mediaList) {
    props.mediaList.removeItem(media_id)
  }

  applyRemovalToCount(1)
  handleRemovedMediaIdsLocally(removedIds)
}

// WebSocket handler: media_bulk_deleted
function handleMediaBulkDeletedWs(data) {
  const { media_ids } = data
  if (!media_ids?.length) return

  const externalIds = media_ids.filter(id => !deletingItemIds.value.has(id))
  if (externalIds.length === 0) return

  localRemovedIds.value = new Set([...localRemovedIds.value, ...externalIds])

  if (props.mediaList) {
    props.mediaList.removeItems(externalIds)
  }

  const idsToRemove = new Set(externalIds)

  applyRemovalToCount(externalIds.length)
  handleRemovedMediaIdsLocally(idsToRemove)
}

function handleAssetsRemovedWs(data) {
  if (data.profile_id && data.profile_id !== getCurrentProfileId()) return
  const ids = data.asset_ids || [data.asset_id || data.asset?.id].filter(Boolean)
  const externalIds = ids.filter((id) => !deletingItemIds.value.has(id))
  if (externalIds.length === 0) return
  localRemovedIds.value = new Set([...localRemovedIds.value, ...externalIds])
  if (props.mediaList) props.mediaList.removeItems(externalIds)
  applyRemovalToCount(externalIds.length)
  handleRemovedMediaIdsLocally(new Set(externalIds))
}

// WebSocket handler: auto_delete_removed
function handleAutoDeleteRemovedWs(data) {
  const { media_id } = data
  if (media_id) {
    applyMediaPatchToLocalState(media_id, { expires_at: null })
  }
}

// WebSocket handler: media_updated (update info panel in real-time)
function handleMediaUpdatedWs(data) {
  const { media_id, fields, media } = data
  if (!media_id || !media) return
  const updateFields = Array.isArray(fields) ? fields : []

  applyMediaPatchToLocalState(media_id, mediaUpdatePatch(updateFields, media))

  // Force re-render of marker UI if markers changed
  if (updateFields.includes('markers')) {
    markerUpdateTrigger.value++
  }
}

onMounted(async () => {
  // Reset any stale loading states from previous mount
  setViewLoading.value = false

  // Subscribe to WebSocket events FIRST - before any awaits that could fail
  // and prevent registration. Store unsubscribe functions for cleanup.
  // (Generate-forever arrivals are driven by the liveItemIds watcher, not a WS
  // event — the provider list is the source of truth for insert positions.)
  wsUnsubscribers.push(onWebSocketEvent('media_deleted', handleMediaDeletedWs))
  wsUnsubscribers.push(onWebSocketEvent('media_bulk_deleted', handleMediaBulkDeletedWs))
  wsUnsubscribers.push(onWebSocketEvent('asset_deleted', handleAssetsRemovedWs))
  wsUnsubscribers.push(onWebSocketEvent('assets_trashed', handleAssetsRemovedWs))
  wsUnsubscribers.push(onWebSocketEvent('asset_identity_deleted', handleAssetsRemovedWs))
  if (props.isTrashView) {
    wsUnsubscribers.push(onWebSocketEvent('asset_restored', handleAssetsRemovedWs))
    wsUnsubscribers.push(onWebSocketEvent('assets_restored', handleAssetsRemovedWs))
  }

  // Add capture-phase Escape handler
  window.addEventListener('keydown', handleEscapeCapture, true)
  // Ensure tools cache is populated for displaying tool names in history
  fetchProvidersAndTools()

  // Set initial body class if focus mode is enabled
  if (focusMode.value) {
    document.body.classList.add('slideshow-focus-mode')
  }

  // Set up mouse move listener for cursor hiding in focus mode. Listen on
  // window (not just the overlay) so moving the mouse over a modal/popup that
  // floats above the slideshow also reveals the cursor.
  window.addEventListener('mousemove', handleMouseMove)
  // Start cursor timeout if in focus mode
  if (overlay.value && focusMode.value) {
    resetCursorTimeout()
  }

  // Initialize shuffled indices if randomized from URL
  if (props.randomized && props.randomSeed) {
    isRandomized.value = true
    shuffledIndices.value = createShuffledIndices(localTotalCount.value, props.randomSeed)
  }

  // Skip pageProvider loading if items are provided directly (nested slideshow)
  if (!props.items) {
    // Load initial item and nearby items
    const actualIndex = getActualIndex(currentIndex.value)
    await ensureItemLoaded(actualIndex)

    // Verify the item was actually loaded - if not, try index 0 as fallback
    // Check the appropriate cache based on whether we're using shared mediaList
    const itemFromCache = props.mediaList
      ? props.mediaList.getItem(actualIndex)
      : itemsCache.value.get(actualIndex)

    console.log('[SlideshowMode] After ensureItemLoaded:', {
      actualIndex,
      startIndex: props.startIndex,
      currentIndex: currentIndex.value,
      hasMediaList: !!props.mediaList,
      itemFromCache: itemFromCache?.id,
      itemFromCacheHash: itemFromCache?.file_hash?.substring(0, 8),
      mediaListTotal: props.mediaList?.totalCount?.value
    })

    if (!itemFromCache) {
      console.warn(`Slideshow: Item at index ${actualIndex} not found after loading, trying index 0`)
      if (actualIndex !== 0) {
        await ensureItemLoaded(0)
        const hasItemAtZero = props.mediaList
          ? props.mediaList.getItem(0)
          : itemsCache.value.has(0)
        if (hasItemAtZero) {
          currentIndex.value = 0
        }
      }
    }

    preloadNearbyItems(currentIndex.value)
  }

  // Initialize the advance engine: stamp the initial dwell and arm the scheduler
  // (the displayItem identity watch will re-stamp/re-arm once the first item loads).
  currentShownAt = performance.now()
  scheduleAdvance()

  // Fetch available markers
  await fetchMarkers()

  // Listen for markers config changes
  window.addEventListener('markers-changed', fetchMarkers)

  // Close volume popup on click outside
  document.addEventListener('mousedown', closeVolumeSlider)

  // NOTE: WebSocket handlers were registered at the top of onMounted (before awaits)
  // Register remaining WS handlers that are less critical (OK if they miss initial events)
  wsUnsubscribers.push(onWebSocketEvent('auto_delete_removed', handleAutoDeleteRemovedWs))
  wsUnsubscribers.push(onWebSocketEvent('media_updated', handleMediaUpdatedWs))
})

onUnmounted(() => {
  destroyMsePlayback()
  // Clean up WebSocket handlers to prevent leaked handlers from accumulating
  for (const unsub of wsUnsubscribers) {
    unsub()
  }
  wsUnsubscribers.length = 0

  stopSlideshowTimer()
  // Clean up capture-phase Escape handler
  window.removeEventListener('keydown', handleEscapeCapture, true)
  // Clean up focus mode body class
  document.body.classList.remove('slideshow-focus-mode')
  // Clean up cursor hiding
  window.removeEventListener('mousemove', handleMouseMove)
  cleanupCursorTimeout()
  // Clean up ResizeObserver
  if (containerResizeObserver) {
    containerResizeObserver.disconnect()
    containerResizeObserver = null
  }
  // Clean up markers-changed listener
  window.removeEventListener('markers-changed', fetchMarkers)
  // Clean up volume popup click-outside listener
  document.removeEventListener('mousedown', closeVolumeSlider)
  // Stop the transport playhead poll (and undo a mid-scrub userSelect lock)
  if (transportRaf != null) {
    cancelAnimationFrame(transportRaf)
    transportRaf = null
  }
  if (transportScrubbing.value) document.body.style.userSelect = ''
})

// Also clean up focus mode when deactivated by KeepAlive (e.g., navigating away)
// This is needed because the parent view uses KeepAlive, so onUnmounted won't fire
onDeactivated(() => {
  document.body.classList.remove('slideshow-focus-mode')
  cleanupCursorTimeout()
  // Pause the transport playhead poll while hidden by KeepAlive
  if (transportRaf != null) {
    cancelAnimationFrame(transportRaf)
    transportRaf = null
  }
})

// The playback registry pauses the video on deactivate; resume the ambient
// autoplay when the user navigates back to a view with the slideshow open.
onActivated(() => {
  if (isVideo.value && videoElement.value) void videoElement.value.play()
  if (videoElement.value && transportRaf == null) {
    transportRaf = requestAnimationFrame(transportTick)
  }
})

// Set up ResizeObserver when container ref becomes available
watch(mediaContainerRef, (newRef, oldRef) => {
  // Clean up old observer
  if (containerResizeObserver) {
    containerResizeObserver.disconnect()
    containerResizeObserver = null
  }
  // Set up new observer
  if (newRef) {
    containerResizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        containerSize.value = {
          width: entry.contentRect.width,
          height: entry.contentRect.height
        }
      }
    })
    containerResizeObserver.observe(newRef)
  }
}, { immediate: true })

// Watch for item changes
watch(currentIndex, async (newIndex) => {
  // Load current and nearby items (preloadNearbyItems handles actual index mapping)
  const actualIndex = getActualIndex(newIndex)
  await ensureItemLoaded(actualIndex)

  // If item still not in cache after loading, the index might be invalid
  // This can happen if totalCount is stale or items were deleted
  if (!itemsCache.value.has(actualIndex) && !props.items) {
    console.warn(`Slideshow: Navigation to index ${actualIndex} failed - item not in page results`)
    // Clamp to valid range if possible
    if (localTotalCount.value > 0 && newIndex >= localTotalCount.value) {
      currentIndex.value = localTotalCount.value - 1
    }
  }

  preloadNearbyItems(newIndex)
})

// Face data is now loaded in the consolidated metadata watcher below

// Parse landmarks JSON string into array of {x, y} points
function parseLandmarks(landmarksStr) {
  if (!landmarksStr) return []
  try {
    const parsed = JSON.parse(landmarksStr)
    // Backend stores landmarks as array of {x, y} objects (normalized 0-1)
    if (Array.isArray(parsed)) {
      // If it's already an array of {x, y} objects
      if (parsed[0] && typeof parsed[0] === 'object' && 'x' in parsed[0] && 'y' in parsed[0]) {
        return parsed
      }
      // If it's an array of arrays [[x1, y1], [x2, y2], ...]
      if (Array.isArray(parsed[0])) {
        return parsed.map(p => ({ x: p[0], y: p[1] }))
      }
      // If it's a flat array [x1, y1, x2, y2, ...]
      if (typeof parsed[0] === 'number') {
        const points = []
        for (let i = 0; i < parsed.length; i += 2) {
          points.push({ x: parsed[i], y: parsed[i + 1] })
        }
        return points
      }
    }
    return []
  } catch (e) {
    console.error('Failed to parse landmarks:', e)
    return []
  }
}

// Handle media load event - show checkerboard for transparency only after loaded.
// For <img>, the native `load` event fires once bytes are downloaded but before
// the browser finishes decoding the bitmap (async decoding by default), leaving
// a brief window where nothing is painted and the checker background shows
// through underneath. Wait for decode() so the flip to checker lines up with
// pixels actually landing on screen. Rapid nav guard: bail if the user has
// already moved on to a different item by the time decode() settles.
function handleMediaLoad(event) {
  const img = event?.target
  const itemId = itemIdentity(displayItem.value)
  const finish = () => {
    if (itemIdentity(displayItem.value) !== itemId) return
    mediaLoaded.value = true
    // Apply saved volume to newly loaded video
    if (videoElement.value) {
      videoElement.value.volume = volume.value
    }
  }
  if (img?.tagName === 'IMG' && typeof img.decode === 'function') {
    img.decode().then(finish, finish)
  } else {
    finish()
  }
}

// Handle context menu on main image or thumbnails
function handleContextMenu(event, item) {
  const mediaId = itemPayloadId(item)
  const assetId = hasAssetIdentity(item || {}) ? itemIdentity(item) : null
  if (!mediaId && !assetId) return
  contextMenu.show({
    event,
    mediaId,
    mediaIds: mediaId ? [mediaId] : [],
    assetId,
    assetIds: assetId ? [assetId] : [],
    selectedItems: item ? [item] : [],
    fileHash: item?.file_hash,
  })
}

// Watch for randomization changes from parent (URL restore)
watch(() => props.randomized, (newValue) => {
  if (newValue && props.randomSeed && !isRandomized.value) {
    // Parent enabled randomization (e.g., from URL)
    clearLiveAdvanceQueue()
    isRandomized.value = true
    shuffledIndices.value = createShuffledIndices(props.totalCount, props.randomSeed)
  } else if (!newValue && isRandomized.value) {
    // Parent disabled randomization
    clearLiveAdvanceQueue()
    isRandomized.value = false
    shuffledIndices.value = []
  }
})

// Watch loop setting and persist to localStorage
watch(loopEnabled, (newValue) => {
  const settings = loadSettings()
  settings.loopEnabled = newValue
  saveSettings(settings)
})

// Watch duration index and persist to localStorage
watch(currentDurationIndex, (newValue) => {
  const settings = loadSettings()
  settings.durationIndex = newValue
  saveSettings(settings)
})

// Watch for total count changes from parent (happens after websocket refresh)
watch(() => props.totalCount, (newValue, oldValue) => {
  // When server updates count, clear local removed IDs - server state is now correct
  if (oldValue !== undefined && newValue !== oldValue) {
    localRemovedIds.value = new Set()
  }

  localTotalCount.value = newValue

  // pageProvider path: the parent count is authoritative, so close when it genuinely
  // empties (e.g. the last item was deleted). The mediaList path closes via
  // applyRemovalToCount instead. Guard on a real >0 -> 0 transition so we never close
  // on the initial mount.
  if (!props.mediaList && oldValue !== undefined && oldValue > 0 && newValue <= 0) {
    close()
    return
  }

  // Resiliency: pinning happens on the WS event (1:1 with completions), so do NOT
  // pin here — that would double-count. We only re-arm the advance scheduler so the
  // stepper keeps moving even if a single WS completion was missed (the displayItem
  // lock + baseCurrentItem drift-correction keep the on-screen item correct).
  if (props.autoAdvanceOnNew && oldValue !== undefined && newValue > oldValue) {
    console.log(`[SlideshowMode auto-advance] count_delta ${oldValue} -> ${newValue} followStream=${followStream.value}`)
    scheduleAdvance()
  }

  // Rebuild shuffled indices when count changes to keep them in sync
  if (isRandomized.value && shuffledIndices.value.length !== newValue) {
    const seed = props.randomSeed || Date.now()
    shuffledIndices.value = createShuffledIndices(newValue, seed)
  }
})

// Watch for mediaList.effectiveTotal changes (handles prepend/remove operations)
watch(() => props.mediaList?.effectiveTotal?.value, (newValue) => {
  if (newValue !== undefined && newValue !== localTotalCount.value) {
    localTotalCount.value = newValue
    // Rebuild shuffled indices if randomized
    if (isRandomized.value && shuffledIndices.value.length !== newValue) {
      const seed = props.randomSeed || Date.now()
      shuffledIndices.value = createShuffledIndices(newValue, seed)
    }
  }
})


// Watch video transport visibility and persist to localStorage
watch(showVideoTransport, (newValue) => {
  const settings = loadSettings()
  settings.showVideoTransport = newValue
  saveSettings(settings)
})

// Watch image strip visibility and persist to localStorage
watch(showImageStrip, (newValue) => {
  const settings = loadSettings()
  settings.showImageStrip = newValue
  saveSettings(settings)
})

// Watch focus mode and persist to localStorage
watch(focusMode, (newValue) => {
  const settings = loadSettings()
  settings.focusMode = newValue
  saveSettings(settings)

  // Toggle body class to hide app-level sidebar
  if (newValue) {
    document.body.classList.add('slideshow-focus-mode')
    // Start cursor hiding timeout
    resetCursorTimeout()
  } else {
    document.body.classList.remove('slideshow-focus-mode')
    // Stop cursor hiding and show cursor
    cleanupCursorTimeout()
  }
})

// Pause cursor hiding while context menu is open
watch(() => contextMenu.state.value.visible, (visible) => {
  if (visible) {
    cleanupCursorTimeout()
  } else if (focusMode.value) {
    resetCursorTimeout()
  }
})

// Apply volume to the video element (persistence lives in useMediaPlayback)
watch(volume, (newValue) => {
  if (videoElement.value) {
    videoElement.value.volume = newValue
  }
})

watch(isMuted, (newValue) => {
  if (videoElement.value) {
    videoElement.value.muted = newValue
    if (!newValue) {
      videoElement.value.volume = volume.value
    }
  }
})

// Fetch and cache all metadata for an item (used for preloading in infinity mode)
async function fetchAndCacheMetadata(item) {
  const identity = itemIdentity(item)
  const mediaId = itemPayloadId(item)
  const assetId = hasAssetIdentity(item) ? identity : null
  if (!identity || !mediaId) return null

  // Check cache first
  const cached = metadataCache.value.get(identity)
  if (cached) return cached

  try {
    // Fetch all metadata in parallel
    const [facesResult, boardsResult, projectsResult, jobResult, chatResult, lineageResult] = await Promise.all([
      getMediaFaces(mediaId).catch(err => {
        console.error('Failed to load faces:', err)
        return { faces: [] }
      }),
      (assetId ? getAssetBoards(assetId) : axios.get(`/api/media/${mediaId}/boards`).then(r => r.data)).catch(err => {
        console.error('Failed to fetch media boards:', err)
        return []
      }),
      (assetId ? getAssetProjects(assetId) : axios.get(`/api/media/${mediaId}/projects`).then(r => r.data)).catch(err => {
        console.error('Failed to fetch media projects:', err)
        return []
      }),
      axios.get(`/api/media/${mediaId}/generation-job`).then(r => r.data).catch(() => null),
      item.chat_item_id
        ? axios.get(`/api/chats/by-item/${item.chat_item_id}`).then(r => r.data).catch(err => {
            if (err.response?.status === 410) return { error: 'deleted' }
            if (err.response?.status === 404) return { error: 'not_found' }
            return null
          })
        : Promise.resolve(null),
      axios.get(`/api/media/${mediaId}/lineage?include_descendants=true`).then(r => r.data).catch(err => {
        console.error('Failed to fetch lineage:', err)
        return { derivatives: [], descendants: [] }
      })
    ])

    // Extract descendants from lineage (combine immediate derivatives + recursive descendants)
    // Preserve relationship_type alongside media data
    // Filter out entries with missing media (can happen with older/incomplete lineage data)
    const allDescendants = [
      ...(lineageResult?.derivatives || []).filter(d => d?.media?.id).map(d => ({ ...d.media, _relationship_type: d.relationship_type || 'derived' })),
      ...(lineageResult?.descendants || []).filter(d => d?.media?.id).map(d => ({ ...d.media, _relationship_type: d.relationship_type || 'derived' }))
    ]
    // Deduplicate by id
    const descendantMap = new Map()
    allDescendants.forEach(d => descendantMap.set(d.id, d))
    const uniqueDescendants = Array.from(descendantMap.values())

    // Split into derived vs inspired
    const derivedDescendants = uniqueDescendants.filter(d => d._relationship_type !== 'inspired')
    const inspiredDescendants = uniqueDescendants.filter(d => d._relationship_type === 'inspired')

    // Store in cache
    const metadata = {
      faces: facesResult?.faces || [],
      boards: boardsResult || [],
      projects: projectsResult || [],
      job: jobResult,
      chat: chatResult,
      descendants: derivedDescendants,
      inspiredDescendants: inspiredDescendants
    }
    metadataCache.value.set(identity, metadata)

    return metadata
  } catch (err) {
    console.error('Failed to fetch metadata for media', item.id, err)
    // Return safe defaults so the panel still renders with whatever we have
    return {
      faces: [],
      boards: [],
      projects: [],
      job: null,
      chat: null,
      descendants: [],
      inspiredDescendants: []
    }
  }
}

// Load all metadata when current item changes - parallel fetching with caching
// immediate: true ensures metadata loads even when currentItem has a value at mount
// (e.g. when opened from BrowseGridView with a shared mediaList that already has items cached)
watch(currentItem, async (newItem) => {
  // Skip during atomic transitions - we'll set metadata manually
  if (isAtomicTransition.value) return

  // Clear face overlays when item changes
  visibleFaceOverlays.value.clear()

  if (!newItem?.id) {
    faces.value = []
    mediaProjects.value = []
    mediaBoards.value = []
    generationJob.value = null
    chatInfo.value = null
    descendants.value = []
    inspiredDescendants.value = []
    return
  }

  // Check cache first - if cached, update synchronously (no blink)
  const cached = metadataCache.value.get(itemIdentity(newItem))
  if (cached) {
    faces.value = cached.faces
    mediaProjects.value = cached.projects || []
    mediaBoards.value = cached.boards
    generationJob.value = cached.job
    chatInfo.value = cached.chat
    descendants.value = cached.descendants || []
    inspiredDescendants.value = cached.inspiredDescendants || []
    return
  }

  // Not cached - fetch asynchronously (normal navigation, not preloaded infinity mode)
  chatInfoLoading.value = true
  const metadata = await fetchAndCacheMetadata(newItem)
  chatInfoLoading.value = false

  if (metadata) {
    faces.value = metadata.faces
    mediaProjects.value = metadata.projects || []
    mediaBoards.value = metadata.boards
    generationJob.value = metadata.job
    chatInfo.value = metadata.chat
    descendants.value = metadata.descendants || []
    inspiredDescendants.value = metadata.inspiredDescendants || []
  }
}, { immediate: true })

// Strip functions removed - now handled by HorizontalVirtualScroller component


// Fetch all available markers
async function fetchMarkers() {
  try {
    const response = await axios.get('/api/markers')
    availableMarkers.value = response.data
  } catch (error) {
    console.error('Failed to fetch markers:', error)
  }
}

// Fetch boards for current media item
async function fetchMediaBoards(mediaId) {
  if (!mediaId) {
    mediaBoards.value = []
    return
  }

  try {
    const response = await axios.get(`/api/media/${mediaId}/boards`)
    mediaBoards.value = response.data
  } catch (error) {
    console.error('Failed to fetch media boards:', error)
    mediaBoards.value = []
  }
}

async function fetchGenerationJob(mediaId) {
  if (!mediaId) {
    generationJob.value = null
    return
  }

  try {
    const response = await axios.get(`/api/media/${mediaId}/generation-job`)
    generationJob.value = response.data
  } catch (error) {
    // Silently fail - not all images have generation jobs
    generationJob.value = null
  }
}

// Fetch chat info for "Jump to Chat" feature
async function fetchChatInfo(chatItemId) {
  if (!chatItemId) {
    chatInfo.value = null
    return
  }

  chatInfoLoading.value = true
  try {
    const response = await axios.get(`/api/chats/by-item/${chatItemId}`)
    chatInfo.value = response.data
  } catch (error) {
    if (error.response?.status === 410) {
      // Chat was deleted
      chatInfo.value = { error: 'deleted' }
    } else if (error.response?.status === 404) {
      // Chat item or chat not found
      chatInfo.value = { error: 'not_found' }
    } else {
      console.error('Failed to fetch chat info:', error)
      chatInfo.value = null
    }
  } finally {
    chatInfoLoading.value = false
  }
}

// Jump to the chat that generated this image
function jumpToChat() {
  if (!chatInfo.value || chatInfo.value.error) return
  router.push(`/chat/${chatInfo.value.id}`)
}

// Check if a marker is active for current media item
function isMarkerActive(markerId) {
  if (!currentItem.value || !currentItem.value.markers) return false
  return currentItem.value.markers.some(m => m.id === markerId)
}

// Toggle marker for current media item
async function toggleMarker(markerId) {
  if (!currentItem.value) return

  const isActive = isMarkerActive(markerId)
  const mediaId = currentPayloadId.value
  const assetId = currentAssetId.value

  try {
    let response
    if (assetId && isActive) {
      response = await removeMarkerFromAsset(assetId, markerId)
    } else if (assetId) {
      response = await addMarkerToAsset(assetId, markerId)
    } else if (isActive) {
      // Remove marker
      response = await axios.delete(`/api/media/${mediaId}/markers/${markerId}`)
    } else {
      // Add marker
      response = await axios.post(`/api/media/${mediaId}/markers/${markerId}`)
    }

    // Use markers from toggle response (avoids a separate GET request)
    const updatedMarkers = response?.data?.markers || response?.markers || (
      isActive
        ? (currentItem.value.markers || []).filter((marker) => marker.id !== markerId)
        : [...(currentItem.value.markers || []), availableMarkers.value.find((marker) => marker.id === markerId)].filter(Boolean)
    )

    applyMediaPatchToLocalState(mediaId, {
      markers: updatedMarkers,
      // Adding explicit curation makes the Asset durable. Reflect that
      // immediately instead of leaving the info panel on a stale projection.
      ...(isActive ? {} : { expires_at: null, auto_delete_at: null }),
    })

    // Force re-render of marker UI
    markerUpdateTrigger.value++
  } catch (error) {
    console.error('Failed to toggle marker:', error)
  }
}

</script>

<style scoped>
/* Sidebar scrollbar styling */
.sidebar-scroll::-webkit-scrollbar {
  width: 8px;
}

.sidebar-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-scroll::-webkit-scrollbar-thumb {
  background: rgba(156, 163, 175, 0.3);
  border-radius: 4px;
}

.sidebar-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(156, 163, 175, 0.5);
}

/* Firefox scrollbar */
.sidebar-scroll {
  scrollbar-width: thin;
  scrollbar-color: rgba(156, 163, 175, 0.3) transparent;
}

/* Status dot classes */
.status-completed {
  @apply bg-green-500 shadow-[0_0_0_2px_rgba(34,197,94,0.2)];
}

.status-processing {
  @apply bg-blue-500 shadow-[0_0_0_2px_rgba(59,130,246,0.2)];
  animation: pulse 2s ease-in-out infinite;
}

.status-reprocessing {
  @apply bg-purple-500 shadow-[0_0_0_2px_rgba(168,85,247,0.2)];
  animation: pulse 2s ease-in-out infinite;
}

.status-failed {
  @apply bg-red-500 shadow-[0_0_0_2px_rgba(239,68,68,0.2)];
}

.status-pending {
  @apply bg-gray-500 shadow-[0_0_0_2px_rgba(107,114,128,0.2)];
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

/* Slide transition */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from {
  transform: translateX(100%);
}

.slide-leave-to {
  transform: translateX(100%);
}

/* Slide up transition for related strip */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s ease;
}

.slide-up-enter-from {
  transform: translateY(100%);
}

.slide-up-leave-to {
  transform: translateY(100%);
}

/* Marker button SVG styling */
button :deep(svg) {
  display: inline-block;
  color: currentColor;
}

/* JSON syntax highlighting */
.json-highlighted :deep(.json-key) {
  color: #93c5fd; /* blue-300 */
}
.json-highlighted :deep(.json-string) {
  color: #86efac; /* green-300 */
}
.json-highlighted :deep(.json-number) {
  color: #fdba74; /* orange-300 */
}
.json-highlighted :deep(.json-boolean) {
  color: #c4b5fd; /* violet-300 */
}
.json-highlighted :deep(.json-null) {
  color: #f87171; /* red-400 */
}

/* Volume slider (horizontal) */
.volume-slider {
  -webkit-appearance: none;
  appearance: none;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 9999px;
  height: 4px;
}
.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}

/* Volume slider (vertical) */
.volume-slider-vertical {
  -webkit-appearance: none;
  writing-mode: vertical-lr;
  direction: rtl;
  appearance: none;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 9999px;
  width: 4px;
}
.volume-slider-vertical::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}
</style>
