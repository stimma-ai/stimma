<template>
  <div
    data-testid="media-info-panel"
    class="app-no-drag overflow-y-auto overflow-x-visible flex flex-col relative custom-scrollbar"
    :class="contentOnly
      ? 'flex-1 min-h-0 w-full bg-transparent'
      : [
          'bg-surface-elevated backdrop-blur-[10px] z-chrome order-2 transition-all duration-300',
          focusMode ? 'w-0 opacity-0 pointer-events-none border-l-0' : 'w-96 max-w-[90vw] border-l border-edge-subtle'
        ]"
  >
    <!-- Header (pinned): markers + utility rail, then the two core-loop verbs.
         Grammar: labels stay on the two actions whose icons don't carry
         themselves and which open menus (Remix, Send to Tool); everything
         icon-conventional is a ghost on the rail. Export-original lives in
         the Export modal (format defaults to Original). -->
    <div v-if="currentItem && !isTrashView && !isCurrentItemTrashed" class="px-3 pt-3 pb-2 flex-shrink-0">
      <div class="flex flex-wrap items-center gap-0.5" :key="'markers-' + markerUpdateTrigger">
        <Tooltip v-for="marker in availableMarkers" :key="marker.id" :text="marker.name">
          <button
            type="button"
            :aria-label="marker.name"
            @click="toggleMarker(marker.id)"
            :class="[
              'inline-flex items-center justify-center w-7 h-7 rounded-md cursor-pointer border-none bg-transparent transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60',
              isMarkerActive(marker.id) ? '' : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content-secondary'
            ]"
            :style="isMarkerActive(marker.id) ? { color: marker.color } : {}"
          >
            <span v-html="sanitizeSvg(marker.icon_svg)" class="w-5 h-5 flex items-center justify-center icon-container"></span>
          </button>
        </Tooltip>
        <div class="flex-1"></div>
        <!-- Rail actions render only where the host handles them (Compare
             mode mounts this panel without export/share/edit/graph). -->
        <Tooltip v-if="handles('download')" text="Export">
          <IconButton aria-label="Export" @click="$emit('download')">
            <ArrowDownTrayIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
        <Tooltip v-if="handles('share-to-cloud')" text="Share link">
          <IconButton aria-label="Share link" @click="$emit('share-to-cloud')">
            <ShareIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
        <Tooltip text="More actions">
          <IconButton aria-label="More actions" @click.stop="openContextMenu($event)">
            <EllipsisHorizontalIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
      </div>
      <div class="grid grid-cols-2 gap-1.5 mt-2">
        <button
          v-if="showEditAction && handles('edit-image') && isImageType(currentItem)"
          type="button"
          class="col-span-2 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-surface-raised px-3 py-2 text-xs font-medium text-content transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          @click="$emit('edit-image', mediaIdOf(currentItem))"
        >
          <PencilSquareIcon class="h-3.5 w-3.5 flex-shrink-0" />
          <span>Edit</span>
        </button>
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
          <span>Delete permanently</span>
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
            class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle rounded-md text-content-secondary hover:bg-overlay-light hover:text-content transition-colors duration-150 cursor-pointer no-underline"
          ><ArchiveBoxIcon class="w-3 h-3 text-content-muted" />{{ project.name || 'Untitled' }}</a>
          <a
            v-for="board in mediaBoards"
            :key="'b-' + board.id"
            href="#"
            @click.prevent="$emit('navigate-to-board', board.id)"
            class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle rounded-md text-content-secondary hover:bg-overlay-light hover:text-content transition-colors duration-150 cursor-pointer no-underline"
          ><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted"><path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v11.5A2.25 2.25 0 004.25 18h11.5A2.25 2.25 0 0018 15.75V4.25A2.25 2.25 0 0015.75 2H4.25zM3.5 4.25a.75.75 0 01.75-.75h5v6.5h-5.75V4.25zm0 7.25v4.25c0 .414.336.75.75.75h5v-5h-5.75zm7.25-7.75v6.5h5.75V4.25a.75.75 0 00-.75-.75h-5zm5.75 8h-5.75v5h5a.75.75 0 00.75-.75v-4.25z" clip-rule="evenodd" /></svg>{{ board.name || 'Untitled' }}</a>
          <button
            v-for="container in assetContainers"
            :key="`c-${container.asset_id}-${container.member_order}`"
            class="inline-flex items-center gap-1 rounded-md bg-overlay-subtle px-2 py-0.5 text-xs text-content-secondary transition-colors duration-150 hover:bg-overlay-hover hover:text-content"
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
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-overlay-subtle rounded-md text-content-secondary hover:bg-overlay-light hover:text-content transition-colors duration-150 cursor-pointer no-underline"
            ><TagIcon class="w-3 h-3 text-content-muted" />{{ tag.tag }}</a>
            <Tooltip text="Edit tags">
              <button
                type="button"
                aria-label="Edit tags"
                @click="editingTags = true"
                class="inline-flex items-center gap-1 px-2 py-0.5 border border-dashed border-edge-subtle rounded-md text-content-muted text-xs hover:bg-overlay-light hover:text-content-secondary hover:border-edge transition-colors duration-150 cursor-pointer bg-transparent"
              ><TagIcon class="w-3 h-3" />+</button>
            </Tooltip>
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

      <!-- Auto-delete warning (hidden in trash). Colors come from the §1.9
           status map via expiryBucket; fill-only, no border. -->
      <div v-if="!isTrashView && !isCurrentItemTrashed && currentItem.expires_at && formatRemainingTime(currentItem.expires_at)" class="mb-4">
        <div class="p-3 rounded-md flex items-start gap-2" :class="bgClass(expiryBucket)">
          <TrashIcon class="w-4 h-4 flex-shrink-0 mt-0.5" :class="textClass(expiryBucket)" />
          <div class="flex-1 min-w-0">
            <div class="text-xs font-semibold mb-1" :class="textClass(expiryBucket)">
              Auto-delete in <span class="font-mono tabular-nums">{{ formatRemainingTime(currentItem.expires_at) }}</span>
            </div>
            <div class="text-xs text-content-tertiary">
              This will be moved to trash automatically unless you tag, collect, or mark it.
            </div>
          </div>
          <Tooltip text="Keep it">
            <IconButton aria-label="Remove auto-delete" class="-mt-1 -mr-1" @click="removeAutoDelete">
              <XMarkIcon class="w-4 h-4" />
            </IconButton>
          </Tooltip>
        </div>
      </div>


      <!-- Chat source (if generated via chat) -->
      <div v-if="currentItem.chat_item_id" class="mb-4">
        <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">Source</h4>
        <button
          v-if="chatInfo && !chatInfo.error"
          type="button"
          @click="$emit('jump-to-chat', chatInfo.id)"
          class="-mx-2 w-[calc(100%+1rem)] flex items-center gap-2 px-2 py-1.5 rounded-md bg-transparent border-none cursor-pointer text-accent hover:text-accent-hi hover:bg-overlay-subtle text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        >
          <ChatBubbleLeftRightIcon class="w-4 h-4 flex-shrink-0" />
          <span class="truncate">{{ chatInfo.name }}</span>
          <ArrowTopRightOnSquareIcon class="w-3.5 h-3.5 ml-auto flex-shrink-0" />
        </button>
        <div v-else-if="chatInfo?.error === 'deleted'" class="flex items-center gap-2 py-1.5 text-content-muted text-sm">
          <ChatBubbleLeftRightIcon class="w-4 h-4" />
          <span>Chat deleted</span>
        </div>
        <div v-else-if="chatInfoLoading" class="flex items-center gap-2 py-1.5 text-content-muted text-sm">
          <Spinner size="sm" />
          <span>Loading…</span>
        </div>
      </div>

      <!-- Package: what this deliverable holds, and the one thing you can do
           to it. Its members are NOT re-listed — Lineage below already shows
           the inputs this bundle was built from. -->
      <div v-if="packageStatus" class="mb-6">
        <div class="flex items-center justify-between mb-1">
          <h4 class="m-0 text-xs font-semibold text-content-secondary">Package</h4>
          <button
            class="flex items-center gap-1 rounded-md bg-transparent border-none cursor-pointer text-[11px] text-content-secondary transition-colors duration-150 hover:text-content disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            :disabled="rebuildingPackage"
            @click="rebuildPackage"
          >
            <ArrowPathIcon class="w-3.5 h-3.5" />
            {{ rebuildingPackage ? 'Rebuilding…' : 'Rebuild' }}
          </button>
        </div>
        <KeyValueList :rows="packageRows" />
        <!-- Warning family per DESIGN §1.9; only when a member has moved on. -->
        <p v-if="packageStatus.stale" class="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
          <ExclamationTriangleIcon class="w-3.5 h-3.5 flex-shrink-0" />
          <span>An input has a newer version</span>
        </p>
      </div>

      <!-- Lineage: how this was made, newest step first -->
      <div v-if="provenance.steps.length > 0" class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="m-0 text-xs font-semibold text-content-secondary">Lineage</h4>
          <button
            v-if="handles('view-lineage')"
            type="button"
            :class="sectionLinkClass"
            @click="$emit('view-lineage')"
          >
            <LineageGlyph class="w-3 h-3" />
            View graph
          </button>
        </div>
        <ProvenanceAppHost
          :allow-compare="handles('compare-with-source')"
          @navigate="$emit('navigate-to-source-media', $event)"
          @compare="$emit('compare-with-source', $event)"
        >
          <ProvenanceSteps :steps="provenanceView.steps">
            <template #actions="{ step: { origin: step } }">
              <Tooltip v-if="step.settings && handles('view-in-tool')" :text="`Use these settings in ${step.tool}`">
                <IconButton :aria-label="`Use these settings in ${step.tool}`" data-testid="use-step-settings" @click="$emit('view-in-tool', step.settings)">
                  <AdjustmentsHorizontalIcon class="w-4 h-4" />
                </IconButton>
              </Tooltip>
              <Tooltip v-if="step.mediaId" text="More actions">
                <IconButton aria-label="More actions" @click.stop="openStepMenu($event, step)">
                  <EllipsisHorizontalIcon class="w-4 h-4" />
                </IconButton>
              </Tooltip>
            </template>
          </ProvenanceSteps>
        </ProvenanceAppHost>
        <!-- Flow origin: the run this came out of -->
        <button
          v-if="provenance.flow && handles('open-flow')"
          type="button"
          class="mt-3 flex w-full items-baseline justify-between gap-4 bg-transparent border-none p-0 text-xs cursor-pointer group"
          @click="$emit('open-flow', provenance.flow.flowId)"
        >
          <span class="text-content-tertiary flex-shrink-0">Flow</span>
          <span class="min-w-0 truncate text-accent group-hover:text-accent-hi">
            {{ provenance.flow.phasePath.length ? provenance.flow.phasePath.join(' / ') : 'Open flow' }}
          </span>
        </button>
      </div>

      <!-- Versions are saved states of this Asset; Media remains implementation detail. -->
      <div v-if="currentItem.asset_id && versions.length > 1" class="mb-6">
        <h4 class="m-0 text-xs font-semibold text-content-secondary">Versions</h4>
        <div class="mt-2">
          <div
            v-for="version in visibleVersions"
            :key="version.id"
            class="group flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left"
            :class="version.id === viewedRevisionId ? 'bg-selection/15' : 'hover:bg-overlay-faint'"
            role="button"
            tabindex="0"
            :aria-label="`View version ${version.revision_number}`"
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
                <span v-if="version.id === currentRevisionId" class="flex-shrink-0 text-[10px] text-content-tertiary">Current</span>
                <div class="flex-1"></div>
                <Tooltip :text="formatDateTime(version.created_at)">
                  <span class="flex-shrink-0 font-mono tabular-nums text-[10px] text-content-muted">{{ formatRelativeTime(normalizeDate(version.created_at)) }}</span>
                </Tooltip>
                <button
                  type="button"
                  aria-label="More actions"
                  class="-my-1 -mr-1 flex-shrink-0 rounded-md p-1 text-content-tertiary opacity-0 transition-opacity hover:bg-overlay-subtle hover:text-content group-hover:opacity-100 group-focus-within:opacity-100 [[data-pointer=coarse]_&]:opacity-100"
                  :class="versionMenu.revisionId === version.id ? 'opacity-100' : ''"
                  @click.stop="openVersionMenu($event, version)"
                >
                  <EllipsisHorizontalIcon class="h-4 w-4" />
                </button>
              </div>
              <div class="mt-0.5 truncate text-[11px] text-content-tertiary">
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

      <!-- Made from this (descendants/derivatives) -->
      <div v-if="descendants.length > 0" class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="m-0 text-xs font-semibold text-content-secondary">Made from this</h4>
          <button
            v-if="handles('view-lineage')"
            type="button"
            :class="sectionLinkClass"
            @click="$emit('view-lineage')"
          >
            <LineageGlyph class="w-3 h-3" />
            View graph
          </button>
        </div>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            v-for="descendant in descendants"
            :key="descendant.id"
            :media-id="descendant.id"
            :file-hash="descendant.file_hash"
            :thumbnail-size="128"
            :container-class="relationThumbClass"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', descendant.id)"
          />
        </div>
      </div>

      <!-- Remixes (media remixed from this one) -->
      <div v-if="inspiredDescendants.length > 0" class="mb-6">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">Remixes</h4>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            v-for="descendant in inspiredDescendants"
            :key="descendant.id"
            :media-id="descendant.id"
            :file-hash="descendant.file_hash"
            :thumbnail-size="128"
            :container-class="relationThumbClass"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', descendant.id)"
          />
        </div>
      </div>

      <!-- Remix of (the source this was remixed from) -->
      <div v-if="provenance.inspiredBy" class="mb-6">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">Remix of</h4>
        <div class="flex flex-wrap gap-2">
          <MediaImage
            :media-id="provenance.inspiredBy"
            :thumbnail-size="128"
            :container-class="relationThumbClass"
            img-class="w-full h-full object-cover"
            @click="$emit('navigate-to-source-media', provenance.inspiredBy)"
          />
        </div>
      </div>

      <!-- AI description -->
      <div v-if="currentItem.vlm_caption && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary flex items-center justify-between">
          <span>AI description</span>
          <Tooltip text="Copy">
            <IconButton aria-label="Copy description" @click="copyTextWithToast(currentItem.vlm_caption)">
              <ClipboardDocumentIcon class="w-4 h-4" />
            </IconButton>
          </Tooltip>
        </h4>
        <p class="text-content-secondary text-sm leading-relaxed m-0 select-text">{{ currentItem.vlm_caption }}</p>
      </div>

      <!-- Keywords -->
      <div v-if="keywordsArray.length > 0 && captioningEnabledRef" class="mb-8 last:mb-0">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">Keywords</h4>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="keyword in keywordsArray"
            :key="keyword"
            type="button"
            :aria-label="`Filter by ${keyword}`"
            @click="$emit('filter-by-keyword', keyword)"
            class="inline-block px-2 py-0.5 bg-overlay-subtle rounded-md border-none text-xs text-content-secondary cursor-pointer transition-colors duration-150 hover:bg-overlay-hover hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            {{ keyword }}
          </button>
        </div>
      </div>

      <!-- File -->
      <ProvenanceFileFacts class="mb-6" :rows="fileInfoRows">
        <template #actions="{ row }">
          <template v-if="row.key === 'name'">
            <Tooltip v-if="isDesktopMode" text="Show in Finder">
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
      </ProvenanceFileFacts>

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
              <Tooltip :text="visibleFaceOverlays.has(face.id) ? 'Hide face overlay' : 'Show face overlay'">
                <IconButton
                  :aria-label="visibleFaceOverlays.has(face.id) ? 'Hide face overlay' : 'Show face overlay'"
                  @click="toggleFaceOverlay(face.id)"
                >
                  <EyeIcon class="w-4 h-4" :class="visibleFaceOverlays.has(face.id) ? 'text-accent-hi' : ''" />
                </IconButton>
              </Tooltip>
              <span class="font-mono tabular-nums text-xs text-content-tertiary">{{ (face.confidence * 100).toFixed(1) }}%</span>
            </div>
            <div class="font-mono tabular-nums text-[10px] text-content-muted">
              {{ face.bbox.x.toFixed(3) }}, {{ face.bbox.y.toFixed(3) }} · {{ face.bbox.width.toFixed(3) }} × {{ face.bbox.height.toFixed(3) }}
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, h, getCurrentInstance, camelize, toHandlerKey } from 'vue'
import axios from 'axios'
import {
  EyeIcon,
  ChatBubbleLeftRightIcon,
  ArrowTopRightOnSquareIcon,
  ArchiveBoxIcon,
  TagIcon
} from '@heroicons/vue/24/solid'
import {
  AdjustmentsHorizontalIcon,
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ClipboardDocumentIcon,
  EllipsisHorizontalIcon,
  ExclamationTriangleIcon,
  FolderOpenIcon,
  PencilSquareIcon,
  ShareIcon,
  TrashIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import ActionMenu from './ActionMenu.vue'
import InlineTagEditor from './InlineTagEditor.vue'
import SendToToolMenu from './SendToToolMenu.vue'
import InspireMenu from './InspireMenu.vue'
import { MediaImage } from './media'
import ProvenanceAppHost from './media/ProvenanceAppHost.vue'
import ProvenanceSteps from '../provenance/ProvenanceSteps.vue'
import ProvenanceFileFacts from '../provenance/ProvenanceFileFacts.vue'
import { viewFromProvenance } from '../provenance/fromProvenance'
import KeyValueList from './ui/KeyValueList.vue'
import StatusDot from './ui/StatusDot.vue'
import Spinner from './ui/Spinner.vue'
import IconButton from './ui/IconButton.vue'
import Tooltip from './ui/Tooltip.vue'
import { captioningEnabledRef } from '../appConfig'
import { getApiBase, isDesktop } from '../apiConfig'
import { formatRelativeTime, getRemainingTimeColor } from '../utils/timeFormat'
import { useExpirationClock } from '../composables/useExpirationClock'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { useProvenanceBuilder } from '../composables/useMediaProvenance'
import { copyToClipboard } from '../utils/clipboard'
import { addToast } from '../composables/useToasts'
import { isImage as isImageType, hasVisualContent, getMediaType } from '../utils/mediaTypes'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { bgClass, textClass } from '../utils/statusColors'
import { factRows, formatDateTime, normalizeDate } from '../utils/mediaProvenance'
import { useAssetApi } from '../composables/useAssetApi'
import { hasAssetIdentity, mediaIdOf } from '../utils/assetIdentity'

const { formatRemainingTime } = useExpirationClock()
const isDesktopMode = isDesktop()

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
  // Reuse the panel inside another sidebar without imposing the slideshow's
  // fixed width, border, backdrop, or transition chrome.
  contentOnly: {
    type: Boolean,
    default: false
  },
  showEditAction: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits([
  'restore',
  'permanent-delete',
  'download',
  'download-version',
  'edit-image',
  'share-to-cloud',
  'filter-by-tag',
  'filter-by-keyword',
  'navigate-to-board',
  'navigate-to-project',
  'navigate-to-source-media',
  'compare-with-source',
  // A step's recorded settings (ProvenanceSettings), for "Use these settings".
  'view-in-tool',
  'view-lineage',
  'open-flow',
  'jump-to-chat',
  'toggle-marker',
  'tags-updated',
  'menu-sent',
  'package-rebuilt',
])

// Actions that leave the panel render only where the host listens for them —
// Compare mode, the editor's Info tab and the slideshow each handle a
// different subset, and a button that does nothing is worse than none.
const hostProps = getCurrentInstance()?.vnode.props || {}
function handles(event) {
  return typeof hostProps[toHandlerKey(camelize(event))] === 'function'
    || Array.isArray(hostProps[toHandlerKey(camelize(event))])
}

const sectionLinkClass = 'text-[11px] text-content-secondary hover:text-content transition-colors duration-150 flex items-center gap-1 bg-transparent border-none cursor-pointer'
const relationThumbClass = 'w-16 h-16 rounded-media bg-matte overflow-hidden cursor-pointer hover:ring-2 hover:ring-accent/60 transition-shadow'

// The lineage glyph (two parents joining into one), shared by the section links.
const LineageGlyph = (glyphProps) => h('svg', { viewBox: '0 0 20 20', fill: 'none', stroke: 'currentColor', class: glyphProps.class }, [
  h('circle', { cx: 6, cy: 4.5, r: 1.75, 'stroke-width': 1.5 }),
  h('circle', { cx: 14, cy: 4.5, r: 1.75, 'stroke-width': 1.5 }),
  h('circle', { cx: 10, cy: 15.5, r: 1.75, 'stroke-width': 1.5 }),
  h('path', { d: 'M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75', 'stroke-width': 1.5, 'stroke-linecap': 'round' }),
])

const provenanceBuilder = useProvenanceBuilder()
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

// --- Package ---------------------------------------------------------------
// A package is a deliverable: the panel states what the bundle holds, warns
// when an input has moved on, and offers the rebuild. It deliberately does not
// list members — that is lineage, and Lineage already draws it.

const packageManifest = ref(null)
const packageStatus = ref(null)
const rebuildingPackage = ref(false)
let packageLoadToken = 0

const packageMediaId = computed(() => {
  const item = props.currentItem
  if (!item || getMediaType(item) !== 'package') return null
  return mediaIdOf(item)
})

function fileCountLabel(count) {
  return `${count} ${count === 1 ? 'file' : 'files'}`
}

const packageRows = computed(() => {
  const status = packageStatus.value
  if (!status) return []
  const rows = (status.runs || []).map(run => ({
    key: `run-${run.id}`,
    label: run.recipe?.display_name || run.recipe?.id || (run.root || '').replace(/\/$/, '') || 'Files',
    value: fileCountLabel(run.file_count || 0),
  }))
  const extras = packageManifest.value?.extras?.length || 0
  if (extras) rows.push({ key: 'extras', label: 'Extras', value: fileCountLabel(extras) })
  if (!rows.length) {
    const count = (status.members || []).length
    rows.push({ key: 'contents', label: 'Contents', value: `${count} ${count === 1 ? 'item' : 'items'}` })
  }
  return rows
})

async function loadPackageInfo(mediaId) {
  const token = ++packageLoadToken
  if (!mediaId) {
    packageManifest.value = null
    packageStatus.value = null
    return
  }
  try {
    const { data } = await axios.get(`${getApiBase()}/media/${mediaId}/package`)
    if (token !== packageLoadToken) return
    packageManifest.value = data.manifest
    packageStatus.value = data.status
  } catch (error) {
    if (token !== packageLoadToken) return
    packageManifest.value = null
    packageStatus.value = null
  }
}

watch(packageMediaId, (mediaId) => { void loadPackageInfo(mediaId) }, { immediate: true })

async function rebuildPackage() {
  const assetId = packageStatus.value?.asset_id ?? props.currentItem?.asset_id
  if (!assetId || rebuildingPackage.value) return
  rebuildingPackage.value = true
  try {
    const { data } = await axios.post(`${getApiBase()}/assets/${assetId}/package/rebuild`, {})
    addToast(`Rebuilt as revision ${data?.revision_number ?? ''}`.trim(), 'success')
    // The rebuild is a new revision with a new payload: reload from it, and let
    // the host refresh the asset head it is projecting.
    await loadPackageInfo(data?.media_id ?? packageMediaId.value)
    emit('package-rebuilt', assetId)
  } catch (error) {
    addToast(error?.response?.data?.detail || error?.message || 'Rebuild failed.', 'error', 6000)
  } finally {
    rebuildingPackage.value = false
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

// A lineage step's menu acts on that step's media, not the item on stage.
function openStepMenu(event, step) {
  const ownId = mediaIdOf(props.currentItem || {})
  if (!step?.mediaId || step.mediaId === ownId) return openContextMenu(event)
  const rect = event.currentTarget.getBoundingClientRect()
  contextMenu.showAt({ x: rect.left, y: rect.bottom + 4, mediaId: step.mediaId })
}

// Face overlay visibility (self-contained)
const visibleFaceOverlays = ref(new Set())

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
  if (!props.currentItem?.file_path || !isDesktopMode) return
  try {
    const { desktop } = await import('../desktop')
    await desktop.revealItemInDir(props.currentItem.file_path)
  } catch (error) {
    console.error('Failed to reveal in Finder:', error)
    addToast('Could not show file in Finder', 'error')
  }
}

// How this was made (steps newest-first, relations, file facts) — the one
// shared reading of generation_metadata (utils/mediaProvenance).
const provenance = computed(() => provenanceBuilder.build(props.currentItem))
const provenanceView = computed(() => viewFromProvenance(provenance.value))

// Typeset file facts; the name row carries reveal/copy actions.
const fileInfoRows = computed(() => {
  const m = props.currentItem
  if (!m) return []
  const rows = factRows(provenance.value.fileFacts).map(row => (
    row.key === 'name' ? { ...row, actions: true } : row
  ))
  // Processing status rides along as a fact row once everything completed;
  // while anything is pending/running/failed it renders as its own section.
  if (hasVisualContent(m) && allProcessingDone.value) {
    rows.push({ key: 'processing', label: 'Processing', value: processingSummary.value, mono: false, valueClass: 'text-content-tertiary' })
  }
  return rows
})

// Auto-delete urgency on the §1.9 status buckets (the timer's tiers mapped,
// never a color): under an hour is failed-red, under a day warning-amber.
const expiryBucket = computed(() => {
  const tier = getRemainingTimeColor(props.currentItem?.expires_at)
  if (tier.includes('red')) return 'failed'
  if (tier.includes('orange') || tier.includes('yellow')) return 'warning'
  return 'queued'
})

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

// Local status vocabulary (clip_status/face_detection_status/vlm_caption_status)
// mapped onto the shared StatusBucket vocabulary — colors always come from
// statusColors.ts via StatusDot (DESIGN.md §1.9); this only knows the
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

// Expose visible face overlays for parent to use in rendering overlays
defineExpose({
  visibleFaceOverlays
})
</script>

<style scoped>
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

</style>
