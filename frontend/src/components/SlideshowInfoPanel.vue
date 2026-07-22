<template>
  <div
    data-testid="media-info-panel"
    class="bg-surface-elevated backdrop-blur-[10px] overflow-y-auto overflow-x-visible z-chrome flex flex-col relative sidebar-scroll order-2 transition-all duration-300"
    :class="focusMode ? 'w-0 opacity-0 pointer-events-none border-l-0' : 'w-[384px] max-w-[90vw] border-l border-edge-subtle'"
  >
    <!-- Header (pinned): markers + utility rail, then the two core-loop verbs.
         Grammar: labels stay on the two actions whose icons don't carry
         themselves and which open menus (Remix, Send to Tool); everything
         icon-conventional is a ghost on the rail. Export-original lives in
         the Export modal (format defaults to Original). -->
    <div v-if="currentItem && !isTrashView && !isCurrentItemTrashed" class="px-3 pt-3 pb-2 flex-shrink-0">
      <div class="flex flex-wrap items-center gap-0.5" :key="'markers-' + markerUpdateTrigger">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          @click="toggleMarker(marker.id)"
          :class="[
            'inline-flex items-center justify-center w-7 h-7 rounded-md cursor-pointer border-none bg-transparent transition-colors duration-150',
            isMarkerActive(marker.id) ? '' : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content-secondary'
          ]"
          :style="isMarkerActive(marker.id) ? { color: marker.color } : {}"
          :title="marker.name"
        >
          <span v-html="sanitizeSvg(marker.icon_svg)" class="w-5 h-5 flex items-center justify-center icon-container"></span>
        </button>
        <div class="flex-1"></div>
        <Tooltip text="Export">
          <IconButton @click="$emit('download')">
            <ArrowDownTrayIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
        <Tooltip text="Share">
          <IconButton @click="$emit('share-to-cloud')">
            <ShareIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
        <Tooltip text="More actions">
          <IconButton @click.stop="openContextMenu($event)">
            <EllipsisHorizontalIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
      </div>
      <div class="grid grid-cols-2 gap-1.5 mt-2">
        <InspireMenu
          :media-id="mediaIdOf(currentItem)"
          @sent="$emit('menu-sent')"
          class="action-pair-wrap"
        />
        <SendToToolMenu
          :media-item="currentItem"
          :media-type="currentMediaType"
          @sent="$emit('menu-sent')"
          class="action-pair-wrap"
        />
      </div>
    </div>

    <div v-if="currentItem" class="p-3 overflow-y-auto overflow-x-hidden">
      <!-- Trash actions -->
      <div v-if="isTrashView || isCurrentItemTrashed" class="flex flex-col gap-1.5 mb-6">
        <button
          @click="$emit('restore')"
          class="w-full bg-overlay-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-md text-xs font-medium transition-colors duration-150 hover:bg-green-500/15"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-emerald-500">
            <path fill-rule="evenodd" d="M2 4.25A2.25 2.25 0 014.25 2h6.5A2.25 2.25 0 0113 4.25V5.5H9.25A3.75 3.75 0 005.5 9.25v6.08a3.75 3.75 0 01-3.5.67V4.25zM9.25 7A2.25 2.25 0 007 9.25v6.5A2.25 2.25 0 009.25 18h6.5A2.25 2.25 0 0018 15.75v-6.5A2.25 2.25 0 0015.75 7h-6.5z" clip-rule="evenodd" />
          </svg>
          <span>Restore</span>
        </button>
        <button
          @click="$emit('permanent-delete')"
          class="w-full bg-overlay-subtle text-content cursor-pointer px-3 py-2 flex items-center gap-2 rounded-md text-xs font-medium transition-colors duration-150 hover:bg-red-500/15"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-red-500">
            <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
          </svg>
          <span>Delete Permanently</span>
        </button>
      </div>

      <!-- Organization: chips are self-describing, no heading -->
      <div class="mb-6">
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
            class="inline-flex items-center gap-1 rounded border border-edge-subtle bg-overlay-subtle px-2 py-0.5 text-xs text-content-secondary transition-colors hover:bg-overlay-hover hover:text-content"
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
          :media-id="mediaIdOf(currentItem)"
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
        <h4 class="m-0 mb-2 text-xs font-semibold text-content-secondary">Source</h4>
        <div class="space-y-2">
          <button
            v-if="chatInfo && !chatInfo.error"
            @click="$emit('jump-to-chat', chatInfo.id)"
            class="w-full flex items-center gap-2 px-3 py-2 bg-accent/20 hover:bg-accent/30 border border-accent/30 rounded text-accent hover:text-accent-hi text-sm transition-colors"
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
          <h4 class="m-0 text-xs font-semibold text-content-secondary flex items-center gap-2">
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
            View graph
          </button>
        </div>
        <!-- Timeline rail (§3.1 grammar): steps separate by the rail + dots
             when history stacks; a single step renders flat — a lone dot on
             a rail would be structure separating nothing. -->
        <div :class="effectiveGenerationHistory.length > 1 ? 'relative pl-4' : ''">
          <div
            v-if="effectiveGenerationHistory.length > 1"
            class="absolute left-[3px] top-2 bottom-2 w-[2px] rounded-full bg-edge-subtle"
          ></div>
          <div
            v-for="(step, idx) in effectiveGenerationHistory"
            :key="idx"
            class="relative"
            :class="idx > 0 ? 'mt-5' : ''"
          >
            <span
              v-if="effectiveGenerationHistory.length > 1"
              class="absolute -left-[16.5px] top-[9.5px] w-[9px] h-[9px] rounded-full bg-surface border-2 border-content-tertiary"
            ></span>
            <!-- Step header: display name + relative time; facts indent under it -->
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-[13px] font-semibold text-content truncate">{{ getToolDisplayName(step) }}</span>
              <span
                v-if="step.generated_at"
                class="font-mono tabular-nums text-[10px] text-content-muted flex-shrink-0"
                :title="formatDate(step.generated_at)"
              >{{ (step.is_imported ? 'imported ' : '') + formatRelativeTime(step.generated_at) }}</span>
              <div class="flex-1"></div>
              <IconButton title="More actions" @click.stop="openContextMenu($event)">
                <EllipsisHorizontalIcon class="w-4 h-4" />
              </IconButton>
            </div>

            <!-- Step Content -->
            <div class="mt-1.5 space-y-2.5">
              <!-- Source Images for this step -->
              <div v-if="step.source_inputs?.length > 0">
                <div class="text-content-tertiary text-xs mb-1.5">Inputs</div>
                <div class="flex flex-wrap gap-3">
                  <template v-for="(source, sourceIdx) in step.source_inputs" :key="sourceIdx">
                    <div v-if="source.media_id" class="flex flex-col">
                      <button
                        @click="source.preprocessor && getPreprocessedUrl(source) ? openExternalImageModal(getPreprocessedUrl(source), true) : $emit('navigate-to-source-media', source.media_id)"
                        class="relative w-24 h-24 rounded-media overflow-hidden bg-matte hover:ring-1 hover:ring-accent/60 transition-shadow p-0 cursor-pointer border-none"
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
                        class="relative w-24 h-24 rounded-media overflow-hidden bg-checker hover:ring-1 hover:ring-accent/60 transition-shadow p-0 cursor-pointer border-none"
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

              <!-- Prompt: typeset in full; clicking it copies (easter egg,
                   skipped when the click is really a text selection) -->
              <p
                v-if="step.prompt"
                @click="copyPromptText(step.prompt)"
                class="text-content-secondary text-xs leading-relaxed m-0 select-text"
              >{{ step.prompt }}</p>

              <!-- Negative Prompt -->
              <div v-if="step.negative_prompt">
                <div class="text-content-tertiary text-xs mb-1">Negative prompt</div>
                <p
                  @click="copyPromptText(step.negative_prompt)"
                  class="text-content-secondary text-xs leading-relaxed m-0 select-text"
                >{{ step.negative_prompt }}</p>
              </div>

              <!-- Facts + generic parameters + LoRAs: ONE KeyValueList so the
                   hairline between groups exists (two adjacent lists drop the
                   rule at the seam — last:border-0 meets a fresh first row).
                   LoRAs are fact rows, not a boxed sub-panel. -->
              <KeyValueList :rows="[...stepFactRows(step), ...stepParamRows(step), ...stepLoraRows(step)]" />

              <!-- Raw Metadata (opens modal for imported items) -->
              <button
                v-if="step.is_imported && step.raw_metadata"
                class="flex w-full items-center justify-between bg-transparent border-none p-0 text-xs text-content-tertiary cursor-pointer hover:text-content"
                @click="openMetadataModal(step.raw_metadata)"
              >
                <span>External metadata</span>
                <span class="text-[10px]">&#9654;</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Versions are saved states of this Asset; Media remains implementation detail. -->
      <div v-if="currentItem.asset_id && versions.length > 1" class="mb-6">
        <h4 class="m-0 text-xs font-semibold text-content-secondary">
          Versions <span class="normal-case tracking-normal text-content-muted">{{ versions.length }}</span>
        </h4>
        <div class="mt-2">
          <div
            v-for="version in visibleVersions"
            :key="version.id"
            class="group flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left"
            :class="version.id === viewedRevisionId ? 'bg-selection/15' : 'hover:bg-overlay-faint'"
            role="button"
            tabindex="0"
            title="View this version"
            @click="viewVersion(version)"
            @keydown.enter.prevent="viewVersion(version)"
            @keydown.space.prevent="viewVersion(version)"
          >
            <div class="h-10 w-10 flex-shrink-0 overflow-hidden rounded-media bg-matte">
              <MediaImage
                :media-id="version.media.id"
                :file-hash="version.media.file_hash"
                :thumbnail-size="128"
                :contain="true"
                container-class="h-full w-full"
              />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-1.5 text-xs">
                <span class="flex-shrink-0 text-content">Version {{ version.revision_number }}</span>
                <span v-if="version.id === currentRevisionId" class="flex-shrink-0 font-mono text-[10px] uppercase tracking-wide text-content-tertiary">Current</span>
                <div class="flex-1"></div>
                <span
                  class="flex-shrink-0 font-mono tabular-nums text-[10px] text-content-muted"
                  :title="formatVersionDate(version.created_at)"
                >{{ formatRelativeTime(version.created_at) }}</span>
                <button
                  class="-my-1 -mr-1 flex-shrink-0 rounded-md p-1 text-content-tertiary opacity-0 transition-opacity hover:bg-overlay-subtle hover:text-content group-hover:opacity-100 group-focus-within:opacity-100"
                  :class="versionMenu.revisionId === version.id ? 'opacity-100' : ''"
                  title="More actions"
                  @click.stop="openVersionMenu($event, version)"
                >
                  <EllipsisHorizontalIcon class="h-4 w-4" />
                </button>
              </div>
              <div class="mt-0.5 truncate text-[11px] text-content-tertiary" :title="version.note || ''">
                {{ version.note || '—' }}
              </div>
            </div>
          </div>
          <button
            v-if="versions.length > VERSION_PREVIEW_COUNT"
            class="mt-1 rounded-md px-1.5 py-1 text-[11px] text-content-tertiary hover:bg-overlay-subtle hover:text-content"
            @click="showAllVersions = !showAllVersions"
          >{{ showAllVersions ? 'Show less' : `Show ${versions.length - VERSION_PREVIEW_COUNT} more` }}</button>
          <ActionMenu
            v-if="versionMenu.revisionId"
            :x="versionMenu.x"
            :y="versionMenu.y"
            :actions="versionMenuActions"
            @close="versionMenu.revisionId = null"
          />
        </div>
      </div>

      <!-- Made From This (descendants/derivatives) -->
      <div v-if="descendants.length > 0" class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="m-0 text-xs font-semibold text-content-secondary">
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
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">
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
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">
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
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary flex items-center justify-between">
          <span>Prompt</span>
          <button
            @click="copyToClipboard(currentItem.extracted_prompt)"
            class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-overlay-light hover:text-content"
            title="Copy to clipboard"
          >
            <ClipboardDocumentIcon class="w-4 h-4" />
          </button>
        </h4>
        <p class="text-content-secondary text-sm leading-relaxed m-0 select-text">{{ currentItem.extracted_prompt }}</p>
      </div>

      <!-- AI Description -->
      <div v-if="currentItem.vlm_caption && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary flex items-center justify-between">
          <span>AI Description</span>
          <button
            @click="copyToClipboard(currentItem.vlm_caption)"
            class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-overlay-light hover:text-content"
            title="Copy to clipboard"
          >
            <ClipboardDocumentIcon class="w-4 h-4" />
          </button>
        </h4>
        <p class="text-content-secondary text-sm leading-relaxed m-0 select-text">{{ currentItem.vlm_caption }}</p>
      </div>

      <!-- Keywords -->
      <div v-if="keywordsArray.length > 0 && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">Keywords</h4>
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
        <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">File</h4>
        <KeyValueList :rows="fileInfoRows">
          <template #actions="{ row }">
            <template v-if="row.key === 'name'">
              <Tooltip v-if="isTauriMode" text="Show in Finder">
                <IconButton aria-label="Show in Finder" @click="revealFileInFinder">
                  <FolderOpenIcon class="w-3.5 h-3.5" />
                </IconButton>
              </Tooltip>
              <Tooltip text="Copy path">
                <IconButton aria-label="Copy path" @click="copyFilePath">
                  <ClipboardDocumentIcon class="w-3.5 h-3.5" />
                </IconButton>
              </Tooltip>
            </template>
          </template>
        </KeyValueList>
      </div>

      <!-- Processing status: a File fact row once everything completed (see
           fileInfoRows); this per-stage section appears only while something
           is pending, running, or failed -->
      <div v-if="isVisualMedia && !allProcessingDone" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">Processing status</h4>
        <div>
          <div class="flex items-center gap-2 py-1.5 border-b border-edge-subtle">
            <StatusDot :bucket="processingStatusBucket(currentItem.clip_status)" :pulse="isProcessingStatusPulsing(currentItem.clip_status)" />
            <span class="text-xs text-content-tertiary">Visual indexing</span>
          </div>
          <div class="flex items-center gap-2 py-1.5 border-b border-edge-subtle last:border-b-0">
            <StatusDot :bucket="processingStatusBucket(currentItem.face_detection_status)" :pulse="isProcessingStatusPulsing(currentItem.face_detection_status)" />
            <span class="text-xs text-content-tertiary">Face analysis</span>
          </div>
          <div v-if="captioningEnabledRef" class="flex items-center gap-2 py-1.5">
            <StatusDot :bucket="processingStatusBucket(currentItem.vlm_caption_status)" :pulse="isProcessingStatusPulsing(currentItem.vlm_caption_status)" />
            <span class="text-xs text-content-tertiary">Visual analysis</span>
          </div>
        </div>
      </div>

      <!-- Detected faces: typeset rows, last section -->
      <div v-if="faces.length > 0" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">Detected faces</h4>
        <div>
          <div
            v-for="(face, index) in faces"
            :key="face.id"
            class="py-1.5 border-b border-edge-subtle last:border-b-0"
          >
            <div class="flex items-center gap-2">
              <span class="text-xs text-content">Face {{ index + 1 }}</span>
              <div class="flex-1"></div>
              <IconButton
                :title="visibleFaceOverlays.has(face.id) ? 'Hide face overlay' : 'Show face overlay'"
                @click="toggleFaceOverlay(face.id)"
              >
                <EyeIcon class="w-4 h-4" :class="visibleFaceOverlays.has(face.id) ? 'text-accent-hi' : ''" />
              </IconButton>
              <span class="font-mono tabular-nums text-xs text-content-tertiary">{{ (face.confidence * 100).toFixed(1) }}%</span>
            </div>
            <div class="font-mono tabular-nums text-[10px] text-content-muted">
              {{ face.bbox.x.toFixed(3) }}, {{ face.bbox.y.toFixed(3) }} · {{ face.bbox.width.toFixed(3) }} × {{ face.bbox.height.toFixed(3) }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- External Image Modal (for viewing non-library source images) -->
    <Teleport to="body">
      <div
        v-if="showExternalImageModal"
        class="fixed inset-0 bg-overlay-strong flex items-center justify-center z-modal"
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
    <Modal
      :show="showMetadataModal"
      size="custom"
      custom-class="max-w-[80vw] max-h-[80vh] flex flex-col"
      @close="showMetadataModal = false"
    >
      <template #header>
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-content m-0">External metadata</h3>
          <button
            @click="showMetadataModal = false"
            class="bg-transparent border-none text-content-tertiary cursor-pointer p-1 rounded hover:bg-surface hover:text-content"
          >
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
      </template>
      <div class="overflow-auto p-4 flex-1 min-h-0">
        <pre
          v-if="formatMetadataForDisplay(metadataModalContent).isJson"
          class="text-sm text-content-secondary m-0 whitespace-pre font-mono json-highlighted select-text"
          v-html="formatMetadataForDisplay(metadataModalContent).content"
        ></pre>
        <pre
          v-else
          class="text-sm text-content-tertiary m-0 whitespace-pre-wrap font-mono select-text"
        >{{ metadataModalContent }}</pre>
      </div>
    </Modal>

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
import { ClipboardDocumentIcon, FolderOpenIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import ActionMenu from './ActionMenu.vue'
import TagEditor from './TagEditor.vue'
import InlineTagEditor from './InlineTagEditor.vue'
import SendToToolMenu from './SendToToolMenu.vue'
import SendToChatMenu from './SendToChatMenu.vue'
import InspireMenu from './InspireMenu.vue'
import { AppImage, MediaImage } from './media'
import KeyValueList from './ui/KeyValueList.vue'
import StatusDot from './ui/StatusDot.vue'
import Modal from './ui/Modal.vue'
import { captioningEnabledRef } from '../appConfig'
import { getApiBase, isTauri } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'
import { useProvidersApi } from '../composables/useProvidersApi'
import { getRemainingTimeColor } from '../utils/timeFormat'
import { useExpirationClock } from '../composables/useExpirationClock'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { copyToClipboard } from '../utils/clipboard'
import { addToast } from '../composables/useToasts'
import { getFilterDisplayLabel } from '@stimma/image-editor'
import { isImage as isImageType, hasVisualContent, getMediaType } from '../utils/mediaTypes'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { useAssetApi } from '../composables/useAssetApi'
import { hasAssetIdentity, mediaIdOf } from '../utils/assetIdentity'

import IconButton from './ui/IconButton.vue'
import Tooltip from './ui/Tooltip.vue'
import { ArrowDownTrayIcon, ShareIcon, EllipsisHorizontalIcon } from '@heroicons/vue/24/outline'

const { formatRemainingTime } = useExpirationClock()
const isTauriMode = isTauri()

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
  'download-version'
])

