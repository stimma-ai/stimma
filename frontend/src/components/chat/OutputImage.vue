<template>
  <!-- Output image container: always square with letterboxing (v2) -->
  <div
    class="rounded overflow-hidden flex-shrink-0 relative group"
    :style="containerStyle"
    :class="{
      'bg-base flex items-center justify-center': row.output.status === 'pending' || row.output.status === 'generating',
      'cursor-pointer': (row.output.status === 'complete' || row.output.status === 'trashed') && !isTrashed && !row.output.deleted,
      'bg-red-500/10 flex flex-col items-center justify-center': row.output.status === 'failed' || row.output.status === 'cancelled'
    }"
    @click="handleClick"
    @mouseenter="startHoverVideo"
    @mouseleave="stopHoverVideo"
  >
    <!-- Generating spinner -->
    <div
      v-if="row.output.status === 'pending' || row.output.status === 'generating'"
      class="relative w-full h-full flex items-center justify-center"
    >
      <!-- Pulse dot and thin bar on the matte, never a spinner (DESIGN.md §3.3) -->
      <div class="flex w-2/5 flex-col items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full animate-pulse-soft" :class="row.output.status === 'generating' ? 'bg-blue-500' : 'bg-zinc-500'"></span>
        <div v-if="row.output.progress" class="h-0.5 w-full overflow-hidden rounded-full bg-overlay-medium">
          <div
            class="h-full bg-blue-500 transition-all"
            :style="{ width: `${row.output.progress}%` }"
          ></div>
        </div>
      </div>
      <!-- Cancel button on hover -->
      <button
        @click.stop="$emit('cancel', row.id)"
        class="absolute top-1 right-1 p-1 bg-surface/80 hover:bg-red-500/20 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="Cancel"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 text-content-tertiary hover:text-red-500">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Permanently Deleted -->
    <template v-if="row.output.deleted">
      <div class="w-full h-full bg-surface flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-8 h-8 text-content-muted">
          <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
        </svg>
      </div>
    </template>

    <!-- Complete: workspace file (no media_id, served via workspace URL) -->
    <template v-else-if="row.output.status === 'complete' && row.output.workspace_url && !row.output.media_id">
      <img
        :src="workspaceImageSrc"
        class="w-full h-full object-contain"
        loading="lazy"
      />
    </template>

    <!-- Complete or Trashed (trashed items still viewable) -->
    <template v-else-if="(row.output.status === 'complete' || row.output.status === 'trashed') && row.output.media_id">
      <!-- A set is drawn from its own members on the matte (SetStackPreview).
           A grid arrives with a backdrop baked in by the server (light: the
           surface token; dark: neutral 24, which no token matches), and the
           set's baked thumbnail is the fallback when no member can be read;
           matching it keeps the picture and what surrounds it one matte. The
           gutters keep the parent's chips off the artwork. -->
      <div class="absolute inset-x-0" :style="{ top: `${gutterTop}px`, bottom: `${gutterBottom}px` }">
        <SetStackPreview
          v-if="outputMediaType === 'set' && !stackUnavailable"
          :media-id="row.output.media_id"
          @unavailable="stackUnavailable = true"
        />
        <MediaImage
          v-else
          :media-id="row.output.media_id"
          :thumbnail="effectiveThumbnail"
          :thumbnail-size="effectiveThumbnail ? (fitThumbnail || 512) : undefined"
          :thumbnail-mode="fitThumbnail ? 'fit' : 'crop'"
          :background-class="isComposite ? 'bg-matte' : 'bg-matte'"
          :contain="true"
          container-class="w-full h-full"
        />
      </div>

      <video
        v-if="videoStarted"
        :key="row.output.media_id"
        ref="videoRef"
        :src="videoSrc"
        playsinline
        :muted="videoPreview"
        :loop="videoPreview"
        preload="metadata"
        class="pointer-events-none absolute inset-0 h-full w-full bg-matte object-contain"
        @play="videoPlaying = true"
        @pause="videoPlaying = false"
        @ended="videoPlaying = false"
        @error="videoError = !videoPreview; videoPlaying = false"
        @contextmenu.prevent="openVideoMenu"
      />
      <!-- Artwork keeps the collection's primary click: open the slideshow. -->
      <div
        v-if="canPlayVideo"
        data-video-surface
        class="absolute inset-0"
        draggable="true"
        @dragstart="onVideoDragStart"
        @dragend="handleDragEnd"
        @contextmenu.prevent="openVideoMenu"
      />
      <IconButton
        v-if="canPlayVideo"
        data-video-playback
        :aria-label="videoPlaying && !videoPreview ? 'Pause video' : 'Play video'"
        :title="videoPlaying && !videoPreview ? 'Pause video' : 'Play video'"
        class="absolute bottom-2 left-1/2 z-chrome -translate-x-1/2 !bg-black/55 backdrop-blur transition-opacity duration-150 hover:!bg-black/75 focus-visible:opacity-100 group-hover:opacity-100 coarse:opacity-100"
        :class="videoPlaying && !videoPreview ? 'opacity-100 !text-live' : 'opacity-0 !text-white'"
        @click.stop="toggleVideo"
      >
        <PauseIcon v-if="videoPlaying && !videoPreview" class="h-4 w-4" />
        <PlayIcon v-else class="h-4 w-4" />
      </IconButton>
      <span v-if="videoError" role="status" class="pointer-events-none absolute inset-x-2 bottom-2 bg-matte/90 p-2 text-center text-xs text-content-secondary">Unable to play this video. Try opening it in the slideshow.</span>

      <!-- Type chip (upper right): the browse TileChip, monochrome glyph, mono member count for sets and grids -->
      <div v-if="outputMediaType && outputMediaType !== 'image' && !(hideCountChip && isComposite)" class="absolute top-1.5 right-1.5 z-chrome" :style="insetRight ? { right: `${insetRight}px` } : null">
        <TileChip>
          <!-- Audio icon (music note) -->
          <svg v-if="outputMediaType === 'audio'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2z" />
          </svg>
          <!-- Text icon (document) -->
          <svg v-else-if="outputMediaType === 'text'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <!-- Set icon (layers) -->
          <svg v-else-if="outputMediaType === 'set'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
          </svg>
          <!-- Grid icon -->
          <svg v-else-if="outputMediaType === 'grid'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
          </svg>
          <FilmIcon v-else-if="outputMediaType === 'video'" aria-label="Video" />
          <!-- Sprite icon (film frame) -->
          <svg v-else-if="outputMediaType === 'sprite'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 0 1-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m0 0h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125m1.5 3.75C5.496 15.75 6 15.246 6 14.625v-1.5m-3.75 0h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125m0 0h1.5m0 0c.621 0 1.125.504 1.125 1.125v1.5m-1.5-3.75C5.496 8.25 6 7.746 6 7.125v-1.5M4.875 8.25C4.254 8.25 3.75 7.746 3.75 7.125v-1.5m0 0c0-.621.504-1.125 1.125-1.125h1.5C6.996 4.5 7.5 5.004 7.5 5.625v1.5m0 0v10.5m0-10.5h9m-9 10.5h9m0 0v-10.5m0 10.5c0 .621.504 1.125 1.125 1.125h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5m1.5 2.625c.621 0 1.125-.504 1.125-1.125v-1.5m0 0h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125m0 0h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125m0 0h1.5m0 0c.621 0 1.125.504 1.125 1.125v1.5m-1.5-3.75C18.504 8.25 18 7.746 18 7.125v-1.5m1.125 2.625h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125h1.5c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125" />
          </svg>
          <!-- Package icon (archive box) -->
          <svg v-else-if="outputMediaType === 'package'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
          </svg>
          <!-- Layout icon (newspaper) -->
          <svg v-else-if="outputMediaType === 'layout'" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
          </svg>
          <span v-if="(outputMediaType === 'set' || outputMediaType === 'grid') && memberCount">{{ memberCount }}</span>
        </TileChip>
      </div>

      <!-- Trashed badge (upper left) - yellow trash icon -->
      <div v-if="isTrashed" :style="insetLeft ? { left: `${insetLeft}px` } : null" class="absolute top-1.5 left-1.5 z-chrome bg-black/60 backdrop-blur-md rounded px-1.5 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3.5 h-3.5 text-amber-400">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
      </div>

      <!-- Auto-delete time remaining badge (upper left, only if not trashed) -->
      <div v-else-if="formattedRemainingTime" :style="insetLeft ? { left: `${insetLeft}px` } : null" class="absolute top-1.5 left-1.5 z-chrome bg-black/60 backdrop-blur-md rounded px-1.5 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-amber-400">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
        <span class="text-[10px] font-semibold text-amber-400 leading-none whitespace-nowrap">{{ formattedRemainingTime }}</span>
      </div>

      <!-- Marker toggle buttons (bottom left) -->
      <div v-if="!isTrashed && availableMarkers.length > 0" class="absolute bottom-2 left-2 z-chrome flex gap-0.5" :style="insetBottom ? { bottom: `${insetBottom}px` } : null">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          @click.stop="toggleMarker(row.output.media_id, marker)"
          :class="[
            'w-7 h-7 coarse:w-11 coarse:h-11 rounded-md flex items-center justify-center transition-colors',
            hasMarker(row.output.media_id, marker.id)
              ? (isComposite ? 'bg-overlay-light' : 'bg-black/70')
              : (isComposite ? 'text-content-tertiary hover:bg-overlay-light hover:text-content' : 'text-white/85 [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.7))] hover:bg-black/55 hover:text-white hover:[filter:none]'),
            quietMarkers && !hasMarker(row.output.media_id, marker.id) ? 'opacity-0 group-hover:opacity-100 [[data-pointer=coarse]_&]:hidden' : ''
          ]"
          :style="hasMarker(row.output.media_id, marker.id) ? { color: marker.color } : {}"
          :title="hasMarker(row.output.media_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
        >
          <span class="w-4 h-4 flex items-center justify-center icon-container" :class="hasMarker(row.output.media_id, marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
        </button>
      </div>

      <!-- Bottom right controls: info button -->
      <div class="absolute bottom-2 right-2 z-chrome flex gap-1 items-center" :style="insetBottom ? { bottom: `${insetBottom}px` } : null">
        <!-- Info button (visible on hover) -->
        <button
          v-if="row.output.job_id"
          @click.stop="$emit('show-job-info', row.output.job_id)"
          class="w-6 h-6 flex items-center justify-center bg-black/60 backdrop-blur-md hover:bg-blue-500/80 rounded text-content-secondary hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="Show generation info"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </template>

    <!-- Failed -->
    <template v-else-if="row.output.status === 'failed'">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-red-500 mb-1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
      </svg>
      <div class="text-xs text-red-500 mb-1">Failed</div>
      <div v-if="row.output.error_summary" class="text-[10px] text-red-400 mb-1 px-2 text-center leading-tight line-clamp-3">{{ row.output.error_summary }}</div>
      <details v-if="row.output.error && row.output.error !== row.output.error_summary" class="w-full px-1 mb-1" @click.stop>
        <summary class="text-[10px] cursor-pointer text-red-400/70 hover:text-red-400 select-none text-center">Details</summary>
        <pre class="mt-1 text-[9px] whitespace-pre-wrap break-words font-mono bg-red-500/10 rounded p-1 max-h-20 overflow-y-auto custom-scrollbar text-red-400/80 select-text">{{ row.output.error }}</pre>
      </details>
      <button
        @click.stop="$emit('retry', row.id)"
        class="px-2 py-0.5 text-xs bg-surface-raised hover:bg-surface-hover text-content rounded transition-colors"
      >
        Retry
      </button>
    </template>

    <!-- Cancelled -->
    <template v-else-if="row.output.status === 'cancelled'">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-red-500 mb-1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
      </svg>
      <div class="text-xs text-red-500">Cancelled</div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useManagedMediaElement } from '../../composables/useMediaPlayback'
