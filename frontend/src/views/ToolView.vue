<template>
  <div class="w-full h-full flex bg-surface-overlay text-content-secondary relative">
    <!-- Slideshow Mode (overlays everything when active) -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowTotalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :live-item-ids="slideshowState.autoAdvanceOnNew ? slideshowLiveItemIds : null"
      :randomized="slideshowState.randomized"
      :random-seed="slideshowState.randomSeed"
      :auto-advance-on-new="slideshowState.autoAdvanceOnNew"
      :inline="true"
      @close="exitSlideshow"
      @compare-with-source="handleCompareFromSlideshow"
    />

    <!-- Compare Mode (overlays slideshow when active) -->
    <CompareMode
      v-if="compareState.active"
      :left-item="compareState.leftItem"
      :right-item="compareState.rightItem"
      :loading="compareState.loading"
      :error="compareState.error"
      @close="exitCompare"
      @swap="swapCompareImages"
    />

    <!-- Loading State -->
    <div v-if="isInitialLoading && !slideshowState.active" class="flex-1 flex items-center justify-center">
      <div class="flex flex-col items-center gap-4">
        <div class="w-10 h-10 border-4 border-edge border-t-blue-500 rounded-full animate-spin"></div>
        <span class="text-content-muted text-sm">Loading...</span>
      </div>
    </div>

    <!-- Error State -->
    <ConnectionError
      v-else-if="error"
      :status-code="error.statusCode"
      @retry="loadTool(true)"
    />

    <!-- Tool View (use v-show to keep mounted during slideshow) -->
    <template v-else-if="tool">
      <!-- Unavailable Overlay (semi-transparent, shows cached UI behind it) -->
      <div
        v-if="toolAvailability !== 'available'"
        class="absolute inset-0 bg-black/50 z-40 flex items-center justify-center pointer-events-auto"
      >
        <div class="bg-surface border border-edge-subtle rounded-lg p-6 max-w-md text-center shadow-xl">
          <svg class="w-12 h-12 text-yellow-400 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <h3 class="text-lg font-semibold text-content mb-2">{{ unavailableTitle }}</h3>
          <p class="text-content-tertiary">
            {{ unavailableSubtitle }}
          </p>
        </div>
      </div>
      <!-- Loading Generation Config Overlay -->
      <div
        v-if="loadingGenerationConfig"
        class="absolute inset-0 bg-black/60 z-50 flex items-center justify-center pointer-events-auto"
      >
        <div class="bg-surface border border-edge-subtle rounded-lg p-6 max-w-md text-center shadow-xl">
          <div class="w-10 h-10 border-4 border-edge border-t-purple-500 rounded-full animate-spin mx-auto mb-4"></div>
          <h3 class="text-lg font-semibold text-content mb-2">Converting generation settings</h3>
          <p class="text-content-tertiary text-sm">
            Converting generation parameters from the source image to match this tool's parameters. This may take a moment.
          </p>
        </div>
      </div>
      <!-- Full-width app header on top, columns below. The header content is
           teleported up from the controls scope into #tool-header-slot so it
           sits above both columns regardless of the Studio/Stage layout. -->
      <div v-show="!slideshowState.active" class="flex-1 min-w-0 flex flex-col min-h-0">
        <div id="tool-header-slot" class="flex-none border-b border-surface px-4 pt-4 pb-3"></div>
        <div class="flex-1 min-w-0 flex min-h-0">

      <!-- Generation Controls. In Studio mode the primary column (left, wide); in
           Stage mode a narrow LEFT sidebar (on the left specifically, to read
           differently from the slideshow). Always order-1 (leftmost). Width is
           always explicit (66.667% in Studio = old flex-1 against w-1/3 sibling)
           so the toggle tweens. The border fades color, not presence. The
           transition is suppressed during seam drag so the resize stays 1:1. -->
      <div
        class="flex flex-col min-h-0 min-w-0 order-1 flex-none border-r transition-[width,border-color] duration-300 ease-out"
        :class="[
          layoutMode === 'stage' ? 'border-transparent' : 'border-surface',
          stageResizing ? '!transition-none' : ''
        ]"
        :style="{ width: layoutMode === 'stage' ? stageControlsWidth + 'px' : '66.6667%' }"
      >
       <div class="flex-1 overflow-y-auto scrollbar-stable p-4 pb-6">
        <!-- Header (teleported full-width to #tool-header-slot) -->
        <Teleport defer to="#tool-header-slot">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary"><ToolIcon :tool="tool" bare :ring="false" /></div>
            <HopToToolMenu
              :source-tool-id="tool.full_tool_id"
              :tool-name="tool.name"
              :source-task-types="tool.task_types || []"
              :custom-name="instanceCustomName"
              :current-tab-id="ownTab?.id ?? null"
              @hop="handleHopToTool"
              @hop-instance="(tab, hopTool) => handleHopToTool(hopTool, tab)"
              @rename="renameInstance"
            />
          </div>
          <div class="flex items-center gap-2">
            <!-- Edit (frozen-flow tools only): the tool's own page is the obvious
                 place to find "edit this tool". Matches the Presets trigger. -->
            <button
              v-if="isUserTool"
              class="flex items-center gap-2 px-3 py-1.5 bg-overlay-subtle hover:bg-overlay-light border border-edge-subtle rounded text-sm text-content-secondary transition-colors"
              title="Edit this tool"
              @click="openEditUserTool"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
              </svg>
              Edit
            </button>
            <span
              v-if="tool.metadata?.display_price && !hidePricesRef"
              class="px-2.5 py-1 text-xs rounded-full"
              :class="isStimmaCloudTool
                ? 'stimma-cloud-border-solid stimma-cloud-text font-medium bg-overlay-subtle'
                : 'text-content-tertiary bg-overlay-subtle border border-edge-subtle'"
            >{{ tool.metadata.display_price }}</span>
            <PresetPicker
              v-if="tool.full_tool_id"
              :tool-id="tool.full_tool_id"
              :current-state="getCurrentState()"
              :selected-preset-id="selectedPresetId"
              :active-preset-name="activePreset?.name"
              :is-modified="isModified"
              :has-active-preset="hasActivePreset"
              @select="handlePresetSelect"
              @saved="handlePresetSaved"
              @save="saveToActivePreset"
              @revert="handleRevertToBaseState"
              @clear="handleResetToDefaults"
            />
          </div>
        </div>
        <!-- Subtitle: Provider, task types. Renamed instances condense the
             tool name onto this row (mirrors the sidebar row contract). -->
        <div class="text-xs mt-1 mb-6 flex items-center gap-1.5 text-content-muted">
          <template v-if="instanceCustomName">
            <span>{{ tool.name }}</span>
            <span>·</span>
          </template>
          <span v-if="isStimmaCloudTool" class="stimma-cloud-text font-medium">Stimma Cloud</span>
          <span v-else class="text-content-muted">{{ providerDisplayName }}</span>
          <template v-if="taskTypesDisplay">
            <span>·</span>
            <span>{{ taskTypesDisplay }}</span>
          </template>
          <template v-if="projectScopeId">
            <span>·</span>
            <span class="inline-flex items-center gap-1.5">
              <span>Saving to</span>
              <span class="inline-flex items-center gap-1.5 rounded-full bg-overlay-subtle px-2 py-0.5 text-[11px] font-medium text-content-secondary">
                <ArchiveBoxIcon class="h-3.5 w-3.5 flex-shrink-0" />
                <span class="truncate max-w-[180px]">{{ projectScopeName }}</span>
              </span>
            </span>
          </template>
        </div>

        <!-- Inspiration Banner (active remix) -->
        <RemixBanner
          v-if="remixSource"
          :thumbnail-url="getThumbnailUrl(remixSource.mediaId, 256)"
          :prompt-snippet="remixSource.promptSnippet"
          :media-id="remixSource.mediaId"
          :current-prompt="globalPrefs.prompt"
          :rendered-prompt="remixSource.renderedPrompt"
          :show-use-image="!!mediaInputConfig"
          :seed="remixSource.seed"
          @dismiss="remixSource = null"
          @view-source="openRemixSourceInSlideshow"
          @copy-prompt="handleRemixUsePrompt"
          @copy-exact-prompt="handleRemixUseExactPrompt"
          @use-image="handleRemixUseImage"
          @use-seed="handleRemixUseSeed"
        />
        <!-- Inspiration Banner (dismissed interstitial — auto-cleared remix) -->
        <RemixBanner
          v-else-if="dismissedRemix"
          :dismissed="true"
          :thumbnail-url="getThumbnailUrl(dismissedRemix.mediaId, 256)"
          :prompt-snippet="dismissedRemix.promptSnippet"
          :media-id="dismissedRemix.mediaId"
          @restore="handleRemixRestore"
          @dismiss="dismissedRemix = null"
          @expired="handleRemixDismissedExpired"
        />

        <!-- Resolution auto-change notification -->
        <div
          v-if="resAutoChange"
          class="flex items-center gap-3 mb-2 px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/5 text-[11px]"
        >
          <span class="text-content-secondary flex-1">
            Size changed to <span class="font-medium text-content">{{ resAutoChange.newWidth }}×{{ resAutoChange.newHeight }}</span>
          </span>
          <button
            @click="resAutoChangeKeepArea"
            class="text-blue-500 hover:text-blue-400 font-medium whitespace-nowrap"
          >Keep {{ resAutoChangeOldAreaLabel }} area</button>
          <button
            @click="resAutoChangeRevert"
            class="text-blue-500 hover:text-blue-400 font-medium whitespace-nowrap"
          >Restore previous size</button>
          <button
            @click="resAutoChange = null"
            class="text-content-muted hover:text-content-secondary"
          >
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>

        <!-- Row 2: Resolution + Markers | Generate + Forever + Auto-delete -->
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <!-- Constrained resolution picker (for tools with x-allowed-dimensions) -->
            <ConstrainedResolutionPicker
              v-if="allowedDimensions"
              :allowed-dimensions="allowedDimensions"
              :width="modelParams.width"
              :height="modelParams.height"
              @update="onResolutionUpdate"
            />
            <!-- Resolution picker (for tools with width/height params) -->
            <ResolutionPicker
              v-else-if="hasWidthHeight && !hasMegapixels"
              :width="modelParams.width"
              :height="modelParams.height"
              :has-reference-images="!isFromScratch"
              v-model:mode="resolutionMode"
              v-model:lock-size="resolutionLockSize"
              v-model:lock-area="resolutionLockArea"
              @update="onResolutionUpdate"
            />
            <!-- Aspect ratio picker (for tools with aspect_ratio param) -->
            <GeminiResolutionPicker
              v-if="hasAspectRatio"
              :aspect-ratio="modelParams.aspect_ratio || '1:1'"
              :image-size="modelParams.image_size || '1K'"
              :image-size-choices="imageSizeChoices"
              @update:aspect-ratio="modelParams.aspect_ratio = $event"
              @update:image-size="modelParams.image_size = $event"
            />
            <!-- Megapixels picker (for tools with megapixels param) -->
            <MegapixelsPicker
              v-if="hasMegapixels"
              v-model="modelParams.megapixels"
            />
            <AutoMarkPicker
              :markers="jobsManager?.availableMarkers.value || []"
              v-model="globalPrefs.autoMarkerIds"
            />
          </div>

          <div class="flex items-center gap-2">
            <!-- Generate/Process Button (split: Run + batch-size dropdown) -->
            <BatchRunButton
              :batch-size="uiState.batchSize"
              :disabled="!canSubmit"
              :is-mac="isMac"
              :media-batch-count="globalPrefs.batchMode ? mediaInputItems.length : 0"
              @run="submitJob"
              @update:batch-size="uiState.batchSize = $event"
            />

            <!-- Forever Mode Toggle -->
            <ForeverModeButton
              :is-active="uiState.generateForeverMode"
              :concurrency="uiState.generateForeverConcurrency"
              :idle-limit="uiState.generateForeverIdleLimit"
              :is-stimma-cloud="isStimmaCloudTool"
              @toggle="stopForeverMode"
              @start="startForeverMode"
              @update:concurrency="uiState.generateForeverConcurrency = $event"
              @update:idle-limit="uiState.generateForeverIdleLimit = $event"
            />

            <!-- Auto-delete duration selector -->
            <AutoDeletePicker
              :model-value="autoDeleteDuration"
              @update:model-value="setAutoDeleteDuration"
            />

            <!-- Layout mode toggle: off = Studio (controls primary), on = Stage
                 (image primary, steer by chat). -->
            <button
              @click="layoutMode = layoutMode === 'stage' ? 'studio' : 'stage'"
              class="cursor-pointer transition-colors flex items-center justify-center px-3 py-2 rounded-lg"
              :class="layoutMode === 'stage' ? 'bg-blue-500/15 text-blue-500' : 'bg-surface-raised hover:bg-surface-hover text-content'"
              :title="layoutMode === 'stage' ? 'Stage — image primary, steer by chat' : 'Studio — controls primary'"
            >
              <PhotoIcon class="w-5 h-5" />
            </button>

            <!-- Queue options (both modes): lifted onto the header button strip so
                 the queue itself has no heading/floating menu. -->
            <div v-if="jobsManager" class="relative flex items-center">
              <button
                @click="stageMenuOpen = !stageMenuOpen"
                class="cursor-pointer transition-colors flex items-center justify-center px-3 py-2 rounded-lg bg-surface-raised hover:bg-surface-hover text-content"
                title="Queue options"
              >
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><circle cx="10" cy="4" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="10" cy="16" r="1.5"/></svg>
              </button>
              <div v-if="stageMenuOpen" class="fixed inset-0 z-40" @click="stageMenuOpen = false"></div>
              <div v-if="stageMenuOpen" class="absolute right-0 top-full mt-2 z-50 bg-surface border border-edge-subtle rounded-md shadow-lg min-w-[160px] overflow-hidden py-1" @click.stop>
                <template v-if="isFromScratch">
                  <button
                    @click="setImageMode('fit'); stageMenuOpen = false"
                    :class="['w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors', uiState.imageMode === 'fit' ? 'text-blue-500' : 'text-content-secondary']"
                  ><span class="w-4">{{ uiState.imageMode === 'fit' ? '✓' : '' }}</span>Fit</button>
                  <button
                    @click="setImageMode('cover'); stageMenuOpen = false"
                    :class="['w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors', uiState.imageMode === 'cover' ? 'text-blue-500' : 'text-content-secondary']"
                  ><span class="w-4">{{ uiState.imageMode === 'cover' ? '✓' : '' }}</span>Cover</button>
                  <div class="border-t border-edge-subtle my-1"></div>
                </template>
                <button
                  @click="clearQueue(); stageMenuOpen = false"
                  :disabled="queuedJobsCount === 0"
                  :class="['w-full px-3 py-2 text-left text-sm transition-colors', queuedJobsCount > 0 ? 'text-red-500 hover:bg-red-500/10' : 'text-content-muted cursor-not-allowed']"
                >Clear Queue{{ queuedJobsCount > 0 ? ` (${queuedJobsCount})` : '' }}</button>
              </div>
            </div>
          </div>
        </div>
        </Teleport>

        <!-- Prompt (for task types that need it). external-chat: the editor is a
             plain editor here — the page-level chat lives in the dock below and
             is owned by this view, not the prompt field. -->
        <div v-if="hasPrompt" class="mb-6">
          <AIPromptEditor
            ref="aiPromptEditorRef"
            v-model="globalPrefs.prompt"
            :rows="isFromScratch ? 19 : 10"
            external-chat
            :promptOptions="globalPrefs.promptOptions"
            @update:promptOptions="globalPrefs.promptOptions = $event"
            :placeholder="promptPlaceholder"
          />
        </div>

        <!-- Lyrics (audio music tools): a second, prompt-like input. Sits right
             under the main prompt — the prompt is the production brief (genre,
             mood), the lyrics are the words sung. Bound to modelParams like the
             other special params; empty → instrumental / auto-written lyrics. -->
        <div v-if="hasLyrics" class="mb-6">
          <label class="block text-sm font-medium text-content mb-1.5">Lyrics</label>
          <textarea
            v-model="modelParams.lyrics"
            rows="5"
            placeholder="Optional lyrics. Use section tags like [Verse], [Chorus]. Leave empty for an instrumental or auto-written track."
            class="w-full rounded-lg border border-edge-subtle bg-overlay-faint px-3 py-2 text-sm text-content placeholder:text-content-muted focus:outline-none focus:border-blue-500/50 resize-y"
          />
        </div>

        <!-- Page-level agent chat. Mounted unconditionally and teleported into
             the single full-width dock so it survives layout switches without
             ever changing target — the chat stays put while the studio/stage
             toggle animates the columns above it. -->
        <Teleport defer to="#agent-dock">
          <PromptAgentChat
            ref="promptAgentChatRef"
            :prompt="globalPrefs.prompt"
            :has-prompt="hasPrompt"
            :active-skills="activeToolSkills"
            v-model:instructions="globalPrefs.agentInstructions"
          />
        </Teleport>

        <!-- Media Input (images or videos, unified picker). In batch mode the slot
             collapses to a representative stack with a count; the same prep
             controls apply uniformly to every item. -->
        <MediaPicker
          v-if="mediaInputConfig && !hasMask"
          ref="mediaPickerRef"
          :model-value="mediaInputItems"
          @update:model-value="updateMediaInputItems"
          :accept="mediaInputConfig.accept"
          :min-items="mediaInputConfig.min"
          :max-items="mediaInputConfig.max"
          :reorderable="mediaInputConfig.reorderable"
          :label="mediaInputConfig.label"
          :description="mediaInputConfig.description"
          :controlnet-options="controlnetOptions"
          :batch-mode="globalPrefs.batchMode"
          :frame-mode-key="fullToolIdFromProps"
          @view-media="openSingleImageSlideshow"
          @view-media-batch="openMediaBatchSlideshow"
          @suggest-resolution="onSuggestResolution"
          @suggest-aspect="onSuggestAspect"
          @explode="explodeBatch"
        />

        <!-- Reference audio: its own section, separate from the visual input
             above (audio-conditioned tools like lip-sync / avatar). -->
        <MediaPicker
          v-if="audioInputConfig"
          :model-value="audioInputItems"
          @update:model-value="updateAudioInputItems"
          :accept="audioInputConfig.accept"
          :min-items="audioInputConfig.min"
          :max-items="audioInputConfig.max"
          :reorderable="audioInputConfig.reorderable"
          :label="audioInputConfig.label"
          :description="audioInputConfig.description"
        />

        <!-- Inpaint: Combined source image + Mask editor -->
        <MaskEditor
          ref="maskEditorRef"
          v-if="hasMask"
          :image="inpaintSourceImage"
          :mask-format="maskFormat"
          v-model="maskDataUrl"
          @update:image="handleInpaintImageUpdate"
          @expand="maskEditorModalOpen = true"
        />

        <!-- AI Mask Assistant (below MaskEditor when inpainting with an image) -->
        <AIMaskAssistant
          v-if="hasMask && inpaintSourceImage?.path"
          :image-path="inpaintSourceImage.path"
          :mask-editor-ref="maskEditorRef"
        />


        <!-- Video Frame Images (for image-to-video). Same rich picker as ordinary
             reference images — prep, auto-resolution, drag-to-swap — but with named
             Start / End slots and a "same for both" loop shortcut. Slots are an
             ordered array: index 0 = start, index 1 = end (bridged to videoImages). -->
        <MediaPicker
          v-if="hasVideoFrames"
          ref="mediaPickerRef"
          :model-value="frameItems"
          @update:model-value="updateFrameItems"
          accept="image"
          :min-items="frameMinItems"
          :max-items="hasEndFrame ? 2 : 1"
          :reorderable="hasEndFrame"
          label="Reference Frames"
          :slot-labels="hasEndFrame ? ['Start Frame', 'End Frame'] : ['Start Frame']"
          :frame-grab-defaults="hasEndFrame ? ['last', 'first'] : ['last']"
          :frame-mode-key="fullToolIdFromProps"
          :allow-sets="false"
          :controlnet-options="controlnetOptions"
          :disabled="frameConstraintState.disabled"
          :disabled-reason="frameConstraintState.reason"
          @view-media="openSingleImageSlideshow"
          @suggest-resolution="onSuggestResolution"
          @suggest-aspect="onSuggestAspect"
        />

        <!-- Video Parameters: Duration (for tools using duration param) -->
        <div v-if="hasDuration" class="mb-6">
          <div class="rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]">
            <!-- Duration -->
            <div class="flex items-center justify-between gap-4 px-4 py-3">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-content">Duration</div>
                <div class="text-xs text-content-muted mt-0.5">{{ outputsAudio ? 'Audio length in seconds' : 'Video length in seconds' }}</div>
              </div>
              <!-- Dropdown for fixed duration options -->
              <SettingsDropdown
                v-if="allowedDurations"
                :model-value="String(modelParams.duration || durationConfig.default)"
                @update:model-value="modelParams.duration = Number($event)"
                :options="allowedDurations.map((d: number) => ({ value: String(d), label: `${d}s` }))"
              />
              <!-- Slider for continuous range -->
              <div v-else class="flex min-w-0 w-[45%] max-w-[360px] flex-shrink-0 items-center justify-end gap-1.5">
                <input v-no-autocorrect
                  type="range"
                  v-model.number="modelParams.duration"
                  :min="durationConfig.min"
                  :max="durationConfig.max"
                  :step="durationConfig.step"
                  class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                >
                <div class="text-sm text-content w-10 flex-shrink-0 text-right">{{ (modelParams.duration || durationConfig.default).toFixed(1) }}s</div>
              </div>
            </div>
            <!-- FPS (shown for comfyui tools that still expose fps) -->
            <div v-if="hasFps" class="flex items-center justify-between gap-4 px-4 py-3">
              <div class="w-[55%] flex-shrink-0">
                <div class="text-sm font-medium text-content">FPS</div>
                <div class="text-xs text-content-muted mt-0.5">Frames per second</div>
              </div>
              <SettingsDropdown
                :model-value="String(modelParams.fps)"
                @update:model-value="modelParams.fps = Number($event)"
                :options="fpsOptions.map((fps: number) => ({ value: String(fps), label: `${fps} fps` }))"
              />
            </div>
          </div>
        </div>

        <!-- Video Parameters: Frame Count + FPS (legacy, for VACE tools) -->
        <div v-else-if="hasFrameCount" class="mb-6">
          <div class="rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]">
            <!-- Frame Count -->
            <div class="flex items-center justify-between gap-4 px-4 py-3">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-content">Frame Count</div>
                <div class="text-xs text-content-muted mt-0.5">Number of frames to generate</div>
              </div>
              <div class="flex min-w-0 w-[45%] max-w-[360px] flex-shrink-0 items-center justify-end gap-1.5">
                <input v-no-autocorrect
                  type="range"
                  v-model.number="modelParams.frameCount"
                  :min="frameCountConfig.min"
                  :max="frameCountConfig.max"
                  class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                >
                <div class="text-center flex-shrink-0">
                  <div class="text-sm text-content">{{ modelParams.frameCount }}</div>
                  <div class="text-xs text-content-muted">~{{ estimatedDuration }}s</div>
                </div>
              </div>
            </div>
            <!-- FPS -->
            <div class="flex items-center justify-between gap-4 px-4 py-3">
              <div class="w-[55%] flex-shrink-0">
                <div class="text-sm font-medium text-content">FPS</div>
                <div class="text-xs text-content-muted mt-0.5">Frames per second</div>
              </div>
              <SettingsDropdown
                :model-value="String(modelParams.fps)"
                @update:model-value="modelParams.fps = Number($event)"
                :options="fpsOptions.map((fps: number) => ({ value: String(fps), label: `${fps} fps` }))"
              />
            </div>
          </div>
        </div>


        <!-- Upscale Resolution (for tools with x-control: "upscale_resolution") -->
        <UpscaleResolutionPicker
          v-if="showUpscalePicker"
          class="my-6"
          :model-value="resolutionPickerValue"
          @update:model-value="onResolutionPickerUpdate"
          :input-width="inputImageWidth"
          :input-height="inputImageHeight"
          :support-scale-factor="showUpscalePicker"
          :support-resolution="showUpscalePicker"
        />


        <!-- LoRA Selection (for task types that support it) -->
        <LoraPoolPanel
          v-if="hasLoras"
          ref="loraPoolPanelRef"
          :tool-id="scopedToolId(fullToolIdFromProps)"
          :model-name="tool?.model || null"
          :available-loras="availableLoras"
          :is-refreshing="isRefreshingLoras"
          :is-uploading="isUploadingLora"
          :upload-progress="loraUploadProgress"
          :upload-file-name="loraUploadFileName"
          :upload-config="loraUploadConfig"
          @refresh-loras="refreshLoras"
          @upload="uploadLora"
        />

        <!-- Post-processing chain (auto-runs after each generation when On).
             Not shown for audio tools — no audio post-processing chains exist. -->
        <PostProcessingPanel
          v-if="!outputsAudio"
          v-model:chain="toolChain"
          :current-tool-id="fullToolIdFromProps"
          :base-media-type="outputsVideo ? 'video' : 'image'"
        />

        <!-- Generic Parameters (dynamic from tool schema, grouped) -->
        <SchemaParamGroup
          :groups="groupedGenericParams"
          :values="constraintValues"
          :is-group-collapsed="getGroupCollapsed"
          :on-toggle-group-collapsed="toggleGroupCollapsed"
          @update:param="(name, value) => { modelParams[name] = value }"
        />

        <div v-if="submissionError" class="mt-6 p-3 bg-red-500/10 border border-red-500/30 rounded-md text-red-500 text-sm flex items-center justify-between gap-3">
          <span>{{ submissionError }}</span>
          <button
            v-if="submissionErrorCode === 'subscription_required'"
            @click="connectStimmaCloudForSubmission"
            :disabled="submissionCloudConnecting"
            class="flex-shrink-0 rounded-full px-2.5 py-1 text-xs font-medium stimma-cloud-text border border-current/20 hover:border-current/40 transition-colors"
          >
            {{ submissionCloudConnecting ? 'Connecting…' : 'Connect Stimma Cloud' }}
          </button>
        </div>
       </div>
      </div>

      <!-- Draggable seam between the controls sidebar and the hero (Stage only).
           Zero-width in the flex layout so it adds no gap or gray line; the drag
           zone is an overlay straddling the boundary. -->
      <div
        v-show="layoutMode === 'stage'"
        class="order-2 relative w-0 flex-none z-10"
      >
        <div
          @pointerdown="startStageResize"
          class="group absolute inset-y-0 -left-1 w-2 cursor-col-resize"
          title="Drag to resize"
        >
          <!-- Thin fixed-width visual bar centered on the seam, so the highlight
               is a uniform rectangle regardless of the wider drag zone. -->
          <div
            class="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 group-hover:bg-blue-500/50 transition-colors"
            :class="{ 'bg-blue-500/50': stageResizing }"
          ></div>
        </div>
      </div>

      <!-- Hero (MIDDLE): always rendered as flex-1 between controls and queue.
           In Studio the controls (66.667%) + queue (33.333%) claim the full row,
           so the hero collapses to 0px and stays invisible; in Stage the columns
           shrink and the hero grows into the gap, revealing the current image.
           Stays mounted across the toggle so the matte/image tween smoothly. -->
      <div
        v-if="jobsManager"
        class="order-3 flex-1 min-w-0 flex min-h-0 relative items-center justify-center bg-slideshow-matt overflow-hidden"
      >
        <!-- Empty state -->
        <div v-if="!stageCurrentJob" class="flex flex-col items-center gap-3 text-content-muted">
          <div v-if="stageHasPending" class="w-10 h-10 border-4 border-edge border-t-blue-500 rounded-full animate-spin"></div>
          <span class="text-sm">{{ stageHasPending ? 'Generating…' : 'No images yet' }}</span>
        </div>

        <!-- Current generation (click → full slideshow at this image). No padding
             so the matte runs edge to edge. We bypass MediaImage's contain wrapper
             (which sizes to natural dimensions and shows whitespace when the image
             is smaller than the hero) by using cover mode with an !object-contain
             override on the img — fills the hero, then object-fit does the
             aspect-ratio work. Container forced transparent so the matte shows. -->
        <div
          v-else
          class="absolute inset-0 cursor-zoom-in"
          @click="openSlideshow(stageCurrentJob)"
          title="Open in slideshow"
        >
          <div
            v-if="outputsVideo && stageCurrentHash"
            class="absolute inset-0"
            draggable="true"
            @dragstart.stop="onHeroDragStart($event)"
            @dragend="handleHeroDragEnd"
          >
            <video
              :src="getMediaFileUrl(stageCurrentHash)"
              class="w-full h-full object-contain"
              autoplay loop muted playsinline
            />
          </div>
          <!-- Audio result: inline player. Stop click propagation so transport
               controls don't also trigger the slideshow zoom on the wrapper. -->
          <AudioPlayer
            v-else-if="outputsAudio && stageCurrentMediaId != null"
            :key="`tool-audio-${stageCurrentMediaId}`"
            :src="stageCurrentHash ? getMediaFileUrl(stageCurrentHash) : ''"
            :media-id="stageCurrentMediaId"
            class="w-full h-full cursor-default"
            @click.stop
          />
          <MediaImage
            v-else-if="stageCurrentMediaId != null"
            :media-id="stageCurrentMediaId"
            :thumbnail="false"
            :contain="false"
            container-class="w-full h-full !bg-transparent"
            img-class="!object-contain !bg-none !bg-transparent"
            alt="Current generation"
          />
        </div>

        <!-- Jump to newest (top-left) when viewing an older image -->
        <button
          v-if="stageCurrentJob && !stageOnNewest"
          @click.stop="stagePinnedMediaId = null"
          class="absolute top-4 left-4 z-10 flex items-center gap-1.5 bg-black/55 backdrop-blur-md text-white text-xs px-3 py-1.5 rounded-full hover:bg-black/75 transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" /></svg>
          Jump to newest
        </button>

        <!-- Auto-delete time remaining for the hero image. Stage strips hide this
             to keep thumbnails uncluttered. -->
        <div
          v-if="stageAutoDeleteTime"
          :class="[
            'absolute left-4 z-10 h-8 flex items-center justify-center gap-1.5 px-2.5 bg-black/70 backdrop-blur-md rounded text-xs font-bold text-[#FFC107] shadow-[0_2px_8px_rgba(0,0,0,0.45)]',
            stageCurrentJob && !stageOnNewest ? 'top-14' : 'top-4'
          ]"
          title="Auto-trash time remaining"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3.5 h-3.5">
            <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
          </svg>
          <span class="leading-none whitespace-nowrap">{{ stageAutoDeleteTime }}</span>
        </div>

        <!-- Generation time/details for the hero image. Stage strips hide this
             to keep thumbnails uncluttered. -->
        <button
          v-if="stageCurrentJob"
          @click.stop="showJobInfo(stageCurrentJob)"
          class="absolute top-4 right-4 z-10 h-8 flex items-center justify-center gap-1.5 px-2.5 bg-black/70 backdrop-blur-md hover:bg-blue-500/80 rounded text-xs font-bold text-white transition-colors shadow-[0_2px_8px_rgba(0,0,0,0.45)]"
          title="Generation details"
        >
          <span v-if="stageGenerationTime">{{ stageGenerationTime }}s</span>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
          </svg>
        </button>

        <!-- Per-image marker toggles for the hero image. -->
        <template v-if="stageCurrentJob">
          <div v-if="stageMarkers.length" class="absolute bottom-4 left-4 z-10 flex gap-1">
            <button
              v-for="marker in stageMarkers"
              :key="marker.id"
              @click.stop="handleToggleMarker({ mediaId: stageCurrentMediaId, marker })"
              :class="['w-8 h-8 rounded-lg flex items-center justify-center transition-all border-2', stageHasMarker(marker.id) ? 'bg-black/80' : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white']"
              :style="stageHasMarker(marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
              :title="stageHasMarker(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
            >
              <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
            </button>
          </div>
        </template>
      </div>

      <!-- Queue rail (RIGHT): same JobsGrid in both modes — width tweens from
           33.333% (Studio: wide rail) to 160px (Stage: narrow strip alongside
           the hero). Click semantics differ: Studio opens the slideshow, Stage
           pins the thumbnail to the hero (current-media-id highlights it). -->
      <div
        v-if="jobsManager"
        class="order-4 flex-none overflow-y-auto scrollbar-stable bg-surface-overlay border-l transition-[width,padding,border-color] duration-300 ease-out"
        :class="[
          layoutMode === 'stage' ? 'border-surface p-2' : 'border-transparent p-4',
          stageResizing ? '!transition-none' : ''
        ]"
        :style="{ width: layoutMode === 'stage' ? '160px' : '33.3333%' }"
      >
        <JobsGrid
          :jobs="allJobs"
          :markers="jobsManager.availableMarkers.value"
          :media-hashes="jobsManager.mediaHashes.value"
          :media-has-alpha="jobsManager.mediaHasAlpha.value"
          :media-markers="jobsManager.mediaMarkers.value"
          :media-generation-times="jobsManager.mediaGenerationTimes.value"
          :media-data="jobsManager.mediaData.value"
          :batch-jobs="jobsManager.batchJobs.value"
          :active-chain-runs="jobsManager.activeChainRuns.value"
          :is-video="outputsVideo"
          :is-audio="outputsAudio"
          :image-mode="uiState.imageMode"
          :current-media-id="layoutMode === 'stage' ? stageCurrentMediaId : null"
          :tool-display-name="tool?.name"
          :compact-overlays="layoutMode === 'stage'"
          :thumbnail-size="queueThumbnailSize"
          :slot-count="uiState.generateForeverMode ? (uiState.generateForeverConcurrency ?? 1) : null"
          empty-message="No jobs yet"
          @job-click="handleQueueClick"
          @toggle-marker="handleToggleMarker"
          @dismiss-job="dismissJob"
          @retry-job="retryJob"
          @cancel-job="cancelJob"
          @cancel-and-dismiss-batch="cancelAndDismissBatch"
          @dismiss-batch="dismissBatch"
          @retry-chain="jobsManager.retryChainRun"
          @dismiss-chain="jobsManager.dismissChainRun"
          @media-load-error="handleMediaLoadError"
          @show-job-info="showJobInfo"
        />
      </div>
        </div>

        <!-- Agent chat dock: full width at the bottom of the page in both modes,
             so the chat stays put while the columns above tween between Studio
             and Stage. Single Teleport target — no remount on layout toggle. -->
        <div
          id="agent-dock"
          class="flex-none overflow-y-auto border-t border-edge bg-surface-overlay px-4 pt-3 pb-4 max-h-[45%] shadow-[0_-4px_12px_rgba(0,0,0,0.06)]"
        ></div>
      </div>
    </template>

    <!-- Error Modal -->
    <JobErrorModal
      :show="showErrorModal"
      :job="errorModalJob"
      @close="closeErrorModal"
      @retry="handleErrorModalRetry"
      @dismiss="handleErrorModalDismiss"
    />

    <!-- Info Modal -->
    <JobInfoModal
      :show="showInfoModal"
      :job="infoModalJob"
      @close="closeInfoModal"
    />

    <!-- Mask Editor Modal -->
    <MaskEditorModal
      v-model="maskEditorModalOpen"
      :image="inpaintSourceImage"
      :mask-data-url="maskDataUrl"
      :mask-format="maskFormat"
      @update:mask-data-url="maskDataUrl = $event"
      @update:image="handleInpaintImageUpdate"
    />

    <!-- Edit tool (frozen-flow tools) — settings + delete -->
    <FreezeToolDialog
      :show="editToolDialogOpen"
      :tool="editingToolRow"
      :flow-name="editingFlowName"
      :flow-output-names="editingFlowOutputNames"
      @cancel="editToolDialogOpen = false"
      @saved="onUserToolEdited"
      @deleted="onUserToolDeleted"
      @open-flow="onEditOpenBackingFlow"
    />

    <!-- Context Menu for queue images/videos -->
    <MediaContextMenu />

    <!-- Generic confirm modal (batch explode, etc.) -->
    <ConfirmModal
      :show="confirmModalState.show"
      :title="confirmModalState.title"
      :message="confirmModalState.message"
      :confirm-text="confirmModalState.confirmText"
      cancel-text="Cancel"
      @confirm="resolveConfirm(true)"
      @cancel="resolveConfirm(false)"
    />

    <!-- Debug: Copy tool JSON button (lower right) - dev mode only -->
    <button
      v-if="tool && devModeRef"
      @click="copyToolJson"
      class="absolute bottom-4 right-4 p-1.5 rounded text-content-muted hover:text-purple-500 hover:bg-purple-500/10 transition-colors z-10"
      title="Copy tool JSON"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0 1 12 12.75Zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 0 1-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 0 0 2.248-2.354M12 12.75a2.25 2.25 0 0 1-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 0 0-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 0 1 .4-2.253M12 8.25a2.25 2.25 0 0 0-2.248 2.146M12 8.25a2.25 2.25 0 0 1 2.248 2.146M8.683 5a6.032 6.032 0 0 1-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0 1 15.318 5m0 0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 0 0-.575-1.752M4.921 6a24.048 24.048 0 0 0-.392 3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 0 1-5.223 1.082" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick, provide } from 'vue'