const { cachedTools } = useProvidersApi()
const contextMenu = useMediaContextMenu()
const { getRevisions, restoreRevision, getContainers } = useAssetApi()

const editingTags = ref(false)
const versions = ref([])
// Recent versions are visible on arrival; deep history stays one click away.
const VERSION_PREVIEW_COUNT = 5
const showAllVersions = ref(false)
const currentRevisionId = ref(null)
const assetContainers = ref([])

// Guards against an older in-flight load landing after a newer one.
let versionsLoadToken = 0

async function loadVersions() {
  const assetId = props.currentItem?.asset_id
  const token = ++versionsLoadToken
  if (!assetId) {
    versions.value = []
    currentRevisionId.value = null
    assetContainers.value = []
    return
  }
  try {
    // The list is NOT cleared first: blanking it collapses the section's height
    // and shoves the rest of the panel around for a frame on every reload.
    const result = await getRevisions(assetId)
    if (token !== versionsLoadToken) return
    versions.value = result.items || []
    currentRevisionId.value = result.current_revision_id || props.currentItem?.revision_id
    const containers = await getContainers(assetId)
    if (token !== versionsLoadToken) return
    assetContainers.value = containers
  } catch (error) {
    console.error('Failed to load asset versions:', error)
  }
}

// Which version is on screen right now — not necessarily the asset's current
// revision, since viewing an older version navigates the stage to that payload.
const viewedRevisionId = computed(() => {
  const item = props.currentItem
  if (!item) return currentRevisionId.value
  const match = versions.value.find(version => version.media?.id === (item.media_id ?? item.id))
  return match?.id ?? item.revision_id ?? currentRevisionId.value
})

