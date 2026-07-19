<template>
  <div
    class="relative space-y-3 mb-6"
    :class="disabled ? 'opacity-40 pointer-events-none' : ''"
    :data-drop-zone="`media-picker-${accept}`"
    @dragover.prevent="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop($event)"
  >
    <div class="flex items-baseline justify-between pb-1 mb-1.5">
      <div class="flex items-baseline gap-2 min-w-0">
        <label class="text-xs font-semibold text-content-secondary">{{ displayLabel }}</label>
        <span v-if="props.description" class="text-xs text-content-muted truncate">{{ props.description }}</span>
      </div>
      <span v-if="!batchMode" class="text-[10px] font-mono tabular-nums text-content-tertiary flex-shrink-0">{{ items.length }}/{{ maxItems }}</span>
    </div>

    <!-- Item Grid/Sequence -->
    <div :class="reorderable ? 'flex flex-wrap gap-3 items-start' : 'grid gap-3 items-start [grid-template-columns:repeat(auto-fill,minmax(min(100%,15rem),1fr))]'">
      <template v-for="(item, index) in displayItems" :key="item.originalIndex">
        <div class="flex items-center gap-1 min-w-0">
          <div
            :class="[
              'flex flex-col flex-shrink-0 min-w-0',
              reorderable ? 'w-[17rem]' : 'w-full flex-1',
              reorderable ? 'gap-1.5' : 'gap-2'
            ]"
          >
            <div
              :class="[
                'relative bg-matte overflow-hidden group flex-shrink-0 rounded-media',
                reorderable
                  ? 'w-[17rem] h-[9.5rem] cursor-grab'
                  : (accept === 'audio' ? 'w-full h-[7rem]' : 'w-full h-[18.5rem]'),
                dragIndex === item.originalIndex ? 'opacity-30' : '',
                dropIndex === index && dropIndex !== dragIndex ? 'ring-2 ring-accent' : ''
              ]"
              :draggable="!!item.mediaId && !batchMode"
              @dragstart="item.mediaId && !batchMode && onReorderDragStart($event, item)"
              @dragend="onReorderDragEnd()"
              @dragover.prevent.stop="onTileDragOver($event, index)"
              @dragleave.stop="onDragLeave"
              @drop.prevent.stop="onTileDrop($event, index)"
            >
              <!-- Set preview with thumbnail -->
              <template v-if="item.isSet">
                <AppImage
                  :src="item.mediaId ? getThumbnailUrl(item.mediaId, 256) : ''"
                  :alt="`Set with ${item.setItemCount} items`"
                  contain
                  container-class="w-full h-full"
                  preserve-previous-on-src-change
                />
                <!-- Set badge overlay (upper right, matching browser style) -->
                <div class="absolute top-2 right-2 z-chrome">
                  <div class="bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
                    <svg class="w-4 h-4 flex-shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
                    </svg>
                    <span class="text-xs font-semibold text-content leading-none">{{ item.setItemCount }}</span>
                  </div>
                </div>
              </template>

              <!-- Frame scrub: while picking a frame, a live <video> takes over the
                   image area so scrubbing is instant and frame-accurate. -->
              <video
                v-else-if="accept === 'image' && item._videoSource && openPrepPanel[item.originalIndex] === 'frame'"
                :ref="(el) => setScrubVideo(item.originalIndex as number, el as HTMLVideoElement | null)"
                :src="frameVideoUrl(item)"
                class="w-full h-full object-contain bg-surface"
                muted
                playsinline
                preload="auto"
                @loadedmetadata="onScrubVideoLoaded(item, $event)"
              />

              <!-- Library-backed image preview. Use the exact Media identity rather
                   than its content hash: duplicate payloads can share a hash while
                   only this Media row owns the path used by the tool. -->
              <MediaImage
                v-else-if="accept === 'image' && item.mediaId && item.hash"
                :media-id="item.mediaId"
                :thumbnail="false"
                :alt="`${accept} ${index + 1}`"
                contain
                container-class="w-full h-full"
                img-class="cursor-pointer"
                :draggable="false"
                :enable-context-menu="false"
                @click="onItemClick(item)"
              />

              <!-- Derived/reference-cache image preview. Once prep has been
                   applied, path is the derived file and must take precedence over
                   the original item's mediaId. -->
              <AppImage
                v-else-if="accept === 'image'"
                :src="getMediaUrl(item)"
                :alt="`${accept} ${index + 1}`"
                contain
                container-class="w-full h-full"
                :img-class="item.mediaId ? 'cursor-pointer' : ''"
                preserve-previous-on-src-change
                @click="onItemClick(item)"
              />

              <!-- Video preview -->
              <video
                v-else-if="accept === 'video' && !item.isSet"
                :src="getMediaUrl(item)"
                :class="['w-full h-full', reorderable ? 'object-contain bg-surface-raised' : 'object-contain']"
                muted
                playsinline
                preload="auto"
                @loadedmetadata="onVideoLoaded($event)"
                @mouseenter="($event.target as HTMLVideoElement).play()"
                @mouseleave="onVideoLeave($event)"
                @error="onVideoError($event, item)"
              />

              <!-- Audio preview: waveform band + compact inline player (matches how
                   audio reads everywhere else in the app — library grid, slideshow). -->
              <CompactAudioPlayer
                v-else-if="accept === 'audio'"
                :src="getMediaUrl(item)"
                :media-id="item.mediaId"
              />

              <!-- Video error fallback -->
              <div v-if="accept === 'video' && videoErrors[item.path]" class="absolute inset-0 flex items-center justify-center bg-surface">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-8 h-8 text-content-muted">
                  <path d="M3.25 4A2.25 2.25 0 0 0 1 6.25v7.5A2.25 2.25 0 0 0 3.25 16h7.5A2.25 2.25 0 0 0 13 13.75v-7.5A2.25 2.25 0 0 0 10.75 4h-7.5ZM19 4.75a.75.75 0 0 0-1.28-.53l-3 3a.75.75 0 0 0-.22.53v4.5c0 .199.079.39.22.53l3 3a.75.75 0 0 0 1.28-.53V4.75Z" />
                </svg>
              </div>

              <!-- Video icon overlay (for videos only) -->
              <div v-if="accept === 'video' && !reorderable" class="absolute top-1 left-1 w-5 h-5 bg-black/60 rounded-full flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content">
                  <path d="M3.25 4A2.25 2.25 0 0 0 1 6.25v7.5A2.25 2.25 0 0 0 3.25 16h7.5A2.25 2.25 0 0 0 13 13.75v-7.5A2.25 2.25 0 0 0 10.75 4h-7.5ZM19 4.75a.75.75 0 0 0-1.28-.53l-3 3a.75.75 0 0 0-.22.53v4.5c0 .199.079.39.22.53l3 3a.75.75 0 0 0 1.28-.53V4.75Z" />
                </svg>
              </div>

              <!-- Batch count badge (stack indicator) -->
              <div v-if="batchMode" class="absolute top-2 left-2 z-chrome">
                <div class="bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
                  <svg class="w-4 h-4 flex-shrink-0 text-accent-hi" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" /></svg>
                  <span class="text-xs font-semibold text-content leading-none">{{ items.length }}</span>
                </div>
              </div>

              <!-- Clear collapsed batch slot -->
              <button
                v-if="batchMode"
                @click.stop="clearItems"
                class="absolute top-1 right-1 z-chrome w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                title="Clear"
                aria-label="Clear"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
                  <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                </svg>
              </button>

              <!-- Remove button -->
              <button
                v-if="!batchMode"
                @click.stop="removeItem(item.originalIndex)"
                class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
                  <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                </svg>
              </button>

              <!-- Slot-label badge (named-slot mode, e.g. Start / End) -->
              <div v-if="!batchMode && useSlotLabels" class="absolute top-1 left-1 px-1.5 h-5 flex items-center justify-center bg-black/70 rounded pointer-events-none">
                <span class="text-[10px] text-white font-semibold leading-none">{{ slotBadge(index) }}</span>
              </div>

              <!-- Order badge (only meaningful once there's more than one item to order) -->
              <div v-else-if="!batchMode && displayItems.length > 1" :class="[
                'absolute flex items-center justify-center pointer-events-none',
                reorderable ? 'top-1 left-1 w-6 h-6 bg-black/70 rounded-full' : 'top-1 left-1 w-5 h-5 bg-black/70 rounded-full'
              ]">
                <span class="text-xs text-white font-medium">{{ index + 1 }}</span>
              </div>

              <!-- Frame-grab badge: this still came from a video, at this timestamp -->
              <div
                v-if="item._videoSource"
                class="absolute bottom-1 left-1 z-chrome bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1 pointer-events-none"
                :title="`Frame from ${item._videoSource.filename}`"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-white">
                  <path d="M3.25 4A2.25 2.25 0 0 0 1 6.25v7.5A2.25 2.25 0 0 0 3.25 16h7.5A2.25 2.25 0 0 0 13 13.75v-7.5A2.25 2.25 0 0 0 10.75 4h-7.5ZM19 4.75a.75.75 0 0 0-1.28-.53l-3 3a.75.75 0 0 0-.22.53v4.5c0 .199.079.39.22.53l3 3a.75.75 0 0 0 1.28-.53V4.75Z" />
                </svg>
                <span class="text-[10px] font-semibold text-white leading-none">{{ formatFrameTime(item._frameTime) }}</span>
              </div>

            </div>

            <!-- Frame picker: choose which frame of the source video to use as the still.
                 Shown for any video-grabbed item. -->
            <template v-if="accept === 'image' && !item.isSet && item._videoSource">
              <div class="w-full">
                <div
                  class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle cursor-pointer hover:bg-overlay-subtle transition-colors"
                  @click="togglePrepPanel(item.originalIndex, 'frame')"
                >
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M3.25 4A2.25 2.25 0 0 0 1 6.25v7.5A2.25 2.25 0 0 0 3.25 16h7.5A2.25 2.25 0 0 0 13 13.75v-7.5A2.25 2.25 0 0 0 10.75 4h-7.5ZM19 4.75a.75.75 0 0 0-1.28-.53l-3 3a.75.75 0 0 0-.22.53v4.5c0 .199.079.39.22.53l3 3a.75.75 0 0 0 1.28-.53V4.75Z" /></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Frame</span>
                  <!-- The single readout. Click toggles time ↔ frames (not expand/collapse). -->
                  <button
                    v-if="frameFps(item) > 0"
                    @click.stop="toggleFrameDisplay"
                    :title="frameDisplayMode === 'frames' ? 'Show time' : 'Show frame number'"
                    class="text-[10px] font-mono text-accent-hi font-medium tabular-nums hover:text-accent cursor-pointer"
                  >{{ headerFrameLabel(item) }}</button>
                  <span v-else class="text-[10px] font-mono text-accent-hi font-medium tabular-nums">{{ headerFrameLabel(item) }}</span>
                  <svg class="w-3 h-3 text-content-muted flex-shrink-0 transition-transform" :class="{ 'rotate-180': openPrepPanel[item.originalIndex] === 'frame' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
                </div>
                <!-- Frame picker expanded panel (the live preview is the <video> up top) -->
                <div v-if="openPrepPanel[item.originalIndex] === 'frame'" class="px-2.5 py-2 bg-overlay-faint rounded-md space-y-2">
                  <!-- Filmstrip timeline: full tile width, square cells, undistorted -->
                  <div
                    class="relative w-full rounded-md overflow-hidden border border-edge-subtle bg-black/30 cursor-pointer select-none touch-none"
                    style="min-height: 38px"
                    @pointerdown="onScrubPointerDown(item, $event)"
                    @pointermove="onScrubPointerMove(item, $event)"
                    @pointerup="onScrubPointerUp(item, $event)"
                    @pointercancel="onScrubPointerCancel(item)"
                    @dragstart.prevent
                  >
                    <img
                      v-if="frameStripUrl(item) && !stripFailed[item.originalIndex]"
                      :src="frameStripUrl(item)"
                      @load="stripReady[item.originalIndex] = true"
                      @error="stripFailed[item.originalIndex] = true"
                      class="block w-full h-auto pointer-events-none"
                      :class="{ 'opacity-0': !stripReady[item.originalIndex] }"
                      draggable="false"
                    />
                    <!-- plain-track fallback (no strip / OS file drop / still loading) -->
                    <div
                      v-if="!frameStripUrl(item) || stripFailed[item.originalIndex] || !stripReady[item.originalIndex]"
                      class="absolute inset-x-2 top-1/2 -translate-y-1/2 h-1 rounded-full bg-white/10 pointer-events-none"
                    >
                      <div class="absolute left-0 top-0 h-full rounded-full bg-accent" :style="{ width: framePercent(item) + '%' }"></div>
                    </div>
                    <!-- playhead -->
                    <div
                      class="absolute top-0 bottom-0 w-0.5 bg-accent-hi pointer-events-none"
                      style="box-shadow: 0 0 6px rgba(96,165,250,.8)"
                      :style="{ left: framePercent(item) + '%' }"
                    >
                      <div class="absolute -top-[3px] left-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-accent-hi"></div>
                    </div>
                  </div>
                  <!-- One unified control strip (full width): step ◀ · First · Middle · Last · step ▶ -->
                  <div class="flex w-full rounded-md border border-edge-subtle overflow-hidden">
                    <button @click="stepFrame(item, -1)" title="Previous frame"
                      :disabled="atFirstFrame(item)"
                      class="flex-shrink-0 w-9 flex items-center justify-center py-1 border-r border-edge-subtle text-content-muted hover:bg-overlay-medium hover:text-content transition-colors disabled:opacity-30 disabled:pointer-events-none">
                      <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.5 5 7.5 10l5 5"/></svg>
                    </button>
                    <button
                      v-for="pos in (['first', 'middle', 'last'] as const)"
                      :key="pos"
                      @click="setFramePosition(item, pos)"
                      :class="[
                        'flex-1 py-1 text-[11px] capitalize border-r border-edge-subtle transition-colors',
                        item._framePosition === pos ? 'bg-accent/15 text-accent-hi font-medium' : 'text-content-muted hover:bg-overlay-medium'
                      ]"
                    >{{ pos }}</button>
                    <button @click="stepFrame(item, 1)" title="Next frame"
                      :disabled="atLastFrame(item)"
                      class="flex-shrink-0 w-9 flex items-center justify-center py-1 text-content-muted hover:bg-overlay-medium hover:text-content transition-colors disabled:opacity-30 disabled:pointer-events-none">
                      <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 5l5 5-5 5"/></svg>
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- Per-image prep controls: Flip/Rotate / Scale / Extend Canvas / Preprocess / Paint.
                 Always offered — prep is baked client-side before submit, so it works
                 regardless of whether the tool declares x-allow-prep. -->
            <template v-if="accept === 'image' && !item.isSet">
              <!-- Flip / Rotate row -->
              <div class="w-full">
                <div
                  class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle cursor-pointer hover:bg-overlay-subtle transition-colors"
                  @click="togglePrepPanel(item.originalIndex, 'flip')"
                >
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16M4 12h16M7 9l-3 3 3 3M17 9l3 3-3 3"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Flip / Rotate</span>
                  <span :class="['text-[10px] font-mono', hasFlip(item) ? 'text-accent-hi font-medium' : 'text-content-muted']">
                    {{ getFlipStatusText(item) }}
                  </span>
                  <div class="w-3 h-3 flex-shrink-0">
                    <Spinner
                        v-if="delayedProcessingIndex === item.originalIndex && delayedProcessingReason === 'flip'"
                        size="sm"
                      />
                    <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPrepPanel[item.originalIndex] === 'flip' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
                  </div>
                </div>
                <!-- Flip / Rotate expanded panel -->
                <div v-if="openPrepPanel[item.originalIndex] === 'flip'" class="px-2.5 py-2 bg-overlay-faint rounded-md">
                  <div class="pl-5 flex items-center gap-1.5">
                    <button
                      @click="toggleFlip(item.originalIndex, 'horizontal')"
                      :class="[
                        'flex-1 flex items-center justify-center py-1.5 rounded border transition-colors',
                        item._flip?.horizontal ? 'border-accent/50 text-accent-hi bg-accent/10' : 'border-transparent text-content-muted bg-overlay-light hover:bg-overlay-medium'
                      ]"
                      title="Flip horizontal"
                    >
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16M4 12h16M7 9l-3 3 3 3M17 9l3 3-3 3"/></svg>
                    </button>
                    <button
                      @click="toggleFlip(item.originalIndex, 'vertical')"
                      :class="[
                        'flex-1 flex items-center justify-center py-1.5 rounded border transition-colors',
                        item._flip?.vertical ? 'border-accent/50 text-accent-hi bg-accent/10' : 'border-transparent text-content-muted bg-overlay-light hover:bg-overlay-medium'
                      ]"
                      title="Flip vertical"
                    >
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 12h16M12 4v16M9 7l3-3 3 3M9 17l3 3 3-3"/></svg>
                    </button>
                    <button
                      @click="rotate(item.originalIndex, 'left')"
                      class="flex-1 flex items-center justify-center py-1.5 rounded text-content-muted bg-overlay-light hover:bg-overlay-medium transition-colors"
                      title="Rotate left 90°"
                    >
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5"/></svg>
                    </button>
                    <button
                      @click="rotate(item.originalIndex, 'right')"
                      class="flex-1 flex items-center justify-center py-1.5 rounded text-content-muted bg-overlay-light hover:bg-overlay-medium transition-colors"
                      title="Rotate right 90°"
                    >
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-9-9 9.75 9.75 0 0 1 6.74 2.74L21 8M21 3v5h-5"/></svg>
                    </button>
                  </div>
                  <!-- Reset -->
                  <div v-if="hasFlip(item)" class="mt-1.5 pl-5 flex justify-end">
                    <button @click="resetFlip(item.originalIndex)"
                      class="text-[10px] text-content-muted hover:text-accent-hi">Reset</button>
                  </div>
                </div>
              </div>

              <!-- Crop row (opens the modal crop editor) -->
              <div class="w-full">
                <div class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle">
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 3.75V16.5a.75.75 0 0 0 .75.75h12.25M3.75 7.5H16.5a.75.75 0 0 1 .75.75v12.25"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Crop</span>
                  <span v-if="hasCrop(item)" class="text-[10px] font-mono tabular-nums text-accent-hi font-medium">
                    {{ getCropStatusText(item) }}
                  </span>
                  <Spinner
                    v-if="delayedProcessingIndex === item.originalIndex && delayedProcessingReason === 'crop'"
                    size="sm"
                  />
                  <button
                    v-if="hasCrop(item)"
                    @click="resetCrop(item.originalIndex)"
                    class="text-[10px] px-1.5 py-0.5 rounded text-content-muted bg-overlay-light hover:bg-red-500/10 hover:text-red-400 transition-colors"
                    title="Clear crop"
                  >
                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"/></svg>
                  </button>
                  <button
                    @click="openCropEditor(item.originalIndex)"
                    :class="[
                      'text-[10px] px-2 py-0.5 rounded border transition-colors',
                      hasCrop(item)
                        ? 'border-accent/50 text-accent-hi bg-accent/10 hover:bg-accent/15'
                        : 'border-transparent text-content-muted bg-overlay-light hover:bg-overlay-medium'
                    ]"
                  >Edit</button>
                </div>
              </div>

              <!-- Scale row -->
              <div class="w-full">
                <div
                  class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle cursor-pointer hover:bg-overlay-subtle transition-colors"
                  @click="togglePrepPanel(item.originalIndex, 'scale')"
                >
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 3.75H4.5m0 0v3m0-3l3.75 3.75M7.5 20.25H4.5m0 0v-3m0 3l3.75-3.75M16.5 3.75h3m0 0v3m0-3l-3.75 3.75M16.5 20.25h3m0 0v-3m0 3l-3.75-3.75"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Scale</span>
                  <span :class="['text-[10px] font-mono', hasScale(item) ? 'text-accent-hi font-medium' : 'text-content-muted']">
                    {{ getScaleStatusText(item) }}
                  </span>
                  <div class="w-3 h-3 flex-shrink-0">
                    <Spinner
                        v-if="delayedProcessingIndex === item.originalIndex && delayedProcessingReason === 'scale'"
                        size="sm"
                      />
                    <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPrepPanel[item.originalIndex] === 'scale' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
                  </div>
                </div>
                <!-- Scale expanded panel -->
                <div v-if="openPrepPanel[item.originalIndex] === 'scale'" class="px-2.5 py-2 bg-overlay-faint rounded-md space-y-2">
                  <!-- Pill mode switcher -->
                  <div class="flex bg-overlay-faint rounded-md p-0.5 gap-0.5 ml-5">
                    <button
                      v-for="mode in scaleModes" :key="mode.value"
                      @click="onScaleModeChange(item.originalIndex, mode.value)"
                      :class="[
                        'flex-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                        (item._scale?.mode || 'factor') === mode.value
                          ? 'bg-accent/15 text-accent-hi'
                          : 'text-content-muted hover:text-content-secondary'
                      ]"
                    >{{ mode.label }}</button>
                  </div>
                  <!-- Factor: slider only -->
                  <div v-if="!item._scale?.mode || item._scale.mode === 'factor'" class="pl-5 flex items-center gap-1.5">
                    <input type="range" min="10" max="400" :step="5"
                      :value="Math.round((item._scale?.factor || 1) * 100)"
                      @input="onScaleSliderInput(item.originalIndex, parseInt(($event.target as HTMLInputElement).value) / 100)"
                      @mouseup="onScaleSliderCommit(item.originalIndex)"
                      @touchend="onScaleSliderCommit(item.originalIndex)"
                      class="flex-1 h-1 accent-accent cursor-pointer" />
                    <span class="text-[10px] font-mono text-accent-hi tabular-nums w-10 text-right">{{ (item._scale?.factor || 1).toFixed(2) }}x</span>
                  </div>
                  <!-- Megapixels: slider -->
                  <div v-else-if="item._scale?.mode === 'megapixels'" class="pl-5 flex items-center gap-1.5">
                    <input type="range" min="1" max="80" :step="1"
                      :value="Math.round((item._scale?.megapixels || origMegapixels(item)) * 10)"
                      @input="onMegapixelsSliderInput(item.originalIndex, parseInt(($event.target as HTMLInputElement).value) / 10)"
                      @mouseup="onScaleSliderCommit(item.originalIndex)"
                      @touchend="onScaleSliderCommit(item.originalIndex)"
                      class="flex-1 h-1 accent-accent cursor-pointer" />
                    <span class="text-[10px] font-mono text-accent-hi tabular-nums w-10 text-right">{{ (item._scale?.megapixels || origMegapixels(item)).toFixed(1) }} MP</span>
                  </div>
                  <!-- Manual: W × H with locked aspect -->
                  <div v-else-if="item._scale?.mode === 'manual'" class="pl-5 flex items-center gap-1.5">
                    <input v-no-autocorrect type="number" min="1" step="1"
                      :value="item._scale?.width ?? croppedDims(item).w"
                      @change="onManualDimensionInput(item.originalIndex, 'width', parseInt(($event.target as HTMLInputElement).value))"
                      class="w-16 px-1.5 py-0.5 text-[10px] bg-base border border-edge-subtle rounded text-content tabular-nums focus:outline-none focus:border-edge" />
                    <svg class="w-3 h-3 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m12 0H4.5a1.5 1.5 0 0 0-1.5 1.5v7.5a1.5 1.5 0 0 0 1.5 1.5h15a1.5 1.5 0 0 0 1.5-1.5v-7.5a1.5 1.5 0 0 0-1.5-1.5z"/></svg>
                    <input v-no-autocorrect type="number" min="1" step="1"
                      :value="item._scale?.height ?? croppedDims(item).h"
                      @change="onManualDimensionInput(item.originalIndex, 'height', parseInt(($event.target as HTMLInputElement).value))"
                      class="w-16 px-1.5 py-0.5 text-[10px] bg-base border border-edge-subtle rounded text-content tabular-nums focus:outline-none focus:border-edge" />
                  </div>
                  <!-- Reset -->
                  <div v-if="hasScale(item)" class="pl-5 flex justify-end">
                    <button @click="resetScale(item.originalIndex)"
                      class="text-[10px] text-content-muted hover:text-accent-hi">Reset</button>
                  </div>
                </div>
              </div>

              <!-- Extend Canvas row -->
              <div class="w-full">
                <div
                  class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle cursor-pointer hover:bg-overlay-subtle transition-colors"
                  @click="togglePrepPanel(item.originalIndex, 'extend')"
                >
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Extend Canvas</span>
                  <span :class="['text-[10px] font-mono', hasExtendPadding(item) ? 'text-accent-hi font-medium' : 'text-content-muted']">
                    {{ getExtendStatusText(item) }}
                  </span>
                  <svg class="w-3 h-3 text-content-muted flex-shrink-0 transition-transform" :class="{ 'rotate-180': openPrepPanel[item.originalIndex] === 'extend' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
                </div>
                <!-- Extend expanded panel -->
                <div v-if="openPrepPanel[item.originalIndex] === 'extend'" class="px-2.5 py-2 bg-overlay-faint rounded-md">
                  <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 pl-5">
                    <div>
                      <div class="flex justify-between mb-0.5">
                        <span class="text-[10px] text-content-muted">Top</span>
                        <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ getExtendValue(item, 'top') }}%</span>
                      </div>
                      <input type="range" min="0" max="100" :step="1"
                        :value="getExtendValue(item, 'top')"
                        @input="onExtendSliderInput(item.originalIndex, 'top', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onExtendSliderCommit(item.originalIndex)"
                        @touchend="onExtendSliderCommit(item.originalIndex)"
                        class="w-full h-1 accent-accent cursor-pointer" />
                    </div>
                    <div>
                      <div class="flex justify-between mb-0.5">
                        <span class="text-[10px] text-content-muted">Bottom</span>
                        <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ getExtendValue(item, 'bottom') }}%</span>
                      </div>
                      <input type="range" min="0" max="100" :step="1"
                        :value="getExtendValue(item, 'bottom')"
                        @input="onExtendSliderInput(item.originalIndex, 'bottom', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onExtendSliderCommit(item.originalIndex)"
                        @touchend="onExtendSliderCommit(item.originalIndex)"
                        class="w-full h-1 accent-accent cursor-pointer" />
                    </div>
                    <div>
                      <div class="flex justify-between mb-0.5">
                        <span class="text-[10px] text-content-muted">Left</span>
                        <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ getExtendValue(item, 'left') }}%</span>
                      </div>
                      <input type="range" min="0" max="100" :step="1"
                        :value="getExtendValue(item, 'left')"
                        @input="onExtendSliderInput(item.originalIndex, 'left', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onExtendSliderCommit(item.originalIndex)"
                        @touchend="onExtendSliderCommit(item.originalIndex)"
                        class="w-full h-1 accent-accent cursor-pointer" />
                    </div>
                    <div>
                      <div class="flex justify-between mb-0.5">
                        <span class="text-[10px] text-content-muted">Right</span>
                        <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ getExtendValue(item, 'right') }}%</span>
                      </div>
                      <input type="range" min="0" max="100" :step="1"
                        :value="getExtendValue(item, 'right')"
                        @input="onExtendSliderInput(item.originalIndex, 'right', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onExtendSliderCommit(item.originalIndex)"
                        @touchend="onExtendSliderCommit(item.originalIndex)"
                        class="w-full h-1 accent-accent cursor-pointer" />
                    </div>
                  </div>
                  <!-- Background color -->
                  <div class="flex items-center gap-1.5 mt-2 pl-5">
                    <span class="text-[10px] text-content-muted">Fill</span>
                    <input type="color"
                      :value="item._extendBgColor || '#000000'"
                      @input="onExtendBgColorInput(item.originalIndex, ($event.target as HTMLInputElement).value)"
                      @change="onExtendBgColorCommit(item.originalIndex, ($event.target as HTMLInputElement).value)"
                      class="w-5 h-4 border border-edge-subtle rounded cursor-pointer" />
                    <span class="text-[10px] text-content-muted tabular-nums">{{ item._extendBgColor || '#000000' }}</span>
                  </div>
                  <!-- Reset -->
                  <div v-if="hasExtendPadding(item)" class="mt-1 pl-5 flex justify-end">
                    <button @click="resetExtendPadding(item.originalIndex)"
                      class="text-[10px] text-content-muted hover:text-accent-hi"
                      title="Reset to no extension">Reset</button>
                  </div>
                </div>
              </div>

              <!-- Preprocess row -->
              <div v-if="hasControlnet" class="w-full">
                <div
                  class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle cursor-pointer hover:bg-overlay-subtle transition-colors"
                  @click="togglePrepPanel(item.originalIndex, 'preprocess')"
                >
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6 13.5V3.75m0 9.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 3.75V16.5m12-3V3.75m0 9.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 3.75V16.5m-6-9V3.75m0 3.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 9.75V10.5"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Preprocess</span>
                  <span :class="['text-[10px] font-mono', item._preprocessor ? 'text-accent-hi font-medium' : 'text-content-muted']">
                    {{ item._preprocessor ? (controlnetLabels[item._preprocessor] || item._preprocessor) : 'Original' }}
                  </span>
                  <div class="w-3 h-3 flex-shrink-0">
                    <Spinner
                        v-if="delayedProcessingIndex === item.originalIndex && delayedProcessingReason === 'preprocess'"
                        size="sm"
                      />
                    <svg v-else class="w-3 h-3 text-content-muted transition-transform" :class="{ 'rotate-180': openPrepPanel[item.originalIndex] === 'preprocess' }" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
                  </div>
                </div>
                <!-- Preprocess expanded panel -->
                <div v-if="openPrepPanel[item.originalIndex] === 'preprocess'" class="px-2.5 py-2 bg-overlay-faint rounded-md">
                  <div class="flex items-center gap-1.5 pl-5">
                    <select
                      :value="item._preprocessor || ''"
                      @change="applyPreprocessor(item.originalIndex, ($event.target as HTMLSelectElement).value || null)"
                      :disabled="processingIndex === item.originalIndex"
                      :class="[
                        'flex-1 text-[10px] rounded border bg-overlay-light pl-1 pr-1 py-0.5 cursor-pointer',
                        item._preprocessor
                          ? 'border-accent/50 text-accent-hi'
                          : 'border-transparent text-content-muted'
                      ]"
                    >
                      <option value="">Original</option>
                      <option v-for="option in controlnetOptions" :key="option" :value="option">
                        {{ controlnetLabels[option] || option }}
                      </option>
                    </select>
                  </div>
                  <!-- Canny threshold sliders -->
                  <div v-if="item._preprocessor === 'canny'" class="flex flex-col gap-1 w-full mt-1.5 pl-5">
                    <div class="flex items-center gap-1.5 w-full min-w-0">
                      <span class="text-[10px] text-content-muted w-6">Low</span>
                      <input type="range" min="1" max="255"
                        :value="item._preprocessorParams?.low ?? 128"
                        @input="onPreprocessorSliderInput(item.originalIndex, 'low', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onPreprocessorSliderCommit(item.originalIndex)"
                        @touchend="onPreprocessorSliderCommit(item.originalIndex)"
                        class="flex-1 min-w-0 h-1 accent-accent cursor-pointer" />
                      <span class="text-[10px] text-content-muted w-5 text-right tabular-nums">{{ item._preprocessorParams?.low ?? 'A' }}</span>
                    </div>
                    <div class="flex items-center gap-1.5 w-full min-w-0">
                      <span class="text-[10px] text-content-muted w-6">High</span>
                      <input type="range" min="1" max="255"
                        :value="item._preprocessorParams?.high ?? 128"
                        @input="onPreprocessorSliderInput(item.originalIndex, 'high', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onPreprocessorSliderCommit(item.originalIndex)"
                        @touchend="onPreprocessorSliderCommit(item.originalIndex)"
                        class="flex-1 min-w-0 h-1 accent-accent cursor-pointer" />
                      <span class="text-[10px] text-content-muted w-5 text-right tabular-nums">{{ item._preprocessorParams?.high ?? 'A' }}</span>
                    </div>
                    <button @click="onPreprocessorReset(item.originalIndex)"
                      class="text-[10px] text-content-muted hover:text-accent-hi self-end"
                      title="Reset to defaults">Reset</button>
                  </div>
                  <!-- Lineart sliders -->
                  <div v-if="item._preprocessor === 'lineart'" class="flex flex-col gap-1 w-full mt-1.5 pl-5">
                    <div class="flex items-center gap-1.5 w-full min-w-0">
                      <span class="text-[10px] text-content-muted w-8">Sigma</span>
                      <input type="range" min="1" max="200"
                        :value="item._preprocessorParams?.sigma ? Math.round(item._preprocessorParams.sigma * 10) : 60"
                        @input="onPreprocessorSliderInput(item.originalIndex, 'sigma', parseInt(($event.target as HTMLInputElement).value) / 10)"
                        @mouseup="onPreprocessorSliderCommit(item.originalIndex)"
                        @touchend="onPreprocessorSliderCommit(item.originalIndex)"
                        class="flex-1 min-w-0 h-1 accent-accent cursor-pointer" />
                      <span class="text-[10px] text-content-muted w-6 text-right tabular-nums">{{ (item._preprocessorParams?.sigma ?? 6.0).toFixed(1) }}</span>
                    </div>
                    <div class="flex items-center gap-1.5 w-full min-w-0">
                      <span class="text-[10px] text-content-muted w-8">Thresh</span>
                      <input type="range" min="1" max="32"
                        :value="item._preprocessorParams?.threshold ?? 8"
                        @input="onPreprocessorSliderInput(item.originalIndex, 'threshold', parseInt(($event.target as HTMLInputElement).value))"
                        @mouseup="onPreprocessorSliderCommit(item.originalIndex)"
                        @touchend="onPreprocessorSliderCommit(item.originalIndex)"
                        class="flex-1 min-w-0 h-1 accent-accent cursor-pointer" />
                      <span class="text-[10px] text-content-muted w-5 text-right tabular-nums">{{ item._preprocessorParams?.threshold ?? 8 }}</span>
                    </div>
                    <button @click="onPreprocessorReset(item.originalIndex)"
                      class="text-[10px] text-content-muted hover:text-accent-hi self-end"
                      title="Reset to defaults">Reset</button>
                  </div>
                  <!-- Lineart Realistic toggle -->
                  <div v-if="item._preprocessor === 'lineart_realistic'" class="flex flex-col gap-1 w-full mt-1.5 pl-5">
                    <label class="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox"
                        :checked="!!(item._preprocessorParams?.coarse)"
                        @change="onRealisticCoarseToggle(item.originalIndex, ($event.target as HTMLInputElement).checked)"
                        class="w-3 h-3 accent-accent" />
                      <span class="text-[10px] text-content-muted">Coarse</span>
                    </label>
                  </div>
                </div>
              </div>

              <!-- Paint row (hidden in batch mode — per-item painting can't apply uniformly) -->
              <div v-if="!batchMode" class="w-full">
                <div class="flex items-center gap-2 px-2.5 py-1.5 border-t border-edge-subtle">
                  <svg class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg>
                  <span class="text-[11px] text-content-secondary flex-1">Paint</span>
                  <button
                    v-if="item._paintLayerDataUrl"
                    @click="revertPaint(item.originalIndex)"
                    class="text-[10px] px-1.5 py-0.5 rounded text-content-muted bg-overlay-light hover:bg-red-500/10 hover:text-red-400 transition-colors"
                    title="Clear paint"
                  >
                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"/></svg>
                  </button>
                  <button
                    @click="openPaintEditor(item.originalIndex)"
                    :class="[
                      'text-[10px] px-2 py-0.5 rounded border transition-colors',
                      item._paintLayerDataUrl
                        ? 'border-accent/50 text-accent-hi bg-accent/10 hover:bg-accent/15'
                        : 'border-transparent text-content-muted bg-overlay-light hover:bg-overlay-medium'
                    ]"
                  >Edit</button>
                </div>
              </div>

              <!-- Output size footer — shows final pipeline dimensions, Use sets canvas -->
              <div class="w-full border-t border-edge-subtle">
                <div class="flex items-center gap-2 px-2.5 py-1.5">
                  <span class="text-[10px] text-content-muted flex-1 min-w-0 whitespace-nowrap tabular-nums">{{ getExtendedDimensions(item).width }} × {{ getExtendedDimensions(item).height }}</span>
                  <button
                    @click="setCanvasToItemAspect(item)"
                    class="text-[10px] px-1.5 py-0.5 rounded text-content-muted bg-overlay-light hover:bg-overlay-medium transition-colors flex items-center gap-1 flex-shrink-0"
                    title="Use this image's aspect ratio while keeping the current megapixel size"
                  >
                    <ArrowDownOnSquareIcon class="w-3 h-3" />
                    <span>Aspect</span>
                  </button>
                  <button
                    @click="setCanvasToItemSize(item)"
                    class="text-[10px] px-1.5 py-0.5 rounded text-content-muted bg-overlay-light hover:bg-overlay-medium transition-colors flex items-center gap-1 flex-shrink-0"
                    title="Set canvas size to this image's output dimensions"
                  >
                    <ArrowDownOnSquareIcon class="w-3 h-3" />
                    <span>Size</span>
                  </button>
                </div>
              </div>
            </template>

            <div v-if="batchMode && index === 0 && accept === 'image' && !item.isSet" class="w-full border-t border-edge-subtle">
              <button
                type="button"
                class="w-full flex items-center justify-center gap-2 px-2.5 py-1.5 text-[11px] text-red-400 hover:bg-red-500/[0.06] transition-colors"
                @click.stop="emit('explode')"
              >
                <Square3Stack3DIcon class="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                <span>Explode batch</span>
              </button>
            </div>
          </div>

          <!-- Connection arrow between items (video sequence only) -->
          <div
            v-if="reorderable && accept === 'video' && index < displayItems.length - 1"
            class="text-content-muted flex-shrink-0"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path fill-rule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clip-rule="evenodd" />
            </svg>
          </div>
        </div>
      </template>

      <!-- Add: dashed tile only when EMPTY; ghost row once items exist.
           Both stay live drop targets (accent chrome on drag-over). -->
      <div
        v-if="!batchMode && items.length < maxItems && items.length === 0"
        ref="addTileRef"
        @click="onAddTileClick"
        @dragover.prevent.stop="onDragOver"
        @dragleave.stop="onDragLeave"
        @drop.prevent.stop="onDrop($event)"
        :class="[
          'border border-dashed rounded-lg flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer h-24 w-full',
          reorderable ? '' : 'col-span-full',
          isDragging || pickerPopoverOpen ? 'ring-1 ring-accent/50 bg-accent/10 border-transparent' : 'border-edge text-content-muted hover:border-accent'
        ]"
      >
        <span class="text-xs text-content-muted flex items-center gap-1.5">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          {{ isDragging ? 'Drop here' : (useSlotLabels ? slotName(items.length) : 'Add — drop, paste, or browse') }}
        </span>
      </div>
    </div>

    <!-- Add row (compact, once items exist) -->
    <div
      v-if="!batchMode && items.length < maxItems && items.length > 0"
      ref="addTileRef"
      @click="onAddTileClick"
      @dragover.prevent.stop="onDragOver"
      @dragleave.stop="onDragLeave"
      @drop.prevent.stop="onDrop($event)"
      :class="[
        'mt-1.5 w-full flex items-center gap-1.5 rounded-md px-1 py-1.5 text-xs cursor-pointer transition-colors',
        isDragging || pickerPopoverOpen ? 'border border-dashed border-accent/50 bg-accent/10 text-accent-hi justify-center' : 'text-content-muted hover:text-content-secondary hover:bg-overlay-subtle'
      ]"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
      </svg>
      {{ isDragging ? 'Drop here' : (useSlotLabels ? `Add ${slotName(items.length)}` : 'Add') }}
      <button
        v-if="useSlotLabels && items.length >= 1 && !isDragging"
        @click.stop="duplicateFirstToFill"
        class="ml-auto text-[10px] px-2 py-0.5 rounded text-content-muted bg-overlay-subtle hover:bg-accent/10 hover:text-accent-hi transition-colors"
        :title="`Use the same image as ${slotName(0)} (for loops)`"
      >
        Same as {{ slotBadge(0) }}
      </button>
    </div>

    <!-- Disabled reason takes priority over the min-items nag — no point telling
         the user to add an item this picker is currently blocking them from adding. -->
    <div v-if="disabled && disabledReason" class="text-xs text-amber-500/80">
      {{ disabledReason }}
    </div>
    <!-- Min items validation message -->
    <div v-else-if="items.length < minItems" class="text-xs text-yellow-500/70">
      Add at least {{ minItems }} {{ accept === 'image' ? 'images' : accept === 'audio' ? 'audio files' : 'videos' }}
    </div>

    <!-- Loading indicator: absolute overlay so it never reflows the layout -->
    <div v-if="isUploading" class="absolute top-0 right-0 z-10 flex items-center gap-1.5 bg-black/60 backdrop-blur-md rounded-md px-2 py-1 pointer-events-none">
      <Spinner size="sm" />
      <span class="text-[10px] text-content-muted">Working…</span>
    </div>

    <!-- Hidden file input -->
    <input v-no-autocorrect
      ref="fileInput"
      type="file"
      :accept="fileAcceptString"
      :multiple="maxItems > 1"
      class="hidden"
      @change="handleFileSelect"
    >

    <!-- In-app media picker: recents-first popover anchored to the add tile;
         "Browse Files…" inside it falls back to the OS dialog. -->
    <MediaPickerPopover
      v-if="pickerPopoverOpen"
      :accept="accept"
      :anchor-el="addTileRef"
      :exclude-ids="pickerExcludeIds"
      @pick="onPopoverPick"
      @browse="onPopoverBrowse"
      @close="pickerPopoverOpen = false"
    />

    <!-- Full-screen preview modal for preprocessed images -->
    <Modal
      :show="!!previewModalUrl"
      size="custom"
      custom-class="max-w-[90vw] w-auto"
      @close="previewModalUrl = ''"
    >
      <div class="relative max-h-[90vh]">
        <img
          :src="previewModalUrl"
          class="max-w-full max-h-[90vh] object-contain"
          @click.stop
        />
        <button
          @click="previewModalUrl = ''"
          class="absolute top-2 right-2 bg-black/60 text-white rounded-full p-2 hover:bg-black/80 border-none cursor-pointer"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>
    </Modal>

    <!-- Crop editor modal -->
    <CropEditorModal
      v-model="cropEditorOpen"
      :image-url="cropEditorImage?.url ?? null"
      :image-width="cropEditorImage?.width"
      :image-height="cropEditorImage?.height"
      :flip="cropEditorImage?.flip ?? null"
      :crop="cropEditorImage?.crop ?? null"
      @apply="onCropApply"
    />

    <!-- Paint editor modal -->
    <PaintEditorModal
      v-if="paintEditorIndex !== null"
      :model-value="paintEditorIndex !== null"
      :image="paintEditorImage"
      :paint-layer-data-url="paintEditorIndex !== null ? (items[paintEditorIndex]?._paintLayerDataUrl ?? null) : null"
      @update:model-value="closePaintEditor"
      @update:paint-layer-data-url="onPaintLayerUpdate($event)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onBeforeUnmount, onMounted } from 'vue'