import { devModeRef, hidePricesRef } from '../appConfig'
import { usePromptMiniAgent } from '../composables/usePromptMiniAgent'
import { usePromptEditorUndo } from '../composables/usePromptEditorUndo'
import { PROMPT_EDITOR_AGENT_KEY } from '../composables/promptEditorAgentKey'

defineOptions({
  name: 'ToolView'
})

// Props from route - fullToolId is the provider tool ID
const props = defineProps<{
  fullToolId: string
}>()

import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { ArchiveBoxIcon, PhotoIcon } from '@heroicons/vue/24/outline'
import { useWebSocket } from '../composables/useWebSocket'
import { useGenerationPreferences } from '../composables/useGenerationPreferences'
import { useWorkspaceTabs, toolInstanceScopedId, toolInstanceRoute } from '../composables/useWorkspaceTabs'
import { useStimpacksApi, type Skill } from '../composables/useStimpacksApi'
import { useGenerationJobs } from '../composables/useGenerationJobs'
import { useGenerationStatus } from '../composables/useGenerationStatus'
import {
  buildBasePayload,
  buildCapturedState,
  getPreUploadTasks,
  hasPromptFeature,
  type PayloadBuilderState,
  type PayloadBuilderConfig,
} from '../composables/useJobPayloadBuilder'
import { submitJobAsync, submitBatchJobAsync, submitMediaBatchJobAsync, BatchJobResponse } from '../composables/useSubmissionQueue'
import { createDragPreview, handleDragEnd as handleHeroDragEnd } from '../composables/useDragPreview'
import { useToolAutoDeleteDuration } from '../composables/useToolAutoDeleteDuration'
import { usePromptWarmPool } from '../composables/usePromptWarmPool'
import { useTabNavigation } from '../composables/useTabNavigation'
import { useGlobalKeyboardShortcuts } from '../composables/useGlobalKeyboardShortcuts'
import { useMediaApi } from '../composables/useMediaApi'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { useToolState, type ToolState } from '../composables/useToolState'
import { usePresetsApi } from '../composables/usePresetsApi'
import { useToolSchemaFeatures } from '../composables/useToolSchemaFeatures'
import { useVideoFrameExtraction, type FramePosition } from '../composables/useVideoFrameExtraction'
import { useTelemetry } from '../composables/useTelemetry'
import { makeGlobalKey, makeToolDbKey } from '../utils/storageKeys'
import { snapDimsToGrid as snapDimsToSchemaGrid } from '../utils/resolutionControls'
import { getBlob, putBlob, deleteBlob } from '../utils/blobStorage'
import { getToolDefaults } from '../utils/generationDefaults'
import { parseGenerationConfig, type GenerationConfigUpdate } from '../utils/parseGenerationConfig'
import type { PromptMetadata } from '../types/generationMetadata'
import { formatRemainingTime } from '../utils/timeFormat'
import { isStimmaCloudTool as isStimmaCloud } from '../utils/stimmaCloud'
import { copyToClipboard } from '../utils/clipboard'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { formatTaskTypeLabel } from '../utils/taskTypeIcons'
import { addToast } from '../composables/useToasts'
import SlideshowMode from '../components/SlideshowMode.vue'
import CompareMode from '../components/CompareMode.vue'
import { useCompare } from '../composables/useCompare'
import ResolutionPicker from '../components/ResolutionPicker.vue'
import AutoDeletePicker from '../components/AutoDeletePicker.vue'
import ForeverModeButton from '../components/ForeverModeButton.vue'
import BatchRunButton from '../components/BatchRunButton.vue'
import ConnectionError from '../components/ConnectionError.vue'
import { MediaContextMenu, MediaImage } from '../components/media'
import { AudioPlayer } from '../components/viewers'
import {
  AIMaskAssistant,
  AIPromptEditor,
  ConstrainedResolutionPicker,
  GeminiResolutionPicker,
  JobErrorModal,
  JobInfoModal,
  LoraPoolPanel,
  MaskEditor,
  MaskEditorModal,
  MediaPicker,
  AutoMarkPicker,
  PresetPicker,
  MegapixelsPicker,
  UpscaleResolutionPicker
} from '../components/generation'
import type { MediaItem } from '../components/generation/MediaPicker.vue'
import ConfirmModal from '../components/ConfirmModal.vue'
import HopToToolMenu from '../components/HopToToolMenu.vue'
import ToolIcon from '../components/tools/ToolIcon.vue'
import FreezeToolDialog from '../components/flow/FreezeToolDialog.vue'
import { useFlowsApi } from '../composables/useFlowsApi'
import PostProcessingPanel from '../components/generation/postprocessing/PostProcessingPanel.vue'
import SchemaParamGroup from '../components/generation/SchemaParamGroup.vue'
import { resolveParamConstraints } from '../utils/paramConstraints'
import { CHAIN_TOOL_TASK_TYPES, defaultInsertIndex, emptyChain, mergeRecordedChain, newStepId, normalizeChain, stepInputMedia, stepAcceptedMedia, toRecordedSteps, type ChainStep, type PostProcessingChain } from '../utils/postProcessingChain'
import { CHAIN_FILTER_DEFS, getChainFilterDef, getChainFilterDefaults } from '@stimma/image-editor'
import RemixBanner from '../components/generation/RemixBanner.vue'
import PromptAgentChat from '../components/generation/PromptAgentChat.vue'
import JobsGrid from '../components/generation/JobsGrid.vue'
import SettingsDropdown from '../components/ui/SettingsDropdown.vue'
import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'
import { signInWithBrowser } from '../composables/useAuth'

const API_BASE = '/api'
const router = useRouter()
const route = useRoute()
const projectScopeId = computed(() => {
  const raw = route.query.project_id
  if (raw == null) return null
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = parseInt(String(value), 10)
  return Number.isFinite(parsed) ? parsed : null
})
// Instance discriminator — injected on every tool route by the router guard.
// Fixed for this component's lifetime (the KeepAlive key includes it, so a
// different instance mounts a different ToolView).
const instanceScopeId = (() => {
  const raw = route.query.instance
  if (raw == null) return null
  const value = Array.isArray(raw) ? raw[0] : raw
  return value ? String(value) : null
})()
// Layout mode: 'studio' = controls primary (default), 'stage' = current image
// primary with controls demoted to a rail. Persisted per-tool via uiState
// (makeToolProfileKey 'ui'), like imageMode — see useGenerationPreferences.
const layoutMode = computed<'studio' | 'stage'>({
  get: () => uiState.value.layoutMode,
  set: (v) => { uiState.value.layoutMode = v }
})
const queueThumbnailSize = computed(() => layoutMode.value === 'stage' ? 512 : 1024)

// Stage hero state. The hero shows the newest completed generation and follows
// new arrivals, unless the user has navigated/pinned to an older one (via ←/→ or
// by clicking a thumbnail in the queue strip). null pin = follow newest.
const stagePinnedMediaId = ref<number | null>(null)
const stageMenuOpen = ref(false)

// Width of the Stage controls sidebar, draggable via the seam. Default is ~20%
// wider than the old fixed 380px. Session-local (not persisted yet).
const stageControlsWidth = ref(456)
const stageResizing = ref(false)
let stageResizeStartX = 0
let stageResizeStartW = 0
function onStageResize(e: PointerEvent) {
  stageControlsWidth.value = Math.max(456, Math.min(760, stageResizeStartW + (e.clientX - stageResizeStartX)))
}
function endStageResize() {
  stageResizing.value = false
  window.removeEventListener('pointermove', onStageResize)
  window.removeEventListener('pointerup', endStageResize)
}
function startStageResize(e: PointerEvent) {
  stageResizing.value = true
  stageResizeStartX = e.clientX
  stageResizeStartW = stageControlsWidth.value
  window.addEventListener('pointermove', onStageResize)
  window.addEventListener('pointerup', endStageResize)
  e.preventDefault()
}
function generationJobParams(job: any): any {
  if (!job?.parameters) return null
  try { return JSON.parse(job.parameters) } catch { return null }
}

function isMediaBatchJob(job: any): boolean {
  return !!generationJobParams(job)?._batch_presentation_only
}

function generationBatchIndex(job: any): number {
  const value = generationJobParams(job)?._batch_index
  return Number.isFinite(value) ? Number(value) : Number.MAX_SAFE_INTEGER
}

function isVisibleStageJob(job: any): boolean {
  if (!job || job.status !== 'completed' || !job.result_media_id) return false
  return !!jobsManager?.mediaHashes.value?.[job.result_media_id]
}

function isMediaBatchComplete(batch: any): boolean {
  const jobs = batch?.jobs || []
  const total = batch?.total || jobs.length
  if (jobs.length < total) return false
  return jobs.length > 0 && jobs.every((job: any) =>
    job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled'
  )
}

// Stage navigation follows the visible rail reading order. Media-batch members
// are ordered by the backend's _batch_index, matching the source reference order,
// instead of completion time.
const stageCompletedJobs = computed<any[]>(() => {
  if (!jobsManager) return []

  const batchGroups = Object.values(jobsManager.batchJobs.value || {})
    .filter((batch: any) => (batch.jobs || []).some(isMediaBatchJob))
  const mediaBatchIds = new Set(batchGroups.map((batch: any) => batch.batch_id))
  const jobsInMediaBatch = new Set<number>()
  for (const batch of batchGroups as any[]) {
    for (const job of batch.jobs || []) jobsInMediaBatch.add(job.id)
  }

  const sortJobsInBatch = (jobs: any[]) => [...jobs]
    .filter(isVisibleStageJob)
    .sort((a, b) => {
      const byIndex = generationBatchIndex(a) - generationBatchIndex(b)
      if (byIndex !== 0) return byIndex
      return a.id - b.id
    })

  const activeBatchItems = batchGroups
    .filter((batch: any) => !isMediaBatchComplete(batch))
    .map((batch: any) => ({
      timestamp: new Date((batch.jobs || [])[0]?.created_at || Date.now()).getTime(),
      jobs: sortJobsInBatch(batch.jobs || []),
    }))
    .filter(item => item.jobs.length > 0)
    .sort((a, b) => b.timestamp - a.timestamp)

  const completedItems: Array<{ timestamp: number, jobs: any[] }> = []
  for (const batch of batchGroups as any[]) {
    if (!isMediaBatchComplete(batch)) continue
    const jobs = sortJobsInBatch(batch.jobs || [])
    if (jobs.length === 0) continue
    const latestCompleted = jobs.reduce((latest: number, job: any) =>
      Math.max(latest, new Date(job.completed_at || job.created_at || 0).getTime()), 0)
    completedItems.push({ timestamp: latestCompleted, jobs })
  }

  for (const job of jobsManager.sortedCompletedJobs.value || []) {
    if (jobsInMediaBatch.has(job.id)) continue
    if (job.batch_id && mediaBatchIds.has(job.batch_id)) continue
    if (!isVisibleStageJob(job)) continue
    completedItems.push({
      timestamp: new Date(job.completed_at || job.created_at || 0).getTime(),
      jobs: [job],
    })
  }

  completedItems.sort((a, b) => b.timestamp - a.timestamp)
  return [...activeBatchItems, ...completedItems].flatMap(item => item.jobs)
})
const stageHasPending = computed(() =>
  (allJobs.value || []).some((j: any) => ['enhancing', 'queued', 'assigned', 'processing'].includes(j.status))
)
const stageCurrentJob = computed<any | null>(() => {
  const list = stageCompletedJobs.value
  if (!list.length) return null
  if (stagePinnedMediaId.value != null) {
    const found = list.find((j: any) => j.result_media_id === stagePinnedMediaId.value)
    if (found) return found
  }
  return list[0] // newest
})
const stageCurrentMediaId = computed<number | null>(() => stageCurrentJob.value?.result_media_id ?? null)
const stageCurrentHash = computed<string | null>(() =>
  stageCurrentMediaId.value != null ? (jobsManager?.mediaHashes.value?.[stageCurrentMediaId.value] ?? null) : null
)

function onHeroDragStart(event: DragEvent) {
  const mediaId = stageCurrentMediaId.value
  if (mediaId == null) return
  createDragPreview(event, getThumbnailUrl(mediaId, 128), mediaId, undefined, true)
}
const stageGenerationTime = computed<number | null>(() => {
  if (stageCurrentMediaId.value == null) return null
  const time = jobsManager?.mediaGenerationTimes.value?.[stageCurrentMediaId.value]
  return time ? Math.round(time * 10) / 10 : null
})
const stageAutoDeleteTime = computed<string | null>(() => {
  const autoDeleteAt = stageCurrentJob.value?.auto_delete_at
  if (!autoDeleteAt) return null
  const remaining = formatRemainingTime(autoDeleteAt)
  return remaining && remaining !== '0m' ? remaining : null
})
const stageOnNewest = computed(() => {
  const list = stageCompletedJobs.value
  return !!stageCurrentJob.value && list.length > 0 && stageCurrentJob.value.id === list[0].id
})
const stageMarkers = computed(() => jobsManager?.availableMarkers.value || [])
function stageHasMarker(markerId: number): boolean {
  if (stageCurrentMediaId.value == null) return false
  const ms: any[] = jobsManager?.mediaMarkers.value?.[stageCurrentMediaId.value] || []
  return ms.some((m: any) => m.id === markerId)
}

// Clicking a thumbnail in the stage strip pins a completed job onto the hero;
// other statuses (e.g. failed) fall through to the normal click handler.
function stagePinJob(job: any) {
  if (job?.status === 'completed' && job.result_media_id) {
    stagePinnedMediaId.value = job.result_media_id
  } else {
    handleJobClick(job)
  }
}

// The queue rail is a single control across both modes — route clicks based on
// the active mode. Stage pins to the hero; Studio opens the slideshow.
function handleQueueClick(job: any) {
  if (layoutMode.value === 'stage') {
    stagePinJob(job)
  } else {
    handleJobClick(job)
  }
}

// ←/→ navigate the hero through completed jobs (newest at index 0). Right = older.
function stageNav(delta: number) {
  const list = stageCompletedJobs.value
  if (!list.length) return
  const curId = stageCurrentJob.value?.id
  let idx = list.findIndex((j: any) => j.id === curId)
  if (idx < 0) idx = 0
  const next = Math.max(0, Math.min(list.length - 1, idx + delta))
  stagePinnedMediaId.value = list[next].result_media_id
}
function stageKeydown(e: KeyboardEvent) {
  if (layoutMode.value !== 'stage' || slideshowState.active) return
  const ae = document.activeElement as HTMLElement | null
  if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable || ae.closest?.('.cm-editor'))) return
  if (e.key === 'ArrowRight' || e.key === 'd') { e.preventDefault(); stageNav(1) }
  else if (e.key === 'ArrowLeft' || e.key === 'a') { e.preventDefault(); stageNav(-1) }
  else if (e.key === 'Home') { e.preventDefault(); stageNav(-Infinity) }
  else if (e.key === 'End') { e.preventDefault(); stageNav(Infinity) }
}
onMounted(() => window.addEventListener('keydown', stageKeydown))
onUnmounted(() => window.removeEventListener('keydown', stageKeydown))

const { enterSlideshowMode, exitSlideshowMode, slideshowActive } = useTabNavigation()
const { getProviderTool, getToolState, saveToolState, refreshProviderTools, subscribeToProviderChanges, uploadToTool, fetchProvidersAndTools } = useProvidersApi()

// WebSocket subscription for provider status changes
let unsubscribeFromProviderChanges: (() => void) | null = null
let foreverModeUnsubscribers: Array<() => void> = []
const { getMediaItem, getMediaFileUrl, getThumbnailUrl, getProject } = useMediaApi()
const { compareState, enterCompare, exitCompare, swapImages: swapCompareImages } = useCompare()

// Tool data - now a provider tool with state
interface ToolWithState extends ProviderTool {
  state: Record<string, any>
  generator: string  // Alias for metadata.generator_name
  model: string      // Alias for metadata.model_name
}
const tool = ref<ToolWithState | null>(null)
const isInitialLoading = ref(true)
const error = ref<{ message: string; statusCode?: number } | null>(null)
const submissionError = ref<string | null>(null)
// Discriminator for the last submission error, e.g. 'subscription_required'
// (enhance-at-submit has no LLM entitlement) — drives the CTA shown beside
// the error text; never folded into the error string itself.
const submissionErrorCode = ref<string | null>(null)

function classifySubmissionError(err: any): string {
  const detail = err?.response?.data?.detail
  const code = typeof detail === 'object' ? detail?.code : null
  submissionErrorCode.value = code || null
  if (typeof detail === 'string') return detail
  return detail?.message || 'Failed to submit job'
}

const submissionCloudConnecting = ref(false)
async function connectStimmaCloudForSubmission() {
  submissionCloudConnecting.value = true
  try {
    await signInWithBrowser()
  } catch (err: any) {
    console.error('Failed to connect Stimma Cloud:', err)
  } finally {
    submissionCloudConnecting.value = false
  }
}
let loadRetryTimeout: ReturnType<typeof setTimeout> | null = null
let availabilityPollInterval: ReturnType<typeof setInterval> | null = null
const LOAD_RETRY_DELAY_MS = 1000
const AVAILABILITY_POLL_MS = 1000

// Flag to prevent loadPendingGeneration from re-running or being overwritten
const pendingGenerationApplied = ref(false)
// Loading state for async operations (e.g., LLM lora matching)
const loadingGenerationConfig = ref(false)

// Remix state - tracks which media item the current config was remixed from
const remixSource = ref<{
  mediaId: number
  promptSnippet: string
  renderedPrompt?: string  // expanded prompt (wildcards resolved)
  seed?: number | null      // seed from original generation for reproducibility
  // Enhance/translate settings the source image was generated with, so "Use
  // Prompt" can restore them (translate is only present for newer generations).
  promptMetadata?: PromptMetadata
} | null>(null)

// Debug: Copy tool JSON
async function copyToolJson() {
  if (!tool.value) return
  try {
    const response = await fetch(`/api/tools/provider-tool/${tool.value.full_tool_id}/raw-schema`)
    if (!response.ok) {
      throw new Error('Failed to fetch tool schema')
    }
    const data = await response.json()
    const jsonStr = JSON.stringify(data, null, 2)
    const success = await copyToClipboard(jsonStr)
    if (success) {
      addToast('Tool JSON copied to clipboard', 'success', 2000)
    }
  } catch (err) {
    console.error('Failed to copy tool JSON:', err)
    addToast('Failed to copy tool JSON', 'error', 3000)
  }
}

// Note: inline param editing now lives in SchemaParamGroup

// Tool availability computed properties
const toolAvailability = computed(() => tool.value?.availability || 'available')
const providerDisplayName = computed(() => tool.value?.provider_name || tool.value?.provider_id || 'Provider')
const toolDisplayName = computed(() => tool.value?.name || 'this tool')
const isStimmaCloudTool = computed(() => isStimmaCloud(tool.value))

// True when the selected tool is Ideogram 4 — gates the prompt editor's JSON
// mode (Ideogram 4 is trained on structured JSON captions). The Ideogram 4 tool
// registers model_vendor 'ideogram' with model 'ideogram:4@0' / name 'Ideogram 4.0'.
const isIdeogram4 = computed(() => {
  const t = tool.value
  if (!t) return false
  const vendor = (t.model_vendor || (t.metadata as any)?.model_vendor || '').toLowerCase()
  if (vendor !== 'ideogram') return false
  const model = (t.model || (t.metadata as any)?.model_name || t.name || '').toLowerCase()
  return /ideogram[\s:_-]*v?4(\b|@|\.0|$)/.test(model) || model.includes('ideogram:4')
})

// The tool's model string — sent to the enhance endpoint, which classifies it
// server-side (model_family) to pick the enhancement style. Raw string stays local.
const toolModelString = computed<string>(() => {
  const t = tool.value
  if (!t) return ''
  return (t.model || (t.metadata as any)?.model_name || t.name || '') as string
})

// Enhance Prompt routing: Ideogram converts to structured JSON (post-resolve, so
// wildcards are expanded and the real canvas is known); every other model gets a
// text rewrite (pre-resolve) whose concrete style the backend picks by family.
const enhanceMode = computed<'text' | 'ideogram-json'>(() =>
  isIdeogram4.value ? 'ideogram-json' : 'text'
)

// ----- User (frozen-flow) tool editing -----
// A tool the user made by freezing a flow. These are editable in place here so
// the tool's own page is the obvious place to find "edit this tool".
const isUserTool = computed(
  () =>
    tool.value?.provider_id === 'user-tools' ||
    (tool.value?.metadata as any)?.provenance === 'user-flow',
)
const userToolId = computed<number | null>(() => {
  const id = (tool.value?.metadata as any)?.user_tool_id
  return id != null ? Number(id) : null
})

const { getFlow } = useFlowsApi()
const editToolDialogOpen = ref(false)
const editingToolRow = ref<any | null>(null)
const editingFlowOutputNames = ref<string[]>([])
const editingFlowName = ref<string | null>(null)

async function openEditUserTool() {
  const id = userToolId.value
  if (id == null) return
  try {
    const base = getApiBase()
    const resp = await axios.get(`${base}/user-tools/${id}`)
    const row = resp.data
    // Derive the backing flow's declared output names for the binding select.
    let outputNames: string[] = []
    editingFlowName.value = null
    if (row?.flow_id != null) {
      try {
        const flow: any = await getFlow(row.flow_id)
        editingFlowName.value = flow?.name || null
        const schema = flow?.output_schema
        if (schema && typeof schema === 'object') {
          const props = schema.properties && typeof schema.properties === 'object' ? schema.properties : schema
          outputNames = Object.keys(props).filter((k) => !['type', 'properties', 'required'].includes(k))
        }
      } catch (_) { /* non-fatal */ }
    }
    for (const v of Object.values(row?.output_map || {})) {
      if (v && !outputNames.includes(v as string)) outputNames.push(v as string)
    }
    editingFlowOutputNames.value = outputNames
    editingToolRow.value = row
    editToolDialogOpen.value = true
  } catch (err) {
    addToast('Could not load tool for editing', 'error', 5000)
  }
}

