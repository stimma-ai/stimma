<template>
  <div class="contents">
    <!-- SVG gradient definition for Stimma Cloud branding -->
    <svg class="absolute w-0 h-0" aria-hidden="true">
      <defs>
        <linearGradient id="stimma-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0d9488" />
          <stop offset="50%" stop-color="#06b6d4" />
          <stop offset="100%" stop-color="#6366f1" />
        </linearGradient>
      </defs>
    </svg>

    <!-- Mobile overlay backdrop -->
    <Transition name="fade">
      <div
        v-if="isOpen && isMobile"
        class="fixed inset-0 bg-overlay-backdrop z-modal"
        @click="$emit('close')"
      ></div>
    </Transition>

    <!-- Sidebar -->
    <Transition :name="isMobile ? 'slide' : ''">
      <div
        v-if="!isMobile || isOpen"
        class="navigation-sidebar h-screen bg-surface border-r border-edge-subtle flex flex-col flex-shrink-0"
        :class="isMobile ? 'fixed top-0 left-0 z-modal shadow-[2px_0_10px_rgba(0,0,0,0.3)] w-[276px]' : 'relative'"
        :style="!isMobile ? { width: `${sidebarWidth}px` } : undefined"
      >
        <!-- Draggable region + fade overlay for traffic light area -->
        <div v-if="isTauriMac" class="absolute top-0 left-0 right-3 h-9 z-10 pointer-events-none">
          <div class="absolute top-0 left-0 right-0 h-7 bg-surface" data-tauri-drag-region style="pointer-events: auto;" />
          <div class="absolute bottom-0 left-0 right-0 h-2 bg-gradient-to-b from-surface to-transparent" />
        </div>

        <!-- Nav Menu - only show when we have data -->
        <nav v-if="hasLoadedData" ref="navEl" @scroll.passive="updateNavEdge" class="p-3 flex flex-col gap-1 flex-1 overflow-y-auto custom-scrollbar" :class="isTauriMac ? 'pt-10' : 'pt-3'">

          <!-- ==================== ZONE 1: Library Links ==================== -->

          <!-- Stimma Home -->
          <button
            @click="handleNavClick('home')"
            @dragover="handleDragOver"
            @dragenter="handleStimmaHomeDragEnter"
            @dragleave="handleStimmaHomeDragLeave"
            @drop="handleStimmaHomeDrop"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-medium transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="[
              activeTab === 'home' ? '!bg-overlay-hover !text-content' : '',
              dragHoverStimmaHome ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
            ]"
            title="Stimma (drag media here to attach)"
          >
            <img src="/logo.png" class="w-3.5 h-3.5 flex-shrink-0" :class="{ 'logo-disconnected': !wsConnected }" alt="" />
            <span class="font-brand lowercase tracking-[0.12em]">stimma</span>
          </button>

          <!-- Saved Views -->
          <button
            v-for="savedView in savedViews"
            :key="savedView.id"
            @click="openSavedView(savedView.id)"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="isSavedViewActive(savedView.id) ? '!bg-overlay-hover !text-content' : ''"
            :title="savedView.name"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
            <span class="truncate text-sm">{{ savedView.name }}</span>
          </button>

          <!-- All Assets -->
          <button
            @click="handleNavClick('browse')"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="activeTab === 'browse' ? '!bg-overlay-hover !text-content' : ''"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
            <span>All Assets</span>
          </button>

          <!-- Trash -->
          <button
            @click="handleNavClick('trash')"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="activeTab === 'trash' ? '!bg-overlay-hover !text-content' : ''"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            <span>Trash</span>
          </button>

          <div class="group relative">
            <button
              @click="handleNavClick('projects')"
              class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
              :class="activeTab === 'projects' ? '!bg-overlay-hover !text-content' : ''"
            >
              <ArchiveBoxIcon class="w-3.5 h-3.5 flex-shrink-0" />
              <span>Projects</span>
            </button>
            <Tooltip text="Create new project" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewProject"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </button>
            </Tooltip>
          </div>

          <!-- Boards landing link (with drag-drop to create new) -->
          <div class="group relative">
            <button
              @click="handleNavClick('boards')"
              @dragover="handleDragOver"
              @dragenter="handleNewBoardDragEnter"
              @dragleave="handleNewBoardDragLeave"
              @drop="handleNewBoardDrop"
              class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
              :class="[
                activeTab === 'boards' ? '!bg-overlay-hover !text-content' : '',
                dragHoverNewBoard ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Boards (drag media here to create new)"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
              </svg>
              <span>Boards</span>
            </button>
            <!-- Create new board button -->
            <Tooltip text="Create new board" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewBoard"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </button>
            </Tooltip>
          </div>

          <!-- Chats landing link (with drag-drop to create new) -->
          <div class="group relative">
            <button
              @click="handleNavClick('chats')"
              data-tour="chats"
              @dragover="handleDragOver"
              @dragenter="handleNewChatDragEnter"
              @dragleave="handleNewChatDragLeave"
              @drop="handleNewChatDrop"
              class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
              :class="[
                activeTab === 'chats' ? '!bg-overlay-hover !text-content' : '',
                dragHoverNewChat ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Chats (drag media here to create new)"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
              </svg>
              <span>Chats</span>
            </button>
            <!-- Create new chat button -->
            <Tooltip text="Create new chat" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewChat"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </button>
            </Tooltip>
          </div>

          <!-- Flows landing link -->
          <div class="group relative">
            <button
              @click="handleNavClick('flows')"
              @dragover="handleDragOver"
              @dragenter="handleNewFlowDragEnter"
              @dragleave="handleNewFlowDragLeave"
              @drop="handleNewFlowDrop"
              class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
              :class="[
                activeTab === 'flows' ? '!bg-overlay-hover !text-content' : '',
                dragHoverNewFlow ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Flows (drag media here to create new)"
            >
              <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
              <span>Flows</span>
            </button>
            <Tooltip text="Create new flow" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewFlow"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </button>
            </Tooltip>
          </div>

          <!-- Tools landing link -->
          <button
            @click="handleNavClick('all-tools')"
            data-tour="tools"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="activeTab === 'all-tools' ? '!bg-overlay-hover !text-content' : ''"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
            </svg>
            <span>Tools</span>
          </button>

          <!-- Stimpacks landing link -->
          <button
            @click="handleNavClick('stimpacks')"
            class="flex items-center gap-2.5 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left"
            :class="activeTab === 'stimpacks' ? '!bg-overlay-hover !text-content' : ''"
          >
            <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
            </svg>
            <span>Stimpacks</span>
          </button>

          <!-- ==================== ZONE 2: Workspace Tabs ==================== -->
          <div v-if="pinnedTabs.length > 0 || openTabs.length > 0" class="mt-3">
            <div class="mx-3 mb-2 border-t border-edge-subtle"></div>

            <!-- Pinned/open micro-labels replace the old dashed separator -->
            <div v-if="pinnedTabs.length > 0" class="px-3 pt-1 pb-1 text-xs font-semibold text-content-secondary">Pinned</div>

            <!-- Pinned tabs -->
            <div
              v-for="(tab, index) in pinnedTabs"
              :key="'pinned-' + tab.id"
              class="group relative"
              draggable="true"
              @dragstart="handleTabReorderDragStart(index, 'pinned', $event)"
              @dragend="handleTabReorderDragEnd"
              @dragover="handleTabReorderDragOver(index, 'pinned', $event)"
              @drop="handleTabReorderDrop(index, 'pinned', $event)"
            >
              <!-- Drop indicator line -->
              <div
                v-if="tabReorderDropTarget?.index === index && tabReorderDropTarget?.group === 'pinned'"
                class="absolute left-0 right-0 h-0.5 bg-accent-hi -top-px z-10"
              ></div>
              <button
                @click="navigateToTab(tab)"
                @contextmenu="showTabContextMenu(tab, $event)"
                @dragover="handleTabDragOver(tab, $event)"
                @dragenter="handleTabDragEnter(tab, $event)"
                @dragleave="handleTabDragLeave(tab, $event)"
                @drop="handleTabMediaDrop(tab, $event)"
                class="flex items-center gap-2.5 px-3 py-2 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent text-left w-full"
                :class="[
                  isTabActive(tab) ? '!bg-overlay-hover !text-content' : '',
                  dragHoverTabId === tab.id ? (tab.type === 'tool' && dragAddModifier ? '!bg-green-500/20 !text-content ring-1 ring-green-500/50' : '!bg-accent/10 !text-content ring-1 ring-accent') : '',
                  tab.type === 'tool' && !isToolCompatible(tab.entityId) ? 'opacity-50' : '',
                  isTabToolUnavailable(tab) ? 'pr-7 opacity-70 group-hover:opacity-100' : ''
                ]"
                :style="{ minHeight: '44px' }"
                :title="tab.type === 'tool' ? (getToolIncompatibilityReason(tab.entityId) || tab.displayName) : tab.displayName"
              >
                <!-- Inline rename -->
                <template v-if="editingItem?.tabId === tab.id">
                  <MediaImage v-if="tab.type === 'editor' && tab.editorMediaId" :media-id="Number(tab.editorMediaId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <MediaImage v-else-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'board'" class="w-8 h-8 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-0.5 flex-shrink-0">
                    <div v-if="getBoardPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-0.5">
                      <div
                        v-for="(column, columnIndex) in getBoardPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-rename-board-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-0.5"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-rename-board-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getBoardPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isBoardPreviewVideo(item.file_format)"
                            thumbnail
                            :thumbnail-size="128"
                            :draggable="false"
                            :enable-context-menu="false"
                            container-class="h-full w-full"
                            img-class="h-full w-full object-cover"
                          />
                        </div>
                      </div>
                    </div>
                    <div v-else class="flex h-full items-center justify-center">
                      <component :is="getTabIcon(tab)" class="w-4 h-4 text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" />
                  <div v-else-if="tab.type === 'tool'" class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <div class="w-7 h-7"><ToolIcon :tool="getToolForIcon(tab.entityId)" bare :ring="false" /></div>
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 flex-shrink-0" />
                  <input v-no-autocorrect
                    v-model="editingName"
                    @keydown="handleRenameKeydown"
                    @blur="saveRename"
                    @click.stop
                    class="flex-1 bg-transparent text-content text-sm font-normal outline-none border-none min-w-0"
                    placeholder="Name..."
                    autofocus
                  />
                </template>
                <!-- Normal display -->
                <template v-else>
                  <MediaImage v-if="tab.type === 'editor' && tab.editorMediaId" :media-id="Number(tab.editorMediaId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <MediaImage v-else-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'board'" class="w-8 h-8 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-0.5 flex-shrink-0">
                    <div v-if="getBoardPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-0.5">
                      <div
                        v-for="(column, columnIndex) in getBoardPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-board-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-0.5"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-board-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getBoardPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isBoardPreviewVideo(item.file_format)"
                            thumbnail
                            :thumbnail-size="128"
                            :draggable="false"
                            :enable-context-menu="false"
                            container-class="h-full w-full"
                            img-class="h-full w-full object-cover"
                          />
                        </div>
                      </div>
                    </div>
                    <div v-else class="flex h-full items-center justify-center">
                      <component :is="getTabIcon(tab)" class="w-4 h-4 text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" />
                  <div v-else-if="tab.type === 'tool'" class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <div class="w-7 h-7"><ToolIcon :tool="getToolForIcon(tab.entityId)" bare :ring="false" /></div>
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 flex-shrink-0" />

                  <!-- Tool with title/subtitle -->
                  <div v-if="tab.type === 'tool'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col" @dblclick.stop="startInlineRename(tab)">
                      <span class="truncate text-[13px] text-content">
                        {{ getToolTabTitle(tab) }}
                      </span>
                      <!-- Renamed instance: tool name condenses onto the subtitle
                           line, provider (and its cloud gradient) preserved -->
                      <span v-if="tab.customName" class="truncate text-[11px] text-content-muted">
                        {{ tab.displayName }} · <span :class="getToolSubtitleClass(tab.entityId)">{{ getToolSubtitle(tab.entityId) }}</span>
                      </span>
                      <span
                        v-else
                        class="truncate text-[11px]"
                        :class="getToolSubtitleClass(tab.entityId)"
                      >
                        {{ getToolSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="tab.projectName"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ tab.projectName }}</span>
                  </div>

                  <!-- Board with title/subtitle -->
                  <div v-else-if="tab.type === 'board' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] text-content">
                        {{ tab.displayName }}
                      </span>
                      <span class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatBoardTabDetail(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getBoardProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getBoardProjectName(tab.entityId) }}</span>
                  </div>

                  <div v-else-if="tab.type === 'project' && tab.displayName" class="flex-1 min-w-0 flex flex-col">
                    <span class="truncate text-[13px] text-content">
                      {{ tab.displayName }}
                    </span>
                    <span class="truncate text-[11px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Project without name -->
                  <div v-else-if="tab.type === 'project'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this project...
                    </span>
                    <span class="truncate text-[11px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Chat with title/subtitle -->
                  <div v-else-if="tab.type === 'chat' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] text-content">
                        {{ tab.displayName }}
                      </span>
                      <span v-if="formatChatTabSubtitle(tab.entityId)" class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatChatTabSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getChatProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getChatProjectName(tab.entityId) }}</span>
                  </div>

                  <!-- Chat without name -->
                  <div v-else-if="tab.type === 'chat'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span
                        @click.stop="startInlineRename(tab)"
                        class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                      >
                        Name this chat...
                      </span>
                      <span v-if="formatChatTabSubtitle(tab.entityId)" class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatChatTabSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getChatProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getChatProjectName(tab.entityId) }}</span>
                  </div>

                  <!-- Flow with title/subtitle -->
                  <div v-else-if="tab.type === 'flow'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      v-if="tab.displayName"
                      class="truncate text-[13px] text-content"
                    >
                      {{ tab.displayName }}
                    </span>
                    <span
                      v-else
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this flow...
                    </span>
                    <FlowStatusPill
                      :flow-id="tab.entityId"
                      show-pending
                      text-class="truncate text-[11px] text-content-muted"
                    />
                  </div>

                  <!-- Non-tool/chat/board/flow items -->
                  <span
                    v-else-if="tab.displayName"
                    class="truncate text-sm flex-1"
                  >
                    {{ tab.displayName }}
                  </span>
                  <span
                    v-else-if="tab.type === 'board'"
                    @click.stop="startInlineRename(tab)"
                    class="truncate text-sm flex-1 text-content-muted italic cursor-pointer hover:text-content-secondary"
                  >
                    Name this board...
                  </span>
                  <StatusDot
                    v-if="isTabGenerating(tab) && tab.type !== 'flow'"
                    bucket="running"
                    pulse
                    class="self-center"
                  />
                  <StatusDot
                    v-else-if="unseenKindFor(tab.id)"
                    :bucket="unseenKindFor(tab.id) === 'error' ? 'failed' : 'running'"
                    class="self-center"
                    :title="unseenKindFor(tab.id) === 'error' ? 'Finished with errors since you last looked' : 'Finished since you last looked'"
                  />
                </template>
              </button>
              <!-- Unavailable indicator (warning triangle), same slot a close X would use -->
              <span
                v-if="isTabToolUnavailable(tab)"
                class="absolute right-1.5 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center text-content-muted pointer-events-none"
                :title="getToolSubtitle(tab.entityId)"
              >
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </span>
            </div>

            <!-- Drop zone after last pinned tab -->
            <div
              v-if="pinnedTabs.length > 0 && tabReorderDragSource?.group === 'pinned'"
              class="relative h-2"
              @dragover="handleTabReorderDragOver(pinnedTabs.length, 'pinned', $event)"
              @drop="handleTabReorderDrop(pinnedTabs.length, 'pinned', $event)"
            >
              <div
                v-if="tabReorderDropTarget?.index === pinnedTabs.length && tabReorderDropTarget?.group === 'pinned'"
                class="absolute left-0 right-0 h-0.5 bg-accent-hi top-0 z-10"
              ></div>
            </div>

            <!-- Separator + micro-label between pinned and open tabs -->
            <div v-if="pinnedTabs.length > 0 && openTabs.length > 0" class="mx-3 my-1 border-t border-edge-subtle"></div>
            <div v-if="openTabs.length > 0" class="px-3 pt-3 pb-1 text-xs font-semibold text-content-secondary">Open</div>

            <!-- Open (unpinned) tabs -->
            <div
              v-for="(tab, index) in openTabs"
              :key="'open-' + tab.id"
              class="group relative"
              draggable="true"
              @dragstart="handleTabReorderDragStart(index, 'open', $event)"
              @dragend="handleTabReorderDragEnd"
              @dragover="handleTabReorderDragOver(index, 'open', $event)"
              @drop="handleTabReorderDrop(index, 'open', $event)"
            >
              <!-- Drop indicator line -->
              <div
                v-if="tabReorderDropTarget?.index === index && tabReorderDropTarget?.group === 'open'"
                class="absolute left-0 right-0 h-0.5 bg-accent-hi -top-px z-10"
              ></div>
              <button
                @click="navigateToTab(tab)"
                @contextmenu="showTabContextMenu(tab, $event)"
                @dragover="handleTabDragOver(tab, $event)"
                @dragenter="handleTabDragEnter(tab, $event)"
                @dragleave="handleTabDragLeave(tab, $event)"
                @drop="handleTabMediaDrop(tab, $event)"
                class="flex items-center gap-3 px-3 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent text-left w-full group-hover:pr-7"
                :class="[
                  isTabActive(tab) ? '!bg-overlay-hover !text-content' : '',
                  dragHoverTabId === tab.id ? (tab.type === 'tool' && dragAddModifier ? '!bg-green-500/20 !text-content ring-1 ring-green-500/50' : '!bg-accent/10 !text-content ring-1 ring-accent') : '',
                  tab.type === 'tool' && !isToolCompatible(tab.entityId) ? 'opacity-50' : '',
                  isTabToolUnavailable(tab) ? 'pr-7 opacity-70 group-hover:opacity-100' : '',
                  tab.type === 'tool' ? 'py-1.5' : 'py-2'
                ]"
                :style="{ minHeight: '44px' }"
                :title="tab.type === 'tool' ? (getToolIncompatibilityReason(tab.entityId) || tab.displayName) : tab.displayName"
              >
                <!-- Inline rename -->
                <template v-if="editingItem?.tabId === tab.id">
                  <MediaImage v-if="tab.type === 'editor' && tab.editorMediaId" :media-id="Number(tab.editorMediaId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <MediaImage v-else-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'board'" class="w-8 h-8 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-0.5 flex-shrink-0">
                    <div v-if="getBoardPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-0.5">
                      <div
                        v-for="(column, columnIndex) in getBoardPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-rename-open-board-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-0.5"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-rename-open-board-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getBoardPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isBoardPreviewVideo(item.file_format)"
                            thumbnail
                            :thumbnail-size="128"
                            :draggable="false"
                            :enable-context-menu="false"
                            container-class="h-full w-full"
                            img-class="h-full w-full object-cover"
                          />
                        </div>
                      </div>
                    </div>
                    <div v-else class="flex h-full items-center justify-center">
                      <component :is="getTabIcon(tab)" class="w-4 h-4 text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" />
                  <div v-else-if="tab.type === 'tool'" class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <div class="w-7 h-7"><ToolIcon :tool="getToolForIcon(tab.entityId)" bare :ring="false" /></div>
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 flex-shrink-0" />
                  <input v-no-autocorrect
                    v-model="editingName"
                    @keydown="handleRenameKeydown"
                    @blur="saveRename"
                    @click.stop
                    class="flex-1 bg-transparent text-content text-sm font-normal outline-none border-none min-w-0"
                    placeholder="Name..."
                    autofocus
                  />
                </template>
                <!-- Normal display -->
                <template v-else>
                  <MediaImage v-if="tab.type === 'editor' && tab.editorMediaId" :media-id="Number(tab.editorMediaId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <MediaImage v-else-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'board'" class="w-8 h-8 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-0.5 flex-shrink-0">
                    <div v-if="getBoardPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-0.5">
                      <div
                        v-for="(column, columnIndex) in getBoardPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-open-board-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-0.5"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-open-board-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getBoardPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isBoardPreviewVideo(item.file_format)"
                            thumbnail
                            :thumbnail-size="128"
                            :draggable="false"
                            :enable-context-menu="false"
                            container-class="h-full w-full"
                            img-class="h-full w-full object-cover"
                          />
                        </div>
                      </div>
                    </div>
                    <div v-else class="flex h-full items-center justify-center">
                      <component :is="getTabIcon(tab)" class="w-4 h-4 text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" />
                  <div v-else-if="tab.type === 'tool'" class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <div class="w-7 h-7"><ToolIcon :tool="getToolForIcon(tab.entityId)" bare :ring="false" /></div>
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 flex-shrink-0" />

                  <!-- Tool with title/subtitle -->
                  <div v-if="tab.type === 'tool'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col" @dblclick.stop="startInlineRename(tab)">
                      <span class="truncate text-[13px] text-content">
                        {{ getToolTabTitle(tab) }}
                      </span>
                      <!-- Renamed instance: tool name condenses onto the subtitle
                           line, provider (and its cloud gradient) preserved -->
                      <span v-if="tab.customName" class="truncate text-[11px] text-content-muted">
                        {{ tab.displayName }} · <span :class="getToolSubtitleClass(tab.entityId)">{{ getToolSubtitle(tab.entityId) }}</span>
                      </span>
                      <span
                        v-else
                        class="truncate text-[11px]"
                        :class="getToolSubtitleClass(tab.entityId)"
                      >
                        {{ getToolSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="tab.projectName"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ tab.projectName }}</span>
                  </div>

                  <!-- Board with title/subtitle -->
                  <div v-else-if="tab.type === 'board' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] text-content">
                        {{ tab.displayName }}
                      </span>
                      <span class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatBoardTabDetail(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getBoardProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getBoardProjectName(tab.entityId) }}</span>
                  </div>

                  <div v-else-if="tab.type === 'project' && tab.displayName" class="flex-1 min-w-0 flex flex-col">
                    <span class="truncate text-[13px] text-content">
                      {{ tab.displayName }}
                    </span>
                    <span class="truncate text-[11px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Project without name -->
                  <div v-else-if="tab.type === 'project'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this project...
                    </span>
                    <span class="truncate text-[11px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Chat with title/subtitle -->
                  <div v-else-if="tab.type === 'chat' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] text-content">
                        {{ tab.displayName }}
                      </span>
                      <span v-if="formatChatTabSubtitle(tab.entityId)" class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatChatTabSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getChatProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getChatProjectName(tab.entityId) }}</span>
                  </div>

                  <!-- Chat without name -->
                  <div v-else-if="tab.type === 'chat'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span
                        @click.stop="startInlineRename(tab)"
                        class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                      >
                        Name this chat...
                      </span>
                      <span v-if="formatChatTabSubtitle(tab.entityId)" class="min-w-0 truncate text-[11px] text-content-muted">
                        {{ formatChatTabSubtitle(tab.entityId) }}
                      </span>
                    </div>
                    <span
                      v-if="getChatProjectName(tab.entityId)"
                      class="flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px]"
                    >{{ getChatProjectName(tab.entityId) }}</span>
                  </div>

                  <!-- Flow with title/subtitle -->
                  <div v-else-if="tab.type === 'flow'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      v-if="tab.displayName"
                      class="truncate text-[13px] text-content"
                    >
                      {{ tab.displayName }}
                    </span>
                    <span
                      v-else
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this flow...
                    </span>
                    <FlowStatusPill
                      :flow-id="tab.entityId"
                      show-pending
                      text-class="truncate text-[11px] text-content-muted"
                    />
                  </div>

                  <!-- Non-tool/chat/board/flow items -->
                  <span
                    v-else-if="tab.displayName"
                    class="truncate text-sm flex-1"
                  >
                    {{ tab.displayName }}
                  </span>
                  <span
                    v-else-if="tab.type === 'board'"
                    @click.stop="startInlineRename(tab)"
                    class="truncate text-sm flex-1 text-content-muted italic cursor-pointer hover:text-content-secondary"
                  >
                    Name this board...
                  </span>
                  <StatusDot
                    v-if="isTabGenerating(tab) && tab.type !== 'flow'"
                    bucket="running"
                    pulse
                    class="self-center"
                  />
                  <StatusDot
                    v-else-if="unseenKindFor(tab.id)"
                    :bucket="unseenKindFor(tab.id) === 'error' ? 'failed' : 'running'"
                    class="self-center"
                    :title="unseenKindFor(tab.id) === 'error' ? 'Finished with errors since you last looked' : 'Finished since you last looked'"
                  />
                </template>
              </button>
              <!-- Unavailable indicator (warning triangle); hidden on hover so the close X
                   takes the same slot — no content shift, no slide. -->
              <span
                v-if="isTabToolUnavailable(tab)"
                class="absolute right-1.5 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center text-content-muted opacity-100 group-hover:opacity-0 transition-opacity pointer-events-none"
                :title="getToolSubtitle(tab.entityId)"
              >
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </span>
              <!-- Close button (appears on hover) -->
              <Tooltip text="Close" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  @click.stop="closeTab(tab.id)"
                  class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content-secondary hover:bg-overlay-light"
                >
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </Tooltip>
            </div>

            <!-- Drop zone after last open tab -->
            <div
              v-if="openTabs.length > 0 && tabReorderDragSource?.group === 'open'"
              class="relative h-2"
              @dragover="handleTabReorderDragOver(openTabs.length, 'open', $event)"
              @drop="handleTabReorderDrop(openTabs.length, 'open', $event)"
            >
              <div
                v-if="tabReorderDropTarget?.index === openTabs.length && tabReorderDropTarget?.group === 'open'"
                class="absolute left-0 right-0 h-0.5 bg-accent-hi top-0 z-10"
              ></div>
            </div>
          </div>

        </nav>

        <!-- Footer: account chip (only when signed in) + settings gear. The
             top hairline shows only while nav content is scrolled under it
             (scroll-edge divider); border stays in flow via transparent so
             toggling never shifts layout. -->
        <div
          class="flex items-center gap-1 px-2 py-2 border-t flex-shrink-0 transition-colors"
          :class="navScrolledUnder ? 'border-edge-subtle' : 'border-transparent'"
        >
          <!-- Signed in: chip fills the left, compact feedback + gear icons
               on the right. Signed out: feedback and gear split the bar as
               equal cells so it reads as a composed strip, not two orphaned
               icons at opposite corners. -->
          <template v-if="showAccountChip">
            <Tooltip text="Stimma account" class="flex-1 min-w-0">
              <button
                @click="openAccountSettings"
                class="w-full flex items-center gap-2.5 px-2 py-1 rounded text-left transition-colors cursor-pointer hover:bg-overlay-subtle border-none bg-transparent"
              >
                <div class="w-7 h-7 rounded-full bg-overlay-light text-content-secondary flex items-center justify-center text-xs font-semibold uppercase flex-shrink-0">
                  {{ accountInitial }}
                </div>
                <div class="min-w-0 flex flex-col leading-tight">
                  <span class="text-[13px] text-content truncate">{{ accountName }}</span>
                  <span v-if="accountBalance" class="text-[11px] font-mono text-content-muted tabular-nums">{{ accountBalance }}</span>
                </div>
              </button>
            </Tooltip>
            <FeedbackFooterButton />
          </template>
          <FeedbackFooterButton v-if="!showAccountChip" wide />
          <Tooltip text="Settings (⌘,)" :class="showAccountChip ? 'w-8 flex-shrink-0' : 'flex-1'">
            <button
              @click="openSettingsFromFooter"
              class="w-full h-8 flex items-center justify-center rounded text-content-tertiary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle border-none bg-transparent"
            >
              <svg class="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
              </svg>
            </button>
          </Tooltip>
        </div>

        <!-- Drop-intent hint while media is dragged over a tool tab. Absolute
             overlay (not flow) so appearing mid-drag can't shift tabs under
             the cursor and flicker the hover state. -->
        <div
          v-if="dragHoverToolTab"
          class="pointer-events-none absolute bottom-0 left-0 right-0 z-20 border-t border-edge-subtle bg-surface/95 px-3 py-2 text-[11px]"
        >
          <span v-if="dragAddModifier" class="text-green-400 font-medium">Add to inputs</span>
          <template v-else>
            <span class="text-content font-medium">Replace inputs</span>
            <span class="text-content-muted"> · hold ⇧ to add</span>
          </template>
        </div>

        <!-- Resize handle (desktop only) -->
        <div
          v-if="!isMobile"
          class="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-accent/40 transition-colors z-10"
          @mousedown.stop="startResize"
        ></div>

      </div>
    </Transition>

    <!-- Workspace Tabs Context Menu -->
    <WorkspaceTabsContextMenu @rename="handleRenameFromContextMenu" @rename-tab="handleRenameTabFromContextMenu" @refresh="loadPinnedTools" />

    <!-- Flow-tab drop targets: pops out flush against the sidebar edge,
         centered on the tab. Pull right onto a target and release. -->
    <Teleport to="body">
      <div
        v-if="flowDropTargets"
        class="fixed z-menu w-48 bg-surface border border-edge rounded-lg shadow-xl p-1.5 space-y-1.5"
        :style="{ left: flowDropTargets.left + 'px', top: flowDropTargets.top + 'px' }"
        @dragenter.prevent="cancelFlowTargetsHide"
        @dragover.prevent="onFlowTargetsPanelDragOver"
        @dragleave="onFlowTargetsPanelDragLeave"
      >
        <div
          data-zone="__chat__"
          class="flex items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed text-[12.5px] font-medium transition-colors"
          :class="flowTargetHover === '__chat__' ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onFlowTargetDrop(null, $event)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 flex-shrink-0 pointer-events-none">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm3.75 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm3.75 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM21 12c0 4.556-4.03 8.25-9 8.25a9.76 9.76 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          <span class="truncate pointer-events-none">Chat</span>
        </div>
        <div
          v-for="zone in flowDropTargets.zones"
          :key="zone.name"
          :data-zone="zone.name"
          class="flex items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed text-[12.5px] font-medium transition-colors"
          :class="flowTargetHover === zone.name ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onFlowTargetDrop(zone, $event)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 flex-shrink-0 pointer-events-none">
            <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z" />
          </svg>
          <span class="truncate pointer-events-none">{{ zone.label }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onUpdated, watch, h, nextTick } from 'vue'