import axios from 'axios'
import { ArrowDownOnSquareIcon, Square3Stack3DIcon } from '@heroicons/vue/24/outline'
import { useMediaApi } from '../../composables/useMediaApi'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { getApiBase } from '../../apiConfig'
import { makeProfileKey } from '../../utils/storageKeys'
import { useVideoFrameExtraction, type FramePosition } from '../../composables/useVideoFrameExtraction'
import { createDragPreview, handleDragEnd as clearDragPreview } from '../../composables/useDragPreview'
import { addToast } from '../../composables/useToasts'
import AppImage from '../media/AppImage.vue'
import MediaImage from '../media/MediaImage.vue'
import CompactAudioPlayer from '../viewers/CompactAudioPlayer.vue'
import PaintEditorModal from './PaintEditorModal.vue'
import CropEditorModal from './CropEditorModal.vue'
import MediaPickerPopover from './MediaPickerPopover.vue'
import { recordMediaInputUse, removeRecentMediaInput, type RecentInputKind } from '../../composables/useRecentMediaInputs'
import { removeRecentMediaPick } from '../../composables/useRecentMediaPicks'
import { getMediaType } from '../../utils/mediaTypes'
import Spinner from '../ui/Spinner.vue'
import Modal from '../ui/Modal.vue'