async function onUserToolEdited() {
  editToolDialogOpen.value = false
  editingToolRow.value = null
  try { await fetchProvidersAndTools(true) } catch (_) { /* best-effort */ }
}

function onUserToolDeleted() {
  editToolDialogOpen.value = false
  editingToolRow.value = null
  fetchProvidersAndTools(true).catch(() => {})
  // The tool no longer exists — leave its page.
  router.push({ name: 'all-tools' }).catch(() => {})
}

function onEditOpenBackingFlow(flowId: number | string) {
  editToolDialogOpen.value = false
  router.push({ name: 'flow', params: { id: String(flowId) } }).catch(() => {})
}

// Format task types for display (e.g., "text-to-image" -> "Text to Image")
const taskTypesDisplay = computed(() => {
  const taskTypes = tool.value?.task_types
  if (!taskTypes || taskTypes.length === 0) return null
  return taskTypes
    .map(t => formatTaskTypeLabel(t))
    .join(' · ')
})

const unavailableTitle = computed(() => {
  return `${providerDisplayName.value} Is Unavailable`
})

const unavailableSubtitle = computed(() => {
  if (toolAvailability.value === 'disconnected' || toolAvailability.value === 'unconfigured') {
    return `You will not be able to use ${toolDisplayName.value} until it re-connects.`
  }
  return ''
})

// Note: SPECIAL_PARAM_NAMES, genericParams, groupedGenericParams moved to useToolSchemaFeatures

// Generator type detection - uses tool.metadata
const selectedGeneratorInfo = computed(() => {
  if (!tool.value?.metadata) return null
  return {
    type: tool.value.metadata.generator_type,
    name: tool.value.metadata.generator_name,
  }
})

const projectScopeName = ref('Untitled Project')

watch(projectScopeId, async (projectId) => {
  if (projectId == null) {
    projectScopeName.value = 'Untitled Project'
    return
  }

  try {
    const project = await getProject(projectId)
    projectScopeName.value = project?.name?.trim() || 'Untitled Project'
  } catch (err) {
    console.warn('Failed to load project scope name:', err)
    projectScopeName.value = 'Untitled Project'
  }
}, { immediate: true })

// Note: Schema-driven feature detection moved to useToolSchemaFeatures composable
// (hasWidthHeight, hasAspectRatio, hasMegapixels, hasPrompt, mediaInputConfig, etc.)

// Auto-select nearest aspect ratio when image is added
function aspectRatioToDecimal(ar: string): number {
  const [w, h] = ar.split(':').map(Number)
  return w / h
}

function findNearestAspectRatio(width: number, height: number): string {
  const choices = aspectRatioChoices.value
  if (choices.length === 0) return '1:1'

  const imageAspect = width / height
  let nearestAR = choices[0]
  let smallestDiff = Infinity

  for (const ar of choices) {
    const arDecimal = aspectRatioToDecimal(ar)
    const diff = Math.abs(imageAspect - arDecimal)
    if (diff < smallestDiff) {
      smallestDiff = diff
      nearestAR = ar
    }
  }

  return nearestAR
}

// Computed getter for media input items — keyed by which parameter_schema
// property (and matching globalPrefs array) this slot is, NOT by accept type:
// a video-only filter still uses the input_images slot/param, just narrowed
// to video via x-accept-media (see MediaInputConfig.paramKey).
const mediaInputItems = computed(() => {
  if (!mediaInputConfig.value) return []
  return mediaInputConfig.value.paramKey === 'input_images'
    ? globalPrefs.value.inputImages
    : globalPrefs.value.inputVideos
})

// Update handler for media input items
function updateMediaInputItems(items: any[]) {
  if (!mediaInputConfig.value) return
  if (mediaInputConfig.value.paramKey === 'input_images') {
    globalPrefs.value.inputImages = items
  } else {
    globalPrefs.value.inputVideos = items
  }
  // Leaving an empty batch slot drops back to ordinary single-input mode.
  if (globalPrefs.value.batchMode && items.length === 0) {
    globalPrefs.value.batchMode = false
  }
}

// Reference audio is its own input section (audio-conditioned tools); it has a
// dedicated picker and state slot, independent of the visual input above.
const audioInputItems = computed(() => {
  if (!audioInputConfig.value) return []
  return globalPrefs.value.inputAudios
})

function updateAudioInputItems(items: any[]) {
  if (!audioInputConfig.value) return
  globalPrefs.value.inputAudios = items
}

// Explode a batch into ordinary reference items: keep what the slot can hold,
// and apply the batch's image adjustments to each kept item. Items are only
// dropped if the batch is larger than the input can hold; that's the only case
// worth a warning.
async function explodeBatch() {
  const max = mediaInputConfig.value?.max ?? 1
  const items = mediaInputItems.value
  const n = items.length
  const dropped = Math.max(0, n - max)

  const message = dropped > 0
    ? `This batch has ${n} images but this input only holds ${max}. Exploding keeps the first ${max} as separate reference images and drops the other ${dropped}.`
    : `Turn this batch into ${n} separate reference image${n === 1 ? '' : 's'} with the same image adjustments.`
  const ok = await confirmModal({
    title: 'Explode batch',
    message,
    confirmText: 'Explode',
  })
  if (!ok) return

  // Carry the batch's uniform prep (set on the representative) onto every kept
  // item. The representative is already processed; the others get the prep
  // metadata and MediaPicker's watcher applies it to each.
  const rep: any = items[0] || {}
  const prepFields = {
    _scale: rep._scale ?? null,
    _flip: rep._flip ?? null,
    _crop: rep._crop ?? null,
    _preprocessor: rep._preprocessor ?? null,
    _preprocessorParams: rep._preprocessorParams ?? null,
    _extendPadding: rep._extendPadding ?? null,
    _extendBgColor: rep._extendBgColor ?? null,
  }
  const kept = items.slice(0, max).map((it: any, idx: number) =>
    idx === 0 ? it : { ...it, ...prepFields }
  )
  globalPrefs.value.batchMode = false
  updateMediaInputItems(kept)
}

// Lightweight promise-based confirm modal (no browser alert/confirm sheets).
const confirmModalState = ref<{ show: boolean; title: string; message: string; confirmText: string }>({
  show: false, title: '', message: '', confirmText: 'Confirm',
})
let confirmResolver: ((ok: boolean) => void) | null = null
function confirmModal(opts: { title: string; message: string; confirmText?: string }): Promise<boolean> {
  confirmModalState.value = {
    show: true, title: opts.title, message: opts.message, confirmText: opts.confirmText || 'Confirm',
  }
  return new Promise<boolean>((resolve) => { confirmResolver = resolve })
}
function resolveConfirm(ok: boolean) {
  confirmModalState.value = { ...confirmModalState.value, show: false }
  confirmResolver?.(ok)
  confirmResolver = null
}

// Video frame images for image-to-video (initialized after toolId is available).
// Typed as MediaItem so the slots can carry dimensions + prep metadata (scale,
// flip, extend, paint, preprocess) just like ordinary reference images.
const videoImages = reactive({
  startImage: null as MediaItem | null,
  endImage: null as MediaItem | null
})

// Bridge between the named-slot picker (an ordered MediaItem[] — index 0 = start,
// index 1 = end) and videoImages, which stays the source of truth for the i2v
// generation / remix / enhancer paths. frameItems compacts to non-empty slots so
// a lone image always reads as the start frame.
const frameItems = computed<MediaItem[]>(() => {
  const out: MediaItem[] = []
  if (videoImages.startImage) out.push(videoImages.startImage)
  if (videoImages.endImage) out.push(videoImages.endImage)
  return out
})

function updateFrameItems(items: MediaItem[]) {
  videoImages.startImage = items[0] ? { ...items[0] } : null
  videoImages.endImage = items[1] ? { ...items[1] } : null
}

// Inpaint mask data URL
const maskDataUrl = ref<string | null>(null)

// Ref for MaskEditor (used by AI mask assistant)
const maskEditorRef = ref<InstanceType<typeof MaskEditor> | null>(null)

// Mask editor modal state
const maskEditorModalOpen = ref(false)

// Note: inpaint/outpaint settings are now stored directly in modelParams
// using snake_case keys from the schema (e.g., context_expand_factor, mask_blend_pixels)

// Note: hasVideoFrames, hasMask, hasLoras, hasScaleFactor, hasUpscaleResolution, showUpscalePicker, hasResolution, hasFrameCount, outputsVideo, isFromScratch
// are now provided by useToolSchemaFeatures composable

// Note: generic-param formatting/editing helpers now live in SchemaParamGroup

// Note: promptPlaceholder is now provided by useToolSchemaFeatures composable

// Video-specific computed properties
const frameCountConfig = computed(() => {
  const props = tool.value?.parameter_schema?.properties || {}
  const schema = props.frame_count
  if (schema) {
    return {
      min: schema.minimum ?? 1,
      max: schema.maximum ?? 161,
      default: schema.default ?? 81,
    }
  }
  return { min: 1, max: 161, default: 81 }
})

// durationConfig / hasFps / fpsOptions now come from useToolSchemaFeatures
// (shared with ChainStepSettings.vue) — see the destructure below.

const estimatedDuration = computed(() => {
  // If tool uses duration param directly, use it
  if (modelParams.value.duration) {
    return Number(modelParams.value.duration).toFixed(1)
  }
  // Fall back to frames/fps calculation for frame_count-based tools
  const fps = modelParams.value.fps || 16
  const frames = modelParams.value.frameCount || 81
  return (frames / fps).toFixed(1)
})

// Note: State management (buildToolState, applyToolState, saveStateToLocalStorage, etc.)
// is now provided by useToolState composable

// Data from API
const outputFolder = ref<string | null>(null)

// Get fullToolId from props - this is constant for this component instance
// (each tool gets its own KeepAlive'd component instance via unique key)
const fullToolIdFromProps = props.fullToolId || ''
// Create a storage-safe ID (replace colons with underscores)
// Include project scope for project-scoped tool instances, then the instance
// suffix — every tool tab is an instance with fully independent state.
const ownProjectScopeId = projectScopeId.value
const projectSuffix = ownProjectScopeId ? `__project_${ownProjectScopeId}` : ''
const instanceSuffix = instanceScopeId ? `__i_${instanceScopeId}` : ''
const toolIdForStorage = fullToolIdFromProps.replace(/:/g, '_') + projectSuffix + instanceSuffix

// True when the CURRENT route addresses this exact component (tool + project
// + instance). KeepAlive keeps deactivated ToolViews' watchers live, and two
// instances of the same tool must not both consume a query-param handoff.
function isMyToolRoute(): boolean {
  if (route.name !== 'tool' || route.params.fullToolId !== fullToolIdFromProps) return false
  const rawProj = route.query.project_id
  const routeProj = rawProj == null ? null : parseInt(String(Array.isArray(rawProj) ? rawProj[0] : rawProj), 10) || null
  if ((ownProjectScopeId ?? null) !== routeProj) return false
  const rawInst = route.query.instance
  const routeInst = rawInst == null ? null : String(Array.isArray(rawInst) ? rawInst[0] : rawInst)
  return routeInst === instanceScopeId
}

function buildToolWithState(providerTool: ProviderTool, state: Record<string, any> = {}): ToolWithState {
  const derivedGenerator = providerTool.metadata?.generator_name ||
    (providerTool.provider_id.startsWith('builtin:')
      ? providerTool.provider_id.split(':')[1]
      : providerTool.provider_id)

  return {
    ...providerTool,
    state,
    generator: derivedGenerator,
    model: providerTool.metadata?.model_name || providerTool.name,
  }
}

function scheduleLoadRetry() {
  if (loadRetryTimeout) return
  loadRetryTimeout = setTimeout(async () => {
    loadRetryTimeout = null
    // Silent: keep the error state on screen while we reconnect in the
    // background instead of flickering the full-screen spinner each cycle.
    await loadTool(true, true)
  }, LOAD_RETRY_DELAY_MS)
}

function stopAvailabilityPolling() {
  if (availabilityPollInterval) {
    clearInterval(availabilityPollInterval)
    availabilityPollInterval = null
  }
}

function startAvailabilityPolling() {
  if (availabilityPollInterval || !tool.value) return
  availabilityPollInterval = setInterval(async () => {
    if (!tool.value || tool.value.availability === 'available') {
      stopAvailabilityPolling()
      return
    }
    try {
      const refreshedTool = await getProviderTool(tool.value.full_tool_id)
      tool.value = buildToolWithState(refreshedTool, tool.value.state || {})
      if (refreshedTool.availability === 'available') {
        stopAvailabilityPolling()
      }
    } catch {
      // Keep polling until provider reconnects
    }
  }, AVAILABILITY_POLL_MS)
}

// Browser GUID to ensure unique generator instance IDs
// Store in localStorage so job history persists across browser restarts
const browserGuidKey = makeGlobalKey('browser_guid')
let tabGuid = localStorage.getItem(browserGuidKey)
if (!tabGuid) {
  tabGuid = crypto.randomUUID()
  localStorage.setItem(browserGuidKey, tabGuid)
}

// Generator instance ID for this tool (unique per tool instance AND browser).
// Use @@ as separator to avoid ambiguity with hyphens in tool IDs (e.g., nano-banana vs nano-banana-edit).
// Tabs migrated from the pre-instance format carry a legacy (unsuffixed)
// feedScope so their job-feed history stays attached — prefer it when present.
const _tabsForFeed = useWorkspaceTabs()
const _feedTab = instanceScopeId ? _tabsForFeed.getToolInstanceTab(fullToolIdFromProps, projectScopeId.value, instanceScopeId) : undefined
const generatorInstanceId = `tool-${_feedTab?.feedScope || toolIdForStorage}@@${tabGuid}`

// This instance's workspace tab (reactive — carries customName for the
// header title, updated by renames from here or the sidebar).
const ownTab = computed(() => instanceScopeId
  ? _tabsForFeed.getToolInstanceTab(fullToolIdFromProps, ownProjectScopeId, instanceScopeId)
  : undefined)
const instanceCustomName = computed(() => ownTab.value?.customName || null)

function renameInstance(name: string | null) {
  if (ownTab.value) _tabsForFeed.updateTabCustomName(ownTab.value.id, name)
}

// Scoped tool ID for localStorage keys (project suffix + instance suffix)
function scopedToolId(fullToolId: string): string {
  return fullToolId + projectSuffix + instanceSuffix
}

// Load saved video images for this tool (persistence for image-to-video)
function getVideoImagesKey(fullToolId: string) {
  return makeToolDbKey(scopedToolId(fullToolId), 'video_images')
}

function loadVideoImages() {
  if (!tool.value) return
  const savedVideoImages = localStorage.getItem(getVideoImagesKey(tool.value.full_tool_id))
  if (savedVideoImages) {
    try {
      const parsed = JSON.parse(savedVideoImages)
      // Slots are ordered (start first). An end frame with no start — possible
      // under the old independent-slots picker — collapses up to the start slot.
      videoImages.startImage = parsed.startImage || parsed.endImage || null
      videoImages.endImage = parsed.startImage ? (parsed.endImage || null) : null
    } catch (e) {
      console.error('Failed to parse saved video images:', e)
    }
  } else {
    // Clear when switching to a tool with no saved video images
    videoImages.startImage = null
    videoImages.endImage = null
  }
}

// Save video images to localStorage when they change
watch(videoImages, (newImages) => {
  if (tool.value) {
    localStorage.setItem(getVideoImagesKey(tool.value.full_tool_id), JSON.stringify(newImages))
  }
}, { deep: true })

// Persist remix source to localStorage per-tool
function getRemixKey(fullToolId: string) {
  return makeToolDbKey(scopedToolId(fullToolId), 'remix')
}

function loadRemixState() {
  if (!tool.value) return
  const saved = localStorage.getItem(getRemixKey(tool.value.full_tool_id))
  if (saved) {
    try {
      remixSource.value = JSON.parse(saved)
    } catch (e) {
      console.error('Failed to parse saved remix source:', e)
      remixSource.value = null
    }
  } else {
    remixSource.value = null
  }
}

watch(remixSource, (newVal) => {
  if (tool.value) {
    if (newVal) {
      localStorage.setItem(getRemixKey(tool.value.full_tool_id), JSON.stringify(newVal))
    } else {
      localStorage.removeItem(getRemixKey(tool.value.full_tool_id))
    }
  }
})

// Auto-deactivate remix when the user makes a major prompt change.
// Gradual drift is fine — we only fire when the prompt shifts drastically in one go
// (e.g. clearing it, pasting something entirely new, or replacing 80%+ at once).
const remixPromptBaseline = ref<string | null>(null)
const REMIX_DEACTIVATE_THRESHOLD = 0.75  // 75% word-set difference triggers deactivation
const dismissedRemix = ref<{ mediaId: number; promptSnippet: string; renderedPrompt?: string; seed?: number | null; promptMetadata?: PromptMetadata } | null>(null)
let remixDeactivateSuppressedUntil = 0  // timestamp — detection suppressed until this time

// When remix is set, snapshot the current prompt as the baseline.
// When remix is cleared, drop the baseline.
watch(remixSource, (src) => {
  if (src) {
    remixPromptBaseline.value = globalPrefs.value.prompt
    dismissedRemix.value = null  // Clear any dismissed interstitial when a real remix is active
  } else {
    remixPromptBaseline.value = null
  }
})

// Suppress deactivation detection and re-baseline (used after remix-initiated prompt changes)
function suppressRemixDeactivation(durationMs = 30000) {
  remixDeactivateSuppressedUntil = Date.now() + durationMs
  // Also re-baseline so the new prompt is the reference point going forward
  remixPromptBaseline.value = globalPrefs.value.prompt
}

function calculateWordSetDifference(a: string, b: string): number {
  if (!a && !b) return 0
  if (!a || !b) return 1
  const words = (s: string) => new Set(s.toLowerCase().split(/\s+/).filter(w => w.length > 2))
  const setA = words(a)
  const setB = words(b)
  if (setA.size === 0 && setB.size === 0) return 0
  if (setA.size === 0 || setB.size === 0) return 1
  const intersection = [...setA].filter(w => setB.has(w)).length
  const union = new Set([...setA, ...setB]).size
  return union > 0 ? 1 - (intersection / union) : 1
}

let remixDeactivateTimer: ReturnType<typeof setTimeout> | null = null

// Caps the displayed "active" job count to generate-forever's concurrency
// (set up below, once uiState exists) - passed as a ref since uiState isn't
// defined yet at this point in setup. Null/unset (manual generation, forever
// mode off) leaves the active list uncapped.
const activeJobsCap = ref<number | null>(null)

// Job management composable - called at top level
// This MUST be called synchronously during setup, not in an async function
// taskType will be null initially, but jobs are filtered by generatorInstanceId anyway
const jobsManager = useGenerationJobs({
  taskType: null,  // We filter by generatorInstanceId instead
  generatorInstanceId: generatorInstanceId,
  activeCap: activeJobsCap
})
const { beginInstanceWork } = useGenerationStatus()

// Generation preferences composable - called at TOP LEVEL during setup
// taskType is a placeholder - the real key is toolId which creates tool-specific storage
// We use 'text-to-image' as default taskType just to get proper defaults structure
const {
  globalPrefs,
  modelParams,
  uiState,
  preferencesLoaded,
  onGeneratorChanged,
  onModelChanged,
  saveModelParams,
  loadUIState,
  flushPendingSaves: flushGenerationPreferenceSaves,
} = useGenerationPreferences({
  taskType: 'text-to-image',  // Just for defaults structure - we manage our own state persistence
  // Instance-scoped: prompt/inputs (_global) and layout/batch (_ui) belong to
  // this tab, not the tool. (Pre-instance these leaked across project scopes.)
  fullToolId: scopedToolId(fullToolIdFromProps)
})

watch(
  () => uiState.value.generateForeverMode ? uiState.value.generateForeverConcurrency : null,
  (cap) => { activeJobsCap.value = cap ?? null },
  { immediate: true }
)

// --- Video dropped into an image slot → grab a still (centralized safety net) ---
// MediaPicker converts videos it accepts directly, but a video can reach an
// image-intent slot from other paths too: Send-to-Tool, restore/remix, and (in the
// Tauri app) native OS drags that bypass MediaPicker's browser handlers. This watcher
// (placed after globalPrefs is defined — its getter runs synchronously) normalizes
// ANY video that lands in an image-intent slot into a captured frame, so an
// image-only tool only ever receives an image. Skipped when the input_images slot is
// actually video-only (accept === 'video', e.g. the reverse filter) — see
// inputImagesSlotWantsStills — since that tool wants the whole video, not a frame.
// Role-aware default: generic inputs use the first frame; the i2v Start frame uses
// the source's LAST frame (extend forward) and the End frame its FIRST (connect
// into). If a frame can't be grabbed (e.g. an undecodable format), the entry is
// dropped with a message rather than left to crash the tool at run time.
const { extractFrame } = useVideoFrameExtraction()
const VIDEO_INPUT_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']

function isVideoInputEntry(entry: any): boolean {
  if (!entry || entry._videoSource) return false  // null, or already a grabbed still
  const name = String(entry.filename || entry.path || '').toLowerCase()
  const ext = name.split('.').pop()
  return !!ext && VIDEO_INPUT_EXTENSIONS.includes(ext)
}

async function grabFrameForEntry(entry: any, position: FramePosition): Promise<MediaItem> {
  // Server-side extract from the entry's video path (library original or reference
  // copy). The backend validates the path against allowed media dirs.
  if (!entry.path) throw new Error('No source available for this video.')
  const ext = await extractFrame({ sourcePath: entry.path, position })
  return {
    path: ext.path,
    filename: ext.filename,
    width: ext.width,
    height: ext.height,
    _videoSource: {
      mediaId: entry.mediaId,
      hash: entry.hash,
      filename: entry.filename || 'video',
      duration: ext.duration,
      fps: ext.fps,
      sourcePath: entry.path,
    },
    _frameTime: ext.time,
    _framePosition: position,
  }
}

// A video-only input_images slot (e.g. the reverse filter, x-accept-media:
// ['video']) stores its item in globalPrefs.inputImages too — paramKey and
// accept diverge there (see MediaInputConfig.paramKey) — so this safety net
// must not grab a frame for it; the tool wants the whole video.
function inputImagesSlotWantsStills(): boolean {
  return mediaInputConfig.value?.accept !== 'video'
}

function hasPendingVideoInput(): boolean {
  const imgs = (globalPrefs.value.inputImages || []) as MediaItem[]
  return (inputImagesSlotWantsStills() && imgs.some(isVideoInputEntry))
    || isVideoInputEntry(videoImages.startImage)
    || isVideoInputEntry(videoImages.endImage)
}

// In-flight guard doubles as a handle the submit path can await, so a fast Run
// can't beat the grab and ship a raw video.
let videoNormalizeInFlight: Promise<void> | null = null
function normalizeVideoInputsToFrames(): Promise<void> {
  if (videoNormalizeInFlight) return videoNormalizeInFlight
  if (!hasPendingVideoInput()) return Promise.resolve()

  const run = async () => {
    const imgs = (globalPrefs.value.inputImages || []) as MediaItem[]
    if (inputImagesSlotWantsStills() && imgs.some(isVideoInputEntry)) {
      // Rebuild the array, replacing videos with grabbed stills and dropping any we
      // can't read (so we never leave a video in an image slot, and never re-loop).
      const next: MediaItem[] = []
      for (const entry of imgs) {
        if (!isVideoInputEntry(entry)) { next.push(entry); continue }
        try {
          next.push(await grabFrameForEntry(entry, 'first'))
        } catch (e: any) {
          console.error('Frame grab failed:', e)
          addToast(e?.response?.data?.detail || e?.message || "Couldn't grab a frame from that video.", 'error')
        }
      }
      globalPrefs.value.inputImages = next
    }
    if (isVideoInputEntry(videoImages.startImage)) {
      try {
        videoImages.startImage = await grabFrameForEntry(videoImages.startImage as MediaItem, 'last')
      } catch (e: any) {
        console.error('Frame grab failed (start):', e)
        addToast(e?.response?.data?.detail || e?.message || "Couldn't grab a frame from that video.", 'error')
        videoImages.startImage = null
      }
    }
    if (isVideoInputEntry(videoImages.endImage)) {
      try {
        videoImages.endImage = await grabFrameForEntry(videoImages.endImage as MediaItem, 'first')
      } catch (e: any) {
        console.error('Frame grab failed (end):', e)
        addToast(e?.response?.data?.detail || e?.message || "Couldn't grab a frame from that video.", 'error')
        videoImages.endImage = null
      }
    }
  }

  videoNormalizeInFlight = run().finally(() => { videoNormalizeInFlight = null })
  return videoNormalizeInFlight
}

watch(
  () => [globalPrefs.value.inputImages, videoImages.startImage, videoImages.endImage],
  () => { normalizeVideoInputsToFrames() },
  { deep: true }
)

// Auto-deactivate remix on major prompt change (watcher must be after globalPrefs is defined)
watch(globalPrefs, () => {
  const newPrompt = globalPrefs.value.prompt
  if (!remixSource.value || remixPromptBaseline.value === null) return
  if (newPrompt === remixPromptBaseline.value) return
  // Skip during suppression window (after restore or remix-initiated prompt changes)
  if (Date.now() < remixDeactivateSuppressedUntil) {
    remixPromptBaseline.value = newPrompt
    return
  }

  if (remixDeactivateTimer) clearTimeout(remixDeactivateTimer)

  remixDeactivateTimer = setTimeout(() => {
    remixDeactivateTimer = null
    if (!remixSource.value || remixPromptBaseline.value === null) return
    // Re-check suppression inside the timeout too
    if (Date.now() < remixDeactivateSuppressedUntil) {
      remixPromptBaseline.value = globalPrefs.value.prompt
      return
    }

    const currentPrompt = globalPrefs.value.prompt
    const diff = calculateWordSetDifference(currentPrompt, remixPromptBaseline.value)
    if (diff >= REMIX_DEACTIVATE_THRESHOLD) {
      // Stash the remix for the dismissed interstitial, then clear active remix
      dismissedRemix.value = { ...remixSource.value }
      remixSource.value = null
    } else {
      remixPromptBaseline.value = currentPrompt
    }
  }, 600)
}, { deep: true })

// Inpaint source image (first image from inputImages)
const inpaintSourceImage = computed(() => {
  if (!globalPrefs.value.inputImages?.length) return null
  return globalPrefs.value.inputImages[0] || null
})

// Handle image update from MaskEditor
function handleInpaintImageUpdate(image: { path: string; filename?: string; hash?: string; mediaId?: number } | null) {
  if (image) {
    globalPrefs.value.inputImages = [image]
  } else {
    globalPrefs.value.inputImages = []
  }
}

// Persist mask + paint-layer data URLs to IndexedDB (too large for localStorage).
// Keys are tool-scoped + db_guid-scoped so they don't leak across profiles/reinstalls.
const maskStorageKey = computed(() => tool.value ? makeToolDbKey(scopedToolId(tool.value.full_tool_id), 'mask') : null)

// Track if we've ever had a mask in this session (to avoid clearing on initial load)
const hadMaskInSession = ref(false)
let maskPersistTimeout: ReturnType<typeof setTimeout> | null = null

// Watch maskDataUrl changes and persist (debounced)
watch([maskDataUrl, inpaintSourceImage], ([newMask, newImage], [oldMask]) => {
  const key = maskStorageKey.value
  if (!key) return

  if (maskPersistTimeout) {
    clearTimeout(maskPersistTimeout)
    maskPersistTimeout = null
  }

  if (newMask && newImage?.path) {
    hadMaskInSession.value = true
    const imagePath = newImage.path
    maskPersistTimeout = setTimeout(() => {
      putBlob(key, { mask: newMask, imagePath }).catch(() => { /* ignore */ })
    }, 300)
  } else if (!newMask && (oldMask || hadMaskInSession.value)) {
    deleteBlob(key).catch(() => { /* ignore */ })
    hadMaskInSession.value = false
  }
})

// Load persisted mask when tool changes (only if image path matches)
watch([() => tool.value?.full_tool_id, inpaintSourceImage], async ([newFullToolId, currentImage]) => {
  if (!newFullToolId) return
  const key = makeToolDbKey(scopedToolId(newFullToolId), 'mask')
  const stored = await getBlob<{ mask: string; imagePath: string }>(key).catch(() => null)
  // Bail if tool switched under us while the async load was in flight
  if (tool.value?.full_tool_id !== newFullToolId) return

  if (stored) {
    if (stored.imagePath === currentImage?.path) {
      hadMaskInSession.value = true
      maskDataUrl.value = stored.mask
    } else if (currentImage?.path) {
      // Image is different from when mask was painted, clear it
      deleteBlob(key).catch(() => { /* ignore */ })
      maskDataUrl.value = null
    }
    // If currentImage is null/undefined, don't clear yet - wait for it to load
  } else if (currentImage?.path) {
    maskDataUrl.value = null
  }
}, { immediate: true })

// --- Paint layer persistence (per image slot, like mask) ---
// Paint layers are large data URLs that must NOT be stored in globalPrefs (quota risk).
// Each slot's paint layer is stored separately in IndexedDB keyed by tool + slot index.

let paintPersistTimeouts: Record<number, ReturnType<typeof setTimeout>> = {}

