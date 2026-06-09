<template>
  <div class="w-full h-full flex bg-surface-overlay text-content-secondary relative">
    <!-- Slideshow Mode (overlays everything when active) -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="jobsManager?.totalCompletedCount.value || 0"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :randomized="slideshowState.randomized"
      :random-seed="slideshowState.randomSeed"
      :auto-advance-on-new="true"
      :generator-instance-id="generatorInstanceId"
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
          <HopToToolMenu
            :source-tool-id="tool.full_tool_id"
            :tool-name="tool.name"
            :source-task-types="tool.task_types || []"
            @hop="handleHopToTool"
          />
          <div class="flex items-center gap-2">
            <span
              v-if="tool.metadata?.display_price"
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
              @revert="revertToBaseState"
              @clear="handleResetToDefaults"
            />
          </div>
        </div>
        <!-- Subtitle: Provider, task types -->
        <div class="text-xs mt-1 mb-6 flex items-center gap-1.5 text-content-muted">
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
          @copy-prompt="globalPrefs.prompt = remixSource!.promptSnippet; suppressRemixDeactivation()"
          @copy-exact-prompt="globalPrefs.prompt = remixSource!.renderedPrompt!; suppressRemixDeactivation()"
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

        <!-- Page-level agent chat. Mounted unconditionally and teleported into
             the single full-width dock so it survives layout switches without
             ever changing target — the chat stays put while the studio/stage
             toggle animates the columns above it. -->
        <Teleport defer to="#agent-dock">
          <PromptAgentChat
            ref="promptAgentChatRef"
            :prompt="globalPrefs.prompt"
            :has-prompt="hasPrompt"
            v-model:instructions="globalPrefs.agentInstructions"
          />
        </Teleport>

        <!-- Media Input (images or videos, unified picker) -->
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
          :allow-prep="mediaInputConfig.allowPrep"
          @view-media="openSingleImageSlideshow"
          @suggest-resolution="onSuggestResolution"
          @suggest-aspect="onSuggestAspect"
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


        <!-- Video Frame Images (for image-to-video) -->
        <VideoImagePicker
          v-if="hasVideoFrames"
          :start-image="videoImages.startImage"
          :end-image="videoImages.endImage"
          :show-end-frame="hasEndFrame"
          @update:start-image="videoImages.startImage = $event"
          @update:end-image="videoImages.endImage = $event"
          @view-image="openSingleImageSlideshow"
        />

        <!-- Video Parameters: Duration (for tools using duration param) -->
        <div v-if="hasDuration" class="mb-6">
          <div class="rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]">
            <!-- Duration -->
            <div class="flex items-center justify-between gap-4 px-4 py-3">
              <div class="w-[55%] flex-shrink-0">
                <div class="text-sm font-medium text-content">Duration</div>
                <div class="text-xs text-content-muted mt-0.5">Video length in seconds</div>
              </div>
              <!-- Dropdown for fixed duration options -->
              <SettingsDropdown
                v-if="allowedDurations"
                :model-value="String(modelParams.duration || durationConfig.default)"
                @update:model-value="modelParams.duration = Number($event)"
                :options="allowedDurations.map((d: number) => ({ value: String(d), label: `${d}s` }))"
              />
              <!-- Slider for continuous range -->
              <div v-else class="flex items-center gap-1.5 flex-shrink-0">
                <input v-no-autocorrect
                  type="range"
                  v-model.number="modelParams.duration"
                  :min="durationConfig.min"
                  :max="durationConfig.max"
                  :step="durationConfig.step"
                  class="w-44 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                >
                <div class="text-sm text-content w-10 text-right">{{ (modelParams.duration || durationConfig.default).toFixed(1) }}s</div>
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
              <div class="w-[55%] flex-shrink-0">
                <div class="text-sm font-medium text-content">Frame Count</div>
                <div class="text-xs text-content-muted mt-0.5">Number of frames to generate</div>
              </div>
              <div class="flex items-center gap-1.5 flex-shrink-0">
                <input v-no-autocorrect
                  type="range"
                  v-model.number="modelParams.frameCount"
                  :min="frameCountConfig.min"
                  :max="frameCountConfig.max"
                  class="w-44 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                >
                <div class="text-center">
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
          :tool-id="fullToolIdFromProps"
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

        <!-- Generic Parameters (dynamic from tool schema, grouped) -->
        <template v-for="paramGroup in groupedGenericParams" :key="paramGroup.group || 'ungrouped'">
          <div class="mb-6">
            <!-- Group header - collapsible if paramGroup.collapsible is true -->
            <div v-if="paramGroup.label" class="mb-3">
              <button
                v-if="paramGroup.collapsible"
                @click="toggleGroupCollapsed(paramGroup.group)"
                type="button"
                class="flex items-center gap-2 text-xs font-medium text-content-muted uppercase tracking-wide hover:text-content-tertiary transition-colors"
              >
                <span :class="['transition-transform text-[10px]', getGroupCollapsed(paramGroup.group) ? '' : 'rotate-90']">&#9654;</span>
                {{ paramGroup.label }}
              </button>
              <span v-else class="text-xs font-medium text-content-muted uppercase tracking-wide">{{ paramGroup.label }}</span>
            </div>
            <!-- Parameters list (settings-style: label+desc on left, control on right) -->
            <div v-show="!paramGroup.collapsible || !getGroupCollapsed(paramGroup.group)" class="rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]">
              <template v-for="param in paramGroup.params" :key="param.name">
                <!-- Skip if visibleWhen condition not met -->
                <template v-if="!param.visibleWhen || modelParams[param.visibleWhen.param] === param.visibleWhen.value">
                  <!-- Seed control with randomize checkbox -->
                  <div v-if="param.control === 'seed'" class="flex items-center justify-between gap-4 px-4 py-3">
                    <div class="min-w-0 flex-1">
                      <div class="text-sm font-medium text-content">{{ param.label }}</div>
                      <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                    </div>
                    <div class="flex items-center justify-end gap-3 flex-wrap">
                      <input v-no-autocorrect
                        :value="modelParams[param.name]"
                        @input="modelParams[param.name] = parseIntOrNull(($event.target as HTMLInputElement).value)"
                        type="number"
                        :disabled="modelParams.randomizeSeed ?? true"
                        class="w-28 sm:w-36 px-2 py-1.5 bg-base border border-edge rounded text-content text-sm disabled:opacity-40 focus:outline-none focus:border-blue-500"
                      >
                      <label class="flex items-center gap-1.5 text-xs text-content-tertiary cursor-pointer">
                        <input v-no-autocorrect
                          :checked="modelParams.randomizeSeed ?? true"
                          @change="modelParams.randomizeSeed = ($event.target as HTMLInputElement).checked"
                          type="checkbox"
                          class="w-3.5 h-3.5 rounded"
                        >
                        <span>Randomize</span>
                      </label>
                    </div>
                  </div>
                  <!-- Enum/Select -->
                  <div v-else-if="param.enum" class="flex items-center justify-between gap-4 px-4 py-3">
                    <div class="min-w-0 flex-1">
                      <div class="text-sm font-medium text-content">{{ param.label }}</div>
                      <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                    </div>
                    <div class="min-w-0 max-w-[45%] flex-shrink-0">
                      <SettingsDropdown
                        :model-value="String(modelParams[param.name] ?? param.default)"
                        @update:model-value="modelParams[param.name] = $event"
                        :options="param.enum.map((opt: string) => ({ value: opt, label: param.enumLabels?.[opt] || formatEnumOption(opt, param.format) }))"
                      />
                    </div>
                  </div>
                  <!-- Number/Slider -->
                  <div v-else-if="param.type === 'number' || param.type === 'integer'" class="flex items-center justify-between gap-4 px-4 py-3">
                    <div class="min-w-0 flex-1">
                      <div class="text-sm font-medium text-content">{{ param.label }}</div>
                      <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                    </div>
                    <div class="flex min-w-0 w-[45%] max-w-[360px] flex-shrink-0 items-center justify-end gap-2">
                      <input v-no-autocorrect
                        type="range"
                        :value="modelParams[param.name] ?? param.default"
                        @input="modelParams[param.name] = Number(($event.target as HTMLInputElement).value)"
                        :min="param.minimum ?? 0"
                        :max="param.maximum ?? 100"
                        :step="param.step ?? (param.type === 'integer' ? 1 : 0.1)"
                        class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                      />
                      <input v-no-autocorrect
                        v-if="editingParam === param.name"
                        type="text"
                        :value="modelParams[param.name] ?? param.default"
                        @blur="commitParamEdit(param, $event)"
                        @keydown.enter="commitParamEdit(param, $event)"
                        @keydown.escape="editingParam = null"
                        class="w-16 flex-shrink-0 text-sm text-content-secondary bg-base border border-edge rounded px-2 py-1 text-right focus:outline-none focus:border-blue-500"
                        ref="paramEditInput"
                      />
                      <span
                        v-else
                        @dblclick="startParamEdit(param.name)"
                        class="w-12 flex-shrink-0 text-sm text-content-tertiary text-right cursor-text hover:text-content-secondary select-none"
                        :title="'Double-click to edit'"
                      >{{ formatGenericParamValue(param, modelParams[param.name] ?? param.default) }}</span>
                    </div>
                  </div>
                  <!-- Boolean/Checkbox -->
                  <div v-else-if="param.type === 'boolean'" class="flex items-center justify-between gap-4 px-4 py-3">
                    <div class="w-[55%] flex-shrink-0">
                      <div class="text-sm font-medium text-content">{{ param.label }}</div>
                      <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                    </div>
                    <input v-no-autocorrect
                      type="checkbox"
                      :checked="modelParams[param.name] ?? param.default"
                      @change="modelParams[param.name] = ($event.target as HTMLInputElement).checked"
                      class="flex-shrink-0 w-4 h-4 rounded border-edge bg-base text-blue-500 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
                    />
                  </div>
                  <!-- String input (textarea for x-control: textarea, otherwise single-line) -->
                  <div v-else-if="param.type === 'string'" class="px-4 py-3">
                    <div class="flex items-center justify-between gap-4 mb-2">
                      <div class="w-[55%] flex-shrink-0">
                        <div class="text-sm font-medium text-content">{{ param.label }}</div>
                        <div v-if="param.description && param.control !== 'textarea'" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                      </div>
                    </div>
                    <textarea v-no-autocorrect
                      v-if="param.control === 'textarea'"
                      :value="modelParams[param.name] ?? param.default ?? ''"
                      @input="modelParams[param.name] = ($event.target as HTMLTextAreaElement).value"
                      rows="4"
                      :placeholder="param.description || ''"
                      class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm resize-y focus:outline-none focus:border-blue-500 font-sans"
                    ></textarea>
                    <input v-no-autocorrect
                      v-else
                      type="text"
                      :value="modelParams[param.name] ?? param.default ?? ''"
                      @input="modelParams[param.name] = ($event.target as HTMLInputElement).value"
                      :placeholder="param.description"
                      class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </template>
              </template>
            </div>
          </div>
        </template>

        <div v-if="submissionError" class="mt-6 p-3 bg-red-500/10 border border-red-500/30 rounded-md text-red-500 text-sm">
          {{ submissionError }}
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
          <video
            v-if="outputsVideo && stageCurrentHash"
            :src="getMediaFileUrl(stageCurrentHash)"
            class="w-full h-full object-contain"
            autoplay loop muted playsinline
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

        <!-- Per-image marker toggles for the hero image. (Generation time/details
             live on the always-visible queue tile, so no pill here.) -->
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
              <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="marker.icon_svg" />
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
          :media-markers="jobsManager.mediaMarkers.value"
          :media-generation-times="jobsManager.mediaGenerationTimes.value"
          :batch-jobs="jobsManager.batchJobs.value"
          :is-video="outputsVideo"
          :image-mode="uiState.imageMode"
          :current-media-id="layoutMode === 'stage' ? stageCurrentMediaId : null"
          empty-message="No jobs yet"
          @job-click="handleQueueClick"
          @toggle-marker="handleToggleMarker"
          @dismiss-job="dismissJob"
          @retry-job="retryJob"
          @cancel-job="cancelJob"
          @cancel-and-dismiss-batch="cancelAndDismissBatch"
          @dismiss-batch="dismissBatch"
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

    <!-- Delete Tool Confirmation Modal -->

    <!-- Context Menu for queue images/videos -->
    <MediaContextMenu />

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
import { devModeRef } from '../appConfig'
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
import { useGenerationJobs } from '../composables/useGenerationJobs'
import {
  buildBasePayload,
  buildCapturedState,
  getPreUploadTasks,
  hasPromptFeature,
  type PayloadBuilderState,
  type PayloadBuilderConfig,
} from '../composables/useJobPayloadBuilder'
import { submitJobAsync, submitBatchJobAsync, BatchJobResponse } from '../composables/useSubmissionQueue'
import { useToolAutoDeleteDuration } from '../composables/useToolAutoDeleteDuration'
import { usePromptPreloader } from '../composables/usePromptPreloader'
import { useTabNavigation } from '../composables/useTabNavigation'
import { useGlobalKeyboardShortcuts } from '../composables/useGlobalKeyboardShortcuts'
import { useMediaApi } from '../composables/useMediaApi'
import { useProvidersApi, type ProviderTool } from '../composables/useProvidersApi'
import { useToolState, type ToolState } from '../composables/useToolState'
import { usePresetsApi } from '../composables/usePresetsApi'
import { useToolSchemaFeatures } from '../composables/useToolSchemaFeatures'
import { makeGlobalKey, makeToolDbKey } from '../utils/storageKeys'
import { getBlob, putBlob, deleteBlob } from '../utils/blobStorage'
import { getToolDefaults } from '../utils/generationDefaults'
import { parseGenerationConfig, type GenerationConfigUpdate } from '../utils/parseGenerationConfig'
import { isStimmaCloudTool as isStimmaCloud } from '../utils/stimmaCloud'
import { copyToClipboard } from '../utils/clipboard'
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
  UpscaleResolutionPicker,
  VideoImagePicker
} from '../components/generation'
import HopToToolMenu from '../components/HopToToolMenu.vue'
import RemixBanner from '../components/generation/RemixBanner.vue'
import PromptAgentChat from '../components/generation/PromptAgentChat.vue'
import JobsGrid from '../components/generation/JobsGrid.vue'
import SettingsDropdown from '../components/ui/SettingsDropdown.vue'
import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'

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
// Layout mode: 'studio' = controls primary (default), 'stage' = current image
// primary with controls demoted to a rail. Persisted per-tool via uiState
// (makeToolProfileKey 'ui'), like imageMode — see useGenerationPreferences.
const layoutMode = computed<'studio' | 'stage'>({
  get: () => uiState.value.layoutMode,
  set: (v) => { uiState.value.layoutMode = v }
})

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
const stageCompletedJobs = computed<any[]>(() => jobsManager?.sortedCompletedJobs.value || []) // newest-first
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
const { getProviderTool, getToolState, saveToolState, refreshProviderTools, subscribeToProviderChanges, uploadToTool } = useProvidersApi()

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