const { getMediaItem, getMediaFileUrl, getThumbnailUrl } = useMediaApi()
const { extractFrame } = useVideoFrameExtraction()

export interface MediaItem {
  path: string
  filename: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
  thumbnailUrl?: string
  originalIndex?: number
  // Set-specific fields
  isSet?: boolean
  setItemCount?: number
  setId?: number  // Media ID of the set (for batch processing)
  // ControlNet preprocessing fields
  _originalPath?: string        // Stashed original path before preprocessing
  _originalHash?: string        // Stashed original hash before preprocessing
  _preprocessor?: string | null // Active preprocessor for this image
  _preprocessorParams?: Record<string, number> // e.g. { low: 50, high: 150 } for canny thresholds
  // Scale fields
  _scale?: {
    mode: 'factor' | 'megapixels' | 'manual'
    factor?: number
    megapixels?: number
    width?: number
    height?: number
  } | null
  _originalWidth?: number
  _originalHeight?: number
  // Paint layer fields
  _paintLayerDataUrl?: string | null  // Transparent PNG data URL of paint strokes
  _paintLayerPath?: string | null     // Server-side uploaded paint layer path
  // Extend canvas fields
  _extendPadding?: {
    top: number; bottom: number;
    left: number; right: number;
  } | null
  _extendBgColor?: string | null  // hex color for extend fill
  // Flip / rotate fields (applied first in the pipeline, before scale)
  _flip?: {
    horizontal?: boolean
    vertical?: boolean
    rotation?: number  // 0 | 90 | 180 | 270, clockwise degrees
  } | null
  // Crop field (applied after flip/rotate, before scale): normalized
  // left/top-anchored rect, fractions 0-1 of the post-flip image, plus an
  // optional free rotation of the rect (straighten) in clockwise degrees.
  _crop?: {
    x: number
    y: number
    width: number
    height: number
    rotation?: number
  } | null
  // Base image for paint editor (after scale+preprocess+extend, before paint)
  _basePath?: string | null
  _baseWidth?: number | null
  _baseHeight?: number | null
  // Frame-grab fields: this still was captured from a video. The item itself is a
  // normal image (path/width/height point at the captured frame); these describe
  // its origin so the scrubber can re-open the source and re-capture.
  _videoSource?: {
    mediaId?: number      // library video id, if grabbed from the library
    hash?: string         // library video file hash
    filename: string      // source video filename (for display)
    duration?: number     // source duration in seconds
    fps?: number          // source frame rate (for frame-accurate stepping)
    sourcePath?: string   // path to the source video on the server (re-extract / playback)
    clientKey?: string    // session key into the dropped-File cache (OS file drops only)
  } | null
  _frameTime?: number          // timestamp (seconds) the frame was captured at
  _framePosition?: 'first' | 'last' | 'middle' | 'custom'
}