import { ArchiveBoxIcon } from '@heroicons/vue/24/outline'
import { useRouter, useRoute } from 'vue-router'
import { useWebSocket } from '../composables/useWebSocket'
import { useAuth } from '../composables/useAuth'
import { useCloudAccount } from '../composables/useCloudAccount'
import { hideAccountRef } from '../appConfig'
import { setPendingMedia } from '../composables/usePendingMedia'
import { makeProfileKey } from '../utils/storageKeys'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { createTaskTypeIconComponent } from '../utils/taskTypeIcons'
import { planToolHandoff } from '../utils/toolHandoff'
import { addToast } from '../composables/useToasts'
import { useGenerationStatus } from '../composables/useGenerationStatus'
import { useUnseenActivity } from '../composables/useUnseenActivity'
import { useAgentActivity } from '../composables/useAgentActivity'
import { useMediaApi } from '../composables/useMediaApi'
import { useProvidersApi } from '../composables/useProvidersApi'
import { useSendToTool } from '../composables/useSendToTool'
import { useWorkspaceTabs, toolTabRoute, type WorkspaceTab } from '../composables/useWorkspaceTabs'
import { removeRecentEntity } from '../composables/useRecentEntities'
import { useProjectRoute } from '../composables/useProjectRoute'
import { useWorkspaceTabsContextMenu } from '../composables/useWorkspaceTabsContextMenu'
import { useFlowCounts } from '../composables/useFlowCounts'
import { useFlowsApi } from '../composables/useFlowsApi'
import { flowMediaInputFields, fieldAcceptsDraggedType, type FlowMediaInputField } from '../utils/flowMediaInputs'
import FlowStatusPill from './flow/FlowStatusPill.vue'
import { useDragStore } from '../stores/dragStore'
import { getDroppedAssetRefs, getDroppedMediaIds } from '../composables/useDragPreview'
import { isTauri } from '../apiConfig'
import { MediaImage } from './media'
import ToolIcon from './tools/ToolIcon.vue'
import EntityIcon from './EntityIcon.vue'
import StatusDot from './ui/StatusDot.vue'
import Tooltip from './ui/Tooltip.vue'
import WorkspaceTabsContextMenu from './WorkspaceTabsContextMenu.vue'
// @ts-expect-error - distribution-aliased Vue component (see vite.config.js)
import FeedbackFooterButton from '@stimma/feedback-footer-button'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  isMobile: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'open-settings', 'media-dropped-on-tool', 'media-dropped-on-chat'])