import IconButton from '../ui/IconButton.vue'
import { FilmIcon, PauseIcon, PlayIcon } from '@heroicons/vue/24/outline'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'
import { useViewport } from '../../composables/useViewport'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'

import { MediaImage, TileChip } from '../media'
import SetStackPreview from './SetStackPreview.vue'
import { workspaceMediaUrl } from '../../utils/workspaceMediaUrl'
import { useMarkers } from '../../composables/useMarkers'
import { useMediaState } from '../../composables/useMediaState'
import { useExpirationClock } from '../../composables/useExpirationClock'
import { getMediaType } from '../../utils/mediaTypes'
import { useMediaApi } from '../../composables/useMediaApi'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps({
  row: {
    type: Object,
    required: true
  },
  size: {
    type: Number,
    default: 240
  },
  // Fill the parent's width (square letterbox preserved via aspect-ratio) instead of a fixed pixel size
  fill: {
    type: Boolean,
    default: false
  },
  playable: { type: Boolean, default: false },
  useThumbnail: {
    type: Boolean,
    default: true
  },
  // Show a whole-image thumbnail of this size, even for a confirmed image.
  fitThumbnail: {
    type: Number,
    default: null
  },
  // Unset markers wait for hover; on touch they live on the opened picture.
  quietMarkers: {
    type: Boolean,
    default: false
  },
  // Room for controls the parent lays over the tile.
  insetLeft: { type: Number, default: 0 },
  insetRight: { type: Number, default: 0 },
  insetBottom: { type: Number, default: 0 },
  // Bands kept clear of the artwork, for chips the parent lays above and below it.
  gutterTop: { type: Number, default: 0 },
  // The parent shows a set's or grid's member count itself.
  hideCountChip: { type: Boolean, default: false },
  gutterBottom: { type: Number, default: 0 }
})