interface Props {
  modelValue: MediaItem[]
  accept: 'image' | 'video' | 'audio'
  minItems?: number
  maxItems?: number
  reorderable?: boolean
  label?: string
  description?: string
  allowSets?: boolean  // Allow sets to be dropped (for batch processing)
  controlnetOptions?: string[]  // e.g. ["canny", "depth", "lineart", "pose"]
  // Named slots: when provided, each tile is a role (e.g. ['Start Frame', 'End
  // Frame']) rather than an anonymous ordered item. Drives the per-tile badge,
  // the empty add-tile label, and the "use same for both" loop shortcut. Items
  // remain a plain ordered array — slot N is items[N].
  slotLabels?: string[]
  // Batch state: the slot holds N items and runs the tool once per item. The slot
  // collapses to one representative "stack" tile (with a count); its prep is the
  // uniform prep applied to every item. Non-applicable controls (paint, reorder,
  // add) are hidden.
  batchMode?: boolean
  // Default frame to grab when a VIDEO is dropped into an image slot, indexed by
  // slot. For the i2v frame picker this is ['last', 'first'] (drop a video into the
  // Start slot → its last frame to extend forward; into the End slot → its first
  // frame to connect into). Absent / unset slots default to 'first'.
  frameGrabDefaults?: Array<'first' | 'last'>
  // Stable per-tool key used to persist the frame readout mode (time vs frames).
  frameModeKey?: string
  // Block all interaction (add/drag/drop/reorder/remove) without touching
  // modelValue — driven by x-constraints (e.g. Kling: frames vs native audio
  // are mutually exclusive, so whichever the user set first locks the other).
  disabled?: boolean
  disabledReason?: string
}

const props = withDefaults(defineProps<Props>(), {
  minItems: 1,
  maxItems: 1,
  reorderable: false,
  label: '',
  description: '',
  allowSets: true,
  controlnetOptions: () => [],
  slotLabels: () => [],
  disabled: false,
  batchMode: false,
  frameGrabDefaults: () => [],
  frameModeKey: ''
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: MediaItem[]): void
  (e: 'view-media', mediaId: number): void
  (e: 'view-media-batch', mediaIds: number[]): void
  (e: 'suggest-resolution', dims: { width: number; height: number } | null, options?: { manual?: boolean }): void
  (e: 'suggest-aspect', dims: { width: number; height: number } | null, options?: { manual?: boolean }): void
  (e: 'explode'): void
}>()

const API_BASE = '/api'

// File accept strings by media type
const FILE_ACCEPT = {
  image: 'image/jpeg,image/png,image/webp',
  video: 'video/mp4,video/webm,video/quicktime,video/x-msvideo,video/x-matroska',
  audio: 'audio/mpeg,audio/wav,audio/flac,audio/mp4,audio/aac,audio/ogg'
}

// Upload endpoints by media type
const UPLOAD_ENDPOINTS = {
  image: '/api/generate/upload-reference',
  video: '/api/generate/upload-reference-video',
  audio: '/api/generate/upload-reference-audio'
}

// Reference file endpoints by media type (uses getApiBase() for Tauri compatibility)
function getReferenceFileEndpoint(type: 'image' | 'video' | 'audio') {
  const base = getApiBase()
  if (type === 'audio') return `${base}/generate/reference-audio-file`
  return type === 'video' ? `${base}/generate/reference-video-file` : `${base}/generate/reference-file`
}

// Canonical video formats (matches backend utils/query_builder.VIDEO_FORMATS, plus m4v).
const VIDEO_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']

// An image slot accepts videos too: dropping a video grabs a frame (decision: anything
// that accepts an image accepts a video). Whole-video slots (accept==='video') are
// unchanged. Frame grab is therefore enabled exactly when this is an image slot.
const isImageSlot = computed(() => props.accept === 'image')

function isVideoExtension(ext?: string | null): boolean {
  return !!ext && VIDEO_EXTENSIONS.includes(ext.toLowerCase())
}

function isVideoFile(file: File): boolean {
  if (file.type.startsWith('video/')) return true
  const ext = file.name.split('.').pop()
  return isVideoExtension(ext)
}

// Default frame for a video dropped into a given slot index (role-aware for i2v).
function frameDefaultForSlot(slotIndex: number): FramePosition {
  return props.frameGrabDefaults?.[slotIndex] ?? 'first'
}