// Platform detection
const isTauriMac = isTauri() && navigator.platform.toLowerCase().includes('mac')

// Navigation
const router = useRouter()
const route = useRoute()
const activeTab = computed(() => {
  if (String(route.name || '').startsWith('project-') || route.name === 'projects') {
    return 'projects'
  }
  return route.name
})

// WebSocket
const { on, connected: wsConnected } = useWebSocket()

// Footer: account chip + settings gear. hideAccountRef (developer toggle)
// forces the signed-out treatment for screenshots.
const { isAuthenticated, user } = useAuth()
const { cloudUser, fetchCloudAccount, formatBalance } = useCloudAccount()
const showAccountChip = computed(() => isAuthenticated.value && !hideAccountRef.value)

const accountName = computed(() => {
  const email = user.value?.email || ''
  return email.split('@')[0] || 'Account'
})
const accountInitial = computed(() => accountName.value.charAt(0) || '?')
const accountBalance = computed(() =>
  cloudUser.value ? formatBalance(cloudUser.value.credits) : ''
)

watch(isAuthenticated, (signedIn) => {
  if (signedIn) fetchCloudAccount()
}, { immediate: true })

function openAccountSettings() {
  emit('open-settings', 'account')
  if (props.isMobile) emit('close')
}

function openSettingsFromFooter() {
  emit('open-settings')
  if (props.isMobile) emit('close')
}