// Inline param editing state
const editingParam = ref<string | null>(null)

function startParamEdit(paramName: string) {
  editingParam.value = paramName
  // Focus the input after Vue renders it
  nextTick(() => {
    const input = document.querySelector(`input[ref="paramEditInput"]`) as HTMLInputElement
    if (input) {
      input.focus()
      input.select()
    }
  })
}

function commitParamEdit(param: any, event: Event) {
  const input = event.target as HTMLInputElement
  const rawValue = input.value.replace(/%$/, '')  // Strip % suffix if present
  const numValue = Number(rawValue)

  if (!isNaN(numValue)) {
    // Clamp to min/max
    const min = param.minimum ?? 0
    const max = param.maximum ?? 100
    const clamped = Math.max(min, Math.min(max, numValue))
    modelParams.value[param.name] = param.type === 'integer' ? Math.round(clamped) : clamped
  }

  editingParam.value = null
}

// Tool availability computed properties
const toolAvailability = computed(() => tool.value?.availability || 'available')
const providerDisplayName = computed(() => tool.value?.provider_name || tool.value?.provider_id || 'Provider')
const toolDisplayName = computed(() => tool.value?.name || 'this tool')
const isStimmaCloudTool = computed(() => isStimmaCloud(tool.value))

// Format task types for display (e.g., "text-to-image" -> "Text to Image")
const taskTypesDisplay = computed(() => {
  const taskTypes = tool.value?.task_types
  if (!taskTypes || taskTypes.length === 0) return null
  return taskTypes
    .map(t => t.split('-').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' '))
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

// Computed getter for media input items based on accept type
const mediaInputItems = computed(() => {
  if (!mediaInputConfig.value) return []
  return mediaInputConfig.value.accept === 'image'
    ? globalPrefs.value.inputImages
    : globalPrefs.value.inputVideos
})

// Update handler for media input items
function updateMediaInputItems(items: any[]) {
  if (!mediaInputConfig.value) return
  if (mediaInputConfig.value.accept === 'image') {
    globalPrefs.value.inputImages = items
  } else {
    globalPrefs.value.inputVideos = items
  }
}

// Video frame images for image-to-video (initialized after toolId is available)
const videoImages = reactive({
  startImage: null as { path: string; filename: string; hash?: string; mediaId?: number } | null,
  endImage: null as { path: string; filename: string; hash?: string; mediaId?: number } | null
})

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

// Format enum option for display based on x-format hint
function formatEnumOption(value: string, format?: string): string {
  if (format === 'filename') {
    // Strip folder path and common extensions (for checkpoints, loras, etc.)
    return value
      .replace(/^.*\//, '')  // Remove folder path
      .replace(/\.(safetensors|ckpt|pt|bin)$/i, '')  // Remove extension
  }
  // Default: just return the value as-is
  return value
}

// Format generic parameter value for display
function formatGenericParamValue(param: any, value: any): string {
  if (value === undefined || value === null) return ''
  const step = param.step ?? (param.type === 'integer' ? 1 : 0.1)
  let formatted: string
  if (step < 1) {
    // Determine decimal places from step
    const decimals = step.toString().split('.')[1]?.length || 1
    formatted = Number(value).toFixed(decimals)
  } else {
    formatted = String(value)
  }
  // Apply format suffix
  if (param.format === 'percent') {
    formatted += '%'
  } else if (param.unit === 'frames') {
    // Show seconds based on fps
    const fps = modelParams.value.fps || 16
    const seconds = (Number(value) / fps).toFixed(1)
    formatted += ` (~${seconds}s)`
  }
  return formatted
}

// Parse integer from string, returning null for invalid input
function parseIntOrNull(value: string): number | null {
  const parsed = parseInt(value, 10)
  return isNaN(parsed) ? null : parsed
}


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

// Duration config from schema (for tools using duration param instead of frame_count)
const durationConfig = computed(() => {
  const props = tool.value?.parameter_schema?.properties || {}
  const schema = props.duration
  if (schema) {
    return {
      min: schema.minimum ?? 1.0,
      max: schema.maximum ?? 10.0,
      step: schema['x-step'] ?? 0.5,
      default: schema.default ?? 5.0,
    }
  }
  return { min: 1.0, max: 10.0, step: 0.5, default: 5.0 }
})

// Whether tool has an fps param
const hasFps = computed(() => {
  const props = tool.value?.parameter_schema?.properties || {}
  return 'fps' in props
})

const fpsOptions = computed(() => {
  const props = tool.value?.parameter_schema?.properties || {}
  const fpsSchema = props.fps
  if (fpsSchema) {
    const min = fpsSchema.minimum ?? 16
    const max = fpsSchema.maximum ?? 32
    const options = new Set<number>()
    for (const v of [16, 24, 25, 30, 32]) {
      if (v >= min && v <= max) options.add(v)
    }
    if (fpsSchema.default != null) options.add(fpsSchema.default)
    const sorted = Array.from(options).sort((a: number, b: number) => a - b)
    if (sorted.length > 0) return sorted
  }
  return [16, 24, 32]
})

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
// Include project scope for project-scoped tool instances
const projectSuffix = projectScopeId.value ? `__project_${projectScopeId.value}` : ''
const toolIdForStorage = fullToolIdFromProps.replace(/:/g, '_') + projectSuffix

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
    await loadTool(true)
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

// Generator instance ID for this tool (unique per tool AND per browser tab)
// Use @@ as separator to avoid ambiguity with hyphens in tool IDs (e.g., nano-banana vs nano-banana-edit)
const generatorInstanceId = `tool-${toolIdForStorage}@@${tabGuid}`

// Scoped tool ID for localStorage keys (includes project suffix for project-scoped instances)
function scopedToolId(fullToolId: string): string {
  return projectSuffix ? fullToolId + projectSuffix : fullToolId
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
      videoImages.startImage = parsed.startImage || null
      videoImages.endImage = parsed.endImage || null
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
const dismissedRemix = ref<{ mediaId: number; promptSnippet: string; renderedPrompt?: string; seed?: number | null } | null>(null)
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

// Job management composable - called at top level
// This MUST be called synchronously during setup, not in an async function
// taskType will be null initially, but jobs are filtered by generatorInstanceId anyway
const jobsManager = useGenerationJobs({
  taskType: null,  // We filter by generatorInstanceId instead
  generatorInstanceId: generatorInstanceId
})

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
} = useGenerationPreferences({
  taskType: 'text-to-image',  // Just for defaults structure - we manage our own state persistence
  fullToolId: fullToolIdFromProps
})

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
const maskStorageKey = computed(() => tool.value ? makeToolDbKey(tool.value.full_tool_id, 'mask') : null)

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
  const key = makeToolDbKey(newFullToolId, 'mask')
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
  return makeToolDbKey(tool.value.full_tool_id, 'paint', slotIndex)
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

    const key = makeToolDbKey(fullToolId, 'paint', i)
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

// Prompt preloader
const { getCachedImprovedPrompt, onCacheUsed, updateConcurrentJobs } = usePromptPreloader({
  prompt: computed(() => globalPrefs.value.prompt),
  autoImproveEnabled: computed(() => globalPrefs.value.promptOptions?.autoImprove?.enabled ?? false),
  autoImproveInstructions: computed(() => globalPrefs.value.promptOptions?.autoImprove?.instructions ?? null)
})

// Slideshow state
const slideshowState = reactive({
  active: false,
  totalCount: 0,
  startIndex: 0,
  pageProvider: null as any,
  randomized: false,
  randomSeed: null as number | null
})

function enterSlideshow(params: any) {
  slideshowState.active = true
  slideshowState.totalCount = params.totalCount
  slideshowState.startIndex = params.startIndex
  slideshowState.pageProvider = params.pageProvider
  slideshowState.randomized = params.randomized
  slideshowState.randomSeed = params.randomSeed
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
  () => _loraPool.getAllItems(fullToolIdFromProps),
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
  _loraPool.syncItemsToPool(fullToolIdFromProps, items)
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
      alert(`${errors.length} upload(s) failed:\n${errors.join('\n')}`)
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
  allowedDurations,
  hasVideoFrames,
  hasEndFrame,
  outputsVideo,
  isFromScratch,
  mediaInputConfig,
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
  scopedToolId: projectSuffix ? fullToolIdFromProps + projectSuffix : undefined,
  tool,
  globalPrefs,
  modelParams,
  toolLoras,
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

const activeJobCount = computed(() => {
  const jobs = jobsManager?.jobs.value
  if (!jobs) return 0
  return jobs.filter((j: any) => ['queued', 'assigned', 'processing'].includes(j.status)).length
})

watch(activeJobCount, (count) => {
  updateConcurrentJobs(count)
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

function showResAutoChange(newW: number, newH: number) {
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
    modelParams.value.width = dims.width
    modelParams.value.height = dims.height
  }
  resAutoChange.value = null
  if (resAutoChangeTimer) { clearTimeout(resAutoChangeTimer); resAutoChangeTimer = null }
}

function onResolutionUpdate(width: number, height: number) {
  modelParams.value.width = width
  modelParams.value.height = height
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
    agentThinking: globalPrefs.value.agentThinking ?? false,
  }
}

// Note: handlePresetSelect, handlePresetSaved, clearActivePreset, revertToBaseState,
// saveToActivePreset, saveAsToolDefaults are now provided by useToolState composable
function handleResetToDefaults() {
  clearActivePreset()
  remixSource.value = null
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

async function loadTool(forceReload = false) {
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

  isInitialLoading.value = true
  error.value = null

  try {
    // Load provider tool descriptor; tolerate state fetch failures
    const providerTool = await getProviderTool(fullToolId)
    const toolState = await getToolState(fullToolId).catch(() => ({ state: {} as Record<string, any> }))
    tool.value = buildToolWithState(providerTool, toolState.state || {})
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

  // Set video-specific defaults (for tools with duration param)
  if (hasDuration.value) {
    if (modelParams.value.duration == null) {
      modelParams.value.duration = allowedDurations.value?.[0] ?? durationConfig.value.default
    }
    if (hasFps.value && !modelParams.value.fps) {
      const props = tool.value?.parameter_schema?.properties || {}
      const fpsDefault = props.fps?.default
      modelParams.value.fps = fpsDefault || fpsOptions.value[0] || 24
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

  const storageKey = makeToolDbKey(tool.value.full_tool_id, 'pending_input')
  const pendingInput = sessionStorage.getItem(storageKey)
  if (!pendingInput) {
    return
  }

  try {
    const config = JSON.parse(pendingInput)
    sessionStorage.removeItem(storageKey)

    // Apply input based on what the tool's parameter_schema expects
    if (mediaInputConfig.value?.accept === 'image' && config.inputImages?.length > 0) {
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
      if (config.appendImages && mediaInputConfig.value.max > 1) {
        // Append to existing images, replacing last slot(s) if full
        const max = mediaInputConfig.value.max
        const existing = globalPrefs.value.inputImages
        const slotsAvailable = max - existing.length

        if (slotsAvailable >= newImages.length) {
          // Room to append all
          globalPrefs.value.inputImages = [...existing, ...newImages]
        } else {
          // Replace from the end to make room
          const keepCount = max - newImages.length
          globalPrefs.value.inputImages = [...existing.slice(0, keepCount), ...newImages]
        }
      } else {
        globalPrefs.value.inputImages = newImages
      }
    }

    if (hasVideoFrames.value && config.startImage) {
      const newFrame = {
        path: config.startImage.path,
        filename: config.startImage.filename || config.startImage.hash,
        hash: config.startImage.hash,
        mediaId: config.startImage.mediaId
      }
      // Drop into the first empty slot; if both filled, replace start
      if (videoImages.startImage && !videoImages.endImage) {
        videoImages.endImage = newFrame
      } else {
        videoImages.startImage = newFrame
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
      if (config.appendVideos) {
        // Append to existing videos (for video-stitch)
        globalPrefs.value.inputVideos = [...globalPrefs.value.inputVideos, ...newVideos]
      } else {
        globalPrefs.value.inputVideos = newVideos
      }
    }

    // Clear the query param
    router.replace({ query: {} })
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

  const storageKey = makeToolDbKey(tool.value.full_tool_id, 'pending_generation')
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

    router.replace({ query: {} })
  } catch (err) {
    console.error('Failed to load pending generation config:', err)
    sessionStorage.removeItem(storageKey)
  }
}

// Load generation config from a media item (remix flow)
async function loadRemix(mediaId: string) {
  if (!tool.value) return

  loadingGenerationConfig.value = true

  try {
    const response = await axios.post(
      `/api/generate/config-from-media/${mediaId}?target_tool_id=${tool.value.full_tool_id}`
    )
    const data = response.data

    // Parse config into structured updates
    const update = parseGenerationConfig(data, {
      hasPrompt: hasPrompt.value,
      hasFrameCount: hasFrameCount.value,
      hasResolution: hasResolution.value,
      hasVideoFrames: hasVideoFrames.value,
    })
    if (!update) return

    applyAdaptedConfig(update)

    // Restore source inputs for the target tool:
    // - I2V tools: use the ORIGINAL source inputs (start/end frames from the generation)
    //   NOT the output video — you want to re-generate from the same start frame
    // - Image-edit tools: use the remix source image itself as the input
    //   (the user wants to re-edit that result, not its ancestors)
    const sourceInputs: any[] = data.source_inputs || []
    const remixInput = data.remix_source_input

    if (hasVideoFrames.value && sourceInputs.length > 0) {
      // I2V: restore original start/end frames
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
            })
          } catch (err) {
            console.warn('Failed to copy source input to reference:', err)
          }
        }
        if (restoredImages.length > 0) {
          globalPrefs.value.inputImages = restoredImages
        }
      }
      // If no edit source inputs (t2i source), don't set inputImages — tool stays in t2i mode
    }

    // Set remix source
    remixSource.value = {
      mediaId: Number(mediaId),
      promptSnippet: data.source_prompt_snippet || '',
      renderedPrompt: data.prompt_variants?.rendered || undefined,
      seed: data.seed ?? null,
    }

    router.replace({ query: {} })
  } catch (err) {
    console.error('Failed to load remix from media:', err)
  } finally {
    loadingGenerationConfig.value = false
  }
}

// Handle hopping to another tool with current state
async function handleHopToTool(targetTool: { full_tool_id: string; name: string }) {
  if (!tool.value) return

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

    // Store config in sessionStorage for the target tool to pick up
    const storageKey = makeToolDbKey(targetTool.full_tool_id, 'pending_generation')
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
        role: img.role || null,
      })),
      // Don't transfer sampling params - let target tool use its defaults
    }

    // Carry forward inspiration source if set
    if (remixSource.value) {
      payload._remixSource = remixSource.value
    }

    sessionStorage.setItem(storageKey, JSON.stringify(payload))

    // Navigate to target tool
    router.push({
      name: 'tool',
      params: { fullToolId: targetTool.full_tool_id },
      query: {
        loadGeneration: Date.now().toString(),  // Force detection for KeepAlive'd components
      }
    })
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
async function submitJob() {
  if (!tool.value || !canSubmit.value) return
  const count = Math.min(8, Math.max(1, uiState.value.batchSize || 1))
  for (let i = 0; i < count; i++) {
    await submitOneJob()
  }
}