function formatFrameTime(seconds?: number): string {
  const s = Math.max(0, Math.floor(seconds ?? 0))
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}:${rem.toString().padStart(2, '0')}`
}

const fileInput = ref<HTMLInputElement | null>(null)
const isUploading = ref(false)
const isDragging = ref(false)
const videoErrors = ref<Record<string, boolean>>({})

// Per-image controlnet preprocessing state
type ProcessingReason = 'flip' | 'crop' | 'scale' | 'preprocess' | 'extend' | 'paint'
const processingIndex = ref<number | null>(null)
const processingReason = ref<ProcessingReason | null>(null)
const delayedProcessingIndex = ref<number | null>(null)
const delayedProcessingReason = ref<ProcessingReason | null>(null)
let processingSpinnerTimer: number | null = null

watch(processingIndex, (newIndex) => {
  if (processingSpinnerTimer !== null) {
    window.clearTimeout(processingSpinnerTimer)
    processingSpinnerTimer = null
  }

  if (newIndex === null) {
    delayedProcessingIndex.value = null
    delayedProcessingReason.value = null
    return
  }

  // Avoid flicker for fast preprocess calls; only show spinner if still processing after 500ms.
  processingSpinnerTimer = window.setTimeout(() => {
    if (processingIndex.value === newIndex) {
      delayedProcessingIndex.value = newIndex
      delayedProcessingReason.value = processingReason.value
    }
    processingSpinnerTimer = null
  }, 500)
})

onBeforeUnmount(() => {
  if (processingSpinnerTimer !== null) {
    window.clearTimeout(processingSpinnerTimer)
    processingSpinnerTimer = null
  }
})

const controlnetLabels: Record<string, string> = {
  canny: 'Canny',
  depth: 'Depth',
  lineart: 'Lineart (Standard)',
  lineart_realistic: 'Lineart (Realistic)',
  lineart_anime: 'Lineart (Anime)',
  pose: 'Pose',
  pose_hands: 'Pose + Hands',
}

const hasControlnet = computed(() => props.controlnetOptions.length > 0)

// Named-slot mode (e.g. Start Frame / End Frame). Only meaningful when there's
// more than one role to distinguish — a lone slot needs no badge.
const useSlotLabels = computed(() => props.slotLabels.length > 1)
function slotName(index: number): string {
  return props.slotLabels[index] || `Slot ${index + 1}`
}
// Short badge text for a slot, e.g. "Start Frame" → "Start".
function slotBadge(index: number): string {
  const name = props.slotLabels[index]
  if (!name) return String(index + 1)
  return name.replace(/\s*frame\s*$/i, '').trim() || name
}

// Loop shortcut: copy slot 0 into the next empty slot so both frames share one
// image (seamless loops want identical start/end). The copy carries the same
// path + prep metadata; editing one slot's prep afterwards re-derives from the
// shared original, so the slots stay independent once duplicated.
function duplicateFirstToFill() {
  if (items.value.length < 1 || items.value.length >= props.maxItems) return
  const copy: MediaItem = { ...items.value[0] }
  const newItems = [...items.value, copy]
  items.value = newItems
  emit('update:modelValue', newItems)
}

// Drag state for reordering
const dragIndex = ref<number | null>(null)
const dropIndex = ref<number | null>(null)

// Local items state
const items = ref<MediaItem[]>([...props.modelValue])

// Watch for external changes
watch(() => props.modelValue, (newValue) => {
  items.value = [...newValue]

  // Auto-apply preprocessing for items that arrive with prep metadata set
  // but haven't been preprocessed yet (e.g., from "Send to Tool" / Remix).
  // Skip items currently being processed to avoid a re-trigger loop:
  // applyFullPreprocessing emits before _originalPath is set by the API response,
  // which would cause this watcher to re-call indefinitely.
  newValue.forEach((item: any, i: number) => {
    if (item._originalPath || processingIndex.value === i) return
    const needsFlip = hasFlip(item)
    const needsPreprocessor = hasControlnet.value && !!item._preprocessor
    const needsPaint = !!item._paintLayerPath
    const needsExtend = !!(item._extendPadding && (
      item._extendPadding.top > 0 || item._extendPadding.bottom > 0 ||
      item._extendPadding.left > 0 || item._extendPadding.right > 0
    ))
    const needsScale = hasScale(item)
    if (needsFlip || needsPreprocessor || needsPaint || needsExtend || needsScale) {
      applyFullPreprocessing(i)
    }
  })

  backfillDimensions()
}, { deep: true })

// Backfill width/height for items that have a mediaId but no dimensions. Frames
// restored from the legacy picker (and some config-hop / send-to-tool paths)
// arrive without dims, which leaves the output-size footer at 1×1 and starves
// the resolution auto-match. Fetch the real dims from the library and patch them
// in. The re-entrancy guard + "missing dims" filter keep the follow-up emit from
// looping.
let backfillingDimensions = false
async function backfillDimensions() {
  if (backfillingDimensions) return
  const targets = items.value
    .map((it, i) => ({ it, i }))
    .filter(({ it }) => !it.isSet && it.mediaId && (!it.width || !it.height))
  if (targets.length === 0) return
  backfillingDimensions = true
  try {
    const newItems = [...items.value]
    let changed = false
    for (const { it, i } of targets) {
      try {
        const media = await getMediaItem(it.mediaId!)
        if (media?.width && media?.height) {
          newItems[i] = { ...newItems[i], width: media.width, height: media.height }
          changed = true
        }
      } catch (e) {
        console.warn('[MediaPicker] dimension backfill failed:', e)
      }
    }
    if (changed) {
      items.value = newItems
      emit('update:modelValue', newItems)
    }
  } finally {
    backfillingDimensions = false
  }
}

// Items already present at first render (e.g. a restored frame) won't trip the
// modelValue watch, so kick a backfill on mount too.
onMounted(() => { backfillDimensions() })

// Computed
const fileAcceptString = computed(() =>
  // Image slots also accept videos (we grab a frame); whole-video slots don't change.
  isImageSlot.value ? `${FILE_ACCEPT.image},${FILE_ACCEPT.video}` : FILE_ACCEPT[props.accept]
)

const displayLabel = computed(() => {
  if (props.label) return props.label
  if (props.accept === 'audio') return 'Reference Audio'
  return props.accept === 'image' ? 'Reference Images' : 'Input Videos'
})

// Check if any input is a set (batch mode)
const hasSetInput = computed(() => items.value.some(item => item.isSet))

// Total items in sets (for batch display)
const setItemCount = computed(() => {
  return items.value.reduce((sum, item) => sum + (item.setItemCount || 0), 0)
})

// Display items with original index tracking for drag preview
const displayItems = computed(() => {
  const itemsWithIndex = items.value.map((v, i) => ({ ...v, originalIndex: i }))

  // Batch mode: collapse to a single representative tile (a stack with a count).
  // Prep set on the representative is the uniform prep applied to every item.
  if (props.batchMode) {
    return itemsWithIndex.slice(0, 1)
  }

  if (props.reorderable && dragIndex.value !== null && dropIndex.value !== null && dragIndex.value !== dropIndex.value) {
    const result = [...itemsWithIndex]
    const [dragged] = result.splice(dragIndex.value, 1)
    result.splice(dropIndex.value, 0, dragged)
    return result
  }

  return itemsWithIndex
})

function getMediaUrl(item: MediaItem): string {
  // If item has a hash property, it's from the media library
  if (item.hash) {
    return getMediaFileUrl(item.hash)
  }
  // If path is not defined, fall back to filename
  if (!item.path) {
    if (item.filename) {
      return getMediaFileUrl(item.filename)
    }
    return ''
  }
  // If it's an absolute file path (starts with /), use the reference file endpoint
  // Include profile= query param since <img> elements can't send X-Profile-ID headers
  if (item.path.startsWith('/')) {
    const endpoint = getReferenceFileEndpoint(props.accept)
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${endpoint}?path=${encodeURIComponent(item.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  // Otherwise assume path is a hash
  return getMediaFileUrl(item.path)
}

function openFilePicker() {
  fileInput.value?.click()
}

// In-app media picker popover state. The add tile opens the popover; the OS
// file dialog is reached through its "Browse Files…" button.
const pickerPopoverOpen = ref(false)
const addTileRef = ref<HTMLElement | null>(null)

const pickerExcludeIds = computed(() =>
  items.value.map(i => i.mediaId).filter((id): id is number => typeof id === 'number')
)

function onAddTileClick() {
  if (props.disabled) return
  pickerPopoverOpen.value = !pickerPopoverOpen.value
}

async function onPopoverPick(mediaId: number) {
  pickerPopoverOpen.value = false
  await addFromMediaId(mediaId)
}

function onPopoverBrowse() {
  pickerPopoverOpen.value = false
  openFilePicker()
}

const previewModalUrl = ref('')

function onItemClick(item: MediaItem) {
  if (props.accept !== 'image') return
  if (props.batchMode) {
    const mediaIds = items.value.map(item => item.mediaId).filter((id): id is number => typeof id === 'number')
    if (mediaIds.length > 0) {
      emit('view-media-batch', mediaIds)
      return
    }
  }
  // If any processing has been applied, show the processed result in a full-screen modal
  if (item._originalPath) {
    const url = getMediaUrl(item)
    if (url) {
      previewModalUrl.value = url
      return
    }
  }
  // Otherwise open original in slideshow
  if (item.mediaId) {
    emit('view-media', item.mediaId)
  }
}

// Video-specific handlers
function onVideoLoaded(event: Event) {
  const video = event.target as HTMLVideoElement
  video.currentTime = 0.1
}

function onVideoLeave(event: Event) {
  const video = event.target as HTMLVideoElement
  video.pause()
  video.currentTime = 0.1
}

function onVideoError(event: Event, item: MediaItem) {
  console.error('Video load error:', item.path, getMediaUrl(item))
  videoErrors.value[item.path] = true
}

// Drag and drop handlers for adding items
function onDragOver() {
  if (props.disabled) return
  isDragging.value = true
}

function onDragLeave() {
  isDragging.value = false
}

function onTileDragOver(event: DragEvent, index: number) {
  if (props.reorderable && dragIndex.value !== null) {
    onReorderDragOver(event, index)
    return
  }
  onDragOver()
}

async function onTileDrop(event: DragEvent, index: number) {
  // Internal reorder takes precedence only when a reorder drag is active.
  if (props.reorderable && dragIndex.value !== null) {
    onReorderDrop()
    return
  }
  await onDrop(event, index)
}

async function onDrop(event: DragEvent, replaceIndex?: number) {
  isDragging.value = false
  if (props.disabled) return

  // Check for media ID from media library drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  if (mediaId) {
    if (replaceIndex === undefined && items.value.length >= props.maxItems) {
      return
    }
    await addFromMediaId(parseInt(mediaId), replaceIndex)
    return
  }

  // Fall back to file handling
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return

  // Image slots accept images and videos (videos → frame grab); video slots only
  // videos; audio slots only audio.
  const matchingFiles = Array.from(files).filter(f =>
    isImageSlot.value
      ? (f.type.startsWith('image/') || isVideoFile(f))
      : props.accept === 'audio'
        ? f.type.startsWith('audio/')
        : f.type.startsWith('video/')
  )
  if (matchingFiles.length === 0) return

  // Calculate how many we can add
  const slotsAvailable = replaceIndex !== undefined ? 1 : props.maxItems - items.value.length
  const filesToUpload = matchingFiles.slice(0, slotsAvailable)

  for (let i = 0; i < filesToUpload.length; i++) {
    const targetIndex = i === 0 ? replaceIndex : undefined
    await uploadFile(filesToUpload[i], targetIndex)
  }
}

// Reorder drag handlers
function onReorderDragStart(event: DragEvent, item: MediaItem) {
  const index = item.originalIndex as number
  dragIndex.value = index
  dropIndex.value = index

  // Reordering within this picker runs entirely off dragIndex/dropIndex above and
  // never reads dataTransfer. Setting the standard in-app media payload here too
  // (same shape MediaImage.vue uses) is what lets external drop zones — the
  // sidebar's board/tool/chat tabs — accept a drop of this tile; it's inert for
  // the reorder path since onReorderDrop/onTileDrop never look at it.
  if (item.mediaId && event.dataTransfer) {
    const thumbnailUrl = getThumbnailUrl(item.mediaId, 128)
    const ext = item.filename?.split('.').pop()?.toLowerCase() || ''
    createDragPreview(event, thumbnailUrl, item.mediaId, ext, props.accept === 'video')
  }
}

function onReorderDragOver(event: DragEvent, displayIndex: number) {
  if (dragIndex.value === null) return
  event.preventDefault()
  dropIndex.value = displayIndex
}

function onReorderDrop() {
  if (dragIndex.value !== null && dropIndex.value !== null && dragIndex.value !== dropIndex.value) {
    const newItems = [...items.value]
    const [item] = newItems.splice(dragIndex.value, 1)
    newItems.splice(dropIndex.value, 0, item)
    items.value = newItems
    emit('update:modelValue', newItems)
  }
  dragIndex.value = null
  dropIndex.value = null
}

function onReorderDragEnd() {
  dragIndex.value = null
  dropIndex.value = null
  clearDragPreview()
}

// Grab a still from a video (server-side, via ffmpeg) and insert it as a normal
// image item. The source is either an OS file (a drop / picker) or a library/
// reference video path. Default frame is role-aware per the target slot
// (Start→last, End→first, generic→first).
async function captureAndInsertFrame(
  src: { file?: File; sourcePath?: string },
  slotIndex: number,
  source: { mediaId?: number; hash?: string; filename: string; sourcePath?: string },
  replaceIndex?: number,
) {
  const position = frameDefaultForSlot(slotIndex)
  isUploading.value = true
  try {
    const ext = await extractFrame({ file: src.file, sourcePath: src.sourcePath, position })
    // For OS file drops there's no server copy of the video — keep the File in the
    // session cache so the frame picker can scrub + re-extract from it.
    let clientKey: string | undefined
    if (src.file) {
      clientKey = `vf_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
      droppedVideoFiles.set(clientKey, src.file)
    }
    const newItem: MediaItem = {
      path: ext.path,
      filename: ext.filename,
      width: ext.width,
      height: ext.height,
      _videoSource: {
        mediaId: source.mediaId,
        hash: source.hash,
        filename: source.filename,
        duration: ext.duration,
        fps: ext.fps,
        sourcePath: source.sourcePath,
        clientKey,
      },
      _frameTime: ext.time,
      _framePosition: position,
    }

    let newItems: MediaItem[]
    if (replaceIndex !== undefined) {
      newItems = [...items.value]
      newItems[replaceIndex] = newItem
    } else {
      newItems = [...items.value, newItem]
    }
    items.value = newItems
    emit('update:modelValue', newItems)
  } catch (error: any) {
    console.error('Failed to grab video frame:', error)
    addToast(error?.response?.data?.detail || error?.message || "Couldn't grab a frame from that video.", 'error')
  } finally {
    isUploading.value = false
  }
}

async function addFromMediaId(mediaId: number, replaceIndex?: number) {
  isUploading.value = true
  try {
    const mediaItem = await getMediaItem(mediaId)

    // Feed the picker popover's "Recent" tab. Atomic media only — sets are a
    // batch mechanism, not a reusable input.
    const kind = getMediaType(mediaItem)
    if (kind === 'image' || kind === 'video' || kind === 'audio') {
      recordMediaInputUse({
        mediaId: mediaItem.id,
        fileHash: mediaItem.file_hash,
        fileFormat: mediaItem.file_format,
        kind: kind as RecentInputKind,
      })
    }

    // Video dropped into an image slot → grab a frame instead of using it directly.
    if (isImageSlot.value && isVideoExtension(mediaItem.file_format)) {
      const slotIndex = replaceIndex ?? items.value.length
      const filename = mediaItem.file_path?.split('/').pop() || `video.${mediaItem.file_format}`
      isUploading.value = false  // captureAndInsertFrame manages its own flag
      await captureAndInsertFrame(
        { sourcePath: mediaItem.file_path },
        slotIndex,
        { mediaId: mediaItem.id, hash: mediaItem.file_hash, filename, sourcePath: mediaItem.file_path },
        replaceIndex,
      )
      return
    }

    // Check if this is a set
    const isSet = mediaItem.file_format === 'stimmaset.json'

    if (isSet) {
      // Handle set input
      if (!props.allowSets) {
        console.warn('Sets are not allowed for this input')
        return
      }

      // Parse raw_metadata if it's a string
      let setContent: any = null
      if (typeof mediaItem.raw_metadata === 'string') {
        try {
          setContent = JSON.parse(mediaItem.raw_metadata)
        } catch (e) {
          console.error('Failed to parse set raw_metadata:', e)
        }
      } else {
        setContent = mediaItem.raw_metadata
      }

      // Get item count from member_count (computed by backend) or parsed content
      const itemCount = mediaItem.member_count || setContent?.items?.length || 0
      if (itemCount === 0) {
        console.error('Invalid set: no items found')
        return
      }

      // Validate set content type matches accept prop (if we have resolved content)
      const setItems = setContent?.items || []
      if (setItems.length > 0) {
        const contentType = getSetContentType(setItems)
        if (contentType && contentType !== props.accept) {
          console.warn(`Set contains ${contentType}s but this input expects ${props.accept}s`)
          return
        }
      }

      // Create a set reference item
      const newItem: MediaItem = {
        path: mediaItem.file_path,
        filename: mediaItem.file_path?.split('/').pop() || 'set.stimmaset.json',
        hash: mediaItem.file_hash,
        mediaId: mediaItem.id,
        isSet: true,
        setItemCount: itemCount,
        setId: mediaItem.id,
      }

      // Sets replace all existing items (batch mode)
      items.value = [newItem]
      emit('update:modelValue', [newItem])
    } else {
      // A library pick is an existing immutable Media payload. Use it directly;
      // routing it back through upload ingest creates a duplicate Asset.
      const newItem: MediaItem = {
        path: mediaItem.file_path,
        filename: mediaItem.file_path?.split('/').pop() || `media.${mediaItem.file_format}`,
        hash: mediaItem.file_hash,
        mediaId: mediaItem.id,
        width: mediaItem.width,
        height: mediaItem.height,
      }

      let newItems: MediaItem[]
      if (replaceIndex !== undefined) {
        newItems = [...items.value]
        newItems[replaceIndex] = newItem
      } else {
        newItems = [...items.value, newItem]
      }

      items.value = newItems
      emit('update:modelValue', newItems)
    }
  } catch (error) {
    console.error('Failed to add from media library:', error)
    // The item no longer exists — stop offering it in the popover feeds.
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      removeRecentMediaInput(mediaId)
      removeRecentMediaPick(mediaId)
    }
  } finally {
    isUploading.value = false
  }
}

// Helper to determine the content type of a set
function getSetContentType(items: any[]): 'image' | 'video' | null {
  const IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif']
  const VIDEO_FORMATS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v']

  const types = new Set<string>()
  for (const item of items) {
    const resolved = item.resolved
    if (!resolved) continue

    const format = (resolved.file_format || '').toLowerCase()
    if (IMAGE_FORMATS.includes(format)) {
      types.add('image')
    } else if (VIDEO_FORMATS.includes(format)) {
      types.add('video')
    }
  }

  if (types.size === 1) {
    return types.has('image') ? 'image' : 'video'
  }
  return null  // Mixed or unknown
}