// Scroll-edge divider: the footer's top hairline shows only while nav
// content is scrolled under it, and disappears at scroll-bottom.
const navEl = ref<HTMLElement | null>(null)
const navScrolledUnder = ref(false)

function updateNavEdge() {
  const el = navEl.value
  navScrolledUnder.value = !!el && el.scrollHeight - el.scrollTop - el.clientHeight > 1
}

let navResizeObserver: ResizeObserver | null = null
watch(navEl, (el) => {
  navResizeObserver?.disconnect()
  navResizeObserver = null
  if (el) {
    navResizeObserver = new ResizeObserver(updateNavEdge)
    navResizeObserver.observe(el)
    updateNavEdge()
  }
})
// Content mutations (tabs opening/closing, sections loading) change
// scrollHeight without resizing the nav box, so re-check after renders.
onUpdated(() => nextTick(updateNavEdge))
onUnmounted(() => navResizeObserver?.disconnect())

// Generation status
const { isToolActive: isToolGenerating, isFeedScopeActive } = useGenerationStatus()

// Finished-while-away dots (blue = done, red = failed)
const { unseenKindFor } = useUnseenActivity()

// Chat agent activity (primed on load/reconnect, cleared on disconnect)
const { isChatGenerating } = useAgentActivity()

// Send to tool
const { sendToTool } = useSendToTool()

// Workspace tabs
const {
  pinnedTabs, openTabs, allTabs, addTab, addEditorTab, updateEditorMedia, nextEditorId,
  findNextTab, removeTab, updateTabName, removeTabByEntity,
  reconcileToolPins, moveTab, setLastLibraryRoute, getLastLibraryRoute,
  markTabActivated, updateTabCustomName
} = useWorkspaceTabs()

// Per-project last-visited sub-route memory
const { getLastProjectRoute } = useProjectRoute()

// Context menu
const tabsContextMenu = useWorkspaceTabsContextMenu()

// Per-flow status/count singleton is mounted here so FlowStatusPill (used
// below for flow tabs) has live data — we don't otherwise read it directly.
useFlowCounts()

// Drag store
const { draggedMediaInfo, draggedMediaItems, draggedMediaCount, draggedMediaType } = useDragStore()

// APIs
const { getSavedViews, getBoard, getProject, createBoard: apiCreateBoard, createProject: apiCreateProject, updateBoard, updateProject } = useMediaApi()
const { listPinnedTools, fetchProvidersAndTools, subscribeToProviderChanges } = useProvidersApi()

// ==================== State ====================

const savedViews = ref([])
const allToolsMap = ref<Map<string, any>>(new Map())
const pinnedTools = ref([])
const toolAvailabilityMap = ref<Map<string, string>>(new Map())
// True once the live provider/tool list has loaded at least once, so we know a
// pin missing from that list is genuinely orphaned (not just not-yet-loaded).
const liveToolsLoaded = ref(false)

// Backfill open tool-tab names from the resolved tool list. Tabs created by
// navigation (including a freshly-frozen custom tool) fall back to the tool id
// until the providers cache loads; keep their displayName in sync with the
// real tool name once it's available.
watch(allToolsMap, (map) => {
  for (const tab of allTabs.value) {
    if (tab.type !== 'tool') continue
    const t = map.get(tab.entityId)
    if (t?.name && t.name !== tab.displayName) updateTabName(tab.id, t.name)
  }
}, { deep: false })
type BoardPreviewItem = {
  id: number
  file_hash?: string | null
  file_path?: string | null
  file_format?: string | null
  width?: number | null
  height?: number | null
}

type BoardMetadata = {
  cover_media_id: number | null
  item_count: number
  section_count: number
  project_id: number | null
  preview_items: BoardPreviewItem[]
}

const boardMetadata = ref<Map<string, BoardMetadata>>(new Map())
const chatMetadata = ref<Map<string, { thumbnail_media_id: number | null, last_message: string, project_id: number | null }>>(new Map())
const projectNames = ref<Map<string, string>>(new Map())

// Drag-drop state
const dragHoverTabId = ref<string | null>(null)
// Live shift state while dragging over a tool tab: shift flips the drop from
// replace-inputs to add-to-inputs; cursor, ring color, and hint bar track it.
const dragAddModifier = ref(false)
// Whether the currently drag-hovered tab is a tool tab (drives the hint bar).
const dragHoverToolTab = computed(() => {
  const id = dragHoverTabId.value
  if (!id) return false
  return [...pinnedTabs.value, ...openTabs.value].some(t => t.id === id && t.type === 'tool')
})
const dragHoverNewBoard = ref(false)
const dragHoverNewChat = ref(false)
const dragHoverNewFlow = ref(false)
const dragHoverStimmaHome = ref(false)
const tabDragCounters = ref<Map<string, number>>(new Map())
const newBoardDragCounter = ref(0)
const newChatDragCounter = ref(0)
const newFlowDragCounter = ref(0)
const stimmaHomeDragCounter = ref(0)

// Tab reorder state
const tabReorderDragSource = ref<{ index: number, group: 'pinned' | 'open' } | null>(null)
const tabReorderDropTarget = ref<{ index: number, group: 'pinned' | 'open' } | null>(null)

// Inline rename state
const editingItem = ref<{ tabId: string, tabType: string, entityId: string } | null>(null)
const editingName = ref('')

// Resize state
const MIN_SIDEBAR_WIDTH = 200
const MAX_SIDEBAR_WIDTH = 500
const SIDEBAR_WIDTH_KEY = makeProfileKey('sidebar', 'width')
const sidebarWidth = ref(parseInt(localStorage.getItem(SIDEBAR_WIDTH_KEY) || '276', 10))
const isResizing = ref(false)
const resizeStartX = ref(0)
const resizeStartWidth = ref(0)

// Loading state
const loadingState = ref({
  savedViews: { loading: true, error: false },
  tools: { loading: true, error: false }
})

const hasLoadedData = computed(() => {
  return Object.values(loadingState.value).some(s => !s.loading && !s.error)
})

// ==================== Tool compatibility ====================

const toolCompatibility = computed(() => {
  const map = new Map<string, { compatible: boolean; reason?: string }>()
  const dragged = draggedMediaInfo.value
  if (!dragged) return map

  const checkTool = (tool: any) => {
    const result = planToolHandoff({
      tool,
      items: draggedMediaItems.value,
      count: draggedMediaCount.value,
    })
    if (!result.eligible) {
      map.set(tool.full_tool_id, { compatible: false, reason: result.reason })
    }
  }

  for (const tool of allToolsMap.value.values()) {
    checkTool(tool)
  }

  return map
})

function isToolCompatible(fullToolId: string): boolean {
  const info = toolCompatibility.value.get(fullToolId)
  return info?.compatible !== false
}

function getToolIncompatibilityReason(fullToolId: string): string | undefined {
  return toolCompatibility.value.get(fullToolId)?.reason
}

function getToolAvailability(fullToolId: string): string {
  return toolAvailabilityMap.value.get(fullToolId) || 'available'
}

function getToolProvider(fullToolId: string): string {
  const tool = allToolsMap.value.get(fullToolId)
  // Prefer the friendly name; fall back to the provider id, then to the
  // provider-id prefix of the full_tool_id ("{provider_id}:{tool_id}"). The
  // last form always works even for orphaned tools whose provider has been
  // removed from config and dropped from the tool cache.
  return tool?.provider_name || tool?.provider_id || fullToolId.split(':')[0] || 'Provider'
}

// Subtitle under a tool tab. When the tool is reachable we show its provider
// (e.g. "ComfyUI"); when it isn't we keep the provider identity AND explain
// *why* it's greyed out, e.g. "ComfyUI · disconnected".
// Title for a tool instance row: custom name wins; unnamed duplicates of the
// same (tool, project) get a positional "(2)" so identical rows stay tellable.
function getToolTabTitle(tab: WorkspaceTab): string {
  if (tab.customName) return tab.customName
  const unnamedSiblings = allTabs.value.filter(t =>
    t.type === 'tool' && !t.customName &&
    t.entityId === tab.entityId &&
    (t.projectId ?? null) === (tab.projectId ?? null)
  )
  if (unnamedSiblings.length <= 1) return tab.displayName
  const idx = unnamedSiblings.findIndex(t => t.id === tab.id)
  return idx > 0 ? `${tab.displayName} (${idx + 1})` : tab.displayName
}

function getToolSubtitle(fullToolId: string): string {
  const availability = getToolAvailability(fullToolId)
  const provider = getToolProvider(fullToolId)
  if (availability === 'disconnected') return `${provider} · disconnected`
  if (availability !== 'available') return `${provider} · not configured`
  return provider
}

function getToolSubtitleClass(fullToolId: string): string {
  const availability = getToolAvailability(fullToolId)
  // Unavailable tools read as a calm, de-emphasized state (muted + italic),
  // not an alarming colored one. The warning triangle in the action slot
  // carries the "needs attention" signal.
  if (availability !== 'available') return 'text-content-muted italic'
  return isToolStimmaCloud(fullToolId) ? 'stimma-cloud-text font-medium' : 'text-content-muted'
}

function isTabToolUnavailable(tab: any): boolean {
  return tab.type === 'tool' && getToolAvailability(tab.entityId) !== 'available'
}

function isToolStimmaCloud(fullToolId: string): boolean {
  const tool = allToolsMap.value.get(fullToolId)
  return tool ? isStimmaCloudTool(tool) : false
}

// Build a ToolIcon-compatible object for a tab's tool. Prefer the cached tool
// row (carries model_vendor); when it's missing (e.g. provider not yet loaded)
// pass at least the id so the task-generic glyph still renders.
function getToolForIcon(fullToolId: string) {
  const tool = allToolsMap.value.get(fullToolId)
  if (tool) return tool
  return { id: fullToolId, full_tool_id: fullToolId, task_types: [] as string[] }
}

function extractBoardMetadata(board: any) {
  const sections = board?.sections || []
  const previewItems = sections
    .flatMap((section: any) => section.items || [])
    .slice(0, 4)
  const firstItem = previewItems[0] || null
  return {
    cover_media_id: firstItem?.id || null,
    item_count: board?.asset_count || 0,
    section_count: sections.length,
    project_id: board?.project_id ?? null,
    preview_items: previewItems
  }
}

