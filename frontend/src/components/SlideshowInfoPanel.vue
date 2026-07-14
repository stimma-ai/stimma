<template>
  <div
    class="bg-surface-elevated backdrop-blur-[10px] overflow-y-auto overflow-x-visible z-[10001] flex flex-col relative sidebar-scroll order-2 transition-all duration-300"
    :class="focusMode ? 'w-0 opacity-0 pointer-events-none border-l-0' : 'w-[384px] max-w-[90vw] border-l border-edge-subtle'"
  >
    <!-- Header: markers (pinned) -->
    <div v-if="currentItem && !isTrashView && !isCurrentItemTrashed && availableMarkers.length > 0" class="px-3 pt-3 pb-2 flex-shrink-0">
      <div class="flex flex-wrap gap-2" :key="'markers-' + markerUpdateTrigger">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          @click="toggleMarker(marker.id)"
          :class="[
            'p-2 rounded-lg border text-xs cursor-pointer transition-colors flex items-center',
            isMarkerActive(marker.id)
              ? ''
              : 'bg-overlay-faint border-edge-subtle text-content-tertiary hover:bg-overlay-light hover:text-content-secondary'
          ]"
          :style="isMarkerActive(marker.id) ? { backgroundColor: marker.color + '22', borderColor: marker.color + '66', color: marker.color } : {}"
          :title="marker.name"
        >
          <span v-html="sanitizeSvg(marker.icon_svg)" class="w-5 h-5 flex-shrink-0 icon-container"></span>
        </button>
      </div>
    </div>

    <div v-if="currentItem" class="p-3 overflow-y-auto overflow-x-hidden">
      <!-- Actions -->
      <h4 class="m-0 mb-2 text-xs uppercase tracking-wider text-content-tertiary font-semibold">Actions</h4>
      <div class="flex flex-col gap-1.5 mb-6">
        <template v-if="isTrashView || isCurrentItemTrashed">
          <button
            @click="$emit('restore')"
            class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-green-500/10 hover:border-green-500/50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-emerald-500">
              <path fill-rule="evenodd" d="M2 4.25A2.25 2.25 0 014.25 2h6.5A2.25 2.25 0 0113 4.25V5.5H9.25A3.75 3.75 0 005.5 9.25v6.08a3.75 3.75 0 01-3.5.67V4.25zM9.25 7A2.25 2.25 0 007 9.25v6.5A2.25 2.25 0 009.25 18h6.5A2.25 2.25 0 0018 15.75v-6.5A2.25 2.25 0 0015.75 7h-6.5z" clip-rule="evenodd" />
            </svg>
            <span>Restore</span>
          </button>
          <button
            @click="$emit('permanent-delete')"
            class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-red-500/10 hover:border-red-500/50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-red-500">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
            </svg>
            <span>Delete Permanently</span>
          </button>
        </template>
        <template v-else>
          <InspireMenu
            v-if="currentItem"
            :media-id="currentItem.id"
            @sent="$emit('menu-sent')"
            class="action-stack-wrap"
          />
          <SendToToolMenu
            v-if="currentItem"
            :media-item="currentItem"
            :media-type="currentMediaType"
            @sent="$emit('menu-sent')"
            class="action-stack-wrap"
          />
          <button
            v-if="currentItem"
            @click="$emit('share-to-cloud')"
            class="w-full bg-overlay-subtle border border-edge-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-overlay-light hover:border-edge"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-violet-500 flex-shrink-0">
              <path d="M13 4.5a2.5 2.5 0 1 1 .702 1.737L6.97 9.604a2.518 2.518 0 0 1 0 .792l6.733 3.367a2.5 2.5 0 1 1-.671 1.341l-6.733-3.367a2.5 2.5 0 1 1 0-3.475l6.733-3.366A2.52 2.52 0 0 1 13 4.5Z" />
            </svg>
            Share
          </button>
          <!-- Export (split button: Export opens modal, dropdown arrow for original) -->
          <div class="flex w-full gap-px">
            <button
              @click="$emit('download')"
              class="flex-1 bg-overlay-subtle border border-edge-subtle border-r-0 text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-l-lg text-xs font-medium transition-all hover:bg-overlay-light hover:border-edge"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-tertiary flex-shrink-0">
                <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
                <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
              </svg>
              Export
            </button>
            <button
              @click="$emit('download-original')"
              class="bg-overlay-subtle border border-edge-subtle border-l-0 text-content-tertiary cursor-pointer px-2 py-2 flex items-center rounded-r-lg text-xs transition-all hover:bg-overlay-light hover:text-content"
              title="Download original"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
                <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
                <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
              </svg>
            </button>
          </div>
          <button
            ref="moreButtonRef"
            @click.stop="openContextMenu($event)"
            class="w-full bg-overlay-subtle border border-edge-subtle text-content-secondary cursor-pointer px-3 py-2 flex items-center gap-2 rounded-lg text-xs font-medium transition-all hover:bg-overlay-light hover:text-content"
            title="More actions"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0">
              <path d="M3 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM8.5 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM15.5 8.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z" />
            </svg>
            More
          </button>
        </template>
      </div>

      <!-- Organization section -->
      <div class="mb-6">
        <h4 class="m-0 mb-2 text-xs uppercase tracking-wider text-content-tertiary font-semibold">Organization</h4>
        <div v-if="!isTrashView && !isCurrentItemTrashed" class="flex items-center gap-1.5 flex-wrap text-xs">
          <a
            v-for="project in mediaProjects"
            :key="'p-' + project.id"
            href="#"
            @click.prevent="$emit('navigate-to-project', project.id)"
            class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle border border-edge-subtle rounded text-content-secondary hover:bg-overlay-light hover:text-content transition-colors cursor-pointer no-underline"
          ><ArchiveBoxIcon class="w-3 h-3 text-content-muted" />{{ project.name || 'Untitled' }}</a>
          <a
            v-for="board in mediaBoards"
            :key="'b-' + board.id"
            href="#"
            @click.prevent="$emit('navigate-to-board', board.id)"
            class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle border border-edge-subtle rounded text-content-secondary hover:bg-overlay-light hover:text-content transition-colors cursor-pointer no-underline"
          ><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted"><path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v11.5A2.25 2.25 0 004.25 18h11.5A2.25 2.25 0 0018 15.75V4.25A2.25 2.25 0 0015.75 2H4.25zM3.5 4.25a.75.75 0 01.75-.75h5v6.5h-5.75V4.25zm0 7.25v4.25c0 .414.336.75.75.75h5v-5h-5.75zm7.25-7.75v6.5h5.75V4.25a.75.75 0 00-.75-.75h-5zm5.75 8h-5.75v5h5a.75.75 0 00.75-.75v-4.25z" clip-rule="evenodd" /></svg>{{ board.name || 'Untitled' }}</a>
          <button
            v-for="container in assetContainers"
            :key="`c-${container.asset_id}-${container.member_order}`"
            class="inline-flex items-center gap-1 rounded border border-white/10 bg-white/[0.05] px-2 py-0.5 text-xs text-content-secondary transition-colors hover:bg-white/10 hover:text-content"
            @click="$emit('navigate-to-source-media', container.media_id)"
          >
            <span class="grid h-3 w-3 grid-cols-2 gap-px">
              <span v-for="cell in 4" :key="cell" class="rounded-[1px] bg-content-muted"></span>
            </span>
            Used in {{ container.title || `Untitled ${container.asset_type}` }}
          </button>
          <template v-if="!editingTags">
            <a
              v-for="tag in (currentItem?.tags || [])"
              :key="tag.id"
              href="#"
              @click.prevent="$emit('filter-by-tag', tag.id)"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle border border-edge-subtle rounded text-content-secondary hover:bg-overlay-light hover:text-content transition-colors cursor-pointer no-underline"
            ><TagIcon class="w-3 h-3 text-content-muted" />{{ tag.tag }}</a>
            <button
              @click="editingTags = true"
              class="inline-flex items-center gap-1 px-2 py-0.5 border border-dashed border-edge-subtle rounded text-content-muted text-xs hover:bg-overlay-light hover:text-content-secondary hover:border-edge transition-colors cursor-pointer bg-transparent"
              title="Edit tags"
            ><TagIcon class="w-3 h-3" />+</button>
          </template>
        </div>
        <InlineTagEditor
          v-if="!isTrashView && !isCurrentItemTrashed && editingTags"
          :media-id="currentItem.id"
          :asset-id="currentItem.asset_id"
          :tags="currentItem?.tags || []"
          @close="editingTags = false"
          @tags-changed="handleInlineTagsChanged"
          class="mt-1.5"
        />
      </div>

      <!-- Auto-Delete Warning (hide in trash view or for trashed items) -->
      <div v-if="!isTrashView && !isCurrentItemTrashed && currentItem.expires_at && formatRemainingTime(currentItem.expires_at)" class="mb-4">
        <div :class="['p-3 rounded-lg border-2 flex items-start gap-2 relative', getRemainingTimeColor(currentItem.expires_at) === 'bg-red-500/80' ? 'bg-red-500/10 border-red-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-orange-500/80' ? 'bg-orange-500/10 border-orange-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-yellow-500/80' ? 'bg-yellow-500/10 border-yellow-500' : 'bg-gray-500/10 border-gray-500']">
          <button
            @click="removeAutoDelete"
            class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center rounded hover:bg-overlay-light transition-colors text-content-tertiary hover:text-content"
            title="Remove auto-delete"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" :class="['w-5 h-5 flex-shrink-0 mt-0.5', getRemainingTimeColor(currentItem.expires_at) === 'bg-red-500/80' ? 'text-red-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-orange-500/80' ? 'text-orange-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-yellow-500/80' ? 'text-yellow-400' : 'text-gray-400']">
            <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
          </svg>
          <div class="flex-1 pr-4">
            <div :class="['text-xs font-semibold mb-1', getRemainingTimeColor(currentItem.expires_at) === 'bg-red-500/80' ? 'text-red-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-orange-500/80' ? 'text-orange-500' : getRemainingTimeColor(currentItem.expires_at) === 'bg-yellow-500/80' ? 'text-yellow-400' : 'text-gray-400']">
              Auto-Delete in {{ formatRemainingTime(currentItem.expires_at) }}
            </div>
            <div class="text-xs text-content-tertiary">
              This image will be automatically moved to trash unless you tag, collect, or mark it.
            </div>
          </div>
        </div>
      </div>


      <!-- Chat Source (if generated via chat) -->
      <div v-if="currentItem.chat_item_id" class="mb-4">
        <h4 class="m-0 mb-2 text-xs uppercase tracking-wider text-content-tertiary font-semibold">Source</h4>
        <div class="space-y-2">
          <button
            v-if="chatInfo && !chatInfo.error"
            @click="$emit('jump-to-chat', chatInfo.id)"
            class="w-full flex items-center gap-2 px-3 py-2 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 rounded text-blue-500 hover:text-blue-600 text-sm transition-colors"
          >
            <ChatBubbleLeftRightIcon class="w-4 h-4" />
            <span class="truncate">{{ chatInfo.name }}</span>
            <ArrowTopRightOnSquareIcon class="w-3.5 h-3.5 ml-auto flex-shrink-0" />
          </button>
          <div
            v-else-if="chatInfo?.error === 'deleted'"
            class="flex items-center gap-2 px-3 py-2 bg-surface/50 border border-edge/50 rounded text-content-muted text-sm"
          >
            <ChatBubbleLeftRightIcon class="w-4 h-4" />
            <span>Chat deleted</span>
          </div>
          <div
            v-else-if="chatInfoLoading"
            class="flex items-center gap-2 px-3 py-2 bg-surface/50 border border-edge/50 rounded text-content-muted text-sm"
          >
            <span class="animate-pulse">Loading...</span>
          </div>
        </div>
      </div>

      <!-- Lineage (MOVED UP - now right after org/divider) -->
      <div v-if="effectiveGenerationHistory.length > 0" class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold flex items-center gap-2">
            Lineage
          </h4>
          <button
            class="text-[11px] text-content-secondary hover:text-content transition-colors flex items-center gap-1 bg-transparent border-none cursor-pointer"
            @click="$emit('view-lineage')"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" class="w-3 h-3">
              <circle cx="6" cy="4.5" r="1.75" stroke-width="1.5" />
              <circle cx="14" cy="4.5" r="1.75" stroke-width="1.5" />
              <circle cx="10" cy="15.5" r="1.75" stroke-width="1.5" />
              <path d="M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            View
          </button>
        </div>
        <div class="space-y-4">
          <!-- Each history step -->
          <div
            v-for="(step, idx) in effectiveGenerationHistory"
            :key="idx"
            class="border border-edge rounded-lg overflow-hidden"
          >
            <!-- Step Header -->
            <div class="bg-surface/50 px-3 py-2 flex items-center justify-between">
              <span class="text-content-secondary text-xs font-medium px-2 py-0.5 bg-overlay-subtle rounded">
                {{ getToolDisplayName(step) }}
              </span>
              <button
                @click.stop="openContextMenu($event)"
                class="p-1 text-content-tertiary hover:text-content hover:bg-overlay-light rounded transition-colors bg-transparent border-none cursor-pointer"
                title="More actions"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                  <path d="M10 3a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM10 8.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM11.5 15.5a1.5 1.5 0 10-3 0 1.5 1.5 0 003 0z" />
                </svg>
              </button>
            </div>

            <!-- Step Content -->
            <div class="p-3 space-y-3">
              <!-- Source Images for this step -->
              <div v-if="step.source_inputs?.length > 0" class="bg-overlay-subtle p-2 rounded">
                <div class="text-content-tertiary text-xs mb-2">Input Assets</div>
                <div class="flex flex-wrap gap-3">
                  <template v-for="(source, sourceIdx) in step.source_inputs" :key="sourceIdx">
                    <div v-if="source.media_id" class="flex flex-col">
                      <button
                        @click="source.preprocessor && getPreprocessedUrl(source) ? openExternalImageModal(getPreprocessedUrl(source), true) : $emit('navigate-to-source-media', source.media_id)"
                        class="relative w-32 h-32 rounded-lg overflow-hidden border border-edge hover:border-blue-500 transition-colors p-0 cursor-pointer"
                        :title="formatSourceRole(source.role)"
                      >
                        <!-- Preprocessed inputs show a derived preview URL, not the stored library asset. -->
                        <AppImage
                          v-if="source.preprocessor && getPreprocessedUrl(source)"
                          :src="getPreprocessedUrl(source)"
                          :alt="formatSourceRole(source.role)"
                          :contain="true"
                          container-class="w-full h-full"
                        />
                        <!-- Library asset: MediaImage so right-click menu + drag-drop work like everywhere else. -->
                        <MediaImage
                          v-else
                          :media-id="source.media_id"
                          :file-path="source.file_path"
                          :alt="formatSourceRole(source.role)"
                          :thumbnail-size="256"
                          :contain="true"
                          container-class="w-full h-full"
                        />
                        <div v-if="source.preprocessor || source.paint_layer || source.extend_padding || source.flip || source.crop" class="absolute top-1 right-1 flex flex-col gap-0.5 items-end">
                          <span v-if="source.preprocessor" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            {{ formatPreprocessor(source.preprocessor, source.preprocessor_params) }}
                          </span>
                          <span v-if="source.paint_layer" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Painted
                          </span>
                          <span v-if="source.extend_padding" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Extended
                          </span>
                          <span v-if="source.flip && formatFlip(source.flip)" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            {{ formatFlip(source.flip) }}
                          </span>
                          <span v-if="source.crop" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Cropped
                          </span>
                        </div>
                      </button>
                      <!-- Action row below thumbnail -->
                      <div class="flex justify-center gap-2 mt-1.5">
                        <template v-if="source.preprocessor && getPreprocessedUrl(source)">
                          <button
                            @click="openExternalImageModal(getPreprocessedUrl(source), true)"
                            class="text-content-secondary hover:text-content text-[10px] bg-transparent border-none cursor-pointer"
                          >
                            Processed
                          </button>
                          <span class="text-content-muted text-[10px]">|</span>
                          <button
                            @click="$emit('navigate-to-source-media', source.media_id)"
                            class="text-content-secondary hover:text-content text-[10px] bg-transparent border-none cursor-pointer"
                          >
                            Original
                          </button>
                        </template>
                        <template v-else>
                          <button
                            @click="$emit('navigate-to-source-media', source.media_id)"
                            class="text-content-secondary hover:text-content text-[10px] bg-transparent border-none cursor-pointer"
                          >
                            View
                          </button>
                        </template>
                        <span class="text-content-muted text-[10px]">|</span>
                        <button
                          @click="$emit('compare-with-source', source.media_id)"
                          class="text-content-secondary hover:text-content text-[10px] bg-transparent border-none cursor-pointer"
                        >
                          Compare
                        </button>
                      </div>
                    </div>
                    <div v-else class="flex flex-col">
                      <button
                        @click="openExternalImageModal(source.preprocessor && getPreprocessedUrl(source) ? getPreprocessedUrl(source) : source.file_path, !!getPreprocessedUrl(source))"
                        class="relative w-32 h-32 rounded-lg overflow-hidden border border-edge hover:border-amber-500 transition-colors bg-checker p-0 cursor-pointer"
                        :title="source.file_path"
                      >
                        <img
                          :src="source.preprocessor && getPreprocessedUrl(source) ? getPreprocessedUrl(source) : getReferenceFileUrl(source.file_path)"
                          :alt="formatSourceRole(source.role)"
                          class="w-full h-full object-contain"
                          @error="handleExternalImageError"
                        />
                        <div v-if="source.preprocessor || source.paint_layer || source.extend_padding || source.flip || source.crop" class="absolute top-1 right-1 flex flex-col gap-0.5 items-end">
                          <span v-if="source.preprocessor" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            {{ formatPreprocessor(source.preprocessor, source.preprocessor_params) }}
                          </span>
                          <span v-if="source.paint_layer" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Painted
                          </span>
                          <span v-if="source.extend_padding" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Extended
                          </span>
                          <span v-if="source.flip && formatFlip(source.flip)" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            {{ formatFlip(source.flip) }}
                          </span>
                          <span v-if="source.crop" class="px-2 py-1 bg-black/70 text-white text-[10px] rounded-full leading-none">
                            Cropped
                          </span>
                        </div>
                      </button>
                      <div class="flex justify-center mt-1.5">
                        <button
                          @click="openExternalImageModal(source.preprocessor && getPreprocessedUrl(source) ? getPreprocessedUrl(source) : source.file_path, !!getPreprocessedUrl(source))"
                          class="text-content-secondary hover:text-content text-[10px] bg-transparent border-none cursor-pointer"
                        >
                          View
                        </button>
                      </div>
                    </div>
                  </template>
                </div>
              </div>

              <!-- Prompt -->
              <div v-if="step.prompt" class="bg-overlay-subtle p-2 rounded">
                <div class="flex items-center justify-between mb-1">
                  <span class="text-content-tertiary text-xs">Prompt</span>
                  <button
                    @click="copyToClipboard(step.prompt)"
                    class="bg-transparent border-none text-content-tertiary cursor-pointer p-0.5 rounded hover:bg-overlay-light hover:text-content"
                  >
                    <ClipboardDocumentIcon class="w-3 h-3" />
                  </button>
                </div>
                <p class="text-content-secondary text-xs leading-relaxed m-0">{{ step.prompt }}</p>
              </div>

              <!-- Negative Prompt -->
              <div v-if="step.negative_prompt" class="bg-overlay-subtle p-2 rounded">
                <div class="flex items-center justify-between mb-1">
                  <span class="text-content-tertiary text-xs">Negative Prompt</span>
                  <button
                    @click="copyToClipboard(step.negative_prompt)"
                    class="bg-transparent border-none text-content-tertiary cursor-pointer p-0.5 rounded hover:bg-overlay-light hover:text-content"
                  >
                    <ClipboardDocumentIcon class="w-3 h-3" />
                  </button>
                </div>
                <p class="text-content-secondary text-xs leading-relaxed m-0">{{ step.negative_prompt }}</p>
              </div>

              <!-- Timestamp (standalone for generated items) -->
              <div v-if="step.generated_at && !step.is_imported" class="bg-overlay-subtle p-2 rounded">
                <div class="text-content-tertiary text-xs mb-0.5">Generated</div>
                <div class="text-content text-xs">{{ formatRelativeTime(step.generated_at) }}</div>
              </div>

              <!-- Parameters Grid (generic display of all params) -->
              <div class="grid grid-cols-2 gap-2 text-xs">
                <!-- Imported timestamp (in grid) -->
                <div v-if="step.generated_at && step.is_imported" class="bg-overlay-subtle p-2 rounded">
                  <div class="text-content-tertiary mb-0.5">Imported</div>
                  <div class="text-content">{{ formatRelativeTime(step.generated_at) }}</div>
                </div>
                <div v-if="step.model" class="bg-overlay-subtle p-2 rounded">
                  <div class="text-content-tertiary mb-0.5">Model</div>
                  <div class="text-content">{{ step.model }}</div>
                </div>
                <!-- Generic parameter display -->
                <div
                  v-for="param in getDisplayableStepParams(step.parameters)"
                  :key="param.label"
                  :class="['bg-overlay-subtle p-2 rounded', param.fullWidth ? 'col-span-2' : '']"
                >
                  <div class="text-content-tertiary mb-0.5">{{ param.label }}</div>
                  <div :class="['text-content', param.fullWidth ? 'break-all text-xs' : '']">{{ param.value }}</div>
                </div>
              </div>

              <!-- LoRAs (handle both 'loras' and legacy 'selected_loras' field names) -->
              <div v-if="(step.parameters?.loras || step.parameters?.selected_loras)?.length > 0" class="bg-overlay-subtle p-2 rounded">
                <div class="text-content-tertiary text-xs mb-1">LoRAs</div>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="(lora, loraIdx) in (step.parameters.loras || step.parameters.selected_loras)"
                    :key="loraIdx"
                    class="bg-overlay-subtle text-content-secondary px-2 py-0.5 rounded text-xs"
                  >
                    {{ getLoraDisplayName(lora) }} ({{ formatLoraWeight(lora.weight) }})
                  </span>
                </div>
              </div>

              <!-- Raw Metadata (opens modal for imported items) -->
              <div v-if="step.is_imported && step.raw_metadata" class="bg-overlay-subtle p-2 rounded">
                <div
                  class="text-content-tertiary text-xs cursor-pointer select-none flex justify-between items-center hover:text-content"
                  @click="openMetadataModal(step.raw_metadata)"
                >
                  <span>External Metadata</span>
                  <span class="text-[10px]">&#9654;</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Versions are saved states of this Asset; Media remains implementation detail. -->
      <div v-if="currentItem.asset_id && versions.length > 1" class="mb-6">
        <button
          class="flex w-full items-center justify-between bg-transparent p-0 text-left"
          @click="versionsExpanded = !versionsExpanded"
        >
          <h4 class="m-0 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            Versions <span class="normal-case tracking-normal text-content-muted">{{ versions.length }}</span>
          </h4>
          <span class="text-xs text-content-muted">{{ versionsExpanded ? 'Hide' : 'Show' }}</span>
        </button>
        <div v-if="versionsExpanded" class="mt-2 space-y-2">
          <div
            v-for="version in versions"
            :key="version.id"
            class="rounded-lg border p-2"
            :class="version.id === currentRevisionId ? 'border-blue-500/50 bg-blue-500/15' : 'border-white/10 bg-white/[0.05]'"
          >
            <div class="flex gap-2">
              <button
                class="h-14 w-14 flex-shrink-0 overflow-hidden rounded border border-white/10 bg-black/20 p-0"
                title="View this version"
                @click="$emit('navigate-to-source-media', version.media.id)"
              >
                <MediaImage
                  :media-id="version.media.id"
                  :file-hash="version.media.file_hash"
                  :thumbnail-size="128"
                  :contain="true"
                  container-class="h-full w-full"
                />
              </button>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2 text-xs">
                  <span class="font-medium text-content">Version {{ version.revision_number }}</span>
                  <span v-if="version.id === currentRevisionId" class="text-blue-400">Current</span>
                </div>
                <div class="mt-0.5 truncate text-[11px] text-content-muted">
                  {{ formatVersionDate(version.created_at) }}
                  <span v-if="version.parent_revision_id && version.parent_revision_id !== previousRevisionId(version)"> · branched</span>
                </div>
                <div class="mt-2 flex flex-wrap gap-1">
                  <button class="rounded bg-white/[0.05] px-2 py-1 text-[11px] text-content-secondary hover:bg-white/10" @click="$emit('navigate-to-source-media', version.media.id)">View</button>
                  <button v-if="isImageType(version.media)" class="rounded bg-white/[0.05] px-2 py-1 text-[11px] text-content-secondary hover:bg-white/10" @click="$emit('edit-image', version.media.id)">Edit from</button>
                  <button class="rounded bg-white/[0.05] px-2 py-1 text-[11px] text-content-secondary hover:bg-white/10" @click="$emit('download-version', version.media.id)">Export</button>
                  <button
                    v-if="version.id !== currentRevisionId"
                    class="rounded px-2 py-1 text-[11px]"
                    :class="confirmRestoreId === version.id ? 'bg-blue-500 text-white' : 'bg-white/[0.05] text-content-secondary hover:bg-white/10'"
                    @click="requestRestore(version)"
                  >{{ confirmRestoreId === version.id ? 'Confirm restore' : 'Restore as latest' }}</button>
                </div>
              </div>
            </div>
          </div>
          <button
            class="w-full rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2 text-xs text-content-secondary hover:bg-white/10 hover:text-content"
            @click="$emit('download-versions', versions.map(version => version.media.id))"
          >Export all versions</button>
        </div>
      </div>

      <!-- Made From This (descendants/derivatives) -->
      <div v-if="descendants.length > 0" class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">
            Made From This
          </h4>
          <button
            class="text-xs text-content-secondary hover:text-content transition-colors flex items-center gap-1"
            @click="$emit('view-lineage')"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" class="w-3 h-3">
              <circle cx="6" cy="4.5" r="1.75" stroke-width="1.5" />
              <circle cx="14" cy="4.5" r="1.75" stroke-width="1.5" />
              <circle cx="10" cy="15.5" r="1.75" stroke-width="1.5" />
              <path d="M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            View Lineage
          </button>
        </div>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            v-for="descendant in descendants"
            :key="descendant.id"
            :media-id="descendant.id"
            :file-hash="descendant.file_hash"
            :thumbnail-size="128"
            container-class="w-16 h-16 rounded overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', descendant.id)"
          />
        </div>
      </div>

      <!-- Remixes (images that were remixed from this one) -->
      <div v-if="inspiredDescendants.length > 0" class="mb-6">
        <h4 class="m-0 mb-3 text-xs uppercase tracking-wider text-content-tertiary font-semibold">
          Remixes
        </h4>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            v-for="descendant in inspiredDescendants"
            :key="descendant.id"
            :media-id="descendant.id"
            :file-hash="descendant.file_hash"
            :thumbnail-size="128"
            container-class="w-16 h-16 rounded overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', descendant.id)"
          />
        </div>
      </div>

      <!-- Remix Of (the source that this image was remixed from) -->
      <div v-if="inspiredByInfo" class="mb-6">
        <h4 class="m-0 mb-3 text-xs uppercase tracking-wider text-content-tertiary font-semibold">
          Remix Of
        </h4>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            :media-id="inspiredByInfo.media_id"
            :thumbnail-size="128"
            container-class="w-16 h-16 rounded overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', inspiredByInfo.media_id)"
          />
        </div>
      </div>

      <!-- Prompt (only show if no generation history) -->
      <div v-if="currentItem.extracted_prompt && effectiveGenerationHistory.length === 0" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-sm uppercase tracking-wider text-content-tertiary font-semibold flex items-center justify-between">
          <span>Prompt</span>
          <button
            @click="copyToClipboard(currentItem.extracted_prompt)"
            class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-overlay-light hover:text-content"
            title="Copy to clipboard"
          >
            <ClipboardDocumentIcon class="w-4 h-4" />
          </button>
        </h4>
        <p class="text-content-secondary text-sm leading-relaxed m-0">{{ currentItem.extracted_prompt }}</p>
      </div>

      <!-- AI Description -->
      <div v-if="currentItem.vlm_caption && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-sm uppercase tracking-wider text-content-tertiary font-semibold flex items-center justify-between">
          <span>AI Description</span>
          <button
            @click="copyToClipboard(currentItem.vlm_caption)"
            class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-overlay-light hover:text-content"
            title="Copy to clipboard"
          >
            <ClipboardDocumentIcon class="w-4 h-4" />
          </button>
        </h4>
        <p class="text-content-secondary text-sm leading-relaxed m-0">{{ currentItem.vlm_caption }}</p>
      </div>

      <!-- Detected Faces -->
      <div v-if="faces.length > 0" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-sm uppercase tracking-wider text-content-tertiary font-semibold">
          Detected Faces ({{ faces.length }})
        </h4>
        <div class="grid grid-cols-1 gap-2">
          <div v-for="(face, index) in faces" :key="face.id"
               class="bg-overlay-subtle p-2 rounded">
            <div class="text-xs space-y-1">
              <div class="flex justify-between items-center mb-1">
                <span class="text-content font-semibold">Face {{ index + 1 }}</span>
                <div class="flex items-center gap-2">
                  <button
                    @click="toggleFaceOverlay(face.id)"
                    :class="[
                      'bg-transparent border-none p-1 rounded cursor-pointer transition-all',
                      visibleFaceOverlays.has(face.id) ? 'text-green-500 hover:text-green-500' : 'text-content-tertiary hover:text-content'
                    ]"
                    :title="visibleFaceOverlays.has(face.id) ? 'Hide face overlay' : 'Show face overlay'"
                  >
                    <EyeIcon class="w-4 h-4" />
                  </button>
                  <span class="text-content-tertiary">{{ (face.confidence * 100).toFixed(1) }}%</span>
                </div>
              </div>
              <div class="text-content-tertiary font-mono text-[0.65rem]">
                <div>x: {{ face.bbox.x.toFixed(3) }}, y: {{ face.bbox.y.toFixed(3) }}</div>
                <div>w: {{ face.bbox.width.toFixed(3) }}, h: {{ face.bbox.height.toFixed(3) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Keywords -->
      <div v-if="keywordsArray.length > 0 && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-sm uppercase tracking-wider text-content-tertiary font-semibold">Keywords</h4>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="keyword in keywordsArray"
            :key="keyword"
            @click="$emit('filter-by-keyword', keyword)"
            class="inline-block px-2 py-0.5 bg-overlay-light rounded-full text-xs text-content-secondary cursor-pointer transition-all border border-transparent hover:bg-green-500/30 hover:border-green-500 hover:-translate-y-px"
            :title="`Filter by '${keyword}'`"
          >
            {{ keyword }}
          </span>
        </div>
      </div>

      <!-- File -->
      <div class="mb-6">
        <h4 class="m-0 mb-2 text-xs uppercase tracking-wider text-content-tertiary font-semibold">File</h4>
        <div class="space-y-2">
          <div v-if="currentItem.file_path" class="bg-overlay-subtle p-2 rounded text-xs">
            <div class="text-content-tertiary mb-0.5">Name</div>
            <div class="text-content break-words text-xs">{{ currentItem.file_path.split('/').pop() }}</div>
          </div>
          <div v-if="currentItem.file_path" class="bg-overlay-subtle p-2 rounded text-xs">
            <div class="text-content-tertiary mb-0.5">Path</div>
            <div class="text-content-tertiary font-mono break-all text-xs">{{ currentItem.file_path }}</div>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Format</div>
              <div class="text-content text-xs">{{ formatFileFormat(currentItem.file_format) }}</div>
            </div>
            <div class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Size</div>
              <div class="text-content text-xs">{{ formatFileSize(currentItem.file_size) }}</div>
            </div>
            <div v-if="currentItem.width > 0 && currentItem.height > 0" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Resolution</div>
              <div class="text-content text-xs">{{ currentItem.width }} &times; {{ currentItem.height }}</div>
            </div>
            <div v-if="currentItem.duration" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Duration</div>
              <div class="text-content text-xs">{{ formatDuration(currentItem.duration) }}</div>
            </div>
            <div v-if="currentItem.audio_sample_rate" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Sample Rate</div>
              <div class="text-content text-xs">{{ formatSampleRate(currentItem.audio_sample_rate) }}</div>
            </div>
            <div v-if="currentItem.audio_bit_depth" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Bit Depth</div>
              <div class="text-content text-xs">{{ currentItem.audio_bit_depth }}-bit</div>
            </div>
            <div v-if="currentItem.audio_channels" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Channels</div>
              <div class="text-content text-xs">{{ formatChannels(currentItem.audio_channels) }}</div>
            </div>
            <div v-if="currentItem.audio_bitrate" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Bitrate</div>
              <div class="text-content text-xs">{{ formatBitrate(currentItem.audio_bitrate) }}</div>
            </div>
            <div v-if="currentItem.created_date" class="bg-overlay-subtle p-2 rounded">
              <div class="text-content-tertiary mb-0.5">Created</div>
              <div class="text-content text-xs">{{ formatDate(currentItem.created_date) }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Processing Status (only for visual media - images and videos) -->
      <div v-if="isVisualMedia" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-sm uppercase tracking-wider text-content-tertiary font-semibold">Processing Status</h4>
        <div class="grid grid-cols-2 gap-2">
          <div class="flex items-center gap-1.5 px-2 py-1.5 bg-overlay-subtle rounded">
            <span :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', getStatusClass(currentItem.clip_status)]"></span>
            <span class="text-xs text-content-tertiary font-medium">Visual Indexing</span>
          </div>
          <div class="flex items-center gap-1.5 px-2 py-1.5 bg-overlay-subtle rounded">
            <span :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', getStatusClass(currentItem.face_detection_status)]"></span>
            <span class="text-xs text-content-tertiary font-medium">Face Analysis</span>
          </div>
          <div v-if="captioningEnabledRef" class="flex items-center gap-1.5 px-2 py-1.5 bg-overlay-subtle rounded">
            <span :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', getStatusClass(currentItem.vlm_caption_status)]"></span>
            <span class="text-xs text-content-tertiary font-medium">Visual Analysis</span>
          </div>
        </div>
      </div>
    </div>

    <!-- External Image Modal (for viewing non-library source images) -->
    <Teleport to="body">
      <div
        v-if="showExternalImageModal"
        class="fixed inset-0 bg-overlay-strong flex items-center justify-center z-[10002]"
        @click="showExternalImageModal = false"
      >
        <div class="relative max-w-[90vw] max-h-[90vh]">
          <img
            :src="externalImageIsRawUrl ? externalImagePath : getReferenceFileUrl(externalImagePath)"
            class="max-w-full max-h-[90vh] object-contain"
            @click.stop
          />
          <div class="absolute bottom-0 left-0 right-0 bg-overlay-strong p-2 text-xs text-content-tertiary truncate">
            {{ externalImageIsRawUrl ? 'Preprocessed Image' : getFilename(externalImagePath) }}
          </div>
          <button
            @click="showExternalImageModal = false"
            class="absolute top-2 right-2 bg-overlay-light text-content rounded-full p-2 hover:bg-overlay-strong border-none cursor-pointer"
          >
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
      </div>
    </Teleport>

    <!-- External Metadata Modal -->
    <Teleport to="body">
      <div
        v-if="showMetadataModal"
        class="fixed inset-0 bg-overlay-strong flex items-center justify-center z-[10002]"
        @click="showMetadataModal = false"
      >
        <div
          class="relative bg-base rounded-lg border border-edge max-w-[80vw] max-h-[80vh] flex flex-col"
          @click.stop
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-4 py-3 border-b border-edge">
            <h3 class="text-sm font-semibold text-content m-0">External Metadata</h3>
            <button
              @click="showMetadataModal = false"
              class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 rounded hover:bg-surface hover:text-content"
            >
              <XMarkIcon class="w-5 h-5" />
            </button>
          </div>
          <!-- Content -->
          <div class="overflow-auto p-4 flex-1 min-h-0">
            <pre
              v-if="formatMetadataForDisplay(metadataModalContent).isJson"
              class="text-sm text-content-secondary m-0 whitespace-pre font-mono json-highlighted"
              v-html="formatMetadataForDisplay(metadataModalContent).content"
            ></pre>
            <pre
              v-else
              class="text-sm text-content-tertiary m-0 whitespace-pre-wrap font-mono"
            >{{ metadataModalContent }}</pre>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import axios from 'axios'
import {
  EyeIcon,
  ChatBubbleLeftRightIcon,
  ArrowTopRightOnSquareIcon,
  ArchiveBoxIcon,
  TagIcon
} from '@heroicons/vue/24/solid'
import { ClipboardDocumentIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import TagEditor from './TagEditor.vue'
import InlineTagEditor from './InlineTagEditor.vue'
import SendToToolMenu from './SendToToolMenu.vue'
import SendToChatMenu from './SendToChatMenu.vue'
import InspireMenu from './InspireMenu.vue'
import { AppImage, MediaImage } from './media'
import { captioningEnabledRef } from '../appConfig'
import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'
import { useProvidersApi } from '../composables/useProvidersApi'
import { formatRemainingTime, getRemainingTimeColor } from '../utils/timeFormat'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { copyToClipboard } from '../utils/clipboard'
import { addToast } from '../composables/useToasts'
import { getFilterDisplayLabel } from '@stimma/image-editor'
import { isImage as isImageType, hasVisualContent, getMediaType } from '../utils/mediaTypes'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { useAssetApi } from '../composables/useAssetApi'

const props = defineProps({
  currentItem: {
    type: Object,
    default: null
  },
  isTrashView: {
    type: Boolean,
    default: false
  },
  isCurrentItemTrashed: {
    type: Boolean,
    default: false
  },
  availableMarkers: {
    type: Array,
    default: () => []
  },
  isVideo: {
    type: Boolean,
    default: false
  },
  focusMode: {
    type: Boolean,
    default: false
  },
  markerUpdateTrigger: {
    type: Number,
    default: 0
  },
  // Pre-fetched data from parent (avoids duplicate API calls)
  mediaProjects: {
    type: Array,
    default: () => []
  },
  mediaBoards: {
    type: Array,
    default: () => []
  },
  descendants: {
    type: Array,
    default: () => []
  },
  inspiredDescendants: {
    type: Array,
    default: () => []
  },
  faces: {
    type: Array,
    default: () => []
  },
  chatInfo: {
    type: Object,
    default: null
  },
  chatInfoLoading: {
    type: Boolean,
    default: false
  },
  generationHistory: {
    type: Array,
    default: null  // null means compute internally
  },
  // Custom title for the panel header
  title: {
    type: String,
    default: 'Media Info'
  }
})

const emit = defineEmits([
  'delete',
  'restore',
  'permanent-delete',
  'find-similar',
  'download',
  'download-original',
  'add-to-board',
  'add-to-project',
  'filter-by-tag',
  'filter-by-keyword',
  'navigate-to-board',
  'navigate-to-project',
  'navigate-to-source-media',
  'compare-with-source',
  'view-in-tool',
  'jump-to-chat',
  'toggle-marker',
  'tags-saved',
  'menu-sent',
  'print',
  'view-lineage',
  'share-to-cloud',
  'remove-from-project',
  'remove-from-board',
  'manage-tags',
  'tags-updated',
  'edit-image',
  'download-version',
  'download-versions'
])

const { cachedTools } = useProvidersApi()
const contextMenu = useMediaContextMenu()
const { getRevisions, restoreRevision, getContainers } = useAssetApi()

const moreButtonRef = ref(null)
const editingTags = ref(false)
const versions = ref([])
const versionsExpanded = ref(false)
const confirmRestoreId = ref(null)
const currentRevisionId = ref(null)
const assetContainers = ref([])

async function loadVersions() {
  versions.value = []
  currentRevisionId.value = null
  assetContainers.value = []
  confirmRestoreId.value = null
  if (!props.currentItem?.asset_id) return
  try {
    const result = await getRevisions(props.currentItem.asset_id)
    versions.value = result.items || []
    currentRevisionId.value = result.current_revision_id || props.currentItem.revision_id
    assetContainers.value = await getContainers(props.currentItem.asset_id)
  } catch (error) {
    console.error('Failed to load asset versions:', error)
  }
}

function formatVersionDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function previousRevisionId(version) {
  const previous = versions.value.find(item => item.revision_number === version.revision_number - 1)
  return previous?.id || null
}

async function requestRestore(version) {
  if (confirmRestoreId.value !== version.id) {
    confirmRestoreId.value = version.id
    return
  }
  try {
    await restoreRevision(props.currentItem.asset_id, version.id)
    confirmRestoreId.value = null
    await loadVersions()
    addToast(`Version ${version.revision_number} restored as the latest version`, 'success')
  } catch (error) {
    addToast(error.response?.data?.detail || 'Could not restore version', 'error')
  }
}

// Reset tag editor when switching slides
watch(() => [props.currentItem?.asset_id, props.currentItem?.revision_id], () => {
  editingTags.value = false
  loadVersions()
}, { immediate: true })

function handleInlineTagsChanged(updatedTags) {
  emit('tags-updated', props.currentItem.id, updatedTags)
}

function openContextMenu(event) {
  if (!props.currentItem) return
  // Use event target position if ref not available
  const el = event?.currentTarget || moreButtonRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  contextMenu.showAt({
    x: rect.left,
    y: rect.bottom + 4,
    mediaId: props.currentItem.id,
    assetId: props.currentItem.asset_id || undefined,
    fileHash: props.currentItem.file_hash,
    mediaIds: [props.currentItem.id],
    assetIds: props.currentItem.asset_id ? [props.currentItem.asset_id] : [],
    selectedItems: [props.currentItem]
  })
}

function getReferenceFileUrl(filePath) {
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(filePath)}&profile=${encodeURIComponent(profileId)}`
  if (pin) url += `&pin=${encodeURIComponent(pin)}`
  return url
}


// Face overlay visibility (self-contained)
const visibleFaceOverlays = ref(new Set())

// Generation metadata toggle (self-contained)
const showGenerationMetadata = ref(true)



// External image modal state
const showExternalImageModal = ref(false)
const externalImagePath = ref('')

// Preprocessed image URL cache: key = "{mediaId|filePath}_{preprocessor}_{paramsJSON}" => URL
const preprocessedUrls = ref({})

function preprocessedCacheKey(source) {
  const id = source.media_id || source.file_path
  const paramsStr = source.preprocessor_params ? JSON.stringify(source.preprocessor_params) : ''
  return `${id}_${source.preprocessor}_${paramsStr}`
}

function getPreprocessedUrl(source) {
  return preprocessedUrls.value[preprocessedCacheKey(source)]
}

async function resolvePreprocessedUrl(source) {
  const key = preprocessedCacheKey(source)
  if (preprocessedUrls.value[key]) return
  try {
    const resp = await axios.post('/api/generate/preprocess-controlnet', {
      source_path: source.file_path,
      preprocessor: source.preprocessor,
      preprocessor_params: source.preprocessor_params || null,
    })
    if (resp.data?.path) {
      const profileId = getCurrentProfileId()
      const pin = getCachedPin(profileId)
      let url = `${getApiBase()}/generate/controlnet-preview?path=${encodeURIComponent(resp.data.path)}&profile=${encodeURIComponent(profileId)}`
      if (pin) url += `&pin=${encodeURIComponent(pin)}`
      preprocessedUrls.value = { ...preprocessedUrls.value, [key]: url }
    }
  } catch (err) {
    console.warn('Failed to resolve preprocessed image:', err)
  }
}

// Watch for preprocessed URLs is set up after effectiveGenerationHistory computed (see below)

// Metadata modal state
const showMetadataModal = ref(false)
const metadataModalContent = ref('')

// Computed: check if current item is an image
const isImage = computed(() => props.currentItem ? isImageType(props.currentItem) : false)

// Computed: get the media type of current item
const currentMediaType = computed(() => props.currentItem ? getMediaType(props.currentItem) : 'image')

// Computed: check if current item has visual content (image or video)
// Used to determine whether to show AI processing status
const isVisualMedia = computed(() => props.currentItem ? hasVisualContent(props.currentItem) : false)

// Computed: keywords array from currentItem
const keywordsArray = computed(() => {
  if (!props.currentItem || !props.currentItem.keywords) return []
  if (Array.isArray(props.currentItem.keywords)) return props.currentItem.keywords
  return props.currentItem.keywords.split(',').map(k => k.trim()).filter(k => k)
})

// Parse generation metadata for internal use (when generationHistory not provided)
const generationMetadata = computed(() => {
  if (!props.currentItem?.generation_metadata) return null
  try {
    return typeof props.currentItem.generation_metadata === 'string'
      ? JSON.parse(props.currentItem.generation_metadata)
      : props.currentItem.generation_metadata
  } catch (e) {
    console.error('Failed to parse generation metadata:', e)
    return null
  }
})

// Extract inspired_by info from generation metadata
const inspiredByInfo = computed(() => {
  const meta = generationMetadata.value
  if (!meta?.inspired_by) return null
  return meta.inspired_by
})

// Compute generation history internally when not provided as prop
const effectiveGenerationHistory = computed(() => {
  // Use provided history if available
  if (props.generationHistory !== null) {
    return Array.isArray(props.generationHistory) ? props.generationHistory : []
  }

  // Compute internally for readOnly mode
  if (!props.currentItem) return []

  // For imported items with no generation_metadata, show a single "imported" entry
  if (!generationMetadata.value) {
    return [{
      media_id: props.currentItem.id,
      task_type: null,
      is_imported: true,
      model: null,
      generator: null,
      prompt: props.currentItem.extracted_prompt || null,
      negative_prompt: null,
      parameters: {
        width: props.currentItem.width,
        height: props.currentItem.height
      },
      generated_at: props.currentItem.indexed_date,
      source_inputs: [],
      tool_id: null,
      raw_metadata: props.currentItem.raw_metadata || null
    }]
  }

  try {
    const history = []
    const meta = generationMetadata.value
    const stepParameters = getStepParameters(meta)

    // Build step from generation metadata
    const step = {
      media_id: props.currentItem?.id,
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
      step.raw_metadata = props.currentItem.raw_metadata || null
      // Add LoRAs into parameters for display
      if (Array.isArray(meta.loras) && meta.loras.length > 0) {
        step.parameters.loras = meta.loras.map(l => ({
          lora: l?.name,
          weight: l?.weight
        }))
      }
    }

    history.push(step)

    // Add ancestor steps from lineage_trace
    if (Array.isArray(meta.lineage_trace) && meta.lineage_trace.length > 0) {
      const ancestors = [...meta.lineage_trace].reverse()
      for (const ancestor of ancestors) {
        if (!ancestor) continue
        const ancestorParameters = getStepParameters(ancestor)
        history.push({
          media_id: ancestor.media_id,
          task_type: ancestor.task_type,
          model: ancestor.model,
          generator: ancestor.generator,
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

// Resolve preprocessed URLs when generation history changes
watch(effectiveGenerationHistory, (history) => {
  if (!history) return
  for (const step of history) {
    if (!step.source_inputs) continue
    for (const source of step.source_inputs) {
      if (source.preprocessor && source.file_path) {
        resolvePreprocessedUrl(source)
      }
    }
  }
}, { immediate: true })

// Reset face overlays when item changes
watch(() => props.currentItem?.id, () => {
  visibleFaceOverlays.value = new Set()
})

// Marker functions
function isMarkerActive(markerId) {
  if (!props.currentItem || !props.currentItem.markers) return false
  return props.currentItem.markers.some(m => m.id === markerId)
}

function toggleMarker(markerId) {
  emit('toggle-marker', markerId)
}

// Face overlay toggle
function toggleFaceOverlay(faceId) {
  const overlays = new Set(visibleFaceOverlays.value)
  if (overlays.has(faceId)) {
    overlays.delete(faceId)
  } else {
    overlays.add(faceId)
  }
  visibleFaceOverlays.value = overlays
}

// Auto-delete removal
async function removeAutoDelete() {
  if (!props.currentItem) return

  try {
    await axios.delete(`/api/assets/item/${props.currentItem.asset_id}/expiration`)
    props.currentItem.expires_at = null
  } catch (error) {
    console.error('Failed to remove auto-delete:', error)
    addToast('Failed to remove auto-delete. Please try again.', 'error')
  }
}

// Modal functions
const externalImageIsRawUrl = ref(false)

function openExternalImageModal(filePath, isRawUrl = false) {
  externalImagePath.value = filePath
  externalImageIsRawUrl.value = isRawUrl
  showExternalImageModal.value = true
}

function openMetadataModal(content) {
  metadataModalContent.value = content
  showMetadataModal.value = true
}

function handleExternalImageError(event) {
  event.target.style.display = 'none'
  const parent = event.target.parentElement
  if (parent && !parent.querySelector('.external-image-placeholder')) {
    const placeholder = document.createElement('div')
    placeholder.className = 'external-image-placeholder w-full h-full flex flex-col items-center justify-center text-content-muted'
    placeholder.innerHTML = `
      <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
      </svg>
      <span class="text-xs mt-1">Unavailable</span>
    `
    parent.appendChild(placeholder)
  }
}

// Formatting helpers
function formatFileFormat(format) {
  if (!format) return ''
  const formatMap = {
    'stimmaset.json': 'Set',
    'stimmagrid.json': 'Grid',
    'md': 'Markdown',
    'txt': 'Text'
  }
  return formatMap[format.toLowerCase()] || format.toUpperCase()
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatDuration(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function formatSampleRate(hz) {
  if (hz >= 1000) {
    return `${(hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1)} kHz`
  }
  return `${hz} Hz`
}

function formatChannels(channels) {
  if (channels === 1) return 'Mono'
  if (channels === 2) return 'Stereo'
  return `${channels} channels`
}

function formatBitrate(bps) {
  if (bps >= 1000000) {
    return `${(bps / 1000000).toFixed(1)} Mbps`
  }
  if (bps >= 1000) {
    return `${Math.round(bps / 1000)} kbps`
  }
  return `${bps} bps`
}

function formatDate(dateString) {
  const date = new Date(dateString)
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatShortDate(dateString) {
  const date = new Date(dateString)
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric' })
}

function formatRelativeTime(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffSecs = Math.floor(diffMs / 1000)
  const diffMins = Math.floor(diffSecs / 60)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffSecs < 60) return 'just now'
  if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`
  if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`
  if (diffDays === 1) return 'yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7)
    return `${weeks} week${weeks === 1 ? '' : 's'} ago`
  }
  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30)
    return `${months} month${months === 1 ? '' : 's'} ago`
  }
  const years = Math.floor(diffDays / 365)
  return `${years} year${years === 1 ? '' : 's'} ago`
}

function formatLoraWeight(weight) {
  const formatted = weight.toFixed(2)
  return formatted.replace(/(\.\d)0$/, '$1')
}

function getLoraDisplayName(lora) {
  const raw = lora.lora || lora.path || ''
  const filename = raw.split('/').pop() || raw
  return filename.replace(/\.safetensors$/i, '') || 'Unknown LoRA'
}

function getToolDisplayName(step) {
  if (step.task_type === 'agent_edit') {
    return 'Edited by Agent'
  }
  if (step.tool_id) {
    const tool = cachedTools.value.find(t => t.full_tool_id === step.tool_id)
    if (tool) return tool.name
    const colonIndex = step.tool_id.indexOf(':')
    if (colonIndex !== -1) return step.tool_id.substring(colonIndex + 1)
    return step.tool_id
  }
  if (step.task_type === 'filter') return 'Filter'
  return step.task_type || 'imported'
}

const preprocessorLabels = {
  canny: 'Canny',
  depth: 'Depth',
  lineart: 'Line Art',
  pose: 'Pose',
  pose_hands: 'Pose + Hands',
}

function formatPreprocessor(id, params) {
  const label = preprocessorLabels[id] || id
  if (!params) return label
  if (id === 'canny' && params.low != null && params.high != null) {
    return `${label} (${params.low}-${params.high})`
  }
  if (id === 'lineart' && params.sigma != null) {
    return `${label} (σ${params.sigma})`
  }
  return label
}

function formatFlip(flip) {
  if (!flip) return ''
  const parts = []
  if (flip.horizontal) parts.push('H')
  if (flip.vertical) parts.push('V')
  const rot = (((flip.rotation || 0) % 360) + 360) % 360
  if (rot !== 0) parts.push(`${rot}°`)
  if (parts.length === 0) return ''
  return `Flip ${parts.join(' ')}`
}

function formatSourceRole(role) {
  const roleMap = {
    'input_image': 'Input Image',
    'start_image': 'Start Frame',
    'end_image': 'End Frame',
    'reference': 'Reference',
    'input_video': 'Input Video',
  }
  return roleMap[role] || role
}

function formatMethod(method) {
  const methodMap = {
    'color_based': 'Color-based',
    'rembg_ai': 'AI (rembg)',
    'ai_upscale': 'AI Upscale',
    'lanczos': 'Lanczos',
    'u2net': 'U\u00b2Net',
    'u2net_human_seg': 'U\u00b2Net Portrait',
    'isnet-anime': 'ISNet Anime'
  }
  return methodMap[method] || method
}

function getStepParameters(stepLike) {
  const params = { ...((stepLike && stepLike.parameters) || {}) }
  if (params.seed === undefined && stepLike?.seed !== undefined && stepLike?.seed !== null) {
    params.seed = stepLike.seed
  }
  return params
}

// Parameters to exclude from generic display
const excludedStepParams = new Set([
  'prompt', 'negative_prompt', 'selected_loras', 'loras',
  'width', 'height', 'input_width', 'input_height', 'output_width', 'output_height',
  'output_size', 'bbox',
  'checkpoint',  // Already shown via step.model
])

const stepLabelOverrides = {
  seed: 'Seed',
  cfg: 'CFG',
  fps: 'FPS',
  generation_time: 'Gen Time',
  frame_count: 'Frames',
  color_correction: 'Color Correction',
  target_megapixels: 'Target MP',
  aspect_ratio: 'Aspect Ratio',
  padding_percent: 'Padding',
  padding: 'Padding',
  item_count: 'Items',
  cell_count: 'Cells',
  clip_skip: 'Clip Skip',
  checkpoint: 'Model',
  filter_id: 'Filter',
}

const fullWidthParams = new Set(['checkpoint'])

function getDisplayableStepParams(params) {
  if (!params) return []

  const result = []

  if (params.width && params.height && !params.input_width) {
    result.push({ label: 'Size', value: `${params.width}\u00d7${params.height}`, fullWidth: false })
  }
  if (params.input_width && params.input_height) {
    result.push({ label: 'Input Size', value: `${params.input_width}\u00d7${params.input_height}`, fullWidth: false })
  }
  if (params.output_width && params.output_height) {
    result.push({ label: 'Output Size', value: `${params.output_width}\u00d7${params.output_height}`, fullWidth: false })
  }
  if (params.output_size?.width && params.output_size?.height) {
    result.push({ label: 'Output Size', value: `${params.output_size.width}\u00d7${params.output_size.height}`, fullWidth: false })
  }
  if (params.bbox) {
    result.push({ label: 'Crop Region', value: `${params.bbox.x},${params.bbox.y} \u2192 ${params.bbox.width}\u00d7${params.bbox.height}`, fullWidth: true })
  }

  for (const [key, value] of Object.entries(params)) {
    if (excludedStepParams.has(key)) continue
    if (value === null || value === undefined) continue
    if (typeof value === 'object') continue

    const label = stepLabelOverrides[key] || formatStepParamLabel(key)
    const formattedValue = formatStepParamValue(key, value)
    const fullWidth = fullWidthParams.has(key) || formattedValue.length > 16
    result.push({ label, value: formattedValue, fullWidth })
  }

  return result
}

function formatStepParamLabel(key) {
  return key
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function formatStepParamValue(key, value) {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (key === 'filter_id' || key === 'filter') return getFilterDisplayLabel(String(value))
  if (key === 'generation_time') return `${value}s`
  if (key === 'resolution') return `${value}p`
  if (key === 'padding_percent') return `${(value * 100).toFixed(0)}%`
  if (key === 'confidence') return `${(value * 100).toFixed(0)}%`
  if (key === 'scale') return `${value}\u00d7`
  if (key === 'shift' && typeof value === 'number') return Number(value).toFixed(2)
  if (key === 'optimization' || key === 'method') {
    if (key === 'method') return formatMethod(value)
    return String(value).charAt(0).toUpperCase() + String(value).slice(1)
  }
  if (key === 'color_correction') return String(value).toUpperCase()
  if (typeof value === 'number' && !Number.isInteger(value)) return value.toFixed(2)
  return String(value)
}

function getStatusClass(status) {
  switch (status) {
    case 'completed':
      return 'status-completed'
    case 'processing':
      return 'status-processing'
    case 'reprocessing':
      return 'status-reprocessing'
    case 'failed':
      return 'status-failed'
    case 'pending':
    default:
      return 'status-pending'
  }
}

function getFilename(filePath) {
  if (!filePath) return 'Unknown'
  return filePath.split('/').pop()
}

function formatMetadataForDisplay(content) {
  try {
    const parsed = JSON.parse(content)
    const json = JSON.stringify(parsed, null, 2)

    const highlighted = json
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
      .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
      .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
      .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
      .replace(/: (null)/g, ': <span class="json-null">$1</span>')

    return { isJson: true, content: highlighted }
  } catch (e) {
    return { isJson: false, content: content }
  }
}


// Expose visible face overlays for parent to use in rendering overlays
defineExpose({
  visibleFaceOverlays
})
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

/* Component pill wrappers (InspireMenu, SendToToolMenu) - scale to fill */
.action-pill-wrap {
  flex: 1 1 0;
  min-width: 0;
}
.action-pill-wrap :deep(> div),
.action-pill-wrap :deep(> div > button) {
  width: 100%;
}
.action-pill-wrap :deep(button) {
  padding: 5px 6px;
  font-size: 11px;
  border-radius: 6px;
  justify-content: center;
  gap: 4px;
}
.action-pill-wrap :deep(button svg:first-child) {
  width: 12px;
  height: 12px;
}
.action-pill-wrap :deep(button svg:last-child) {
  display: none;
}
.action-pill-wrap :deep(button span) {
  white-space: nowrap;
}

/* Vertical action button wrappers (InspireMenu, SendToToolMenu) */
.action-stack-wrap :deep(> div),
.action-stack-wrap :deep(> div > button) {
  width: 100%;
}
.action-stack-wrap :deep(button) {
  width: 100%;
  padding: 8px 12px;
  font-size: 12px;
  border-radius: 8px;
  justify-content: flex-start;
  gap: 8px;
}
.action-stack-wrap :deep(button svg:first-child) {
  width: 16px;
  height: 16px;
}
.action-stack-wrap :deep(button svg:last-child) {
  display: none;
}

/* Marker button SVG styling */
button :deep(svg) {
  display: inline-block;
  color: currentColor;
}

/* JSON syntax highlighting */
.json-highlighted :deep(.json-key) {
  color: #93c5fd;
}
.json-highlighted :deep(.json-string) {
  color: #86efac;
}
.json-highlighted :deep(.json-number) {
  color: #fdba74;
}
.json-highlighted :deep(.json-boolean) {
  color: #c4b5fd;
}
.json-highlighted :deep(.json-null) {
  color: #f87171;
}
</style>