async function uploadFile(file: File, replaceIndex?: number) {
  // Video dropped/picked into an image slot → grab a frame server-side from the
  // uploaded bytes (the still is all the tool consumes; the video isn't kept).
  if (isImageSlot.value && isVideoFile(file)) {
    const slotIndex = replaceIndex ?? items.value.length
    await captureAndInsertFrame(
      { file },
      slotIndex,
      { filename: file.name },
      replaceIndex,
    )
    return
  }

  isUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)

    const endpoint = UPLOAD_ENDPOINTS[props.accept]
    const response = await axios.post(endpoint, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    const newItem: MediaItem = {
      path: response.data.path,
      filename: response.data.filename,
      hash: response.data.file_hash,
      mediaId: response.data.media_id,
      width: response.data.width,
      height: response.data.height,
      thumbnailUrl: response.data.thumbnail_url
    }

    // Clear any previous error for this path
    if (props.accept === 'video') {
      delete videoErrors.value[newItem.path]
    }

    let newItems: MediaItem[]
    if (replaceIndex !== undefined) {
      newItems = [...items.value]
      newItems[replaceIndex] = newItem
    } else {
      newItems = [...items.value, newItem]
    }

    items.value = newItems
    emit('update:modelValue', newItems)
  } catch (error) {
    console.error('Failed to upload file:', error)
  } finally {
    isUploading.value = false
  }
}

async function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files

  if (!files || files.length === 0) return

  // Clear the input so the same file can be selected again
  input.value = ''

  // Upload files up to max
  const slotsAvailable = props.maxItems - items.value.length
  const filesToUpload = Array.from(files).slice(0, slotsAvailable)

  for (const file of filesToUpload) {
    await uploadFile(file)
  }
}

// --- Per-image ControlNet preprocessing ---

function onPreprocessorSliderInput(index: number, param: string, value: number) {
  const item = items.value[index]
  if (!item) return

  // Update the param immediately for UI feedback (no reprocessing yet)
  const currentParams = item._preprocessorParams ? { ...item._preprocessorParams } : {}
  currentParams[param] = value

  const newItems = [...items.value]
  newItems[index] = { ...item, _preprocessorParams: currentParams }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function saveControlnetParams(preprocessor: string, params: Record<string, number>) {
  const key = makeProfileKey('controlnet', preprocessor)
  localStorage.setItem(key, JSON.stringify(params))
}

function loadControlnetParams(preprocessor: string): Record<string, number> | null {
  const key = makeProfileKey('controlnet', preprocessor)
  const raw = localStorage.getItem(key)
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

const PREPROCESSOR_DEFAULTS: Record<string, Record<string, number>> = {
  canny: { low: 128, high: 128 },
  lineart: { sigma: 6.0, threshold: 8 },
  lineart_realistic: { coarse: 0 },
}

function onPreprocessorSliderCommit(index: number) {
  const item = items.value[index]
  if (!item || !item._preprocessorParams || !item._preprocessor) return
  const params = { ...item._preprocessorParams }

  // Clamp canny: low must be < high
  if (item._preprocessor === 'canny' && params.low !== undefined && params.high !== undefined) {
    if (params.low >= params.high) {
      params.low = Math.max(1, params.high - 1)
    }
    // Update UI to reflect clamped values
    const newItems = [...items.value]
    newItems[index] = { ...item, _preprocessorParams: params }
    items.value = newItems
    emit('update:modelValue', newItems)
  }

  applyPreprocessor(index, item._preprocessor, params)
}

function onPreprocessorReset(index: number) {
  const item = items.value[index]
  if (!item || !item._preprocessor) return
  // Clear params and re-apply with defaults
  const newItems = [...items.value]
  newItems[index] = { ...item, _preprocessorParams: undefined }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyPreprocessor(index, item._preprocessor, PREPROCESSOR_DEFAULTS[item._preprocessor])
}

function onRealisticCoarseToggle(index: number, checked: boolean) {
  const item = items.value[index]
  if (!item || item._preprocessor !== 'lineart_realistic') return
  applyPreprocessor(index, 'lineart_realistic', { coarse: checked ? 1 : 0 })
}

async function applyPreprocessor(index: number, preprocessor: string | null, params?: Record<string, number>) {
  const item = items.value[index]
  if (!item || item.isSet) return

  const newItems = [...items.value]

  // Clicking "Original" — restore preprocessor (but keep paint/extend)
  if (preprocessor === null) {
    newItems[index] = {
      ...item,
      _preprocessor: null,
      _preprocessorParams: undefined,
    }
    items.value = newItems
    emit('update:modelValue', newItems)
    // Re-run pipeline without preprocessor (may still have paint/extend)
    await applyFullPreprocessing(index)
    return
  }

  // Load saved params if none explicitly provided (fresh dropdown selection)
  if (!params) {
    params = loadControlnetParams(preprocessor) ?? undefined
  }

  // Same preprocessor already active — no-op (but allow if params provided, since slider changed)
  if (item._preprocessor === preprocessor && !params) return

  // Update preprocessor metadata on item first
  newItems[index] = {
    ...item,
    _preprocessor: preprocessor,
    _preprocessorParams: params,
  }
  items.value = newItems
  emit('update:modelValue', newItems)

  // Persist params for next time this preprocessor is selected
  const usedParams = params || PREPROCESSOR_DEFAULTS[preprocessor]
  if (usedParams) saveControlnetParams(preprocessor, usedParams)

  // Run the full pipeline
  await applyFullPreprocessing(index)
}

/**
 * Run the full preprocessing pipeline: scale → preprocess → extend → paint.
 * Called whenever any prep parameter changes.
 */
async function applyFullPreprocessing(index: number, reason: ProcessingReason = 'preprocess') {
  const item = items.value[index]
  if (!item || item.isSet) return

  // Stash the original path/hash/dims if not already done
  const originalPath = item._originalPath || item.path
  const originalHash = item._originalHash || item.hash
  const originalWidth = item._originalWidth ?? item.width
  const originalHeight = item._originalHeight ?? item.height

  const itemHasFlip = hasFlip(item)
  const itemHasCrop = hasCrop(item)
  const hasPreprocessor = !!item._preprocessor
  const hasPaint = !!(item._paintLayerDataUrl || item._paintLayerPath)
  const hasExtend = !!(item._extendPadding && (
    item._extendPadding.top > 0 || item._extendPadding.bottom > 0 ||
    item._extendPadding.left > 0 || item._extendPadding.right > 0
  ))
  const itemHasScale = hasScale(item)

  // Nothing to do — restore original
  if (!itemHasFlip && !itemHasCrop && !hasPreprocessor && !hasPaint && !hasExtend && !itemHasScale) {
    if (item._originalPath) {
      const newItems = [...items.value]
      newItems[index] = {
        ...item,
        path: item._originalPath,
        hash: item._originalHash,
        width: item._originalWidth ?? item.width,
        height: item._originalHeight ?? item.height,
        _originalPath: undefined,
        _originalHash: undefined,
        _originalWidth: undefined,
        _originalHeight: undefined,
        _basePath: null,
        _baseWidth: null,
        _baseHeight: null,
      }
      items.value = newItems
      emit('update:modelValue', newItems)
    }
    return
  }

  processingReason.value = reason
  processingIndex.value = index
  try {
    // Upload paint layer if it exists but hasn't been uploaded yet
    let paintLayerPath = item._paintLayerPath || null
    if (hasPaint && !paintLayerPath) {
      const paintBlob = await fetch(item._paintLayerDataUrl!).then(r => r.blob())
      const formData = new FormData()
      formData.append('file', paintBlob, 'paint_layer.png')
      const uploadResponse = await axios.post(`${API_BASE}/generate/upload-paint-layer`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      paintLayerPath = uploadResponse.data.path
    }

    // Build request body: flip/rotate → crop → scale → preprocess → extend → paint
    const body: Record<string, any> = {
      source_path: originalPath,
    }
    if (itemHasFlip) {
      body.flip = {
        horizontal: !!item._flip!.horizontal,
        vertical: !!item._flip!.vertical,
        rotation: ((item._flip!.rotation ?? 0) % 360 + 360) % 360,
      }
    }
    if (itemHasCrop) {
      body.crop = item._crop
    }
    if (itemHasScale) {
      const s = item._scale!
      if (s.mode === 'megapixels') {
        body.scale = { mode: 'megapixels', megapixels: s.megapixels || 1 }
      } else if (s.mode === 'manual') {
        // Scale runs on the post-crop image, so the factor is relative to it.
        const { w } = croppedDims(item)
        const factor = (s.width || w) / w
        body.scale = { mode: 'factor', factor }
      } else {
        body.scale = { mode: 'factor', factor: s.factor || 1 }
      }
    }
    if (hasPreprocessor) {
      body.preprocessor = item._preprocessor
      if (item._preprocessorParams) body.preprocessor_params = item._preprocessorParams
    }
    if (hasExtend) {
      body.extend_padding = item._extendPadding
      if (item._extendBgColor) body.extend_bg_color = item._extendBgColor
    }
    if (paintLayerPath) body.paint_layer_path = paintLayerPath

    const response = await axios.post(`${API_BASE}/generate/preprocess-reference`, body)
    const newItems = [...items.value]
    newItems[index] = {
      ...items.value[index],  // Re-read to avoid stale state
      path: response.data.path,
      hash: undefined,
      width: response.data.width,
      height: response.data.height,
      _originalPath: originalPath,
      _originalHash: originalHash,
      _originalWidth: originalWidth,
      _originalHeight: originalHeight,
      _paintLayerPath: paintLayerPath,
      // base_path is only returned by the server when paint exists; when there's
      // no paint, the main path IS the base (same file), so we fall back to it.
      _basePath: response.data.base_path || response.data.path,
      _baseWidth: response.data.base_width || response.data.width,
      _baseHeight: response.data.base_height || response.data.height,
    }
    items.value = newItems
    emit('update:modelValue', newItems)
  } catch (err) {
    console.error('Reference preprocessing failed:', err)
  } finally {
    processingIndex.value = null
    processingReason.value = null
  }
}

// --- Prep panel toggling ---
const openPrepPanel = reactive<Record<number, string | null>>({})

function togglePrepPanel(index: number, panel: string) {
  if (openPrepPanel[index] === panel) {
    openPrepPanel[index] = null
  } else {
    openPrepPanel[index] = panel
  }
}

// --- Frame picker (for stills grabbed from a video) ---
// Scrubbing is CLIENT-side and live: while the Frame panel is open, a <video>
// takes over the tile's image area and we seek it directly on every input, so it's
// instant and frame-accurate. The committed still is still extracted server-side
// (ffmpeg, any codec) on release / step / shortcut. Re-picking is like dropping a
// fresh image: the new still replaces the old and prior prep is dropped.
const frameScrub = reactive<Record<number, number>>({})        // working scrub time (s)
const frameCommitting = reactive<Record<number, boolean>>({})  // re-extract in flight
const frameCommitTimers: Record<number, ReturnType<typeof setTimeout>> = {}
const scrubVideoEls: Record<number, HTMLVideoElement | null> = {}
// Session caches for OS file drops (no server copy): the File for re-extraction,
// and a stable object URL so the scrub <video> can play it.
const droppedVideoFiles = new Map<string, File>()
const droppedVideoUrls = new Map<string, string>()

function droppedFileUrl(clientKey: string): string {
  if (!droppedVideoUrls.has(clientKey)) {
    const f = droppedVideoFiles.get(clientKey)
    if (!f) return ''
    droppedVideoUrls.set(clientKey, URL.createObjectURL(f))
  }
  return droppedVideoUrls.get(clientKey) || ''
}

function frameDuration(item: MediaItem): number {
  return item._videoSource?.duration || 0
}

function frameFps(item: MediaItem): number {
  return item._videoSource?.fps || 0
}

function frameStep(item: MediaItem): number {
  const fps = frameFps(item)
  return fps > 0 ? 1 / fps : 0.04
}

function atFirstFrame(item: MediaItem): boolean {
  return frameScrubValue(item) <= 1e-3
}

function atLastFrame(item: MediaItem): boolean {
  const dur = frameDuration(item)
  return dur > 0 && frameScrubValue(item) >= dur - frameStep(item) - 1e-3
}

function frameScrubValue(item: MediaItem): number {
  return frameScrub[item.originalIndex as number] ?? item._frameTime ?? 0
}

// Playable URL for the scrub <video>: a dropped File's object URL, else the library
// media URL (supports range/seeking), else the reference-video serve path.
function frameVideoUrl(item: MediaItem): string {
  const vs = item._videoSource
  if (!vs) return ''
  if (vs.clientKey) {
    const u = droppedFileUrl(vs.clientKey)
    if (u) return u
  }
  if (vs.mediaId) return getMediaFileUrl(vs.mediaId)
  if (vs.sourcePath) {
    const base = getApiBase()
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let u = `${base}/generate/reference-video-file?path=${encodeURIComponent(vs.sourcePath)}&profile=${encodeURIComponent(profileId)}`
    if (pin) u += `&pin=${encodeURIComponent(pin)}`
    return u
  }
  return ''
}

function setScrubVideo(index: number, el: HTMLVideoElement | null) {
  scrubVideoEls[index] = el
}

function onScrubVideoLoaded(item: MediaItem, event: Event) {
  // Show the currently-selected frame when the scrubber opens.
  const el = event.target as HTMLVideoElement
  const t = frameScrubValue(item)
  try { el.currentTime = Math.min(t, Math.max(0, (el.duration || frameDuration(item)) - 1e-3)) } catch { /* ignore */ }
}

function formatScrubTime(seconds: number): string {
  const s = Math.max(0, seconds)
  const m = Math.floor(s / 60)
  const rem = s - m * 60
  return `${m}:${rem.toFixed(2).padStart(5, '0')}`
}

// Seek the live <video> immediately (responsive); schedule a debounced server
// commit so continuous dragging doesn't spam extractions.
function seekScrub(item: MediaItem, t: number, { commit = 'debounced' as 'debounced' | 'now' | 'none' } = {}) {
  const i = item.originalIndex as number
  const dur = frameDuration(item)
  const clamped = Math.max(0, dur ? Math.min(t, dur) : t)
  frameScrub[i] = clamped
  const el = scrubVideoEls[i]
  if (el) { try { el.currentTime = clamped } catch { /* ignore */ } }
  if (commit === 'none') return
  if (frameCommitTimers[i]) clearTimeout(frameCommitTimers[i])
  if (commit === 'now') {
    commitFrame(item, 'custom', clamped)
  } else {
    frameCommitTimers[i] = setTimeout(() => commitFrame(item, 'custom', clamped), 280)
  }
}

function stepFrame(item: MediaItem, dir: number) {
  if (dir < 0 && atFirstFrame(item)) return
  if (dir > 0 && atLastFrame(item)) return
  const step = frameStep(item)
  seekScrub(item, frameScrubValue(item) + dir * step, { commit: 'debounced' })
}

async function commitFrame(item: MediaItem, position: FramePosition, timeSeconds?: number) {
  const i = item.originalIndex as number
  const vs = item._videoSource
  const file = vs?.clientKey ? droppedVideoFiles.get(vs.clientKey) : undefined
  if (!vs || (!vs.sourcePath && !file) || frameCommitting[i]) return
  if (frameCommitTimers[i]) { clearTimeout(frameCommitTimers[i]); delete frameCommitTimers[i] }
  frameCommitting[i] = true
  try {
    const ext = await extractFrame({ file, sourcePath: vs.sourcePath, position, timeSeconds })
    const updated: MediaItem = {
      path: ext.path,
      filename: ext.filename,
      width: ext.width,
      height: ext.height,
      _videoSource: vs,   // keep source so the picker stays available
      _frameTime: ext.time,
      _framePosition: position,
    }
    const newItems = [...items.value]
    newItems[i] = updated
    items.value = newItems
    emit('update:modelValue', newItems)
    frameScrub[i] = ext.time
  } catch (e: any) {
    console.error('Failed to pick frame:', e)
    addToast(e?.response?.data?.detail || e?.message || "Couldn't pick that frame.", 'error')
  } finally {
    frameCommitting[i] = false
  }
}

function setFramePosition(item: MediaItem, position: 'first' | 'middle' | 'last') {
  const dur = frameDuration(item)
  // For the live <video>, land one frame short of the end (seeking exactly to
  // duration can show black); the committed 'last' frame uses the server's backoff.
  const t = position === 'first' ? 0 : position === 'middle' ? dur / 2 : Math.max(0, dur - frameStep(item))
  seekScrub(item, t, { commit: 'none' })
  commitFrame(item, position)
}

// Filmstrip timeline (progressive enhancement over the plain track).
const stripReady = reactive<Record<number, boolean>>({})
const stripFailed = reactive<Record<number, boolean>>({})
const stripDragging = reactive<Record<number, boolean>>({})

function frameStripUrl(item: MediaItem): string {
  const sp = item._videoSource?.sourcePath
  if (!sp) return ''   // OS file drops have no server copy → plain-track fallback
  const base = getApiBase()
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let u = `${base}/generate/frame-strip?source_path=${encodeURIComponent(sp)}&count=6&w=120&profile=${encodeURIComponent(profileId)}`
  if (pin) u += `&pin=${encodeURIComponent(pin)}`
  return u
}

function framePercent(item: MediaItem): number {
  const dur = frameDuration(item)
  if (dur <= 0) return 0
  return Math.min(100, Math.max(0, (frameScrubValue(item) / dur) * 100))
}

function frameCount(item: MediaItem): number {
  const fps = frameFps(item)
  return fps > 0 ? Math.max(1, Math.round(frameDuration(item) * fps)) : 0
}

function frameIndex(item: MediaItem): number {
  const fps = frameFps(item)
  return fps > 0 ? Math.min(frameCount(item), Math.round(frameScrubValue(item) * fps) + 1) : 0
}

// Readout mode (time vs frames) — persisted per tool (not per slot), defaulting to
// time. Frames are only shown when we actually know the source fps.
const frameDisplayMode = ref<'time' | 'frames'>('time')

function loadFrameDisplayMode() {
  if (!props.frameModeKey) { frameDisplayMode.value = 'time'; return }
  try {
    frameDisplayMode.value = localStorage.getItem(makeProfileKey('frame-mode', props.frameModeKey)) === 'frames' ? 'frames' : 'time'
  } catch { frameDisplayMode.value = 'time' }
}

function toggleFrameDisplay() {
  frameDisplayMode.value = frameDisplayMode.value === 'frames' ? 'time' : 'frames'
  if (props.frameModeKey) {
    try { localStorage.setItem(makeProfileKey('frame-mode', props.frameModeKey), frameDisplayMode.value) } catch { /* ignore */ }
  }
}

function showFrames(item: MediaItem): boolean {
  return frameDisplayMode.value === 'frames' && frameFps(item) > 0
}

// The single readout (header). Time shows hundredths; frames show f n/total.
function headerFrameLabel(item: MediaItem): string {
  return showFrames(item) ? `f ${frameIndex(item)}/${frameCount(item)}` : formatScrubTime(frameScrubValue(item))
}

onMounted(loadFrameDisplayMode)
watch(() => props.frameModeKey, loadFrameDisplayMode)

function scrubFromPointer(item: MediaItem, el: HTMLElement, clientX: number, commit: 'debounced' | 'now') {
  const r = el.getBoundingClientRect()
  const frac = r.width > 0 ? Math.min(1, Math.max(0, (clientX - r.left) / r.width)) : 0
  seekScrub(item, frac * (frameDuration(item) || 0), { commit })
}

function endScrubDrag(i: number) {
  stripDragging[i] = false
  document.body.style.userSelect = ''
}

function onScrubPointerDown(item: MediaItem, e: PointerEvent) {
  // Suppress the text-selection a drag would otherwise start across nearby labels.
  e.preventDefault()
  document.body.style.userSelect = 'none'
  const el = e.currentTarget as HTMLElement
  el.setPointerCapture?.(e.pointerId)
  stripDragging[item.originalIndex as number] = true
  scrubFromPointer(item, el, e.clientX, 'debounced')
}

function onScrubPointerMove(item: MediaItem, e: PointerEvent) {
  if (!stripDragging[item.originalIndex as number]) return
  e.preventDefault()
  scrubFromPointer(item, e.currentTarget as HTMLElement, e.clientX, 'debounced')
}

function onScrubPointerUp(item: MediaItem, e: PointerEvent) {
  const i = item.originalIndex as number
  if (!stripDragging[i]) return
  endScrubDrag(i)
  scrubFromPointer(item, e.currentTarget as HTMLElement, e.clientX, 'now')
}

function onScrubPointerCancel(item: MediaItem) {
  endScrubDrag(item.originalIndex as number)
}

onBeforeUnmount(() => {
  for (const url of droppedVideoUrls.values()) URL.revokeObjectURL(url)
  for (const t of Object.values(frameCommitTimers)) clearTimeout(t)
  document.body.style.userSelect = ''  // in case we unmount mid-drag
})

// --- Scale ---

const scaleModes = [
  { value: 'factor' as const, label: 'Factor' },
  { value: 'megapixels' as const, label: 'Megapixels' },
  { value: 'manual' as const, label: 'Manual' },
]

// --- Flip / Rotate ---

function hasFlip(item: MediaItem): boolean {
  const f = item._flip
  if (!f) return false
  return !!f.horizontal || !!f.vertical || (((f.rotation ?? 0) % 360 + 360) % 360) !== 0
}

function getFlipStatusText(item: MediaItem): string {
  const f = item._flip
  if (!f || !hasFlip(item)) return 'None'
  const parts: string[] = []
  if (f.horizontal) parts.push('H')
  if (f.vertical) parts.push('V')
  const rot = ((f.rotation ?? 0) % 360 + 360) % 360
  if (rot !== 0) parts.push(`${rot}°`)
  return parts.join(' ')
}

function toggleFlip(index: number, axis: 'horizontal' | 'vertical') {
  const item = items.value[index]
  if (!item) return
  const current = item._flip || {}
  const newFlip = { ...current, [axis]: !current[axis] }
  const newItems = [...items.value]
  newItems[index] = { ...item, _flip: newFlip }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'flip')
}

function rotate(index: number, dir: 'left' | 'right') {
  const item = items.value[index]
  if (!item) return
  const current = item._flip || {}
  const delta = dir === 'right' ? 90 : 270
  const rotation = (((current.rotation ?? 0) + delta) % 360 + 360) % 360
  const newItems = [...items.value]
  newItems[index] = { ...item, _flip: { ...current, rotation } }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'flip')
}

function resetFlip(index: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _flip: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'flip')
}