async function ensureProjectName(projectId: number | string | null | undefined) {
  if (projectId == null) return
  const key = String(projectId)
  if (projectNames.value.has(key)) return
  try {
    const project = await getProject(Number(projectId))
    projectNames.value.set(key, project?.name || 'Untitled Project')
    projectNames.value = new Map(projectNames.value)
  } catch {}
}

function applyBoardUpdate(board: any) {
  if (!board?.id) return
  const boardId = String(board.id)
  boardMetadata.value.set(boardId, extractBoardMetadata(board))
  boardMetadata.value = new Map(boardMetadata.value)
  ensureProjectName(board?.project_id ?? null)

  const nextName = (board.name || '').trim()
  if (nextName) {
    updateTabName(`board:${boardId}`, nextName)
  }
}

async function loadBoardMetadata(boardId: string) {
  try {
    const board = await getBoard(parseInt(boardId, 10))
    if (board) {
      applyBoardUpdate(board)
    }
  } catch (error) {
    console.error('Failed to load board metadata:', error)
  }
}

function getBoardMetadata(boardId: string) {
  return boardMetadata.value.get(boardId)
}

function getBoardPreviewItems(boardId: string) {
  return getBoardMetadata(boardId)?.preview_items || []
}

function getBoardPreviewColumns(boardId: string) {
  const items = getBoardPreviewItems(boardId)
  const columns: BoardPreviewItem[][] = [[], []]
  items.forEach((item, index) => {
    columns[index % columns.length].push(item)
  })
  return columns
}

function getBoardPreviewTileStyle(item: BoardPreviewItem) {
  const width = Math.max(item?.width || 1, 1)
  const height = Math.max(item?.height || 1, 1)
  return {
    aspectRatio: `${width} / ${height}`
  }
}

function isBoardPreviewVideo(fileFormat?: string | null) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat.toLowerCase())
}

function formatCount(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`
}

function formatChatTabSubtitle(chatId: string): string {
  const metadata = getChatMetadata(chatId)
  return metadata?.last_message || ''
}

function getChatProjectName(chatId: string): string {
  const metadata = getChatMetadata(chatId)
  if (metadata?.project_id == null) return ''
  return projectNames.value.get(String(metadata.project_id)) || ''
}

function getBoardProjectName(boardId: string): string {
  const metadata = getBoardMetadata(boardId)
  if (metadata?.project_id == null) return ''
  return projectNames.value.get(String(metadata.project_id)) || ''
}

function formatBoardTabDetail(boardId: string): string {
  const metadata = getBoardMetadata(boardId)
  const itemText = formatCount(metadata?.item_count || 0, 'item')
  const sectionCount = metadata?.section_count || 0
  return sectionCount > 1 ? `${itemText} · ${formatCount(sectionCount, 'section')}` : itemText
}

function getChatMetadata(chatId: string) {
  return chatMetadata.value.get(chatId)
}

const chatMetadataLoading = new Set<string>()
const chatMetadataLoaded = new Set<string>()

async function loadChatMetadata(chatId: string, force = false) {
  if (chatMetadataLoading.has(chatId)) return
  if (!force && chatMetadataLoaded.has(chatId)) return
  chatMetadataLoading.add(chatId)
  try {
    const res = await fetch(`/api/chats/${chatId}/preview`)
    if (!res.ok) return
    const preview = await res.json()
    if (preview) {
      chatMetadata.value.set(chatId, {
        thumbnail_media_id: preview.thumbnail_media_id || null,
        last_message: preview.last_message || '',
        project_id: preview.project_id ?? null
      })
      // Trigger reactivity
      chatMetadata.value = new Map(chatMetadata.value)
      ensureProjectName(preview.project_id ?? null)
    }
  } catch {
  } finally {
    chatMetadataLoading.delete(chatId)
    chatMetadataLoaded.add(chatId)
  }
}

function loadAllChatMetadata() {
  for (const tab of allTabs.value) {
    if (tab.type === 'chat' && !chatMetadata.value.has(tab.entityId)) {
      loadChatMetadata(tab.entityId)
    }
  }
}

function loadAllBoardMetadata() {
  for (const tab of allTabs.value) {
    if (tab.type === 'board' && !boardMetadata.value.has(tab.entityId)) {
      loadBoardMetadata(tab.entityId)
    }
  }
}

// ==================== Tab helpers ====================

function getTabIcon(tab: WorkspaceTab) {
  if (tab.type === 'tool') {
    const tool = allToolsMap.value.get(tab.entityId)
    return createTaskTypeIconComponent(tool?.task_type || 'text-to-image', 'currentColor')
  }
  if (tab.type === 'chat') {
    return h('svg', { class: 'w-3.5 h-3.5', fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '2', stroke: 'currentColor' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155' })
    ])
  }
  if (tab.type === 'board') {
    return h('svg', { class: 'w-3.5 h-3.5', viewBox: '0 0 20 20', fill: 'currentColor' }, [
      h('path', { d: 'M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z' })
    ])
  }
  if (tab.type === 'project') {
    return ArchiveBoxIcon
  }
  if (tab.type === 'editor') {
    return h('svg', { class: 'w-3.5 h-3.5 text-blue-500', xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 20 20', fill: 'currentColor' }, [
      h('path', { d: 'M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z' })
    ])
  }
  if (tab.type === 'lineage') {
    // Git-branch-like icon for lineage
    return h('svg', { class: 'w-3.5 h-3.5', fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '2', stroke: 'currentColor' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z' })
    ])
  }
  if (tab.type === 'flow') {
    return h('svg', { class: 'w-3.5 h-3.5', fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '2', stroke: 'currentColor' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z' })
    ])
  }
  return h('span')
}

function isTabActive(tab: WorkspaceTab): boolean {
  if (tab.type === 'tool') {
    if (route.name !== 'tool' || route.params.fullToolId !== tab.entityId) return false
    const routeProjectId = route.query.project_id ? Number(route.query.project_id) : null
    if ((tab.projectId || null) !== routeProjectId) return false
    return (tab.instanceId || null) === (route.query.instance ? String(route.query.instance) : null)
  }
  if (tab.type === 'chat') return route.name === 'chat' && String(route.params.id) === tab.entityId
  if (tab.type === 'board') return route.name === 'board-detail' && String(route.params.id) === tab.entityId
  if (tab.type === 'project') return String(route.name || '').startsWith('project-') && String(route.params.id) === tab.entityId
  if (tab.type === 'editor') return (route.name === 'edit-image' || route.name === 'edit-image-empty') && String(route.params.editorId) === tab.entityId
  if (tab.type === 'lineage') return route.name === 'lineage' && String(route.params.mediaId) === tab.entityId
  if (tab.type === 'flow') return route.name === 'flow' && String(route.params.id) === tab.entityId
  return false
}

function isTabGenerating(tab: WorkspaceTab): boolean {
  if (tab.type === 'tool') {
    return tab.feedScope ? isFeedScopeActive(tab.feedScope) : isToolGenerating(tab.entityId, tab.projectId ?? null)
  }
  if (tab.type === 'chat') return isChatGenerating(tab.entityId)
  return false
}

function navigateToTab(tab: WorkspaceTab) {
  if (tab.type === 'tool') {
    router.push(toolTabRoute(tab))
  }
  else if (tab.type === 'chat') router.push({ name: 'chat', params: { id: tab.entityId } })
  else if (tab.type === 'board') router.push({ name: 'board-detail', params: { id: tab.entityId } })
  else if (tab.type === 'project') router.push({ name: getLastProjectRoute(tab.entityId), params: { id: tab.entityId } })
  else if (tab.type === 'editor') {
    if (tab.editorMediaId) {
      router.push({ name: 'edit-image', params: { editorId: tab.entityId, mediaId: tab.editorMediaId } })
    } else {
      router.push({ name: 'edit-image-empty', params: { editorId: tab.entityId } })
    }
  }
  else if (tab.type === 'lineage') router.push({ name: 'lineage', params: { mediaId: tab.entityId } })
  else if (tab.type === 'flow') router.push({ name: 'flow', params: { id: tab.entityId } })

  if (props.isMobile) emit('close')
}

function closeTab(tabId: string) {
  const closingTab = allTabs.value.find(t => t.id === tabId)
  const isActive = closingTab && isTabActive(closingTab)
  if (isActive) {
    const next = findNextTab(new Set([tabId]))
    if (next) {
      navigateToTab(next)
    } else {
      router.push({ name: 'browse' })
    }
  }
  removeTab(tabId)
}

function showTabContextMenu(tab: WorkspaceTab, event: MouseEvent) {
  // Resolve project_id from metadata for boards/chats; tool instances carry
  // their own scope (used by "New Tab" to open a sibling in the same project)
  let projectId: number | null = null
  if (tab.type === 'board') {
    projectId = boardMetadata.value.get(tab.entityId)?.project_id ?? null
  } else if (tab.type === 'chat') {
    projectId = chatMetadata.value.get(tab.entityId)?.project_id ?? null
  } else if (tab.type === 'tool') {
    projectId = tab.projectId ?? null
  }
  tabsContextMenu.show({
    event,
    tabId: tab.id,
    tabType: tab.type,
    entityId: tab.entityId,
    displayName: tab.displayName,
    isPinned: tab.pinned,
    projectId
  })
}

// ==================== Navigation ====================

function handleNavClick(pageName: string) {
  router.push({ name: pageName })
  if (props.isMobile) emit('close')
}

function openSavedView(viewId: number) {
  router.push({ name: 'saved-view', params: { id: viewId } })
  if (props.isMobile) emit('close')
}

function isSavedViewActive(viewId: number) {
  return route.name === 'saved-view' && parseInt(route.params.id as string) === viewId
}

// ==================== Drag-drop ====================

function handleDragOver(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
}

// WKWebView does not populate modifier keys on DOM drag events (click events
// are fine — that's why shift-click in menus works). In Tauri, poll the OS
// shift state through the shift_key_down command during drag-over; browser
// builds use the drag event's own shiftKey.
const IS_TAURI = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
let lastShiftPoll = 0
function pollNativeShift() {
  const now = performance.now()
  if (now - lastShiftPoll < 100) return
  lastShiftPoll = now
  import('@tauri-apps/api/core')
    .then(({ invoke }) => invoke<boolean>('shift_key_down'))
    .then((down) => { dragAddModifier.value = down })
    .catch(() => {})
}

// Tool tabs get intent-aware cursor feedback: a naked pointer for the default
// replace ('move'), the OS copy badge (green +) only while shift = add.
// dragover fires continuously, so pressing/releasing shift mid-hover updates
// the cursor, ring color, and hint bar live (via the poll above in Tauri —
// the dropEffect set here uses the last polled value, ≤100ms stale).
function handleTabDragOver(tab: WorkspaceTab, e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    if (IS_TAURI) {
      pollNativeShift()
    } else {
      dragAddModifier.value = e.shiftKey
    }
    e.dataTransfer.dropEffect = tab.type === 'tool' && !dragAddModifier.value ? 'move' : 'copy'
  }
}

function handleTabDragEnter(tab: WorkspaceTab, e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    dragAddModifier.value = e.shiftKey
    const count = (tabDragCounters.value.get(tab.id) || 0) + 1
    tabDragCounters.value.set(tab.id, count)
    // A different tab under the pointer usually means the drag moved on —
    // but a diagonal pull toward the panel can clip a neighbor, so hide on
    // a grace timer (entering the panel cancels it) instead of instantly.
    if (flowDropTargets.value && flowDropTargets.value.tabId !== tab.id) scheduleFlowTargetsHide()
    if (tab.type === 'lineage') return // No drag-drop onto lineage tabs
    if (tab.type !== 'tool' || isToolCompatible(tab.entityId)) {
      dragHoverTabId.value = tab.id
    }
    if (tab.type === 'flow') void maybeShowFlowDropTargets(tab, e.currentTarget as HTMLElement)
  }
}

function handleTabDragLeave(tab: WorkspaceTab, e: DragEvent) {
  const count = (tabDragCounters.value.get(tab.id) || 0) - 1
  tabDragCounters.value.set(tab.id, Math.max(0, count))
  if (count <= 0 && dragHoverTabId.value === tab.id) {
    dragHoverTabId.value = null
    dragAddModifier.value = false
  }
  // Toward the panel or away entirely — the grace timer covers both; the
  // panel's dragenter cancels it.
  if (count <= 0 && flowDropTargets.value?.tabId === tab.id) scheduleFlowTargetsHide()
}

async function handleTabMediaDrop(tab: WorkspaceTab, e: DragEvent) {
  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  const assetIds = getDroppedAssetRefs(e.dataTransfer).map((item) => item.asset_id)
  if (mediaIds.length === 0) {
    // Not a media drop, let it bubble up for tab reordering
    return
  }

  // It's a media drop, handle it and stop propagation
  e.preventDefault()
  e.stopPropagation()
  dragHoverTabId.value = null
  tabDragCounters.value.delete(tab.id)
  resetFlowDropTargets()
  // e.shiftKey is unpopulated in WKWebView; the polled value covers Tauri.
  const add = e.shiftKey || dragAddModifier.value
  dragAddModifier.value = false

  // Lineage tabs don't accept media drops
  if (tab.type === 'lineage') return

  const mediaId = mediaIds[0]

  if (tab.type === 'tool') {
    const tool = allToolsMap.value.get(tab.entityId)
    if (!tool) return

    emit('media-dropped-on-tool', { fullToolId: tab.entityId, mediaId, instanceId: tab.instanceId })
    try {
      // Pass all dropped ids (multi-select drag) so they batch instead of only the first.
      // Target THIS row's instance, not just the tool+project.
      // Shift-drop adds to the tool's existing inputs; plain drop replaces them.
      await sendToTool(mediaIds.length > 1 ? mediaIds : mediaId, tool, undefined, tab.projectId ?? null, tab.instanceId ?? null, { add })
      if (props.isMobile) emit('close')
    } catch (error) {
      console.error('Failed to send media to tool:', error)
      addToast(error instanceof Error ? error.message : 'Failed to send assets to tool', 'warning')
    }
  } else if (tab.type === 'chat') {
    emit('media-dropped-on-chat', { chatId: parseInt(tab.entityId, 10), mediaId })
    setPendingMedia('chat', [mediaId], parseInt(tab.entityId, 10))
    router.push({ name: 'chat', params: { id: tab.entityId } })
    if (props.isMobile) emit('close')
  } else if (tab.type === 'flow') {
    // A flow shows an embedded chat (ChatView) scoped to that flow. Hand the
    // media to that chat so it lands in the flow's composer once the flow
    // page loads, then switch to it — mirroring the plain-chat case above.
    const flowChatId = await resolveFlowChatId(parseInt(tab.entityId, 10))
    if (flowChatId != null) setPendingMedia('chat', mediaIds, flowChatId)
    router.push({ name: 'flow', params: { id: tab.entityId } })
    if (props.isMobile) emit('close')
  } else if (tab.type === 'board') {
    try {
      await fetch(`/api/boards/${tab.entityId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(assetIds.length > 0 ? { asset_ids: assetIds } : { media_ids: mediaIds })
      })
      if (props.isMobile) emit('close')
    } catch (error) {
      console.error('Failed to add media to board:', error)
    }
  } else if (tab.type === 'editor') {
    updateEditorMedia(tab.id, String(mediaId))
    router.push({ name: 'edit-image', params: { editorId: tab.entityId, mediaId } })
  }
}