const emit = defineEmits(['view-image', 'retry', 'cancel', 'show-job-info'])
const { formatRemainingTime } = useExpirationClock()

const containerStyle = computed(() =>
  props.fill
    ? (props.playable ? { width: '100%', height: '100%', aspectRatio: 'auto' } : { width: '100%', aspectRatio: '1 / 1' })
    : { width: `${props.size}px`, height: `${props.size}px` }
)

const workspaceImageSrc = computed(() => workspaceMediaUrl(props.row.output.workspace_url))

// Use shared markers composable
const {
  availableMarkers,
  init: initMarkers,
  loadMarkersForMedia,
  hasMarker,
  toggleMarker
} = useMarkers()

// Use shared media state composable for auto_delete_at and deleted_at
const {
  mediaState,
  init: initMediaState,
  loadStateForMedia
} = useMediaState()

// Initialize on mount
onMounted(async () => {
  initMediaState()
  await initMarkers()
  // Load markers and media state for this media if complete
  const isComplete = props.row.output.status === 'complete' || props.row.output.status === 'trashed'
  if (isComplete && props.row.output.media_id) {
    await Promise.all([
      loadMarkersForMedia([props.row.output.media_id]),
      loadStateForMedia([props.row.output.media_id])
    ])
  }
})

// Load markers and media state when media_id becomes available (e.g., after generation completes)
watch(
  () => props.row.output.media_id,
  async (newMediaId) => {
    const isComplete = props.row.output.status === 'complete' || props.row.output.status === 'trashed'
    if (newMediaId && isComplete) {
      await Promise.all([
        loadMarkersForMedia([newMediaId]),
        loadStateForMedia([newMediaId])
      ])
    }
  }
)