async function submitOneJob() {
  if (!tool.value || !canSubmit.value) {
    return
  }

  submissionError.value = null

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
      return
    }
  }

  // Build captured state from schema
  const capturedState = buildCapturedState(builderConfig, builderState, uploadResults)

  // Thread inspiration lineage into parameters
  if (remixSource.value) {
    capturedState.parameters.inspired_by_media_id = remixSource.value.mediaId
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
  const promptOptions = capturedState.promptOptions

  const cachedPrompt = toolHasPrompt && promptOptions?.autoImprove?.enabled
    ? getCachedImprovedPrompt(prompt, promptOptions.autoImprove.instructions || null)
    : null

  const needsEnhancing = toolHasPrompt && promptOptions?.autoImprove?.enabled && !cachedPrompt
  const pendingId = needsEnhancing
    ? jobsManager.addPendingJob(prompt, { model_name: tool.value!.model, generator_name: tool.value!.generator })
    : null

  if (cachedPrompt) onCacheUsed()

  // Check if this is a batch submission (any input has a set)
  const inputImages = globalPrefs.value.inputImages || []
  const hasSetInput = inputImages.some((img: any) => img.isSet)

  if (hasSetInput) {
    // Batch submission - convert set inputs to set_id format
    const setInput = inputImages.find((img: any) => img.isSet)
    if (!setInput?.setId) {
      console.error('Set input missing setId')
      submissionError.value = 'Invalid set input'
      return
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
      cachedImprovedPrompt: cachedPrompt,
      buildPayload: (processedPrompt, promptMetadata) => ({
        ...basePayload,
        parameters: {
          ...batchParameters,
          prompt: processedPrompt,
        },
        prompt_metadata: promptMetadata,
        // Let backend generate smart title from input set info
      }),
      onSubmitted: (batchInfo: BatchJobResponse) => {
        if (pendingId) jobsManager?.removePendingJob(pendingId)
        console.log(`Batch submitted: ${batchInfo.total_jobs} jobs, batch_id: ${batchInfo.batch_id}`)
        // Track active batch for forever mode (batches run sequentially)
        if (uiState.value.generateForeverMode) {
          foreverModeActiveBatchId.value = batchInfo.batch_id
        }
      },
      onError: (err: any) => {
        if (pendingId) jobsManager?.removePendingJob(pendingId)
        submissionError.value = err.response?.data?.detail || 'Failed to submit batch job'
      }
    })
  } else {
    // Regular single-job submission
    submitJobAsync({
      prompt,
      promptOptions,
      cachedImprovedPrompt: cachedPrompt,
      buildPayload: (processedPrompt, promptMetadata) => ({
        ...basePayload,
        parameters: {
          ...capturedState.parameters,
          prompt: processedPrompt,  // Override with processed prompt
        },
        prompt_metadata: promptMetadata,
      }),
      onSubmitted: () => { if (pendingId) jobsManager?.removePendingJob(pendingId) },
      onError: (err: any) => {
        if (pendingId) jobsManager?.removePendingJob(pendingId)
        submissionError.value = err.response?.data?.detail || 'Failed to submit job'
      }
    })
  }
}