function getPaintStorageKey(slotIndex: number): string | null {
  if (!tool.value) return null
  return makeToolDbKey(scopedToolId(tool.value.full_tool_id), 'paint', slotIndex)
}

// Watch inputImages for paint layer changes and persist each slot separately
watch(() => globalPrefs.value.inputImages.map((img: any) => ({
  paintLayerDataUrl: img._paintLayerDataUrl,
  path: img._originalPath || img.path,
})), (newSlots, oldSlots) => {
  if (!tool.value) return
  for (let i = 0; i < newSlots.length; i++) {
    const slot = newSlots[i]
    const oldSlot = oldSlots?.[i]
    if (slot.paintLayerDataUrl === oldSlot?.paintLayerDataUrl) continue

    const key = getPaintStorageKey(i)
    if (!key) continue

    if (paintPersistTimeouts[i]) {
      clearTimeout(paintPersistTimeouts[i])
    }

    if (slot.paintLayerDataUrl && slot.path) {
      const paint = slot.paintLayerDataUrl
      const imagePath = slot.path
      paintPersistTimeouts[i] = setTimeout(() => {
        putBlob(key, { paint, imagePath }).catch(() => { /* ignore */ })
      }, 300)
    } else if (!slot.paintLayerDataUrl) {
      deleteBlob(key).catch(() => { /* ignore */ })
    }
  }

  // Clean up slots that no longer exist
  if (oldSlots && oldSlots.length > newSlots.length) {
    for (let i = newSlots.length; i < oldSlots.length; i++) {
      const key = getPaintStorageKey(i)
      if (key) deleteBlob(key).catch(() => { /* ignore */ })
    }
  }
}, { deep: true })

// Restore paint layers from dedicated storage — called after initializeState
async function restorePaintLayers() {
  if (!tool.value) return
  const fullToolId = tool.value.full_tool_id
  const images = globalPrefs.value.inputImages
  if (!images?.length) return

  let anyRestored = false
  for (let i = 0; i < images.length; i++) {
    if (images[i]._paintLayerDataUrl) continue

    const key = makeToolDbKey(scopedToolId(fullToolId), 'paint', i)
    const stored = await getBlob<{ paint: string; imagePath: string }>(key).catch(() => null)
    if (!stored) continue
    // Bail if tool switched under us
    if (tool.value?.full_tool_id !== fullToolId) return

    const itemPath = images[i]._originalPath || images[i].path
    if (stored.imagePath === itemPath) {
      images[i] = { ...images[i], _paintLayerDataUrl: stored.paint }
      anyRestored = true
    } else {
      deleteBlob(key).catch(() => { /* ignore */ })
    }
  }
  if (anyRestored) {
    globalPrefs.value.inputImages = [...images]
  }
}

// Auto-select nearest aspect ratio when first reference image is added (for tools with aspect_ratio param)
watch(() => globalPrefs.value.inputImages, (newImages, oldImages) => {
  const wasEmpty = !oldImages || oldImages.length === 0
  const hasImages = newImages && newImages.length > 0
  if (!hasImages) return

  const firstImage = newImages[0]
  const oldFirst = oldImages?.[0]
  const firstChanged = wasEmpty || firstImage?.path !== oldFirst?.path || firstImage?.mediaId !== oldFirst?.mediaId

  if (firstChanged && firstImage?.width && firstImage?.height) {
    // Don't auto-snap during initial load (state is being restored)
    if (isInitialLoading.value) return
    // Snap aspect ratio to match first image unless exact size is locked.
    if (hasAspectRatio.value && !resolutionLockSize.value) {
      const nearestAR = findNearestAspectRatio(firstImage.width, firstImage.height)
      modelParams.value.aspect_ratio = nearestAR
    }
    // Snap width/height to match first image (with notification)
    if (hasWidthHeight.value) {
      suggestResolutionFromImage(firstImage.width, firstImage.height)
    }
  }
}, { deep: true })

// Same auto-resolution snap for image-to-video tools, driven by the start frame.
// Frame tools store inputs in videoImages, not globalPrefs.inputImages, so they
// need their own watcher to keep the canvas matched to the dropped start frame.
watch(() => videoImages.startImage, (newStart, oldStart) => {
  if (!newStart?.width || !newStart?.height) return
  if (isInitialLoading.value) return
  const changed = !oldStart
    || newStart.path !== oldStart.path
    || newStart.mediaId !== oldStart.mediaId
    // Dimensions just resolved (e.g. legacy frame backfilled by the picker) —
    // treat as a change so the canvas can match a frame that previously read 1×1.
    || (!oldStart.width && !!newStart.width)
  if (!changed) return
  if (hasAspectRatio.value && !resolutionLockSize.value) {
    modelParams.value.aspect_ratio = findNearestAspectRatio(newStart.width, newStart.height)
  }
  if (hasWidthHeight.value) {
    suggestResolutionFromImage(newStart.width, newStart.height)
  }
})

// LoRA state — ref that syncs bidirectionally with the composable pool
import { useLoraPool } from '../composables/useLoraPool'
import type { LoraPoolItem } from '../composables/useLoraPool'
const _loraPool = useLoraPool()
const toolLoras = ref<LoraPoolItem[]>([])

// Get enabled loras for job submission
function getToolEnabledLoras(): Array<{ lora: string; weight: number }> {
  return toolLoras.value
    .filter(l => l.enabled && l.lora)
    .map(l => ({ lora: l.lora, weight: l.weight }))
}

// Post-processing chain — rides tool state / presets like the LoRA pool
const toolChain = ref<PostProcessingChain>(emptyChain())

// Track idle count for auto-stop feature (generations without user changes)
const foreverModeIdleCount = ref(0)

// Reset forever mode idle counter when user makes changes
// These are considered "user changes" that reset the counter:
// - Editing prompt or negative prompt
// - Changing input images/videos
// - Changing model parameters (except seed/randomizeSeed which are automated)
// - Changing LoRA selection/weights

function resetForeverModeIdleCount() {
  foreverModeIdleCount.value = 0
}

// Watch prompt changes
watch(() => globalPrefs.value.prompt, resetForeverModeIdleCount)

// Watch input images/videos changes
watch(() => globalPrefs.value.inputImages, resetForeverModeIdleCount, { deep: true })
watch(() => globalPrefs.value.inputVideos, resetForeverModeIdleCount, { deep: true })

// Watch model params changes (excluding seed-related fields)
watch(modelParams, (newParams, oldParams) => {
  // Skip if this is the initial load or if only seed/randomizeSeed changed
  if (!oldParams) return

  // Check if any non-seed parameter changed
  for (const key of Object.keys(newParams)) {
    if (key === 'seed' || key === 'randomizeSeed') continue
    if (newParams[key] !== oldParams[key]) {
      resetForeverModeIdleCount()
      return
    }
  }
}, { deep: true })

// Watch LoRA changes
watch(toolLoras, resetForeverModeIdleCount, { deep: true })

// Shared auto-delete duration
const { autoDeleteDuration, setAutoDeleteDuration } = useToolAutoDeleteDuration()

// Slideshow state
const slideshowState = reactive({
  active: false,
  totalCount: 0,
  startIndex: 0,
  pageProvider: null as any,
  randomized: false,
  randomSeed: null as number | null,
  autoAdvanceOnNew: false
})

const slideshowTotalCount = computed(() =>
  slideshowState.autoAdvanceOnNew
    ? (jobsManager?.totalCompletedCount.value || 0)
    : slideshowState.totalCount
)

function enterSlideshow(params: any) {
  slideshowState.active = true
  slideshowState.totalCount = params.totalCount
  slideshowState.startIndex = params.startIndex
  slideshowState.pageProvider = params.pageProvider
  slideshowState.randomized = params.randomized
  slideshowState.randomSeed = params.randomSeed
  slideshowState.autoAdvanceOnNew = !!params.autoAdvanceOnNew
  enterSlideshowMode()
}

function exitSlideshow() {
  slideshowState.active = false
  exitSlideshowMode()
}

// Handle compare from slideshow (source image compare)
async function handleCompareFromSlideshow({ leftMediaId, rightMediaId }: { leftMediaId: number, rightMediaId: number }) {
  // Don't exit slideshow - keep it active so we return to it when compare closes
  // Compare mode will overlay on top (higher z-index)
  await enterCompare({ leftMediaId, rightMediaId, returnTo: 'slideshow' })
}

// Open the remix source in slideshow
function openRemixSourceInSlideshow() {
  if (!remixSource.value) return
  openSingleImageSlideshow(remixSource.value.mediaId)
}

// Copy seed from remix source into current generation params
function handleRemixUseSeed() {
  if (remixSource.value?.seed == null) return
  modelParams.value.seed = remixSource.value.seed
  modelParams.value.randomizeSeed = false
}

// Use the remix source's original prompt. The intent is to reproduce the source,
// so restore the enhance + translate settings it was generated with (when known).
function handleRemixUsePrompt() {
  if (!remixSource.value) return
  globalPrefs.value.prompt = remixSource.value.promptSnippet
  const meta = remixSource.value.promptMetadata
  if (meta) {
    globalPrefs.value.promptOptions = {
      ...globalPrefs.value.promptOptions,
      autoImprove: {
        ...globalPrefs.value.promptOptions.autoImprove,
        enabled: !!meta.auto_improve_enabled,
        instructions: meta.auto_improve_instructions || '',
      },
      translate: {
        enabled: !!meta.translate_enabled,
        language: meta.translate_language || globalPrefs.value.promptOptions.translate?.language || 'zh-Hans',
      },
    }
  }
  suppressRemixDeactivation()
}

// Use the remix source's exact rendered prompt. Since the intent is to use the
// prompt verbatim, also turn off enhance + translate so it isn't rewritten.
function handleRemixUseExactPrompt() {
  if (remixSource.value?.renderedPrompt == null) return
  globalPrefs.value.prompt = remixSource.value.renderedPrompt
  globalPrefs.value.promptOptions = {
    ...globalPrefs.value.promptOptions,
    autoImprove: { ...globalPrefs.value.promptOptions.autoImprove, enabled: false },
    translate: { language: 'zh-Hans', ...globalPrefs.value.promptOptions.translate, enabled: false },
  }
  suppressRemixDeactivation()
}

// Restore a dismissed remix
function handleRemixRestore() {
  if (!dismissedRemix.value) return
  remixSource.value = dismissedRemix.value
  dismissedRemix.value = null
  // Suppress detection for 30s so things settle after restore
  suppressRemixDeactivation()
}

// Dismissed remix interstitial expired
function handleRemixDismissedExpired() {
  dismissedRemix.value = null
}