// Get current media state (reactive via shared composable)
const currentMediaState = computed(() => {
  if (!props.row.output.media_id) return null
  return mediaState.value[props.row.output.media_id] || null
})

// Computed for auto-delete time display (from media state or row data)
const formattedRemainingTime = computed(() => {
  // Prefer shared media state, fall back to row data
  const autoDeleteAt = currentMediaState.value
    ? currentMediaState.value.auto_delete_at
    : props.row.output.auto_delete_at
  if (!autoDeleteAt) return null
  const result = formatRemainingTime(autoDeleteAt)
  // Don't show if already expired
  if (result === '0m') return null
  return result
})

// Check if the image is trashed (from media state or row status)
const isTrashed = computed(() => {
  // If we have media state, check deleted_at
  if (currentMediaState.value) {
    return !!currentMediaState.value.deleted_at
  }
  // Fall back to row status
  return props.row.output.status === 'trashed'
})

// Get the media type for badge display
const outputMediaType = computed(() => {
  // Check if we have file_format from media state or row output
  const fileFormat = currentMediaState.value?.file_format || props.row.output.file_format
  if (!fileFormat) return null
  return getMediaType({ file_format: fileFormat })
})

// Set when a set has no member to draw its own stack from.
const stackUnavailable = ref(false)

const isComposite = computed(() => outputMediaType.value === 'set' || outputMediaType.value === 'grid')