const visibleVersions = computed(() => {
  if (showAllVersions.value) return versions.value
  const preview = versions.value.slice(0, VERSION_PREVIEW_COUNT)
  // Never hide the version being viewed — the panel reloads on navigation, and
  // collapsing the row you just opened out of the list reads as a disappearance.
  if (preview.some(version => version.id === viewedRevisionId.value)) return preview
  const viewed = versions.value.find(version => version.id === viewedRevisionId.value)
  return viewed ? [...preview, viewed] : preview
})

const versionMenu = ref({ revisionId: null, x: 0, y: 0 })

function openVersionMenu(event, version) {
  const rect = event.currentTarget.getBoundingClientRect()
  versionMenu.value = { revisionId: version.id, x: rect.right - 200, y: rect.bottom + 4 }
}

const versionMenuActions = computed(() => {
  const version = versions.value.find(item => item.id === versionMenu.value.revisionId)
  if (!version) return []
  const actions = []
  if (version.id !== currentRevisionId.value) {
    actions.push({
      id: 'make-current',
      label: 'Make current',
      action: () => makeVersionCurrent(version),
    })
  }
  if (isImageType(version.media)) {
    actions.push({
      id: 'edit-from',
      label: 'Edit from this version',
      action: () => emit('edit-image', version.media.id),
    })
  }
  actions.push({
    id: 'export',
    label: 'Export…',
    action: () => emit('download-version', version.media),
  })
  return actions
})