// Forever mode
async function startForeverMode(concurrency: number) {
  if (!tool.value) return
  uiState.value.generateForeverMode = true
  modelParams.value.randomizeSeed = true
  foreverModeIdleCount.value = 0  // Reset idle counter on start
  try {
    await axios.post(`${API_BASE}/generate/forever/register`, null, {
      params: {
        generator_instance_id: generatorInstanceId,
        backend_name: tool.value.generator,
        max_concurrency: concurrency
      }
    })
  } catch (err) {
    console.error('Failed to register forever mode:', err)
  }
}

async function stopForeverMode() {
  if (!tool.value) return
  uiState.value.generateForeverMode = false
  foreverModeActiveBatchId.value = null  // Clear active batch tracking
  try {
    await axios.post(`${API_BASE}/generate/forever/unregister`, null, {
      params: {
        generator_instance_id: generatorInstanceId,
        backend_name: tool.value.generator
      }
    })
  } catch (err) {
    console.error('Failed to unregister forever mode:', err)
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

// Extended-thinking toggle. It's a normal per-tool setting: backed by
// globalPrefs so it persists, scopes to the tool/project, and rides presets like
// any other param (see buildToolState/applyToolState/getCurrentState). Defaults
// off — the prompt-agent does single-step editor control; the user turns it on
// per tool when a weaker model needs the extra reasoning.
const promptAgentThinking = computed<boolean>({
  get: () => globalPrefs.value.agentThinking ?? false,
  set: (v: boolean) => { globalPrefs.value.agentThinking = v },
})

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
  getThinking: () => promptAgentThinking.value,
})