// Sets and grids show their member count on the type chip, as browse tiles do.
const { getMediaItem } = useMediaApi()
const memberCount = ref(0)
watch(
  () => [isComposite.value, props.row.output.media_id],
  async ([composite, mediaId]) => {
    if (!composite || !mediaId) return
    try {
      const item = await getMediaItem(mediaId, { includeTrashed: true })
      if (props.row.output.media_id === mediaId) memberCount.value = item?.member_count || 0
    } catch { /* the chip just omits the count */ }
  },
  { immediate: true }
)

// Force thumbnail mode for composite media (grids, sets) whose raw files are JSON, not images.
// Default to thumbnail until we know the type — safe because chat tiles top out around the
// 512px thumbnail size.
const ATOMIC_IMAGE_TYPES = new Set(['image'])
const effectiveThumbnail = computed(() => {
  if (props.useThumbnail || props.fitThumbnail) return true
  // Only use full-res file when we've confirmed it's a regular image
  if (outputMediaType.value && ATOMIC_IMAGE_TYPES.has(outputMediaType.value)) return false
  return true
})

const videoRef = ref(null)
useManagedMediaElement(videoRef)
const videoStarted = ref(false)
const videoPlaying = ref(false)
const videoPreview = ref(false)
const videoError = ref(false)
const { isCoarsePointer } = useViewport()
const { getMediaFileUrl, getThumbnailUrl } = useMediaApi()
const videoMenu = useMediaContextMenu()
const isPlayableVideo = computed(() => outputMediaType.value === 'video' && !isTrashed.value && !props.row.output.deleted && props.row.output.status === 'complete')
const canPlayVideo = computed(() => props.playable && isPlayableVideo.value)
const videoSrc = computed(() => getMediaFileUrl(props.row.output.media_id))
let hoverTimer
let playbackRequest = 0
async function playVideo(preview) {
  const request = ++playbackRequest
  videoPreview.value = preview
  videoStarted.value = true
  videoError.value = false
  await nextTick()
  const video = videoRef.value
  if (request !== playbackRequest || !video) return
  video.muted = preview
  try { await video.play() } catch {
    if (request === playbackRequest && !preview) videoError.value = true
  }
}
function toggleVideo() {
  clearTimeout(hoverTimer)
  if (videoPlaying.value && !videoPreview.value) {
    ++playbackRequest
    videoRef.value?.pause()
  } else {
    void playVideo(false)
  }
}
function startHoverVideo() {
  if (isCoarsePointer.value || !isPlayableVideo.value || videoStarted.value) return
  // Same dwell as the browser: passing across a tile never opens a decoder.
  hoverTimer = setTimeout(() => { void playVideo(true) }, 150)
}
function stopHoverVideo() {
  clearTimeout(hoverTimer)
  if (!videoPreview.value) return
  resetVideo()
}
function resetVideo() {
  clearTimeout(hoverTimer)
  ++playbackRequest
  videoRef.value?.pause()
  videoStarted.value = false
  videoPlaying.value = false
  videoPreview.value = false
  videoError.value = false
}
function onVideoDragStart(event) {
  const id = props.row.output.media_id
  createDragPreview(event, getThumbnailUrl(id, 128), id, props.row.output.file_format, true)
  event.dataTransfer?.setData('application/x-stimma-assets', JSON.stringify({
    items: [{ asset_id: props.row.output.asset_id ?? null, revision_id: null, media_id: id }],
  }))
}
function openVideoMenu(event) {
  videoMenu.show({ event, mediaId: props.row.output.media_id, assetId: props.row.output.asset_id })
}
watch(() => props.row.output.media_id, resetVideo)
onBeforeUnmount(resetVideo)
onDeactivated(resetVideo)

watch(isPlayableVideo, playable => { if (!playable) resetVideo() })

function handleClick() {
  // Don't allow clicking on deleted or trashed images
  if (props.row.output.deleted || isTrashed.value) return
  // Allow clicking on complete images
  if ((props.row.output.status === 'complete' || props.row.output.status === 'trashed') && props.row.output.media_id) {
    resetVideo()
    emit('view-image', props.row.output.media_id)
  }
}
</script>