function viewVersion(version) {
  if (!version?.media?.id) return
  if (version.id === viewedRevisionId.value) return
  emit('navigate-to-source-media', version.media.id)
}

function formatVersionDate(value) {
  if (!value) return ''
  // Exact timestamp — the row shows relative time and keeps this as its tooltip.
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

// Additive: commits this version's content as a new revision on top. Nothing is
// deleted, so it needs no confirmation — doing it again undoes it.
async function makeVersionCurrent(version) {
  try {
    await restoreRevision(props.currentItem.asset_id, version.id)
    await loadVersions()
    addToast(`Version ${version.revision_number} saved as the current version`, 'success')
  } catch (error) {
    addToast(error.response?.data?.detail || 'Could not restore version', 'error')
  }
}

// Reset tag editor when switching slides
watch(() => [props.currentItem?.asset_id, props.currentItem?.revision_id], () => {
  editingTags.value = false
}, { immediate: true })

// Reload on revision changes too — a newly committed revision has to appear —
// but the list is replaced in place, so switching versions never blanks it.
watch(() => [props.currentItem?.asset_id, props.currentItem?.revision_id], (next, prev) => {
  if (!prev || next[0] !== prev[0]) showAllVersions.value = false
  loadVersions()
}, { immediate: true })

function handleInlineTagsChanged(updatedTags) {
  emit('tags-updated', mediaIdOf(props.currentItem), updatedTags)
}

// Asset identity for context-menu actions. Embedded container cells and other
// payload-shaped items carry `id` = media id with no `asset_id`; the generic
// `assetIdOf` fallback (`asset_id ?? id`) would address whichever unrelated
// Asset shares that number. Only a real asset_id (or the resolved
// saved_asset_id of an embedded cell whose Media is also a saved Asset) may
// drive Asset-level actions here.
function contextAssetId() {
  const item = props.currentItem
  if (!item) return null
  if (hasAssetIdentity(item)) return item.asset_id
  return item.saved_asset_id ?? null
}

function openContextMenu(event) {
  if (!props.currentItem) return
  const el = event?.currentTarget
  if (!el) return
  const rect = el.getBoundingClientRect()
  const assetId = contextAssetId()
  contextMenu.showAt({
    x: rect.left,
    y: rect.bottom + 4,
    mediaId: mediaIdOf(props.currentItem),
    assetId: assetId || undefined,
    fileHash: props.currentItem.file_hash,
    mediaIds: [mediaIdOf(props.currentItem)].filter(Boolean),
    assetIds: [assetId].filter(Boolean),
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

// Atelier generation-step facts as KeyValueList rows.
// Generated/Imported time lives in the step header now, not the fact list.
function stepFactRows(step) {
  const rows = []
  // Skip the Model row when it just repeats the step header's display name
  if (step.model && step.model.toLowerCase() !== getToolDisplayName(step).toLowerCase()) {
    rows.push({ label: 'Model', value: step.model, mono: false, truncate: true })
  }
  return rows
}
function stepParamRows(step) {
  const rows = getDisplayableStepParams(step.parameters).map(p => ({
    label: p.label, value: p.value, truncate: p.fullWidth,
  }))
  // Dedupe: the current item's own output Size repeats the File section's
  // Resolution row — generation facts describe the run, file facts the artifact.
  const m = props.currentItem
  if (m && step.media_id === mediaIdOf(m) && m.width > 0 && m.height > 0) {
    const fileRes = `${m.width}×${m.height}`
    return rows.filter(r => !(r.label === 'Size' && r.value === fileRes))
  }
  return rows
}
// LoRAs as fact rows (handles both 'loras' and legacy 'selected_loras');
// weight reads accent when non-default, per the §3.4 modified signal.
function stepLoraRows(step) {
  const loras = step.parameters?.loras || step.parameters?.selected_loras || []
  return loras.map(lora => ({
    label: 'LoRA',
    value: `${getLoraDisplayName(lora)} · ${formatLoraWeight(lora.weight)}`,
    truncate: true,
    valueClass: lora.weight !== 1 ? 'text-accent-hi' : undefined,
  }))
}

// Click-to-copy easter egg on prompts. A click that ends a text selection
// isn't a copy request — skip it so manual select-and-copy still works.
async function copyPromptText(text) {
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return
  await copyTextWithToast(text)
}

async function copyTextWithToast(text) {
  if (await copyToClipboard(text)) {
    addToast('Copied to clipboard', 'success')
  } else {
    addToast('Could not copy to clipboard', 'error')
  }
}

async function copyFilePath() {
  if (!props.currentItem?.file_path) return
  await copyTextWithToast(props.currentItem.file_path)
}

async function revealFileInFinder() {
  if (!props.currentItem?.file_path || !isTauriMode) return
  try {
    const { revealItemInDir } = await import('@tauri-apps/plugin-opener')
    await revealItemInDir(props.currentItem.file_path)
  } catch (error) {
    console.error('Failed to reveal in Finder:', error)
    addToast('Could not show file in Finder', 'error')
  }
}

// Atelier typeset file facts (KeyValueList) — replaces the field-tile grid
const fileInfoRows = computed(() => {
  const m = props.currentItem
  if (!m) return []
  const rows = []
  if (m.file_path) rows.push({ key: 'name', label: 'Name', value: m.file_path.split('/').pop(), truncate: true, actions: true })
  if (m.file_format) rows.push({ label: 'Format', value: formatFileFormat(m.file_format) })
  if (m.file_size) rows.push({ label: 'Size', value: formatFileSize(m.file_size) })
  if (m.width > 0 && m.height > 0) rows.push({ label: 'Resolution', value: `${m.width} × ${m.height}` })
  if (m.duration) rows.push({ label: 'Duration', value: formatDuration(m.duration) })
  if (m.audio_sample_rate) rows.push({ label: 'Sample rate', value: formatSampleRate(m.audio_sample_rate) })
  if (m.audio_bit_depth) rows.push({ label: 'Bit depth', value: `${m.audio_bit_depth}-bit` })
  if (m.audio_channels) rows.push({ label: 'Channels', value: formatChannels(m.audio_channels), mono: false })
  if (m.audio_bitrate) rows.push({ label: 'Bitrate', value: formatBitrate(m.audio_bitrate) })
  if (m.created_date) rows.push({ label: 'Created', value: formatDate(m.created_date) })
  // Processing status rides along as a fact row once everything completed;
  // while anything is pending/running/failed it renders as its own section.
  if (hasVisualContent(m) && allProcessingDone.value) {
    rows.push({ label: 'Processing', value: processingSummary.value, valueClass: 'text-content-tertiary' })
  }
  return rows
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
      media_id: mediaIdOf(props.currentItem),
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

// Local status vocabulary (clip_status/face_detection_status/vlm_caption_status)
// mapped onto the shared StatusBucket vocabulary — colors always come from
// statusColors.ts via StatusDot (STANDARDS.md §1.9); this only knows the
// mapping, never a color.
function processingStatusBucket(status) {
  switch (status) {
    case 'completed':
      return 'done'
    case 'processing':
      return 'running'
    case 'reprocessing':
      return 'special'
    case 'failed':
      return 'failed'
    case 'pending':
    default:
      return 'queued'
  }
}

function isProcessingStatusPulsing(status) {
  return status === 'processing' || status === 'reprocessing'
}

// All-clear check for the collapsed one-line footer. Caption status only
// counts when captioning is enabled.
const allProcessingDone = computed(() => {
  const m = props.currentItem
  if (!m) return false
  const statuses = [m.clip_status, m.face_detection_status]
  if (captioningEnabledRef.value) statuses.push(m.vlm_caption_status)
  return statuses.every(s => s === 'completed')
})

const processingSummary = computed(() => {
  const parts = ['indexed', 'faces analyzed']
  if (captioningEnabledRef.value) parts.push('captioned')
  return parts.join(' · ')
})

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

/* Action-pair wrappers (InspireMenu, SendToToolMenu): restyle each menu's
   own trigger into the kit secondary-button look — centered icon+label,
   no border, no trailing chevron. Only the TRIGGER button (direct child);
   the teleported dropdown contents are untouched. */
.action-pair-wrap {
  min-width: 0;
}
.action-pair-wrap :deep(button) {
  width: 100%;
  background: rgb(var(--color-surface-raised-rgb));
  border: none;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  justify-content: center;
  gap: 6px;
  color: rgb(var(--color-text-primary-rgb));
  transition: background-color 150ms;
}
.action-pair-wrap :deep(button:hover) {
  background: rgb(var(--color-surface-hover-rgb));
}
.action-pair-wrap :deep(button svg:first-child) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
.action-pair-wrap :deep(button svg:last-child) {
  display: none;
}
.action-pair-wrap :deep(button span) {
  white-space: nowrap;
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