// Use remix source image as reference image input
async function handleRemixUseImage() {
  if (!remixSource.value || !mediaInputConfig.value) return
  const mediaId = remixSource.value.mediaId
  try {
    const mediaItem = await getMediaItem(mediaId)
    if (!mediaItem?.file_path) return
    const copyResp = await axios.post(
      `/api/generate/copy-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
    )
    const refImage = {
      path: copyResp.data.path,
      filename: copyResp.data.filename,
      mediaId: copyResp.data.media_id,
      hash: copyResp.data.file_hash,
      width: copyResp.data.width,
      height: copyResp.data.height,
    }
    const existing = globalPrefs.value.inputImages || []
    const max = mediaInputConfig.value.max || 1
    const slotsAvailable = max - existing.length
    if (slotsAvailable > 0) {
      globalPrefs.value.inputImages = [...existing, refImage]
    } else {
      // Replace last slot
      globalPrefs.value.inputImages = [...existing.slice(0, max - 1), refImage]
    }
  } catch (err) {
    console.error('Failed to use remix image as reference:', err)
  }
}

// Global keyboard shortcuts
useGlobalKeyboardShortcuts({
  onEscapePressed: () => {
    if (slideshowState.active) {
      exitSlideshow()
    }
  }
})

// Watch for browser back button
watch(slideshowActive, (newValue) => {
  if (!newValue && slideshowState.active) {
    slideshowState.active = false
  }
})

// Error modal state
const errorModalJob = ref<any>(null)
const showErrorModal = ref(false)
const infoModalJobId = ref<number | null>(null)
const showInfoModal = ref(false)
const infoModalJob = computed(() => {
  if (!infoModalJobId.value || !jobsManager) return null
  return jobsManager.jobs.value.find((j: any) => j.id === infoModalJobId.value) || null
})


// Sync toolLoras ref <-> composable pool bidirectionally
let _syncingFromPool = false
let _syncingToPool = false

// When the composable pool changes, update the ref
watch(
  () => _loraPool.getAllItems(scopedToolId(fullToolIdFromProps)),
  (items) => {
    if (_syncingToPool) return
    _syncingFromPool = true
    toolLoras.value = items
    nextTick(() => { _syncingFromPool = false })
  },
  { deep: true, immediate: true }
)

// When the ref changes (e.g. from useToolState restore), sync to the pool
watch(toolLoras, (items) => {
  if (_syncingFromPool) return
  if (!fullToolIdFromProps) return
  _syncingToPool = true
  _loraPool.syncItemsToPool(scopedToolId(fullToolIdFromProps), items)
  nextTick(() => { _syncingToPool = false })
}, { deep: true })

// Note: parameterSchema is now provided by useToolSchemaFeatures composable


// Available LoRAs from the generator
const isRefreshingLoras = ref(false)

const availableLoras = computed(() => {
  // Get LoRAs from the tool's parameter_schema
  if (!tool.value?.parameter_schema?.properties?.loras) return []

  const lorasSchema = tool.value.parameter_schema.properties.loras
  const pathEnum = lorasSchema.items?.properties?.path?.enum || []
  const nameEnum = lorasSchema.items?.properties?.name?.enum || []

  if (!pathEnum.length) return []

  // Build lora objects from the enums (trust the provider's enum list)
  const loras = pathEnum
    .map((path: string, i: number) => ({
      path,
      name: nameEnum[i] || path.split('/').pop()?.replace(/\.[^.]+$/i, '').replace(/_/g, ' ') || path,
    }))
  return loras.sort((a: any, b: any) => a.path.localeCompare(b.path))
})

async function refreshLoras() {
  if (!tool.value) return
  isRefreshingLoras.value = true
  try {
    // Extract provider ID from full_tool_id
    // Format: "provider_id:task_type:model_slug" (e.g., "comfyui:text-to-image:flux-dev")
    // Provider ID is just the first part
    const fullToolId = tool.value.full_tool_id
    const parts = fullToolId?.split(':') || []
    const providerId = parts.length >= 1 ? parts[0] : undefined

    // Refresh the provider's tools (triggers LoRA re-discovery)
    await refreshProviderTools(providerId)

    // Quietly fetch updated tool schema without triggering full loading state
    if (fullToolId) {
      const providerTool = await getProviderTool(fullToolId)
      // Update only the parameter_schema which contains LoRA info
      tool.value = {
        ...tool.value,
        parameter_schema: providerTool.parameter_schema
      }
    }
  } catch (err) {
    console.error('Failed to refresh LoRAs:', err)
  } finally {
    isRefreshingLoras.value = false
  }
}

// LoRA upload config — extracted from x-accept-upload on the `loras` parameter
// in parameter_schema. Cloud tools emit it at the top level on the loras
// param; desktop / ComfyUI workflows historically nest it under
// items.properties.path. Check both, top-level first.
const loraUploadConfig = computed(() => {
  const lorasSchema = tool.value?.parameter_schema?.properties?.loras
  if (!lorasSchema) return null

  const cfg =
    lorasSchema['x-accept-upload'] ??
    lorasSchema.items?.properties?.path?.['x-accept-upload']
  if (!cfg) return null

  return {
    extensions: cfg.extensions || [],
    max_size: cfg.max_size || 0,
  }
})

// Upload a LoRA file
const loraPoolPanelRef = ref<InstanceType<typeof LoraPoolPanel> | null>(null)
const isUploadingLora = ref(false)
const loraUploadProgress = ref<number | null>(null)
const loraUploadFileName = ref<string | null>(null)

async function uploadLora(files: File[]) {
  if (!tool.value?.full_tool_id) return
  if (files.length === 0) return

  isUploadingLora.value = true
  isRefreshingLoras.value = true
  const errors: string[] = []
  let addedCount = 0

  try {
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const label = files.length > 1 ? `${file.name} (${i + 1}/${files.length})` : file.name
      loraUploadFileName.value = label
      loraUploadProgress.value = 0

      try {
        const result = await uploadToTool(
          tool.value.full_tool_id!,
          'loras',
          file,
          (percent) => { loraUploadProgress.value = percent },
        )

        if (result.success && (result.installed_path || (result as any).lora_id)) {
          // Refresh schema so the new LoRA appears in availableLoras
          const fullToolId = tool.value.full_tool_id
          if (fullToolId) {
            const providerTool = await getProviderTool(fullToolId)
            tool.value = {
              ...tool.value,
              parameter_schema: providerTool.parameter_schema
            }
          }

          // Cloud providers return an opaque lora_id; desktop providers return
          // installed_path. Either becomes the pool item's identifier key.
          const poolKey = (result as any).lora_id ?? result.installed_path!
          // For cloud LoRAs the key is an opaque UUID, so pass the original
          // filename as the display name. Desktop LoRAs leave it undefined
          // — the path-derived heuristic still renders nicely.
          const displayName = (result as any).lora_id ? file.name : undefined

          // Add to pool immediately — first one enabled, rest disabled
          await nextTick()
          loraPoolPanelRef.value?.addLoraByPath(poolKey, addedCount === 0, displayName)
          addedCount++
        } else {
          errors.push(`${file.name}: ${result.error || 'unknown error'}`)
        }
      } catch (err: any) {
        const message = err?.response?.data?.detail || err?.message || 'Upload failed'
        errors.push(`${file.name}: ${message}`)
      }
    }

    if (errors.length > 0) {
      addToast(`${errors.length} upload(s) failed: ${errors.join('; ')}`, 'error', 8000)
    }
  } finally {
    isUploadingLora.value = false
    loraUploadProgress.value = null
    loraUploadFileName.value = null
    isRefreshingLoras.value = false
  }
}

// Tool schema features composable - provides hasPrompt, hasLoras, mediaInputConfig, etc.
const {
  hasWidthHeight,
  hasAspectRatio,
  hasMegapixels,
  hasPrompt,
  hasMask,
  maskFormat,
  hasLoras,
  hasScaleFactor,
  hasUpscaleResolution,
  showUpscalePicker,
  hasResolution,
  hasFrameCount,
  hasDuration,
  hasLyrics,
  allowedDurations,
  durationConfig,
  hasFps,
  fpsOptions,
  videoParamDefaults,
  hasVideoFrames,
  hasEndFrame,
  frameMinItems,
  frameConstraints,
  outputsVideo,
  outputsAudio,
  isFromScratch,
  mediaInputConfig,
  audioInputConfig,
  aspectRatioChoices,
  imageSizeChoices,
  parameterSchema,
  groupedGenericParams,
  promptPlaceholder,
  allowedDimensions,
  controlnetOptions,
} = useToolSchemaFeatures({
  tool,
  availableLoras,
})

// Values used to evaluate x-constraints (SchemaParamGroup.vue, below). Frame
// state lives in videoImages/frameItems, and reference-audio state in
// globalPrefs.inputAudios (via audioInputItems) — neither is part of
// modelParams, so params like Kling's `sound` (constrained on `input_images`)
// or Fish Audio / Qwen3-TTS's `voice` (constrained on `input_audios`) need
// them available live too.
const constraintValues = computed(() => ({
  ...modelParams.value,
  ...(hasVideoFrames.value ? { input_images: frameItems.value } : {}),
  ...(audioInputConfig.value ? { input_audios: audioInputItems.value } : {}),
}))

// input_images isn't a GenericParam (it has its own MediaPicker, not a
// SchemaParamGroup row), so its constraint state — e.g. Kling: frames
// disabled while native audio is on — is resolved directly here rather than
// via the groupedGenericParams loop above.
const frameConstraintState = computed(() => resolveParamConstraints(frameConstraints.value, constraintValues.value))

// Converges any param with an active `disable` constraint + force_value to
// that value — regardless of whether the user changed the constraining param
// (e.g. dropped a frame) or the constrained param (e.g. toggled audio) first.
// Not gated by isInitialLoading: a restored preset/remix with an invalid
// combination (e.g. sound:true + a frame) must self-correct on load too.
watch([groupedGenericParams, constraintValues], () => {
  for (const group of groupedGenericParams.value) {
    for (const param of group.params) {
      const state = resolveParamConstraints(param.constraints, constraintValues.value)
      if (state.disabled && state.forceValue !== undefined && modelParams.value[param.name] !== state.forceValue) {
        modelParams.value[param.name] = state.forceValue
      }
    }
  }
}, { deep: true, immediate: true })

// Video output → cinematography enhancement. This is the AUTHORITATIVE signal
// (we know the task); the backend doesn't rely on recognizing the model string.
const enhanceIsVideo = computed(() => !!outputsVideo.value)

// Audio output → sound-focused enhancement (text-to-audio / music / sound /
// speech). Authoritative like enhanceIsVideo; keeps the enhancer from rewriting
// an audio prompt into a visual scene.
const enhanceIsAudio = computed(() => !!outputsAudio.value)

// Image edit → edit-style enhancement. Input images on a non-video tool mean the
// prompt is an instruction over those images, not a fresh scene to describe. The
// count drives backend routing (>0 → edit style) and "first/second image" phrasing.
// In batch mode inputImages is the batch list (one item PER job), so the per-job
// edit count is 1 — not the list length.
const enhanceInputImageCount = computed(() => {
  if (outputsVideo.value) return 0
  if (globalPrefs.value.batchMode) {
    return globalPrefs.value.batchField === 'input_images' ? 1 : 0
  }
  return globalPrefs.value.inputImages?.length ?? 0
})

// image-to-video: the start frame, fed to the enhancer so the cinematography
// prompt animates the actual image. Only when it's a library item (has a mediaId).
const enhanceSourceMediaId = computed<number | null>(() =>
  videoImages.startImage?.mediaId ?? null
)
const enhanceUsesImage = computed(() => {
  const source: any = videoImages.startImage
  return !!(source?.path || source?.file_path || source?.filePath)
})

// Server-owned prompt warm pool: while generate-forever is running, tells the
// server how many LLM-enhanced prompt variants to keep ready so submits pick
// one up with zero added latency. Scoped to forever mode's own lifecycle
// (registers/tears down alongside it) - a single manual generation has no
// duty cycle to preserve, so it isn't speculated for here; it just goes
// through the normal enhance-at-submit path.
const { clear: clearPromptWarmPool } = usePromptWarmPool({
  generatorInstanceId,
  toolId: computed(() => tool.value?.full_tool_id ?? null),
  prompt: computed(() => globalPrefs.value.prompt),
  // Only the text-rewrite path with no source image can be pre-enhanced from
  // prompt text alone. Ideogram converts post-resolve, and i2v depends on the
  // frame, so neither is eligible.
  autoImproveEnabled: computed(() =>
    (globalPrefs.value.promptOptions?.autoImprove?.enabled ?? false) &&
    enhanceMode.value === 'text' &&
    !enhanceUsesImage.value
  ),
  autoImproveInstructions: computed(() => globalPrefs.value.promptOptions?.autoImprove?.instructions ?? null),
  model: computed(() => toolModelString.value || null),
  isVideo: enhanceIsVideo,
  isAudio: enhanceIsAudio,
  inputImageCount: enhanceInputImageCount,
  active: computed(() => uiState.value.generateForeverMode ?? false),
  concurrency: computed(() => uiState.value.generateForeverConcurrency ?? 1),
})

// Tool state composable - provides state persistence, presets, and modified detection
const {
  activePreset,
  baseState,
  collapsedGroups,
  hasActivePreset,
  selectedPresetId,
  isModified,
  buildToolState,
  applyToolState,
  clearLocalStorageState,
  getGroupCollapsed,
  toggleGroupCollapsed,
  loadCollapsedGroups,
  loadAIPromptExpanded,
  saveAIPromptExpanded,
  loadActivePresetId,
  handlePresetSelect,
  handlePresetSaved,
  clearActivePreset,
  revertToBaseState,
  saveToActivePreset,
  initializeState,
  startWatchingChanges,
  stopWatching,
  flushPendingSaves,
} = useToolState({
  fullToolId: fullToolIdFromProps,
  scopedToolId: (projectSuffix || instanceSuffix) ? scopedToolId(fullToolIdFromProps) : undefined,
  tool,
  globalPrefs,
  modelParams,
  toolLoras,
  toolChain,
  uiState,
  saveToolState,
})

// Upscale resolution picker value
const resolutionPickerValue = computed(() => ({
  resolutionMode: modelParams.value.resolutionMode || 'relative',
  scaleFactor: modelParams.value.scaleFactor || 2,
  targetResolution: modelParams.value.targetResolution || 1080
}))

function onResolutionPickerUpdate(value: { resolutionMode: 'relative' | 'pixels', scaleFactor: number, targetResolution: number }) {
  modelParams.value.resolutionMode = value.resolutionMode
  modelParams.value.scaleFactor = value.scaleFactor
  modelParams.value.targetResolution = value.targetResolution
}

// Get input image dimensions for upscale
const inputImageHeight = computed(() => {
  if (globalPrefs.value.inputImages?.length > 0) {
    return globalPrefs.value.inputImages[0]?.height || null
  }
  return null
})

const inputImageWidth = computed(() => {
  if (globalPrefs.value.inputImages?.length > 0) {
    return globalPrefs.value.inputImages[0]?.width || null
  }
  return null
})

const finalResolution = computed(() => {
  if ((modelParams.value.resolutionMode || 'relative') === 'relative' && inputImageHeight.value && inputImageWidth.value) {
    const shortEdge = Math.min(inputImageWidth.value, inputImageHeight.value)
    return Math.round(shortEdge * (modelParams.value.scaleFactor || 2))
  }
  return modelParams.value.targetResolution || 1080
})

// Schema-driven field validation checks
// Maps parameter_schema field names to UI state validation
const inputFieldChecks: Record<string, () => boolean> = {
  'input_images': () => {
    // For videoFramePicker, check videoImages state
    if (hasVideoFrames.value) return !!videoImages.startImage
    return globalPrefs.value.inputImages?.length > 0
  },
  'input_videos': () => globalPrefs.value.inputVideos?.length >= (mediaInputConfig.value?.min || 2),
  'input_audios': () => globalPrefs.value.inputAudios?.length >= (audioInputConfig.value?.min || 1),
  'mask': () => !!maskDataUrl.value,
  'prompt': () => true, // Prompts are always optional (unconditional generation)
  'negative_prompt': () => true, // Always optional
}

// Can submit check - schema-driven validation
const canSubmit = computed(() => {
  if (!tool.value || !outputFolder.value) return false

  // Check all required fields from parameter_schema
  const required = tool.value.parameter_schema?.required || []
  for (const field of required) {
    const check = inputFieldChecks[field]
    if (check && !check()) return false
  }

  return true
})

// Job counts from jobs manager
const allJobs = computed(() => jobsManager?.allJobs.value || [])

// Keep the stage pin honest as the completed-jobs list changes. Declared here
// (after jobsManager) so the watch's initial getter run doesn't hit the TDZ of
// jobsManager.
watch(stageCompletedJobs, (list: any[], prevList: any[] = []) => {
  // Drop a stale stage pin if the pinned job left the list (dismissed) → resume
  // following newest.
  if (stagePinnedMediaId.value != null && !list.some((j: any) => j.result_media_id === stagePinnedMediaId.value)) {
    stagePinnedMediaId.value = null
    return
  }
  // Auto-advance: when a new completed job arrives at the head and the user was
  // viewing the previous newest — either following (pin null) or explicitly
  // pinned to what was the head — follow the new newest by clearing the pin.
  // Without this, clicking/arrowing to the newest image pins it and freezes the
  // hero, so later arrivals never advance.
  const newHeadId = list[0]?.id
  const prevHeadId = prevList[0]?.id
  if (newHeadId != null && newHeadId !== prevHeadId) {
    const wasOnNewest = stagePinnedMediaId.value == null ||
      stagePinnedMediaId.value === prevList[0]?.result_media_id
    if (wasOnNewest) stagePinnedMediaId.value = null
  }
})
const queuedJobsCount = computed(() => {
  const jobs = jobsManager?.jobs.value
  if (!jobs) return 0
  return jobs.filter((j: any) => ['queued', 'assigned'].includes(j.status)).length
})

// OS Detection
const isMac = computed(() => navigator.platform.toUpperCase().indexOf('MAC') >= 0)

// Methods
// --- Resolution auto-change notification ---
// When resolution is changed automatically (image drop, extend, scale processing),
// show a temporary notification bar with old-size/same-area options.
const resAutoChange = ref<{
  oldWidth: number; oldHeight: number;
  newWidth: number; newHeight: number;
} | null>(null)
let resAutoChangeTimer: ReturnType<typeof setTimeout> | null = null
const resolutionMode = ref<'aspect' | 'manual'>('aspect')
const resAutoChangeOldAreaLabel = computed(() => {
  if (!resAutoChange.value) return ''
  return formatMegapixelArea(resAutoChange.value.oldWidth, resAutoChange.value.oldHeight)
})
const resolutionLockSize = computed({
  get: () => Boolean(uiState.value.resolutionLockSize),
  set: (value: boolean) => {
    uiState.value.resolutionLockSize = value
    if (value) uiState.value.resolutionLockArea = false
  }
})
const resolutionLockArea = computed({
  get: () => Boolean(uiState.value.resolutionLockArea),
  set: (value: boolean) => {
    uiState.value.resolutionLockArea = value
    if (value) uiState.value.resolutionLockSize = false
  }
})

function dimensionsForAreaAndAspect(area: number, aspect: number): { width: number; height: number } | null {
  if (!Number.isFinite(area) || !Number.isFinite(aspect) || area <= 0 || aspect <= 0) return null
  const height = Math.max(1, Math.round(Math.sqrt(area / aspect)))
  const width = Math.max(1, Math.round(height * aspect))
  return { width, height }
}

function formatMegapixelArea(width: number, height: number): string {
  const mp = (width * height) / 1_000_000
  if (!Number.isFinite(mp) || mp <= 0) return 'current'
  return `${Number(mp.toFixed(1))}MP`
}

// Snap onto the active tool's legal grid (shared util — also used by chain
// step settings and mirrored by the backend snaps).
function snapDimsToGrid(width: number, height: number): { width: number; height: number } {
  return snapDimsToSchemaGrid(parameterSchema.value?.properties, width, height)
}

function suggestedDimensionsForLocks(sourceW: number, sourceH: number): { width: number; height: number } | null {
  const oldW = Number(modelParams.value.width)
  const oldH = Number(modelParams.value.height)
  if (!oldW || !oldH || oldW <= 0 || oldH <= 0) {
    return resolutionLockSize.value || resolutionLockArea.value ? null : { width: sourceW, height: sourceH }
  }

  if (resolutionLockSize.value) return null
  if (!resolutionLockArea.value) return { width: sourceW, height: sourceH }

  return dimensionsForAreaAndAspect(oldW * oldH, sourceW / sourceH)
}

function showResAutoChange(rawW: number, rawH: number) {
  const { width: newW, height: newH } = snapDimsToGrid(rawW, rawH)
  const oldW = modelParams.value.width
  const oldH = modelParams.value.height
  if (oldW === newW && oldH === newH) return
  resolutionMode.value = 'manual'
  // On first notification (or if previous expired), stash the original resolution.
  // If overlapping, keep the original "old" from the first change.
  if (!resAutoChange.value) {
    resAutoChange.value = { oldWidth: oldW, oldHeight: oldH, newWidth: newW, newHeight: newH }
  } else {
    resAutoChange.value = { ...resAutoChange.value, newWidth: newW, newHeight: newH }
  }
  modelParams.value.width = newW
  modelParams.value.height = newH
  // Reset the 10s timer
  if (resAutoChangeTimer) clearTimeout(resAutoChangeTimer)
  resAutoChangeTimer = setTimeout(() => { resAutoChange.value = null }, 10000)
}

function resAutoChangeRevert() {
  if (!resAutoChange.value) return
  modelParams.value.width = resAutoChange.value.oldWidth
  modelParams.value.height = resAutoChange.value.oldHeight
  resAutoChange.value = null
  if (resAutoChangeTimer) { clearTimeout(resAutoChangeTimer); resAutoChangeTimer = null }
}

function resAutoChangeKeepArea() {
  if (!resAutoChange.value) return
  const { oldWidth, oldHeight, newWidth, newHeight } = resAutoChange.value
  const dims = dimensionsForAreaAndAspect(oldWidth * oldHeight, newWidth / newHeight)
  if (dims) {
    const snapped = snapDimsToGrid(dims.width, dims.height)
    modelParams.value.width = snapped.width
    modelParams.value.height = snapped.height
  }
  resAutoChange.value = null
  if (resAutoChangeTimer) { clearTimeout(resAutoChangeTimer); resAutoChangeTimer = null }
}

function onResolutionUpdate(width: number, height: number) {
  const snapped = snapDimsToGrid(width, height)
  modelParams.value.width = snapped.width
  modelParams.value.height = snapped.height
}

function suggestResolutionFromImage(width: number, height: number, options?: { manual?: boolean }) {
  if (options?.manual) {
    showResAutoChange(width, height)
    return
  }
  const dims = suggestedDimensionsForLocks(width, height)
  if (dims) showResAutoChange(dims.width, dims.height)
}

function onSuggestResolution(dims: { width: number; height: number } | null, options?: { manual?: boolean }) {
  if (!dims) return
  if (hasWidthHeight.value) {
    suggestResolutionFromImage(dims.width, dims.height, options)
  }
}

function onSuggestAspect(dims: { width: number; height: number } | null) {
  if (!dims) return
  if (hasWidthHeight.value) {
    const oldW = Number(modelParams.value.width)
    const oldH = Number(modelParams.value.height)
    const adjusted = dimensionsForAreaAndAspect(oldW * oldH, dims.width / dims.height)
    if (adjusted) showResAutoChange(adjusted.width, adjusted.height)
  }
  if (hasAspectRatio.value) {
    modelParams.value.aspect_ratio = findNearestAspectRatio(dims.width, dims.height)
  }
}

function generateRandomSeed() {
  return Math.floor(Math.random() * 4294967296)
}

// Get URL for source image (used by MaskEditor)
function getSourceImageUrl(image: { path?: string; filename?: string; hash?: string }): string {
  // If image has a hash property, it's from the media library - use original file
  if (image.hash) {
    return getMediaFileUrl(image.hash)
  }
  // If path is an absolute file path (starts with /), use the file endpoint
  if (image.path?.startsWith('/')) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(image.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  // Otherwise assume path is a hash
  if (image.path) {
    return getMediaFileUrl(image.path)
  }
  // Fallback to filename as hash
  if (image.filename) {
    return getMediaFileUrl(image.filename)
  }
  return ''
}

// Get current state for preset picker (subset of full state)
function getCurrentState() {
  return {
    width: modelParams.value.width,
    height: modelParams.value.height,
    cfg: modelParams.value.cfg,
    steps: modelParams.value.steps,
    sampler: modelParams.value.sampler,
    scheduler: modelParams.value.scheduler,
    shift: modelParams.value.shift,
    denoise: modelParams.value.denoise,
    loras: toolLoras.value,
    prompt: globalPrefs.value.prompt,
    negative_prompt: modelParams.value.negative_prompt,
    promptOptions: globalPrefs.value.promptOptions,
    agentInstructions: globalPrefs.value.agentInstructions || '',
    postProcessingChain: toolChain.value,
  }
}

// Note: handlePresetSelect, handlePresetSaved, clearActivePreset, revertToBaseState,
// saveToActivePreset, saveAsToolDefaults are now provided by useToolState composable
const { track: trackTelemetry } = useTelemetry()

function handleResetToDefaults() {
  trackTelemetry('params_reset', { _toolId: tool.value?.full_tool_id }, 'generation')
  clearActivePreset()
  remixSource.value = null
}

function handleRevertToBaseState() {
  trackTelemetry('preset_reverted', {
    _toolId: tool.value?.full_tool_id,
    _presetId: activePreset.value?.id,
  }, 'generation')
  revertToBaseState()
}

// Load data
async function loadOutputFolder() {
  try {
    const params = {}
    if (projectScopeId.value != null) {
      params.project_id = projectScopeId.value
    }
    const response = await axios.get(`${API_BASE}/generate/folder`, { params })
    outputFolder.value = response.data.path
    globalPrefs.value.folder_path = response.data.path
  } catch (err) {
    console.error('Failed to load output folder:', err)
  }
}

async function loadTool(forceReload = false, silent = false) {
  const fullToolId = props.fullToolId
  if (!fullToolId) {
    error.value = { message: 'No tool ID provided' }
    isInitialLoading.value = false
    return
  }

  // Skip loading if we already have this tool loaded (e.g., returning via KeepAlive)
  if (!forceReload && tool.value && tool.value.full_tool_id === fullToolId) {
    return
  }

  // The full-screen spinner is a first-load affordance. Background reconnect
  // retries run silently so the existing error state stays put rather than
  // flickering to the spinner every cycle.
  if (!silent) {
    isInitialLoading.value = true
    error.value = null
  }

  try {
    // Load provider tool descriptor; tolerate state fetch failures
    const providerTool = await getProviderTool(fullToolId)
    const toolState = await getToolState(fullToolId).catch(() => ({ state: {} as Record<string, any> }))
    tool.value = buildToolWithState(providerTool, toolState.state || {})
    error.value = null
  } catch (err: any) {
    console.error('Failed to load tool:', err)
    const statusCode = err?.response?.status
    error.value = { message: 'Failed to load tool', statusCode }
    isInitialLoading.value = false
    scheduleLoadRetry()
    return
  }

  // Load output folder and init job manager in parallel
  await Promise.all([
    loadOutputFolder(),
    jobsManager.init()
  ])

  // Apply tool schema defaults directly (tools are the single source of truth)
  const toolDefaults = getToolDefaults(tool.value.parameter_schema)

  // Apply defaults to modelParams
  Object.assign(modelParams.value, toolDefaults)

  // If tool has constrained dimensions, default to the most square-ish pair
  if (allowedDimensions.value) {
    const dims = allowedDimensions.value
    let bestPair = dims[0]
    let bestDiff = Math.abs(dims[0][0] / dims[0][1] - 1)
    for (const pair of dims) {
      const diff = Math.abs(pair[0] / pair[1] - 1)
      if (diff < bestDiff) {
        bestDiff = diff
        bestPair = pair
      }
    }
    modelParams.value.width = bestPair[0]
    modelParams.value.height = bestPair[1]
  }

  // Initialize state from preset or tool defaults (via composable)
  const savedPresetId = loadActivePresetId()
  await initializeState(savedPresetId)

  // Load presets for the agent's state_context (fire-and-forget).
  refreshAgentPresets()

  // Ensure seed
  if (!modelParams.value.seed) {
    modelParams.value.seed = generateRandomSeed()
  }

  // Load UI state (forever mode settings, etc.) from localStorage
  loadUIState()
  preferencesLoaded.value = true

  // Restore paint layers from dedicated storage (saved separately due to size).
  // Fire-and-forget — paint layers reapply async; other init work shouldn't wait.
  void restorePaintLayers()

  // Load AI prompt improver expanded state from localStorage (tool-specific, overrides generic UI state)
  uiState.value.aiPromptExpanded = loadAIPromptExpanded()

  // Load collapsed groups state from localStorage
  loadCollapsedGroups()

  // Load video images for image-to-video tools
  loadVideoImages()

  // Load persisted inspiration state
  loadRemixState()

  // Set video-specific defaults (for tools with duration param). Shared with
  // the chain-step panel via videoParamDefaults — one source of truth.
  if (hasDuration.value) {
    if (modelParams.value.duration == null) {
      modelParams.value.duration = videoParamDefaults.value.duration
    }
    if (hasFps.value && !modelParams.value.fps) {
      modelParams.value.fps = videoParamDefaults.value.fps
    }
  }

  // Set video-specific defaults (for tools with frame_count param, legacy VACE)
  if (hasFrameCount.value) {
    if (!modelParams.value.frameCount) {
      modelParams.value.frameCount = frameCountConfig.value.default
    }
    if (!modelParams.value.fps) {
      modelParams.value.fps = fpsOptions.value[0] || 16
    }
  }

  // Start watching for changes to save to localStorage (via composable)
  startWatchingChanges()

  isInitialLoading.value = false

  // Check for pending input from "Send to Tool" action
  loadPendingInput()

  // Check for pending generation config from "Generate more like this" action
  nextTick(() => {
    loadPendingGeneration()
    loadPresetFromQuery()
  })

  // Check for remixFrom query param (also supports legacy inspireFrom/loadFromMedia)
  const remixMediaId = (route.query.remixFrom || route.query.inspireFrom || route.query.loadFromMedia) as string | undefined
  if (remixMediaId) {
    loadRemix(remixMediaId)
  }

  if (toolAvailability.value !== 'available') {
    startAvailabilityPolling()
  } else {
    stopAvailabilityPolling()
  }
}

// Load pending input from sessionStorage (used when sending media to this tool)
function loadPendingInput() {
  if (!route.query.loadInput || !tool.value) {
    return
  }

  const storageKey = makeToolDbKey(scopedToolId(tool.value.full_tool_id), 'pending_input')
  const pendingInput = sessionStorage.getItem(storageKey)
  if (!pendingInput) {
    return
  }

  try {
    const config = JSON.parse(pendingInput)
    sessionStorage.removeItem(storageKey)

    // Media-batch: multi-select Send to Tool marked this slot as a batch. Enter
    // batch mode — items live in inputImages/inputVideos, Run submits one job
    // per item, prep is uniform across the batch.
    if (config.mode === 'batch' && Array.isArray(config.items) && config.items.length > 0) {
      const items = config.items.map((m: any) => ({
        path: m.path,
        filename: m.filename || m.hash,
        hash: m.hash,
        mediaId: m.mediaId,
        width: m.width,
        height: m.height,
      }))
      globalPrefs.value.batchMode = true
      globalPrefs.value.batchField = config.field === 'input_videos' ? 'input_videos' : 'input_images'
      if (config.field === 'input_videos') {
        globalPrefs.value.inputVideos = items
        globalPrefs.value.inputImages = []
      } else {
        globalPrefs.value.inputImages = items
        globalPrefs.value.inputVideos = []
      }
      const restQuery = { ...route.query }
      delete restQuery.loadInput
      router.replace({ query: restQuery })
      return
    }

    // Apply input based on what the tool's parameter_schema expects (keyed by
    // paramKey — the schema property/globalPrefs array — not accept type; a
    // video-only filter still restores into inputImages via input_images).
    if (mediaInputConfig.value?.paramKey === 'input_images' && config.inputImages?.length > 0) {
      const newImages = config.inputImages.map((img: any) => ({
        path: img.path,
        filename: img.filename || img.hash,
        hash: img.hash,
        mediaId: img.mediaId,
        width: img.width,
        height: img.height,
        // Preserve set fields for batch processing
        isSet: img.isSet,
        setItemCount: img.setItemCount,
        setId: img.setId
      }))
      // Untargeted sends (sidebar drop, send-to-tool) replace by default —
      // "this is the input now". Shift carries the add intent; adding keeps
      // what's there and drops overflow past the slot's capacity.
      const max = mediaInputConfig.value.max
      if (config.append && max > 1) {
        globalPrefs.value.inputImages = [...globalPrefs.value.inputImages, ...newImages].slice(0, max)
      } else {
        globalPrefs.value.inputImages = newImages.slice(0, max)
      }
    }

    if (hasVideoFrames.value && config.startImage) {
      const newFrame = {
        path: config.startImage.path,
        filename: config.startImage.filename || config.startImage.hash,
        hash: config.startImage.hash,
        mediaId: config.startImage.mediaId,
        // Carry dimensions so the output-size footer and resolution auto-match
        // work — the send-to-tool / drag payload includes them.
        width: config.startImage.width,
        height: config.startImage.height,
      }
      if (config.append) {
        // Add intent: fill the first empty frame slot; if both are filled,
        // replace the end frame (the "appended" position).
        if (!videoImages.startImage) {
          videoImages.startImage = newFrame
        } else {
          videoImages.endImage = newFrame
        }
      } else {
        // Replace intent: this image IS the animation source. A leftover end
        // frame would be stale relative to the new start, so clear it too.
        videoImages.startImage = newFrame
        videoImages.endImage = null
      }
    }

    if (config.inputVideos?.length > 0) {
      const newVideos = config.inputVideos.map((vid: any) => ({
        path: vid.path,
        filename: vid.filename || vid.hash,
        hash: vid.hash,
        mediaId: vid.mediaId,
        width: vid.width,
        height: vid.height
      }))
      // Clamp to the video slot's declared capacity (x-max-items) so no entry
      // point can over-stuff a single-video tool — MediaPicker renders whatever
      // it is handed and only gates additions made through the picker itself.
      const videoMax = mediaInputConfig.value?.paramKey === 'input_videos'
        ? mediaInputConfig.value.max
        : Infinity
      if (config.append && videoMax > 1) {
        // Add to existing videos (for video-stitch), dropping overflow past
        // capacity — same policy as the image path above.
        globalPrefs.value.inputVideos = [...globalPrefs.value.inputVideos, ...newVideos].slice(0, videoMax)
      } else {
        globalPrefs.value.inputVideos = newVideos.slice(0, videoMax)
      }
    }

    // Audio handoff (send-to-tool of an audio asset → audio-conditioned tools)
    if (config.inputAudios?.length > 0) {
      const newAudios = config.inputAudios.map((aud: any) => ({
        path: aud.path,
        filename: aud.filename || aud.hash,
        hash: aud.hash,
        mediaId: aud.mediaId,
      }))
      const max = audioInputConfig.value?.max ?? 1
      if (config.append && max > 1) {
        globalPrefs.value.inputAudios = [...globalPrefs.value.inputAudios, ...newAudios].slice(0, max)
      } else {
        globalPrefs.value.inputAudios = newAudios.slice(0, max)
      }
    }

    // Clear only the loadInput trigger; preserve project_id (and any other
    // params) so the KeepAlive component key stays on the project-scoped
    // instance instead of bouncing to the global tool.
    const restQuery = { ...route.query }
    delete restQuery.loadInput
    router.replace({ query: restQuery })
  } catch (err) {
    console.error('Failed to load pending input:', err)
    sessionStorage.removeItem(storageKey)
  }
}

// Shared function to apply a parsed GenerationConfigUpdate to the UI state.
// Used by both loadPendingGeneration() and loadRemix().
function applyAdaptedConfig(update: GenerationConfigUpdate): string {
  const applied: string[] = []

  // Apply prompt and prompt options
  if (update.prompt !== undefined) {
    globalPrefs.value.prompt = update.prompt
    applied.push('prompt')
  }
  if (update.negative_prompt !== undefined) {
    modelParams.value.negative_prompt = update.negative_prompt
  }
  if (update.promptOptions?.autoImprove) {
    globalPrefs.value.promptOptions = {
      ...globalPrefs.value.promptOptions,
      autoImprove: update.promptOptions.autoImprove
    }
  }

  // Apply LoRAs - merge with existing, never remove from UI list
  if (update.disableAllLoras) {
    toolLoras.value = toolLoras.value.map(l => ({ ...l, enabled: false }))
  } else if (update.loras && update.loras.length > 0) {
    const newLoraMap = new Map(update.loras.map(l => [l.lora, l]))
    const processedPaths = new Set<string>()

    const updatedExisting = toolLoras.value.map(existing => {
      const newConfig = newLoraMap.get(existing.lora)
      if (newConfig) {
        processedPaths.add(existing.lora)
        return { ...existing, weight: newConfig.weight, enabled: true }
      }
      return { ...existing, enabled: false }
    })

    const brandNewLoras: LoraPoolItem[] = update.loras
      .filter(l => !processedPaths.has(l.lora))
      .map(l => ({ lora: l.lora, weight: l.weight, enabled: true }))

    toolLoras.value = [...updatedExisting, ...brandNewLoras]
    applied.push(`${update.loras.length} LoRA${update.loras.length > 1 ? 's' : ''}`)
  } else {
    toolLoras.value = toolLoras.value.map(l => ({ ...l, enabled: false }))
  }

  // Apply model parameters
  const paramKeys = Object.keys(update.modelParams)
  for (const [key, value] of Object.entries(update.modelParams)) {
    (modelParams.value as any)[key] = value
  }
  if (paramKeys.length > 0) {
    // Check if only dimension params were applied vs sampling params too
    const samplingParams = paramKeys.filter(k => !['width', 'height'].includes(k))
    if (samplingParams.length > 0) {
      applied.push('sampling params')
    }
  }

  // Apply the recorded post-processing chain — same non-destructive merge
  // philosophy as LoRAs: recorded steps are enabled/configured/added, extra
  // on-screen steps are disabled (kept), active steps take the recorded order.
  if (update.postProcessingChain && update.postProcessingChain.length > 0) {
    toolChain.value = mergeRecordedChain(toolChain.value, update.postProcessingChain)
    applied.push(`${update.postProcessingChain.length}-step chain`)
  }

  // Apply source inputs — clear if not provided so stale images don't carry over
  if (update.videoImages) {
    videoImages.startImage = update.videoImages.startImage || null
    videoImages.endImage = update.videoImages.endImage || null
  } else {
    videoImages.startImage = null
    videoImages.endImage = null
  }
  if (update.inputImages) {
    globalPrefs.value.inputImages = update.inputImages
  } else {
    globalPrefs.value.inputImages = []
  }

  // Seed is not applied here — it's tracked in remixSource for the "Use Seed" button.
  // The user's current randomizeSeed setting is preserved.

  // Build summary
  const carriedOver = applied.length > 0 ? applied.join(', ') : 'dimensions'
  const resetParts: string[] = []
  const samplingWasReset = Object.keys(update.modelParams).filter(k => !['width', 'height'].includes(k)).length === 0
  if (samplingWasReset) resetParts.push('sampling params reset to defaults')
  const resetStr = resetParts.length > 0 ? `. ${resetParts.join(', ')}` : ''
  return `Carried over: ${carriedOver}${resetStr}.`
}

// Load pending generation config from sessionStorage (used for "generate more like this" and "go to tool")
async function loadPendingGeneration() {
  if (pendingGenerationApplied.value) return
  if (!route.query.loadGeneration || !tool.value) return

  const storageKey = makeToolDbKey(scopedToolId(tool.value.full_tool_id), 'pending_generation')
  const pendingConfig = sessionStorage.getItem(storageKey)
  if (!pendingConfig) return

  pendingGenerationApplied.value = true

  try {
    const data = JSON.parse(pendingConfig)
    sessionStorage.removeItem(storageKey)

    // Parse config into structured updates
    const update = parseGenerationConfig(data, {
      hasPrompt: hasPrompt.value,
      hasFrameCount: hasFrameCount.value,
      hasResolution: hasResolution.value,
      hasVideoFrames: hasVideoFrames.value,
    })
    if (!update) return

    applyAdaptedConfig(update)

    // Restore source inputs (reference images) from the hop
    const sourceInputs: any[] = data.source_inputs || []
    if (sourceInputs.length > 0) {
      if (hasVideoFrames.value) {
        // I2V tools: restore start/end frames
        for (const source of sourceInputs) {
          if (!source.file_path) continue
          try {
            const copyResp = await axios.post(
              `/api/generate/copy-to-reference?source_path=${encodeURIComponent(source.file_path)}`
            )
            const refImage = {
              path: copyResp.data.path,
              filename: copyResp.data.filename,
              mediaId: source.media_id,
              hash: copyResp.data.file_hash,
              width: copyResp.data.width,
              height: copyResp.data.height,
            }
            if (source.role === 'end_image') {
              videoImages.endImage = refImage
            } else {
              videoImages.startImage = refImage
            }
          } catch (err) {
            console.warn(`Failed to copy source input to reference:`, err)
          }
        }
      } else if (mediaInputConfig.value) {
        // Image tools: restore input images
        const restored: any[] = []
        for (const source of sourceInputs) {
          if (!source.file_path) continue
          try {
            const copyResp = await axios.post(
              `/api/generate/copy-to-reference?source_path=${encodeURIComponent(source.file_path)}`
            )
            restored.push({
              path: copyResp.data.path,
              filename: copyResp.data.filename,
              mediaId: source.media_id,
              hash: copyResp.data.file_hash,
              width: copyResp.data.width,
              height: copyResp.data.height,
              _preprocessor: source.preprocessor || null,
              _preprocessorParams: source.preprocessor_params || null,
              _paintLayerPath: source.paint_layer || null,
              _extendPadding: source.extend_padding || null,
              _extendBgColor: source.extend_bg_color || null,
              _scale: source.scale || null,
              _flip: source.flip || null,
              _crop: source.crop || null,
            })
          } catch (err) {
            console.warn(`Failed to copy source input to reference:`, err)
          }
        }
        if (restored.length > 0) {
          globalPrefs.value.inputImages = restored
        }
      }
    }

    // Restore remix source if carried from a tool hop
    if (data._remixSource) {
      remixSource.value = data._remixSource
    }

    // Clear only the loadGeneration trigger; keep project_id so we stay on the
    // project-scoped KeepAlive instance.
    const restQuery = { ...route.query }
    delete restQuery.loadGeneration
    router.replace({ query: restQuery })
  } catch (err) {
    console.error('Failed to load pending generation config:', err)
    sessionStorage.removeItem(storageKey)
  }
}

// Apply a preset carried on the route (global search preset results navigate
// here with ?preset_id=). Consumes the query param like loadPendingGeneration.
async function loadPresetFromQuery() {
  const presetId = route.query.preset_id
  if (!presetId || !tool.value) return
  try {
    if (!agentPresets.value.length) await refreshAgentPresets()
    const preset = agentPresets.value.find((p: any) => String(p.id) === String(presetId))
    if (preset) {
      handlePresetSelect(preset)
      aiPromptEditorRef.value?.setPromptText?.(globalPrefs.value.prompt || '')
    }
  } catch (err) {
    console.error('Failed to apply preset from query:', err)
  } finally {
    const restQuery = { ...route.query }
    delete restQuery.preset_id
    router.replace({ query: restQuery })
  }
}

// Load generation config from a media item (remix flow)
//
// loadRemix can fire more than once for a single remix — both the loadTool init
// path and the route-query watcher trigger it — so it MUST be re-entrancy safe.
// We stamp each call with a sequence number and bail after every await if a newer
// call has started, so a stale invocation can't clobber the winner's state. We
// also resolve the source frames into reference images BEFORE mutating UI state,
// then apply config + assign the frames synchronously — otherwise applyAdaptedConfig
// clears the frame picker and it stays empty across the awaited copy-to-reference
// (the bug where an i2v remix lands with no start frame populated).
let loadRemixSeq = 0
async function loadRemix(mediaId: string) {
  if (!tool.value) return

  const mySeq = ++loadRemixSeq
  loadingGenerationConfig.value = true

  try {
    const response = await axios.post(
      `/api/generate/config-from-media/${mediaId}?target_tool_id=${tool.value.full_tool_id}`
    )
    if (loadRemixSeq !== mySeq) return  // superseded by a newer remix
    const data = response.data

    // Parse config into structured updates
    const update = parseGenerationConfig(data, {
      hasPrompt: hasPrompt.value,
      hasFrameCount: hasFrameCount.value,
      hasResolution: hasResolution.value,
      hasVideoFrames: hasVideoFrames.value,
    })
    if (!update) return

    // Resolve source inputs for the target tool BEFORE touching UI state:
    // - I2V tools: use the ORIGINAL source inputs (start/end frames from the generation)
    //   NOT the output video — you want to re-generate from the same start frame
    // - Image-edit tools: use the remix source image itself as the input
    //   (the user wants to re-edit that result, not its ancestors)
    const sourceInputs: any[] = data.source_inputs || []
    const restoreVideoFrames = hasVideoFrames.value
    let resolvedStart: any = null
    let resolvedEnd: any = null
    let resolvedInputs: typeof globalPrefs.value.inputImages | null = null

    if (restoreVideoFrames && sourceInputs.length > 0) {
      // I2V: restore original start/end frames
      for (const source of sourceInputs) {
        if (!source.file_path) continue
        try {
          const copyResp = await axios.post(
            `/api/generate/copy-to-reference?source_path=${encodeURIComponent(source.file_path)}`
          )
          if (loadRemixSeq !== mySeq) return  // superseded mid-copy
          const refImage = {
            path: copyResp.data.path,
            filename: copyResp.data.filename,
            mediaId: source.media_id,
            hash: copyResp.data.file_hash,
            width: copyResp.data.width,
            height: copyResp.data.height,
          }
          if (source.role === 'end_image') {
            resolvedEnd = refImage
          } else {
            resolvedStart = refImage
          }
        } catch (err) {
          console.warn(`Failed to copy source input (${source.role}) to reference:`, err)
        }
      }
    } else if (mediaInputConfig.value) {
      // For image-to-image tools: restore the original source inputs (reference images) if they exist.
      // If the source was t2i (no source inputs), don't populate inputImages — let the tool stay in t2i mode.
      const editSourceInputs = sourceInputs.filter((s: any) => s.role !== 'start_image' && s.role !== 'end_image')
      if (editSourceInputs.length > 0) {
        // Original was image-to-image: restore the original input images, not the output
        const restoredImages: typeof globalPrefs.value.inputImages = []
        for (const source of editSourceInputs) {
          if (!source.file_path) continue
          try {
            const copyResp = await axios.post(
              `/api/generate/copy-to-reference?source_path=${encodeURIComponent(source.file_path)}`
            )
            if (loadRemixSeq !== mySeq) return  // superseded mid-copy
            restoredImages.push({
              path: copyResp.data.path,
              filename: copyResp.data.filename,
              mediaId: source.media_id,
              hash: copyResp.data.file_hash,
              width: copyResp.data.width,
              height: copyResp.data.height,
              _preprocessor: source.preprocessor || null,
              _preprocessorParams: source.preprocessor_params || null,
              _paintLayerPath: source.paint_layer || null,
              _extendPadding: source.extend_padding || null,
              _extendBgColor: source.extend_bg_color || null,
              _scale: source.scale || null,
              _flip: source.flip || null,
              _crop: source.crop || null,
            })
          } catch (err) {
            console.warn('Failed to copy source input to reference:', err)
          }
        }
        if (restoredImages.length > 0) {
          resolvedInputs = restoredImages
        }
      }
      // If no edit source inputs (t2i source), don't set inputImages — tool stays in t2i mode
    }

    // Everything below is synchronous: apply config (which clears frames/inputs)
    // then immediately reinstate the resolved source images, so the picker goes
    // straight from old → restored with no empty intermediate frame.
    if (loadRemixSeq !== mySeq) return
    applyAdaptedConfig(update)
    if (restoreVideoFrames) {
      videoImages.startImage = resolvedStart
      videoImages.endImage = resolvedEnd
    } else if (resolvedInputs) {
      globalPrefs.value.inputImages = resolvedInputs
    }

    // Set remix source
    remixSource.value = {
      mediaId: Number(mediaId),
      promptSnippet: data.source_prompt_snippet || '',
      renderedPrompt: data.prompt_variants?.rendered || undefined,
      seed: data.seed ?? null,
      promptMetadata: data.prompt_metadata || undefined,
    }

    // Clear only the remix trigger params; keep project_id so we stay on the
    // project-scoped KeepAlive instance.
    const restQuery = { ...route.query }
    delete restQuery.remixFrom
    delete restQuery.inspireFrom
    delete restQuery.loadFromMedia
    router.replace({ query: restQuery })
  } catch (err) {
    console.error('Failed to load remix from media:', err)
  } finally {
    if (loadRemixSeq === mySeq) loadingGenerationConfig.value = false
  }
}

// Handle hopping to another tool with current state
async function handleHopToTool(targetTool: { full_tool_id: string; name: string }, targetTab?: { projectId?: number; instanceId?: string }) {
  if (!tool.value) return

  trackTelemetry('tool_hop_used', {
    _fromToolId: tool.value.full_tool_id,
    _toToolId: targetTool.full_tool_id,
  }, 'generation')

  loadingGenerationConfig.value = true

  try {
    // Extract current state for transfer
    const currentLoras = toolLoras.value.map(l => ({
      lora: l.lora,
      weight: l.weight,
      enabled: l.enabled
    }))

    // Collect input images: regular input images + video frames
    const allInputImages: any[] = [...(globalPrefs.value.inputImages || [])]
    if (videoImages.startImage) {
      allInputImages.push({ ...videoImages.startImage, role: 'start_image' })
    }
    if (videoImages.endImage) {
      allInputImages.push({ ...videoImages.endImage, role: 'end_image' })
    }

    // Call backend to exact-match loras to target tool
    const response = await axios.post('/api/generate/config-for-tool-hop', {
      target_tool_id: targetTool.full_tool_id,
      prompt: globalPrefs.value.prompt || '',
      negative_prompt: modelParams.value.negative_prompt || '',
      input_images: allInputImages,
      current_loras: currentLoras
    })

    const hopConfig = response.data

    // Store config in sessionStorage for the target tool to pick up.
    // An explicitly picked instance tab wins; otherwise target the
    // most-recent open instance of the target tool in THIS view's project
    // scope (hop previously dropped project scope). Key is instance-scoped.
    const { resolveToolInstance } = _tabsForFeed
    const hopProjectId = targetTab ? (targetTab.projectId ?? null) : ownProjectScopeId
    const hopInstanceId = targetTab?.instanceId
      ?? resolveToolInstance(targetTool.full_tool_id, hopProjectId).instanceId
    const storageKey = makeToolDbKey(toolInstanceScopedId(targetTool.full_tool_id, hopProjectId, hopInstanceId), 'pending_generation')
    const payload: Record<string, any> = {
      prompt: hopConfig.prompt,
      negative_prompt: hopConfig.negative_prompt,
      loras: hopConfig.matched_loras,
      // Carry the ORIGINAL (pre-prep) path plus all non-destructive prep settings
      // so the target tool re-applies them rather than baking onto an already-prepped image.
      source_inputs: (hopConfig.input_images || []).map((img: any) => ({
        file_path: img._originalPath || img.path || img.file_path,
        media_id: img.mediaId ?? img.media_id,
        preprocessor: img._preprocessor || img.preprocessor || null,
        preprocessor_params: img._preprocessorParams || img.preprocessor_params || null,
        paint_layer: img._paintLayerPath || img.paint_layer || null,
        extend_padding: img._extendPadding || img.extend_padding || null,
        extend_bg_color: img._extendBgColor || img.extend_bg_color || null,
        scale: img._scale || img.scale || null,
        flip: img._flip || img.flip || null,
        crop: img._crop || img.crop || null,
        role: img.role || null,
      })),
      // Don't transfer sampling params - let target tool use its defaults
    }

    // Carry forward inspiration source if set
    if (remixSource.value) {
      payload._remixSource = remixSource.value
    }

    sessionStorage.setItem(storageKey, JSON.stringify(payload))

    // Navigate to target tool instance
    router.push(toolInstanceRoute(targetTool.full_tool_id, hopProjectId, hopInstanceId, {
      loadGeneration: Date.now().toString(),  // Force detection for KeepAlive'd components
    }))
  } catch (err) {
    console.error('Failed to hop to tool:', err)
  } finally {
    loadingGenerationConfig.value = false
  }
}

// Job submission
// Run click: queue `batchSize` generations back-to-back. A batch is just the
// shortcut to pressing Run N times — no grouping. Each iteration captures the
// current seed and (when randomize is on) rolls a fresh one for the next, so a
// batch yields N distinct seeds exactly as repeated clicks would.
type ForeverSubmitOptions = {
  foreverBackendName?: string
  foreverSessionId?: number
  foreverReserved?: boolean
}

type SubmitJobResult = {
  submitted: boolean
  declineReservation: boolean
}

function isForeverSubmissionCurrent(options: ForeverSubmitOptions): boolean {
  if (options.foreverSessionId == null) return true
  return uiState.value.generateForeverMode && options.foreverSessionId === foreverModeSessionId.value
}

function noSubmit(options: ForeverSubmitOptions, declineReservation = true): SubmitJobResult {
  return {
    submitted: false,
    declineReservation: declineReservation && options.foreverReserved !== false,
  }
}

async function submitJob(options: ForeverSubmitOptions = {}): Promise<SubmitJobResult> {
  if (!tool.value || !canSubmit.value) return noSubmit(options)
  if (!isForeverSubmissionCurrent(options)) return noSubmit(options, false)

  // A dropped video becomes an image only after an async frame grab. If the user
  // hits Run before that settles, wait for it (and one more pass in case a drop
  // landed mid-flight) so we never submit a raw video to an image tool.
  await normalizeVideoInputsToFrames()
  await normalizeVideoInputsToFrames()
  if (hasPendingVideoInput()) {
    submissionError.value = "Couldn't turn the dropped video into a frame — remove it and try again."
    addToast(submissionError.value, 'error')
    return noSubmit(options)
  }
  if (!isForeverSubmissionCurrent(options)) return noSubmit(options, false)

  const count = options.foreverBackendName
    ? 1
    : Math.min(8, Math.max(1, uiState.value.batchSize || 1))
  let submitted = false
  let declineReservation = true
  for (let i = 0; i < count; i++) {
    const result = await submitOneJob(options)
    submitted = result.submitted || submitted
    declineReservation = result.declineReservation
  }
  return { submitted, declineReservation }
}

function recordUnsubmittedForeverWork(options: ForeverSubmitOptions) {
  if (!isForeverSubmissionCurrent(options)) return
  if (options.foreverBackendName && options.foreverReserved !== false) {
    declineWorkRequest(options.foreverBackendName)
  }
  void recordForeverFailure()
}

async function submitOneJob(options: ForeverSubmitOptions = {}): Promise<SubmitJobResult> {
  if (!tool.value || !canSubmit.value) {
    return noSubmit(options)
  }
  if (!isForeverSubmissionCurrent(options)) return noSubmit(options, false)

  submissionError.value = null
  submissionErrorCode.value = null

  // Ensure seed exists
  if (!modelParams.value.seed) {
    modelParams.value.seed = generateRandomSeed()
  }

  // Build state for payload builder
  const builderState: PayloadBuilderState = {
    globalPrefs: globalPrefs.value as any,
    modelParams: modelParams.value,
    videoImages,
    maskDataUrl: maskDataUrl.value,
    enabledLoras: getToolEnabledLoras(),
    inputImageWidth: inputImageWidth.value,
    inputImageHeight: inputImageHeight.value,
    finalResolution: finalResolution.value,
  }

  const builderConfig: PayloadBuilderConfig = {
    tool: tool.value as any,
    generatorInstanceId,
    autoDeleteDuration: autoDeleteDuration.value,
    projectId: projectScopeId.value,
  }

  // Execute pre-upload tasks (e.g., mask upload for inpaint)
  const uploadResults: Record<string, any> = {}
  const preUploadTasks = getPreUploadTasks(builderConfig, builderState)

  for (const task of preUploadTasks) {
    try {
      Object.assign(uploadResults, await task())
    } catch (err: any) {
      console.error('Pre-upload task failed:', err)
      submissionError.value = err.response?.data?.detail || 'Upload failed'
      return noSubmit(options)
    }
  }
  if (!isForeverSubmissionCurrent(options)) return noSubmit(options, false)

  // Build captured state from schema
  const capturedState = buildCapturedState(builderConfig, builderState, uploadResults)

  // Thread inspiration lineage into parameters
  if (remixSource.value) {
    capturedState.parameters.inspired_by_media_id = remixSource.value.mediaId
  }

  // Attach the post-processing chain (enabled steps, in run order). It rides
  // job parameters so it lands in generation_metadata.parameters and triggers
  // the chain executor when the base generation completes.
  if (toolChain.value.enabled) {
    const recordedSteps = toRecordedSteps(toolChain.value)
    if (recordedSteps.length > 0) {
      capturedState.parameters.post_processing_chain = recordedSteps
    }
  }

  // Randomize seed for next submission (after capturing current seed)
  if (modelParams.value.randomizeSeed) {
    modelParams.value.seed = generateRandomSeed()
  }

  // Build base payload
  const basePayload = buildBasePayload(builderConfig, builderState)

  // Check for prompt enhancement
  const toolHasPrompt = hasPromptFeature(builderConfig)
  const prompt = capturedState.parameters.prompt || ''
  // Enhance Prompt is family-aware: thread the tool's model + enhancement mode
  // into the generate-time pipeline. The backend picks the style from the model;
  // Ideogram (mode 'ideogram-json') runs as the post-resolve JSON step.
  const rawPromptOptions = capturedState.promptOptions
  const promptOptions = rawPromptOptions
    ? {
        ...rawPromptOptions,
        // Tools with no prompt input have nothing to enhance or translate —
        // force both off here rather than trusting stale UI state left over
        // from a previously-selected prompt tool (autoImprove.enabled/translate
        // panels are shared, generic components).
        autoImprove: {
          ...rawPromptOptions.autoImprove,
          enabled: toolHasPrompt && !!rawPromptOptions.autoImprove?.enabled,
          model: toolModelString.value || null,
          // Task-authoritative: video tools always get cinematography.
          isVideo: enhanceIsVideo.value,
          // Task-authoritative: audio tools always get the sound-focused style.
          isAudio: enhanceIsAudio.value,
          // Input images on a non-video tool → edit-style enhancement.
          inputImageCount: enhanceInputImageCount.value,
          mode: enhanceMode.value,
          // i2v: source frame for the enhancer (used on the cinematography path).
          mediaId: enhanceSourceMediaId.value,
        },
        translate: {
          ...rawPromptOptions.translate,
          enabled: toolHasPrompt && !!rawPromptOptions.translate?.enabled,
        },
      }
    : rawPromptOptions
  const enhanceOn = !!promptOptions?.autoImprove?.enabled

  // Ideogram JSON needs the real canvas so the model composes layout/bboxes for
  // the right aspect ratio (Ideogram 4 uses fixed width×height presets).
  const imageSize = enhanceOn && enhanceMode.value === 'ideogram-json'
    ? { width: Number(capturedState.parameters?.width) || null, height: Number(capturedState.parameters?.height) || null }
    : undefined

  // Show a pending placeholder whenever the generate-time prompt pipeline may
  // do LLM work. Enhancement happens server-side at submit time (either from
  // the forever-mode warm pool or synchronously), so keep the slot visibly
  // active until the backend emits the real queued job.
  const needsEnhancing = toolHasPrompt && (
    enhanceOn ||
    promptOptions?.translate?.enabled
  )
  const pendingId = needsEnhancing
    ? jobsManager.addPendingJob(prompt, { model_name: tool.value!.model, generator_name: tool.value!.generator })
    : null
  const finishPendingStatus = pendingId ? beginInstanceWork(generatorInstanceId) : null
  const removePendingEnhancementJob = () => {
    if (!pendingId) return
    jobsManager?.removePendingJob(pendingId)
    finishPendingStatus?.()
  }

  // Media-batch: run the tool once per item in the batched slot.
  if (globalPrefs.value.batchMode) {
    const batchField = globalPrefs.value.batchField || 'input_images'
    const mediaIds = mediaInputItems.value.map((i: any) => i.mediaId).filter(Boolean)
    if (mediaIds.length === 0) {
      submissionError.value = 'Batch slot has no library items to run'
      removePendingEnhancementJob()
      return noSubmit(options)
    }
    const trackForeverBatchSubmit = options.foreverSessionId != null && isForeverSubmissionCurrent(options)
    if (trackForeverBatchSubmit) foreverModeBatchSubmitInFlight.value = true
    const clearForeverBatchSubmit = () => {
      if (trackForeverBatchSubmit) foreverModeBatchSubmitInFlight.value = false
    }

    // Backend injects the batched media (and its prep) per item, so strip those
    // fields from the shared parameters.
    const batchParameters: Record<string, any> = { ...capturedState.parameters }
    const mediaIdField = batchField === 'input_videos' ? 'input_video_media_ids' : 'input_media_ids'
    for (const k of [batchField, mediaIdField, '_original_input_paths', '_original_input_hashes',
      '_input_preprocessors', '_input_preprocessor_params', '_input_paint_layers',
      '_input_extend_padding', '_input_extend_bg_colors', '_input_scales', '_input_flips',
      '_input_crops']) {
      delete batchParameters[k]
    }

    // Uniform batch-safe prep, read from the representative item (the prep the
    // user set on the collapsed stack tile). Backend applies it to every item.
    const rep: any = mediaInputItems.value[0] || {}
    const prep: Record<string, any> = {}
    if (rep._scale) prep.scale = rep._scale
    if (rep._flip) prep.flip = rep._flip
    if (rep._crop) prep.crop = rep._crop
    if (rep._preprocessor) {
      prep.preprocessor = rep._preprocessor
      prep.preprocessor_params = rep._preprocessorParams || null
    }
    if (rep._extendPadding) {
      prep.extend_padding = rep._extendPadding
      prep.extend_bg_color = rep._extendBgColor || null
    }

    const constantInputs = extractMediaBatchConstantInputs(batchParameters, batchField)

    submitMediaBatchJobAsync({
      prompt,
      promptOptions,
      imageSize,
      buildPayload: (processedPrompt, promptMetadata) => ({
        ...basePayload,
        prompt_options: promptOptions || undefined,
        forever_work_reserved: options.foreverReserved === true,
        batch_input: { field: batchField, media_ids: mediaIds },
        constant_inputs: constantInputs,
        parameters: { ...batchParameters, ...(toolHasPrompt ? { prompt: processedPrompt } : {}) },
        prep: Object.keys(prep).length ? prep : undefined,
        prompt_metadata: promptMetadata,
      }),
      shouldSubmit: () => isForeverSubmissionCurrent(options),
      onCancelled: () => {
        removePendingEnhancementJob()
        clearForeverBatchSubmit()
      },
      onSubmitted: (batchInfo: BatchJobResponse) => {
        removePendingEnhancementJob()
        console.log(`Media-batch submitted: ${batchInfo.total_jobs} jobs, batch_id: ${batchInfo.batch_id}`)
        if (uiState.value.generateForeverMode) {
          foreverModeActiveBatchId.value = batchInfo.batch_id
        }
        clearForeverBatchSubmit()
      },
      onError: (err: any) => {
        removePendingEnhancementJob()
        clearForeverBatchSubmit()
        submissionError.value = classifySubmissionError(err)
      },
      onNoBackendSubmission: () => {
        clearForeverBatchSubmit()
        recordUnsubmittedForeverWork(options)
      },
      onBackendRejected: () => {
        clearForeverBatchSubmit()
        void recordForeverFailure()
      },
    })
    return { submitted: true, declineReservation: false }
  }

  // Check if this is a batch submission (any input has a set)
  const inputImages = globalPrefs.value.inputImages || []
  const hasSetInput = inputImages.some((img: any) => img.isSet)

  if (hasSetInput) {
    // Batch submission - convert set inputs to set_id format
    const setInput = inputImages.find((img: any) => img.isSet)
    if (!setInput?.setId) {
      console.error('Set input missing setId')
      submissionError.value = 'Invalid set input'
      removePendingEnhancementJob()
      return noSubmit(options)
    }
    const trackForeverBatchSubmit = options.foreverSessionId != null && isForeverSubmissionCurrent(options)
    if (trackForeverBatchSubmit) foreverModeBatchSubmitInFlight.value = true
    const clearForeverBatchSubmit = () => {
      if (trackForeverBatchSubmit) foreverModeBatchSubmitInFlight.value = false
    }

    // Build parameters with set reference for the first media input
    const batchParameters = { ...capturedState.parameters }

    // Find the input field name for images (could be input_image, input_images, etc.)
    const mediaInputFields = ['input_image', 'input_images', 'image', 'images', 'source_image']
    for (const field of mediaInputFields) {
      if (field in batchParameters) {
        batchParameters[field] = { set_id: setInput.setId }
        break
      }
    }

    // Submit batch job
    submitBatchJobAsync({
      prompt,
      promptOptions,
      imageSize,
      buildPayload: (processedPrompt, promptMetadata) => ({
        ...basePayload,
        prompt_options: promptOptions || undefined,
        forever_work_reserved: options.foreverReserved === true,
        parameters: {
          ...batchParameters,
          ...(toolHasPrompt ? { prompt: processedPrompt } : {}),
        },
        prompt_metadata: promptMetadata,
        // Let backend generate smart title from input set info
      }),
      shouldSubmit: () => isForeverSubmissionCurrent(options),
      onCancelled: () => {
        removePendingEnhancementJob()
        clearForeverBatchSubmit()
      },
      onSubmitted: (batchInfo: BatchJobResponse) => {
        removePendingEnhancementJob()
        console.log(`Batch submitted: ${batchInfo.total_jobs} jobs, batch_id: ${batchInfo.batch_id}`)
        // Track active batch for forever mode (batches run sequentially)
        if (uiState.value.generateForeverMode) {
          foreverModeActiveBatchId.value = batchInfo.batch_id
        }
        clearForeverBatchSubmit()
      },
      onError: (err: any) => {
        removePendingEnhancementJob()
        clearForeverBatchSubmit()
        submissionError.value = classifySubmissionError(err)
      },
      onNoBackendSubmission: () => {
        clearForeverBatchSubmit()
        recordUnsubmittedForeverWork(options)
      },
      onBackendRejected: () => {
        clearForeverBatchSubmit()
        void recordForeverFailure()
      },
    })
  } else {
    // Regular single-job submission
    submitJobAsync({
      prompt,
      promptOptions,
      imageSize,
      buildPayload: (processedPrompt, promptMetadata) => ({
        ...basePayload,
        prompt_options: promptOptions || undefined,
        forever_work_reserved: options.foreverReserved === true,
        parameters: {
          ...capturedState.parameters,
          ...(toolHasPrompt ? { prompt: processedPrompt } : {}),  // Override with processed prompt
        },
        prompt_metadata: promptMetadata,
      }),
      shouldSubmit: () => isForeverSubmissionCurrent(options),
      onCancelled: removePendingEnhancementJob,
      onSubmitted: removePendingEnhancementJob,
      onError: (err: any) => {
        removePendingEnhancementJob()
        submissionError.value = classifySubmissionError(err)
      },
      onNoBackendSubmission: () => {
        recordUnsubmittedForeverWork(options)
      },
      onBackendRejected: () => {
        void recordForeverFailure()
      },
    })
  }

  return { submitted: true, declineReservation: false }
}

function mediaIdCompanionField(field: string): string {
  if (field === 'input_images') return 'input_media_ids'
  if (field === 'input_videos') return 'input_video_media_ids'
  if (field === 'input_audios') return 'input_audio_media_ids'
  return `${field}_media_id`
}

function isSchemaMediaField(name: string, schema: any): boolean {
  if (!schema) return false
  if (name === 'input_images' || name === 'input_videos' || name === 'input_audios') return true
  const type = String(schema.type || '').toLowerCase()
  const format = String(schema.format || schema['x-format'] || '').toLowerCase()
  const control = String(schema['x-control'] || '').toLowerCase()
  return (
    type === 'media' ||
    format.includes('image') ||
    format.includes('video') ||
    format.includes('audio') ||
    control.includes('image') ||
    control.includes('video') ||
    control.includes('audio') ||
    /(^|_)(image|video|audio)s?$/.test(name)
  )
}

function firstMediaId(value: any): number | null {
  const candidate = Array.isArray(value) ? value[0] : value
  const n = Number(candidate)
  return Number.isFinite(n) && n > 0 ? n : null
}

function extractMediaBatchConstantInputs(parameters: Record<string, any>, batchField: string): Record<string, number> {
  const props = tool.value?.parameter_schema?.properties || {}
  const constants: Record<string, number> = {}

  for (const [field, schema] of Object.entries(props)) {
    if (field === batchField) continue
    if (!isSchemaMediaField(field, schema)) continue

    const companion = mediaIdCompanionField(field)
    const mediaId = firstMediaId(parameters[companion] ?? parameters[`${field}_media_id`])
    if (!mediaId) continue

    constants[field] = mediaId
    delete parameters[field]
    delete parameters[companion]
    delete parameters[`${field}_media_id`]
  }

  return constants
}

// Forever mode
async function startForeverMode(concurrency: number) {
  if (!tool.value) return
  if (uiState.value.generateForeverMode) {
    await stopForeverMode()
  }
  foreverModeSessionId.value++
  uiState.value.generateForeverMode = true
  modelParams.value.randomizeSeed = true
  foreverModeIdleCount.value = 0  // Reset idle counter on start
  consecutiveFailures.value = 0
  foreverModeBatchSubmitInFlight.value = false
  workRequestQueue.value = []
  try {
    await axios.post(`${API_BASE}/generate/forever/register`, null, {
      params: {
        generator_instance_id: generatorInstanceId,
        backend_name: tool.value.generator,
        max_concurrency: concurrency,
        tool_id: tool.value.full_tool_id
      }
    })
  } catch (err) {
    console.error('Failed to register forever mode:', err)
  }
}

async function stopForeverMode() {
  if (!tool.value) return
  foreverModeSessionId.value++
  uiState.value.generateForeverMode = false
  foreverModeActiveBatchId.value = null  // Clear active batch tracking
  foreverModePendingBatchCompletion.value = null
  foreverModeBatchSubmitInFlight.value = false
  workRequestQueue.value = []
  // Belt-and-suspenders: /forever/unregister below already tears down the
  // warm pool server-side, but that call can fail (caught/logged, not
  // retried) - clearing directly against the pool's own endpoint means the
  // pool doesn't outlive forever mode even if unregister doesn't land.
  clearPromptWarmPool()
  try {
    await axios.post(`${API_BASE}/generate/forever/unregister`, null, {
      params: {
        generator_instance_id: generatorInstanceId,
        backend_name: tool.value.generator,
        tool_id: tool.value.full_tool_id
      }
    })
  } catch (err) {
    console.error('Failed to unregister forever mode:', err)
  }
}

// Re-registers forever mode after a WebSocket reconnect, retrying with capped
// backoff until it succeeds rather than giving up after a fixed count (see
// call site in the wsConnected watcher for why a silent give-up is unsafe).
// Bails early if forever mode was stopped or restarted (new session id) while
// waiting, so an old reconnect's retry loop can't stomp on a fresh one.
async function reregisterForeverModeWithRetry() {
  if (!tool.value) return
  const session = foreverModeSessionId.value
  const stillCurrent = () =>
    uiState.value.generateForeverMode && foreverModeSessionId.value === session

  // Small initial delay to give backend HTTP routes a moment to come up.
  await new Promise(resolve => setTimeout(resolve, 500))

  const delaysMs = [1000, 2000, 4000, 8000, 8000, 8000, 8000, 8000]
  let attempt = 0
  while (stillCurrent()) {
    try {
      await axios.post(`${API_BASE}/generate/forever/register`, null, {
        params: {
          generator_instance_id: generatorInstanceId,
          backend_name: tool.value.generator,
          max_concurrency: uiState.value.generateForeverConcurrency,
          tool_id: tool.value.full_tool_id
        }
      })
      if (attempt > 0) submissionError.value = null
      return
    } catch (err) {
      console.error(`Failed to re-register forever mode (attempt ${attempt + 1}):`, err)
      if (attempt === 2) {
        // Surface it after a few failures so this isn't silent, but keep
        // retrying in the background rather than giving up.
        submissionError.value = 'Reconnecting generate-forever mode...'
      }
      const delay = delaysMs[Math.min(attempt, delaysMs.length - 1)]
      await new Promise(resolve => setTimeout(resolve, delay))
      attempt++
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════
// Prompt-editor mini-agent: command surface + state context + undo + provide.
// The agent operates this screen with parity to the user; runTool maps each
// backend tool name to the same effect a user action has.
// ══════════════════════════════════════════════════════════════════════════

const aiPromptEditorRef = ref<InstanceType<typeof AIPromptEditor> | null>(null)
// Page-level agent chat. Owns the suggestion categories/ideas the agent's
// category tools operate on (the prompt editor is now just an editor).
const promptAgentChatRef = ref<InstanceType<typeof PromptAgentChat> | null>(null)
const mediaPickerRef = ref<InstanceType<typeof MediaPicker> | null>(null)

// Presets the agent can list/apply. Loaded on mount + after a save (the
// PresetPicker keeps its own copy; this is the agent's view for state_context).
const { getPresetsForTool: agentGetPresets, saveAsPreset: agentSaveAsPreset } = usePresetsApi()
const agentPresets = ref<any[]>([])
async function refreshAgentPresets() {
  const id = tool.value?.full_tool_id
  if (!id) return
  try {
    agentPresets.value = await agentGetPresets(id)
  } catch {
    /* non-fatal — presets just won't show in state_context */
  }
}

// --- Full-content undo (one snapshot per agent run; pill edits snapshot too) ---
interface EditorSnapshot {
  prompt: string
  promptOptions: any
  inputImages: any[]
  modelParams: Record<string, any>
  autoMarkerIds: number[]
  categories: any
  // The chain is part of the undo snapshot (unlike the LoRA pool, which is
  // deliberately outside it) — editing the chain is a prompt-altitude action.
  postProcessingChain: PostProcessingChain
}

const undo = usePromptEditorUndo<EditorSnapshot>({
  capture: () => ({
    prompt: globalPrefs.value.prompt,
    promptOptions: JSON.parse(JSON.stringify(globalPrefs.value.promptOptions ?? null)),
    inputImages: JSON.parse(JSON.stringify(globalPrefs.value.inputImages ?? [])),
    modelParams: JSON.parse(JSON.stringify(modelParams.value ?? {})),
    autoMarkerIds: [...(globalPrefs.value.autoMarkerIds ?? [])],
    categories: promptAgentChatRef.value?.getCategoriesSnapshot
      ? JSON.parse(JSON.stringify(promptAgentChatRef.value.getCategoriesSnapshot()))
      : null,
    postProcessingChain: JSON.parse(JSON.stringify(toolChain.value)),
  }),
  restore: (snap) => {
    globalPrefs.value.prompt = snap.prompt
    aiPromptEditorRef.value?.setPromptText?.(snap.prompt)
    if (snap.promptOptions != null) globalPrefs.value.promptOptions = JSON.parse(JSON.stringify(snap.promptOptions))
    globalPrefs.value.inputImages = JSON.parse(JSON.stringify(snap.inputImages ?? []))
    modelParams.value = JSON.parse(JSON.stringify(snap.modelParams ?? {}))
    globalPrefs.value.autoMarkerIds = [...(snap.autoMarkerIds ?? [])]
    if (snap.categories && promptAgentChatRef.value?.setCategoriesSnapshot) {
      promptAgentChatRef.value.setCategoriesSnapshot(snap.categories)
    }
    if (snap.postProcessingChain) {
      toolChain.value = normalizeChain(snap.postProcessingChain)
    }
  },
})

// --- Helpers ---------------------------------------------------------------

// Keys that are NOT plain parameters: loras and seed have dedicated tools, and
// the resolution controls (width/height/megapixels/aspect_ratio/image_size) are
// driven only through set_resolution. Excluding them keeps
// state_context.parameter_schema consistent with the agent_system_prompt, which
// tells the model these size keys live in state_context.resolution, not
// parameter_schema.
const PARAM_SCHEMA_EXCLUDE = new Set([
  'loras', 'seed',
  'width', 'height', 'megapixels', 'aspect_ratio', 'image_size',
])

// Param schema map: name -> { type, min, max, step, enum }. Drawn from the
// tool's parameter_schema so the agent never sets an out-of-range value.
function getParamSchemaMap(): Record<string, any> {
  const props = parameterSchema.value?.properties || {}
  const out: Record<string, any> = {}
  for (const [name, raw] of Object.entries<any>(props)) {
    if (PARAM_SCHEMA_EXCLUDE.has(name)) continue
    // The upscale picker (scale factor / short-edge) is a dedicated control fed
    // by UI-only keys (scaleFactor/resolutionMode/targetResolution), driven via
    // set_resolution. Its backing schema param (e.g. `resolution`) must NOT leak
    // into parameter_schema, or the agent would set_parameter a key the picker
    // ignores — reporting success while the UI never moves.
    if (raw['x-control'] === 'upscale_resolution') continue
    const entry: any = { type: raw.type || 'string' }
    if (raw.minimum != null) entry.min = raw.minimum
    if (raw.maximum != null) entry.max = raw.maximum
    if (raw['x-step'] != null || raw.step != null) entry.step = raw['x-step'] ?? raw.step
    if (Array.isArray(raw.enum)) entry.enum = raw.enum
    out[name] = entry
  }
  return out
}

// Coerce/validate a parameter value against its schema. Returns { value } or { error }.
function coerceParamValue(name: string, value: any): { value?: any; error?: string } {
  const schema = getParamSchemaMap()[name]
  if (!schema) return { error: `Unknown parameter "${name}". See parameter_schema for valid keys.` }
  if (schema.enum && !schema.enum.includes(value)) {
    return { error: `Invalid value for "${name}". Allowed: ${schema.enum.join(', ')}.` }
  }
  if (schema.type === 'number' || schema.type === 'integer') {
    let num = Number(value)
    if (Number.isNaN(num)) return { error: `"${name}" expects a number.` }
    if (schema.type === 'integer') num = Math.round(num)
    if (schema.min != null && num < schema.min) return { error: `"${name}" min is ${schema.min}.` }
    if (schema.max != null && num > schema.max) return { error: `"${name}" max is ${schema.max}.` }
    return { value: num }
  }
  if (schema.type === 'boolean') {
    // Values arrive as strings from the agent — parse, don't truthy-coerce
    // ("false" is a truthy string).
    if (typeof value === 'string') {
      const v = value.trim().toLowerCase()
      return { value: v === 'true' || v === '1' || v === 'yes' || v === 'on' }
    }
    return { value: !!value }
  }
  return { value: String(value) }
}

// Resolve a LoRA reference (name or path) against available + selected lists.
function resolveLora(ref: string): { path: string; name: string } | null {
  if (!ref) return null
  const needle = ref.toLowerCase().trim()
  const pool: Array<{ path: string; name: string }> = availableLoras.value.map((l: any) => ({ path: l.path, name: l.name }))
  // Exact path or name first.
  let hit = pool.find(l => l.path.toLowerCase() === needle || l.name.toLowerCase() === needle)
  if (hit) return hit
  // Substring on name or path.
  hit = pool.find(l => l.name.toLowerCase().includes(needle) || l.path.toLowerCase().includes(needle))
  if (hit) return hit
  // Keyword overlap.
  const tokens = needle.split(/\s+/).filter(Boolean)
  hit = pool.find(l => {
    const hay = (l.name + ' ' + l.path).toLowerCase()
    return tokens.every(t => hay.includes(t))
  })
  return hit || null
}

// Resolve a chain step reference — step id, 1-based position, or name — to
// its index in toolChain. Returns an error string when nothing matches.
function resolveChainStep(ref: any): { step: ChainStep; index: number } | string {
  const steps = toolChain.value.steps
  if (!steps.length) return 'The post-processing chain is empty.'
  const want = String(ref ?? '').trim()
  if (!want) return 'A step reference (id, position, or name) is required.'
  // Exact id
  let index = steps.findIndex(s => s.id === want)
  // 1-based position
  if (index < 0 && /^\d+$/.test(want)) {
    const pos = parseInt(want, 10) - 1
    if (pos >= 0 && pos < steps.length) index = pos
  }
  // Name (tool name / filter id) substring
  if (index < 0) {
    const needle = want.toLowerCase()
    index = steps.findIndex(s =>
      (s.kind === 'tool' ? `${s.tool_name || ''} ${s.tool_id || ''}` : (s.filter_id || ''))
        .toLowerCase().includes(needle)
    )
  }
  if (index < 0) {
    return `No chain step matches "${want}". See state_context.post_processing.steps.`
  }
  return { step: steps[index], index }
}

// Mutate the chain immutably so the tool-state watcher and panel both react.
function updateToolChainSteps(mutate: (steps: ChainStep[]) => ChainStep[]) {
  toolChain.value = { ...toolChain.value, steps: mutate([...toolChain.value.steps]) }
}

// Drive the resolution picker(s) with parity to the user. Resolution is a
// dedicated multi-mode control, not a parameter_schema entry, so it gets its
// own command. Reuses the same math the pickers use.
function setResolution(args: { width?: number; height?: number; megapixels?: number; aspect_ratio?: string; image_size?: string; scale_factor?: number; target_resolution?: number }): string {
  const roundTo8 = (n: number) => Math.max(8, Math.round(n / 8) * 8)
  const hasW = args.width != null, hasH = args.height != null
  const hasMP = args.megapixels != null
  const hasAR = args.aspect_ratio != null
  const hasIS = args.image_size != null
  const changed: string[] = []

  // Upscale picker: a dedicated multi-mode control fed by UI-only keys
  // (scaleFactor + relative mode, or targetResolution + pixels mode). Write
  // those keys directly so the picker reacts — never the schema `resolution`
  // param, which the picker ignores.
  if (showUpscalePicker.value) {
    if (args.scale_factor != null) {
      const sf = Math.min(4, Math.max(0.5, Number(args.scale_factor)))
      if (Number.isNaN(sf)) return 'scale_factor must be a number (e.g. 2 for 2×).'
      modelParams.value.resolutionMode = 'relative'
      modelParams.value.scaleFactor = sf
      return `Set upscale to ${sf}×.`
    }
    if (args.target_resolution != null) {
      const px = Math.round(Math.min(4320, Math.max(480, Number(args.target_resolution))))
      if (Number.isNaN(px)) return 'target_resolution must be a number of pixels (short edge).'
      modelParams.value.resolutionMode = 'pixels'
      modelParams.value.targetResolution = px
      return `Set target resolution to ${px}px (short edge).`
    }
    return 'Provide scale_factor (e.g. 2 for 2×) or target_resolution (short edge in px).'
  }

  // Allowed-dimensions tools: snap request to the nearest permitted dimension.
  if (allowedDimensions.value && allowedDimensions.value.length) {
    const dims = allowedDimensions.value
    let targetAspect: number | null = null
    let targetArea: number | null = null
    if (hasW && hasH) { targetAspect = Number(args.width) / Number(args.height); targetArea = Number(args.width) * Number(args.height) }
    else if (hasAR) targetAspect = aspectRatioToDecimal(String(args.aspect_ratio))
    if (hasMP) targetArea = Number(args.megapixels) * 1_000_000
    if (targetAspect == null && targetArea == null) return 'Provide a width/height, aspect_ratio, or megapixels.'
    let best = dims[0], bestScore = Infinity
    for (const [w, h] of dims) {
      let score = 0
      if (targetAspect != null) score += Math.abs((w / h) - targetAspect)
      if (targetArea != null) score += (Math.abs((w * h) - targetArea) / 1_000_000) * 0.01
      if (score < bestScore) { bestScore = score; best = [w, h] }
    }
    onResolutionUpdate(best[0], best[1])
    return `Set resolution to ${best[0]}×${best[1]} (nearest supported).`
  }

  // Width/height tools (the user may express size as megapixels and/or aspect).
  if (hasWidthHeight.value && !hasMegapixels.value) {
    if (hasW && hasH && !hasMP && !hasAR) {
      const w = roundTo8(Number(args.width)), h = roundTo8(Number(args.height))
      onResolutionUpdate(w, h)
      changed.push(`${w}×${h}`)
    } else {
      const curW = Number(modelParams.value.width) || 1024
      const curH = Number(modelParams.value.height) || 1024
      const area = hasMP ? Number(args.megapixels) * 1_000_000 : (curW * curH)
      const aspect = hasAR ? aspectRatioToDecimal(String(args.aspect_ratio))
        : (hasW && hasH ? Number(args.width) / Number(args.height) : curW / curH)
      const dims = dimensionsForAreaAndAspect(area, aspect)
      if (dims) {
        const w = roundTo8(dims.width), h = roundTo8(dims.height)
        onResolutionUpdate(w, h)
        changed.push(`${w}×${h}`)
      }
    }
  }

  // Aspect-ratio picker tools (e.g. Gemini).
  if (hasAspectRatio.value) {
    if (hasAR) {
      const ar = String(args.aspect_ratio)
      if (aspectRatioChoices.value.length && !aspectRatioChoices.value.includes(ar)) {
        return `Aspect ratio "${ar}" not available. Options: ${aspectRatioChoices.value.join(', ')}.`
      }
      modelParams.value.aspect_ratio = ar
      changed.push(`aspect ${ar}`)
    }
    if (hasIS) {
      const is = String(args.image_size)
      if (imageSizeChoices.value.length && !imageSizeChoices.value.includes(is)) {
        return `Image size "${is}" not available. Options: ${imageSizeChoices.value.join(', ')}.`
      }
      modelParams.value.image_size = is
      changed.push(`size ${is}`)
    }
  }

  // Megapixels picker tools.
  if (hasMegapixels.value) {
    if (hasMP) {
      modelParams.value.megapixels = Number(args.megapixels)
      changed.push(`${Number(args.megapixels)}MP`)
    } else if (hasW && hasH) {
      const mp = (Number(args.width) * Number(args.height)) / 1_000_000
      modelParams.value.megapixels = mp
      changed.push(`${mp.toFixed(2)}MP`)
    }
  }

  if (!changed.length) return 'No applicable resolution control for this tool, or no recognized arguments.'
  return `Set resolution: ${changed.join(', ')}.`
}

// --- Tool-targeted skills ---------------------------------------------------
// Skills whose `environments.tool` matches this tool's task types auto-activate:
// their bodies ride state_context.notes.skill_guidance into the prompt agent.

const { listSkills: listSkillsApi, getSkillContent, skillEligibleForTool } = useStimpacksApi()
const activeToolSkills = ref<Skill[]>([])
const toolSkillGuidance = ref('')

async function loadToolSkills() {
  const taskTypes = tool.value?.task_types || []
  if (!taskTypes.length) {
    activeToolSkills.value = []
    toolSkillGuidance.value = ''
    return
  }
  try {
    const all = await listSkillsApi()
    const eligible = all.filter(s => skillEligibleForTool(s, taskTypes))
    activeToolSkills.value = eligible
    const bodies = await Promise.all(eligible.map(async s => {
      try {
        const detail = await getSkillContent(s.qualified_name)
        return `## Skill: ${s.display_name}\n\n${detail.content}`
      } catch {
        return null
      }
    }))
    toolSkillGuidance.value = bodies.filter(Boolean).join('\n\n---\n\n')
  } catch {
    activeToolSkills.value = []
    toolSkillGuidance.value = ''
  }
}
watch(() => tool.value?.full_tool_id, () => { void loadToolSkills() }, { immediate: true })

