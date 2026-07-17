<template>
  <div class="bg-surface border-b border-edge flex-shrink-0">
    <!-- Filter Selection Strip (Shopping Cart) -->
    <div class="flex justify-between items-center px-2 py-2 gap-2 flex-wrap">
      <!-- Left Side: Filter Toggle Button -->
      <button class="text-content-secondary px-4 h-9 rounded-lg text-sm cursor-pointer flex items-center gap-2 transition-colors flex-shrink-0 hover:bg-overlay-subtle" @click="toggleCriteriaPanel">
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
        </svg>
        Filters
        <svg class="w-4 h-4 transition-transform ml-1" :class="{ 'rotate-180': showCriteriaPanel }" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      <div class="flex gap-2 flex-wrap flex-1">
        <!-- Marker Toggle Buttons (Always First) - 3-state: none, positive (blue), negative (red) -->
        <button
          v-for="marker in markers"
          :key="marker.id"
          :class="[
            'inline-flex items-center justify-center w-9 h-9 rounded-lg transition-colors cursor-pointer',
            isMarkerPositive(marker.id)
              ? 'bg-blue-500/15 border border-blue-500/50 text-blue-500'
              : isMarkerNegative(marker.id)
              ? 'bg-red-500/15 border border-red-500/50 text-red-500'
              : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content'
          ]"
          :title="marker.name"
          @click="toggleMarker(marker.id)"
        >
          <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
        </button>

        <!-- Similar Search Badge -->
        <div v-if="hasSimilarSearchBadge" class="inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 bg-blue-500/15 text-blue-500">
          <MagnifyingGlassCircleIcon class="w-5 h-5 flex-shrink-0" />
          <span class="leading-none">{{ similarSearchBadgeLabel }}</span>
          <div
            v-for="item in similarSearchSourceItems"
            :key="item.id"
            class="w-8 h-8 bg-surface-raised rounded border border-edge-subtle overflow-hidden"
          >
            <MediaImage
              :media-id="item.id"
              :file-hash="item.file_hash"
              :alt="item.file_path"
              :title="item.file_path"
              container-class="w-full h-full"
              :enable-context-menu="false"
              :draggable="false"
            />
          </div>
          <span v-if="!similarSearchSourceItems || similarSearchSourceItems.length === 0" class="leading-none">
            {{ similarSearchFallbackLabel }}
          </span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click="emit('clear-similar')">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Caption Query Badge -->
        <div v-if="localCaptionQuery && captioningEnabledRef" class="inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 bg-blue-500/15 text-blue-500">
          <span class="leading-none">Caption: {{ localCaptionQuery }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click="clearCaptionQuery">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Prompt Query Badge -->
        <div v-if="localPromptQuery" class="inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 bg-blue-500/15 text-blue-500">
          <span class="leading-none">Prompt: {{ localPromptQuery }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click="clearPromptQuery">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Text Similarity Badge -->
        <div v-if="localSimilarToText" class="inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 bg-blue-500/15 text-blue-500">
          <MagnifyingGlassCircleIcon class="w-5 h-5 flex-shrink-0" />
          <span class="leading-none">{{ localSimilarToText }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click="clearSimilarToText">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Media Type Badges -->
        <div v-for="mediaType in allMediaTypes"
             :key="mediaType"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isMediaTypeExcluded(mediaType) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeMediaType(mediaType)">
          <span class="leading-none">{{ { images: 'Images', videos: 'Videos', audio: 'Audio', text: 'Text', sets: 'Sets', grids: 'Grids', layouts: 'Layouts' }[mediaType] || mediaType }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeMediaType(mediaType)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Resolution Badges -->
        <div v-for="resolution in allResolutions"
             :key="resolution"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isResolutionExcluded(resolution) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeResolution(resolution)">
          <span class="leading-none">{{ resolution.charAt(0).toUpperCase() + resolution.slice(1) }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeResolution(resolution)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Keyword Badges -->
        <template v-if="captioningEnabledRef">
        <div v-for="keyword in allKeywords"
             :key="keyword"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isExcluded(keyword) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeKeyword(keyword)">
          <span class="leading-none">{{ keyword }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeKeyword(keyword)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        </template>

        <!-- Tag Badges -->
        <div v-for="tag in allTags"
             :key="tag.id"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isTagExcluded(tag.id) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeTag(tag.id)">
          <span class="leading-none">{{ tag.tag }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeTag(tag.id)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Project Badges (membership chip + specific projects) - hidden in trash and inside a project -->
        <template v-if="!isTrashMode && !inProjectScope">
          <!-- Membership existence chip: blue = in any project, red = not in any project -->
          <div v-if="projectMembership"
               :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', projectMembership === 'none' ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
               @click="toggleProjectMembershipSign">
            <ArchiveBoxIcon class="w-4 h-4 flex-shrink-0" />
            <span class="leading-none">{{ projectMembership === 'none' ? 'Not in Any Project' : 'Any Project' }}</span>
            <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="clearProjectMembership">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <!-- Specific project chips -->
          <div v-for="project in allProjects"
               :key="'proj-' + project.id"
               :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isProjectExcluded(project.id) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
               @click="toggleExcludeProject(project.id)">
            <ArchiveBoxIcon class="w-4 h-4 flex-shrink-0" />
            <span class="leading-none">{{ project.name }}</span>
            <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeProject(project.id)">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </template>

        <!-- Tool Badges -->
        <div v-for="tool in allTools"
             :key="tool.full_tool_id"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isToolExcluded(tool.full_tool_id) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeTool(tool.full_tool_id)">
          <span class="leading-none">{{ getToolName(tool) }}</span>
          <span v-if="isToolStimmaCloud(tool)" class="text-[10px] leading-none font-medium stimma-cloud-text">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
          <span v-else-if="getToolProvider(tool)" class="text-[10px] leading-none px-1.5 py-0.5 rounded-full opacity-60 bg-black/10">{{ getToolProvider(tool) }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeTool(tool.full_tool_id)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Folder Badges -->
        <div v-for="folder in allFolders"
             :key="folder"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', isFolderExcluded(folder) ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExcludeFolder(folder)">
          <span class="leading-none">{{ getFolderName(folder) }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="removeFolder(folder)">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- File Date Badge (quick ranges toggle include/exclude; custom stays blue) -->
        <div v-if="selectedDateRange"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9', dateRangeExcluded ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500', selectedDateRange !== 'custom' ? 'cursor-pointer' : '']"
             @click="toggleExcludeDateRange">
          <span class="leading-none">{{ getDateRangeLabel() }}</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="clearDateRange">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Imported Badge (not shown in trash mode) -->
        <div v-if="!isTrashMode && localIsImported !== null"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', localIsImported === false ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleImportedExclusion">
          <span class="leading-none">Imported</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="clearImportedFilter">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Unused Badge (not shown in trash mode) -->
        <div v-if="!isTrashMode && localIsUnused !== null"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', localIsUnused === false ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleUnusedExclusion">
          <span class="leading-none">Unused</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="clearUnusedFilter">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Expiring Badge (not shown in trash mode) -->
        <div v-if="!isTrashMode && (localShowExpiring || localExcludeExpiring)"
             :class="['inline-flex items-center gap-1.5 px-3 rounded-lg text-sm font-medium transition-all h-9 cursor-pointer', localExcludeExpiring ? 'bg-red-500/15 text-red-500' : 'bg-blue-500/15 text-blue-500']"
             @click="toggleExpiringExclusion">
          <span class="leading-none">Expiring</span>
          <button class="bg-transparent border-none text-inherit cursor-pointer p-0 flex items-center justify-center w-4 h-4 opacity-70 transition-opacity hover:opacity-100" @click.stop="clearExpiringFilter">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

      </div>

      <!-- Right Side Controls -->
      <div class="flex items-center gap-2">
      <!-- Unified Pill Group -->
      <div class="flex items-center gap-1">
        <!-- Item count -->
        <span v-if="totalCount !== null" class="px-3 py-2 text-sm text-content-tertiary font-medium whitespace-nowrap">{{ itemCountText }}</span>
        <!-- Sort dropdown (not shown in trash mode - trash always sorts by deleted date) -->
        <select v-if="!isTrashMode" v-model="localSortBy" @change="emitUpdate" class="bg-transparent text-content px-3 py-2 text-sm cursor-pointer focus:outline-none appearance-none rounded-lg pr-7 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMyA0LjVMNiA3LjVMOSA0LjUiIHN0cm9rZT0iIzg4OCIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg==')] bg-no-repeat bg-[right_0.5rem_center]">
          <option value="similarity" :disabled="!similarSearchActive && !localSimilarToText">Similarity</option>
          <option value="created_desc">Newest First</option>
          <option value="created_asc">Oldest First</option>
          <option value="random">Random</option>
        </select>
        <!-- Shuffle button - only visible when in random mode (not in trash mode) -->
        <button v-if="!isTrashMode && localSortBy === 'random'" @click="handleShuffle" class="px-3 py-2 cursor-pointer flex items-center justify-center transition-colors hover:bg-overlay-subtle rounded-lg text-content-secondary hover:text-indigo-400" title="Shuffle order">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.678 48.678 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 003.7 3.7 48.656 48.656 0 007.324 0 4.006 4.006 0 003.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3l-3 3" />
          </svg>
        </button>
      </div>
        <!-- 3-dot menu for saved view actions (not shown in trash mode) -->
        <div v-if="!isTrashMode && savedViewId" class="relative" ref="savedViewMenuRef">
          <button
            @click="showSavedViewMenu = !showSavedViewMenu"
            class="text-content-secondary p-2 rounded-lg cursor-pointer flex items-center justify-center transition-colors hover:bg-overlay-subtle"
            title="View options"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
            </svg>
          </button>
          <!-- Dropdown menu -->
          <div
            v-if="showSavedViewMenu"
            class="absolute right-0 top-full mt-1 bg-surface-raised border border-edge-strong rounded-md shadow-lg z-50 py-1 min-w-[160px]"
          >
            <div class="px-4 py-2 text-xs text-content-tertiary uppercase tracking-wider">Saved View</div>
            <button
              @click="handleRenameView"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
              </svg>
              Rename
            </button>
            <div class="border-t border-edge-strong my-1"></div>
            <button
              @click="handleMoveUp"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
              </svg>
              Move Up
            </button>
            <button
              @click="handleMoveDown"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
              Move Down
            </button>
            <div v-if="hasActiveFilters" class="border-t border-edge-strong my-1"></div>
            <button
              v-if="hasActiveFilters"
              @click="showSavedViewMenu = false; clearAllFilters()"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              Clear Filters
            </button>
            <div class="border-t border-edge-strong my-1"></div>
            <button
              @click="handleDeleteView"
              class="w-full px-4 py-2 text-left text-sm text-red-500 hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Delete
            </button>
          </div>
        </div>
        <!-- 3-dot menu for browse actions (save view, clear filters) - shown when filters/sort are non-default -->
        <div v-if="!isTrashMode && !savedViewId && (canSaveView || hasActiveFilters)" class="relative" ref="browseMenuRef">
          <button
            @click="showBrowseMenu = !showBrowseMenu"
            class="text-content-secondary p-2 rounded-lg cursor-pointer flex items-center justify-center transition-colors hover:bg-overlay-subtle"
            title="Filter options"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
            </svg>
          </button>
          <div
            v-if="showBrowseMenu"
            class="absolute right-0 top-full mt-1 bg-surface-raised border border-edge-strong rounded-md shadow-lg z-50 py-1 min-w-[160px]"
          >
            <button
              v-if="canSaveView"
              @click="showBrowseMenu = false; emit('save-view')"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
              </svg>
              Save View
            </button>
            <div v-if="canSaveView && hasActiveFilters" class="border-t border-edge-strong my-1"></div>
            <button
              v-if="hasActiveFilters"
              @click="showBrowseMenu = false; clearAllFilters()"
              class="w-full px-4 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle cursor-pointer flex items-center gap-2"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              Clear Filters
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Expandable Criteria Panel -->
    <transition name="slide-down">
      <div v-if="showCriteriaPanel" class="border-t border-edge bg-overlay-faint relative">
        <!-- Loading spinner -->
        <div v-if="isLoading" class="absolute top-0 left-0 right-0 bottom-0 bg-surface/80 flex items-center justify-center z-10 backdrop-blur-[2px]">
          <div class="w-8 h-8 border-[3px] border-edge border-t-indigo-500 rounded-full spinner"></div>
        </div>
        <div ref="criteriaScrollContainer" class="flex gap-8 px-4 py-3 overflow-x-auto overflow-y-hidden transition-opacity" :class="{ 'opacity-50 pointer-events-none': isLoading }" @wheel="handleHorizontalScroll">
          <!-- Created Column -->
          <div v-if="visibleDateRanges.length > 0 || selectedDateRange === 'custom'" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">CREATED</h4>
            <div class="flex flex-col gap-2">
              <button
                v-for="range in visibleDateRanges"
                :key="range.value"
                @click="selectDateRange(range.value)"
                :class="['flex justify-between items-center py-1.5 rounded-md cursor-pointer transition-all',
                         selectedDateRange === range.value
                           ? (dateRangeExcluded ? 'bg-red-500/15 border border-red-500/50 px-3' : 'bg-overlay-light border border-edge-strong px-3')
                           : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', selectedDateRange === range.value ? (dateRangeExcluded ? 'text-red-400 font-semibold' : 'text-content font-semibold') : 'text-content-secondary']">{{ range.label }}</span>
                <span :class="['text-xs', selectedDateRange === range.value ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.date_ranges[range.value] || 0 }})</span>
              </button>
              <a @click="openCustomDatePicker" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                Custom range...
              </a>
            </div>
          </div>

          <!-- Asset Type Column -->
          <div v-if="visibleMediaTypes.length > 0" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">ASSET TYPE</h4>
            <div class="flex flex-col gap-2">
              <div
                v-for="type in visibleMediaTypes"
                :key="type.value"
                @click="toggleMediaType(type.value)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isMediaTypeSelected(type.value) }, isMediaTypeSelected(type.value) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isMediaTypeSelected(type.value) ? 'text-content font-semibold' : 'text-content-secondary']">{{ type.label }}</span>
                <span :class="['text-xs', isMediaTypeSelected(type.value) ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.media_type[type.value] }})</span>
              </div>
            </div>
          </div>

          <!-- Folders Column -->
          <div v-if="visibleFolders.length > 0" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">FOLDERS</h4>
            <div class="flex flex-col gap-2">
              <div
                v-for="folder in visibleFolders"
                :key="folder"
                @click="toggleFolder(folder)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isFolderSelected(folder) }, isFolderSelected(folder) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isFolderSelected(folder) ? 'text-content font-semibold' : 'text-content-secondary']">{{ getFolderName(folder) }}</span>
                <span :class="['text-xs', isFolderSelected(folder) ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.folders[folder] || 0 }})</span>
              </div>
              <a v-if="folders.length > 5" @click="showFolderModal = true" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                View more ({{ folders.length }})
              </a>
            </div>
          </div>

          <!-- Tags Column -->
          <div v-if="visibleTags.length > 0" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">TAGS</h4>
            <div class="flex flex-col gap-2">
              <!-- Top tags (clickable) -->
              <div
                v-for="tag in visibleTags"
                :key="tag.id"
                @click="toggleTag(tag.id)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isTagSelected(tag.id) }, isTagSelected(tag.id) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isTagSelected(tag.id) ? 'text-content font-semibold' : 'text-content-secondary']">{{ tag.tag }}</span>
                <span :class="['text-xs', isTagSelected(tag.id) ? 'text-content-tertiary' : 'text-content-muted']">({{ tag.usage_count || 0 }})</span>
              </div>
              <!-- View More Link -->
              <a v-if="tags.length > 5" @click="showTagModal = true" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                View more
              </a>
            </div>
          </div>

          <!-- Projects Column (hidden in trash and when already scoped to a single project) -->
          <div v-if="!isTrashMode && !inProjectScope && (showProjectMembershipChip || visibleProjects.length > 0)" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">PROJECTS</h4>
            <div class="flex flex-col gap-2">
              <!-- Membership existence chip: none → In a project (blue) → Not in a project (red) -->
              <div
                v-if="showProjectMembershipChip"
                @click="cycleProjectMembership"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all',
                         projectMembership === 'any' ? 'bg-blue-500/15 border border-blue-500/50 px-3'
                         : projectMembership === 'none' ? 'bg-red-500/15 border border-red-500/50 px-3'
                         : 'hover:bg-overlay-subtle']"
                :title="'Cycle: no constraint → in any project → not in any project'"
              >
                <span :class="['text-sm', projectMembership === 'any' ? 'text-blue-400 font-semibold' : projectMembership === 'none' ? 'text-red-400 font-semibold' : 'text-content-secondary']">
                  {{ projectMembership === 'none' ? 'Not in Any Project' : 'Any Project' }}
                </span>
                <span :class="['text-xs', projectMembership ? 'text-content-tertiary' : 'text-content-muted']">({{ projectMembership === 'none' ? (filterCounts.project_membership?.none || 0) : (filterCounts.project_membership?.any || 0) }})</span>
              </div>
              <!-- Specific projects (greyed out while "not in any project" is active) -->
              <div
                v-for="project in visibleProjects"
                :key="project.id"
                @click="toggleProject(project.id)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md transition-all',
                         projectsDisabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
                         { 'bg-overlay-light border border-edge-strong px-3': isProjectSelected(project.id) },
                         (isProjectSelected(project.id) || projectsDisabled) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm truncate', isProjectSelected(project.id) ? 'text-content font-semibold' : 'text-content-secondary']" :title="project.name">{{ project.name || 'Untitled' }}</span>
                <span :class="['text-xs flex-shrink-0', isProjectSelected(project.id) ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.projects?.[project.id] || 0 }})</span>
              </div>
              <a v-if="projects.length > 5" @click="showAllProjects = !showAllProjects" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                {{ showAllProjects ? 'Show less' : 'View more (' + projects.length + ')' }}
              </a>
            </div>
          </div>

          <!-- Tools Column -->
          <div v-if="visibleTools.length > 0" class="flex flex-col gap-3 min-w-[240px] max-w-[340px] flex-[2] flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">TOOLS</h4>
            <div class="flex flex-col gap-2">
              <div
                v-for="tool in visibleTools"
                :key="tool.full_tool_id"
                @click="toggleTool(tool.full_tool_id)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isToolSelected(tool.full_tool_id) }, isToolSelected(tool.full_tool_id) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span class="flex items-center gap-1.5 min-w-0">
                  <span :class="['text-sm truncate', isToolSelected(tool.full_tool_id) ? 'text-content font-semibold' : 'text-content-secondary']" :title="getToolName(tool)">{{ getToolName(tool) }}</span>
                  <span v-if="isToolStimmaCloud(tool)" class="text-[10px] leading-none font-medium stimma-cloud-text">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
                  <span v-else-if="getToolProvider(tool)" class="text-[10px] leading-none px-1.5 py-0.5 rounded-full flex-shrink-0 text-content-muted bg-overlay-subtle">{{ getToolProvider(tool) }}</span>
                </span>
                <span :class="['text-xs flex-shrink-0', isToolSelected(tool.full_tool_id) ? 'text-content-tertiary' : 'text-content-muted']">({{ tool.count || 0 }})</span>
              </div>
              <a v-if="(filterCounts.tools || []).length > 5" @click="showToolModal = true" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                View more
              </a>
            </div>
          </div>

          <!-- Keywords Column -->
          <div v-if="captioningEnabledRef && visibleKeywords.length > 0" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">KEYWORDS</h4>
            <div class="flex flex-col gap-2">
              <!-- Top keywords (clickable) -->
              <div
                v-for="kw in visibleKeywords"
                :key="kw.keyword"
                @click="toggleKeyword(kw.keyword)"
                :class="['flex justify-between items-center gap-2 py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isKeywordSelected(kw.keyword) }, isKeywordSelected(kw.keyword) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isKeywordSelected(kw.keyword) ? 'text-content font-semibold' : 'text-content-secondary']">{{ kw.keyword }}</span>
                <span :class="['text-xs', isKeywordSelected(kw.keyword) ? 'text-content-tertiary' : 'text-content-muted']">({{ kw.count }})</span>
              </div>
              <!-- View More Link -->
              <a v-if="topKeywords.length > 0" @click="openKeywordModal" class="text-blue-500 text-sm cursor-pointer mt-1 hover:text-blue-500 hover:underline">
                View more
              </a>
            </div>
          </div>

          <!-- Text Filter Column -->
          <div class="flex flex-col gap-3 min-w-[220px] max-w-[320px] flex-[2] flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">AI SEARCH</h4>
            <div class="flex flex-col gap-2">
              <input v-no-autocorrect
                type="text"
                v-model="localSimilarToText"
                @input="debouncedUpdate"
                @keyup.enter="emitUpdate"
                placeholder="Search"
                class="bg-surface-raised border border-edge-strong text-content px-3 py-2 rounded-md text-sm w-full focus:outline-none focus:border-indigo-500"
              />
              <h5 class="m-0 mt-2 text-xs uppercase tracking-wider text-content-tertiary font-semibold">PROMPT FILTER</h5>
              <input v-no-autocorrect
                type="text"
                v-model="localPromptQuery"
                @input="debouncedUpdate"
                placeholder="Filter"
                class="bg-surface-raised border border-edge-strong text-content px-3 py-2 rounded-md text-sm w-full focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <!-- Utility Column - not shown in trash mode -->
          <div v-if="!isTrashMode && showUtilityColumn" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">UTILITY</h4>
            <div class="flex flex-col gap-2">
              <div
                v-if="showImportedRow"
                @click="toggleImportedFilter"
                :class="['flex justify-between items-center py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': localIsImported !== null }, localIsImported !== null ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', localIsImported !== null ? 'text-content font-semibold' : 'text-content-secondary']">Imported</span>
                <span :class="['text-xs', localIsImported !== null ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.imported || 0 }})</span>
              </div>
              <div
                v-if="showExpiringRow"
                @click="toggleExpiringFilter('expiring')"
                :class="['flex justify-between items-center py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isExpiringFilterSelected() }, isExpiringFilterSelected() ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isExpiringFilterSelected() ? 'text-content font-semibold' : 'text-content-secondary']">Expiring</span>
                <span :class="['text-xs', isExpiringFilterSelected() ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.expiring || 0 }})</span>
              </div>
              <div
                v-if="showUnusedRow"
                @click="toggleUnusedFilter"
                :class="['flex justify-between items-center py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': localIsUnused !== null }, localIsUnused !== null ? '' : 'hover:bg-overlay-subtle']"
                title="Generated items never remixed, organized, or referenced anywhere"
              >
                <span :class="['text-sm', localIsUnused !== null ? 'text-content font-semibold' : 'text-content-secondary']">Unused</span>
                <span :class="['text-xs', localIsUnused !== null ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.unused || 0 }})</span>
              </div>
            </div>
          </div>

          <!-- Resolution Column - not shown in trash mode -->
          <div v-if="!isTrashMode && visibleResolutions.length > 0" class="flex flex-col gap-3 min-w-[160px] max-w-[240px] flex-1 flex-shrink-0">
            <h4 class="m-0 text-xs uppercase tracking-wider text-content-tertiary font-semibold">RESOLUTION</h4>
            <div class="flex flex-col gap-2">
              <div
                v-for="res in visibleResolutions"
                :key="res.value"
                @click="toggleResolution(res.value)"
                :class="['flex justify-between items-center py-1.5 rounded-md cursor-pointer transition-all', { 'bg-overlay-light border border-edge-strong px-3': isResolutionSelected(res.value) }, isResolutionSelected(res.value) ? '' : 'hover:bg-overlay-subtle']"
              >
                <span :class="['text-sm', isResolutionSelected(res.value) ? 'text-content font-semibold' : 'text-content-secondary']">{{ res.label }}</span>
                <span :class="['text-xs', isResolutionSelected(res.value) ? 'text-content-tertiary' : 'text-content-muted']">({{ filterCounts.resolution[res.value] }})</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- Keyword Modal -->
    <KeywordModal
      v-if="showKeywordModal && captioningEnabledRef"
      :selectedKeywords="selectedKeywords"
      :filterParams="modalFilterParams"
      @toggle-keyword="toggleKeyword"
      @close="showKeywordModal = false"
    />

    <!-- Tool Modal -->
    <ToolModal
      v-if="showToolModal"
      :tools="filterCounts.tools || []"
      :selectedTools="[...selectedTools, ...excludedTools]"
      @toggle-tool="toggleTool"
      @close="showToolModal = false"
    />

    <!-- Custom Date Picker Modal -->
    <div v-if="showDatePickerModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showDatePickerModal = false">
      <div class="bg-surface-raised border border-edge-strong rounded-lg p-6 w-96 max-w-[90vw]" @click.stop>
        <h3 class="text-lg font-semibold text-content mb-4">Custom Date Range</h3>

        <div class="flex flex-col gap-4">
          <div>
            <label class="block text-sm text-content-tertiary mb-2">From (optional)</label>
            <input v-no-autocorrect
              type="date"
              v-model="customAfterDate"
              @keyup.enter="applyCustomDateRange"
              class="w-full bg-surface border border-edge-strong text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500 date-input"
            />
          </div>

          <div>
            <label class="block text-sm text-content-tertiary mb-2">To (optional)</label>
            <input v-no-autocorrect
              type="date"
              v-model="customBeforeDate"
              @keyup.enter="applyCustomDateRange"
              class="w-full bg-surface border border-edge-strong text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500 date-input"
            />
          </div>
        </div>

        <div class="flex gap-3 mt-6">
          <button
            @click="applyCustomDateRange"
            class="flex-1 bg-indigo-500 text-white px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-indigo-600"
          >
            Apply
          </button>
          <button
            @click="showDatePickerModal = false"
            class="flex-1 bg-transparent border border-edge-strong text-content-secondary px-4 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-subtle"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { MagnifyingGlassCircleIcon } from '@heroicons/vue/24/solid'
import { ArchiveBoxIcon } from '@heroicons/vue/24/outline'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { getCurrentProfileId } from '../composables/useProfile'
import { STIMMA_CLOUD_PROVIDER_ID, STIMMA_TOOL_PROVIDER_DISPLAY_NAME } from '../utils/stimmaCloud'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { captioningEnabledRef } from '../appConfig'
import { useTelemetry } from '../composables/useTelemetry'
import { MediaImage } from './media'

const { track: trackTelemetry } = useTelemetry()

import KeywordModal from './KeywordModal.vue'
import ToolModal from './ToolModal.vue'

const props = defineProps({
  captionQuery: String,
  promptQuery: String,
  mediaTypes: Array,
  excludedMediaTypes: Array,
  resolutions: Array,
  excludedResolutions: Array,
  sortBy: String,
  selectedKeywords: Array,
  excludedKeywords: Array,
  selectedFolders: Array,
  excludedFolders: Array,
  selectedTags: Array,           // New: user-defined tags
  excludedTags: Array,           // New: excluded tags
  selectedProjects: Array,       // Project membership filter (project IDs to include)
  excludedProjects: Array,       // Project membership filter (project IDs to exclude)
  projectMembership: { type: String, default: null },  // null | 'any' | 'none' (in any / no project)
  selectedTools: Array,          // Tool lineage filter (full_tool_id strings)
  excludedTools: Array,          // Excluded tool lineage filter
  selectedMarkers: Array,         // New: selected markers (by ID)
  excludedMarkers: Array,         // New: excluded markers (by ID)
  markers: { type: Array, default: () => [] },  // Available markers from backend
  isImported: { type: Boolean, default: null }, // null | true | false provenance filter
  isUnused: { type: Boolean, default: null },   // null | true | false dead-end filter
  showExpiring: Boolean,          // New: filter for expiring images (positive)
  excludeExpiring: Boolean,       // New: filter to exclude expiring images (negative)
  createdAfter: String,           // ISO datetime string for file date filter
  createdBefore: String,          // ISO datetime string for file date filter
  totalCount: Number,
  similarSearchActive: Boolean,
  similarSearchSourceItem: Object,  // Kept for backwards compat
  similarSearchSourceItems: Array,   // Array of reference items for multi-select
  similarTo: { type: Array, default: () => [] },
  similarFaceTo: { type: Array, default: () => [] },
  similarToText: String,             // Text-based similarity search
  similarityThreshold: { type: Number, default: 0.75 },
  defaultCollapsed: { type: Boolean, default: true }, // Start collapsed
  savedViewId: { type: Number, default: null },  // If viewing a saved view
  savedViewName: { type: String, default: null },  // Name of the saved view
  isTrashMode: { type: Boolean, default: false },  // Trash view mode
  inProjectScope: { type: Boolean, default: false }  // Viewing a single project's assets — project filter is redundant here
})

const emit = defineEmits([
  'update:captionQuery',
  'update:promptQuery',
  'update:mediaTypes',
  'update:excludedMediaTypes',
  'update:resolutions',
  'update:excludedResolutions',
  'update:sortBy',
  'update:selectedKeywords',
  'update:excludedKeywords',
  'update:selectedFolders',
  'update:excludedFolders',
  'update:selectedTags',       // New: tags filter
  'update:excludedTags',       // New: excluded tags
  'update:selectedProjects',   // Project membership filter (include)
  'update:excludedProjects',   // Project membership filter (exclude)
  'update:projectMembership',  // Project membership existence predicate
  'update:selectedTools',      // Tool lineage filter
  'update:excludedTools',      // Excluded tool lineage filter
  'update:selectedMarkers',    // New: markers filter
  'update:excludedMarkers',    // New: excluded markers filter
  'update:isImported',         // Imported lineage provenance filter
  'update:isUnused',           // Unused (dead-end) filter
  'update:showExpiring',       // New: expiring filter (positive)
  'update:excludeExpiring',    // New: exclude expiring filter (negative)
  'update:createdAfter',       // New: file date filter
  'update:createdBefore',      // New: file date filter
  'update:similarToText',
  'update:similarityThreshold',
  'update',
  'clear-similar',
  'shuffle',
  'save-view',
  'delete-view',
  'rename-view',
  'move-up',
  'move-down'
])

const { getTags, getProjects, getConfig } = useMediaApi()
const {
  fetchAssets,
  getTags: getAssetTags,
  getTopKeywords: getAssetTopKeywords,
  getFilterCounts: getAssetFilterCounts,
} = useAssetApi()

const localCaptionQuery = ref(props.captionQuery || '')
const localPromptQuery = ref(props.promptQuery || '')
const localSimilarToText = ref(props.similarToText || '')
const localMediaTypes = ref(props.mediaTypes || [])
const localExcludedMediaTypes = ref(props.excludedMediaTypes || [])
const localResolutions = ref(props.resolutions || [])
const localExcludedResolutions = ref(props.excludedResolutions || [])
const localSortBy = ref(props.sortBy)
const selectedKeywords = ref(props.selectedKeywords || [])
const excludedKeywords = ref(props.excludedKeywords || [])
const selectedFolders = ref(props.selectedFolders || [])
const excludedFolders = ref(props.excludedFolders || [])
const selectedTags = ref(props.selectedTags || [])        // New: tags
const excludedTags = ref(props.excludedTags || [])        // New: excluded tags
const selectedProjects = ref(props.selectedProjects || [])   // Project membership (include)
const excludedProjects = ref(props.excludedProjects || [])   // Project membership (exclude)
const projectMembership = ref(props.projectMembership || null)  // null | 'any' | 'none'
const projects = ref([])                                  // All available projects [{id, name}]
const showAllProjects = ref(false)                        // Expand the project list beyond top 5
const selectedTools = ref(props.selectedTools || [])      // Tool lineage filter
const excludedTools = ref(props.excludedTools || [])      // Excluded tool lineage filter
const selectedMarkers = ref(props.selectedMarkers || [])  // New: markers
const excludedMarkers = ref(props.excludedMarkers || [])  // New: excluded markers
const localIsImported = ref(props.isImported ?? null)
const localIsUnused = ref(props.isUnused ?? null)
const localShowExpiring = ref(props.showExpiring || false)  // New: expiring filter (positive)
const localExcludeExpiring = ref(props.excludeExpiring || false)  // New: exclude expiring filter (negative)
const localSimilarityThreshold = ref(props.similarityThreshold ?? 0.75)
const localCreatedAfter = ref(props.createdAfter || null)  // New: file date filter
const localCreatedBefore = ref(props.createdBefore || null)  // New: file date filter

// Initialize selectedDateRange based on existing date filters
function detectDateRangeFromProps() {
  if (!props.createdAfter && !props.createdBefore) return null
  // If both dates exist or just one, it's a custom range
  return 'custom'
}

const selectedDateRange = ref(detectDateRangeFromProps())  // Track which quick range is selected (e.g., '24hrs', '7d', 'custom')
const dateRangeExcluded = ref(false)  // Quick range inverted to "Older than N" (custom ranges never invert)
const customAfterDate = ref('')  // Temporary state for custom date picker
const customBeforeDate = ref('')  // Temporary state for custom date picker

const topKeywords = ref([])
const tags = ref([])  // All available tags with counts
const folders = ref([])
const filterCounts = ref({
  media_type: { images: 0, videos: 0, audio: 0, text: 0, sets: 0, grids: 0, layouts: 0 },
  resolution: { small: 0, medium: 0, large: 0 },
  folders: {},
  keywords: {},
  tools: [],
  projects: {},
  project_membership: { any: 0, none: 0 },
  date_ranges: {},
  imported: 0,
  expiring: 0,
  unused: 0
})
const showKeywordModal = ref(false)
const showTagModal = ref(false)
const showToolModal = ref(false)
const showFolderModal = ref(false)
const showDatePickerModal = ref(false)
const showCriteriaPanel = ref(!props.defaultCollapsed)
const showSavedViewMenu = ref(false)
const savedViewMenuRef = ref(null)
const showBrowseMenu = ref(false)
const browseMenuRef = ref(null)
const criteriaScrollContainer = ref(null)
const hasLoadedCounts = ref(false)  // Track if counts have been loaded
const canToggle = true // Allow toggling inclusion/exclusion
const isLoading = ref(true)
const unfilteredTotalCount = ref(null)  // Total count with no filters applied

const similarSearchReferenceIds = computed(() => {
  const faceIds = props.similarFaceTo || []
  const imageIds = props.similarTo || []
  return faceIds.length > 0 ? faceIds : imageIds
})

const hasSimilarSearchBadge = computed(() => (
  props.similarSearchActive &&
  (
    (props.similarSearchSourceItems && props.similarSearchSourceItems.length > 0) ||
    similarSearchReferenceIds.value.length > 0
  )
))

const similarSearchBadgeLabel = computed(() => (
  (props.similarFaceTo || []).length > 0 ? 'Similar faces to' : 'Similar to'
))

const similarSearchFallbackLabel = computed(() => {
  const count = similarSearchReferenceIds.value.length
  if (count <= 1) return 'asset'
  return `${count} assets`
})

// Date range presets. Quick ranges are invertible: excluding "Last N" maps to
// created_before = now - N; red styling communicates the invert, label is unchanged.
const dateRanges = [
  { label: 'Last 24 hours', value: '24hrs' },
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days', value: '90d' },
  { label: 'Last year', value: '365d' }
]

let debounceTimer = null

// Check if any filters are active
const hasActiveFilters = computed(() => {
  return !!(
    localCaptionQuery.value ||
    localPromptQuery.value ||
    localSimilarToText.value ||
    (localMediaTypes.value && localMediaTypes.value.length > 0) ||
    (localExcludedMediaTypes.value && localExcludedMediaTypes.value.length > 0) ||
    (localResolutions.value && localResolutions.value.length > 0) ||
    (localExcludedResolutions.value && localExcludedResolutions.value.length > 0) ||
    (selectedKeywords.value && selectedKeywords.value.length > 0) ||
    (excludedKeywords.value && excludedKeywords.value.length > 0) ||
    (selectedFolders.value && selectedFolders.value.length > 0) ||
    (excludedFolders.value && excludedFolders.value.length > 0) ||
    (selectedTags.value && selectedTags.value.length > 0) ||
    (excludedTags.value && excludedTags.value.length > 0) ||
    (selectedProjects.value && selectedProjects.value.length > 0) ||
    (excludedProjects.value && excludedProjects.value.length > 0) ||
    !!projectMembership.value ||
    (selectedTools.value && selectedTools.value.length > 0) ||
    (excludedTools.value && excludedTools.value.length > 0) ||
    (selectedMarkers.value && selectedMarkers.value.length > 0) ||
    (excludedMarkers.value && excludedMarkers.value.length > 0) ||
    localIsImported.value !== null ||
    localIsUnused.value !== null ||
    localShowExpiring.value ||
    localExcludeExpiring.value ||
    props.similarSearchActive ||
    localCreatedAfter.value ||
    localCreatedBefore.value
  )
})

// Check if filters/sort are non-default (for showing Save View button)
const canSaveView = computed(() => {
  // Don't show on saved view pages (they have their own controls)
  if (props.savedViewId) return false
  // Show if any filters are active or sort is not default
  return hasActiveFilters.value || localSortBy.value !== 'created_desc'
})

// Display text for item count
const itemCountText = computed(() => {
  if (props.totalCount === null) return ''

  if (hasActiveFilters.value && unfilteredTotalCount.value !== null) {
    return `${props.totalCount} of ${unfilteredTotalCount.value} items`
  }

  return `${props.totalCount} items`
})

// Top keywords for inline display - show selected keywords first, then top keywords
const topKeywordsLimited = computed(() => {
  const selectedKws = selectedKeywords.value || []
  const excludedKws = excludedKeywords.value || []
  const allSelectedKws = [...selectedKws, ...excludedKws]

  // Get counts from filterCounts if available
  const getCounts = (keyword) => {
    if (filterCounts.value && filterCounts.value.keywords && filterCounts.value.keywords[keyword] !== undefined) {
      return filterCounts.value.keywords[keyword]
    }
    // Fallback to topKeywords
    const found = topKeywords.value.find(kw => kw.keyword === keyword)
    return found ? found.count : 0
  }

  // Start with all selected keywords
  const result = allSelectedKws.map(keyword => ({
    keyword,
    count: getCounts(keyword)
  }))

  // Add top keywords that aren't already selected, up to 5 total
  const remainingSlots = 5 - result.length
  if (remainingSlots > 0) {
    const topKws = topKeywords.value
      .filter(kw => !allSelectedKws.includes(kw.keyword))
      .slice(0, remainingSlots)
      .map(kw => ({
        keyword: kw.keyword,
        count: getCounts(kw.keyword)
      }))
    result.push(...topKws)
  }

  return result
})

// Top 5 folders for inline display
const foldersLimited = computed(() => {
  return folders.value.slice(0, 5)
})

// All keywords (both selected and excluded) for showing badges
const allKeywords = computed(() => {
  const selected = selectedKeywords.value || []
  const excluded = excludedKeywords.value || []
  // Combine and deduplicate
  return [...new Set([...selected, ...excluded])]
})

// All folders (both selected and excluded) for showing badges
// Cart chips must show excluded entries too, or an active exclusion becomes invisible
const allMediaTypes = computed(() => [...new Set([...(localMediaTypes.value || []), ...(localExcludedMediaTypes.value || [])])])
const allResolutions = computed(() => [...new Set([...(localResolutions.value || []), ...(localExcludedResolutions.value || [])])])

const allFolders = computed(() => {
  const selected = selectedFolders.value || []
  const excluded = excludedFolders.value || []
  // Combine and deduplicate
  return [...new Set([...selected, ...excluded])]
})

// All tags (both selected and excluded) for showing badges
const allTags = computed(() => {
  const selectedIds = selectedTags.value || []
  const excludedIds = excludedTags.value || []
  // Combine and deduplicate
  const allIds = [...new Set([...selectedIds, ...excludedIds])]
  // Return tag objects from tags.value, with fallback for unresolved IDs
  const resolved = tags.value.filter(tag => allIds.includes(tag.id))
  const resolvedIds = new Set(resolved.map(t => t.id))
  const fallbacks = allIds
    .filter(id => !resolvedIds.has(id))
    .map(id => ({ id, tag: `Tag #${id}` }))
  return [...resolved, ...fallbacks]
})

// Top 5 tags for inline display
const tagsLimited = computed(() => {
  const selectedIds = selectedTags.value || []
  const excludedIds = excludedTags.value || []
  const allSelectedIds = [...selectedIds, ...excludedIds]

  // Start with all selected tags
  const result = tags.value.filter(tag => allSelectedIds.includes(tag.id))

  // Add more tags up to 5 total
  const remainingSlots = 5 - result.length
  if (remainingSlots > 0) {
    const moreTags = tags.value
      .filter(tag => !allSelectedIds.includes(tag.id))
      .slice(0, remainingSlots)
    result.push(...moreTags)
  }

  return result
})

// Project membership existence chip ("In a project" / "Not in a project") is mutually exclusive
// with picking specific projects: 'none' makes specific projects contradictory, so we grey them out.
const projectsDisabled = computed(() => projectMembership.value === 'none')

// Resolve a project ID to its display name (fallback when the project list hasn't loaded yet)
function getProjectName(projectId) {
  const found = projects.value.find(p => p.id === projectId)
  return found ? (found.name || 'Untitled project') : `Project #${projectId}`
}

// All projects referenced by include/exclude state, for rendering cart chips
const allProjects = computed(() => {
  const selectedIds = selectedProjects.value || []
  const excludedIds = excludedProjects.value || []
  const allIds = [...new Set([...selectedIds, ...excludedIds])]
  return allIds.map(id => ({ id, name: getProjectName(id) }))
})

// Top projects for inline display in the criteria panel (selected first, then fill to 5)
const projectsLimited = computed(() => {
  if (showAllProjects.value) return projects.value
  const allSelectedIds = [...(selectedProjects.value || []), ...(excludedProjects.value || [])]
  const result = projects.value.filter(p => allSelectedIds.includes(p.id))
  const remainingSlots = 5 - result.length
  if (remainingSlots > 0) {
    result.push(...projects.value.filter(p => !allSelectedIds.includes(p.id)).slice(0, remainingSlots))
  }
  return result
})

// All tools (both selected and excluded) for showing badges
const allTools = computed(() => {
  const selectedIds = selectedTools.value || []
  const excludedIds = excludedTools.value || []
  const allIds = [...new Set([...selectedIds, ...excludedIds])]
  // Return tool objects from filterCounts.tools, with fallback for unresolved IDs
  const tools = filterCounts.value.tools || []
  const resolved = tools.filter(t => allIds.includes(t.full_tool_id))
  const resolvedIds = new Set(resolved.map(t => t.full_tool_id))
  const fallbacks = allIds
    .filter(id => !resolvedIds.has(id))
    .map(id => ({ full_tool_id: id, tool_name: id.split(':').pop() || id }))
  return [...resolved, ...fallbacks]
})

// Top 5 tools for inline display in criteria panel
const toolsLimited = computed(() => {
  const selectedIds = selectedTools.value || []
  const excludedIds = excludedTools.value || []
  const allSelectedIds = [...selectedIds, ...excludedIds]
  const tools = filterCounts.value.tools || []

  // Start with all selected tools
  const result = tools.filter(t => allSelectedIds.includes(t.full_tool_id))

  // Add more tools up to 5 total
  const remainingSlots = 5 - result.length
  if (remainingSlots > 0) {
    const moreTools = tools
      .filter(t => !allSelectedIds.includes(t.full_tool_id))
      .slice(0, remainingSlots)
    result.push(...moreTools)
  }

  return result
})

// Facet row/column visibility: hide zero-count entries unless they're part of an
// active filter (so an active selection can always be deselected). Before the
// first counts load, show everything to avoid a flash of empty columns.
const mediaTypeOptions = [
  { value: 'images', label: 'Images' },
  { value: 'videos', label: 'Videos' },
  { value: 'audio', label: 'Audio' },
  { value: 'text', label: 'Text' },
  { value: 'sets', label: 'Sets' },
  { value: 'grids', label: 'Grids' },
  { value: 'layouts', label: 'Layouts' },
]
const resolutionOptions = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
]

const visibleMediaTypes = computed(() => {
  if (!hasLoadedCounts.value) return mediaTypeOptions
  return mediaTypeOptions.filter(t => (filterCounts.value.media_type[t.value] || 0) > 0 || isMediaTypeSelected(t.value))
})

const visibleDateRanges = computed(() => {
  if (!hasLoadedCounts.value) return dateRanges
  return dateRanges.filter(r => (filterCounts.value.date_ranges[r.value] || 0) > 0 || selectedDateRange.value === r.value)
})

const visibleFolders = computed(() => {
  if (!hasLoadedCounts.value) return foldersLimited.value
  return foldersLimited.value.filter(f => (filterCounts.value.folders[f] || 0) > 0 || isFolderSelected(f))
})

const visibleTags = computed(() => {
  if (!hasLoadedCounts.value) return tagsLimited.value
  return tagsLimited.value.filter(t => (t.usage_count || 0) > 0 || isTagSelected(t.id) || isTagExcluded(t.id))
})

const visibleProjects = computed(() => {
  if (!hasLoadedCounts.value) return projectsLimited.value
  return projectsLimited.value.filter(p => (filterCounts.value.projects?.[p.id] || 0) > 0 || isProjectSelected(p.id))
})

const showProjectMembershipChip = computed(() =>
  !hasLoadedCounts.value || (filterCounts.value.project_membership?.any || 0) > 0 || projectMembership.value !== null
)

const visibleTools = computed(() => {
  if (!hasLoadedCounts.value) return toolsLimited.value
  return toolsLimited.value.filter(t => (t.count || 0) > 0 || isToolSelected(t.full_tool_id))
})

const visibleKeywords = computed(() => {
  if (!hasLoadedCounts.value) return topKeywordsLimited.value
  return topKeywordsLimited.value.filter(kw => (kw.count || 0) > 0 || isKeywordSelected(kw.keyword))
})

const visibleResolutions = computed(() => {
  if (!hasLoadedCounts.value) return resolutionOptions
  return resolutionOptions.filter(r => (filterCounts.value.resolution[r.value] || 0) > 0 || isResolutionSelected(r.value))
})

const showImportedRow = computed(() =>
  !hasLoadedCounts.value || (filterCounts.value.imported || 0) > 0 || localIsImported.value !== null
)
const showExpiringRow = computed(() =>
  !hasLoadedCounts.value || (filterCounts.value.expiring || 0) > 0 || localShowExpiring.value || localExcludeExpiring.value
)
const showUnusedRow = computed(() =>
  !hasLoadedCounts.value || (filterCounts.value.unused || 0) > 0 || localIsUnused.value !== null
)
const showUtilityColumn = computed(() => showImportedRow.value || showExpiringRow.value || showUnusedRow.value)

// Filter params to pass to keyword modal
const modalFilterParams = computed(() => {
  const params = {}

  if (props.captionQuery) params.caption_query = props.captionQuery
  if (props.promptQuery) params.prompt_query = props.promptQuery
  if (props.mediaTypes && props.mediaTypes.length > 0) {
    params.media_types = props.mediaTypes.join(',')
  }
  if (props.excludedMediaTypes && props.excludedMediaTypes.length > 0) {
    params.excluded_media_types = props.excludedMediaTypes.join(',')
  }
  if (props.resolutions && props.resolutions.length > 0) {
    params.resolutions = props.resolutions.join(',')
  }
  if (props.excludedResolutions && props.excludedResolutions.length > 0) {
    params.excluded_resolutions = props.excludedResolutions.join(',')
  }
  if (props.selectedFolders && props.selectedFolders.length > 0) {
    params.folders = props.selectedFolders.join(',')
  }
  if (props.excludedFolders && props.excludedFolders.length > 0) {
    params.excluded_folders = props.excludedFolders.join(',')
  }
  if (props.selectedTags && props.selectedTags.length > 0) {
    params.tag_ids = props.selectedTags.join(',')
  }
  if (props.excludedTags && props.excludedTags.length > 0) {
    params.excluded_tag_ids = props.excludedTags.join(',')
  }
  if (props.selectedProjects && props.selectedProjects.length > 0) {
    params.project_ids = props.selectedProjects.join(',')
  }
  if (props.excludedProjects && props.excludedProjects.length > 0) {
    params.excluded_project_ids = props.excludedProjects.join(',')
  }
  if (props.projectMembership === 'any') params.has_project = true
  else if (props.projectMembership === 'none') params.has_project = false
  if (props.selectedTools && props.selectedTools.length > 0) {
    params.tool_ids = props.selectedTools.join(',')
  }
  if (props.excludedTools && props.excludedTools.length > 0) {
    params.excluded_tool_ids = props.excludedTools.join(',')
  }
  if (props.selectedMarkers && props.selectedMarkers.length > 0) {
    params.marker_ids = props.selectedMarkers.join(',')
  }
  if (props.excludedMarkers && props.excludedMarkers.length > 0) {
    params.excluded_marker_ids = props.excludedMarkers.join(',')
  }
  if (props.isImported !== null && props.isImported !== undefined) {
    params.is_imported = props.isImported
  }
  if (props.similarSearchActive) {
    if (props.similarFaceTo && props.similarFaceTo.length > 0) {
      params.similar_face_to = props.similarFaceTo.join(',')
    } else if (props.similarTo && props.similarTo.length > 0) {
      params.similar_to = props.similarTo.join(',')
    } else if (props.similarSearchSourceItems && props.similarSearchSourceItems.length > 0) {
      params.similar_to = props.similarSearchSourceItems.map(item => item.media_id || item.id).join(',')
    }
  }
  return params
})

function debouncedUpdate() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    emitUpdate()
  }, 500)  // Increased from 300ms to 500ms
}

function emitUpdate() {
  emit('update:captionQuery', localCaptionQuery.value)
  emit('update:promptQuery', localPromptQuery.value)
  emit('update:similarToText', localSimilarToText.value)
  emit('update:mediaTypes', localMediaTypes.value)
  emit('update:excludedMediaTypes', localExcludedMediaTypes.value)
  emit('update:resolutions', localResolutions.value)
  emit('update:excludedResolutions', localExcludedResolutions.value)
  emit('update:sortBy', localSortBy.value)
  emit('update:selectedKeywords', selectedKeywords.value)
  emit('update:excludedKeywords', excludedKeywords.value)
  emit('update:selectedFolders', selectedFolders.value)
  emit('update:excludedFolders', excludedFolders.value)
  emit('update:selectedTags', selectedTags.value)              // New: tags
  emit('update:excludedTags', excludedTags.value)              // New: excluded tags
  emit('update:selectedProjects', selectedProjects.value)      // Project membership (include)
  emit('update:excludedProjects', excludedProjects.value)      // Project membership (exclude)
  emit('update:projectMembership', projectMembership.value)    // Project membership existence
  emit('update:selectedTools', selectedTools.value)            // Tool lineage filter
  emit('update:excludedTools', excludedTools.value)            // Excluded tool lineage filter
  emit('update:selectedMarkers', selectedMarkers.value)        // New: markers
  emit('update:excludedMarkers', excludedMarkers.value)        // New: excluded markers
  emit('update:isImported', localIsImported.value)              // Imported provenance filter
  emit('update:isUnused', localIsUnused.value)                  // Unused (dead-end) filter
  emit('update:showExpiring', localShowExpiring.value)         // New: expiring filter (positive)
  emit('update:excludeExpiring', localExcludeExpiring.value)   // New: exclude expiring filter (negative)
  emit('update:createdAfter', localCreatedAfter.value)         // New: file date filter
  emit('update:createdBefore', localCreatedBefore.value)       // New: file date filter
  emit('update:similarityThreshold', localSimilarityThreshold.value)
  emit('update')

  // Track which filter types are active (not the values)
  const filterFlags = {
    hasMediaTypeFilter: (localMediaTypes.value?.length > 0 || localExcludedMediaTypes.value?.length > 0),
    hasResolutionFilter: (localResolutions.value?.length > 0 || localExcludedResolutions.value?.length > 0),
    hasKeywordFilter: (selectedKeywords.value?.length > 0 || excludedKeywords.value?.length > 0),
    hasFolderFilter: (selectedFolders.value?.length > 0 || excludedFolders.value?.length > 0),
    hasTagFilter: (selectedTags.value?.length > 0 || excludedTags.value?.length > 0),
    hasToolFilter: (selectedTools.value?.length > 0 || excludedTools.value?.length > 0),
    hasMarkerFilter: (selectedMarkers.value?.length > 0 || excludedMarkers.value?.length > 0),
    hasImportedFilter: localIsImported.value !== null,
    hasDateFilter: (!!localCreatedAfter.value || !!localCreatedBefore.value),
  }
  if (Object.values(filterFlags).some(Boolean)) {
    trackTelemetry('filter_applied', filterFlags)
  }
}

// Media type toggle (add/remove from cart)
function toggleMediaType(type) {
  const isIncluded = localMediaTypes.value.includes(type)
  const isExcluded = localExcludedMediaTypes.value.includes(type)

  if (isIncluded || isExcluded) {
    // Remove from cart
    localMediaTypes.value = localMediaTypes.value.filter(t => t !== type)
    localExcludedMediaTypes.value = localExcludedMediaTypes.value.filter(t => t !== type)
  } else {
    // Add to cart as included
    localMediaTypes.value.push(type)
  }
  emitUpdate()
}

function isMediaTypeSelected(type) {
  return localMediaTypes.value.includes(type) || localExcludedMediaTypes.value.includes(type)
}

function isMediaTypeExcluded(type) {
  return localExcludedMediaTypes.value.includes(type)
}

// Toggle between include/exclude in the badge
function toggleExcludeMediaType(type) {
  const isExcluded = localExcludedMediaTypes.value.includes(type)

  if (isExcluded) {
    // Switch from excluded to included
    localExcludedMediaTypes.value = localExcludedMediaTypes.value.filter(t => t !== type)
    localMediaTypes.value.push(type)
  } else {
    // Switch from included to excluded
    localMediaTypes.value = localMediaTypes.value.filter(t => t !== type)
    localExcludedMediaTypes.value.push(type)
  }
  emitUpdate()
}

// Remove from cart entirely
function removeMediaType(type) {
  localMediaTypes.value = localMediaTypes.value.filter(t => t !== type)
  localExcludedMediaTypes.value = localExcludedMediaTypes.value.filter(t => t !== type)
  emitUpdate()
}

// Resolution toggle (add/remove from cart)
function toggleResolution(res) {
  const isIncluded = localResolutions.value.includes(res)
  const isExcluded = localExcludedResolutions.value.includes(res)

  if (isIncluded || isExcluded) {
    // Remove from cart
    localResolutions.value = localResolutions.value.filter(r => r !== res)
    localExcludedResolutions.value = localExcludedResolutions.value.filter(r => r !== res)
  } else {
    // Add to cart as included
    localResolutions.value.push(res)
  }
  emitUpdate()
}

function isResolutionSelected(res) {
  return localResolutions.value.includes(res) || localExcludedResolutions.value.includes(res)
}

function isResolutionExcluded(res) {
  return localExcludedResolutions.value.includes(res)
}

// Toggle between include/exclude in the badge
function toggleExcludeResolution(res) {
  const isExcluded = localExcludedResolutions.value.includes(res)

  if (isExcluded) {
    // Switch from excluded to included
    localExcludedResolutions.value = localExcludedResolutions.value.filter(r => r !== res)
    localResolutions.value.push(res)
  } else {
    // Switch from included to excluded
    localResolutions.value = localResolutions.value.filter(r => r !== res)
    localExcludedResolutions.value.push(res)
  }
  emitUpdate()
}

// Remove from cart entirely
function removeResolution(res) {
  localResolutions.value = localResolutions.value.filter(r => r !== res)
  localExcludedResolutions.value = localExcludedResolutions.value.filter(r => r !== res)
  emitUpdate()
}


// Keyword management
function toggleKeyword(keyword) {
  const index = selectedKeywords.value.indexOf(keyword)
  if (index === -1) {
    selectedKeywords.value.push(keyword)
    // Remove from excluded if it was there
    const excludedIndex = excludedKeywords.value.indexOf(keyword)
    if (excludedIndex !== -1) {
      excludedKeywords.value.splice(excludedIndex, 1)
    }
  } else {
    selectedKeywords.value.splice(index, 1)
    // Also remove from excluded
    const excludedIndex = excludedKeywords.value.indexOf(keyword)
    if (excludedIndex !== -1) {
      excludedKeywords.value.splice(excludedIndex, 1)
    }
  }
  emitUpdate()
}

function isKeywordSelected(keyword) {
  return selectedKeywords.value.includes(keyword)
}

function isExcluded(keyword) {
  return excludedKeywords.value.includes(keyword)
}

function toggleExcludeKeyword(keyword) {
  const index = excludedKeywords.value.indexOf(keyword)
  if (index === -1) {
    // Add to excluded
    excludedKeywords.value.push(keyword)
    // Remove from selected if it was there
    const selectedIndex = selectedKeywords.value.indexOf(keyword)
    if (selectedIndex !== -1) {
      selectedKeywords.value.splice(selectedIndex, 1)
    }
  } else {
    // Remove from excluded
    excludedKeywords.value.splice(index, 1)
    // Add back to selected
    if (!selectedKeywords.value.includes(keyword)) {
      selectedKeywords.value.push(keyword)
    }
  }
  emitUpdate()
}

function removeKeyword(keyword) {
  const index = selectedKeywords.value.indexOf(keyword)
  if (index !== -1) {
    selectedKeywords.value.splice(index, 1)
  }
  const excludedIndex = excludedKeywords.value.indexOf(keyword)
  if (excludedIndex !== -1) {
    excludedKeywords.value.splice(excludedIndex, 1)
  }
  emitUpdate()
}

// Clear functions for badges
function clearCaptionQuery() {
  localCaptionQuery.value = ''
  emitUpdate()
}

function clearPromptQuery() {
  localPromptQuery.value = ''
  emitUpdate()
}

function clearSimilarToText() {
  localSimilarToText.value = ''
  emitUpdate()
}

function clearAllFilters() {
  localCaptionQuery.value = ''
  localPromptQuery.value = ''
  localSimilarToText.value = ''
  localMediaTypes.value = []
  localExcludedMediaTypes.value = []
  localResolutions.value = []
  localExcludedResolutions.value = []
  selectedKeywords.value = []
  excludedKeywords.value = []
  selectedFolders.value = []
  excludedFolders.value = []
  selectedTags.value = []
  excludedTags.value = []
  selectedTools.value = []
  excludedTools.value = []
  selectedMarkers.value = []
  excludedMarkers.value = []
  selectedProjects.value = []
  excludedProjects.value = []
  projectMembership.value = null
  localIsImported.value = null
  localIsUnused.value = null
  localShowExpiring.value = false
  localExcludeExpiring.value = false
  localCreatedAfter.value = null
  localCreatedBefore.value = null
  selectedDateRange.value = null
  dateRangeExcluded.value = false
  localSortBy.value = 'created_desc'
  emit('clear-similar')
  emitUpdate()
}

function removeFolder(folder) {
  const index = selectedFolders.value.indexOf(folder)
  if (index !== -1) {
    selectedFolders.value.splice(index, 1)
  }
  const excludedIndex = excludedFolders.value.indexOf(folder)
  if (excludedIndex !== -1) {
    excludedFolders.value.splice(excludedIndex, 1)
  }
  emitUpdate()
}

// Tag functions
function toggleTag(tagId) {
  const index = selectedTags.value.indexOf(tagId)
  if (index === -1) {
    selectedTags.value.push(tagId)
    // Remove from excluded if it was there
    const excludedIndex = excludedTags.value.indexOf(tagId)
    if (excludedIndex !== -1) {
      excludedTags.value.splice(excludedIndex, 1)
    }
  } else {
    selectedTags.value.splice(index, 1)
    // Also remove from excluded
    const excludedIndex = excludedTags.value.indexOf(tagId)
    if (excludedIndex !== -1) {
      excludedTags.value.splice(excludedIndex, 1)
    }
  }
  emitUpdate()
}

function isTagSelected(tagId) {
  return selectedTags.value.includes(tagId)
}

function isTagExcluded(tagId) {
  return excludedTags.value.includes(tagId)
}

function toggleExcludeTag(tagId) {
  const index = excludedTags.value.indexOf(tagId)
  if (index === -1) {
    // Add to excluded
    excludedTags.value.push(tagId)
    // Remove from selected if it was there
    const selectedIndex = selectedTags.value.indexOf(tagId)
    if (selectedIndex !== -1) {
      selectedTags.value.splice(selectedIndex, 1)
    }
  } else {
    // Remove from excluded
    excludedTags.value.splice(index, 1)
    // Add back to selected
    if (!selectedTags.value.includes(tagId)) {
      selectedTags.value.push(tagId)
    }
  }
  emitUpdate()
}

function removeTag(tagId) {
  const index = selectedTags.value.indexOf(tagId)
  if (index !== -1) {
    selectedTags.value.splice(index, 1)
  }
  const excludedIndex = excludedTags.value.indexOf(tagId)
  if (excludedIndex !== -1) {
    excludedTags.value.splice(excludedIndex, 1)
  }
  emitUpdate()
}

// Project functions. Two interacting controls share the "PROJECTS" column:
//  - the membership chip (projectMembership): null -> 'any' (in any project) -> 'none' (in no project)
//  - the specific-project list (selectedProjects/excludedProjects), which behaves like tags.
// Full-power combination rules:
//  - 'none' (not in any project) contradicts any specific project, so entering it clears the lists
//    and the rows are greyed out (projectsDisabled).
//  - 'any' (in any project) coexists with excludes ("in a project, just not these") but is superseded
//    by a specific include, so entering 'any' clears includes and adding an include clears 'any'.
function cycleProjectMembership() {
  if (!projectMembership.value) {
    // none-set -> 'any'; specific includes are redundant under "in any project"
    projectMembership.value = 'any'
    selectedProjects.value = []
  } else if (projectMembership.value === 'any') {
    // 'any' -> 'none'; "not in any project" wipes all specific project filters
    projectMembership.value = 'none'
    selectedProjects.value = []
    excludedProjects.value = []
  } else {
    projectMembership.value = null
  }
  emitUpdate()
}

function clearProjectMembership() {
  projectMembership.value = null
  emitUpdate()
}

// Cart chip body click: flip the membership chip between "in any project" (blue) and "not in any project" (red)
function toggleProjectMembershipSign() {
  if (projectMembership.value === 'any') {
    projectMembership.value = 'none'
    selectedProjects.value = []
    excludedProjects.value = []
  } else if (projectMembership.value === 'none') {
    projectMembership.value = 'any'
  }
  emitUpdate()
}

function isProjectSelected(projectId) {
  return selectedProjects.value.includes(projectId) || excludedProjects.value.includes(projectId)
}

function isProjectExcluded(projectId) {
  return excludedProjects.value.includes(projectId)
}

function toggleProject(projectId) {
  if (projectsDisabled.value) return  // specific projects disabled while "not in any project"
  const index = selectedProjects.value.indexOf(projectId)
  if (index === -1) {
    selectedProjects.value.push(projectId)
    const excludedIndex = excludedProjects.value.indexOf(projectId)
    if (excludedIndex !== -1) excludedProjects.value.splice(excludedIndex, 1)
    // a specific include supersedes the broad "in any project" predicate
    if (projectMembership.value === 'any') projectMembership.value = null
  } else {
    selectedProjects.value.splice(index, 1)
    const excludedIndex = excludedProjects.value.indexOf(projectId)
    if (excludedIndex !== -1) excludedProjects.value.splice(excludedIndex, 1)
  }
  emitUpdate()
}

function toggleExcludeProject(projectId) {
  const index = excludedProjects.value.indexOf(projectId)
  if (index === -1) {
    excludedProjects.value.push(projectId)
    const selectedIndex = selectedProjects.value.indexOf(projectId)
    if (selectedIndex !== -1) selectedProjects.value.splice(selectedIndex, 1)
  } else {
    excludedProjects.value.splice(index, 1)
    if (!selectedProjects.value.includes(projectId)) selectedProjects.value.push(projectId)
  }
  emitUpdate()
}

function removeProject(projectId) {
  const index = selectedProjects.value.indexOf(projectId)
  if (index !== -1) selectedProjects.value.splice(index, 1)
  const excludedIndex = excludedProjects.value.indexOf(projectId)
  if (excludedIndex !== -1) excludedProjects.value.splice(excludedIndex, 1)
  emitUpdate()
}

// Tool functions
function getToolName(tool) {
  if (typeof tool === 'object' && tool.name) return tool.name
  return typeof tool === 'string' ? tool : String(tool)
}

function getToolProvider(tool) {
  if (typeof tool === 'object' && tool.provider_name) return tool.provider_name
  return ''
}

function isToolStimmaCloud(tool) {
  return typeof tool === 'object' && tool.provider_id === STIMMA_CLOUD_PROVIDER_ID
}

function getToolDisplayName(tool) {
  const name = getToolName(tool)
  const provider = getToolProvider(tool)
  return provider ? `${name} (${provider})` : name
}

function toggleTool(fullToolId) {
  const index = selectedTools.value.indexOf(fullToolId)
  if (index === -1) {
    selectedTools.value.push(fullToolId)
    // Remove from excluded if it was there
    const excludedIndex = excludedTools.value.indexOf(fullToolId)
    if (excludedIndex !== -1) {
      excludedTools.value.splice(excludedIndex, 1)
    }
  } else {
    selectedTools.value.splice(index, 1)
    // Also remove from excluded
    const excludedIndex = excludedTools.value.indexOf(fullToolId)
    if (excludedIndex !== -1) {
      excludedTools.value.splice(excludedIndex, 1)
    }
  }
  emitUpdate()
}

function isToolSelected(fullToolId) {
  return selectedTools.value.includes(fullToolId) || excludedTools.value.includes(fullToolId)
}

function isToolExcluded(fullToolId) {
  return excludedTools.value.includes(fullToolId)
}

function toggleExcludeTool(fullToolId) {
  const index = excludedTools.value.indexOf(fullToolId)
  if (index === -1) {
    // Add to excluded
    excludedTools.value.push(fullToolId)
    // Remove from selected if it was there
    const selectedIndex = selectedTools.value.indexOf(fullToolId)
    if (selectedIndex !== -1) {
      selectedTools.value.splice(selectedIndex, 1)
    }
  } else {
    // Remove from excluded
    excludedTools.value.splice(index, 1)
    // Add back to selected
    if (!selectedTools.value.includes(fullToolId)) {
      selectedTools.value.push(fullToolId)
    }
  }
  emitUpdate()
}

function removeTool(fullToolId) {
  const index = selectedTools.value.indexOf(fullToolId)
  if (index !== -1) {
    selectedTools.value.splice(index, 1)
  }
  const excludedIndex = excludedTools.value.indexOf(fullToolId)
  if (excludedIndex !== -1) {
    excludedTools.value.splice(excludedIndex, 1)
  }
  emitUpdate()
}

async function toggleCriteriaPanel() {
  showCriteriaPanel.value = !showCriteriaPanel.value

  // Load keywords and counts on first open (tags and folders already loaded on mount)
  if (showCriteriaPanel.value && !hasLoadedCounts.value) {
    hasLoadedCounts.value = true
    isLoading.value = true
    try {
      await Promise.all([
        loadTopKeywords(),
        loadFilterCounts()
      ])
    } finally {
      isLoading.value = false
    }
  }
}

function handleShuffle() {
  emit('shuffle')
}

// Convert vertical mouse wheel to horizontal scroll in the criteria panel
function handleHorizontalScroll(event) {
  if (!criteriaScrollContainer.value) return

  const container = criteriaScrollContainer.value
  const hasHorizontalScroll = container.scrollWidth > container.clientWidth

  // Only convert if there's vertical scroll (deltaY) and the container actually has horizontal overflow
  if (event.deltaY !== 0 && hasHorizontalScroll) {
    event.preventDefault()
    container.scrollLeft += event.deltaY
  }
}

// Folder management (add/remove from cart)
function toggleFolder(folder) {
  const isIncluded = selectedFolders.value.includes(folder)
  const isExcluded = excludedFolders.value.includes(folder)

  if (isIncluded || isExcluded) {
    // Remove from cart
    const index = selectedFolders.value.indexOf(folder)
    if (index !== -1) {
      selectedFolders.value.splice(index, 1)
    }
    const excludedIndex = excludedFolders.value.indexOf(folder)
    if (excludedIndex !== -1) {
      excludedFolders.value.splice(excludedIndex, 1)
    }
  } else {
    // Add to cart as included
    selectedFolders.value.push(folder)
  }
  emitUpdate()
}

function isFolderSelected(folder) {
  return selectedFolders.value.includes(folder) || excludedFolders.value.includes(folder)
}

function isFolderExcluded(folder) {
  return excludedFolders.value.includes(folder)
}

// Toggle between include/exclude in the badge
function toggleExcludeFolder(folder) {
  const isExcluded = excludedFolders.value.includes(folder)

  if (isExcluded) {
    // Switch from excluded to included
    const index = excludedFolders.value.indexOf(folder)
    if (index !== -1) {
      excludedFolders.value.splice(index, 1)
    }
    selectedFolders.value.push(folder)
  } else {
    // Switch from included to excluded
    const index = selectedFolders.value.indexOf(folder)
    if (index !== -1) {
      selectedFolders.value.splice(index, 1)
    }
    excludedFolders.value.push(folder)
  }
  emitUpdate()
}

function getFolderName(folderPath) {
  // Get the last part of the path as the folder name
  const parts = folderPath.split('/')
  return parts[parts.length - 1] || folderPath
}

// Date range functions
function dateRangeCutoff(rangeValue) {
  const now = new Date()
  const HOUR = 60 * 60 * 1000
  const DAY = 24 * HOUR
  switch (rangeValue) {
    case '2hrs': return new Date(now.getTime() - 2 * HOUR)
    case '24hrs': return new Date(now.getTime() - 24 * HOUR)
    case '72hrs': return new Date(now.getTime() - 72 * HOUR)
    case '7d': return new Date(now.getTime() - 7 * DAY)
    case '30d': return new Date(now.getTime() - 30 * DAY)
    case '90d': return new Date(now.getTime() - 90 * DAY)
    case '365d': return new Date(now.getTime() - 365 * DAY)
    default: return null
  }
}

function applyDateRange(rangeValue, excluded) {
  const cutoff = dateRangeCutoff(rangeValue)
  if (!cutoff) return
  selectedDateRange.value = rangeValue
  dateRangeExcluded.value = excluded
  localCreatedAfter.value = excluded ? null : cutoff.toISOString()
  localCreatedBefore.value = excluded ? cutoff.toISOString() : null
  emitUpdate()
}

// Panel click cycle: off -> "Last N" -> "Older than N" -> off
function selectDateRange(rangeValue) {
  if (selectedDateRange.value === rangeValue) {
    if (!dateRangeExcluded.value) {
      applyDateRange(rangeValue, true)
    } else {
      clearDateRange()
    }
    return
  }
  applyDateRange(rangeValue, false)
}

// Cart chip click: flip between include and exclude (quick ranges only)
function toggleExcludeDateRange() {
  if (!selectedDateRange.value || selectedDateRange.value === 'custom') return
  applyDateRange(selectedDateRange.value, !dateRangeExcluded.value)
}

function clearDateRange() {
  selectedDateRange.value = null
  dateRangeExcluded.value = false
  localCreatedAfter.value = null
  localCreatedBefore.value = null
  emitUpdate()
}

function getDateRangeLabel() {
  if (selectedDateRange.value === 'custom') {
    // Format custom date range for display
    const parts = []
    if (localCreatedAfter.value) {
      const date = new Date(localCreatedAfter.value)
      parts.push(date.toLocaleDateString())
    }
    if (localCreatedBefore.value) {
      const date = new Date(localCreatedBefore.value)
      if (parts.length > 0) {
        parts.push(' - ')
      }
      parts.push(date.toLocaleDateString())
    }
    return parts.join('') || 'Custom range'
  }
  const range = dateRanges.find(r => r.value === selectedDateRange.value)
  return range ? range.label : ''
}

function openCustomDatePicker() {
  // Initialize with current values if they exist
  if (localCreatedAfter.value) {
    const date = new Date(localCreatedAfter.value)
    customAfterDate.value = date.toISOString().slice(0, 10)
  } else {
    customAfterDate.value = ''
  }
  if (localCreatedBefore.value) {
    const date = new Date(localCreatedBefore.value)
    customBeforeDate.value = date.toISOString().slice(0, 10)
  } else {
    customBeforeDate.value = ''
  }
  showDatePickerModal.value = true
}

function applyCustomDateRange() {
  selectedDateRange.value = 'custom'
  dateRangeExcluded.value = false

  // For date-only inputs, set time to start/end of day
  if (customAfterDate.value) {
    const afterDate = new Date(customAfterDate.value)
    afterDate.setHours(0, 0, 0, 0)
    localCreatedAfter.value = afterDate.toISOString()
  } else {
    localCreatedAfter.value = null
  }

  if (customBeforeDate.value) {
    const beforeDate = new Date(customBeforeDate.value)
    beforeDate.setHours(23, 59, 59, 999)
    localCreatedBefore.value = beforeDate.toISOString()
  } else {
    localCreatedBefore.value = null
  }

  showDatePickerModal.value = false
  emitUpdate()
}

function setCustomDateRange(afterDate, beforeDate) {
  selectedDateRange.value = 'custom'
  dateRangeExcluded.value = false
  localCreatedAfter.value = afterDate
  localCreatedBefore.value = beforeDate
  showDatePickerModal.value = false
  emitUpdate()
}

// Marker functions - 3-state toggle
function isMarkerPositive(markerId) {
  return (selectedMarkers.value || []).includes(markerId)
}

function isMarkerNegative(markerId) {
  return (excludedMarkers.value || []).includes(markerId)
}

function toggleMarker(markerId) {
  const isPositive = isMarkerPositive(markerId)
  const isNegative = isMarkerNegative(markerId)

  if (!isPositive && !isNegative) {
    // State 1: None -> Positive (blue)
    selectedMarkers.value = [...selectedMarkers.value, markerId]
  } else if (isPositive) {
    // State 2: Positive -> Negative (red)
    selectedMarkers.value = selectedMarkers.value.filter(id => id !== markerId)
    excludedMarkers.value = [...excludedMarkers.value, markerId]
  } else {
    // State 3: Negative -> None
    excludedMarkers.value = excludedMarkers.value.filter(id => id !== markerId)
  }

  emitUpdate()
}

// Imported provenance filter - 3-state toggle (include, exclude, clear)
function toggleImportedFilter() {
  if (localIsImported.value === null) {
    localIsImported.value = true
  } else if (localIsImported.value === true) {
    localIsImported.value = false
  } else {
    localIsImported.value = null
  }
  emitUpdate()
}

function toggleImportedExclusion() {
  localIsImported.value = localIsImported.value === false
  emitUpdate()
}

function clearImportedFilter() {
  localIsImported.value = null
  emitUpdate()
}

// Unused (dead-end) filter functions - 3-state toggle like Imported
function toggleUnusedFilter() {
  if (localIsUnused.value === null) {
    localIsUnused.value = true
  } else if (localIsUnused.value === true) {
    localIsUnused.value = false
  } else {
    localIsUnused.value = null
  }
  emitUpdate()
}

function toggleUnusedExclusion() {
  localIsUnused.value = localIsUnused.value === false
  emitUpdate()
}

function clearUnusedFilter() {
  localIsUnused.value = null
  emitUpdate()
}

// Expiring filter functions - 3-state toggle
function isExpiringFilterSelected() {
  return localShowExpiring.value
}

function toggleExpiringFilter() {
  const isPositive = localShowExpiring.value
  const isNegative = localExcludeExpiring.value

  if (!isPositive && !isNegative) {
    // State 1: None -> Positive (green)
    localShowExpiring.value = true
    localExcludeExpiring.value = false
  } else if (isPositive) {
    // State 2: Positive -> Negative (red)
    localShowExpiring.value = false
    localExcludeExpiring.value = true
  } else {
    // State 3: Negative -> None
    localShowExpiring.value = false
    localExcludeExpiring.value = false
  }

  emitUpdate()
}

function toggleExpiringExclusion() {
  const isExcluded = localExcludeExpiring.value

  if (isExcluded) {
    // Switch from excluded to included
    localExcludeExpiring.value = false
    localShowExpiring.value = true
  } else {
    // Switch from included to excluded
    localShowExpiring.value = false
    localExcludeExpiring.value = true
  }
  emitUpdate()
}

function clearExpiringFilter() {
  localShowExpiring.value = false
  localExcludeExpiring.value = false
  emitUpdate()
}

// Saved view menu functions
function handleDeleteView() {
  showSavedViewMenu.value = false
  emit('delete-view')
}

function handleRenameView() {
  showSavedViewMenu.value = false
  emit('rename-view')
}

function handleMoveUp() {
  showSavedViewMenu.value = false
  emit('move-up')
}

function handleMoveDown() {
  showSavedViewMenu.value = false
  emit('move-down')
}

function handleClickOutside(event) {
  if (savedViewMenuRef.value && !savedViewMenuRef.value.contains(event.target)) {
    showSavedViewMenu.value = false
  }
  if (browseMenuRef.value && !browseMenuRef.value.contains(event.target)) {
    showBrowseMenu.value = false
  }
}

// Load top keywords
async function loadTopKeywords() {
  try {
    const params = {
      ...modalFilterParams.value,
      limit: 200,
      state: props.isTrashMode ? 'trashed' : 'active'
    }
    const response = await getAssetTopKeywords(params)
    topKeywords.value = response.keywords
    console.log('Loaded keywords:', topKeywords.value.length)
  } catch (error) {
    console.error('Failed to load keywords:', error)
  }
}

// Open keyword modal (loading happens inside the modal now)
function openKeywordModal() {
  showKeywordModal.value = true
}

// Load tags from API
async function loadTags() {
  try {
    const response = await getAssetTags(true)
    tags.value = response
    console.log('Loaded tags:', tags.value.length)
  } catch (error) {
    console.error('Failed to load tags:', error)
  }
}

// Load folders from config
async function loadFolders() {
  try {
    const response = await getConfig()
    folders.value = response.media_paths || []
    console.log('Loaded folders:', folders.value)
  } catch (error) {
    console.error('Failed to load folders:', error)
  }
}

// Load projects from API (names for the PROJECTS filter column; counts come from filter-counts)
async function loadProjects() {
  if (props.isTrashMode || props.inProjectScope) return  // project filtering isn't offered here
  try {
    const response = await getProjects()
    projects.value = (response || [])
      .filter(p => !p.deleted_at)
      .map(p => ({ id: p.id, name: p.name }))
  } catch (error) {
    console.error('Failed to load projects:', error)
  }
}

// Load unfiltered total count
async function loadUnfilteredCount() {
  try {
    const params = {
      page: 1,
      page_size: 1,
      state: props.isTrashMode ? 'trashed' : 'active'
    }
    const response = await fetchAssets(params)
    unfilteredTotalCount.value = response.total
  } catch (error) {
    console.error('Failed to load unfiltered count:', error)
  }
}

// Load filter counts
async function loadFilterCounts() {
  try {
    const params = {
      keyword_limit: 50,  // Get preview counts for top 50 keywords to ensure we cover the top 5 displayed
      state: props.isTrashMode ? 'trashed' : 'active'
    }

    // Pass current filter state
    if (props.captionQuery) params.caption_query = props.captionQuery
    if (props.promptQuery) params.prompt_query = props.promptQuery
    if (props.mediaTypes && props.mediaTypes.length > 0) {
      params.media_types = props.mediaTypes.join(',')
    }
    if (props.excludedMediaTypes && props.excludedMediaTypes.length > 0) {
      params.excluded_media_types = props.excludedMediaTypes.join(',')
    }
    if (props.resolutions && props.resolutions.length > 0) {
      params.resolutions = props.resolutions.join(',')
    }
    if (props.excludedResolutions && props.excludedResolutions.length > 0) {
      params.excluded_resolutions = props.excludedResolutions.join(',')
    }
    if (props.selectedKeywords && props.selectedKeywords.length > 0) {
      params.keywords = props.selectedKeywords.join(',')
    }
    if (props.excludedKeywords && props.excludedKeywords.length > 0) {
      params.excluded_keywords = props.excludedKeywords.join(',')
    }
    if (props.selectedFolders && props.selectedFolders.length > 0) {
      params.folders = props.selectedFolders.join(',')
    }
    if (props.excludedFolders && props.excludedFolders.length > 0) {
      params.excluded_folders = props.excludedFolders.join(',')
    }
    if (props.selectedTags && props.selectedTags.length > 0) {
      params.tag_ids = props.selectedTags.join(',')
    }
    if (props.excludedTags && props.excludedTags.length > 0) {
      params.excluded_tag_ids = props.excludedTags.join(',')
    }
    if (props.selectedProjects && props.selectedProjects.length > 0) {
      params.project_ids = props.selectedProjects.join(',')
    }
    if (props.excludedProjects && props.excludedProjects.length > 0) {
      params.excluded_project_ids = props.excludedProjects.join(',')
    }
    if (props.projectMembership === 'any') params.has_project = true
    else if (props.projectMembership === 'none') params.has_project = false
    if (props.selectedTools && props.selectedTools.length > 0) {
      params.tool_ids = props.selectedTools.join(',')
    }
    if (props.excludedTools && props.excludedTools.length > 0) {
      params.excluded_tool_ids = props.excludedTools.join(',')
    }
    if (props.selectedMarkers && props.selectedMarkers.length > 0) {
      params.marker_ids = props.selectedMarkers.join(',')
    }
    if (props.excludedMarkers && props.excludedMarkers.length > 0) {
      params.excluded_marker_ids = props.excludedMarkers.join(',')
    }
    if (props.isImported !== null && props.isImported !== undefined) {
      params.is_imported = props.isImported
    }
    if (props.isUnused !== null && props.isUnused !== undefined) {
      params.is_unused = props.isUnused
    }
    if (props.showExpiring) params.show_expiring = true
    if (props.excludeExpiring) params.exclude_expiring = true
    if (props.createdAfter) params.created_after = props.createdAfter
    if (props.createdBefore) params.created_before = props.createdBefore

    // Include similarity filter if active (not applicable in trash mode)
    if (!props.isTrashMode && props.similarSearchActive) {
      if (props.similarFaceTo && props.similarFaceTo.length > 0) {
        params.similar_face_to = props.similarFaceTo.join(',')
      } else if (props.similarTo && props.similarTo.length > 0) {
        params.similar_to = props.similarTo.join(',')
      } else if (props.similarSearchSourceItems && props.similarSearchSourceItems.length > 0) {
        params.similar_to = props.similarSearchSourceItems.map(item => item.media_id || item.id).join(',')
      }
    }

    const response = await getAssetFilterCounts(params)
    filterCounts.value = response
    // Update tags from filter counts (includes filtered usage_count)
    if (response.tags) {
      tags.value = response.tags
    }
    console.log('Loaded filter counts:', filterCounts.value)
    console.log('Keyword preview counts:', filterCounts.value.keywords)
  } catch (error) {
    console.error('Failed to load filter counts:', error)
  }
}

// Sync with props - use functions that avoid creating new array references
function syncArray(local, prop) {
  const newVal = prop || []
  // Only update if content actually changed (avoid reference changes triggering loops)
  if (JSON.stringify(local.value) !== JSON.stringify(newVal)) {
    local.value = newVal
  }
}

watch(() => props.captionQuery, (val) => localCaptionQuery.value = val || '')
watch(() => props.promptQuery, (val) => localPromptQuery.value = val || '')
watch(() => props.similarToText, (val) => localSimilarToText.value = val || '')
watch(() => props.mediaTypes, (val) => syncArray(localMediaTypes, val))
watch(() => props.excludedMediaTypes, (val) => syncArray(localExcludedMediaTypes, val))
watch(() => props.resolutions, (val) => syncArray(localResolutions, val))
watch(() => props.excludedResolutions, (val) => syncArray(localExcludedResolutions, val))
watch(() => props.sortBy, (val) => localSortBy.value = val)
watch(() => props.selectedKeywords, (val) => syncArray(selectedKeywords, val))
watch(() => props.excludedKeywords, (val) => syncArray(excludedKeywords, val))
watch(() => props.selectedFolders, (val) => syncArray(selectedFolders, val))
watch(() => props.excludedFolders, (val) => syncArray(excludedFolders, val))
watch(() => props.similarityThreshold, (val) => localSimilarityThreshold.value = val ?? 0.75)
watch(() => props.createdAfter, (val) => {
  if ((val || null) === localCreatedAfter.value) return  // echo of our own emit; keep quick-range identity
  localCreatedAfter.value = val || null
  selectedDateRange.value = detectDateRangeFromProps()
  dateRangeExcluded.value = false
})
watch(() => props.createdBefore, (val) => {
  if ((val || null) === localCreatedBefore.value) return  // echo of our own emit; keep quick-range identity
  localCreatedBefore.value = val || null
  selectedDateRange.value = detectDateRangeFromProps()
  dateRangeExcluded.value = false
})
watch(() => props.selectedTags, (val) => syncArray(selectedTags, val))
watch(() => props.excludedTags, (val) => syncArray(excludedTags, val))
watch(() => props.selectedProjects, (val) => syncArray(selectedProjects, val))
watch(() => props.excludedProjects, (val) => syncArray(excludedProjects, val))
watch(() => props.projectMembership, (val) => projectMembership.value = val || null)
watch(() => props.selectedTools, (val) => syncArray(selectedTools, val))
watch(() => props.excludedTools, (val) => syncArray(excludedTools, val))
watch(() => props.selectedMarkers, (val) => syncArray(selectedMarkers, val))
watch(() => props.excludedMarkers, (val) => syncArray(excludedMarkers, val))
watch(() => props.isImported, (val) => localIsImported.value = val ?? null)
watch(() => props.isUnused, (val) => localIsUnused.value = val ?? null)
watch(() => props.showExpiring, (val) => localShowExpiring.value = val || false)
watch(() => props.excludeExpiring, (val) => localExcludeExpiring.value = val || false)
// Reload counts when similarity search changes
watch(() => props.similarSearchActive, () => {
  loadFilterCounts()
})

// Auto-switch to similarity sort when text search is entered
watch(localSimilarToText, (newVal, oldVal) => {
  if (newVal && newVal.trim() && (!oldVal || !oldVal.trim())) {
    // Text search activated - switch to similarity sort
    localSortBy.value = 'similarity'
  } else if ((!newVal || !newVal.trim()) && oldVal && oldVal.trim()) {
    // Text search cleared - revert to default sort
    if (localSortBy.value === 'similarity') {
      localSortBy.value = 'created_desc'
    }
  }
})

// Debounced watcher for filter changes to reload preview counts
let filterCountsDebounceTimer = null
watch(
  () => [
    props.captionQuery,
    props.promptQuery,
    props.mediaTypes,
    props.excludedMediaTypes,
    props.resolutions,
    props.excludedResolutions,
    props.selectedKeywords,
    props.excludedKeywords,
    props.selectedFolders,
    props.excludedFolders,
    props.selectedTags,
    props.excludedTags,
    props.selectedProjects,
    props.excludedProjects,
    props.projectMembership,
    props.selectedTools,
    props.excludedTools,
    props.selectedMarkers,
    props.excludedMarkers,
    props.isImported,
    props.isUnused,
    props.similarTo,
    props.similarFaceTo,
    props.similarSearchSourceItems,
    props.similarityThreshold
  ],
  () => {
    // Clear existing timer
    if (filterCountsDebounceTimer) {
      clearTimeout(filterCountsDebounceTimer)
    }

    // Set new timer (500ms debounce)
    filterCountsDebounceTimer = setTimeout(() => {
      loadFilterCounts()
      loadTopKeywords()  // Also reload top keywords when filters change
    }, 500)
  },
  { deep: true }
)

// Handle profile changes - reload all filter data for new profile
async function handleProfileChanged() {
  console.log('[FilterBar] Profile changed, reloading filter data')

  // Reset local state
  topKeywords.value = []
  tags.value = []
  folders.value = []
  projects.value = []
  filterCounts.value = {
    media_type: { images: 0, videos: 0, audio: 0, text: 0, sets: 0, grids: 0, layouts: 0 },
    resolution: { small: 0, medium: 0, large: 0 },
    folders: {},
    keywords: {},
    projects: {},
    project_membership: { any: 0, none: 0 },
    date_ranges: {},
    imported: 0,
    expiring: 0,
    unused: 0
  }
  unfilteredTotalCount.value = null
  hasLoadedCounts.value = false

  // Always reload folders and tags (needed even when panel is closed)
  loadUnfilteredCount()
  await Promise.all([
    loadTags(),
    loadFolders(),
    loadProjects()
  ])

  // If panel is open, also reload keywords and counts
  if (showCriteriaPanel.value) {
    hasLoadedCounts.value = true
    isLoading.value = true
    try {
      await Promise.all([
        loadTopKeywords(),
        loadFilterCounts()
      ])
    } finally {
      isLoading.value = false
    }
  }
}

onMounted(async () => {
  // Click outside handler for saved view menu
  document.addEventListener('click', handleClickOutside)

  // Always load unfiltered count immediately for "X of Y" display
  loadUnfilteredCount()

  // Always load tags and folders immediately so they can be displayed in the shopping cart strip
  // even when the panel is closed (e.g., when filtering by tag/folder from slideshow)
  await Promise.all([
    loadTags(),
    loadFolders(),
    loadProjects()
  ])

  // If panel is already open, load keywords and counts immediately
  // Otherwise they'll load when panel is first opened
  if (showCriteriaPanel.value) {
    hasLoadedCounts.value = true
    isLoading.value = true
    try {
      await Promise.all([
        loadTopKeywords(),
        loadFilterCounts()
      ])
    } finally {
      isLoading.value = false
    }
  } else {
    isLoading.value = false
  }

  // Listen for profile changes
  window.addEventListener('profile-changed', handleProfileChanged)
})

onUnmounted(() => {
  window.removeEventListener('profile-changed', handleProfileChanged)
  document.removeEventListener('click', handleClickOutside)
})

// Expose methods for parent components to call
defineExpose({
  refreshTags: loadTags,
  reloadForProfile: handleProfileChanged
})
</script>

<style scoped>
/* Spinner animation */
.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Range slider custom styling */
.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  background: var(--slider-thumb);
  border-radius: 50%;
  cursor: pointer;
  transition: background 0.2s;
}

.slider::-webkit-slider-thumb:hover {
  background: var(--slider-thumb-hover);
}

.slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  background: var(--slider-thumb);
  border-radius: 50%;
  cursor: pointer;
  border: none;
  transition: background 0.2s;
}

.slider::-moz-range-thumb:hover {
  background: var(--slider-thumb-hover);
}

/* Slide Down Animation */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
  max-height: 500px;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  max-height: 0;
  opacity: 0;
}