// ==================== Flow-tab drop targets ====================
// While media hovers a flow tab, a target panel pops out to its right —
// flush against the sidebar edge, vertically centered on the tab — with one
// clear target per destination: the flow's chat (the tab's default drop,
// unchanged) and each media input that accepts the dragged type. The drag
// gesture is: reach the tab, pull right onto a target, release. Flows with
// no compatible media inputs never show the panel.
//
// Finishing the pull must be forgiving: there is no gap between sidebar and
// panel, and every hide goes through a grace timer (never an instant reset)
// so briefly clipping a neighboring tab on the way over can't kill it.

const flowsApi = useFlowsApi()
const flowDropTargets = ref<{ tabId: string; flowId: number; left: number; top: number; zones: FlowMediaInputField[] } | null>(null)
const flowTargetHover = ref<string | null>(null)
let flowTargetsHideTimer: ReturnType<typeof setTimeout> | null = null
// Per-drag-session cache: schemas don't change mid-drag, but can between drags.
const dragFlowFieldsCache = new Map<number, Promise<FlowMediaInputField[]>>()

function flowMediaFieldsFor(flowId: number): Promise<FlowMediaInputField[]> {
  let p = dragFlowFieldsCache.get(flowId)
  if (!p) {
    p = flowsApi.getFlow(flowId).then(f => flowMediaInputFields(f.input_schema)).catch(() => [])
    dragFlowFieldsCache.set(flowId, p)
  }
  return p
}

async function maybeShowFlowDropTargets(tab: WorkspaceTab, el: HTMLElement) {
  const flowId = parseInt(tab.entityId, 10)
  if (!Number.isFinite(flowId)) return
  const fields = await flowMediaFieldsFor(flowId)
  // The fetch is async — the drag may have left this tab meanwhile.
  if ((tabDragCounters.value.get(tab.id) || 0) <= 0) return
  const zones = fields.filter(f => fieldAcceptsDraggedType(f.accept, draggedMediaType.value))
  if (!zones.length) return
  const rect = el.getBoundingClientRect()
  const approxHeight = (zones.length + 1) * 44 + 12
  flowDropTargets.value = {
    tabId: tab.id,
    flowId,
    // Overlap the sidebar edge by 2px — no dead strip to stall the pull.
    left: rect.right - 2,
    top: Math.max(8, Math.min(rect.top + rect.height / 2 - approxHeight / 2, window.innerHeight - approxHeight - 8)),
    zones,
  }
  cancelFlowTargetsHide()
}

function cancelFlowTargetsHide() {
  if (flowTargetsHideTimer) {
    clearTimeout(flowTargetsHideTimer)
    flowTargetsHideTimer = null
  }
}

function scheduleFlowTargetsHide() {
  cancelFlowTargetsHide()
  flowTargetsHideTimer = setTimeout(() => {
    flowDropTargets.value = null
    flowTargetHover.value = null
  }, 250)
}

function resetFlowDropTargets() {
  cancelFlowTargetsHide()
  flowDropTargets.value = null
  flowTargetHover.value = null
  dragFlowFieldsCache.clear()
}

// Hover tracking rides dragover (fires continuously on whatever is under the
// cursor) instead of per-row dragenter, which WKWebView delivers unreliably.
// One handler on the panel reads the row from the event target, so the lit
// target always matches where the drop would land.
function onFlowTargetsPanelDragOver(e: DragEvent) {
  cancelFlowTargetsHide()
  const row = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-zone]') : null
  flowTargetHover.value = row?.dataset.zone ?? null
}

function onFlowTargetsPanelDragLeave(e: DragEvent) {
  const next = e.relatedTarget
  if (next instanceof Node && (e.currentTarget as Node).contains(next)) return
  flowTargetHover.value = null
  scheduleFlowTargetsHide()
}

async function onFlowTargetDrop(zone: FlowMediaInputField | null, e: DragEvent) {
  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  const targets = flowDropTargets.value
  resetFlowDropTargets()
  // The chip's .stop keeps this drop away from handleTabMediaDrop — do its
  // hover cleanup here instead.
  dragHoverTabId.value = null
  if (targets) tabDragCounters.value.delete(targets.tabId)
  if (!targets || mediaIds.length === 0) return

  if (!zone) {
    // Same routing as dropping on the tab itself.
    const flowChatId = await resolveFlowChatId(targets.flowId)
    if (flowChatId != null) setPendingMedia('chat', mediaIds, flowChatId)
    router.push({ name: 'flow', params: { id: String(targets.flowId) } })
    if (props.isMobile) emit('close')
    return
  }

  try {
    const flow = await flowsApi.getFlow(targets.flowId)
    const inputs = { ...(flow.inputs || {}) }
    if (zone.multi) {
      const arr = Array.isArray(inputs[zone.name]) ? [...inputs[zone.name]] : []
      for (const id of mediaIds) if (!arr.includes(id)) arr.push(id)
      inputs[zone.name] = arr
    } else {
      inputs[zone.name] = mediaIds[0]
    }
    await flowsApi.updateFlow(targets.flowId, { inputs })
    router.push({ name: 'flow', params: { id: String(targets.flowId) } })
    if (props.isMobile) emit('close')
  } catch (error) {
    console.error('Failed to set flow input:', error)
    addToast('Failed to set flow input', 'warning')
  }
}

// New Board drag-drop (on the Boards link)
function handleNewBoardDragEnter(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    newBoardDragCounter.value++
    dragHoverNewBoard.value = true
  }
}

function handleNewBoardDragLeave(e: DragEvent) {
  newBoardDragCounter.value--
  if (newBoardDragCounter.value <= 0) {
    dragHoverNewBoard.value = false
    newBoardDragCounter.value = 0
  }
}