// --- State context ---------------------------------------------------------

function getStateContext(): Record<string, any> {
  const ctx: Record<string, any> = {}

  if (tool.value) {
    ctx.current_tool = {
      full_tool_id: tool.value.full_tool_id,
      name: tool.value.name,
      task_types: tool.value.task_types || [],
    }
  }

  if (hasPrompt.value) {
    ctx.prompt = globalPrefs.value.prompt || ''
    ctx.prompt_options = {
      auto_improve: globalPrefs.value.promptOptions?.autoImprove?.enabled ?? false,
      vary_prompt: globalPrefs.value.promptOptions?.varyPrompt?.enabled ?? false,
    }
  }

  // Parameters: current values + schema.
  const schemaMap = getParamSchemaMap()
  const paramNames = Object.keys(schemaMap)
  if (paramNames.length) {
    const params: Record<string, any> = {}
    for (const name of paramNames) {
      params[name] = modelParams.value[name]
    }
    // Seed is special (not in schemaMap) — surface current value + randomize flag.
    params.seed = modelParams.value.seed ?? null
    params.randomize_seed = modelParams.value.randomizeSeed ?? true
    ctx.parameters = params
    ctx.parameter_schema = schemaMap
  }

  // Reference images.
  if (mediaInputConfig.value?.accept === 'image') {
    const imgs = globalPrefs.value.inputImages || []
    if (imgs.length) {
      ctx.reference_images = imgs.map((img: any, index: number) => ({
        index,
        filename: img.filename,
        width: img._originalWidth ?? img.width ?? null,
        height: img._originalHeight ?? img.height ?? null,
        flip: {
          horizontal: !!img._flip?.horizontal,
          vertical: !!img._flip?.vertical,
          rotation: ((img._flip?.rotation ?? 0) % 360 + 360) % 360,
        },
        preprocessor: img._preprocessor ?? null,
        crop: img._crop ?? null,
        scale: img._scale ?? null,
        extend: img._extendPadding ?? null,
      }))
    }
  }

  // Resolution — a dedicated control, NOT a parameter_schema entry. Surface the
  // active mode + current value + allowed options so the agent can drive it.
  const res: Record<string, any> = {}
  if (showUpscalePicker.value) {
    // Upscaler: drive via set_resolution with scale_factor (relative) or
    // target_resolution (absolute short-edge px). Surface both the current
    // values and input/output dims so the agent can convert either way.
    res.mode = 'upscale'
    res.scale_mode = (modelParams.value.resolutionMode || 'relative') === 'pixels' ? 'target_resolution' : 'scale_factor'
    res.scale_factor = modelParams.value.scaleFactor ?? 2
    res.target_resolution = modelParams.value.targetResolution ?? 1080
    if (inputImageWidth.value && inputImageHeight.value) {
      res.input_width = inputImageWidth.value
      res.input_height = inputImageHeight.value
    }
    res.note = 'Upscaler. set_resolution with scale_factor (e.g. 2 for 2×, range 0.5–4) or target_resolution (short edge px, 480–4320). target_resolution applies to the short edge; aspect ratio is preserved.'
  } else if (allowedDimensions.value && allowedDimensions.value.length) {
    res.mode = 'allowed_dimensions'
    res.allowed_dimensions = allowedDimensions.value
    res.width = modelParams.value.width ?? null
    res.height = modelParams.value.height ?? null
  } else {
    if (hasWidthHeight.value && !hasMegapixels.value) {
      res.mode = 'width_height'
      res.width = modelParams.value.width ?? null
      res.height = modelParams.value.height ?? null
      res.note = 'pixels; you may also pass megapixels and/or aspect_ratio and they will be converted'
    }
    if (hasMegapixels.value) {
      res.mode = 'megapixels'
      res.megapixels = modelParams.value.megapixels ?? null
    }
    if (hasAspectRatio.value) {
      res.aspect_ratio = modelParams.value.aspect_ratio || '1:1'
      res.aspect_ratio_choices = aspectRatioChoices.value
      if (imageSizeChoices.value.length) {
        res.image_size = modelParams.value.image_size || null
        res.image_size_choices = imageSizeChoices.value
      }
    }
  }
  if (Object.keys(res).length) ctx.resolution = res

  // Categories.
  const cats = promptAgentChatRef.value?.getCategoriesForState?.()
  if (cats && cats.length) ctx.categories = cats

  // LoRAs (selected only — never dump available).
  if (hasLoras.value && toolLoras.value.length) {
    ctx.loras = {
      selected: toolLoras.value.map(l => {
        const match = availableLoras.value.find((a: any) => a.path === l.lora)
        return { name: match?.name || l.lora, path: l.lora, weight: l.weight, enabled: l.enabled }
      }),
    }
  }

  // Post-processing chain — current steps (with ids for addressing) plus the
  // built-in filter ids the agent can add. STP tool steps are resolved by
  // name via add_chain_step.
  ctx.post_processing = {
    enabled: toolChain.value.enabled,
    steps: toolChain.value.steps.map((s, i) => ({
      id: s.id,
      position: i + 1,
      kind: s.kind,
      name: s.kind === 'tool' ? (s.tool_name || s.tool_id) : s.filter_id,
      ...(s.kind === 'tool' ? { tool_id: s.tool_id, task_type: s.task_type } : { filter_id: s.filter_id }),
      enabled: s.enabled,
      settings: s.settings,
    })),
    available_filters: CHAIN_FILTER_DEFS.map(f => ({ id: f.id, label: f.label, params: f.params.map(p => p.name) })),
  }

  // Markers. set_auto_markers works by name, so surface the current selection
  // as names too (not raw ids) — otherwise the agent can't tell what's applied.
  const availableMarkers = jobsManager?.availableMarkers.value || []
  if (availableMarkers.length) {
    const selectedIds = new Set(globalPrefs.value.autoMarkerIds || [])
    ctx.markers = {
      note: 'Auto-markers are attached (like a tag) to images this page GENERATES from now on — not to the settings or existing media.',
      available: availableMarkers.map((m: any) => ({ id: m.id, name: m.name })),
      selected: availableMarkers.filter((m: any) => selectedIds.has(m.id)).map((m: any) => m.name),
    }
  }

  // Batch size — images queued per Run click (set_batch_size).
  ctx.batch_size = uiState.value.batchSize ?? 1

  // Forever mode.
  ctx.forever = {
    active: uiState.value.generateForeverMode ?? false,
    concurrency: uiState.value.generateForeverConcurrency ?? 1,
    idle_limit: uiState.value.generateForeverIdleLimit ?? null,
  }

  // Presets.
  ctx.presets = {
    available: agentPresets.value.map((p: any) => ({ id: p.id, name: p.name })),
    active: activePreset.value?.name ?? null,
    modified: !!isModified.value,
  }

  // Per-tool agent Instructions — the user's standing guidance for this tool,
  // edited via set/edit_instructions. Always surface (even when empty) so the
  // agent knows the current text for surgical edits.
  ctx.notes = {
    instructions: globalPrefs.value.agentInstructions || '',
  }

  // Tool-targeted skill bodies (auto-active by task_type match). The backend
  // lifts this out of the state JSON and injects it as its own reminder.
  if (toolSkillGuidance.value) {
    ctx.notes.skill_guidance = toolSkillGuidance.value
  }

  return ctx
}