/* Custom Scrollbar for Horizontal Overflow in Filter Panel */
.overflow-x-auto::-webkit-scrollbar {
  -webkit-appearance: none;
  height: 8px;
}

.overflow-x-auto::-webkit-scrollbar-track {
  background: transparent;
}

.overflow-x-auto::-webkit-scrollbar-thumb {
  background: rgba(156, 163, 175, 0.3);
  border-radius: 4px;
}

.overflow-x-auto::-webkit-scrollbar-thumb:hover {
  background: rgba(156, 163, 175, 0.5);
}

/* Firefox scrollbar */
.overflow-x-auto {
  scrollbar-width: thin;
  scrollbar-color: rgba(156, 163, 175, 0.3) transparent;
}

/* Dark mode styling for date inputs and calendar popups */
.date-input {
  color-scheme: dark;
}

.date-input::-webkit-calendar-picker-indicator {
  cursor: pointer;
}

.date-input::-webkit-datetime-edit {
  color: white;
}

.date-input::-webkit-datetime-edit-fields-wrapper {
  color: white;
}

.date-input::-webkit-datetime-edit-text {
  color: var(--color-text-muted);
}

.date-input::-webkit-datetime-edit-month-field,
.date-input::-webkit-datetime-edit-day-field,
.date-input::-webkit-datetime-edit-year-field {
  color: var(--color-text-primary);
}
</style>