async function handleNewBoardDrop(e: DragEvent) {
  e.preventDefault()
  dragHoverNewBoard.value = false
  newBoardDragCounter.value = 0

  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  const assetIds = getDroppedAssetRefs(e.dataTransfer).map((item) => item.asset_id)
  if (mediaIds.length > 0) {
    try {
      const newBoard = await apiCreateBoard('')
      await fetch(`/api/boards/${newBoard.id}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(assetIds.length > 0 ? { asset_ids: assetIds } : { media_ids: mediaIds })
      })
      router.push({ name: 'board-detail', params: { id: newBoard.id } })
      if (props.isMobile) emit('close')
    } catch (error) {
      console.error('Failed to create board with media:', error)
    }
  }
}

// New Chat drag-drop (on the Chats link)
function handleNewChatDragEnter(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    newChatDragCounter.value++
    dragHoverNewChat.value = true
  }
}

function handleNewChatDragLeave(e: DragEvent) {
  newChatDragCounter.value--
  if (newChatDragCounter.value <= 0) {
    dragHoverNewChat.value = false
    newChatDragCounter.value = 0
  }
}

async function handleNewChatDrop(e: DragEvent) {
  e.preventDefault()
  dragHoverNewChat.value = false
  newChatDragCounter.value = 0

  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  if (mediaIds.length > 0) {
    const mediaId = mediaIds[0]
    try {
      const response = await fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      if (!response.ok) throw new Error('Failed to create chat')
      const newChat = await response.json()
      setPendingMedia('chat', [mediaId], newChat.id)
      router.push({ name: 'chat', params: { id: newChat.id } })
      if (props.isMobile) emit('close')
    } catch (error) {
      console.error('Failed to create chat with media:', error)
    }
  }
}

// Resolve (creating if needed) the chat scoped to a flow, mirroring
// FlowView.ensureFlowChat so dropped media is attached to the same chat the
// flow page will display.
async function resolveFlowChatId(flowId: number): Promise<number | null> {
  try {
    const listResp = await fetch(`/api/chats?flow_id=${flowId}&page=1&page_size=1`)
    if (listResp.ok) {
      const list = await listResp.json()
      const existing = list?.items?.[0]?.id
      if (existing != null) return Number(existing)
    }
    const createResp = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flow_id: flowId })
    })
    if (!createResp.ok) throw new Error('Failed to create flow chat')
    const created = await createResp.json()
    return created?.id != null ? Number(created.id) : null
  } catch (error) {
    console.error('Failed to resolve flow chat:', error)
    return null
  }
}

// New Flow drag-drop (on the Flows link) — create a flow and attach the media
// to its chat, matching the Chats link behavior.
function handleNewFlowDragEnter(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    newFlowDragCounter.value++
    dragHoverNewFlow.value = true
  }
}

function handleNewFlowDragLeave(e: DragEvent) {
  newFlowDragCounter.value--
  if (newFlowDragCounter.value <= 0) {
    dragHoverNewFlow.value = false
    newFlowDragCounter.value = 0
  }
}

async function handleNewFlowDrop(e: DragEvent) {
  e.preventDefault()
  dragHoverNewFlow.value = false
  newFlowDragCounter.value = 0

  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  if (mediaIds.length > 0) {
    try {
      const response = await fetch('/api/flows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      if (!response.ok) throw new Error('Failed to create flow')
      const flow = await response.json()
      const flowChatId = await resolveFlowChatId(Number(flow.id))
      if (flowChatId != null) setPendingMedia('chat', mediaIds, flowChatId)
      router.push({ name: 'flow', params: { id: String(flow.id) } })
      if (props.isMobile) emit('close')
    } catch (error) {
      console.error('Failed to create flow with media:', error)
    }
  }
}

// Stimma Home drag-drop (attach media to home chat input)
function handleStimmaHomeDragEnter(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    stimmaHomeDragCounter.value++
    dragHoverStimmaHome.value = true
  }
}

function handleStimmaHomeDragLeave(e: DragEvent) {
  stimmaHomeDragCounter.value--
  if (stimmaHomeDragCounter.value <= 0) {
    dragHoverStimmaHome.value = false
    stimmaHomeDragCounter.value = 0
  }
}

function handleStimmaHomeDrop(e: DragEvent) {
  e.preventDefault()
  dragHoverStimmaHome.value = false
  stimmaHomeDragCounter.value = 0

  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  if (mediaIds.length > 0) {
    setPendingMedia('home', [mediaIds[0]])
    router.push({ name: 'home' })
    if (props.isMobile) emit('close')
  }
}

// Create new board (from plus button)
async function createNewBoard() {
  try {
    const newBoard = await apiCreateBoard('')
    router.push({ name: 'board-detail', params: { id: newBoard.id } })
    if (props.isMobile) emit('close')
  } catch (error) {
    console.error('Failed to create board:', error)
  }
}

// Create new chat (from plus button)
async function createNewChat() {
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    if (!response.ok) throw new Error('Failed to create chat')
    const newChat = await response.json()
    router.push({ name: 'chat', params: { id: newChat.id } })
    if (props.isMobile) emit('close')
  } catch (error) {
    console.error('Failed to create chat:', error)
  }
}

async function createNewFlow() {
  try {
    const response = await fetch('/api/flows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    if (!response.ok) throw new Error('Failed to create flow')
    const flow = await response.json()
    router.push({ name: 'flow', params: { id: String(flow.id) } })
    if (props.isMobile) emit('close')
  } catch (err) {
    console.error('Failed to create flow:', err)
  }
}

async function createNewProject() {
  try {
    const newProject = await apiCreateProject('', '')
    router.push({ name: 'project-overview', params: { id: newProject.id }, query: { rename: '1' } })
    if (props.isMobile) emit('close')
  } catch (error) {
    console.error('Failed to create project:', error)
  }
}

// ==================== Tab reorder ====================

function handleTabReorderDragStart(index: number, group: 'pinned' | 'open', e: DragEvent) {
  tabReorderDragSource.value = { index, group }
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', `tab-reorder:${group}:${index}`)
  }
}

function handleTabReorderDragOver(index: number, group: 'pinned' | 'open', e: DragEvent) {
  if (!tabReorderDragSource.value) return
  if (tabReorderDragSource.value.group !== group) return
  e.preventDefault()
  tabReorderDropTarget.value = { index, group }
}

function handleTabReorderDrop(index: number, group: 'pinned' | 'open', e: DragEvent) {
  e.preventDefault()
  if (!tabReorderDragSource.value) return
  if (tabReorderDragSource.value.group !== group) return

  const fromIndex = tabReorderDragSource.value.index
  if (fromIndex !== index) {
    moveTab(fromIndex, index, group)
  }
  handleTabReorderDragEnd()
}

function handleTabReorderDragEnd() {
  tabReorderDragSource.value = null
  tabReorderDropTarget.value = null
}

// ==================== Inline rename ====================

function handleRenameFromContextMenu(tabType: 'board' | 'chat' | 'flow' | 'project', entityId: string, currentName: string) {
  const tabId = `${tabType}:${entityId}`
  editingItem.value = { tabId, tabType, entityId }
  editingName.value = currentName
  nextTick(() => {
    const input = document.querySelector('input[autofocus]') as HTMLInputElement | null
    if (input) {
      input.focus()
      input.select()
    }
  })
}

function handleRenameTabFromContextMenu(tabId: string) {
  const tab = allTabs.value.find(t => t.id === tabId)
  if (tab) startInlineRename(tab)
}

function startInlineRename(tab: WorkspaceTab) {
  if (tab.type !== 'chat' && tab.type !== 'board' && tab.type !== 'flow' && tab.type !== 'tool' && tab.type !== 'project') return
  editingItem.value = { tabId: tab.id, tabType: tab.type, entityId: tab.entityId }
  // Tool instances: edit the custom name (window title), starting empty when
  // the tab still shows the plain tool name.
  editingName.value = tab.type === 'tool' ? (tab.customName || '') : (tab.displayName || '')
  nextTick(() => {
    const input = document.querySelector('input[autofocus]') as HTMLInputElement | null
    if (input) {
      input.focus()
      input.select()
    }
  })
}

async function saveRename() {
  if (!editingItem.value) return
  const { tabType, entityId, tabId } = editingItem.value
  const newName = editingName.value.trim()

  // Tool instances rename locally (window title); clearing the name reverts
  // to the tool name. No backend entity to PATCH.
  if (tabType === 'tool') {
    updateTabCustomName(tabId, newName || null)
    editingItem.value = null
    editingName.value = ''
    return
  }

  if (!newName) {
    cancelRename()
    return
  }

  try {
    if (tabType === 'board') {
      await updateBoard(parseInt(entityId, 10), { name: newName })
    } else if (tabType === 'project') {
      await updateProject(entityId, { name: newName })
    } else if (tabType === 'chat') {
      await fetch(`/api/chats/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
    } else if (tabType === 'flow') {
      await fetch(`/api/flows/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
    }
    updateTabName(tabId, newName)
  } catch (err) {
    console.error(`Failed to rename ${tabType}:`, err)
  }

  editingItem.value = null
  editingName.value = ''
}

function cancelRename() {
  editingItem.value = null
  editingName.value = ''
}

function handleRenameKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') { event.preventDefault(); saveRename() }
  else if (event.key === 'Escape') { event.preventDefault(); cancelRename() }
}

// ==================== Resize ====================

function startResize(event: MouseEvent) {
  event.preventDefault()
  isResizing.value = true
  resizeStartX.value = event.clientX
  resizeStartWidth.value = sidebarWidth.value
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  document.addEventListener('mousemove', handleResizeMove)
  document.addEventListener('mouseup', stopResize)
}

function handleResizeMove(event: MouseEvent) {
  if (!isResizing.value) return
  const deltaX = event.clientX - resizeStartX.value
  sidebarWidth.value = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, resizeStartWidth.value + deltaX))
}

function stopResize() {
  isResizing.value = false
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  document.removeEventListener('mousemove', handleResizeMove)
  document.removeEventListener('mouseup', stopResize)
}

// ==================== Data loading ====================

async function loadSavedViews() {
  loadingState.value.savedViews.loading = true
  try {
    savedViews.value = await getSavedViews()
    loadingState.value.savedViews.error = false
  } catch (error) {
    console.error('Failed to load saved views:', error)
    loadingState.value.savedViews.error = true
  } finally {
    loadingState.value.savedViews.loading = false
  }
}

// Seed orphaned pins (provider removed from config, dropped from the live tool
// list) into the lookup maps using the persisted pin metadata, so they still
// show their provider identity and read as "not configured". Never overrides a
// live entry.
function mergePinFallbacks(toolsMap: Map<string, any>, availabilityMap: Map<string, string>) {
  for (const pin of pinnedTools.value as any[]) {
    if (!toolsMap.has(pin.full_tool_id)) {
      toolsMap.set(pin.full_tool_id, {
        full_tool_id: pin.full_tool_id,
        provider_id: pin.provider_id,
        provider_name: pin.provider_name,
        task_types: pin.task_types || [],
        availability: 'unconfigured',
      })
    }
    if (!availabilityMap.has(pin.full_tool_id)) {
      availabilityMap.set(pin.full_tool_id, 'unconfigured')
    }
  }
}

async function loadPinnedTools() {
  loadingState.value.tools.loading = true
  try {
    pinnedTools.value = await listPinnedTools()
    reconcileToolPins(pinnedTools.value)
    // If the live list already loaded, fold any newly-known orphaned pins in.
    if (liveToolsLoaded.value) {
      const toolsMap = new Map(allToolsMap.value)
      const availabilityMap = new Map(toolAvailabilityMap.value)
      mergePinFallbacks(toolsMap, availabilityMap)
      allToolsMap.value = toolsMap
      toolAvailabilityMap.value = availabilityMap
    }
    loadingState.value.tools.error = false
  } catch (error) {
    console.error('Failed to load pinned tools:', error)
    loadingState.value.tools.error = true
  } finally {
    loadingState.value.tools.loading = false
  }
}

async function loadToolAvailability() {
  try {
    const { tools } = await fetchProvidersAndTools()
    const availabilityMap = new Map<string, string>()
    const toolsMap = new Map<string, any>()
    for (const tool of tools) {
      availabilityMap.set(tool.full_tool_id, tool.availability || 'available')
      toolsMap.set(tool.full_tool_id, tool)
    }
    mergePinFallbacks(toolsMap, availabilityMap)
    toolAvailabilityMap.value = availabilityMap
    allToolsMap.value = toolsMap
    liveToolsLoaded.value = true
  } catch (error) {
    console.error('Failed to load tool availability:', error)
  }
}

let unsubscribeFromProviderChanges: (() => void) | null = null

// ==================== WebSocket listeners ====================

// Saved views
on('saved_view_created', (data) => {
  if (!savedViews.value.find(sv => sv.id === data.saved_view.id)) {
    savedViews.value.push(data.saved_view)
    savedViews.value.sort((a, b) => a.display_order - b.display_order)
  }
})

on('saved_view_updated', (data) => {
  const index = savedViews.value.findIndex(sv => sv.id === data.saved_view.id)
  if (index !== -1) {
    savedViews.value[index] = data.saved_view
    savedViews.value.sort((a, b) => a.display_order - b.display_order)
  }
})

on('saved_view_deleted', (data) => {
  savedViews.value = savedViews.value.filter(sv => sv.id !== data.view_id)
})

on('saved_views_reordered', (data) => {
  savedViews.value = data.saved_views
})

// Tool pin events
on('tool_pinned', () => loadPinnedTools())
on('tool_unpinned', (data) => {
  pinnedTools.value = pinnedTools.value.filter(t => t.full_tool_id !== data.full_tool_id)
  reconcileToolPins(pinnedTools.value)
})

// Chat events - update tab names, remove tabs on deletion
on('chat_updated', (data) => {
  if (data.chat?.name) {
    updateTabName(`chat:${data.chat.id}`, data.chat.name)
  }
})

on('chat_deleted', (data) => {
  const tabId = `chat:${data.chat_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]))
    if (next) navigateToTab(next)
    else router.push({ name: 'browse' })
  }
  removeTabByEntity('chat', String(data.chat_id))
  removeRecentEntity('chat', String(data.chat_id))
})

