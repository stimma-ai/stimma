<template>
  <!-- Only one mounted menu renders at a time; see useMediaContextMenuHost. -->
  <Teleport v-if="isRenderer" to="body">
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
    <!-- Each submenu teleports separately so this scrolling menu cannot clip
         its sheet or become its containing block during the reveal animation. -->
    <Transition name="menu">
    <div
      v-if="contextMenu.state.value.visible"
      ref="menuRef" data-escape-layer
      data-context-menu
      v-show="!isCoarsePointer || (!activeSubmenu && !activeGroup)"
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu py-1 min-w-[180px]"
      :style="[menuPosition, askWidth ? { width: `${askWidth}px` } : null]"
      @scroll.passive="updateMenuMore"
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
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <MagnifyingGlassIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Find similar</span>
        </button>

        <div v-if="hasClipEmbedding && targetCount <= 3" class="border-t border-edge-subtle my-1"></div>

        <button
          v-if="hasFaceEmbeddings"
          @click="handleFindSimilarFaces"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <FaceSmileIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Find similar faces</span>
        </button>

        <button
          @click="handleRestore"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ArrowUturnLeftIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Restore ${targetCount} Items` : 'Restore' }}</span>
        </button>

        <button
          @click="handlePermanentDelete"
          class="w-full px-3 py-2 text-left text-xs text-red-400 hover:bg-overlay-subtle flex items-center gap-2"
        >
          <TrashIcon class="w-4 h-4 flex-shrink-0" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Delete ${targetCount} Permanently` : 'Delete Permanently' }}</span>
        </button>

      </template>

      <!-- Normal View Actions -->
      <template v-else>
        <!-- A prompt aimed at what was right-clicked (pointer menus only; on a
             phone the prompt lives in the selection's Ask). Typed, it replaces
             the menu with what matches. -->
        <MenuAskRow
          v-if="!isCoarsePointer && targetMediaIds.length > 0"
          v-model:active="askActive"
          :media-ids="targetMediaIds"
          :kind="askKind"
          :project-id="currentProjectId ?? null"
          @sent="onAskSent"
        />
        <template v-if="!askActive">
        <!-- Bare Media (for example a grid cell or chat working result) can be kept explicitly. -->
        <button
          v-if="targetAssetIds.length === 0 && targetMediaIds.length > 0"
          @click="handleKeepInAllAssets"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <BookmarkIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ targetMediaIds.length === 1 ? 'Keep in All Assets' : `Keep ${targetMediaIds.length} in All Assets` }}</span>
        </button>

        <div v-if="targetAssetIds.length === 0 && targetMediaIds.length > 0" class="border-t border-edge-subtle my-1"></div>

        <!-- Sheet: the identity and the marker toggles share one row. Elsewhere the
             wrapper is a plain block and only the marker row shows. -->
        <div class="coarse:flex coarse:items-center coarse:gap-3 coarse:pl-4 coarse:pr-2 coarse:border-b coarse:border-edge-subtle">
        <!-- Sheet only, and only when the sheet has height to spare: which item(s) the actions apply to. -->
        <div
          v-if="isCoarsePointer && selectionSummary"
          class="hidden min-w-0 flex-1 items-center gap-3 [@media(min-height:720px)]:flex"
          data-testid="menu-selection-summary"
        >
          <MediaImage
            v-if="targetMediaIds.length > 0"
            :media-id="targetMediaIds[0]"
            thumbnail
            :thumbnail-size="128"
            :draggable="false"
            :enable-context-menu="false"
            container-class="h-10 w-10 flex-none rounded-media bg-matte"
            img-class="h-full w-full object-cover"
          />
          <div class="min-w-0">
            <div class="truncate text-[14px] font-medium text-content">{{ selectionSummary.title }}</div>
            <div class="truncate font-mono text-[12px] text-content-tertiary">{{ selectionSummary.detail }}</div>
          </div>
        </div>

        <!-- Marker toggles row -->
        <div v-if="markers.length > 0" class="flex items-center gap-1 px-2 py-1.5 border-b border-edge-subtle coarse:flex-none coarse:gap-0 coarse:px-0 coarse:py-0 coarse:border-b-0 coarse:ml-auto" role="group" aria-label="Markers">
          <button
            v-for="marker in markers"
            :key="marker.id"
            @click="handleToggleMarker(marker)"
            :title="hasMarker(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
            :aria-label="hasMarker(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
            :aria-pressed="hasMarker(marker.id)"
            :class="[
              'w-7 h-7 coarse:w-11 coarse:h-11 rounded-md flex items-center justify-center transition-colors',
              hasMarker(marker.id) ? 'bg-overlay-light' : 'hover:bg-overlay-subtle'
            ]"
          >
            <span
              class="w-4 h-4 icon-container"
              :class="hasMarker(marker.id) ? '' : 'text-content-tertiary [&_svg]:fill-none [&_svg]:stroke-current [&_svg]:stroke-[1.75] [&_svg]:[stroke-linejoin:round]'"
              :style="hasMarker(marker.id) ? { color: marker.color } : undefined"
              v-html="sanitizeSvg(marker.icon_svg)"
            />
          </button>
        </div>
        </div>

        <!-- Edit (single image only): opens the asset's own edit mode, the
             Darkroom. Editing is a primary action on an image, not a routing
             operation, so it leads the menu. -->
        <button
          v-if="isImage && !isMultiple"
          @click="handleEditImage"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <PencilIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Edit</span>
        </button>

        <!-- Tags -->
        <button
          @click="handleEditTags"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <TagIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Tags (${targetCount} items)` : 'Tags' }}</span>
        </button>


        <!-- Collections -->
        <div
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('collection', $event)"
          @click.stop="openSubmenu('collection', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="collectionTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <Squares2X2Icon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">{{ isMultiple ? `Collections (${targetCount} items)` : 'Collections' }}</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'collection')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'collection'"
            ref="collectionSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[260px] max-h-[420px] flex flex-col"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <div class="px-2 py-1.5 border-b border-edge-subtle flex-shrink-0">
              <div class="relative">
                <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted" :stroke-width="1.75" />
                <input
                  ref="collectionSearchInputRef"
                  v-model="collectionSearchQuery"
                  type="text"
                  placeholder="Find a collection"
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
                />
              </div>
            </div>

            <div class="min-h-0 overflow-y-auto flex-1">
              <button
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
                :disabled="creatingCollectionQuickAdd"
                @click="handleCreateCollectionQuickAdd"
              >
                <PlusIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                <span>{{ creatingCollectionQuickAdd ? 'Creating...' : 'New collection' }}</span>
              </button>

              <div class="border-t border-edge-subtle my-1"></div>

              <div v-if="loadingCollections" class="px-3 py-2 text-xs text-content-tertiary">Loading collections...</div>
              <div v-else-if="filteredCollections.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No matching collections</div>

              <button
                v-for="collection in filteredCollections"
                :key="collection.id"
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
                :disabled="savingCollectionQuickAddId === collection.id"
                @click="handleQuickAddToCollection(collection.id)"
              >
                <Squares2X2Icon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                <div class="min-w-0 flex-1">
                  <div class="truncate" :class="collection.name ? 'text-content' : 'italic text-content-muted'">{{ collection.name || 'Name this collection...' }}</div>
                  <div class="truncate text-[10px] text-content-muted">{{ formatCollectionSubmenuSummary(collection) }}</div>
                </div>
              </button>
            </div>

          </div>
          </Teleport>
        </div>

        <!-- Projects -->
        <div
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('project', $event)"
          @click.stop="openSubmenu('project', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="projectTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <ArchiveBoxIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">{{ isMultiple ? `Projects (${targetCount} items)` : 'Projects' }}</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'project')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'project'"
            ref="projectSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[260px]"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <ProjectPickerSubmenu
              :media-ids="targetMediaIds"
              :asset-ids="targetAssetIds"
              mode="assign"
              :membership="projectMembership"
              :pinned-project-id="currentProjectId"
              @changed="handleProjectMembershipChanged"
              @close="contextMenu.hide(); activeSubmenu = null"
            />
          </div>
          </Teleport>
        </div>

        <!-- Remove from Project: whenever a target is in the menu's project -->
        <template v-if="showRemoveFromProject">
          <button
            @click="handleRemoveFromProject"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <ArchiveBoxIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span>{{ isMultiple ? `Remove ${targetCount} from Project` : 'Remove from Project' }}</span>
          </button>
        </template>

        <!-- Collection-specific section -->
        <template v-if="inCollection">
          <button
            @click="handleRemoveFromCollection"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <Squares2X2Icon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span>{{ isMultiple ? `Remove ${targetCount} from Collection` : 'Remove from Collection' }}</span>
          </button>
        </template>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Create Set (multiple atomic items only) -->
        <button
          v-if="canCreateSet"
          @click="handleCreateSet"
          :disabled="creatingSet"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2 disabled:opacity-50"
        >
          <Square3Stack3DIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ creatingSet ? 'Creating...' : `Create Set (${targetCount} items)` }}</span>
        </button>

        <!-- Explode action - only for sets/grids -->
        <button
          v-if="!isMultiple && isSetOrGrid"
          @click="handleExplode"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ArrowDownOnSquareStackIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Save {{ isSet ? 'members' : 'cells' }} as assets…</span>
        </button>

        <!-- What the view this item came from offers on it (Tool View: Use in your prompt) -->
        <button
          v-for="a in viewActions"
          :key="a.label"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          data-view-action
          @click="runViewAction(a)"
        >
          <CheckCircleIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ a.label }}</span>
        </button>

        <!-- Remix (single item only, not grids, sprites or packages) - with submenu -->
        <div
          v-if="!isMultiple && !isGrid && !isSprite && !isPackage"
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('generate', $event)"
          @click.stop="openSubmenu('generate', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="generateTriggerRef"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <ArrowPathRoundedSquareIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">Remix</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <!-- Invisible bridge to submenu - prevents mouseleave when traversing gap -->
          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'generate')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <!-- Generate submenu -->
          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'generate'"
            ref="generateSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 w-[300px] max-h-[min(640px,calc(100vh-24px))] flex flex-col"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <!-- Filter box -->
            <div class="px-2.5 py-2 border-b border-edge-subtle flex-shrink-0">
              <div class="relative">
                <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-content-muted" :stroke-width="1.75" />
                <input
                  ref="generateSearchInputRef"
                  v-model="generateSearchQuery"
                  type="text"
                  placeholder="Filter tools..."
                  class="w-full bg-overlay-subtle border border-edge-subtle rounded-md px-2.5 py-1.5 pl-8 text-[13px] text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
                />
              </div>
            </div>

            <div class="min-h-0 overflow-y-auto flex-1">
              <!-- Original tool section (if exists) -->
              <template v-if="!generateSearchQuery.trim() && originalTool">
                <div class="px-3.5 pt-2.5 pb-1 text-xs font-semibold text-content-secondary">
                  Original
                </div>
                <button
                  @click="originalToolInstance ? sendToGenerateToolInstance({ tab: originalToolInstance, tool: originalTool }) : sendToGenerateTool(originalTool)"
                  class="w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-subtle flex items-center gap-2.5"
                >
                  <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(originalTool) ? '' : 'text-content-tertiary'">
                    <ToolIcon :tool="originalTool" size="xs" :bare="true" :ring="false" />
                  </div>
                  <span class="flex-1 min-w-0 truncate">{{ originalToolInstance ? (originalToolInstance.customName || originalToolInstance.displayName) : originalTool.name }}</span>
                  <span
                    v-if="originalToolInstance?.projectName"
                    class="flex-shrink-0 text-[9px] text-content-tertiary bg-overlay-subtle rounded px-1 py-0.5 truncate max-w-[70px]"
                  >{{ originalToolInstance.projectName }}</span>
                  <ToolProviderLabel :cloud="isStimmaCloudTool(originalTool)" :provider-name="originalTool.provider_name" class="pl-3" />
                </button>
                <div class="border-t border-edge-subtle my-1"></div>
              </template>

              <!-- Active tool instances: eligible open tool tabs (incl. renamed
                   stations), targeted exactly. Mirrors Send to Tool's section. -->
              <template v-if="filteredRemixOpenInstances.length > 0">
                <div class="px-3.5 pt-2.5 pb-1 text-xs font-semibold text-content-secondary">
                  Active tools
                </div>
                <button
                  v-for="row in filteredRemixOpenInstances"
                  :key="`instance-${row.tab.id}`"
                  @click="sendToGenerateToolInstance(row)"
                  class="w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-subtle flex items-center gap-2.5"
                >
                  <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(row.tool) ? '' : 'text-content-tertiary'">
                    <ToolIcon :tool="row.tool" size="xs" :bare="true" :ring="false" />
                  </div>
                  <span class="flex-1 min-w-0 truncate">{{ row.tab.customName || row.tab.displayName }}</span>
                  <span
                    v-if="row.tab.projectName"
                    class="flex-shrink-0 text-[9px] text-content-tertiary bg-overlay-subtle rounded px-1 py-0.5 truncate max-w-[70px]"
                  >{{ row.tab.projectName }}</span>
                  <ToolProviderLabel :cloud="isStimmaCloudTool(row.tool)" :provider-name="row.tool.provider_name" class="pl-3" />
                </button>
                <div class="border-t border-edge-subtle my-1"></div>
              </template>
              <div v-if="loadingGenerateTools" class="px-3.5 py-2 text-xs text-content-tertiary">Loading tools...</div>
              <div v-else-if="generateMoreTools.length === 0" class="px-3.5 py-2 text-xs text-content-tertiary">No tools available</div>
              <template v-else-if="generateSearchQuery.trim()">
                <!-- Filtered results (flat, no sections) -->
                <div v-if="filteredGenerateTools.length === 0" class="px-3.5 py-2 text-xs text-content-tertiary">No matching tools</div>
                <button
                  v-for="tool in filteredGenerateTools"
                  :key="tool.full_tool_id"
                  @click="sendToGenerateTool(tool)"
                  class="w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-subtle flex items-center gap-2.5"
                >
                  <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
                    <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
                  </div>
                  <span class="flex-1 min-w-0 truncate">{{ tool.name }}</span>
                  <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
                </button>
              </template>
              <template v-else>
                <!-- Recent tools section -->
                <template v-if="recentGenerateTools.length > 0">
                  <div class="px-3.5 pt-2.5 pb-1 text-xs font-semibold text-content-secondary">
                    Recent
                  </div>
                  <button
                    v-for="tool in recentGenerateTools"
                    :key="`recent-${tool.full_tool_id}`"
                    @click="sendToGenerateTool(tool)"
                    class="w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-subtle flex items-center gap-2.5"
                  >
                    <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
                      <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
                    </div>
                    <span class="flex-1 min-w-0 truncate">{{ tool.name }}</span>
                    <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
                  </button>
                </template>

                <!-- All tools section -->
                <div v-if="recentGenerateTools.length > 0" class="border-t border-edge-subtle my-1"></div>
                <div class="px-3.5 pt-2.5 pb-1 text-xs font-semibold text-content-secondary">
                  {{ originalTool ? 'All tools' : 'Generate image' }}
                </div>
                <button
                  v-for="tool in otherGenerateTools"
                  :key="tool.full_tool_id"
                  @click="sendToGenerateTool(tool)"
                  class="w-full px-3.5 py-2 text-left text-[13px] text-content hover:bg-overlay-subtle flex items-center gap-2.5"
                >
                  <div class="w-3.5 h-3.5 flex-shrink-0" :class="isStimmaCloudTool(tool) ? '' : 'text-content-tertiary'">
                    <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
                  </div>
                  <span class="flex-1 min-w-0 truncate">{{ tool.name }}</span>
                  <ToolProviderLabel :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" class="pl-3" />
                </button>
              </template>
            </div>
          </div>
          </Teleport>
        </div>

<button
          v-if="groupedSend"
          type="button"
          data-testid="menu-group-send"
          @click.stop="openGroup('send', $event)"
          @mouseenter="!isCoarsePointer && openGroup('send', $event)"
          @mouseleave="closeSubmenuDelayed"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <PaperAirplaneIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span class="flex-1">Send to</span>
          <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
        </button>

        <Teleport to="body" :disabled="!groupedSend">
        <div
          v-if="!groupedSend || activeGroup === 'send'"
          ref="groupSheetRef"
          v-show="!groupedSend || !isCoarsePointer || !activeSubmenu"
          v-bind="groupBind(groupedSend)"
        >
          <template v-if="groupedSend && isCoarsePointer">
            <button type="button" class="sheet-row flex-none" @click.stop="activeGroup = null"><span aria-hidden="true">‹</span> Back to actions</button>
            <div class="sheet-section !text-xs !normal-case !tracking-normal !text-content-secondary" aria-hidden="true">Send to</div>
          </template>

        <!-- Send to Tool - with submenu (hidden when grids are selected) -->
        <div
          v-if="!hasGridInSelection"
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('tool', $event)"
          @click.stop="openSubmenu('tool', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="toolTriggerRef"
            aria-label="Send to tool"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <WrenchScrewdriverIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">Tool</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <!-- Invisible bridge to submenu -->
          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'tool')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <!-- Tool submenu (accordion with task type expand/collapse) -->
          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'tool'"
            ref="toolSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 w-[300px] max-h-[min(640px,calc(100vh-24px))] overflow-y-auto"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop="lockSubmenuOpen"
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <TaskTypeToolList
              ref="toolListRef"
              :tools="sendToTools"
              :media-type="currentMediaType"
              :media-types="currentSelectionMediaTypes"
              :selection-count="isSet ? 1 : targetCount"
              :loading="loadingTools"
              show-open-instances
              shift-adds
              @select="handleToolSelect"
              @select-instance="handleToolInstanceSelect"
            />
          </div>
          </Teleport>
        </div>

        <!-- Send to Chat - with submenu -->
        <div
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('chat', $event)"
          @click.stop="openSubmenu('chat', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="chatTriggerRef"
            aria-label="Send to chat"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <ChatBubbleLeftRightIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">Chat</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <!-- Invisible bridge to submenu -->
          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'chat')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <!-- Chat submenu -->
          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'chat'"
            ref="chatSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[200px] max-h-[400px] overflow-y-auto"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <div v-if="loadingChats" class="px-3 py-2 text-xs text-content-tertiary">Loading chats...</div>
            <template v-else>
              <!-- New chat option -->
              <button
                @click="sendToNewChat"
                :class="['w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2', chats.length > 0 ? 'border-b border-edge-subtle' : '']"
              >
                <PlusIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                <span class="font-medium">New chat</span>
              </button>
              <!-- Existing chats -->
              <button
                v-for="chat in chats"
                :key="chat.id"
                @click="sendToChat(chat)"
                class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
              >
                <ChatBubbleLeftRightIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                <span class="truncate flex-1">{{ chat.name || 'Untitled' }}</span>
              </button>
            </template>
          </div>
          </Teleport>
        </div>

        <!-- Send to Flow - flow submenu, then destination submenu -->
        <div
          v-if="flowsEnabled"
          class="relative"
          @mouseenter="!isCoarsePointer && openSubmenu('flow', $event)"
          @click.stop="openSubmenu('flow', $event)"
          @mouseleave="closeSubmenuDelayed"
        >
          <button
            ref="flowTriggerRef"
            aria-label="Send to flow"
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          >
            <BoltIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
            <span class="flex-1">Flow</span>
            <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
          </button>

          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'flow')"
            class="fixed z-submenu"
            :style="submenuBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'flow'"
            ref="flowSubmenuRef" data-escape-layer
            v-show="!isCoarsePointer || !activeFlowDestination"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[220px] max-w-[300px] max-h-[400px] overflow-y-auto"
            :style="submenuPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="activeSubmenu = null"><span aria-hidden="true">‹</span> {{ activeGroup ? 'Back' : 'Back to actions' }}</button>
            <div v-if="loadingFlows" class="px-3 py-2 text-xs text-content-tertiary">Loading flows...</div>
            <template v-else>
              <button
                @click="sendToNewFlow"
                @mouseenter="!isCoarsePointer && clearFlowDestination()"
                :class="['w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2', flows.length > 0 ? 'border-b border-edge-subtle' : '']"
              >
                <PlusIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                <span class="font-medium">New flow</span>
              </button>
              <div
                v-for="flow in flows"
                :key="flow.id"
                @mouseenter="!isCoarsePointer && openFlowDestination(flow, $event)"
                @click.stop="openFlowDestination(flow, $event)"
              >
                <button class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2">
                  <BoltIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
                  <span class="truncate flex-1">{{ flow.name || 'Untitled' }}</span>
                  <ChevronRightIcon class="w-3 h-3 flex-shrink-0 text-content-muted" :stroke-width="2" />
                </button>
              </div>
            </template>
          </div>
          </Teleport>

          <Teleport to="body">
          <div
            v-if="!isCoarsePointer && (activeSubmenu === 'flow' && activeFlowDestination)"
            class="fixed z-submenu"
            :style="flowDestinationBridgeStyle"
            @mouseenter="cancelSubmenuClose"
          />
          </Teleport>

          <Teleport to="body">
          <div
            v-if="activeSubmenu === 'flow' && activeFlowDestination"
            ref="flowDestinationSubmenuRef" data-escape-layer
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[190px] max-w-[280px]"
            :style="flowDestinationPosition"
            @mouseenter="cancelSubmenuClose"
            @mouseleave="closeSubmenuDelayed"
            @click.stop
          >
            <button v-if="isCoarsePointer" type="button" class="sheet-row flex-none" @click.stop="clearFlowDestination()"><span aria-hidden="true">‹</span> Back to flows</button>
            <button
              @click="sendToFlowChat(activeFlowDestination)"
              class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
            >
              <ChatBubbleOvalLeftEllipsisIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
              <span>Attach to message</span>
            </button>
            <button
              v-for="field in activeFlowInputFields"
              :key="field.name"
              @click="sendToFlowInput(activeFlowDestination, field)"
              class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
            >
              <PhotoIcon class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
              <span class="truncate">{{ field.label }}</span>
            </button>
          </div>
          </Teleport>
        </div>

        </div>
        </Teleport>


<button
          v-if="groupedExplore"
          type="button"
          data-testid="menu-group-explore"
          @click.stop="openGroup('explore', $event)"
          @mouseenter="!isCoarsePointer && openGroup('explore', $event)"
          @mouseleave="closeSubmenuDelayed"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <MagnifyingGlassIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span class="flex-1">Explore</span>
          <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
        </button>

        <Teleport to="body" :disabled="!groupedExplore">
        <div
          v-if="!groupedExplore || activeGroup === 'explore'"
          :ref="groupedExplore ? 'groupSheetRef' : undefined"
          v-show="!groupedExplore || !isCoarsePointer || !activeSubmenu"
          v-bind="groupBind(groupedExplore)"
        >
          <template v-if="groupedExplore && isCoarsePointer">
            <button type="button" class="sheet-row flex-none" @click.stop="activeGroup = null"><span aria-hidden="true">‹</span> Back to actions</button>
            <div class="sheet-section !text-xs !normal-case !tracking-normal !text-content-secondary" aria-hidden="true">Explore</div>
          </template>

        <!-- Find Similar (up to 3 items) -->
        <button
          v-if="hasClipEmbedding && targetCount <= 3"
          @click="handleFindSimilar"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <MagnifyingGlassIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Find similar</span>
        </button>

        <button
          v-if="hasFaceEmbeddings"
          @click="handleFindSimilarFaces"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <FaceSmileIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Find similar faces</span>
        </button>

        <!-- Compare (exactly 2 images) -->
        <button
          v-if="targetCount === 2 && !isVideo"
          @click="handleCompare"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ViewColumnsIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Compare</span>
        </button>

        <!-- View Lineage (single item only) -->
        <button
          v-if="!isMultiple"
          @click="handleViewLineage"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" class="w-4 h-4 flex-shrink-0 text-content-tertiary">
            <circle cx="6" cy="4.5" r="1.75" stroke-width="1.75" />
            <circle cx="14" cy="4.5" r="1.75" stroke-width="1.75" />
            <circle cx="10" cy="15.5" r="1.75" stroke-width="1.75" />
            <path d="M6 6.25V8.5C6 10 7.5 11 10 11M14 6.25V8.5C14 10 12.5 11 10 11M10 11V13.75" stroke-width="1.75" stroke-linecap="round" />
          </svg>
          <span>View lineage</span>
        </button>
        </div>
        </Teleport>

        <div class="border-t border-edge-subtle my-1"></div>

<button
          v-if="groupedShare"
          type="button"
          data-testid="menu-group-share"
          @click.stop="openGroup('share', $event)"
          @mouseenter="!isCoarsePointer && openGroup('share', $event)"
          @mouseleave="closeSubmenuDelayed"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ShareIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span class="flex-1">Share and export</span>
          <ChevronRightIcon class="w-3 h-3 text-content-muted" :stroke-width="2" />
        </button>

        <Teleport to="body" :disabled="!groupedShare">
        <div
          v-if="!groupedShare || activeGroup === 'share'"
          :ref="groupedShare ? 'groupSheetRef' : undefined"
          v-show="!groupedShare || !isCoarsePointer || !activeSubmenu"
          v-bind="groupBind(groupedShare)"
        >
          <template v-if="groupedShare && isCoarsePointer">
            <button type="button" class="sheet-row flex-none" @click.stop="activeGroup = null"><span aria-hidden="true">‹</span> Back to actions</button>
            <div class="sheet-section !text-xs !normal-case !tracking-normal !text-content-secondary" aria-hidden="true">Share and export</div>
          </template>

        <!-- Share link (public link, every media type; single item only) -->
        <button
          v-if="!isMultiple"
          data-testid="menu-share-link"
          @click="handleShareLink"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <LinkIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Share link…</span>
        </button>

        <!-- Share file (OS share sheet; single-file items where the platform supports it) -->
        <button
          v-if="!isMultiple && nativeShareSupported && !isMultiFileItem"
          data-testid="menu-share-file"
          @click="handleNativeShare"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ArrowUpTrayIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>Share file…</span>
        </button>

        <!-- Print -->
        <button
          @click="handlePrint"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <PrinterIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Print ${targetCount}` : 'Print' }}</span>
        </button>

        <!-- Export -->
        <button
          @click="handleDownload"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        >
          <ArrowDownTrayIcon class="w-4 h-4 flex-shrink-0 text-content-tertiary" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Export ${targetCount}` : 'Export' }}</span>
        </button>

        </div>
        </Teleport>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Move to Trash -->
        <button
          @click="handleMoveToTrash"
          class="w-full px-3 py-2 text-left text-xs text-red-400 hover:bg-overlay-subtle flex items-center gap-2"
        >
          <TrashIcon class="w-4 h-4 flex-shrink-0" :stroke-width="1.75" />
          <span>{{ isMultiple ? `Move ${targetCount} to trash` : 'Move to trash' }}</span>
        </button>
        </template>
      </template>

      <!-- Sheet only: the actions run past the bottom edge. The cue is its own
           strip with a hard edge, so no action is ever half-covered by it. -->
      <div v-if="isCoarsePointer && menuHasMore" class="pointer-events-none sticky bottom-[calc(-0.5rem-var(--safe-bottom,0px))] z-10 flex h-[calc(2rem+var(--safe-bottom,0px))] items-center justify-center gap-1 border-t border-edge-subtle bg-surface pb-[var(--safe-bottom,0px)] text-xs text-content-tertiary" aria-hidden="true">
        <ChevronDownIcon class="h-3.5 w-3.5" :stroke-width="2" />
        <span>Scroll for more actions</span>
      </div>
    </div>
    </Transition>

    <ConfirmDialog
      :show="showExplodeConfirm"
      :title="`Save ${explodeSummary?.asset_type === 'set' ? 'members' : 'cells'} as assets?`"
      :confirm-label="explodingContainer ? 'Saving…' : 'Save as assets'"
      :busy="explodingContainer"
      @confirm="confirmExplode"
      @cancel="closeExplodeConfirm"
    >
      Create {{ explodeSummary?.to_create || 0 }} new
      {{ explodeSummary?.to_create === 1 ? 'asset' : 'assets' }} from embedded
      {{ explodeSummary?.asset_type === 'set' ? 'members' : 'cells' }}.
      {{ (explodeSummary?.linked || 0) + (explodeSummary?.already_saved || 0) }} existing
      {{ ((explodeSummary?.linked || 0) + (explodeSummary?.already_saved || 0)) === 1 ? 'asset will' : 'assets will' }} be reused.
      When complete, this {{ explodeSummary?.asset_type || 'container' }} will move to Trash so the operation can be undone.
    </ConfirmDialog>

    <!-- Tag picker (submenu of this menu) -->
    <TagPickerPopover
      :visible="showTagEditor"
      :anchor="tagPickerAnchor"
      :submenu-of="menuRef"
      :media-ids="targetMediaIds"
      :asset-ids="targetAssetIds"
      :current-tag-counts="currentTagCounts"
      @close="showTagEditor = false"
      @changed="emit('refresh')"
    />


    <!-- Export Modal -->
    <ExportModal
      :show="showExportModal"
      :media-ids="exportMediaIds"
      :media-items="exportMediaItems"
      @close="showExportModal = false"
    />

    <NativeShareDialog v-if="nativeShareMediaId" :media-id="nativeShareMediaId" @close="nativeShareMediaId = null" />
  </Teleport>
</template>

<script setup lang="ts">
import { flowsEnabled } from '../../composables/useExperimentalFlows'
import { useAssetTrash } from '../../composables/useAssetTrash'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { ref, computed, onMounted, onUnmounted, onUpdated, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaContextMenu, useMediaContextMenuHost, broadcastMediaContextMenuEvent, mediaMenuActions, type MediaMenuAction } from '../../composables/useMediaContextMenu'
import { setPendingMedia } from '../../composables/usePendingMedia'
import { useContextMenuPosition, useSubmenuPosition, computeSubmenuX, computeBridgeStyle, computeSubmenuStyle, measureMenu, SHEET_MENU_STYLE } from '../../composables/useContextMenuPosition'
import { useMediaApi } from '../../composables/useMediaApi'
import { useAssetApi } from '../../composables/useAssetApi'
import { addToast } from '../../composables/useToasts'
import { useProvidersApi, type ProviderToolSummary } from '../../composables/useProvidersApi'
import { useSendToTool } from '../../composables/useSendToTool'
import { getCurrentProfileId } from '../../composables/useProfile'
import TagPickerPopover from '../TagPickerPopover.vue'
import ProjectPickerSubmenu from '../ProjectPickerSubmenu.vue'
import ExportModal from '../ExportModal.vue'
import NativeShareDialog from '../NativeShareDialog.vue'
import { ChevronDownIcon, ArchiveBoxIcon, CheckCircleIcon, ArrowDownOnSquareStackIcon, ArrowDownTrayIcon, ArrowPathRoundedSquareIcon, ArrowUpTrayIcon, ArrowUturnLeftIcon, BoltIcon, BookmarkIcon, ChatBubbleLeftRightIcon, ChatBubbleOvalLeftEllipsisIcon, ChevronRightIcon, FaceSmileIcon, LinkIcon, MagnifyingGlassIcon, PaperAirplaneIcon, PencilIcon, PhotoIcon, PlusIcon, PrinterIcon, ShareIcon, Square3Stack3DIcon, Squares2X2Icon, TagIcon, TrashIcon, ViewColumnsIcon, WrenchScrewdriverIcon } from '@heroicons/vue/24/outline'
import { useShareDialog } from '../../composables/useShareDialog'
import { desktop } from '../../desktop'
import { supportsNativeShare } from '../../utils/nativeShare'
import ConfirmDialog from '../ui/ConfirmDialog.vue'
import TaskTypeToolList from '../TaskTypeToolList.vue'
import ToolIcon from '../tools/ToolIcon.vue'
import MediaImage from './MediaImage.vue'
import ToolProviderLabel from '../tools/ToolProviderLabel.vue'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { makeStorageKey } from '../../utils/storageKeys'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { planToolHandoff } from '../../utils/toolHandoff'
import { isImage as isImageType, isVideo as isVideoType, getMediaType, MediaType } from '../../utils/mediaTypes'
import axios from 'axios'
import { useWorkingContext } from '../../composables/useWorkingContext'
import { announceProjectAssetsChanged, applyMembershipChange, canRemoveFromProject, countMemberships, projectListParam, resolveProjectId } from '../../utils/projectScope'
import { useWorkspaceTabs, toolInstanceRoute, toolTabRoute, type WorkspaceTab } from '../../composables/useWorkspaceTabs'
import { useViewport } from '../../composables/useViewport'
import { openImageEditor } from '../../imageEditor/stack/openImageEditor'
import { usePrint } from '../../composables/usePrint'
import { useTelemetry } from '../../composables/useTelemetry'
import { assetIdOf, hasAssetIdentity, mediaIdOf } from '../../utils/assetIdentity'
import { useFlowsApi, type Flow } from '../../composables/useFlowsApi'
import { flowMediaInputFields, fieldAcceptsDraggedType, type FlowMediaInputField } from '../../utils/flowMediaInputs'
import { syncedStorage } from '../../utils/workspaceStore'
import MenuAskRow from './MenuAskRow.vue'

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
  original_generator_instance_id?: string | null
}

const router = useRouter()
const { activeProjectId: workingProjectId } = useWorkingContext()
const { tabs: workspaceTabs, resolveToolInstance } = useWorkspaceTabs()
const contextMenu = useMediaContextMenu()
const { trashAssetsWithUndo } = useAssetTrash()
const { isCoarsePointer, allowsAutofocus } = useViewport()
const { printAssetDetail, printContactSheet } = usePrint()
const { deleteMedia, restoreFromTrash, permanentlyDeleteMedia, getMediaFileUrl, getMediaItem, getMediaFaces, getMarkers, addMarkerToMedia, removeMarkerFromMedia, downloadMedia, bulkDeleteMedia, bulkRestoreFromTrash, bulkPermanentlyDelete, bulkMarkerOperation, createSetFromMedia, getThumbnailUrl, getCollections, createCollection, addMediaToCollection, removeMediaFromProject, getMediaProjects } = useMediaApi()
const {
  getAssetBrowserItem,
  addMarker: addMarkerToAsset,
  removeMarker: removeMarkerFromAsset,
  bulkMarker: bulkAssetMarkerOperation,
  addToCollection: addAssetsToCollection,
  removeFromCollectionSection,
  removeFromProject: removeAssetFromProject,
  getProjects: getAssetProjects,
  restore: restoreAsset,
  restoreMany: restoreAssets,
  permanentlyDelete: permanentlyDeleteAsset,
  permanentlyDeleteMany: permanentlyDeleteAssets,
  promoteContextualMedia,
} = useAssetApi()
const { listAvailableTools } = useProvidersApi()
const { sendToTool: sendToToolComposable } = useSendToTool()
const flowsApi = useFlowsApi()

const menuRef = ref<HTMLElement | null>(null)

// Sheet scroll cue: true while actions remain below the visible edge.
const menuHasMore = ref(false)
function updateMenuMore() {
  const el = menuRef.value
  menuHasMore.value = !!el && el.scrollHeight - el.scrollTop - el.clientHeight > 8
}
watch(menuRef, () => nextTick(updateMenuMore), { flush: 'post' })
onUpdated(() => nextTick(updateMenuMore))
const generateTriggerRef = ref<HTMLElement | null>(null)
const toolTriggerRef = ref<HTMLElement | null>(null)
const chatTriggerRef = ref<HTMLElement | null>(null)
const flowTriggerRef = ref<HTMLElement | null>(null)
const collectionTriggerRef = ref<HTMLElement | null>(null)
const generateSubmenuRef = ref<HTMLElement | null>(null)
const toolSubmenuRef = ref<HTMLElement | null>(null)
const chatSubmenuRef = ref<HTMLElement | null>(null)
const flowSubmenuRef = ref<HTMLElement | null>(null)
const flowDestinationSubmenuRef = ref<HTMLElement | null>(null)
const collectionSubmenuRef = ref<HTMLElement | null>(null)
const projectSubmenuRef = ref<HTMLElement | null>(null)
const projectTriggerRef = ref<HTMLElement | null>(null)

const activeSubmenu = ref<'generate' | 'tool' | 'chat' | 'flow' | 'collection' | 'project' | null>(null)

// Touch sheets fold related destinations behind one named row (a second sheet,
// and the destination's own list a third). Elsewhere the groups are transparent
// wrappers and every row stays where it was.
type MenuGroup = 'send' | 'explore' | 'share'
const activeGroup = ref<MenuGroup | null>(null)
const groupSheetRef = ref<HTMLElement | null>(null)
// On a desktop pointer the same groups are hover submenus beside the menu: a
// group panel opens next to the root menu and its destinations (Collections,
// Tool, Chat...) open as the usual submenus beside the panel.
// Collections and Projects stay two rows of the root menu, each opening its own list.
const groupedSend = computed(() => true)
const groupedExplore = computed(() => exploreRowCount.value >= 2)
const groupedShare = computed(() => isCoarsePointer.value || shareRowCount.value >= 2)
const groupTriggerRect = ref<DOMRect | null>(null)
const groupPosition = ref<Record<string, string>>({ top: '0px', left: '0px' })
function openGroup(group: MenuGroup, event?: MouseEvent) {
  if (!isCoarsePointer.value) {
    cancelSubmenuClose()
    const target = event?.currentTarget as HTMLElement | null
    if (target) groupTriggerRect.value = target.getBoundingClientRect()
    if (activeGroup.value !== group) activeSubmenu.value = null
  }
  activeGroup.value = group
}
function groupBind(grouped: boolean) {
  if (!grouped) return { class: 'contents' }
  if (isCoarsePointer.value) {
    return {
      class: 'fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1',
      style: SHEET_MENU_STYLE,
      'data-sheet-menu': '',
      'data-escape-layer': '',
    }
  }
  return {
    class: 'fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-submenu py-1 min-w-[200px]',
    style: groupPosition.value,
    'data-escape-layer': '',
    onMouseenter: cancelSubmenuClose,
    onMouseleave: closeSubmenuDelayed,
  }
}
const submenuCloseTimeout = ref<number | null>(null)
const submenuTriggerRect = ref<DOMRect | null>(null)
const submenuClickLockUntil = ref(0)
const activeFlowDestination = ref<Flow | null>(null)
const flowDestinationTriggerRect = ref<DOMRect | null>(null)

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
const collectionSearchInputRef = ref<HTMLInputElement | null>(null)
const collectionSearchQuery = ref('')

// Recent generate tools tracking
const RECENT_GENERATE_KEY = 'generate-more' as const
const MAX_RECENT = 5

function getRecentGenerateToolIds(): string[] {
  try {
    const key = makeStorageKey(RECENT_GENERATE_KEY, 'recent')
    const stored = syncedStorage.getItem(key)
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
    syncedStorage.setItem(key, JSON.stringify(recent.slice(0, MAX_RECENT)))
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
const tools = ref<ProviderToolSummary[]>([])
const loadingGenerateTools = ref(false)
const generateMoreTools = ref<GenerateMoreTool[]>([])

// Split generate tools into original and others
const originalTool = computed(() => generateMoreTools.value.find(t => t.is_original))
const otherGenerateTools = computed(() => generateMoreTools.value.filter(t => !t.is_original))

// Prefer the exact instance that produced this media while its tab still
// exists. generator_instance_id ends in a browser GUID, while feedScope is the
// stable tab-specific prefix before that suffix.
const originalToolInstance = computed(() => {
  const tool = originalTool.value
  const generatorId = tool?.original_generator_instance_id
  if (!tool || !generatorId) return undefined
  return (workspaceTabs.value as WorkspaceTab[]).find(tab =>
    tab.type === 'tool' &&
    (tab.projectId ?? null) === workingProjectId.value &&
    tab.entityId === tool.full_tool_id &&
    !!tab.instanceId &&
    !!tab.feedScope &&
    (generatorId === `tool-${tab.feedScope}` || generatorId.startsWith(`tool-${tab.feedScope}@@`))
  )
})

// Eligible open tool-instance tabs (incl. renamed stations), most-recently-
// active first. Eligibility = the tool appears in the remix tool list.
// resolveToolInstance skips named instances on purpose, so these rows are the
// only way remix can reach them; each row targets its exact tab.
const remixOpenInstances = computed(() => {
  const toolById = new Map(generateMoreTools.value.map(t => [t.full_tool_id, t]))
  return (workspaceTabs.value as WorkspaceTab[])
    .filter(t => t.type === 'tool' && (t.projectId ?? null) === workingProjectId.value && !!t.instanceId && toolById.has(t.entityId))
    .sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0))
    .slice(0, 5)
    .map(tab => ({ tab, tool: toolById.get(tab.entityId)! }))
})

const filteredRemixOpenInstances = computed(() => {
  const query = generateSearchQuery.value.trim().toLowerCase()
  if (!query) return remixOpenInstances.value
  return remixOpenInstances.value.filter(({ tab, tool }) =>
    (tab.customName || '').toLowerCase().includes(query) ||
    tab.displayName.toLowerCase().includes(query) ||
    tool.provider_name.toLowerCase().includes(query)
  )
})


// Chats data
const loadingChats = ref(false)
const chats = ref<Chat[]>([])
const loadingFlows = ref(false)
const flows = ref<Flow[]>([])
const loadingCollections = ref(false)
const collections = ref<any[]>([])
const lastCollectionsProjectId = ref<number | undefined>(undefined)
const lastChatsProjectId = ref<number | undefined>(undefined)
const lastFlowsProjectId = ref<number | undefined>(undefined)
const savingCollectionQuickAddId = ref<number | null>(null)
const creatingCollectionQuickAdd = ref(false)

// Markers data
const markers = ref<Marker[]>([])

// Modal visibility
const showTagEditor = ref(false)
const tagPickerAnchor = ref<HTMLElement | null>(null)
const showExportModal = ref(false)
const exportMediaIds = ref<number[]>([])
const exportMediaItems = ref<any[]>([])
const showExplodeConfirm = ref(false)
const explodingContainer = ref(false)
const explodeAssetId = ref<number | null>(null)
const explodeSummary = ref<any>(null)

const emitToParent = defineEmits<{
  (e: 'refresh'): void
  (e: 'permanent-delete', mediaId: number): void
}>()
// Menu events reach every mounted host, not just the one rendering the menu.
const { isRenderer } = useMediaContextMenuHost((name, ...args) => {
  if (name === 'refresh') emitToParent('refresh')
  else if (name === 'permanent-delete') emitToParent('permanent-delete', args[0] as number)
})
function emit(name: 'refresh' | 'permanent-delete', ...args: unknown[]) {
  broadcastMediaContextMenuEvent(name, ...args)
}

// Multi-selection computed properties
const targetMediaIds = computed<number[]>(() => (
  contextMenu.state.value.mediaIds || [contextMenu.state.value.mediaId].filter((id): id is number => id != null)
))
// A batch without every pick's asset stays a media batch: falling back to the
// clicked item's asset would aim asset actions at that one pick alone.
const targetAssetIds = computed<number[]>(() => (
  contextMenu.state.value.assetIds?.length
    ? contextMenu.state.value.assetIds
    : targetMediaIds.value.length > 1
      ? []
      : [contextMenu.state.value.assetId ?? mediaItem.value?.asset_id]
          .filter((id): id is number => id != null)
))
const targetIds = computed(() => targetAssetIds.value.length > 0 ? targetAssetIds.value : targetMediaIds.value)
const selectedItems = computed(() => contextMenu.state.value.selectedItems || [])
const isMultiple = computed(() => targetIds.value.length > 1)
const viewActions = computed(() => (isMultiple.value ? [] : mediaMenuActions(contextMenu.state.value.mediaId)))
function runViewAction(a: MediaMenuAction) {
  const at = menuRef.value?.getBoundingClientRect() ?? new DOMRect(contextMenu.state.value.x, contextMenu.state.value.y, 1, 1)
  contextMenu.hide()
  a.run(at)
}

// Ask: the prompt row at the top of the menu.
const askActive = ref(false)
const askKind = computed(() => {
  const items = selectedItems.value.length ? selectedItems.value : (mediaItem.value ? [mediaItem.value] : [])
  return items.some((item: any) => isVideoType(item)) ? 'video' : 'image'
})
watch(() => contextMenu.state.value.visible, () => { askActive.value = false })
// Typing keeps the menu the width it opened at: long prompts truncate rather
// than stretch it. Read before the menu items give way to the matches.
const askWidth = ref<number | null>(null)
watch(askActive, (on) => { askWidth.value = on ? (menuRef.value?.offsetWidth ?? null) : null }, { flush: 'pre' })
function onAskSent() {
  contextMenu.hide()
  activeSubmenu.value = null
  activeGroup.value = null
}
const targetCount = computed(() => targetIds.value.length)

// Computed properties from mediaItem (fetched from API)
const isVideo = computed(() => mediaItem.value ? isVideoType(mediaItem.value) : false)
const isImage = computed(() => mediaItem.value ? isImageType(mediaItem.value) : false)
const isTrashed = computed(() => !!mediaItem.value?.deleted_at)
const hasClipEmbedding = computed(() => mediaItem.value?.has_clip_embedding || false)
// Videos are face-detected on their first frame, so they qualify too. Browser
// items carry the flag; bare Media falls back to a background faces lookup.
const hasFaceEmbeddings = computed(() => (
  (isImage.value || isVideo.value) &&
  !isMultiple.value &&
  (mediaItem.value?.has_face_embeddings ?? mediaFaces.value.some((face: any) => face.has_embedding))
))

const exploreRowCount = computed(() => (
  Number(hasClipEmbedding.value && targetCount.value <= 3)
  + Number(hasFaceEmbeddings.value)
  + Number(targetCount.value === 2 && !isVideo.value)
  + Number(!isMultiple.value)
))
// Share link, Share file, Print and Export: the occasional commands. On a desktop
// pointer they stay inline unless the OS share row makes the group long enough.
const shareRowCount = computed(() => (
  Number(!isMultiple.value)
  + Number(!isMultiple.value && nativeShareSupported && !isMultiFileItem.value)
))

// What the sheet's actions apply to: one line of title and one of facts.
const selectionSummary = computed(() => {
  if (isMultiple.value) {
    return { title: `${targetCount.value} items`, detail: currentSelectionMediaTypes.value.join(' · ') }
  }
  const item = mediaItem.value
  if (!item) return null
  const facts: string[] = []
  if (item.width && item.height) facts.push(`${item.width} × ${item.height}`)
  if (item.file_format) facts.push(String(item.file_format).split('.')[0].toUpperCase())
  const kind = currentMediaType.value
  return { title: item.title || kind.charAt(0).toUpperCase() + kind.slice(1), detail: facts.join(' · ') }
})

// Visibility state computed properties
const isSet = computed(() => mediaItem.value?.file_format === 'stimmaset.json')
const isGrid = computed(() => mediaItem.value?.file_format === 'stimmagrid.json')
const isSprite = computed(() => mediaItem.value?.file_format === 'stimmasprite.json')
const isPackage = computed(() => mediaItem.value?.file_format === 'stimmapackage')
const isSetOrGrid = computed(() => isSet.value || isGrid.value)
// No single file to hand to the OS share sheet.
const isMultiFileItem = computed(() => isSetOrGrid.value || isSprite.value || isPackage.value || mediaItem.value?.file_format === 'stimmalayout')
const inCollection = computed(() => contextMenu.state.value.inCollection || false)
const collectionSectionId = computed(() => contextMenu.state.value.collectionSectionId)
const inProject = computed(() => contextMenu.state.value.inProject || false)
// The project this menu acts in: the caller's project when it names one
// (null for an explicit top-level owner such as an unfiled chat), else the
// active working project. Lists and creates in the collection/chat/flow pickers,
// the Projects submenu pin and Remove from Project all use it.
const currentProjectId = computed(() => resolveProjectId(contextMenu.state.value.projectId, workingProjectId.value))

// Project memberships of the targets, loaded when the menu opens. Null while
// unknown (loading, or too many targets to look up one by one).
const MEMBERSHIP_LOOKUP_LIMIT = 100
const projectMembership = ref<Map<number, number> | null>(null)
const membershipWanted = ref(false)
let membershipRequest = 0
const showRemoveFromProject = computed(() => (
  currentProjectId.value != null && (
    canRemoveFromProject(projectMembership.value ?? new Map(), currentProjectId.value) ||
    // A project grid knows its tiles are members before the lookup returns.
    (inProject.value && (contextMenu.state.value.projectId ?? null) === currentProjectId.value && projectMembership.value == null)
  )
))

async function loadProjectMemberships() {
  const request = ++membershipRequest
  projectMembership.value = null
  const assetIds = targetAssetIds.value
  const mediaIds = targetMediaIds.value
  const ids = assetIds.length > 0 ? assetIds : mediaIds
  if (ids.length === 0 || ids.length > MEMBERSHIP_LOOKUP_LIMIT) return
  try {
    const lists = await Promise.all(ids.map(id => (
      (assetIds.length > 0 ? getAssetProjects(id) : getMediaProjects(id)).catch(() => [])
    )))
    if (request !== membershipRequest) return
    projectMembership.value = countMemberships(lists)
  } catch (err) {
    if (request === membershipRequest) console.error('Failed to load project memberships:', err)
  }
}

// Can create set: multiple atomic items selected (not sets or grids)
const STRUCTURED_FORMATS = ['stimmaset.json', 'stimmagrid.json', 'stimmasprite.json', 'stimmapackage']
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
    return isGrid.value || isSprite.value || isPackage.value
  }
  // Multi-select case
  const items = selectedItems.value
  return items.some(item => ['stimmagrid.json', 'stimmasprite.json', 'stimmapackage'].includes(item.file_format?.toLowerCase()))
})
const creatingSet = ref(false)
const filteredCollections = computed(() => {
  const query = collectionSearchQuery.value.trim().toLowerCase()
  if (!query) return collections.value
  return collections.value.filter((collection) => (collection.name || '').toLowerCase().includes(query))
})

function formatCollectionSubmenuSummary(collection: any): string {
  const itemCount = collection.asset_count || 0
  const sectionCount = collection.section_count || 0
  const itemText = `${itemCount} ${itemCount === 1 ? 'item' : 'items'}`
  return sectionCount > 1 ? `${itemText} · ${sectionCount} sections` : itemText
}

// Check if media item has a specific marker
function hasMarker(markerId: number): boolean {
  const itemMarkers = mediaItem.value?.markers || []
  return itemMarkers.some((m: any) => m.id === markerId)
}

// Tag counts for the tag picker (for single item, each tag is either 0 or 1)
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

const currentSelectionMediaTypes = computed((): MediaType[] => {
  if (selectedItems.value.length <= 1) return [currentMediaType.value]
  return Array.from(new Set(selectedItems.value.map(item => getMediaType(item))))
})

const activeFlowInputFields = computed(() => {
  const flow = activeFlowDestination.value
  if (!flow) return []
  return flowMediaInputFields(flow.input_schema).filter(field => {
    const types = field.multi ? currentSelectionMediaTypes.value : [currentMediaType.value]
    return types.every(type => fieldAcceptsDraggedType(field.accept, type))
  })
})

// Filter tools for "Send to Tool" (image/video input tools)
// Also filters by selection count validity for multi-selection
// A tool is eligible if ANY of its task_types match the eligible types
const sendToTools = computed(() => {
  const count = isSet.value ? 1 : targetCount.value  // Sets count as 1 input (will be expanded by backend)

  return tools.value.filter(t => {
    return planToolHandoff({ tool: t, mediaTypes: currentSelectionMediaTypes.value, count }).eligible
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
const submenuOpensLeft = ref(false)
const flowDestinationVisible = computed(() => activeSubmenu.value === 'flow' && activeFlowDestination.value !== null)
const {
  submenuStyle: flowDestinationPosition,
  bridgeStyle: flowDestinationBridgeStyle,
} = useSubmenuPosition(
  flowSubmenuRef,
  flowDestinationTriggerRect,
  flowDestinationSubmenuRef,
  flowDestinationVisible,
  { preferLeft: submenuOpensLeft },
)

// Resolve the active submenu's element ref for measurement
function getActiveSubmenuEl(): HTMLElement | null {
  switch (activeSubmenu.value) {
    case 'collection': return collectionSubmenuRef.value
    case 'generate': return generateSubmenuRef.value
    case 'tool': return toolSubmenuRef.value
    case 'chat': return chatSubmenuRef.value
    case 'flow': return flowSubmenuRef.value
    case 'project': return projectSubmenuRef.value
    default: return null
  }
}

let submenuAppliedCap: number | null = null

function repositionSubmenu() {
  if (isCoarsePointer.value) {
    submenuPosition.value = { ...SHEET_MENU_STYLE }
    submenuBridgeStyle.value = { display: 'none' }
    submenuAppliedCap = null
    getActiveSubmenuEl()?.setAttribute('data-sheet-menu', '')
    return
  }
  // A submenu opened from a group panel sits beside that panel, not the root menu.
  const parentEl = activeGroup.value && groupSheetRef.value ? groupSheetRef.value : menuRef.value
  if (!submenuTriggerRect.value || !parentEl) {
    submenuPosition.value = { top: '0px', left: '0px' }
    submenuBridgeStyle.value = { display: 'none' }
    submenuOpensLeft.value = false
    submenuAppliedCap = null
    return
  }

  const triggerRect = submenuTriggerRect.value
  const menuRect = parentEl.getBoundingClientRect()

  // Measure actual submenu size (fall back before first render)
  const submenuEl = getActiveSubmenuEl()
  const measured = submenuEl ? measureMenu(submenuEl, submenuAppliedCap) : { w: 260, h: 400 }

  const { x, opensLeft } = computeSubmenuX(menuRect, measured.w)
  submenuOpensLeft.value = opensLeft

  const style = computeSubmenuStyle(x, triggerRect.top, measured.h)
  submenuAppliedCap = style.maxHeight ? parseInt(style.maxHeight, 10) : null
  submenuPosition.value = style
  submenuBridgeStyle.value = computeBridgeStyle(menuRect, triggerRect, opensLeft)
}

// Reposition after the submenu renders (so we can measure its actual size),
// then keep re-clamping while its async content (tool/collection lists) loads in
let submenuResizeObserver: ResizeObserver | null = null

watch(activeSubmenu, async (menu) => {
  submenuResizeObserver?.disconnect()
  submenuResizeObserver = null
  if (menu) {
    submenuAppliedCap = null
    await nextTick()
    repositionSubmenu()
    const el = getActiveSubmenuEl()
    if (el && typeof ResizeObserver !== 'undefined') {
      submenuResizeObserver = new ResizeObserver(() => repositionSubmenu())
      submenuResizeObserver.observe(el)
    }
  } else {
    submenuBridgeStyle.value = { display: 'none' }
  }
})

onUnmounted(() => {
  submenuResizeObserver?.disconnect()
  submenuResizeObserver = null
})

// Desktop group panel: opens beside the root menu at the trigger row's height.
function repositionGroup() {
  const panel = groupSheetRef.value
  const trigger = groupTriggerRect.value
  const menu = menuRef.value
  if (isCoarsePointer.value || !panel || !trigger || !menu) {
    groupPosition.value = { top: '0px', left: '0px' }
    return
  }
  const measured = measureMenu(panel, null)
  const { x } = computeSubmenuX(menu.getBoundingClientRect(), measured.w)
  groupPosition.value = computeSubmenuStyle(x, trigger.top, measured.h)
}

watch(activeGroup, async (group) => {
  if (!group || isCoarsePointer.value) return
  await nextTick()
  repositionGroup()
})

// The clicked item as the caller already holds it, when it carries every field
// the menu reads. Grids, the slideshow and the selection bar hold live browser
// items (kept current by realtime updates), so the menu renders from them at
// once instead of waiting on a round trip.
function callerItem() {
  const { assetId, mediaId } = contextMenu.state.value
  const item = selectedItems.value.find((candidate: any) => (
    assetId != null
      ? hasAssetIdentity(candidate) && assetIdOf(candidate) === assetId
      : mediaId != null && mediaIdOf(candidate) === mediaId
  ))
  if (!item || typeof item.file_format !== 'string' || !('deleted_at' in item) ||
      !('has_clip_embedding' in item) || !Array.isArray(item.markers) || !Array.isArray(item.tags)) return null
  return item
}

function revisionPayloadItem(assetItem: any, payload: any) {
  return {
    ...assetItem,
    ...payload,
    id: assetItem.id,
    asset_id: assetIdOf(assetItem),
    media_id: mediaIdOf(payload),
    markers: assetItem.markers,
    tags: assetItem.tags,
    deleted_at: assetItem.deleted_at,
  }
}

// Resolve the clicked item when the menu opens. Only callers that hold just an
// ID pay a round trip, and only they show the loading state.
let mediaItemRequest = 0
async function fetchMediaItem() {
  const request = ++mediaItemRequest
  const assetId = contextMenu.state.value.assetId
  const mediaId = contextMenu.state.value.mediaId
  mediaFaces.value = []
  if (!assetId && !mediaId) return

  const held = callerItem()
  if (held) {
    // Copy: marker toggles edit the menu's item, not the caller's.
    mediaItem.value = { ...held }
    loadingItem.value = false
  } else {
    loadingItem.value = true
    try {
      // Include trashed items so we can show appropriate options
      let item = assetId
        ? await getAssetBrowserItem(assetId, true)
        : await getMediaItem(mediaId!, { includeTrashed: true })
      if (request !== mediaItemRequest) return
      // The caller is showing an older revision of this asset (the chat's
      // artifact stage). The asset row is the current revision, so payload
      // actions (print, export, file type) take the shown revision's media
      // while markers, tags and trash state stay the asset's.
      if (assetId && mediaId != null && item && mediaIdOf(item) !== mediaId) {
        const payload = await getMediaItem(mediaId, { includeTrashed: true })
        if (request !== mediaItemRequest) return
        item = revisionPayloadItem(item, payload)
      }
      mediaItem.value = item
    } catch (err) {
      if (request !== mediaItemRequest) return
      console.error('Failed to load media item:', err)
      mediaItem.value = null
    } finally {
      if (request === mediaItemRequest) loadingItem.value = false
    }
  }
  // Bare Media lacks the browser face flag; look faces up without holding the menu.
  if (mediaItem.value && mediaItem.value.has_face_embeddings == null && (isImage.value || isVideo.value)) {
    fetchMediaFaces(request)
  }
}

async function fetchMediaFaces(request: number) {
  const mediaId = contextMenu.state.value.mediaId
  if (!mediaId || isMultiple.value) return

  try {
    const response = await getMediaFaces(mediaId)
    if (request !== mediaItemRequest) return
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
    tools.value = await listAvailableTools()
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
    const params = new URLSearchParams({ project_id: projectListParam(currentProjectId.value) })
    const url = `/api/chats?${params.toString()}`
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

async function loadFlows() {
  const projectChanged = lastFlowsProjectId.value !== currentProjectId.value
  if (!projectChanged && (flows.value.length > 0 || loadingFlows.value)) return
  lastFlowsProjectId.value = currentProjectId.value
  loadingFlows.value = true
  try {
    const params = currentProjectId.value ? { project_id: currentProjectId.value } : {}
    flows.value = await flowsApi.listFlows(params)
  } catch (err) {
    console.error('Failed to load flows:', err)
  } finally {
    loadingFlows.value = false
  }
}

async function loadCollectionsList(force = false) {
  const projectChanged = lastCollectionsProjectId.value !== currentProjectId.value
  if (!force && !projectChanged && (collections.value.length > 0 || loadingCollections.value)) return
  lastCollectionsProjectId.value = currentProjectId.value
  loadingCollections.value = true
  try {
    collections.value = await getCollections(currentProjectId.value)
  } catch (err) {
    console.error('Failed to load collections:', err)
  } finally {
    loadingCollections.value = false
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

function openSubmenu(menu: 'generate' | 'tool' | 'chat' | 'flow' | 'collection' | 'project', event: MouseEvent) {
  cancelSubmenuClose()

  // Capture the trigger element's position for submenu positioning
  const target = event.currentTarget as HTMLElement
  if (target) {
    submenuTriggerRect.value = target.getBoundingClientRect()
    // A root-level row (Remix, Tags...) replaces any open group panel.
    if (!isCoarsePointer.value && activeGroup.value && !groupSheetRef.value?.contains(target)) activeGroup.value = null
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
  } else if (menu === 'flow') {
    if (!wasAlreadyOpen) clearFlowDestination()
    loadFlows()
  } else if (menu === 'collection') {
    collectionSearchQuery.value = ''
    loadCollectionsList()
  } else if (menu === 'project') {
    // ProjectPickerSubmenu loads the project list; its marks need memberships.
    membershipWanted.value = true
  }
}

function openFlowDestination(flow: Flow, event: MouseEvent) {
  cancelSubmenuClose()
  const target = event.currentTarget as HTMLElement
  if (target) flowDestinationTriggerRect.value = target.getBoundingClientRect()
  activeFlowDestination.value = flow
}

function clearFlowDestination() {
  activeFlowDestination.value = null
  flowDestinationTriggerRect.value = null
}

function closeSubmenuDelayed() {
  // Touch submenus stay open until a choice, outside tap, or Escape. The
  // synthetic mouseleave from opening a stacked sheet is not a dismissal.
  if (isCoarsePointer.value) return
  submenuCloseTimeout.value = window.setTimeout(() => {
    // Guard: don't close if a recent click happened (content may have resized)
    if (Date.now() < submenuClickLockUntil.value) return
    // Guard: don't close if mouse is still over any submenu
    const overSubmenu = (
      isMouseOverElement(generateSubmenuRef.value) ||
      isMouseOverElement(toolSubmenuRef.value) ||
      isMouseOverElement(chatSubmenuRef.value) ||
      isMouseOverElement(flowSubmenuRef.value) ||
      isMouseOverElement(flowDestinationSubmenuRef.value) ||
      isMouseOverElement(collectionSubmenuRef.value) ||
      isMouseOverElement(projectSubmenuRef.value)
    )
    if (overSubmenu) return
    activeSubmenu.value = null
    // The group panel stays while the pointer is on it.
    if (!isMouseOverElement(groupSheetRef.value)) activeGroup.value = null
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
  if (!isRenderer.value || !contextMenu.state.value.visible) return
  const target = event.target as Element
  if (menuRef.value?.contains(target)) return
  // Check all submenu refs (they live in Teleport, outside menuRef)
  if (generateSubmenuRef.value?.contains(target)) return
  if (toolSubmenuRef.value?.contains(target)) return
  if (chatSubmenuRef.value?.contains(target)) return
  if (flowSubmenuRef.value?.contains(target)) return
  if (flowDestinationSubmenuRef.value?.contains(target)) return
  if (collectionSubmenuRef.value?.contains(target)) return
  if (projectSubmenuRef.value?.contains(target)) return
  if (groupSheetRef.value?.contains(target)) return
  // The tag picker submenu lives in its own Teleport
  if (target.closest?.('[data-tag-picker]')) return
  contextMenu.hide()
  activeSubmenu.value = null
  activeGroup.value = null
}

// Close on escape
function handleKeyDown(event: KeyboardEvent) {
  if (event.defaultPrevented || !isRenderer.value || event.key !== 'Escape') return
  const submenus = [generateSubmenuRef, toolSubmenuRef, chatSubmenuRef,
    flowSubmenuRef, flowDestinationSubmenuRef, collectionSubmenuRef, projectSubmenuRef]
  if (submenus.some(menu => isTopmostEscapeLayer(menu.value))) {
    consumeEscape(event)
    if (activeFlowDestination.value) clearFlowDestination()
    else activeSubmenu.value = null
  } else if (activeGroup.value && isTopmostEscapeLayer(groupSheetRef.value)) {
    consumeEscape(event)
    activeGroup.value = null
  } else if (isTopmostEscapeLayer(menuRef.value)) {
    consumeEscape(event)
    contextMenu.hide()
    activeSubmenu.value = null
    activeGroup.value = null
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
  if (menu !== 'flow') clearFlowDestination()
  if (menu === 'generate') {
    await nextTick()
    if (allowsAutofocus.value) generateSearchInputRef.value?.focus()
  } else if (menu === 'collection') {
    await nextTick()
    if (allowsAutofocus.value) collectionSearchInputRef.value?.focus()
  }
})

// Resolve the item per opening and per target (a second right-click while the
// menu is open retargets it without closing). Declared before the membership
// watcher so it settles loadingItem first.
watch(
  () => (contextMenu.state.value.visible && isRenderer.value
    ? `${contextMenu.state.value.assetId ?? ''}|${contextMenu.state.value.mediaId ?? ''}`
    : null),
  (key) => {
    if (key != null) fetchMediaItem()
    else mediaItemRequest++
  },
)

// Memberships only matter for Remove from Project (when the menu acts in a
// project) and the Projects submenu's marks, so other openings skip the lookup.
// It also waits for an ID-only item fetch, so it never competes with the
// request the menu is waiting on.
watch(
  () => (contextMenu.state.value.visible && isRenderer.value && !loadingItem.value &&
    (currentProjectId.value != null || membershipWanted.value)
    ? `${targetAssetIds.value.join(',')}|${targetMediaIds.value.join(',')}`
    : null),
  (key) => {
    if (key != null) loadProjectMemberships()
    else { membershipRequest++; projectMembership.value = null }
  },
)

watch(() => contextMenu.state.value.visible && isRenderer.value, (visible) => {
  if (visible) {
    loadMarkers()
  } else {
    membershipWanted.value = false
    activeSubmenu.value = null
    activeGroup.value = null
    submenuTriggerRect.value = null
    generateSearchQuery.value = ''
    collectionSearchQuery.value = ''
    mediaFaces.value = []
    clearFlowDestination()
    showTagEditor.value = false
  }
})

// Action handlers
function handleFindSimilar() {
  const ids = targetMediaIds.value
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
  const ids = targetMediaIds.value
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
  void openImageEditor(router, mediaId)
}



// Create Set handler
async function handleCreateSet() {
  const ids = targetMediaIds.value
  if (ids.length < 2) return

  creatingSet.value = true
  try {
    await createSetFromMedia(
      ids,
      null,
      currentProjectId.value || null,
      targetAssetIds.value.length > 0 ? targetAssetIds.value : null,
    )
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
    if (targetAssetIds.value.length > 0) {
      if (ids.length > 1) {
        await bulkAssetMarkerOperation(ids, marker.id, !hasIt)
      } else if (hasIt) {
        await removeMarkerFromAsset(ids[0], marker.id)
      } else {
        await addMarkerToAsset(ids[0], marker.id)
      }
    } else if (ids.length > 1) {
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

// Tags handler — opens the tag picker as a submenu; the parent menu stays up
function handleEditTags(event: MouseEvent) {
  tagPickerAnchor.value = event.currentTarget as HTMLElement
  showTagEditor.value = true
}

// Collections handler
async function handleQuickAddToCollection(collectionId: number) {
  if (savingCollectionQuickAddId.value != null) return
  savingCollectionQuickAddId.value = collectionId
  try {
    if (targetAssetIds.value.length > 0) {
      await addAssetsToCollection(collectionId, targetAssetIds.value)
    } else {
      await addMediaToCollection(collectionId, targetMediaIds.value)
    }
    contextMenu.hide()
    emit('refresh')
  } catch (err) {
    console.error('Failed to add media to collection:', err)
  } finally {
    savingCollectionQuickAddId.value = null
  }
}

async function handleCreateCollectionQuickAdd() {
  if (creatingCollectionQuickAdd.value) return
  creatingCollectionQuickAdd.value = true
  try {
    const collection = await createCollection('', currentProjectId.value)
    if (targetAssetIds.value.length > 0) {
      await addAssetsToCollection(collection.id, targetAssetIds.value)
    } else {
      await addMediaToCollection(collection.id, targetMediaIds.value)
    }
    await loadCollectionsList(true)
    contextMenu.hide()
    emit('refresh')
  } catch (err) {
    console.error('Failed to create collection from context menu:', err)
  } finally {
    creatingCollectionQuickAdd.value = false
  }
}

function sendToGenerateTool(tool: GenerateMoreTool) {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  if (!mediaId) return

  trackTelemetry('remix_used')
  addRecentGenerateToolId(tool.full_tool_id)

  // Navigate immediately - ToolView will fetch config and show loading state.
  // Target the most-recent open instance of the tool in the current project
  // context (mirrors useSendToTool's effectiveProjectId inference — remix
  // previously dropped project scope entirely).
  const projectId = workingProjectId.value
  const { instanceId } = resolveToolInstance(tool.full_tool_id, projectId)
  router.push(toolInstanceRoute(tool.full_tool_id, projectId, instanceId, {
    remixFrom: mediaId.toString(),
    _ts: Date.now().toString()
  }))
}

function sendToGenerateToolInstance(row: { tab: WorkspaceTab; tool: GenerateMoreTool }) {
  const mediaId = contextMenu.state.value.mediaId
  contextMenu.hide()
  if (!mediaId) return

  trackTelemetry('remix_used')
  // Instance rows target that exact tab (its project scope rides along).
  router.push(toolTabRoute(row.tab, {
    remixFrom: mediaId.toString(),
    _ts: Date.now().toString()
  }))
}

// Shift-click adds to the tool's existing inputs; plain click replaces them
// (mirrors shift-drop on the sidebar).
function handleToolSelect(tool: ProviderToolSummary, targetTaskType: string, event?: MouseEvent) {
  contextMenu.hide()
  activeSubmenu.value = null

  // Use selectedItems for multi-selection, fall back to mediaItem for single
  const items = selectedItems.value.length === targetMediaIds.value.length && selectedItems.value.length > 0
    ? selectedItems.value.map(item => ({ ...item, id: mediaIdOf(item) }))
    : targetMediaIds.value
  if (items.length === 0) return

  trackTelemetry('send_to_tool_used')
  // Use the shared composable - supports both single and multiple items
  // Pass the target task type so tools with multiple task types use the correct input handling
  void sendToToolComposable(items, tool, targetTaskType, undefined, undefined, { add: event?.shiftKey === true })
    .catch(error => addToast(error instanceof Error ? error.message : 'Failed to send assets to tool', 'warning'))
}

function handleToolInstanceSelect(tab: WorkspaceTab, tool: ProviderToolSummary, targetTaskType: string, event?: MouseEvent) {
  contextMenu.hide()
  activeSubmenu.value = null

  const items = selectedItems.value.length === targetMediaIds.value.length && selectedItems.value.length > 0
    ? selectedItems.value.map(item => ({ ...item, id: mediaIdOf(item) }))
    : targetMediaIds.value
  if (items.length === 0) return

  trackTelemetry('send_to_tool_used')
  // Instance rows target that exact tab (its project scope rides along).
  void sendToToolComposable(items, tool, targetTaskType, tab.projectId ?? null, tab.instanceId ?? null, { add: event?.shiftKey === true })
    .catch(error => addToast(error instanceof Error ? error.message : 'Failed to send assets to tool', 'warning'))
}

async function sendToNewChat() {
  const ids = targetMediaIds.value
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
      body: JSON.stringify({ name: null, project_id: currentProjectId.value })
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
  const ids = targetMediaIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  trackTelemetry('send_to_chat_used')
  setPendingMedia('chat', ids, chat.id)
  router.push({ name: 'chat', params: { id: chat.id } })
}

async function resolveFlowChatId(flowId: number): Promise<number | null> {
  try {
    const headers = { 'X-Profile-ID': getCurrentProfileId() }
    const listResponse = await fetch(`/api/chats?flow_id=${flowId}&page=1&page_size=1`, { headers })
    if (listResponse.ok) {
      const list = await listResponse.json()
      const existingId = list?.items?.[0]?.id
      if (existingId != null) return Number(existingId)
    }

    const createResponse = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ flow_id: flowId }),
    })
    if (!createResponse.ok) throw new Error('Failed to create flow chat')
    const created = await createResponse.json()
    return created?.id != null ? Number(created.id) : null
  } catch (err) {
    console.error('Failed to resolve flow chat:', err)
    return null
  }
}

async function sendToNewFlow() {
  const ids = [...targetMediaIds.value]
  const projectId = currentProjectId.value
  contextMenu.hide()
  activeSubmenu.value = null
  clearFlowDestination()
  if (ids.length === 0) return

  try {
    const flow = await flowsApi.createFlow({ project_id: projectId })
    const chatId = await resolveFlowChatId(flow.id)
    if (chatId != null) setPendingMedia('chat', ids, chatId)
    router.push({ name: 'flow', params: { id: String(flow.id) } })
  } catch (err) {
    console.error('Failed to create flow with assets:', err)
    addToast('Failed to create flow', 'warning')
  }
}

async function sendToFlowChat(flow: Flow) {
  const ids = [...targetMediaIds.value]
  contextMenu.hide()
  activeSubmenu.value = null
  clearFlowDestination()
  if (ids.length === 0) return

  const chatId = await resolveFlowChatId(flow.id)
  if (chatId != null) {
    setPendingMedia('chat', ids, chatId)
  } else {
    addToast('Failed to send assets to the flow agent', 'warning')
  }
  router.push({ name: 'flow', params: { id: String(flow.id) } })
}

async function sendToFlowInput(flow: Flow, field: FlowMediaInputField) {
  const ids = [...targetMediaIds.value]
  contextMenu.hide()
  activeSubmenu.value = null
  clearFlowDestination()
  if (ids.length === 0) return

  try {
    // Re-read before writing so a flow edit made while the menu was open is
    // preserved. This mirrors the sidebar flow-drop behavior.
    const latest = await flowsApi.getFlow(flow.id)
    const inputs = { ...(latest.inputs || {}) }
    if (field.multi) {
      const existing = Array.isArray(inputs[field.name]) ? [...inputs[field.name]] : []
      for (const id of ids) if (!existing.includes(id)) existing.push(id)
      inputs[field.name] = existing
    } else {
      inputs[field.name] = ids[0]
    }
    await flowsApi.updateFlow(flow.id, { inputs })
    router.push({ name: 'flow', params: { id: String(flow.id) } })
  } catch (err) {
    console.error('Failed to set flow input:', err)
    addToast('Failed to set flow input', 'warning')
  }
}

const nativeShareSupported = supportsNativeShare(desktop.kind)
const nativeShareMediaId = ref<number | null>(null)

function handleNativeShare() {
  const id = targetMediaIds.value[0]
  if (!id) return
  nativeShareMediaId.value = id
  contextMenu.hide()
}

const shareDialog = useShareDialog()

function handleShareLink() {
  const id = targetMediaIds.value[0]
  contextMenu.hide()
  if (id) shareDialog.open(mediaItem.value?.id === id ? mediaItem.value : id)
}

async function handleExplode() {
  const assetId = targetAssetIds.value[0]
  contextMenu.hide()
  if (!assetId) {
    addToast('This container has not been migrated to an asset', 'error')
    return
  }

  try {
    explodeSummary.value = (
      await axios.get(`/api/assets/item/${assetId}/container-members/summary`)
    ).data
    explodeAssetId.value = assetId
    showExplodeConfirm.value = true
  } catch (err: any) {
    addToast(err?.response?.data?.detail || 'Could not inspect container', 'error')
  }
}

function closeExplodeConfirm() {
  if (explodingContainer.value) return
  showExplodeConfirm.value = false
  explodeAssetId.value = null
  explodeSummary.value = null
}

async function confirmExplode() {
  if (!explodeAssetId.value) return
  explodingContainer.value = true
  try {
    // Members inherit the container's projects on the backend; the working
    // project rides along so they also land where the user is looking.
    const projectId = currentProjectId.value
    const result = (
      await axios.post(
        `/api/assets/item/${explodeAssetId.value}/explode`,
        projectId != null ? { project_id: projectId } : {},
        { params: projectId != null ? { project_id: projectId } : undefined },
      )
    ).data
    addToast(
      `Created ${result.created_count} ${result.created_count === 1 ? 'asset' : 'assets'}; container moved to Trash`,
      'success',
    )
    showExplodeConfirm.value = false
    explodeAssetId.value = null
    explodeSummary.value = null
    emit('refresh')
  } catch (err: any) {
    addToast(err?.response?.data?.detail || 'Could not save container members', 'error')
  } finally {
    explodingContainer.value = false
  }
}

async function handleKeepInAllAssets() {
  const ids = targetMediaIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    for (const id of ids) await promoteContextualMedia(id, currentProjectId.value)
    addToast(
      ids.length === 1 ? 'Kept in All Assets' : `Kept ${ids.length} in All Assets`,
      'success',
    )
    emit('refresh')
  } catch (err: any) {
    addToast(err?.response?.data?.detail || 'Could not keep media', 'error')
  }
}

async function handleMoveToTrash() {
  const ids = [...targetIds.value]
  const assetIds = [...targetAssetIds.value]
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    if (assetIds.length > 0) {
      await trashAssetsWithUndo(assetIds)
    } else if (ids.length > 1) {
      await bulkDeleteMedia(ids)
    } else {
      await deleteMedia(ids[0])
    }
    emit('refresh')
  } catch (err) {
    console.error('Failed to move to trash:', err)
    addToast('Could not move assets to Trash', 'error')
  }
}

async function handleRestore() {
  const ids = targetIds.value
  contextMenu.hide()
  if (ids.length === 0) return

  try {
    if (targetAssetIds.value.length > 0) {
      if (ids.length > 1) await restoreAssets(ids)
      else await restoreAsset(ids[0])
    } else if (ids.length > 1) {
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
    if (targetAssetIds.value.length > 0) {
      response = ids.length > 1
        ? await permanentlyDeleteAssets(ids)
        : await permanentlyDeleteAsset(ids[0])
    } else if (ids.length > 1) {
      response = await bulkPermanentlyDelete(ids)
    } else {
      response = await permanentlyDeleteMedia(ids[0])
    }
    emit('refresh')
    const accepted = response?.accepted ?? ids.length
    addToast(`Permanent deletion started for ${accepted} ${accepted === 1 ? 'item' : 'items'}`, 'info')
  } catch (err: any) {
    console.error('Failed to permanently delete:', err)
    const message = err?.response?.data?.detail || err?.message || 'Unknown error'
    addToast(`Failed to permanently delete: ${message}`, 'error')
  }
}

function handleDownload() {
  const ids = targetMediaIds.value
  const items = selectedItems.value.length > 0
    ? selectedItems.value.map(item => ({ ...item, id: mediaIdOf(item) }))
    : (mediaItem.value ? [{ ...mediaItem.value, id: mediaIdOf(mediaItem.value) }] : [])
  contextMenu.hide()

  if (ids.length > 0) {
    trackTelemetry('export_used')
    exportMediaIds.value = ids
    exportMediaItems.value = items
    showExportModal.value = true
  }
}

function handlePrint() {
  const items = (contextMenu.state.value.selectedItems || []).map(item => ({ ...item, id: mediaIdOf(item) }))
  const item = mediaItem.value ? { ...mediaItem.value, id: mediaIdOf(mediaItem.value) } : null
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

// Collection-specific actions
async function handleRemoveFromCollection() {
  const ids = targetIds.value
  const sectionId = collectionSectionId.value
  contextMenu.hide()
  if (ids.length === 0 || !sectionId) return

  try {
    if (targetAssetIds.value.length > 0) {
      await Promise.all(ids.map((id) => removeFromCollectionSection(sectionId, id)))
    } else {
      await Promise.all(ids.map((id) => axios.delete(`/api/collections/sections/${sectionId}/items/${id}`)))
    }
    emit('refresh')
  } catch (err) {
    console.error('Failed to remove from collection:', err)
  }
}

function handleProjectMembershipChanged(projectId: number, action: 'add' | 'remove') {
  projectMembership.value = applyMembershipChange(
    projectMembership.value ?? new Map(), targetIds.value.length, projectId, action,
  )
  emitProjectAssetsChanged(projectId, action, targetAssetIds.value, targetMediaIds.value)
  emit('refresh')
}

// Local announcement so open grids update at once, ahead of (and regardless
// of) the server's project_assets_changed broadcast.
function emitProjectAssetsChanged(projectId: number, action: 'add' | 'remove', assetIds: number[], mediaIds: number[]) {
  announceProjectAssetsChanged({
    project_id: projectId,
    asset_ids: assetIds,
    media_ids: mediaIds,
    action: action === 'add' ? 'added' : 'removed',
  })
}

async function handleRemoveFromProject() {
  const ids = targetIds.value
  const assetIds = [...targetAssetIds.value]
  const mediaIds = [...targetMediaIds.value]
  const projectId = currentProjectId.value
  contextMenu.hide()
  if (ids.length === 0 || !projectId) return

  try {
    const results = assetIds.length > 0
      ? await Promise.allSettled(ids.map((id) => removeAssetFromProject(id, projectId)))
      : await Promise.allSettled(ids.map((id) => removeMediaFromProject(projectId, id)))
    // An item that wasn't in the project is not a failure.
    const failed = results.filter((r: any) => r.status === 'rejected' && r.reason?.response?.status !== 404)
    if (failed.length > 0 && failed.length === results.length) throw (failed[0] as PromiseRejectedResult).reason
    emitProjectAssetsChanged(projectId, 'remove', assetIds, mediaIds)
    emit('refresh')
  } catch (err) {
    console.error('Failed to remove from project:', err)
    addToast('Could not remove from project', 'error')
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