function origDims(item: MediaItem): { w: number; h: number } {
  const w = item._originalWidth ?? item.width ?? 1
  const h = item._originalHeight ?? item.height ?? 1
  // Flip/rotate runs first in the pipeline; a 90°/270° rotation swaps the
  // dimensions that every downstream stage (scale, extend, footer) sees.
  const rot = ((item._flip?.rotation ?? 0) % 360 + 360) % 360
  if (rot === 90 || rot === 270) return { w: h, h: w }
  return { w, h }
}

// Pre-scale dimensions: crop runs right after flip/rotate, so every downstream
// stage (scale, extend, footer) sees the cropped size.
function croppedDims(item: MediaItem): { w: number; h: number } {
  const { w, h } = origDims(item)
  const c = item._crop
  if (!c || !hasCrop(item)) return { w, h }
  return {
    w: Math.max(1, Math.round(w * c.width)),
    h: Math.max(1, Math.round(h * c.height)),
  }
}

function origMegapixels(item: MediaItem): number {
  const { w, h } = croppedDims(item)
  return (w * h) / 1_000_000
}

// --- Crop ---

function hasCrop(item: MediaItem): boolean {
  const c = item._crop
  if (!c) return false
  return c.x > 0.0005 || c.y > 0.0005 || c.width < 0.999 || c.height < 0.999 || !!c.rotation
}

function getCropStatusText(item: MediaItem): string {
  if (!hasCrop(item)) return 'Off'
  const { w, h } = croppedDims(item)
  const rot = item._crop?.rotation
  return rot ? `${w} × ${h} · ${rot}°` : `${w} × ${h}`
}

function resetCrop(index: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _crop: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'crop')
}

function hasScale(item: MediaItem): boolean {
  if (!item._scale) return false
  if (item._scale.mode === 'factor') return (item._scale.factor || 1) !== 1
  if (item._scale.mode === 'megapixels') {
    const target = item._scale.megapixels
    if (!target) return false
    return Math.abs(target - origMegapixels(item)) > 0.05
  }
  if (item._scale.mode === 'manual') {
    const { w } = croppedDims(item)
    const target = item._scale.width
    if (!target) return false
    return target !== w
  }
  return false
}

function getScaleStatusText(item: MediaItem): string {
  if (!item._scale || !hasScale(item)) return '1x'
  if (item._scale.mode === 'megapixels') return `${(item._scale.megapixels || 1).toFixed(1)} MP`
  if (item._scale.mode === 'manual') return `${item._scale.width}×${item._scale.height}`
  return `${(item._scale.factor || 1).toFixed(2)}x`
}

type ScaleMode = 'factor' | 'megapixels' | 'manual'

function onScaleModeChange(index: number, mode: ScaleMode) {
  const item = items.value[index]
  if (!item) return
  const { w, h } = croppedDims(item)
  const defaults: Record<ScaleMode, NonNullable<MediaItem['_scale']>> = {
    factor: { mode: 'factor', factor: item._scale?.factor || 1 },
    megapixels: { mode: 'megapixels', megapixels: item._scale?.megapixels || Number(origMegapixels(item).toFixed(1)) },
    manual: { mode: 'manual', width: item._scale?.width || w, height: item._scale?.height || h },
  }
  const newItems = [...items.value]
  newItems[index] = { ...item, _scale: defaults[mode] }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function onScaleSliderInput(index: number, factor: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _scale: { mode: 'factor', factor } }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function onMegapixelsSliderInput(index: number, mp: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _scale: { mode: 'megapixels', megapixels: mp } }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function onManualDimensionInput(index: number, dim: 'width' | 'height', value: number) {
  const item = items.value[index]
  if (!item || !value || value < 1) return
  const { w, h } = croppedDims(item)
  const aspect = w / h
  let width: number, height: number
  if (dim === 'width') {
    width = Math.round(value)
    height = Math.max(1, Math.round(value / aspect))
  } else {
    height = Math.round(value)
    width = Math.max(1, Math.round(value * aspect))
  }
  const newItems = [...items.value]
  newItems[index] = { ...item, _scale: { mode: 'manual', width, height } }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'scale')
}

function onScaleSliderCommit(index: number) {
  applyFullPreprocessing(index, 'scale')
}

function resetScale(index: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _scale: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'scale')
}

// --- Extend Canvas ---

function hasExtendPadding(item: MediaItem): boolean {
  const p = item._extendPadding
  if (!p) return false
  return p.top > 0 || p.bottom > 0 || p.left > 0 || p.right > 0
}

function getExtendValue(item: MediaItem, side: 'top' | 'bottom' | 'left' | 'right'): number {
  return item._extendPadding?.[side] ?? 0
}

function getExtendStatusText(item: MediaItem): string {
  const p = item._extendPadding
  if (!p || !hasExtendPadding(item)) return 'Off'
  // Check if all sides are the same
  if (p.top === p.bottom && p.bottom === p.left && p.left === p.right) {
    return `${p.top}% all`
  }
  const parts: string[] = []
  if (p.top) parts.push(`T${p.top}%`)
  if (p.bottom) parts.push(`B${p.bottom}%`)
  if (p.left) parts.push(`L${p.left}%`)
  if (p.right) parts.push(`R${p.right}%`)
  return parts.join(' ')
}