provide(PROMPT_EDITOR_AGENT_KEY, {
  send: promptMiniAgent.send,
  running: promptMiniAgent.running,
  error: promptMiniAgent.error,
  lastReply: promptMiniAgent.lastReply,
  messages: promptMiniAgent.messages,
  clearHistory: promptMiniAgent.clearHistory,
  thinking: promptAgentThinking,
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
    // On disconnect, clear forever mode batch tracking to prevent stalls
    // (if backend crashes mid-batch, the batch_completed event never fires)
    foreverModeActiveBatchId.value = null
  }

  if (isConnected && tool.value) {
    sendWebSocketMessage('register_generator_instance', {
      generator_instance_id: generatorInstanceId
    })

    // On reconnect, resync job state from backend to clear phantom jobs
    if (wasConnected === false) {
      await jobsManager?.loadJobs()
    }

    // Re-register forever mode on reconnect
    if (wasConnected === false && uiState.value.generateForeverMode) {
      // Small delay to ensure backend HTTP routes are ready
      await new Promise(resolve => setTimeout(resolve, 500))

      // Retry up to 3 times
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await axios.post(`${API_BASE}/generate/forever/register`, null, {
            params: {
              generator_instance_id: generatorInstanceId,
              backend_name: tool.value.generator,
              max_concurrency: uiState.value.generateForeverConcurrency
            }
          })
          break
        } catch (err) {
          console.error(`Failed to re-register forever mode (attempt ${attempt + 1}):`, err)
          if (attempt < 2) {
            await new Promise(resolve => setTimeout(resolve, 1000))
          }
        }
      }
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

// Queue of pending work requests (count of how many jobs to submit)
const workRequestQueue = ref(0)
const processingWorkQueue = ref(false)

// Track active batch in forever mode (batches run sequentially, not in parallel)
const foreverModeActiveBatchId = ref<string | null>(null)

// Track consecutive failures to auto-disable forever mode
const consecutiveFailures = ref(0)
const MAX_CONSECUTIVE_FAILURES = 3

// Check if current inputs are in batch mode (have a set)
function isInBatchMode(): boolean {
  const inputImages = globalPrefs.value.inputImages || []
  return inputImages.some((img: any) => img.isSet)
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
  if (isInBatchMode() && foreverModeActiveBatchId.value) {
    console.log('[Forever Mode] Ignoring work request - batch already in progress')
    declineWorkRequest(data.backend_name)
    return
  }

  // Queue this work request
  workRequestQueue.value++

  // Process queue if not already processing
  if (!processingWorkQueue.value) {
    await processWorkQueue()
  }
}

async function processWorkQueue() {
  if (processingWorkQueue.value) return
  processingWorkQueue.value = true

  try {
    while (workRequestQueue.value > 0 && uiState.value.generateForeverMode && canSubmit.value) {
      // In batch mode, only process if no batch is active
      if (isInBatchMode() && foreverModeActiveBatchId.value) {
        console.log('[Forever Mode] Waiting for current batch to complete')
        break
      }

      workRequestQueue.value--
      modelParams.value.seed = generateRandomSeed()
      await submitJob()

      // In batch mode, stop after submitting one batch - wait for completion
      if (isInBatchMode()) {
        break
      }
    }
  } finally {
    // Decline any remaining queued work requests that won't be processed
    if (workRequestQueue.value > 0 && tool.value) {
      const remaining = workRequestQueue.value
      workRequestQueue.value = 0
      for (let i = 0; i < remaining; i++) {
        declineWorkRequest(tool.value.generator)
      }
    }
    processingWorkQueue.value = false
  }
}

// Forever mode failure tracking
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

  consecutiveFailures.value++

  if (consecutiveFailures.value >= MAX_CONSECUTIVE_FAILURES) {
    consecutiveFailures.value = 0
    await stopForeverMode()
  }
}