// --- Command surface (runTool) ---------------------------------------------

async function runTool(name: string, args: any): Promise<string> {
  args = args || {}
  const editor = aiPromptEditorRef.value
  const chat = promptAgentChatRef.value
  const picker = mediaPickerRef.value
  const imgs = () => globalPrefs.value.inputImages || []

  switch (name) {
    // ── Prompt ──
    case 'set_prompt': {
      const text = String(args.text ?? '')
      globalPrefs.value.prompt = text
      editor?.setPromptText?.(text)
      return 'ok'
    }
    case 'edit_prompt': {
      const oldStr = String(args.old_string ?? '')
      const newStr = String(args.new_string ?? '')
      const current = globalPrefs.value.prompt || ''
      if (!oldStr || !current.includes(oldStr)) {
        return `old_string not found in the prompt. Current prompt: ${JSON.stringify(current)}`
      }
      const updated = args.replace_all
        ? current.split(oldStr).join(newStr)
        : current.replace(oldStr, newStr)
      globalPrefs.value.prompt = updated
      editor?.setPromptText?.(updated)
      return 'ok'
    }
    case 'clear_prompt': {
      globalPrefs.value.prompt = ''
      editor?.setPromptText?.('')
      return 'ok'
    }

    // ── Parameters ──
    case 'set_parameter': {
      const pname = String(args.name ?? '')
      const { value, error } = coerceParamValue(pname, args.value)
      if (error) return `Error: ${error}`
      modelParams.value[pname] = value
      return `Set ${pname} = ${JSON.stringify(value)}`
    }
    case 'set_seed': {
      const v = args.value
      if (v == null) {
        modelParams.value.seed = null
        return 'Cleared seed.'
      }
      const num = Math.round(Number(v))
      if (Number.isNaN(num)) return 'Error: seed must be an integer or null.'
      modelParams.value.seed = num
      modelParams.value.randomizeSeed = false
      return `Set seed = ${num} (randomize off).`
    }
    case 'set_randomize_seed': {
      modelParams.value.randomizeSeed = !!args.enabled
      return `Randomize seed ${args.enabled ? 'on' : 'off'}.`
    }
    case 'set_batch_size': {
      const num = Math.round(Number(args.size))
      if (Number.isNaN(num)) return 'Error: batch size must be an integer.'
      const clamped = Math.min(8, Math.max(1, num))
      uiState.value.batchSize = clamped
      return `Set batch size = ${clamped} (image${clamped === 1 ? '' : 's'} per run).`
    }
    case 'set_resolution':
      return setResolution(args || {})

    // ── Categories (delegate to the page-level PromptAgentChat) ──
    case 'add_category':
      if (!chat?.addCategory) return 'Error: prompt chat not available.'
      return chat.addCategory(args)
    case 'remove_category':
      if (!chat?.removeCategory) return 'Error: prompt chat not available.'
      return chat.removeCategory(String(args.key ?? ''))
    case 'set_category_options':
      if (!chat?.setCategoryOptions) return 'Error: prompt chat not available.'
      return chat.setCategoryOptions(String(args.key ?? ''), args.options || [])
    case 'refresh_category':
      if (!chat?.refreshCategory) return 'Error: prompt chat not available.'
      return await chat.refreshCategory(String(args.key ?? ''))
    case 'refresh_ideas':
      if (!chat?.refreshIdeas) return 'Error: prompt chat not available.'
      return await chat.refreshIdeas()

    // ── Reference images ──
    case 'flip_image':
      if (!picker?.flipImage) return 'No reference-image input on this tool.'
      return await picker.flipImage(Number(args.index), args.axis)
    case 'rotate_image':
      if (!picker?.rotateImage) return 'No reference-image input on this tool.'
      return await picker.rotateImage(Number(args.index), args.direction)
    case 'crop_image':
      if (!picker?.cropImage) return 'No reference-image input on this tool.'
      return await picker.cropImage(Number(args.index), args)
    case 'reset_image_transforms':
      if (!picker?.resetImageTransforms) return 'No reference-image input on this tool.'
      return await picker.resetImageTransforms(Number(args.index))
    case 'preprocess_image':
      if (!picker?.preprocessImage) return 'No reference-image input on this tool.'
      return await picker.preprocessImage(Number(args.index), args.preprocessor)
    case 'scale_image':
      if (!picker?.scaleImage) return 'No reference-image input on this tool.'
      return await picker.scaleImage(Number(args.index), args)
    case 'extend_image':
      if (!picker?.extendImage) return 'No reference-image input on this tool.'
      return await picker.extendImage(Number(args.index), args)
    case 'remove_image': {
      const i = Number(args.index)
      const list = imgs()
      if (!list[i]) return `No image at index ${i} (there are ${list.length}).`
      globalPrefs.value.inputImages = list.filter((_: any, idx: number) => idx !== i)
      return `Removed image ${i}.`
    }
    case 'clear_images': {
      const n = imgs().length
      globalPrefs.value.inputImages = []
      return `Cleared ${n} reference image(s).`
    }
    case 'reorder_image': {
      const from = Number(args.from_index)
      const to = Number(args.to_index)
      const list = [...imgs()]
      if (!list[from]) return `No image at index ${from} (there are ${list.length}).`
      if (to < 0 || to >= list.length) return `to_index ${to} out of range (0-${list.length - 1}).`
      const [moved] = list.splice(from, 1)
      list.splice(to, 0, moved)
      globalPrefs.value.inputImages = list
      return `Moved image ${from} → ${to}.`
    }

    // ── LoRAs ──
    case 'search_loras': {
      const q = String(args.query ?? '').toLowerCase().trim()
      const tokens = q.split(/\s+/).filter(Boolean)
      const matches = availableLoras.value.filter((l: any) => {
        const hay = (l.name + ' ' + l.path).toLowerCase()
        return tokens.length === 0 || tokens.every(t => hay.includes(t))
      }).slice(0, 10)
      if (!matches.length) return `No LoRAs match "${args.query}".`
      return `Matches:\n${matches.map((l: any) => `- ${l.name} (${l.path})`).join('\n')}`
    }
    case 'set_lora_weight': {
      if (!hasLoras.value) return 'This tool does not support LoRAs.'
      const match = resolveLora(String(args.lora ?? ''))
      if (!match) return `No LoRA found matching "${args.lora}". Use search_loras.`
      const weight = Number(args.weight)
      if (Number.isNaN(weight)) return 'Error: weight must be a number.'
      const existing = toolLoras.value.find(l => l.lora === match.path)
      if (existing) {
        toolLoras.value = toolLoras.value.map(l => l.lora === match.path ? { ...l, weight } : l)
      } else {
        toolLoras.value = [...toolLoras.value, { lora: match.path, weight, enabled: true }]
      }
      return `Set ${match.name} weight = ${weight}${existing ? '' : ' (added)'}.`
    }
    case 'set_lora_enabled': {
      if (!hasLoras.value) return 'This tool does not support LoRAs.'
      const match = resolveLora(String(args.lora ?? ''))
      if (!match) return `No LoRA found matching "${args.lora}". Use search_loras.`
      const enabled = !!args.enabled
      const existing = toolLoras.value.find(l => l.lora === match.path)
      if (existing) {
        toolLoras.value = toolLoras.value.map(l => l.lora === match.path ? { ...l, enabled } : l)
      } else {
        toolLoras.value = [...toolLoras.value, { lora: match.path, weight: 1.0, enabled }]
      }
      return `${enabled ? 'Enabled' : 'Disabled'} ${match.name}${existing ? '' : ' (added)'}.`
    }

    // ── Post-processing chain ──
    case 'set_postprocessing_enabled': {
      const enabled = !!args.enabled
      toolChain.value = { ...toolChain.value, enabled }
      return `Post-processing ${enabled ? 'on' : 'off'} (${toolChain.value.steps.length} step${toolChain.value.steps.length === 1 ? '' : 's'}).`
    }
    case 'add_chain_step': {
      const kind = args.kind === 'filter' ? 'filter' : args.kind === 'tool' ? 'tool' : null
      if (!kind) return 'Error: kind must be "tool" or "filter".'
      const ref = String(args.ref ?? '').trim()
      if (!ref) return 'Error: ref is required (filter id, or STP tool name/id).'

      let step: ChainStep
      if (kind === 'filter') {
        const needle = ref.toLowerCase()
        const def = CHAIN_FILTER_DEFS.find(f => f.id === needle)
          || CHAIN_FILTER_DEFS.find(f => f.label.toLowerCase() === needle)
          || CHAIN_FILTER_DEFS.find(f => f.id.includes(needle) || f.label.toLowerCase().includes(needle))
        if (!def) {
          return `No built-in filter matches "${ref}". Available: ${CHAIN_FILTER_DEFS.map(f => f.id).join(', ')}.`
        }
        step = {
          id: newStepId(),
          kind: 'filter',
          enabled: true,
          filter_id: def.id,
          settings: { ...getChainFilterDefaults(def.id), ...(args.settings || {}) },
        }
      } else {
        let tools: ProviderTool[] = []
        try {
          tools = (await fetchProvidersAndTools()).tools
        } catch {
          return 'Error: could not load the tool catalog.'
        }
        const chainTypes = new Set<string>(CHAIN_TOOL_TASK_TYPES)
        const candidates = tools.filter(t => {
          if (t.full_tool_id === fullToolIdFromProps) return false
          const tts = (t.task_types?.length ? t.task_types : [t.task_type])
          return tts.some(tt => chainTypes.has(tt))
        })
        const needle = ref.toLowerCase()
        const match = candidates.find(t => t.full_tool_id.toLowerCase() === needle)
          || candidates.find(t => t.name.toLowerCase() === needle)
          || candidates.find(t => t.name.toLowerCase().includes(needle) || t.full_tool_id.toLowerCase().includes(needle))
        if (!match) {
          const sample = candidates.slice(0, 8).map(t => t.name).join(', ')
          return `No chain-compatible STP tool matches "${ref}".${sample ? ` Some options: ${sample}.` : ''}`
        }
        const tts = (match.task_types?.length ? match.task_types : [match.task_type])
          .filter(tt => chainTypes.has(tt))
        const taskType = tts.find(tt => stepInputMedia(tt, 'tool') === 'image') || tts[0]
        step = {
          id: newStepId(),
          kind: 'tool',
          enabled: true,
          tool_id: match.full_tool_id,
          task_type: taskType,
          tool_name: match.name,
          settings: { ...(args.settings || {}) },
        }
      }

      const steps = toolChain.value.steps
      // Default position: the latest stage that accepts the step's input type
      // (an image step lands before the chain's video transition).
      const baseType = outputsVideo.value ? 'video' : 'image'
      const smart = defaultInsertIndex(toolChain.value, stepAcceptedMedia(step), baseType)
      let pos = smart < 0 ? steps.length : smart
      if (args.position != null) {
        const p = Math.round(Number(args.position)) - 1
        if (!Number.isNaN(p)) pos = Math.max(0, Math.min(steps.length, p))
      }
      updateToolChainSteps(list => {
        list.splice(pos, 0, step)
        return list
      })
      return `Added ${kind} step "${step.kind === 'tool' ? step.tool_name : step.filter_id}" at position ${pos + 1} (id ${step.id}).`
    }
    case 'remove_chain_step': {
      const hit = resolveChainStep(args.step)
      if (typeof hit === 'string') return hit
      updateToolChainSteps(list => list.filter((_, i) => i !== hit.index))
      return `Removed step ${hit.index + 1} (${hit.step.kind === 'tool' ? hit.step.tool_name : hit.step.filter_id}).`
    }
    case 'reorder_chain_step': {
      const hit = resolveChainStep(args.step)
      if (typeof hit === 'string') return hit
      const to = Math.round(Number(args.to_position)) - 1
      if (Number.isNaN(to) || to < 0 || to >= toolChain.value.steps.length) {
        return `to_position out of range (1-${toolChain.value.steps.length}).`
      }
      updateToolChainSteps(list => {
        const [moved] = list.splice(hit.index, 1)
        list.splice(to, 0, moved)
        return list
      })
      return `Moved step to position ${to + 1}.`
    }
    case 'configure_chain_step': {
      const hit = resolveChainStep(args.step)
      if (typeof hit === 'string') return hit
      const settings = args.settings
      if (!settings || typeof settings !== 'object') return 'Error: settings must be an object.'
      if (hit.step.kind === 'filter') {
        const def = getChainFilterDef(hit.step.filter_id || '')
        const valid = new Set((def?.params || []).map(p => p.name))
        const unknown = Object.keys(settings).filter(k => !valid.has(k))
        if (unknown.length) {
          return `Unknown setting(s) ${unknown.join(', ')} for filter "${hit.step.filter_id}". Valid: ${[...valid].join(', ')}.`
        }
      }
      updateToolChainSteps(list => {
        list[hit.index] = { ...list[hit.index], settings: { ...list[hit.index].settings, ...settings } }
        return list
      })
      return `Updated settings on step ${hit.index + 1}: ${Object.keys(settings).join(', ')}.`
    }
    case 'set_chain_step_enabled': {
      const hit = resolveChainStep(args.step)
      if (typeof hit === 'string') return hit
      const enabled = !!args.enabled
      updateToolChainSteps(list => {
        list[hit.index] = { ...list[hit.index], enabled }
        return list
      })
      return `${enabled ? 'Enabled' : 'Disabled'} step ${hit.index + 1}.`
    }

    // ── Markers ──
    case 'set_auto_markers': {
      const available = jobsManager?.availableMarkers.value || []
      const requested: string[] = Array.isArray(args.markers) ? args.markers : []
      const ids: number[] = []
      const names: string[] = []
      const unmatched: string[] = []
      for (const nm of requested) {
        const m = available.find((a: any) => a.name.toLowerCase() === String(nm).toLowerCase())
          || available.find((a: any) => a.name.toLowerCase().includes(String(nm).toLowerCase()))
        if (m) { ids.push(m.id); names.push(m.name) }
        else unmatched.push(nm)
      }
      globalPrefs.value.autoMarkerIds = ids
      const suffix = unmatched.length ? ` (not found: ${unmatched.join(', ')})` : ''
      if (!ids.length) return `Turned off auto-marking — new generations won't be auto-marked${suffix}.`
      return `New generations on this page will be auto-marked "${names.join('", "')}"${suffix}.`
    }

    // ── Prompt options ──
    case 'set_prompt_option': {
      const enabled = !!args.enabled
      const opts = JSON.parse(JSON.stringify(globalPrefs.value.promptOptions || {
        autoImprove: { enabled: false, instructions: '' },
        varyPrompt: { enabled: false, instructions: '' },
      }))
      if (args.option === 'auto_improve') {
        opts.autoImprove = { ...opts.autoImprove, enabled }
      } else if (args.option === 'vary_prompt') {
        opts.varyPrompt = { ...opts.varyPrompt, enabled }
      } else {
        return `Unknown option "${args.option}". Use auto_improve or vary_prompt.`
      }
      globalPrefs.value.promptOptions = opts
      return `${args.option} ${enabled ? 'on' : 'off'}.`
    }

    // ── Per-tool Instructions ──
    // Mirror the set_prompt / edit_prompt pair: whole-blob set + exact
    // search/replace. Rides globalPrefs and auto-persists via the debounced
    // tool-state watcher (and into a preset when saved).
    case 'set_instructions': {
      globalPrefs.value.agentInstructions = String(args.content ?? '')
      return 'ok'
    }
    case 'edit_instructions': {
      const oldStr = String(args.old_string ?? '')
      const newStr = String(args.new_string ?? '')
      const current = globalPrefs.value.agentInstructions || ''
      // Empty old_string = "add this" — append (covers the first write to an
      // empty note, which the agent does via edit_* rather than set_*).
      if (!oldStr) {
        globalPrefs.value.agentInstructions = current ? `${current}\n${newStr}` : newStr
        return 'ok'
      }
      if (!current.includes(oldStr)) {
        return `old_string not found in Instructions. Current Instructions: ${JSON.stringify(current)}`
      }
      globalPrefs.value.agentInstructions = args.replace_all
        ? current.split(oldStr).join(newStr)
        : current.replace(oldStr, newStr)
      return 'ok'
    }

    // ── Actions (Tier 2) ──
    case 'generate': {
      if (!canSubmit.value) return 'Cannot generate: required inputs are missing.'
      await submitJob()
      return 'Generation submitted.'
    }
    case 'start_forever_mode': {
      const concurrency = args.concurrency != null
        ? Math.max(1, Math.round(Number(args.concurrency)))
        : (uiState.value.generateForeverConcurrency ?? 1)
      uiState.value.generateForeverConcurrency = concurrency
      await startForeverMode(concurrency)
      return `Started forever mode (concurrency ${concurrency}).`
    }
    case 'stop_forever_mode': {
      await stopForeverMode()
      return 'Stopped forever mode.'
    }

    // ── Presets ──
    case 'apply_preset': {
      const want = String(args.preset ?? '').trim()
      if (!want) return 'Error: preset name or id is required.'
      if (!agentPresets.value.length) await refreshAgentPresets()
      const wantLower = want.toLowerCase()
      let preset = agentPresets.value.find((p: any) => String(p.id) === want)
        || agentPresets.value.find((p: any) => (p.name || '').toLowerCase() === wantLower)
        || agentPresets.value.find((p: any) => (p.name || '').toLowerCase().includes(wantLower))
      if (!preset) {
        const names = agentPresets.value.map((p: any) => p.name).join(', ')
        return `No preset matching "${want}".${names ? ` Available: ${names}.` : ' There are no saved presets.'}`
      }
      handlePresetSelect(preset)
      editor?.setPromptText?.(globalPrefs.value.prompt || '')
      return `Applied preset "${preset.name}".`
    }
    case 'save_preset': {
      const pname = String(args.name ?? '').trim()
      if (!pname) return 'Error: a name is required.'
      const id = tool.value?.full_tool_id
      if (!id) return 'Error: no active tool.'
      try {
        const preset = await agentSaveAsPreset(pname, id, getCurrentState() as any)
        handlePresetSaved(preset)
        await refreshAgentPresets()
        return `Saved preset "${pname}".`
      } catch (e: any) {
        return `Error saving preset: ${e?.response?.data?.detail || e?.message || 'failed'}`
      }
    }
    case 'reset_to_defaults': {
      handleResetToDefaults()
      editor?.setPromptText?.(globalPrefs.value.prompt || '')
      return 'Reset all settings to tool defaults.'
    }

    // ── History (clicks the Undo/Redo buttons) ──
    case 'undo': {
      if (!undo.canUndo.value) return 'Nothing to undo.'
      undo.undo()
      return 'Undid the last change.'
    }
    case 'redo': {
      if (!undo.canRedo.value) return 'Nothing to redo.'
      undo.redo()
      return 'Redid the change.'
    }

    default:
      return `Unknown tool "${name}".`
  }
}