// Flow events - update tab names, remove tabs on deletion
on('flow_updated', (data) => {
  const flow = data.flow
  if (flow?.id && flow.name) {
    updateTabName(`flow:${flow.id}`, flow.name)
  }
})

on('flow_deleted', (data) => {
  const tabId = `flow:${data.flow_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]))
    if (next) navigateToTab(next)
    else router.push({ name: 'flows' })
  }
  removeTabByEntity('flow', String(data.flow_id))
  removeRecentEntity('flow', String(data.flow_id))
})

// Board events - open new boards as tabs, update names, remove on deletion
on('board_created', (data) => {
  if (data.board) {
    addTab('board', String(data.board.id), data.board.name)
    applyBoardUpdate(data.board)
  }
})

on('board_updated', (data) => {
  if (data.board) {
    applyBoardUpdate(data.board)
  }
})

on('board_items_changed', (data) => {
  if (data.board) {
    applyBoardUpdate(data.board)
  }
})

on('board_deleted', (data) => {
  const tabId = `board:${data.board_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]))
    if (next) navigateToTab(next)
    else router.push({ name: 'browse' })
  }
  boardMetadata.value.delete(String(data.board_id))
  boardMetadata.value = new Map(boardMetadata.value)
  removeTabByEntity('board', String(data.board_id))
  removeRecentEntity('board', String(data.board_id))
})

// Chat generation tracking
on('project_updated', (data) => {
  const project = data.project
  if (!project?.id) return
  const id = String(project.id)
  const name = project.name || 'Untitled Project'
  projectNames.value.set(id, name)
  projectNames.value = new Map(projectNames.value)
  // Update tab displayName for project tabs and projectName on tool/chat/board tabs
  for (const tab of allTabs.value) {
    if (tab.type === 'project' && tab.entityId === id) {
      updateTabName(tab.id, project.name || '')
    }
    if (tab.projectId === project.id) {
      tab.projectName = name
    }
  }
})

// Spinner state itself lives in useAgentActivity; this only refreshes
// chat preview data (new images/messages may exist).
on('agent_stopped', (data) => {
  loadChatMetadata(String(data.chat_id), true)
})

// ==================== Route watcher: auto-create tabs ====================

watch(
  // Include project_id + instance in the source: switching between two
  // instances of the same tool is a query-only change (name/params identical).
  () => ({ name: route.name, params: { ...route.params }, projectQ: route.query.project_id, instanceQ: route.query.instance }),
  (current) => {
    const name = current.name as string
    const params = current.params

    // Track library routes for "close last tab" navigation
    if (['browse', 'trash', 'saved-view', 'boards', 'chats', 'flows', 'all-tools', 'projects'].includes(name) || name?.startsWith('project-')) {
      setLastLibraryRoute(route.fullPath)
    }

    // Auto-create workspace tabs
    if (name === 'tool' && params.fullToolId) {
      const fullToolId = params.fullToolId as string
      const tool = allToolsMap.value.get(fullToolId)
      const toolDisplayName = tool?.name || fullToolId.split(':').pop() || fullToolId
      const rawProjectId = route.query.project_id
      const projectId = rawProjectId ? parseInt(String(Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId), 10) : undefined
      // The router guard guarantees ?instance on tool routes.
      const instanceId = route.query.instance ? String(route.query.instance) : undefined
      if (projectId && Number.isFinite(projectId)) {
        // Project-scoped tool tab — look up project name
        const tab = addTab('tool', fullToolId, toolDisplayName, projectId, undefined, instanceId)
        markTabActivated(tab.id)
        if (!tab.projectName) {
          getProject(projectId).then(project => {
            if (project) {
              addTab('tool', fullToolId, toolDisplayName, projectId, project.name || 'Untitled Project', instanceId)
            }
          }).catch(() => {})
        }
      } else {
        const tab = addTab('tool', fullToolId, toolDisplayName, undefined, undefined, instanceId)
        markTabActivated(tab.id)
      }
    } else if (name?.startsWith('project-') && params.id) {
      const projectId = String(params.id)
      const tab = addTab('project', projectId)
      getProject(parseInt(projectId, 10)).then(project => {
        if (project) {
          updateTabName(tab.id, project.name || '')
          projectNames.value.set(projectId, project.name || 'Untitled Project')
          projectNames.value = new Map(projectNames.value)
        }
      }).catch(() => {})
    } else if (name === 'chat' && params.id) {
      const chatId = String(params.id)
      const tab = addTab('chat', chatId)
      // Fetch real name if we don't have one yet
      if (!tab.displayName || tab.displayName === chatId) {
        fetch(`/api/chats/${chatId}`).then(r => r.ok ? r.json() : null).then(chat => {
          if (chat) {
            updateTabName(tab.id, chat.name || '')
            chatMetadata.value.set(chatId, {
              thumbnail_media_id: getChatMetadata(chatId)?.thumbnail_media_id || null,
              last_message: getChatMetadata(chatId)?.last_message || '',
              project_id: chat.project_id ?? null
            })
            chatMetadata.value = new Map(chatMetadata.value)
            ensureProjectName(chat.project_id ?? null)
          }
        }).catch(() => {})
      }
      // Load preview metadata (thumbnail + last message)
      loadChatMetadata(chatId)
    } else if (name === 'board-detail' && params.id) {
      const colId = String(params.id)
      const tab = addTab('board', colId)
      // Fetch board data for name and metadata
      if (!tab.displayName || tab.displayName === colId || !getBoardMetadata(colId)) {
        getBoard(parseInt(colId, 10)).then(col => {
          if (col) {
            updateTabName(tab.id, col.name || '')
            boardMetadata.value.set(colId, {
              cover_media_id: null,
              item_count: col.asset_count || 0,
              section_count: col.sections?.length || 0,
              project_id: col.project_id ?? null,
              preview_items: (col.sections || [])
                .flatMap((section: any) => section.items || [])
                .slice(0, 4)
            })
            boardMetadata.value = new Map(boardMetadata.value)
            ensureProjectName(col.project_id ?? null)
          }
        }).catch(() => {})
      }
    } else if ((name === 'edit-image' || name === 'edit-image-empty') && params.editorId) {
      addEditorTab(String(params.editorId), params.mediaId ? String(params.mediaId) : undefined)
    } else if (name === 'lineage' && params.mediaId) {
      addTab('lineage', String(params.mediaId), 'Lineage')
    } else if (name === 'flow' && params.id) {
      const flowId = String(params.id)
      const tab = addTab('flow', flowId)
      if (!tab.displayName || tab.displayName === flowId) {
        fetch(`/api/flows/${flowId}`).then(r => r.ok ? r.json() : null).then(flow => {
          if (flow) updateTabName(tab.id, flow.name || '')
        }).catch(() => {})
      }
    }
  },
  { immediate: true }
)

// ==================== Lifecycle ====================

async function handleProfileChanged() {
  console.log('[NavigationSidebar] Profile changed, reloading data')
  await fetchProvidersAndTools(true)
  await Promise.all([loadPinnedTools(), loadSavedViews()])
}

onMounted(() => {
  loadSavedViews()
  loadPinnedTools()
  loadToolAvailability()

  unsubscribeFromProviderChanges = subscribeToProviderChanges(() => {
    loadToolAvailability()
  })

  window.addEventListener('profile-changed', handleProfileChanged)

  // A canceled drag (Esc, released elsewhere) fires neither drop nor a
  // reliable dragleave on the tab — dragend at the window still does. The
  // drop listener is bubble-phase on purpose: the flyout's own drop handler
  // stops propagation, so only drops landing elsewhere reset it here (a
  // capture listener would clear the flyout before its handler could read it).
  window.addEventListener('dragend', resetFlowDropTargets, true)
  window.addEventListener('drop', resetFlowDropTargets)
})

// Load chat/board metadata whenever tabs change (covers initial load, new tabs, profile switch)
watch(allTabs, () => loadAllChatMetadata(), { immediate: true })
watch(allTabs, () => loadAllBoardMetadata(), { immediate: true })

onUnmounted(() => {
  if (unsubscribeFromProviderChanges) {
    unsubscribeFromProviderChanges()
    unsubscribeFromProviderChanges = null
  }
  window.removeEventListener('profile-changed', handleProfileChanged)
  window.removeEventListener('dragend', resetFlowDropTargets, true)
  window.removeEventListener('drop', resetFlowDropTargets)
  document.removeEventListener('mousemove', handleResizeMove)
  document.removeEventListener('mouseup', stopResize)
})

// Persist sidebar width
watch(sidebarWidth, (newWidth) => {
  localStorage.setItem(SIDEBAR_WIDTH_KEY, String(newWidth))
  document.documentElement.style.setProperty('--sidebar-width', `${newWidth}px`)
}, { immediate: true })

// Reload sidebar data when WS connects or reconnects
watch(wsConnected, (connected, wasConnected) => {
  if (connected && !wasConnected) {
    console.log('[Sidebar] WebSocket connected, reloading sidebar data')
    loadSavedViews()
    loadPinnedTools()
    loadToolAvailability()
  }
})
</script>

<style scoped>
/* Logo disconnected animation - pendulum swing (matches Tauri loading screen) */
.logo-disconnected {
  animation: logo-pendulum 2.4s ease-in-out infinite;
}

@keyframes logo-pendulum {
  0%, 100% { transform: rotate(-175deg); }
  50% { transform: rotate(175deg); }
}

/* Fade transition for backdrop */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Slide transition for mobile sidebar */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(-100%);
}

</style>