// Returns post-scale, pre-extend dimensions. After applyFullPreprocessing runs,
// item.width/height reflects the full pipeline output (post-extend), so we must
// start from _originalWidth/_originalHeight (the source) and apply crop + scale
// ourselves.
function getPostScaleDimensions(item: MediaItem): { width: number; height: number } {
  // croppedDims accounts for flip/rotate (90°/270° swaps W/H) and crop.
  const { w, h } = croppedDims(item)
  const s = item._scale
  if (!s) return { width: w, height: h }
  if (s.mode === 'factor') {
    const f = s.factor ?? 1
    return { width: Math.round(w * f), height: Math.round(h * f) }
  }
  if (s.mode === 'manual') {
    return { width: s.width ?? w, height: s.height ?? h }
  }
  if (s.mode === 'megapixels') {
    const currentMp = (w * h) / 1_000_000
    if (currentMp === 0) return { width: w, height: h }
    const factor = Math.sqrt((s.megapixels ?? currentMp) / currentMp)
    return { width: Math.round(w * factor), height: Math.round(h * factor) }
  }
  return { width: w, height: h }
}

function getExtendedDimensions(item: MediaItem): { width: number; height: number } {
  const { width: w, height: h } = getPostScaleDimensions(item)
  const p = item._extendPadding
  if (!p) return { width: w, height: h }
  return {
    width: w + Math.round(w * p.left / 100) + Math.round(w * p.right / 100),
    height: h + Math.round(h * p.top / 100) + Math.round(h * p.bottom / 100),
  }
}

function onExtendSliderInput(index: number, side: 'top' | 'bottom' | 'left' | 'right', value: number) {
  const item = items.value[index]
  if (!item) return

  const currentPadding = item._extendPadding ? { ...item._extendPadding } : { top: 0, bottom: 0, left: 0, right: 0 }
  currentPadding[side] = value

  const newItems = [...items.value]
  newItems[index] = { ...item, _extendPadding: currentPadding }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function setCanvasToItemSize(item: MediaItem) {
  const dims = getExtendedDimensions(item)
  if (dims.width > 0 && dims.height > 0) {
    emit('suggest-resolution', dims, { manual: true })
  }
}

function setCanvasToItemAspect(item: MediaItem) {
  const dims = getExtendedDimensions(item)
  if (dims.width > 0 && dims.height > 0) {
    emit('suggest-aspect', dims, { manual: true })
  }
}

function emitExtendedResolution() {
  // Suggest resolution based on first image with extend padding
  const item = items.value.find(i => i._extendPadding && (
    i._extendPadding.top > 0 || i._extendPadding.bottom > 0 ||
    i._extendPadding.left > 0 || i._extendPadding.right > 0
  ))
  if (item) {
    const dims = getExtendedDimensions(item)
    if (dims.width > 0 && dims.height > 0) {
      emit('suggest-resolution', dims, { manual: false })
      return
    }
  }
  emit('suggest-resolution', null, { manual: false })
}

function onExtendSliderCommit(index: number) {
  emitExtendedResolution()
  applyFullPreprocessing(index, 'extend')
}

function resetExtendPadding(index: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _extendPadding: null, _extendBgColor: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  // After clearing this item's padding, re-check if any other item still has extend
  emitExtendedResolution()
  applyFullPreprocessing(index, 'extend')
}

function onExtendBgColorInput(index: number, color: string) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _extendBgColor: color }
  items.value = newItems
  emit('update:modelValue', newItems)
}

function onExtendBgColorCommit(index: number, color: string) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _extendBgColor: color }
  items.value = newItems
  emit('update:modelValue', newItems)
  if (hasExtendPadding(items.value[index])) {
    applyFullPreprocessing(index, 'extend')
  }
}

// --- Crop Editor ---

const cropEditorOpen = ref(false)
const cropEditorIndex = ref<number | null>(null)
// Snapshot for the modal: original (pre-prep) image URL + flip so the surface
// shows exactly what the backend crops (crop runs on the post-flip image).
const cropEditorImage = ref<{
  url: string
  width?: number
  height?: number
  flip: MediaItem['_flip']
  crop: MediaItem['_crop']
} | null>(null)

function openCropEditor(index: number) {
  const item = items.value[index]
  if (!item) return
  // Build a URL for the ORIGINAL image (the current path may already have
  // crop/scale/extend/paint baked in).
  const url = getMediaUrl({
    ...item,
    path: item._originalPath || item.path,
    hash: item._originalHash || item.hash,
  })
  if (!url) return
  cropEditorImage.value = {
    url,
    width: item._originalWidth ?? item.width,
    height: item._originalHeight ?? item.height,
    flip: item._flip ?? null,
    crop: item._crop ?? null,
  }
  cropEditorIndex.value = index
  cropEditorOpen.value = true
}

function onCropApply(rect: { x: number; y: number; width: number; height: number } | null) {
  const index = cropEditorIndex.value
  if (index === null) return
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _crop: rect }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'crop')
}

watch(cropEditorOpen, (open) => {
  if (!open) {
    cropEditorIndex.value = null
    cropEditorImage.value = null
  }
})

// --- Paint Editor ---

const paintEditorIndex = ref<number | null>(null)
// Stable snapshot of the base image — set once when editor opens, never changes during editing
const paintEditorImage = ref<{ path: string; hash?: string; mediaId?: number; width?: number; height?: number } | null>(null)

async function openPaintEditor(index: number) {
  const item = items.value[index]
  if (!item) return

  // If we have a server-side paint layer but no data URL (e.g., after reload), load it
  if (item._paintLayerPath && !item._paintLayerDataUrl) {
    try {
      const base = getApiBase()
      const profileId = getCurrentProfileId()
      const pin = getCachedPin(profileId)
      let url = `${base}/generate/reference-file?path=${encodeURIComponent(item._paintLayerPath)}&profile=${encodeURIComponent(profileId)}`
      if (pin) url += `&pin=${encodeURIComponent(pin)}`
      const resp = await fetch(url)
      if (resp.ok) {
        const blob = await resp.blob()
        const dataUrl = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onloadend = () => resolve(reader.result as string)
          reader.readAsDataURL(blob)
        })
        const newItems = [...items.value]
        newItems[index] = { ...items.value[index], _paintLayerDataUrl: dataUrl }
        items.value = newItems
        emit('update:modelValue', newItems)
      }
    } catch (e) {
      console.warn('[MediaPicker] Failed to load paint layer from server:', e)
    }
  }

  // Re-read item after potential update
  const current = items.value[index]
  if (!current) return

  // Snapshot the base image for this editing session
  if (current._basePath) {
    paintEditorImage.value = {
      path: current._basePath,
      width: current._baseWidth || current.width,
      height: current._baseHeight || current.height,
    }
  } else if (current._originalPath && (hasScale(current) || !!current._preprocessor || hasExtendPadding(current))) {
    paintEditorImage.value = {
      path: current.path,
      width: current.width,
      height: current.height,
    }
  } else {
    paintEditorImage.value = {
      path: current._originalPath || current.path,
      hash: current._originalHash || current.hash,
      mediaId: current.mediaId,
      width: current.width,
      height: current.height,
    }
  }

  paintEditorIndex.value = index
}

function onPaintLayerUpdate(dataUrl: string | null) {
  if (paintEditorIndex.value === null) return
  const index = paintEditorIndex.value
  const item = items.value[index]
  if (!item) return

  const newItems = [...items.value]
  // Clear the uploaded path since the paint layer changed
  newItems[index] = { ...item, _paintLayerDataUrl: dataUrl, _paintLayerPath: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  // Don't preprocess while editor is open — defer until close
}

function closePaintEditor() {
  const index = paintEditorIndex.value
  paintEditorIndex.value = null
  paintEditorImage.value = null
  if (index !== null) {
    applyFullPreprocessing(index, 'paint')
  }
}

function revertPaint(index: number) {
  const item = items.value[index]
  if (!item) return
  const newItems = [...items.value]
  newItems[index] = { ...item, _paintLayerDataUrl: null, _paintLayerPath: null }
  items.value = newItems
  emit('update:modelValue', newItems)
  applyFullPreprocessing(index, 'paint')
}

function removeItem(index: number) {
  const newItems = [...items.value]
  newItems.splice(index, 1)
  items.value = newItems
  emit('update:modelValue', newItems)
}

function clearItems() {
  items.value = []
  emit('update:modelValue', [])
}

// ──────────────────────────────────────────────────────────────────────────
// Command surface for the mini-agent (called by ToolView.runTool). These wrap
// the same handlers a user click triggers — they mutate metadata AND run the
// server-side pipeline (applyFullPreprocessing) where needed. Index validity is
// checked by ToolView before delegating, but we re-guard here.
// ──────────────────────────────────────────────────────────────────────────

function imageCount(): number {
  return items.value.length
}

async function agentFlip(index: number, axis: 'horizontal' | 'vertical'): Promise<string> {
  if (!items.value[index]) return `No image at index ${index} (there are ${items.value.length}).`
  toggleFlip(index, axis)
  const on = !!items.value[index]?._flip?.[axis]
  return `Flipped image ${index} ${axis} ${on ? 'on' : 'off'}.`
}

async function agentRotate(index: number, direction: 'left' | 'right'): Promise<string> {
  if (!items.value[index]) return `No image at index ${index} (there are ${items.value.length}).`
  rotate(index, direction)
  const rot = ((items.value[index]?._flip?.rotation ?? 0) % 360 + 360) % 360
  return `Rotated image ${index} ${direction} (now ${rot}°).`
}

async function agentResetTransforms(index: number): Promise<string> {
  const item = items.value[index]
  if (!item) return `No image at index ${index} (there are ${items.value.length}).`
  // Clear all transform metadata, then re-run the pipeline once to restore original.
  const newItems = [...items.value]
  newItems[index] = {
    ...item,
    _flip: null,
    _crop: null,
    _scale: null,
    _extendPadding: null,
    _extendBgColor: null,
    _preprocessor: null,
    _preprocessorParams: undefined,
  }
  items.value = newItems
  emit('update:modelValue', newItems)
  await applyFullPreprocessing(index, 'preprocess')
  return `Reset all transforms on image ${index}.`
}

async function agentCrop(
  index: number,
  args: { x?: number; y?: number; width?: number; height?: number; rotation?: number },
): Promise<string> {
  const item = items.value[index]
  if (!item) return `No image at index ${index} (there are ${items.value.length}).`
  const rotation = Math.max(-45, Math.min(45, Math.round(Number(args.rotation ?? 0) * 10) / 10)) || 0
  const rect: NonNullable<MediaItem['_crop']> = {
    x: Math.max(0, Math.min(1, Number(args.x ?? 0))),
    y: Math.max(0, Math.min(1, Number(args.y ?? 0))),
    width: Math.max(0.02, Math.min(1, Number(args.width ?? 1))),
    height: Math.max(0.02, Math.min(1, Number(args.height ?? 1))),
    ...(rotation !== 0 ? { rotation } : {}),
  }
  rect.width = Math.min(rect.width, 1 - rect.x)
  rect.height = Math.min(rect.height, 1 - rect.y)
  const fullFrame = rect.x <= 0.0005 && rect.y <= 0.0005 && rect.width >= 0.999 && rect.height >= 0.999
    && rotation === 0
  const newItems = [...items.value]
  newItems[index] = { ...item, _crop: fullFrame ? null : rect }
  items.value = newItems
  emit('update:modelValue', newItems)
  await applyFullPreprocessing(index, 'crop')
  return fullFrame
    ? `Cleared crop on image ${index}.`
    : `Cropped image ${index} to ${getCropStatusText(items.value[index])}.`
}

async function agentPreprocess(index: number, preprocessor: string): Promise<string> {
  if (!items.value[index]) return `No image at index ${index} (there are ${items.value.length}).`
  if (!hasControlnet.value) return 'This tool does not support ControlNet preprocessors.'
  const pp = preprocessor === 'none' ? null : preprocessor
  if (pp && !props.controlnetOptions.includes(pp)) {
    return `Preprocessor "${pp}" not available. Options: ${props.controlnetOptions.join(', ') || 'none'}.`
  }
  await applyPreprocessor(index, pp)
  return pp ? `Applied "${pp}" preprocessor to image ${index}.` : `Cleared preprocessor on image ${index}.`
}

async function agentScale(
  index: number,
  args: { mode: ScaleMode; factor?: number; megapixels?: number; width?: number; height?: number },
): Promise<string> {
  const item = items.value[index]
  if (!item) return `No image at index ${index} (there are ${items.value.length}).`
  const newItems = [...items.value]
  if (args.mode === 'factor') {
    newItems[index] = { ...item, _scale: { mode: 'factor', factor: args.factor ?? 1 } }
  } else if (args.mode === 'megapixels') {
    newItems[index] = { ...item, _scale: { mode: 'megapixels', megapixels: args.megapixels ?? origMegapixels(item) } }
  } else if (args.mode === 'manual') {
    const { w, h } = croppedDims(item)
    newItems[index] = { ...item, _scale: { mode: 'manual', width: args.width ?? w, height: args.height ?? h } }
  } else {
    return `Invalid scale mode "${args.mode}". Use factor, megapixels, or manual.`
  }
  items.value = newItems
  emit('update:modelValue', newItems)
  await applyFullPreprocessing(index, 'scale')
  return `Scaled image ${index} (${getScaleStatusText(items.value[index])}).`
}

async function agentExtend(
  index: number,
  args: { top?: number; bottom?: number; left?: number; right?: number; bg_color?: string },
): Promise<string> {
  const item = items.value[index]
  if (!item) return `No image at index ${index} (there are ${items.value.length}).`
  const padding = {
    top: args.top ?? item._extendPadding?.top ?? 0,
    bottom: args.bottom ?? item._extendPadding?.bottom ?? 0,
    left: args.left ?? item._extendPadding?.left ?? 0,
    right: args.right ?? item._extendPadding?.right ?? 0,
  }
  const newItems = [...items.value]
  newItems[index] = {
    ...item,
    _extendPadding: padding,
    _extendBgColor: args.bg_color ?? item._extendBgColor ?? null,
  }
  items.value = newItems
  emit('update:modelValue', newItems)
  emitExtendedResolution()
  await applyFullPreprocessing(index, 'extend')
  return `Extended canvas on image ${index} (${getExtendStatusText(items.value[index])}).`
}

defineExpose({
  imageCount,
  flipImage: agentFlip,
  rotateImage: agentRotate,
  resetImageTransforms: agentResetTransforms,
  preprocessImage: agentPreprocess,
  scaleImage: agentScale,
  extendImage: agentExtend,
  cropImage: agentCrop,
})
</script>