// Snapshot for undo lazily — once per run, before the first MUTATING tool — so
// non-mutating tools (undo/redo/search/generate) behave like the buttons and
// don't create spurious undo entries or clear the redo stack.
// Instructions live outside the undo snapshot — durable per-tool scaffolding,
// like the LoRA pool — so writing them shouldn't create an undo entry or clear
// the redo stack.
const AGENT_NON_MUTATING_TOOLS = new Set([
  'undo', 'redo', 'search_loras', 'generate', 'start_forever_mode', 'stop_forever_mode',
  'set_instructions', 'edit_instructions',
  // Batch size lives in uiState, outside the undo snapshot — like forever mode
  // and the LoRA pool — so writing it shouldn't create an undo entry.
  'set_batch_size',
])
let agentRunSnapshotTaken = false

const promptMiniAgent = usePromptMiniAgent({
  getStateContext,
  runTool,
  onRunStart: () => { agentRunSnapshotTaken = false },
  onBeforeTool: (name: string) => {
    if (!agentRunSnapshotTaken && !AGENT_NON_MUTATING_TOOLS.has(name)) {
      undo.snapshot()
      agentRunSnapshotTaken = true
    }
  },
})

provide(PROMPT_EDITOR_AGENT_KEY, {
  send: promptMiniAgent.send,
  running: promptMiniAgent.running,
  error: promptMiniAgent.error,
  lastReply: promptMiniAgent.lastReply,
  lastDebugTrace: promptMiniAgent.lastDebugTrace,
  messages: promptMiniAgent.messages,
  clearHistory: promptMiniAgent.clearHistory,
  snapshot: undo.snapshot,
  undo: undo.undo,
  redo: undo.redo,
  canUndo: undo.canUndo,
  canRedo: undo.canRedo,
})

// WebSocket handling
const { on: onWebSocketEvent, send: sendWebSocketMessage, connected: wsConnected } = useWebSocket()

watch(wsConnected, async (isConnected, wasConnected) => {
  if (!isConnected && wasConnected) {
    foreverModeSessionId.value++
    workRequestQueue.value = []
    // On disconnect, clear forever mode batch tracking to prevent stalls
    // (if backend crashes mid-batch, the batch_completed event never fires)
    foreverModeActiveBatchId.value = null
    foreverModePendingBatchCompletion.value = null
    foreverModeBatchSubmitInFlight.value = false
  }

  if (isConnected && tool.value) {
    sendWebSocketMessage('register_generator_instance', {
      generator_instance_id: generatorInstanceId
    })

    // On reconnect, resync job state from backend to clear phantom jobs
    if (wasConnected === false) {
      await jobsManager?.loadJobs()
    }

    // Re-register forever mode on reconnect. Retries with capped backoff
    // rather than giving up after a fixed count - a backend restart (nodemon
    // picking up a file change, DB migrations running at startup) can easily
    // take longer than a few seconds to have its HTTP routes back up, and a
    // silent permanent give-up here leaves the UI showing forever mode "on"
    // while the server has no idea it exists - jobs then queue forever with
    // nothing to dispatch them, and nothing else will ever retry.
    if (wasConnected === false && uiState.value.generateForeverMode) {
      void reregisterForeverModeWithRetry()
    }
  }
  // If we had an error and connection is restored, retry loading
  if (isConnected && wasConnected === false && error.value) {
    error.value = null
    await loadTool(true)
  }
}, { immediate: true })

watch(toolAvailability, (availability) => {
  if (availability === 'available') {
    stopAvailabilityPolling()
    return
  }
  startAvailabilityPolling()
})

type ForeverWorkRequest = {
  backendName: string
  sessionId: number
  reserved: boolean
}

// Queue of pending work requests, preserving the backend reservation each came from.
const workRequestQueue = ref<ForeverWorkRequest[]>([])
const processingWorkQueue = ref(false)
const foreverModeSessionId = ref(0)

// Track active batch in forever mode (batches run sequentially, not in parallel)
const foreverModeActiveBatchId = ref<string | null>(null)
const foreverModePendingBatchCompletion = ref<any | null>(null)
const foreverModeBatchSubmitInFlight = ref(false)

// Track consecutive failures to auto-disable forever mode
const consecutiveFailures = ref(0)
const MAX_CONSECUTIVE_FAILURES = 3

// Check if current inputs are in batch mode (have a set)
function isInBatchMode(): boolean {
  if (globalPrefs.value.batchMode) return true
  const inputImages = globalPrefs.value.inputImages || []
  return inputImages.some((img: any) => img.isSet)
}

function isForeverBatchBlocked(): boolean {
  return !!foreverModeActiveBatchId.value || foreverModeBatchSubmitInFlight.value
}

function declineWorkRequest(backendName: string) {
  sendWebSocketMessage('generation_decline_work', {
    generator_instance_id: generatorInstanceId,
    backend_name: backendName,
  })
}

async function handleWorkRequest(data: any) {
  if (!tool.value || data.generator_instance_id !== generatorInstanceId) {
    return
  }
  if (!uiState.value.generateForeverMode || !canSubmit.value) {
    declineWorkRequest(data.backend_name)
    return
  }

  // In batch mode, ignore work requests if a batch is already running
  // (batches should run sequentially, parallelization happens within the batch)
  if (isInBatchMode() && isForeverBatchBlocked()) {
    console.log('[Forever Mode] Ignoring work request - batch already in progress')
    declineWorkRequest(data.backend_name)
    return
  }

  // Queue this work request
  workRequestQueue.value.push({
    backendName: data.backend_name,
    sessionId: foreverModeSessionId.value,
    reserved: true,
  })

  // Process queue if not already processing
  if (!processingWorkQueue.value) {
    await processWorkQueue()
  }
}

async function processWorkQueue() {
  if (processingWorkQueue.value) return
  processingWorkQueue.value = true

  try {
    while (workRequestQueue.value.length > 0 && uiState.value.generateForeverMode && canSubmit.value) {
      // In batch mode, only process if no batch is active
      if (isInBatchMode() && isForeverBatchBlocked()) {
        console.log('[Forever Mode] Waiting for current batch to complete')
        break
      }

      const request = workRequestQueue.value.shift()
      if (!request) continue
      if (request.sessionId !== foreverModeSessionId.value) {
        continue
      }
      modelParams.value.seed = generateRandomSeed()
      const result = await submitJob({
        foreverBackendName: request.backendName,
        foreverSessionId: request.sessionId,
        foreverReserved: request.reserved,
      })
      if (!result.submitted && result.declineReservation) {
        declineWorkRequest(request.backendName)
        if (isForeverSubmissionCurrent({ foreverSessionId: request.sessionId })) {
          void recordForeverFailure()
        }
      }

      // In batch mode, stop after submitting one batch - wait for completion
      if (isInBatchMode()) {
        break
      }
    }
  } finally {
    // Decline any remaining queued work requests that won't be processed
    if (workRequestQueue.value.length > 0 && tool.value) {
      const remaining = workRequestQueue.value.splice(0)
      for (const request of remaining) {
        if (request.reserved && request.sessionId === foreverModeSessionId.value) {
          declineWorkRequest(request.backendName)
        }
      }
    }
    processingWorkQueue.value = false
  }
}

// Forever mode failure tracking
async function recordForeverFailure() {
  if (!uiState.value.generateForeverMode) return

  consecutiveFailures.value++

  if (consecutiveFailures.value >= MAX_CONSECUTIVE_FAILURES) {
    consecutiveFailures.value = 0
    await stopForeverMode()
  }
}

async function handleForeverModeJobCompleted(data: any) {
  // Only track jobs from this generator instance
  if (data.generator_instance_id !== generatorInstanceId) return
  // Reset failure counter on success
  consecutiveFailures.value = 0

  // Check idle limit for auto-stop
  if (uiState.value.generateForeverMode && uiState.value.generateForeverIdleLimit > 0) {
    foreverModeIdleCount.value++
    if (foreverModeIdleCount.value >= uiState.value.generateForeverIdleLimit) {
      await stopForeverMode()
    }
  }
}

async function handleForeverModeJobFailed(data: any) {
  // Only track jobs from this generator instance
  if (data.generator_instance_id !== generatorInstanceId) return
  if (!uiState.value.generateForeverMode) return

  await recordForeverFailure()
}

async function handleForeverModeBatchCompleted(data: any) {
  // Check if this is our active batch
  if (data.batch_id !== foreverModeActiveBatchId.value) return
  foreverModePendingBatchCompletion.value = data
  await nextTick()
  await maybeResumeForeverModeBatch()
}

function batchHasActivePostprocessing(batchId: string): boolean {
  const batch = jobsManager?.batchJobs.value?.[batchId]
  if (!batch) return false
  const jobIds = new Set((batch.jobs || []).map((job: any) => job.id))
  if (jobIds.size === 0) return false
  return (jobsManager?.activeChainRuns.value || []).some((run: any) =>
    run.job_id != null && jobIds.has(run.job_id)
  )
}

async function maybeResumeForeverModeBatch() {
  const data = foreverModePendingBatchCompletion.value
  if (!data || data.batch_id !== foreverModeActiveBatchId.value) return
  if (batchHasActivePostprocessing(data.batch_id)) {
    console.log(`[Forever Mode] Batch ${data.batch_id} waiting for post-processing`)
    return
  }
  foreverModePendingBatchCompletion.value = null

  console.log(`[Forever Mode] Batch ${data.batch_id} completed, resuming queue`)

  // Clear active batch
  foreverModeActiveBatchId.value = null

  // Reset failure counter (batch completed = success)
  consecutiveFailures.value = 0

  // Check idle limit for auto-stop
  if (uiState.value.generateForeverMode && uiState.value.generateForeverIdleLimit > 0) {
    foreverModeIdleCount.value++
    if (foreverModeIdleCount.value >= uiState.value.generateForeverIdleLimit) {
      await stopForeverMode()
      return
    }
  }

  // Queue another work request to continue forever mode
  if (uiState.value.generateForeverMode && canSubmit.value) {
    workRequestQueue.value.push({
      backendName: tool.value.generator,
      sessionId: foreverModeSessionId.value,
      reserved: false,
    })
    if (!processingWorkQueue.value) {
      await processWorkQueue()
    }
  }
}

watch(
  () => jobsManager?.activeChainRuns.value.map((run: any) => `${run.id}:${run.status}:${run.job_id}`).join('|') || '',
  () => { void maybeResumeForeverModeBatch() }
)

// Job event handlers
function handleJobClick(job: any) {
  if (job.status === 'completed') {
    // If clicking on a set (batch output), open slideshow of just that set
    if (job.is_set && job.result_media_id) {
      openSingleImageSlideshow(job.result_media_id)
    } else {
      openSlideshow(job)
    }
  } else if (job.status === 'failed') {
    showJobError(job)
  }
}

// Provider-order ids for the slideshow's arrival pinning. The slideshow diffs
// successive values, so this must be the same list (same order) the page
// provider serves.
const slideshowLiveItemIds = computed(() =>
  jobsManager ? jobsManager.sortedCompletedJobs.value.map((job: any) => job.id) : null
)

async function openSlideshow(job: any) {
  if (!job.result_media_id || !jobsManager) return

  const index = jobsManager.sortedCompletedJobs.value.findIndex((j: any) => j.id === job.id)
  if (index === -1) return

  enterSlideshow({
    totalCount: jobsManager.totalCompletedCount.value,
    startIndex: index,
    pageProvider: jobsManager.fetchGeneratedImages,
    randomized: false,
    randomSeed: null,
    autoAdvanceOnNew: true
  })
}

async function openSingleImageSlideshow(mediaId: number) {
  const singleImageProvider = async (pageNumber: number, pageSize: number) => {
    if (pageNumber > 0) return []
    try {
      const item = await getMediaItem(mediaId, { includeTrashed: true })
      return [item]
    } catch (error) {
      return [{ id: mediaId, file_hash: null, _placeholder: true }]
    }
  }

  enterSlideshow({
    totalCount: 1,
    startIndex: 0,
    pageProvider: singleImageProvider,
    randomized: false,
    randomSeed: null,
    autoAdvanceOnNew: false
  })
}

async function openMediaBatchSlideshow(mediaIds: number[]) {
  const ids = [...mediaIds]
  if (ids.length === 0) return

  const batchProvider = async (pageNumber: number, pageSize: number) => {
    const start = pageNumber * pageSize
    const pageIds = ids.slice(start, start + pageSize)
    return Promise.all(pageIds.map(async (mediaId) => {
      try {
        return await getMediaItem(mediaId, { includeTrashed: true })
      } catch (error) {
        return { id: mediaId, file_hash: null, _placeholder: true }
      }
    }))
  }

  enterSlideshow({
    totalCount: ids.length,
    startIndex: 0,
    pageProvider: batchProvider,
    randomized: false,
    randomSeed: null,
    autoAdvanceOnNew: false
  })
}

async function handleToggleMarker({ mediaId, marker }: { mediaId: number, marker: any }) {
  await jobsManager?.toggleMarker(mediaId, marker)
}

function handleMediaLoadError(mediaId: number) {
  jobsManager?.handleMediaLoadError(mediaId)
}

function showJobError(job: any) {
  errorModalJob.value = job
  showErrorModal.value = true
}

function closeErrorModal() {
  showErrorModal.value = false
  errorModalJob.value = null
}

function showJobInfo(job: any) {
  infoModalJobId.value = job.id
  showInfoModal.value = true
}

function closeInfoModal() {
  showInfoModal.value = false
  infoModalJobId.value = null
}

async function handleErrorModalRetry(jobId: number) {
  closeErrorModal()
  await retryJob(jobId)
}

async function handleErrorModalDismiss(jobId: number) {
  closeErrorModal()
  await dismissJob(jobId)
}

async function dismissJob(jobId: number) {
  await jobsManager?.dismissJob(jobId)
}

async function retryJob(jobId: number) {
  await jobsManager?.retryJob(jobId)
}

async function cancelJob(jobId: number | string) {
  if (typeof jobId === 'string' && jobId.startsWith('pending-')) {
    jobsManager?.cancelPendingJob(jobId)
  } else {
    await jobsManager?.cancelJob(jobId as number)
  }
}

async function cancelAndDismissBatch(batchId: string) {
  // Cancel all jobs in the batch that are still cancellable
  const batch = jobsManager?.batchJobs.value[batchId]
  if (batch) {
    for (const job of batch.jobs) {
      if (['queued', 'assigned', 'enhancing', 'processing'].includes(job.status)) {
        await jobsManager?.cancelJob(job.id)
      }
    }
  }
  // Always dismiss the batch from UI regardless of job states
  jobsManager?.dismissBatch(batchId)
}

function dismissBatch(batchId: string) {
  jobsManager?.dismissBatch(batchId)
}

async function clearQueue() {
  await jobsManager?.cancelAllQueued()
}

function setImageMode(mode: string) {
  uiState.value.imageMode = mode
}

// Keyboard shortcuts
function handleKeyDown(event: KeyboardEvent) {
  const modifierKey = isMac.value ? event.metaKey : event.ctrlKey
  if (modifierKey && event.key === 'Enter') {
    event.preventDefault()
    event.stopPropagation()
    if (event.shiftKey) {
      // Cmd/Ctrl+Shift+Enter: toggle forever mode
      if (uiState.value.generateForeverMode) {
        stopForeverMode()
      } else {
        startForeverMode(uiState.value.generateForeverConcurrency)
      }
    } else if (canSubmit.value) {
      submitJob()
    }
  }
}

// Watch for loadInput query param (when navigating from "Send to Tool")
// Uses timestamp value to force detection even when already on this route
watch(() => route.query.loadInput, (newValue, oldValue) => {
  if (newValue && tool.value && !isInitialLoading.value && isMyToolRoute()) {
    // Close slideshow if open so user sees the new input
    if (slideshowState.active) {
      exitSlideshow()
    }
    loadPendingInput()
  }
}, { immediate: false })

// Watch for loadGeneration query param (when navigating from "Generate more like this" or "View in Tool")
// Uses timestamp value to force detection even when already on this route (similar to loadInput)
watch(() => route.query.loadGeneration, (newValue) => {
  if (newValue && tool.value && isMyToolRoute()) {
    // Reset the flag so we can load the new config (important for KeepAlive'd components)
    pendingGenerationApplied.value = false
    // Close slideshow if open
    if (slideshowState.active) {
      exitSlideshow()
    }
    loadPendingGeneration()
  }
}, { immediate: false })

// Watch for preset_id query param (global search preset results, KeepAlive'd instances)
watch(() => route.query.preset_id, (newValue) => {
  if (newValue && tool.value && isMyToolRoute()) {
    loadPresetFromQuery()
  }
}, { immediate: false })

// Watch for remixFrom query param (also supports legacy inspireFrom/loadFromMedia)
watch(
  () => route.query.remixFrom || route.query.inspireFrom || route.query.loadFromMedia,
  (mediaId) => {
    // IMPORTANT: Only load if this watcher is for the CURRENT route's exact
    // instance — during navigation, watchers on the OLD page can fire before
    // deactivation, and sibling instances of the same tool stay live.
    if (mediaId && tool.value && isMyToolRoute()) {
      if (slideshowState.active) {
        exitSlideshow()
      }
      loadRemix(mediaId as string)
    }
  },
  { immediate: false }
)

// Profile change handlers to prevent state leakage between profiles
function handleProfileWillChange() {
  flushPendingSaves()  // save pending changes to OLD profile's storage
}

function handleFlushToolInstanceState(event: Event) {
  const tabId = (event as CustomEvent<{ tabId?: string }>).detail?.tabId
  if (!ownTab.value || tabId !== ownTab.value.id) return
  flushPendingSaves()
  flushGenerationPreferenceSaves()
}

async function handleProfileChanged() {
  stopWatching()  // stop watchers to prevent stale saves during reinit
  await loadTool(true)  // force reload from API + reinitialize state + restart watchers
}

onMounted(async () => {
  console.log('[ToolView onMounted] Starting, route.query:', JSON.stringify(route.query))
  await loadTool()
  console.log('[ToolView onMounted] loadTool completed')

  // Listen for profile changes
  window.addEventListener('profile-will-change', handleProfileWillChange)
  window.addEventListener('profile-changed', handleProfileChanged)
  window.addEventListener('stimma:flush-tool-instance-state', handleFlushToolInstanceState)

  // Register WebSocket event handlers. The handler registry is a module-level
  // singleton that survives HMR, so we must hold the unsubscribers and tear
  // them down on unmount or stale handlers accumulate across reloads.
  foreverModeUnsubscribers = [
    onWebSocketEvent('generation_request_work', handleWorkRequest),
    onWebSocketEvent('generation_job_completed', handleForeverModeJobCompleted),
    onWebSocketEvent('generation_job_failed', handleForeverModeJobFailed),
    onWebSocketEvent('batch_completed', handleForeverModeBatchCompleted)
  ]

  // Subscribe to provider status changes for reactive availability updates
  unsubscribeFromProviderChanges = subscribeToProviderChanges(async () => {
    // Reload tool to get updated availability status
    if (tool.value) {
      try {
        const providerTool = await getProviderTool(tool.value.full_tool_id)
        tool.value = buildToolWithState(providerTool, tool.value.state || {})
      } catch (e) {
        // Tool may no longer exist
        console.warn('Failed to refresh tool availability:', e)
      }
    }
  })

  // Register with WebSocket now that tool is loaded
  if (tool.value && wsConnected.value) {
    sendWebSocketMessage('register_generator_instance', {
      generator_instance_id: generatorInstanceId
    })
  }

  if (tool.value && uiState.value.generateForeverMode) {
    try {
      await axios.post(`${API_BASE}/generate/forever/register`, null, {
        params: {
          generator_instance_id: generatorInstanceId,
          backend_name: tool.value.generator,
          max_concurrency: uiState.value.generateForeverConcurrency,
          tool_id: tool.value.full_tool_id
        }
      })
    } catch (err) {
      console.error('Failed to re-register forever mode:', err)
    }
  }

  // Dev-only: resume generate-forever if an HMR swap interrupted an active
  // session (see the matching dispose-side stash in onUnmounted).
  if (import.meta.hot && import.meta.hot.data.resumeForeverMode && tool.value) {
    const concurrency = import.meta.hot.data.resumeForeverConcurrency ?? uiState.value.generateForeverConcurrency
    import.meta.hot.data.resumeForeverMode = false
    import.meta.hot.data.resumeForeverConcurrency = undefined
    await startForeverMode(concurrency)
  }
})

// Use onActivated/onDeactivated for keyboard handler since this component is in KeepAlive
onActivated(() => {
  console.log('[ToolView onActivated] Component reactivated, route.query:', JSON.stringify(route.query))
  window.addEventListener('keydown', handleKeyDown)
})

onDeactivated(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

onUnmounted(async () => {
  foreverModeSessionId.value++
  workRequestQueue.value = []
  foreverModeBatchSubmitInFlight.value = false

  // Clean up profile change listeners
  window.removeEventListener('profile-will-change', handleProfileWillChange)
  window.removeEventListener('profile-changed', handleProfileChanged)
  window.removeEventListener('stimma:flush-tool-instance-state', handleFlushToolInstanceState)
  stopWatching()

  jobsManager?.cleanup()

  // Unsubscribe forever-mode WebSocket handlers so they don't outlive the
  // component (singleton registry persists across navigation and HMR).
  foreverModeUnsubscribers.forEach(unsub => unsub())
  foreverModeUnsubscribers = []

  // Clean up provider status subscription
  if (unsubscribeFromProviderChanges) {
    unsubscribeFromProviderChanges()
    unsubscribeFromProviderChanges = null
  }

  // Dev-only: bridge active forever mode across HMR so background agent edits
  // don't silently kill an in-progress generate-forever session. import.meta.hot
  // is undefined in prod and import.meta.hot.data is wiped on a true page reload,
  // so this never resumes after a cold reload — only across an HMR swap.
  if (import.meta.hot && tool.value && uiState.value.generateForeverMode) {
    import.meta.hot.data.resumeForeverMode = true
    import.meta.hot.data.resumeForeverConcurrency = uiState.value.generateForeverConcurrency
  }

  if (tool.value && uiState.value.generateForeverMode) {
    try {
      await axios.post(`${API_BASE}/generate/forever/unregister`, null, {
        params: {
          generator_instance_id: generatorInstanceId,
          backend_name: tool.value.generator,
          tool_id: tool.value.full_tool_id
        }
      })
    } catch (err) {
      console.error('Failed to unregister forever mode:', err)
    }
  }

  stopAvailabilityPolling()
  if (loadRetryTimeout) {
    clearTimeout(loadRetryTimeout)
    loadRetryTimeout = null
  }

  window.removeEventListener('keydown', handleKeyDown)
})
</script>