async function handleForeverModeBatchCompleted(data: any) {
  // Check if this is our active batch
  if (data.batch_id !== foreverModeActiveBatchId.value) return

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
    workRequestQueue.value++
    if (!processingWorkQueue.value) {
      await processWorkQueue()
    }
  }
}

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

async function openSlideshow(job: any) {
  if (!job.result_media_id || !jobsManager) return

  const index = jobsManager.sortedCompletedJobs.value.findIndex((j: any) => j.id === job.id)
  if (index === -1) return

  enterSlideshow({
    totalCount: jobsManager.totalCompletedCount.value,
    startIndex: index,
    pageProvider: jobsManager.fetchGeneratedImages,
    randomized: false,
    randomSeed: null
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
    randomSeed: null
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
  if (newValue && tool.value && !isInitialLoading.value) {
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
  if (newValue && tool.value) {
    // Reset the flag so we can load the new config (important for KeepAlive'd components)
    pendingGenerationApplied.value = false
    // Close slideshow if open
    if (slideshowState.active) {
      exitSlideshow()
    }
    loadPendingGeneration()
  }
}, { immediate: false })

// Watch for remixFrom query param (also supports legacy inspireFrom/loadFromMedia)
watch(
  () => route.query.remixFrom || route.query.inspireFrom || route.query.loadFromMedia,
  (mediaId) => {
    // IMPORTANT: Only load if this watcher is for the CURRENT route's tool
    // During navigation, watchers on the OLD page can fire before deactivation
    if (mediaId && tool.value && route.params.fullToolId === tool.value.full_tool_id) {
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
          max_concurrency: uiState.value.generateForeverConcurrency
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
  // Clean up profile change listeners
  window.removeEventListener('profile-will-change', handleProfileWillChange)
  window.removeEventListener('profile-changed', handleProfileChanged)
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
          backend_name: tool.value.generator
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
