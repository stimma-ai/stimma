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

    <!-- Sidebar. Phones: a drawer that stays mounted as the first cell of
         App.vue's compact track (drawer + app side by side); the track rides
         --drawer-x, so the drawer and the pushed app move as one element. -->
    <Transition :name="isMobile ? '' : ''">
      <div
        v-if="true"
        class="navigation-sidebar group/sidebar h-screen bg-surface border-r border-edge-subtle flex flex-col flex-shrink-0"
        :class="isMobile ? 'compact-drawer relative w-[276px] !h-full pt-safe' : focusCollapsed ? ['absolute inset-y-0 left-0 z-modal', peeking ? 'is-peeking translate-x-0 shadow-lg' : '-translate-x-full invisible pointer-events-none'] : 'relative'"
        :style="!isMobile ? { width: `${sidebarWidth}px` } : undefined"
        :aria-hidden="(isMobile && !isOpen) || (focusCollapsed && !peeking) ? 'true' : undefined"
        :inert="(isMobile && !isOpen) || (focusCollapsed && !peeking) ? true : undefined"
      >
        <!-- Draggable region + fade overlay for traffic light area -->
        <div v-if="isDesktopMac" class="absolute top-0 left-0 right-3 h-9 z-10 pointer-events-none">
          <div class="absolute top-0 left-0 right-0 h-7 bg-surface" data-window-drag-region style="pointer-events: auto;" />
          <div class="absolute bottom-0 left-0 right-0 h-2 bg-gradient-to-b from-surface to-transparent" />
        </div>

        <!-- Nav Menu - only show when we have data -->
        <!-- Wide: the library links stay put and only the projects and tabs
             below them scroll. The phone drawer is short, so there the whole
             nav scrolls as one list. -->
        <nav v-if="hasLoadedData" ref="navEl" @scroll.passive="updateNavEdge" class="flex min-h-0 flex-1 flex-col" :class="isMobile ? ['gap-0.5 overflow-y-auto p-3 custom-scrollbar coarse:gap-0', isDesktopMac ? 'pt-10' : ''] : 'overflow-hidden'">

          <!-- ==================== ZONE 1: Library Links ==================== -->
          <!-- The bottom hairline shows only while the list below is scrolled
               under it. On a window too short for both zones this one gives
               way and scrolls too, so the tabs always keep some room. -->
          <div data-nav-zone :class="isMobile ? 'contents' : ['flex min-h-0 shrink flex-col gap-0.5 overflow-y-auto border-b px-3 pb-1 transition-colors coarse:gap-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden', isDesktopMac ? 'pt-10' : 'pt-3', tabsScrolledAbove ? 'border-edge-subtle' : 'border-transparent']">

          <!-- Everything: the brand row goes home and takes drops. Inside a
               project the sidebar drills in: a way back, then the project as
               the header (its menu renames, opens settings, and switches). -->
          <button
            v-if="activeProjectId == null"
            @click="handleNavClick('home')"
            @dragover="handleDragOver"
            @dragenter="handleStimmaHomeDragEnter"
            @dragleave="handleStimmaHomeDragLeave"
            @drop="handleStimmaHomeDrop"
            class="mb-1.5 flex w-full items-center gap-2 rounded border-none bg-transparent px-3 py-1.5 text-left text-sm font-medium text-content-secondary no-underline transition-all cursor-pointer whitespace-nowrap hover:bg-overlay-subtle hover:text-content [&>:first-child]:mx-1"
            :class="dragHoverStimmaHome ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''"
            title="Stimma (drag media here to attach)"
          >
            <img src="/logo.svg" class="w-icon-nav h-icon-nav flex-shrink-0" :class="{ 'logo-disconnected': !wsConnected }" alt="" />
            <span class="font-brand lowercase tracking-[0.12em]">stimma</span>
          </button>
          <template v-else>
            <button
              type="button"
              aria-label="Back to everything"
              class="mb-0.5 flex w-full items-center gap-2 rounded px-3 py-1.5 text-left text-xs text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content coarse:min-h-11 coarse:text-sm [&>:first-child]:mx-1"
              :title="busyElsewhere ? 'Back to everything (work is running elsewhere)' : undefined"
              @click="leaveProject"
            >
              <ChevronLeftIcon class="h-icon-nav w-icon-nav flex-shrink-0" />
              <span>Back to everything</span>
              <Spinner v-if="busyElsewhere" size="sm" hue="border-t-blue-500" class="ml-auto" />
            </button>
            <WorkingContextPicker v-slot="{ toggle, open, openForDrop }" ref="projectPicker" @selected="props.isMobile && emit('close')">
              <!-- Holding dragged media here opens the picker so its rows can take the drop. -->
              <button
                ref="projectHeader"
                type="button"
                aria-label="Working context"
                aria-haspopup="dialog"
                :aria-expanded="open"
                class="mb-1.5 flex w-full items-start gap-2 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11"
                :class="open ? 'bg-overlay-subtle' : ''"
                @click="toggle($event.currentTarget)"
                @dragenter="projectHeaderDrag.onDragEnter"
                @dragover="projectHeaderDrag.onDragOver"
                @dragleave="projectHeaderDrag.onDragLeave"
                @drop="projectHeaderDrag.onDrop"
              ><span class="min-w-0 flex-1 break-words font-brand text-base font-semibold leading-snug text-content">{{ activeProject?.name || 'Untitled project' }}</span><ChevronUpDownIcon class="mt-1.5 h-icon-inline w-icon-inline shrink-0 text-content-muted" /></button>
            </WorkingContextPicker>
          </template>

          <button @click="handleNavClick('home')" @dragover="handleDragOver" @dragenter="handleStimmaHomeDragEnter" @dragleave="handleStimmaHomeDragLeave" @drop="handleStimmaHomeDrop" class="flex w-full items-center gap-2 rounded px-3 py-1.5 text-sm text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content coarse:min-h-11 [&>:first-child]:mx-1" :class="activeTab === 'home' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : ''"><HomeIcon class="h-icon-nav w-icon-nav flex-shrink-0" />Home</button>

          <div class="h-3.5 flex-shrink-0 coarse:h-2" aria-hidden="true"></div>

          <!-- All Assets, then the saved views flush beneath it. Inside Assets
               (the browser or any saved view) every view shows; elsewhere only
               the pinned ones do. Pin from the row or its right-click menu. -->
          <button
            @click="handleNavClick('browse')"
            class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
            :class="activeTab === 'browse' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : ''"
          >
            <PhotoIcon class="w-icon-nav h-icon-nav flex-shrink-0" />
            <span>Assets</span>
          </button>

          <TransitionGroup name="flow-expand">
            <div
              v-for="savedView in sidebarSavedViews"
              :key="savedView.id"
              class="motion-reduce:!transition-none"
              data-testid="sidebar-saved-view"
            >
              <div class="min-h-0 overflow-hidden">
                <div class="group relative">
                  <button
                    @click="openSavedView(savedView.id)"
                    @contextmenu.prevent.stop="openSavedViewMenu(savedView, $event)"
                    class="flex items-center gap-2 px-3 py-1.5 pr-8 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 coarse:pr-12 [&>:first-child]:mx-1"
                    :class="isSavedViewActive(savedView.id) ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : ''"
                    :title="displaySavedViewName(savedView.name)"
                  >
                    <component :is="savedViewIcon(savedView)" class="w-icon-nav h-icon-nav flex-shrink-0" />
                    <span class="truncate text-sm">{{ displaySavedViewName(savedView.name) }}</span>
                  </button>
                  <!-- Inside Assets a pinned view shows its pin, so you can see which
                       views stay when you leave; otherwise the pin appears on hover. -->
                  <Tooltip :text="savedView.pinned ? 'Unpin' : 'Pin'" class="absolute right-1.5 top-1/2 -translate-y-1/2 transition-opacity" :class="savedView.pinned && inAssets ? 'opacity-70 group-hover:opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100 coarse:opacity-70'">
                    <button
                      type="button"
                      data-testid="saved-view-pin"
                      class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light coarse:h-11 coarse:w-11"
                      :aria-label="savedView.pinned ? 'Unpin' : 'Pin'"
                      :aria-pressed="!!savedView.pinned"
                      @click.stop="toggleSavedViewPin(savedView)"
                    >
                      <svg class="w-icon-inline h-icon-inline" viewBox="0 0 16 16" :fill="savedView.pinned ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.25" aria-hidden="true">
                        <path :d="PIN_PATH" />
                      </svg>
                    </button>
                  </Tooltip>
                </div>
              </div>
            </div>
          </TransitionGroup>
          <ActionMenu v-if="savedViewMenu" :x="savedViewMenu.x" :y="savedViewMenu.y" :actions="savedViewMenuActions" @close="savedViewMenu = null" />

          <!-- Collections landing link (with drag-drop to create new) -->
          <div class="group relative">
            <button
              @click="handleNavClick('collections')"
              @dragover="handleDragOver"
              @dragenter="handleNewCollectionDragEnter"
              @dragleave="handleNewCollectionDragLeave"
              @drop="handleNewCollectionDrop"
              class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
              :class="[
                activeTab === 'collections' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : '',
                dragHoverNewCollection ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Collections (drag media here to create new)"
            >
              <Squares2X2Icon class="w-icon-nav h-icon-nav flex-shrink-0" />
              <span>Collections</span>
            </button>
            <!-- Create new collection button -->
            <Tooltip text="Create new collection" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewCollection"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <PlusIcon class="w-icon-inline h-icon-inline" />
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
              class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
              :class="[
                activeTab === 'chats' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : '',
                dragHoverNewChat ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Chats (drag media here to create new)"
            >
              <ChatBubbleLeftRightIcon class="w-icon-nav h-icon-nav flex-shrink-0" />
              <span>Chats</span>
            </button>
            <!-- Create new chat button -->
            <Tooltip text="Create new chat" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewChat"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <PlusIcon class="w-icon-inline h-icon-inline" />
              </button>
            </Tooltip>
          </div>

          <!-- Flows landing link -->
          <div v-if="flowsEnabled" class="group relative">
            <button
              @click="handleNavClick('flows')"
              @dragover="handleDragOver"
              @dragenter="handleNewFlowDragEnter"
              @dragleave="handleNewFlowDragLeave"
              @drop="handleNewFlowDrop"
              class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
              :class="[
                activeTab === 'flows' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : '',
                dragHoverNewFlow ? '!bg-accent/10 !text-content ring-1 ring-accent' : ''
              ]"
              title="Flows (drag media here to create new)"
            >
              <BoltIcon class="w-icon-nav h-icon-nav flex-shrink-0" />
              <span>Flows</span>
            </button>
            <Tooltip text="Create new flow" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click.stop="createNewFlow"
                class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-light"
              >
                <PlusIcon class="w-icon-inline h-icon-inline" />
              </button>
            </Tooltip>
          </div>

          <!-- Tools landing link -->
          <button
            @click="handleNavClick('all-tools')"
            data-tour="tools"
            class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
            :class="activeTab === 'all-tools' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : ''"
          >
            <WrenchScrewdriverIcon class="w-icon-nav h-icon-nav flex-shrink-0" />
            <span>Tools</span>
          </button>

          <!-- Trash closes the nav run, where trash conventionally lives. It is
               a plain row: last in the list is emphasis enough, and the
               Assets fold stays for saved views alone. -->
          <button
            @click="handleNavClick('trash')"
            data-testid="sidebar-trash"
            class="flex items-center gap-2 px-3 py-1.5 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent w-full text-left coarse:min-h-11 [&>:first-child]:mx-1"
            :class="activeTab === 'trash' ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : ''"
          >
            <TrashIcon class="w-icon-nav h-icon-nav flex-shrink-0" />
            <span>Trash</span>
          </button>
          </div>

          <SidebarScrollArea :flat="isMobile" @edges="onTabsEdges">
          <SidebarProjects v-if="activeProjectId == null" @selected="props.isMobile && emit('close')" />

          <!-- ==================== ZONE 2: Workspace Tabs ==================== -->
          <div v-if="pinnedTabs.length > 0 || openTabs.length > 0 || editorTabs.length > 0" class="contents">

            <!-- Pinned and Open share the section label recipe. -->
            <SidebarSectionHeader v-if="pinnedTabs.length > 0" id="pinned" label="Pinned" />

            <template v-if="!isCollapsed('pinned')">
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
                class="coarse:min-h-11 flex items-center gap-2 px-3 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent text-left w-full"
                :aria-current="isTabActive(tab) ? 'page' : undefined"
                :class="[
                  isTwoLineTab(tab) ? 'min-h-10' : 'min-h-8',
                  tab.type === 'tool' ? 'pr-1.5' : '',
                  isTabActive(tab) ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : '',
                  dragHoverTabId === tab.id ? (tab.type === 'tool' && dragAddModifier ? '!bg-green-500/20 !text-content ring-1 ring-green-500/50' : '!bg-accent/10 !text-content ring-1 ring-accent') : '',
                  tab.type === 'tool' && !isToolCompatible(tab.entityId) ? 'opacity-50' : '',
                  isTabToolUnavailable(tab) ? 'opacity-70 group-hover:opacity-100' : ''
                ]"
                :title="tab.type === 'tool' ? [tab.displayName, getToolSubtitle(tab.entityId), getToolIncompatibilityReason(tab.entityId)].filter(Boolean).join(' · ') : tab.displayName"
              >
                <!-- Inline rename -->
                <template v-if="editingItem?.tabId === tab.id">
                  <MediaImage v-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'collection'" class="w-6 h-6 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-px flex-shrink-0">
                    <div v-if="getCollectionPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-px">
                      <div
                        v-for="(column, columnIndex) in getCollectionPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-rename-collection-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-px"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-rename-collection-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getCollectionPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isCollectionPreviewVideo(item.file_format)"
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
                      <component :is="getTabIcon(tab)" class="w-icon-nav h-icon-nav text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" size="xs" />
                  <div v-else-if="tab.type === 'tool'" class="w-6 h-6 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <svg class="w-icon-nav h-icon-nav" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" v-html="toolGlyphSvg(tab.entityId)" />
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-full overflow-hidden flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" size="xs" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" size="xs" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 mx-1 flex-shrink-0" />
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
                  <MediaImage v-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'collection'" class="w-6 h-6 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-px flex-shrink-0">
                    <div v-if="getCollectionPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-px">
                      <div
                        v-for="(column, columnIndex) in getCollectionPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-collection-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-px"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-collection-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getCollectionPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isCollectionPreviewVideo(item.file_format)"
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
                      <component :is="getTabIcon(tab)" class="w-icon-nav h-icon-nav text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" size="xs" />
                  <div v-else-if="tab.type === 'tool'" class="w-6 h-6 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <svg class="w-icon-nav h-icon-nav" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" v-html="toolGlyphSvg(tab.entityId)" />
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-full overflow-hidden flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" size="xs" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" size="xs" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 mx-1 flex-shrink-0" />

                  <!-- Tool name, activity, then the provider mark in the row's
                       trailing slot (the warning when unavailable), so the
                       marks form one right-aligned column -->
                  <div v-if="tab.type === 'tool'" class="flex-1 min-w-0 flex items-center gap-2">
                    <span class="flex-1 min-w-0 truncate text-sm" @dblclick.stop="!isMobile && startInlineRename(tab)">
                      {{ getToolTabTitle(tab) }}
                    </span>
                    <span v-if="isTabStalled(tab)" class="flex flex-shrink-0" title="Waiting in the generation queue"><ClockIcon class="h-3.5 w-3.5 text-amber-500" /></span>
                    <Spinner v-else-if="isTabGenerating(tab)" size="sm" hue="border-t-blue-500" />
                    <StatusDot
                      v-else-if="unseenKindFor(tab.id)"
                      :bucket="unseenKindFor(tab.id) === 'error' ? 'failed' : 'running'"
                      :title="unseenKindFor(tab.id) === 'error' ? 'Finished with errors since you last looked' : 'Finished since you last looked'"
                    />
                    <ToolProviderBadge
                      :class="[
                        isTabToolUnavailable(tab) ? 'invisible' : '',
                      ]"
                      :provider-name="getToolProvider(tab.entityId)"
                      :provider-id="allToolsMap.get(tab.entityId)?.provider_id || tab.entityId.split(':')[0]"
                      :cloud="isToolStimmaCloud(tab.entityId)"
                      :detail="getToolSubtitle(tab.entityId)"
                    />
                  </div>

                  <!-- Collection with title/subtitle -->
                  <div v-else-if="tab.type === 'collection' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] leading-4">
                        {{ tab.displayName }}
                      </span>
                      <span class="min-w-0 truncate font-mono tabular-nums text-[11px] leading-[14px] text-content-muted">
                        {{ formatCollectionTabDetail(tab.entityId) }}
                      </span>
                    </div>
                  </div>

                  <div v-else-if="tab.type === 'project' && tab.displayName" class="flex-1 min-w-0 flex flex-col">
                    <span class="truncate text-[13px] leading-4">
                      {{ tab.displayName }}
                    </span>
                    <span class="truncate text-[11px] leading-[14px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Project without name -->
                  <div v-else-if="tab.type === 'project'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] leading-4 text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this project...
                    </span>
                    <span class="truncate text-[11px] leading-[14px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Chat title -->
                  <div v-else-if="tab.type === 'chat' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-sm">
                        {{ tab.displayName }}
                      </span>
                    </div>
                    <span
                      v-if="getChatMetadata(tab.entityId)?.mcp_driven"
                      class="flex-shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10"
                      title="Driven by a connected assistant over MCP"
                    >MCP</span>
                  </div>

                  <!-- Chat without name -->
                  <div v-else-if="tab.type === 'chat'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span
                        @click.stop="startInlineRename(tab)"
                        class="truncate text-sm text-content-muted italic cursor-pointer hover:text-content-secondary"
                      >
                        Name this chat...
                      </span>
                    </div>
                    <span
                      v-if="getChatMetadata(tab.entityId)?.mcp_driven"
                      class="flex-shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10"
                      title="Driven by a connected assistant over MCP"
                    >MCP</span>
                  </div>

                  <!-- Flow with title/subtitle -->
                  <div v-else-if="tab.type === 'flow'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      v-if="tab.displayName"
                      class="truncate text-[13px] leading-4"
                    >
                      {{ tab.displayName }}
                    </span>
                    <span
                      v-else
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] leading-4 text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this flow...
                    </span>
                    <FlowStatusPill
                      :flow-id="tab.entityId"
                      show-pending
                      text-class="truncate text-[11px] leading-[14px] text-content-muted"
                    />
                  </div>

                  <!-- Non-tool/chat/collection/flow items -->
                  <span
                    v-else-if="tab.displayName"
                    class="truncate text-sm flex-1"
                  >
                    {{ tab.displayName }}
                  </span>
                  <span
                    v-else-if="tab.type === 'collection'"
                    @click.stop="startInlineRename(tab)"
                    class="truncate text-sm flex-1 text-content-muted italic cursor-pointer hover:text-content-secondary"
                  >
                    Name this collection...
                  </span>
                  <!-- Working: spinner. The dot is reserved for "finished since
                       you last looked". -->
                  <span
                    v-if="tab.type === 'chat' && isTabStalled(tab)"
                    class="flex flex-shrink-0 self-center"
                    title="Waiting in the generation queue"
                  ><ClockIcon class="h-3.5 w-3.5 text-amber-500" /></span>
                  <Spinner
                    v-else-if="isTabGenerating(tab) && tab.type !== 'flow' && tab.type !== 'tool'"
                    size="sm"
                    hue="border-t-blue-500"
                    class="self-center"
                  />
                  <StatusDot
                    v-else-if="unseenKindFor(tab.id) && tab.type !== 'tool'"
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
                <ExclamationTriangleIcon class="w-icon-inline h-icon-inline" :stroke-width="1.75" />
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
            </template>

            <!-- Open holds both kinds of working set. Images have no names, so open
                 editors stay a wrap panel at the top; named rows follow below. -->
            <SidebarSectionHeader v-if="openTabs.length > 0 || editorTabs.length > 0" id="open" label="Open" />

            <EditorShelf
              v-if="!isCollapsed('open')"
              :tabs="editorTabs"
              @open="navigateToTabId"
              @remove="closeTab"
              @contextmenu="onShelfContextMenu"
              @media-drop="handleShelfMediaDrop"
            />

            <template v-if="!isCollapsed('open')">
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
                class="coarse:min-h-11 flex items-center gap-2 px-3 rounded text-content-secondary no-underline text-sm font-normal transition-all cursor-pointer whitespace-nowrap relative hover:bg-overlay-subtle hover:text-content border-none bg-transparent text-left w-full"
                :aria-current="isTabActive(tab) ? 'page' : undefined"
                :class="[
                  isTwoLineTab(tab) ? 'min-h-10' : 'min-h-8',
                  tab.type === 'tool' ? 'pr-1.5' : 'group-hover:pr-7',
                  isTabActive(tab) ? '!bg-selection/15 !text-content [&>:first-child]:text-selection' : '',
                  dragHoverTabId === tab.id ? (tab.type === 'tool' && dragAddModifier ? '!bg-green-500/20 !text-content ring-1 ring-green-500/50' : '!bg-accent/10 !text-content ring-1 ring-accent') : '',
                  tab.type === 'tool' && !isToolCompatible(tab.entityId) ? 'opacity-50' : '',
                  isTabToolUnavailable(tab) ? 'opacity-70 group-hover:opacity-100' : ''
                ]"
                :title="tab.type === 'tool' ? [tab.displayName, getToolSubtitle(tab.entityId), getToolIncompatibilityReason(tab.entityId)].filter(Boolean).join(' · ') : tab.displayName"
              >
                <!-- Inline rename -->
                <template v-if="editingItem?.tabId === tab.id">
                  <MediaImage v-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'collection'" class="w-6 h-6 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-px flex-shrink-0">
                    <div v-if="getCollectionPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-px">
                      <div
                        v-for="(column, columnIndex) in getCollectionPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-rename-open-collection-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-px"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-rename-open-collection-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getCollectionPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isCollectionPreviewVideo(item.file_format)"
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
                      <component :is="getTabIcon(tab)" class="w-icon-nav h-icon-nav text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" size="xs" />
                  <div v-else-if="tab.type === 'tool'" class="w-6 h-6 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <svg class="w-icon-nav h-icon-nav" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" v-html="toolGlyphSvg(tab.entityId)" />
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-full overflow-hidden flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" size="xs" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" size="xs" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 mx-1 flex-shrink-0" />
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
                  <MediaImage v-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
                  <div v-else-if="tab.type === 'collection'" class="w-6 h-6 overflow-hidden rounded-media border border-edge-subtle bg-overlay-faint p-px flex-shrink-0">
                    <div v-if="getCollectionPreviewItems(tab.entityId).length > 0" class="flex h-full items-start gap-px">
                      <div
                        v-for="(column, columnIndex) in getCollectionPreviewColumns(tab.entityId)"
                        :key="`${tab.id}-open-collection-column-${columnIndex}`"
                        class="flex min-w-0 flex-1 flex-col gap-px"
                      >
                        <div
                          v-for="(item, index) in column"
                          :key="`${tab.id}-open-collection-item-${columnIndex}-${item.id}-${index}`"
                          class="overflow-hidden rounded-media bg-overlay-subtle"
                          :style="getCollectionPreviewTileStyle(item)"
                        >
                          <MediaImage
                            :media-id="item.id"
                            :file-hash="item.file_hash"
                            :file-path="item.file_path"
                            :file-format="item.file_format"
                            :is-video="isCollectionPreviewVideo(item.file_format)"
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
                      <component :is="getTabIcon(tab)" class="w-icon-nav h-icon-nav text-content-secondary" />
                    </div>
                  </div>
                  <EntityIcon v-else-if="tab.type === 'project'" type="project" size="xs" />
                  <div v-else-if="tab.type === 'tool'" class="w-6 h-6 flex items-center justify-center flex-shrink-0 text-content-secondary">
                    <svg class="w-icon-nav h-icon-nav" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" v-html="toolGlyphSvg(tab.entityId)" />
                  </div>

                  <MediaImage v-else-if="tab.type === 'chat' && getChatMetadata(tab.entityId)?.thumbnail_media_id" :media-id="getChatMetadata(tab.entityId).thumbnail_media_id" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-6 h-6 rounded-full overflow-hidden flex-shrink-0" img-class="w-full h-full object-cover" />
                  <EntityIcon v-else-if="tab.type === 'chat'" type="chat" size="xs" />
                  <EntityIcon v-else-if="tab.type === 'flow'" type="flow" size="xs" />
                  <component v-else :is="getTabIcon(tab)" class="w-4 h-4 mx-1 flex-shrink-0" />

                  <!-- Tool name, activity, then the provider mark in the row's
                       trailing slot (the close X on hover, the warning when
                       unavailable), so the marks form one right-aligned column -->
                  <div v-if="tab.type === 'tool'" class="flex-1 min-w-0 flex items-center gap-2">
                    <span class="flex-1 min-w-0 truncate text-sm" @dblclick.stop="!isMobile && startInlineRename(tab)">
                      {{ getToolTabTitle(tab) }}
                    </span>
                    <span v-if="isTabStalled(tab)" class="flex flex-shrink-0" title="Waiting in the generation queue"><ClockIcon class="h-3.5 w-3.5 text-amber-500" /></span>
                    <Spinner v-else-if="isTabGenerating(tab)" size="sm" hue="border-t-blue-500" />
                    <StatusDot
                      v-else-if="unseenKindFor(tab.id)"
                      :bucket="unseenKindFor(tab.id) === 'error' ? 'failed' : 'running'"
                      :title="unseenKindFor(tab.id) === 'error' ? 'Finished with errors since you last looked' : 'Finished since you last looked'"
                    />
                    <ToolProviderBadge
                      :class="[
                        !isMobile ? 'group-hover:opacity-0 transition-opacity' : '',
                        isTabToolUnavailable(tab) ? 'invisible' : '',
                      ]"
                      :provider-name="getToolProvider(tab.entityId)"
                      :provider-id="allToolsMap.get(tab.entityId)?.provider_id || tab.entityId.split(':')[0]"
                      :cloud="isToolStimmaCloud(tab.entityId)"
                      :detail="getToolSubtitle(tab.entityId)"
                    />
                  </div>

                  <!-- Collection with title/subtitle -->
                  <div v-else-if="tab.type === 'collection' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-[13px] leading-4">
                        {{ tab.displayName }}
                      </span>
                      <span class="min-w-0 truncate font-mono tabular-nums text-[11px] leading-[14px] text-content-muted">
                        {{ formatCollectionTabDetail(tab.entityId) }}
                      </span>
                    </div>
                  </div>

                  <div v-else-if="tab.type === 'project' && tab.displayName" class="flex-1 min-w-0 flex flex-col">
                    <span class="truncate text-[13px] leading-4">
                      {{ tab.displayName }}
                    </span>
                    <span class="truncate text-[11px] leading-[14px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Project without name -->
                  <div v-else-if="tab.type === 'project'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] leading-4 text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this project...
                    </span>
                    <span class="truncate text-[11px] leading-[14px] text-content-muted">
                      Project
                    </span>
                  </div>

                  <!-- Chat title -->
                  <div v-else-if="tab.type === 'chat' && tab.displayName" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span class="truncate text-sm">
                        {{ tab.displayName }}
                      </span>
                    </div>
                    <span
                      v-if="getChatMetadata(tab.entityId)?.mcp_driven"
                      class="flex-shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10"
                      title="Driven by a connected assistant over MCP"
                    >MCP</span>
                  </div>

                  <!-- Chat without name -->
                  <div v-else-if="tab.type === 'chat'" class="flex-1 min-w-0 flex items-center gap-1.5">
                    <div class="flex-1 min-w-0 flex flex-col">
                      <span
                        @click.stop="startInlineRename(tab)"
                        class="truncate text-sm text-content-muted italic cursor-pointer hover:text-content-secondary"
                      >
                        Name this chat...
                      </span>
                    </div>
                    <span
                      v-if="getChatMetadata(tab.entityId)?.mcp_driven"
                      class="flex-shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10"
                      title="Driven by a connected assistant over MCP"
                    >MCP</span>
                  </div>

                  <!-- Flow with title/subtitle -->
                  <div v-else-if="tab.type === 'flow'" class="flex-1 min-w-0 flex flex-col">
                    <span
                      v-if="tab.displayName"
                      class="truncate text-[13px] leading-4"
                    >
                      {{ tab.displayName }}
                    </span>
                    <span
                      v-else
                      @click.stop="startInlineRename(tab)"
                      class="truncate text-[13px] leading-4 text-content-muted italic cursor-pointer hover:text-content-secondary"
                    >
                      Name this flow...
                    </span>
                    <FlowStatusPill
                      :flow-id="tab.entityId"
                      show-pending
                      text-class="truncate text-[11px] leading-[14px] text-content-muted"
                    />
                  </div>

                  <!-- Non-tool/chat/collection/flow items -->
                  <span
                    v-else-if="tab.displayName"
                    class="truncate text-sm flex-1"
                  >
                    {{ tab.displayName }}
                  </span>
                  <span
                    v-else-if="tab.type === 'collection'"
                    @click.stop="startInlineRename(tab)"
                    class="truncate text-sm flex-1 text-content-muted italic cursor-pointer hover:text-content-secondary"
                  >
                    Name this collection...
                  </span>
                  <!-- Working: spinner. The dot is reserved for "finished since
                       you last looked". -->
                  <span
                    v-if="tab.type === 'chat' && isTabStalled(tab)"
                    class="flex flex-shrink-0 self-center"
                    title="Waiting in the generation queue"
                  ><ClockIcon class="h-3.5 w-3.5 text-amber-500" /></span>
                  <Spinner
                    v-else-if="isTabGenerating(tab) && tab.type !== 'flow' && tab.type !== 'tool'"
                    size="sm"
                    hue="border-t-blue-500"
                    class="self-center"
                  />
                  <StatusDot
                    v-else-if="unseenKindFor(tab.id) && tab.type !== 'tool'"
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
                <ExclamationTriangleIcon class="w-icon-inline h-icon-inline" :stroke-width="1.75" />
              </span>
              <!-- Close button (appears on hover). Not on phones: there is no
                   hover to reveal it, so it was an invisible 44px target at the
                   end of every row that swallowed taps; the row's sheet closes. -->
              <Tooltip v-if="!isMobile" text="Close" class="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  @click.stop="closeTab(tab.id)"
                  class="w-5 h-5 flex items-center justify-center rounded text-content-muted hover:text-content-secondary hover:bg-overlay-light"
                >
                  <XMarkIcon class="w-icon-inline h-icon-inline" />
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
            </template>
          </div>
          </SidebarScrollArea>

        </nav>

        <!-- Footer: account chip (only when signed in) + settings gear. The
             top hairline shows only while nav content is scrolled under it
             (scroll-edge divider); border stays in flow via transparent so
             toggling never shifts layout. -->
        <div
          class="@container relative flex items-center gap-1 py-2 border-t flex-shrink-0 transition-colors"
          :class="[navScrolledUnder ? 'border-edge-subtle' : 'border-transparent', showAccountChip ? 'px-2' : 'pl-5 pr-2 coarse:pl-3.5']"
        >
          <!-- Signed in: chip fills the left, compact feedback + gear icons
               on the right. Signed out: feedback and gear split the bar as
               equal cells so it reads as a composed strip, not two orphaned
               icons at opposite corners. -->
          <template v-if="showAccountChip">
            <Tooltip text="Stimma account" class="flex-1 min-w-0">
              <button
                @click="isMobile ? $emit('open-account') : openAccountSettings()"
                aria-label="Stimma account"
                class="w-full flex items-center gap-2.5 px-2 py-1 rounded text-left transition-colors cursor-pointer hover:bg-overlay-subtle border-none bg-transparent"
              >
                <div class="w-7 h-7 rounded-full bg-overlay-light text-content-secondary flex items-center justify-center text-xs font-semibold uppercase flex-shrink-0">
                  {{ accountInitial }}
                </div>
                <!-- A narrow sidebar has no room beside the icons for the name and
                     balance; the initial stands for the account there. -->
                <div class="min-w-0 hidden @[16rem]:flex flex-col leading-tight">
                  <span class="text-[13px] text-content truncate">{{ accountName }}</span>
                  <span v-if="accountBalance" class="text-[11px] font-mono text-content-muted tabular-nums truncate">{{ accountBalance }}</span>
                </div>
              </button>
            </Tooltip>
            <FeedbackFooterButton />
          </template>
          <FeedbackFooterButton v-if="!showAccountChip" />
          <!-- Server picker: an icon in the occasional-actions strip, not a
               chip over the balance. Always present once signed in — with no
               other servers its menu teaches the feature instead of hiding;
               the menu opens upward across the footer. Keyed on sign-in
               alone, not showAccountChip: the developer "hide account" toggle
               dresses the footer for screenshots and must not take the
               picker with it. -->
          <DeviceChip v-if="isAuthenticated" variant="footer" />
          <Tooltip text="Settings (⌘,)" class="w-8 flex-shrink-0 coarse:w-11">
            <button
              @click="openSettingsFromFooter"
              aria-label="Settings"
              class="w-full h-8 flex items-center justify-center rounded text-content-tertiary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle border-none bg-transparent coarse:min-h-11"
            >
              <svg class="w-icon-nav h-icon-nav" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
              </svg>
            </button>
          </Tooltip>
        </div>

        <!-- Resize handle (desktop only) -->
        <div
          v-if="!isMobile"
          class="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-accent/40 transition-colors z-10"
          @mousedown.stop="startResize"
        ></div>

      </div>
    </Transition>

    <!-- The pushed app dims while the drawer is open: the drawer is the one
         bright surface. Taps are caught by the app's own closer; docked
         drawers sit beside the app and leave it lit. -->
    <div
      v-if="isMobile"
      class="pointer-events-none absolute inset-y-0 left-[276px] z-modal w-screen bg-overlay-backdrop transition-opacity duration-200 [.is-docked_&]:hidden"
      :class="isOpen ? 'opacity-100' : 'opacity-0'"
      aria-hidden="true"
    ></div>

    <!-- Workspace Tabs Context Menu -->
    <WorkspaceTabsContextMenu @rename="handleRenameFromContextMenu" @rename-tab="handleRenameTabFromContextMenu" @refresh="loadPinnedTools" />
    <!-- Phones rename from a sheet; inline editing in a drawer row is confusing. -->
    <RenameSheet v-if="isMobile" :show="renameSheetOpen" :name="renameSheet?.name || ''" :label="renameSheet?.label" @close="renameSheetOpen = false" @save="saveRenameFromSheet" />

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
          :class="dropTargetHover === '__chat__' ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onFlowTargetDrop(null, $event)"
        >
          <ChatBubbleOvalLeftEllipsisIcon class="w-icon-nav h-icon-nav flex-shrink-0 pointer-events-none" />
          <span class="truncate pointer-events-none">Chat</span>
        </div>
        <div
          v-for="zone in flowDropTargets.zones"
          :key="zone.name"
          :data-zone="zone.name"
          class="flex items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed text-[12.5px] font-medium transition-colors"
          :class="dropTargetHover === zone.name ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onFlowTargetDrop(zone, $event)"
        >
          <PhotoIcon class="w-icon-nav h-icon-nav flex-shrink-0 pointer-events-none" />
          <span class="truncate pointer-events-none">{{ zone.label }}</span>
        </div>
      </div>

      <!-- Tool-tab drop targets, same gesture as the flow panel: with two or
           more inputs in, one thumbnail per filled slot (drop on one to swap
           just that one), then Replace all, then Add while there's room. -->
      <div
        v-if="toolDropTargets"
        data-tool-drop-targets
        class="fixed z-menu w-56 bg-surface border border-edge rounded-lg shadow-xl p-1.5 space-y-1.5"
        :style="{ left: toolDropTargets.left + 'px', top: toolDropTargets.top + 'px' }"
        @dragenter.prevent="cancelFlowTargetsHide"
        @dragover.prevent="onFlowTargetsPanelDragOver"
        @dragleave="onFlowTargetsPanelDragLeave"
      >
        <div
          v-if="toolDropTargets.slots.length > 1"
          class="grid gap-1.5"
          :style="{ gridTemplateColumns: `repeat(${toolDropTargets.columns}, minmax(0, 1fr))` }"
        >
          <div
            v-for="(slot, i) in toolDropTargets.slots"
            :key="i"
            :data-zone="`slot:${i}`"
            class="relative aspect-square rounded-md overflow-hidden border border-dashed bg-matte transition-colors"
            :class="dropTargetHover === `slot:${i}` ? 'border-accent ring-2 ring-accent' : 'border-edge-strong'"
            :title="`Replace ${toolDropTargets.slotName(i)}`"
            @drop.stop.prevent="onToolTargetDrop({ slot: i }, $event)"
          >
            <MediaImage
              v-if="slot.mediaId || slot.hash"
              :media-id="slot.mediaId"
              :file-hash="slot.hash"
              :thumbnail="true"
              :thumbnail-size="128"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full pointer-events-none"
              class="w-full h-full object-cover"
            />
            <div class="absolute top-0.5 left-0.5 w-4 h-4 bg-black/70 rounded-full flex items-center justify-center pointer-events-none">
              <span class="text-[10px] text-white font-medium leading-none">{{ i + 1 }}</span>
            </div>
            <div v-if="dropTargetHover === `slot:${i}`" class="absolute inset-0 bg-accent/40 flex items-center justify-center pointer-events-none">
              <ArrowsRightLeftIcon class="w-5 h-5 text-white" />
            </div>
          </div>
        </div>
        <div
          v-if="toolDropTargets.replaceAll"
          data-zone="__replace__"
          class="flex items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed text-[12.5px] font-medium transition-colors"
          :class="dropTargetHover === '__replace__' ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onToolTargetDrop('replace', $event)"
        >
          <ArrowsRightLeftIcon class="w-icon-nav h-icon-nav flex-shrink-0 pointer-events-none" />
          <span class="truncate pointer-events-none">{{ toolDropTargets.replaceLabel }}</span>
        </div>
        <div
          v-if="toolDropTargets.addLabel"
          data-zone="__add__"
          class="flex items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed text-[12.5px] font-medium transition-colors"
          :class="dropTargetHover === '__add__' ? 'border-accent bg-accent/15 text-accent' : 'border-edge-strong text-content-muted'"
          @drop.stop.prevent="onToolTargetDrop('add', $event)"
        >
          <PlusIcon class="w-icon-nav h-icon-nav flex-shrink-0 pointer-events-none" />
          <span class="truncate pointer-events-none">{{ toolDropTargets.addLabel }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import ToolProviderBadge from './tools/ToolProviderBadge.vue'
import { flowsEnabled } from '../composables/useExperimentalFlows'
import { ref, computed, onMounted, onUnmounted, onUpdated, watch, h, nextTick } from 'vue'
import { ArchiveBoxIcon, ArrowsRightLeftIcon, BoltIcon, BookmarkIcon, ChatBubbleLeftRightIcon, ChatBubbleOvalLeftEllipsisIcon, ChevronLeftIcon, ChevronUpDownIcon, ClockIcon, ExclamationTriangleIcon, FunnelIcon, HeartIcon, HomeIcon, PhotoIcon, PlusIcon, Squares2X2Icon, TrashIcon, WrenchScrewdriverIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { useMarkers } from '../composables/useMarkers'
import { EXPIRING_MARKER_ID } from '../constants/implicitMarkers'
import { useRouter, useRoute } from 'vue-router'
import { useWebSocket } from '../composables/useWebSocket'
import { useAuth } from '../composables/useAuth'
import { useCloudAccount } from '../composables/useCloudAccount'
import { hideAccountRef } from '../appConfig'
import { setPendingMedia } from '../composables/usePendingMedia'
import { makeProfileKey, makeToolDbKey, makeToolProfileKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'
import { filledSlots, isSavedBatch, resultingSlotCount, toolDropSlot, type SlotThumb, type ToolInputField } from '../utils/toolInputSlots'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { createTaskTypeIconComponent, getTaskTypeIconSvg } from '../utils/taskTypeIcons'
import { planToolHandoff } from '../utils/toolHandoff'
import { addToast, reportActionError } from '../composables/useToasts'
import { useGenerationStatus } from '../composables/useGenerationStatus'
import { useUnseenActivity } from '../composables/useUnseenActivity'
import { useAgentActivity } from '../composables/useAgentActivity'
import { useMediaApi } from '../composables/useMediaApi'
import { useProvidersApi } from '../composables/useProvidersApi'
import { useSendToTool } from '../composables/useSendToTool'
import { useWorkspaceTabs, toolTabRoute, toolInstanceScopedId, editorTabRoute, editorRouteTabId, type WorkspaceTab } from '../composables/useWorkspaceTabs'
import { openImageEditor } from '../imageEditor/stack/openImageEditor'
import { removeRecentEntity } from '../composables/useRecentEntities'
import { useProjectRoute } from '../composables/useProjectRoute'
import { useContextSwitch, useWorkingContext } from '../composables/useWorkingContext'
import { belongsToContext, contextRoute, contextSection, projectIdFrom } from '../utils/workingContext'
import WorkingContextPicker from './WorkingContextPicker.vue'
import SidebarProjects from './sidebar/SidebarProjects.vue'
import { useProjectActivity } from '../composables/useProjectActivity'
import { handleProjectDeletedBroadcast } from '../composables/useProjectDeletion'
import { useDragHoverOpen } from '../composables/useProjectDrop'
import SidebarSectionHeader from './sidebar/SidebarSectionHeader.vue'
import SidebarScrollArea from './sidebar/SidebarScrollArea.vue'
import { displaySavedViewName } from '../utils/savedViewName'
import { useSidebarSections } from '../composables/useSidebarSections'
import { useWorkspaceTabsContextMenu } from '../composables/useWorkspaceTabsContextMenu'
import { useFlowCounts } from '../composables/useFlowCounts'
import { useFlowsApi } from '../composables/useFlowsApi'
import { flowMediaInputFields, fieldAcceptsDraggedType, type FlowMediaInputField } from '../utils/flowMediaInputs'
import FlowStatusPill from './flow/FlowStatusPill.vue'
import { useDragStore } from '../stores/dragStore'
import { getDroppedAssetRefs, getDroppedMediaIds } from '../composables/useDragPreview'
import { isDesktop } from '../apiConfig'
import { desktop } from '../desktop'
import { MediaImage } from './media'
import EntityIcon from './EntityIcon.vue'
import RenameSheet from './compact/RenameSheet.vue'
import StatusDot from './ui/StatusDot.vue'
import Spinner from './ui/Spinner.vue'
import { holdKeys } from '../utils/heldKeys.js'
import Tooltip from './ui/Tooltip.vue'
import ActionMenu from './ActionMenu.vue'
import WorkspaceTabsContextMenu from './WorkspaceTabsContextMenu.vue'
import EditorShelf from './EditorShelf.vue'
// @ts-expect-error - distribution-aliased Vue component (see vite.config.js)
import FeedbackFooterButton from '@stimma/feedback-footer-button'
import DeviceChip from './DeviceChip.vue'
import { scheduleMaintenance } from '../utils/startupMaintenance'
import { createLoadRetry } from '../utils/loadRetry.js'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  isMobile: {
    type: Boolean,
    default: false
  },
  // Focus screens (slideshow, image editor): the docked sidebar leaves the
  // layout but stays mounted, since its drop targets and state live here.
  // `peeking` slides it back in as an overlay for the length of a media drag.
  collapsed: {
    type: Boolean,
    default: false
  },
  peeking: {
    type: Boolean,
    default: false
  }
})
const focusCollapsed = computed(() => props.collapsed && !props.isMobile)

const emit = defineEmits(['close', 'open-settings', 'media-dropped-on-tool', 'media-dropped-on-chat', 'open-account'])

// Platform detection
const isDesktopMac = isDesktop() && navigator.platform.toLowerCase().includes('mac')

// Navigation
const router = useRouter()
const route = useRoute()
const { activeProjectId, activeProject, refreshProjects, rememberProject, selectProject } = useWorkingContext()
const switchContext = useContextSwitch()
const { isCollapsed, toggleSection } = useSidebarSections()
const { isBusyElsewhere } = useProjectActivity()
const busyElsewhere = computed(() => activeProjectId.value != null && isBusyElsewhere(activeProjectId.value))
const projectPicker = ref<InstanceType<typeof WorkingContextPicker> | null>(null)
const projectHeader = ref<HTMLElement | null>(null)
const projectHeaderDrag = useDragHoverOpen(() => projectPicker.value?.openForDrop(projectHeader.value))
async function leaveProject() {
  if (await switchContext(null) && props.isMobile) emit('close')
}
const activeTab = computed(() => contextSection(route.name) || route.name)

// WebSocket
const { on, connected: wsConnected } = useWebSocket()

// Footer: account chip + settings gear. hideAccountRef (developer toggle)
// forces the signed-out treatment for screenshots.
const { isAuthenticated, user } = useAuth()
const { cloudUser, fetchCloudAccount, formatBalance } = useCloudAccount()
// The phone's account menu is also its disconnect/sign-out escape path.
const showAccountChip = computed(() => ['ios', 'android'].includes(desktop.kind) || (isAuthenticated.value && !hideAccountRef.value))

const accountName = computed(() => {
  const email = user.value?.email || ''
  return email.split('@')[0] || 'Account'
})
const accountInitial = computed(() => accountName.value.charAt(0) || '?')
const accountBalance = computed(() =>
  cloudUser.value ? formatBalance(cloudUser.value.credits) : ''
)

// The balance is optional chrome: refresh it with other background
// maintenance (promptly once startup is done) rather than during startup.
watch(isAuthenticated, (signedIn) => {
  if (signedIn) void scheduleMaintenance('cloud-account', fetchCloudAccount)
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
const tabsScrolledAbove = ref(false)

// Wide: the scroll area below the library links reports both of its edges.
function onTabsEdges(edges: { above: boolean; below: boolean }) {
  tabsScrolledAbove.value = edges.above
  navScrolledUnder.value = edges.below
}

// Phones: the nav itself is the scroller.
function updateNavEdge() {
  if (!props.isMobile) return
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
const { isToolActive: isToolGenerating, isFeedScopeActive, isToolStalled, isFeedScopeStalled, isChatGenerationStalled } = useGenerationStatus()

// Finished-while-away dots (blue = done, red = failed)
const { unseenKindFor } = useUnseenActivity()

// Chat agent activity (primed on load/reconnect, cleared on disconnect)
const { isChatWorking } = useAgentActivity()

// Send to tool
const { sendToTool } = useSendToTool()

// Workspace tabs
const {
  pinnedTabs: allPinnedTabs, openTabs: allOpenTabs, editorTabs: allEditorTabs, allTabs, addTab, addEditorTab, updateEditorMedia,
  findNextTab, removeTab, updateTabName, removeTabByEntity,
  reconcileToolPins, moveTab, setLastLibraryRoute,
  markTabActivated, updateTabCustomName, setTabContext
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
const { getSavedViews, updateSavedView, reorderSavedView, getCollection, getProject, createCollection: apiCreateCollection, updateCollection, updateProject } = useMediaApi()
const { listPinnedTools, fetchProvidersAndTools, subscribeToProviderChanges } = useProvidersApi()

// ==================== State ====================

const savedViews = ref([])
const contextSavedViews = computed(() => savedViews.value.filter(v => (v.project_id ?? null) === activeProjectId.value))
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
type CollectionPreviewItem = {
  id: number
  file_hash?: string | null
  file_path?: string | null
  file_format?: string | null
  width?: number | null
  height?: number | null
}

type CollectionMetadata = {
  cover_media_id: number | null
  item_count: number
  section_count: number
  project_id: number | null
  preview_items: CollectionPreviewItem[]
}

const collectionMetadata = ref<Map<string, CollectionMetadata>>(new Map())
const chatMetadata = ref<Map<string, { thumbnail_media_id: number | null, last_message: string, project_id: number | null, mcp_driven?: boolean }>>(new Map())
const projectNames = ref<Map<string, string>>(new Map())

const flowMetadata = ref<Map<string, number | null | undefined>>(new Map())
function isContextTab(tab: WorkspaceTab) {
  if (tab.type === 'collection') {
    const owner = collectionMetadata.value.has(tab.entityId) ? collectionMetadata.value.get(tab.entityId)!.project_id : tab.projectId
    return owner !== undefined && owner === activeProjectId.value
  }
  if (tab.type === 'chat') {
    const owner = chatMetadata.value.has(tab.entityId) ? chatMetadata.value.get(tab.entityId)!.project_id : tab.projectId
    return owner !== undefined && owner === activeProjectId.value
  }
  if (tab.type === 'flow') {
    const owner = flowMetadata.value.has(tab.entityId) ? flowMetadata.value.get(tab.entityId) : tab.projectId
    return owner !== undefined && owner === activeProjectId.value
  }
  return belongsToContext(tab, activeProjectId.value)
}
const pinnedTabs = computed(() => allPinnedTabs.value.filter(isContextTab))
const openTabs = computed(() => allOpenTabs.value.filter(isContextTab))
// Held per tab, so the handoff between one job and the next (on any of the
// tab's clients) never flashes the stalled clock.
const stalledTabIds = holdKeys(
  () => new Set([...pinnedTabs.value, ...openTabs.value].filter(isTabStalledNow).map(tab => tab.id)),
  3000,
)
const isTabStalled = (tab: WorkspaceTab) => stalledTabIds.value.has(tab.id)
const editorTabs = computed(() => allEditorTabs.value.filter(isContextTab))
const visibleTabIds = computed(() => allTabs.value.filter(isContextTab).map(t => t.id))
// Drag-drop state
const dragHoverTabId = ref<string | null>(null)
// Live shift state while dragging over a tool tab: shift flips a drop on the
// tab itself from replace-inputs to add-to-inputs (a shortcut; the drop-target
// panel beside the tab offers Add without it). Cursor and ring color track it.
const dragAddModifier = ref(false)
const dragHoverNewCollection = ref(false)
const dragHoverNewChat = ref(false)
const dragHoverNewFlow = ref(false)
const dragHoverStimmaHome = ref(false)
const tabDragCounters = ref<Map<string, number>>(new Map())
const newCollectionDragCounter = ref(0)
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

// The nav shows once the first load settles, even a failed one: its links work
// without the lists, which fill in when a retry lands. Later reloads and
// retries never take it away again.
const hasLoadedData = ref(false)
let sidebarUnmounted = false

// A failed list retries on its own; a reconnect would too, but the socket can
// stay up while reads fail (a phone whose network was settling at launch).
// A list already being read (a reconnect) is left to that read, which rearms
// the retry if it fails.
const sidebarRetry = createLoadRetry(() => {
  const { savedViews: views, tools } = loadingState.value
  if (views.error && !views.loading) void loadSavedViews()
  if (tools.error && !tools.loading) void loadPinnedTools()
})
function settleSidebarLoad() {
  if (sidebarUnmounted) return
  hasLoadedData.value = true
  const states = Object.values(loadingState.value)
  if (states.some(s => s.loading)) return
  if (states.some(s => s.error)) sidebarRetry.failed()
  else sidebarRetry.succeeded()
}

// A phone drawer is short, so pinned tools (reachable from Tools) start folded
// until the person chooses otherwise; their choice is stored from then on.
watch(() => hasLoadedData.value && props.isMobile, (phoneReady) => {
  if (!phoneReady || localStorage.getItem(makeProfileKey('sidebar', 'collapsed_sections')) !== null) return
  if (!isCollapsed('pinned')) toggleSection('pinned')
}, { immediate: true })

// Saved views sit under Assets. Inside Assets (the browser or any saved view)
// they all show; elsewhere only the pinned ones do. Pinning is part of the view.
const inAssets = computed(() => activeTab.value === 'browse' || route.name === 'saved-view')
const sidebarSavedViews = computed(() => contextSavedViews.value.filter(v => inAssets.value || v.pinned))
const PIN_PATH = 'M10.5 1.5L14.5 5.5L12 8L11.5 12L8 8.5L4.5 12L4 11.5L7.5 8L4 4.5L8 4L10.5 1.5Z'
const pinSvg = (filled: boolean) => `<svg viewBox="0 0 16 16" fill="${filled ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.25"><path d="${PIN_PATH}"/></svg>`
async function toggleSavedViewPin(view: any) {
  const pinned = !view.pinned
  view.pinned = pinned
  try {
    await updateSavedView(view.id, { pinned })
  } catch (error) {
    console.error('Failed to pin saved view:', error)
    view.pinned = !pinned
  }
}
const savedViewMenu = ref<{ view: any, x: number, y: number } | null>(null)
function openSavedViewMenu(view: any, event: MouseEvent) {
  savedViewMenu.value = { view, x: event.clientX, y: event.clientY }
}
const UP_SVG = '<svg fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5"/></svg>'
const DOWN_SVG = '<svg fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5"/></svg>'
const savedViewMenuActions = computed(() => {
  const view = savedViewMenu.value?.view
  if (!view) return []
  const siblings = contextSavedViews.value
  const index = siblings.findIndex(v => v.id === view.id)
  const pin = { id: 'pin', label: view.pinned ? 'Unpin' : 'Pin', icon: pinSvg(!view.pinned), action: () => toggleSavedViewPin(view) }
  // Reordering is offered only where every view is visible, so a move never
  // swaps with a hidden neighbour.
  if (!inAssets.value) return [pin]
  return [
    pin,
    { id: 'divider' },
    { id: 'up', label: 'Move up', disabled: index <= 0, icon: UP_SVG, action: () => moveSavedView(view, 'up') },
    { id: 'down', label: 'Move down', disabled: index < 0 || index >= siblings.length - 1, icon: DOWN_SVG, action: () => moveSavedView(view, 'down') },
  ]
})
async function moveSavedView(view: any, direction: 'up' | 'down') {
  try { await reorderSavedView(view.id, direction) } catch (error) { console.error('Failed to move saved view:', error) }
}

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
  if (availability === 'needs_setup') return `${provider} · not ready`
  if (availability !== 'available') return `${provider} · not configured`
  return provider
}

// The rail has one row height (32px, 44px on touch) and one two-line variant
// (40px): rows that carry a second line of detail. Mirrors the row template.
function isTwoLineTab(tab: WorkspaceTab): boolean {
  switch (tab.type) {
    // Tools carry a trailing provider mark; chats show only their title.
    case 'tool': return false
    case 'collection': return !!tab.displayName
    case 'chat': return false
    case 'flow':
    case 'project': return true
    default: return false
  }
}

function isTabToolUnavailable(tab: any): boolean {
  return tab.type === 'tool' && getToolAvailability(tab.entityId) !== 'available'
}

function isToolStimmaCloud(fullToolId: string): boolean {
  const tool = allToolsMap.value.get(fullToolId)
  return tool ? isStimmaCloudTool(tool) : false
}

function extractCollectionMetadata(collection: any) {
  const sections = collection?.sections || []
  const previewItems = sections
    .flatMap((section: any) => section.items || [])
    .slice(0, 4)
  const firstItem = previewItems[0] || null
  return {
    cover_media_id: firstItem?.id || null,
    item_count: collection?.asset_count || 0,
    section_count: sections.length,
    project_id: collection?.project_id ?? null,
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

// The open chat, collection or flow moved to another project (here or in another
// window): the working context follows what's on screen.
function followOpenEntity(routeName: string, id: string, projectId: number | null) {
  if (route.name === routeName && String(route.params.id) === id && activeProjectId.value !== projectId) selectProject(projectId)
}

function applyCollectionUpdate(collection: any) {
  if (!collection?.id) return
  const collectionId = String(collection.id)
  setTabContext(`collection:${collectionId}`, collection.project_id ?? null)
  if ('project_id' in collection) followOpenEntity('collection-detail', collectionId, collection.project_id ?? null)
  collectionMetadata.value.set(collectionId, extractCollectionMetadata(collection))
  collectionMetadata.value = new Map(collectionMetadata.value)
  ensureProjectName(collection?.project_id ?? null)

  const nextName = (collection.name || '').trim()
  if (nextName) {
    updateTabName(`collection:${collectionId}`, nextName)
  }
}

async function loadCollectionMetadata(collectionId: string) {
  try {
    const collection = await getCollection(parseInt(collectionId, 10))
    if (collection) {
      applyCollectionUpdate(collection)
    }
  } catch (error) {
    console.error('Failed to load collection metadata:', error)
  }
}

function getCollectionMetadata(collectionId: string) {
  return collectionMetadata.value.get(collectionId)
}

function getCollectionPreviewItems(collectionId: string) {
  return getCollectionMetadata(collectionId)?.preview_items || []
}

function getCollectionPreviewColumns(collectionId: string) {
  const items = getCollectionPreviewItems(collectionId)
  const columns: CollectionPreviewItem[][] = [[], []]
  items.forEach((item, index) => {
    columns[index % columns.length].push(item)
  })
  return columns
}

function getCollectionPreviewTileStyle(item: CollectionPreviewItem) {
  const width = Math.max(item?.width || 1, 1)
  const height = Math.max(item?.height || 1, 1)
  return {
    aspectRatio: `${width} / ${height}`
  }
}

function isCollectionPreviewVideo(fileFormat?: string | null) {
  return !!fileFormat && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(fileFormat.toLowerCase())
}

function formatCount(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`
}

function formatCollectionTabDetail(collectionId: string): string {
  const metadata = getCollectionMetadata(collectionId)
  const itemText = formatCount(metadata?.item_count || 0, 'asset')
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
      setTabContext(`chat:${chatId}`, preview.project_id ?? null)
      chatMetadata.value.set(chatId, {
        thumbnail_media_id: preview.thumbnail_media_id || null,
        last_message: preview.last_message || '',
        project_id: preview.project_id ?? null,
        mcp_driven: !!preview.mcp_driven
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

function loadAllCollectionMetadata() {
  for (const tab of allTabs.value) {
    if (tab.type === 'collection' && !collectionMetadata.value.has(tab.entityId)) {
      loadCollectionMetadata(tab.entityId)
    }
  }
}

// ==================== Tab helpers ====================

// A saved view is a filter, so its glyph says which filter: the marker it
// shows, the clock for expiring items, otherwise the funnel.
const { availableMarkers, init: initMarkers } = useMarkers()
onMounted(() => { void initMarkers() })
function savedViewIcon(view: any) {
  const filters = view?.filters || {}
  if (filters.showExpiring || (filters.selectedMarkers || []).includes(EXPIRING_MARKER_ID)) return ClockIcon
  const names = new Set<string>(
    (filters.selectedMarkers || [])
      .map((id: number) => availableMarkers.value.find((m: any) => m.id === id)?.name)
      .filter(Boolean)
  )
  if (names.has('library')) return BookmarkIcon
  if (names.has('favorite')) return HeartIcon
  return FunnelIcon
}

// Pinned and open tool rows use the task-type glyph at the nav icon's size
// and weight; the provider appears as a trailing badge.
function toolGlyphSvg(toolId: string) {
  return getTaskTypeIconSvg(allToolsMap.value.get(toolId)?.task_type || 'text-to-image')
}

function getTabIcon(tab: WorkspaceTab) {
  if (tab.type === 'tool') {
    const tool = allToolsMap.value.get(tab.entityId)
    return createTaskTypeIconComponent(tool?.task_type || 'text-to-image', 'currentColor')
  }
  if (tab.type === 'chat') return h(ChatBubbleLeftRightIcon, {})
  if (tab.type === 'collection') return h(Squares2X2Icon, {})
  if (tab.type === 'project') return ArchiveBoxIcon
  if (tab.type === 'lineage') {
    // Git-branch-like icon for lineage
    return h('svg', { class: 'w-icon-nav h-icon-nav', fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.75', stroke: 'currentColor' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z' })
    ])
  }
  if (tab.type === 'flow') return h(BoltIcon, {})
  return h('span')
}

function isTabActive(tab: WorkspaceTab): boolean {
  if (tab.type === 'tool') {
    if (route.name !== 'tool' || route.params.fullToolId !== tab.entityId) return false
    const routeProjectId = projectIdFrom(route.query.project_id)
    if ((tab.projectId || null) !== routeProjectId) return false
    return (tab.instanceId || null) === (route.query.instance ? String(route.query.instance) : null)
  }
  if (tab.type === 'chat') return route.name === 'chat' && String(route.params.id) === tab.entityId
  if (tab.type === 'collection') return route.name === 'collection-detail' && String(route.params.id) === tab.entityId
  if (tab.type === 'project') return String(route.name || '').startsWith('project-') && String(route.params.id) === tab.entityId
  if (tab.type === 'editor') return editorRouteTabId(route) === tab.id
  if (tab.type === 'lineage') return route.name === 'lineage' && String(route.params.mediaId) === tab.entityId
  if (tab.type === 'flow') return route.name === 'flow' && String(route.params.id) === tab.entityId
  return false
}

function isTabGenerating(tab: WorkspaceTab): boolean {
  if (tab.type === 'tool') {
    return tab.feedScope ? isFeedScopeActive(tab.feedScope) : isToolGenerating(tab.entityId, tab.projectId ?? null)
  }
  if (tab.type === 'chat') return isChatWorking(tab.entityId)
  return false
}

// Working, but everything it is waiting on sits in the generation queue.
function isTabStalledNow(tab: WorkspaceTab): boolean {
  if (tab.type === 'tool') {
    return tab.feedScope ? isFeedScopeStalled(tab.feedScope) : isToolStalled(tab.entityId, tab.projectId ?? null)
  }
  if (tab.type === 'chat') return isChatWorking(tab.entityId) && isChatGenerationStalled(tab.entityId)
  return false
}

function navigateToTab(tab: WorkspaceTab) {
  if (tab.type === 'tool') {
    router.push(toolTabRoute(tab))
  }
  else if (tab.type === 'chat') router.push({ name: 'chat', params: { id: tab.entityId } })
  else if (tab.type === 'collection') router.push({ name: 'collection-detail', params: { id: tab.entityId } })
  else if (tab.type === 'project') router.push({ name: getLastProjectRoute(tab.entityId), params: { id: tab.entityId } })
  else if (tab.type === 'editor') router.push(editorTabRoute(tab))
  else if (tab.type === 'lineage') router.push({ name: 'lineage', params: { mediaId: tab.entityId } })
  else if (tab.type === 'flow') router.push({ name: 'flow', params: { id: tab.entityId } })

  if (props.isMobile) emit('close')
}

function closeTab(tabId: string) {
  const closingTab = allTabs.value.find(t => t.id === tabId)
  const isActive = closingTab && isTabActive(closingTab)
  if (isActive) {
    const next = findNextTab(new Set([tabId]), visibleTabIds.value)
    if (next) {
      navigateToTab(next)
    } else {
      router.push({ name: 'browse' })
    }
  }
  removeTab(tabId)
}

/** Shelf chips hand back a tab id; navigation stays in one place. */
function navigateToTabId(tabId: string) {
  const tab = allTabs.value.find(t => t.id === tabId)
  if (tab) navigateToTab(tab)
}

function onShelfContextMenu(payload: { tabId: string, event: MouseEvent }) {
  const tab = allTabs.value.find(t => t.id === payload.tabId)
  if (tab) showTabContextMenu(tab, payload.event)
}

function showTabContextMenu(tab: WorkspaceTab, event: MouseEvent) {
  // Resolve project_id from metadata for collections/chats; tool instances carry
  // their own scope (used by "New Tab" to open a sibling in the same project)
  let projectId: number | null = null
  if (tab.type === 'collection') {
    projectId = collectionMetadata.value.get(tab.entityId)?.project_id ?? null
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
  router.push(contextRoute(pageName, activeProjectId.value))
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

// Tool tabs get intent-aware cursor feedback: a naked pointer for the default
// replace ('move'), the OS copy badge (green +) only while shift = add.
// dragover updates the cursor, ring color, and hint when Shift changes.
function handleTabDragOver(tab: WorkspaceTab, e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    dragAddModifier.value = e.shiftKey
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
    const panelTabId = flowDropTargets.value?.tabId ?? toolDropTargets.value?.tabId
    if (panelTabId && panelTabId !== tab.id) scheduleFlowTargetsHide()
    if (tab.type === 'lineage') return // No drag-drop onto lineage tabs
    if (tab.type !== 'tool' || isToolCompatible(tab.entityId)) {
      dragHoverTabId.value = tab.id
    }
    if (tab.type === 'flow') void maybeShowFlowDropTargets(tab, e.currentTarget as HTMLElement)
    if (tab.type === 'tool') showToolDropTargets(tab, e.currentTarget as HTMLElement)
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
  if (count <= 0 && (flowDropTargets.value?.tabId === tab.id || toolDropTargets.value?.tabId === tab.id)) scheduleFlowTargetsHide()
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
    // Shift-drop adds to the tool's existing inputs; plain drop replaces them.
    await sendDropToTool(tab, mediaIds, { add })
  } else if (tab.type === 'chat') {
    emit('media-dropped-on-chat', { chatId: parseInt(tab.entityId, 10), mediaId })
    setPendingMedia('chat', mediaIds, parseInt(tab.entityId, 10))
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
  } else if (tab.type === 'collection') {
    try {
      const response = await fetch(`/api/collections/${tab.entityId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(assetIds.length > 0 ? { asset_ids: assetIds } : { media_ids: mediaIds })
      })
      if (!response.ok) throw new Error(await response.text())
      if (props.isMobile) emit('close')
    } catch (error) {
      reportActionError("Couldn't add to collection.", error)
    }
  }
}

/**
 * Media dropped on the editing shelf. An editor is its Asset's document —
 * another image can't be loaded into one — so a drop opens that image's own
 * editor, which puts a chip on the shelf.
 */
function handleShelfMediaDrop(e: DragEvent) {
  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  if (mediaIds.length === 0) return
  e.preventDefault()
  e.stopPropagation()
  void openImageEditor(router, mediaIds[0])
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
const dropTargetHover = ref<string | null>(null)
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
  toolDropTargets.value = null
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

// The hide timer and hover tracking are shared with the tool-tab panel below.
function scheduleFlowTargetsHide() {
  cancelFlowTargetsHide()
  flowTargetsHideTimer = setTimeout(() => {
    flowDropTargets.value = null
    toolDropTargets.value = null
    dropTargetHover.value = null
  }, 250)
}

function resetFlowDropTargets() {
  cancelFlowTargetsHide()
  flowDropTargets.value = null
  toolDropTargets.value = null
  dropTargetHover.value = null
  dragFlowFieldsCache.clear()
}

// Hover tracking rides dragover (fires continuously on whatever is under the
// cursor) instead of per-row dragenter, which WKWebView delivers unreliably.
// One handler on the panel reads the row from the event target, so the lit
// target always matches where the drop would land.
function onFlowTargetsPanelDragOver(e: DragEvent) {
  cancelFlowTargetsHide()
  const row = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-zone]') : null
  dropTargetHover.value = row?.dataset.zone ?? null
}

function onFlowTargetsPanelDragLeave(e: DragEvent) {
  const next = e.relatedTarget
  if (next instanceof Node && (e.currentTarget as Node).contains(next)) return
  dropTargetHover.value = null
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

// ==================== Tool-tab drop targets ====================
// The same pop-out as flow tabs, for tool tabs: drop on a numbered thumbnail
// to swap just that input, on Replace (all) for the tab's default, or on Add
// to append. Releasing on the tab itself still replaces all, and Shift on the
// tab still adds — the panel just doesn't depend on a modifier reaching the
// drag (Chromium on Linux/Wayland doesn't report one reliably).

interface ToolDropTargets {
  tabId: string
  tab: WorkspaceTab
  left: number
  top: number
  /** Thumbnails to swap one at a time (empty when that isn't offered). */
  slots: SlotThumb[]
  /** Filled slot count, or null when the tab's inputs couldn't be read. */
  filled: number | null
  max: number
  columns: number
  replaceAll: boolean
  replaceLabel: string
  addLabel: string | null
  slotName: (index: number) => string
}

const toolDropTargets = ref<ToolDropTargets | null>(null)

/** The tab's saved working state, or null when it can't be read. */
function readToolTabState(tab: WorkspaceTab, field: ToolInputField) {
  const scoped = toolInstanceScopedId(tab.entityId, tab.projectId ?? null, tab.instanceId ?? null)
  const parse = (raw: string | null) => {
    if (!raw) return null
    try { return JSON.parse(raw) } catch { return null }
  }
  const state = parse(syncedStorage.getItem(makeToolProfileKey(scoped, 'state')))
  const frames = field === 'frames' ? parse(syncedStorage.getItem(makeToolDbKey(scoped, 'video_images'))) : null
  return { state, frames }
}

function showToolDropTargets(tab: WorkspaceTab, el: HTMLElement) {
  const tool = allToolsMap.value.get(tab.entityId)
  if (!tool) return
  const draggedType = draggedMediaType.value
  const slot = toolDropSlot(tool, draggedType)
  let slots: SlotThumb[] = []
  let known = false
  let batch = false
  if (slot) {
    const { state, frames } = readToolTabState(tab, slot.field)
    batch = isSavedBatch(state)
    const filled = batch ? null : filledSlots(slot.field, state, frames)
    if (filled) {
      slots = filled.slice(0, Number.isFinite(slot.max) ? slot.max : undefined)
      known = true
    }
  }
  const max = slot?.max ?? Infinity
  // A targeted change is checked against the slot's count afterwards (a tool
  // needing two images takes a one-image swap into a full pair). Without drag
  // info (nothing to plan with), trust the tool to cap it.
  const fitsWith = (count: number) => !draggedMediaInfo.value
    || planToolHandoff({ tool, items: draggedMediaItems.value, count, targeted: true }).eligible
  const replaceAll = isToolCompatible(tab.entityId)
  const slotSwap = known && slots.length > 1 && fitsWith(slots.length)
  const dragged = Math.max(1, draggedMediaCount.value || 1)
  const noun = slot?.field === 'inputVideos' ? 'video' : slot?.field === 'inputAudios' ? 'audio' : 'image'
  const slotName = (i: number) => slot?.field === 'frames' ? (i === 0 ? 'start frame' : 'end frame') : `${noun} ${i + 1}`
  // Add only where the slot takes more than one item and has room. A saved
  // batch offers only Replace. When the tool's inputs can't be read, offer Add
  // on trust (the tool caps it).
  let addLabel: string | null = null
  if (batch) addLabel = null
  else if (!known) addLabel = max > 1 && replaceAll ? 'Add' : null
  else if (max > 1 && slots.length < max && fitsWith(resultingSlotCount(slots.length, { add: dragged }, max))) {
    addLabel = `Add as ${slotName(slots.length)}`
  }
  if (!replaceAll && !slotSwap && !addLabel) return
  const shownSlots = slotSwap ? slots : []
  const columns = Math.min(4, Math.max(2, shownSlots.length))
  const thumbRows = shownSlots.length > 1 ? Math.ceil(shownSlots.length / columns) : 0
  const rect = el.getBoundingClientRect()
  const thumbSize = (224 - 12 - (columns - 1) * 6) / columns
  const approxHeight = thumbRows * (thumbSize + 6) + ((addLabel ? 1 : 0) + (replaceAll ? 1 : 0)) * 44 + 12
  flowDropTargets.value = null
  toolDropTargets.value = {
    tabId: tab.id,
    tab,
    // Overlap the sidebar edge by 2px, like the flow panel.
    left: rect.right - 2,
    top: Math.max(8, Math.min(rect.top + rect.height / 2 - approxHeight / 2, window.innerHeight - approxHeight - 8)),
    slots: shownSlots,
    filled: known ? slots.length : null,
    max,
    columns,
    replaceAll,
    replaceLabel: slots.length > 1 ? 'Replace all' : 'Replace',
    addLabel,
    slotName,
  }
  cancelFlowTargetsHide()
}

async function onToolTargetDrop(zone: 'replace' | 'add' | { slot: number }, e: DragEvent) {
  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  const targets = toolDropTargets.value
  resetFlowDropTargets()
  // The zone's .stop keeps this drop away from handleTabMediaDrop — do its
  // hover cleanup here instead.
  dragHoverTabId.value = null
  dragAddModifier.value = false
  if (targets) tabDragCounters.value.delete(targets.tabId)
  if (!targets || mediaIds.length === 0) return
  const filled = targets.filled
  if (zone === 'add') {
    const resultingCount = filled == null ? undefined : resultingSlotCount(filled, { add: mediaIds.length }, targets.max)
    await sendDropToTool(targets.tab, mediaIds, { add: true, resultingCount })
  } else if (zone === 'replace') {
    await sendDropToTool(targets.tab, mediaIds, {})
  } else {
    const resultingCount = filled == null ? undefined : resultingSlotCount(filled, { replaceIndex: zone.slot }, targets.max)
    await sendDropToTool(targets.tab, mediaIds.slice(0, 1), { replaceIndex: zone.slot, resultingCount })
  }
}

async function sendDropToTool(tab: WorkspaceTab, mediaIds: number[], opts: { add?: boolean; replaceIndex?: number; resultingCount?: number }) {
  const tool = allToolsMap.value.get(tab.entityId)
  if (!tool) return
  emit('media-dropped-on-tool', { fullToolId: tab.entityId, mediaId: mediaIds[0], instanceId: tab.instanceId })
  try {
    // Pass all dropped ids (multi-select drag) so they batch instead of only the first.
    // Target THIS row's instance, not just the tool+project.
    await sendToTool(mediaIds.length > 1 ? mediaIds : mediaIds[0], tool, undefined, tab.projectId ?? null, tab.instanceId ?? null, opts)
    if (props.isMobile) emit('close')
  } catch (error) {
    console.error('Failed to send media to tool:', error)
    addToast(error instanceof Error ? error.message : 'Failed to send assets to tool', 'warning')
  }
}

// New Collection drag-drop (on the Collections link)
function handleNewCollectionDragEnter(e: DragEvent) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    newCollectionDragCounter.value++
    dragHoverNewCollection.value = true
  }
}

function handleNewCollectionDragLeave(e: DragEvent) {
  newCollectionDragCounter.value--
  if (newCollectionDragCounter.value <= 0) {
    dragHoverNewCollection.value = false
    newCollectionDragCounter.value = 0
  }
}

async function handleNewCollectionDrop(e: DragEvent) {
  e.preventDefault()
  dragHoverNewCollection.value = false
  newCollectionDragCounter.value = 0

  const mediaIds = getDroppedMediaIds(e.dataTransfer)
  const assetIds = getDroppedAssetRefs(e.dataTransfer).map((item) => item.asset_id)
  if (mediaIds.length > 0) {
    try {
      const newCollection = await apiCreateCollection('', activeProjectId.value)
      const response = await fetch(`/api/collections/${newCollection.id}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(assetIds.length > 0 ? { asset_ids: assetIds } : { media_ids: mediaIds })
      })
      if (!response.ok) throw new Error(await response.text())
      router.push({ name: 'collection-detail', params: { id: newCollection.id } })
      if (props.isMobile) emit('close')
    } catch (error) {
      reportActionError("Couldn't create collection.", error)
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
    try {
      const response = await fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: activeProjectId.value })
      })
      if (!response.ok) throw new Error('Failed to create chat')
      const newChat = await response.json()
      setPendingMedia('chat', mediaIds, newChat.id)
      router.push({ name: 'chat', params: { id: newChat.id } })
      if (props.isMobile) emit('close')
    } catch (error) {
      reportActionError("Couldn't create chat.", error)
    }
  }
}

// Resolve (creating if needed) the chat scoped to a flow, mirroring
// FlowView.ensureFlowChat so dropped media is attached to the same chat the
// flow page will display.
async function resolveFlowChatId(flowId: number): Promise<number | null> {
  try {
    const listResp = await fetch(`/api/chats?flow_id=${flowId}&page=1&page_size=1`)
    if (!listResp.ok) throw new Error(await listResp.text())
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
    reportActionError("Couldn't create chat.", error)
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
        body: JSON.stringify({ project_id: activeProjectId.value })
      })
      if (!response.ok) throw new Error('Failed to create flow')
      const flow = await response.json()
      const flowChatId = await resolveFlowChatId(Number(flow.id))
      if (flowChatId != null) setPendingMedia('chat', mediaIds, flowChatId)
      router.push({ name: 'flow', params: { id: String(flow.id) } })
      if (props.isMobile) emit('close')
    } catch (error) {
      reportActionError("Couldn't create flow.", error)
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
    setPendingMedia('home', [mediaIds[0]], null, activeProjectId.value)
    router.push(contextRoute('home', activeProjectId.value))
    if (props.isMobile) emit('close')
  }
}

// Create new collection (from plus button)
async function createNewCollection() {
  try {
    const newCollection = await apiCreateCollection('', activeProjectId.value)
    router.push({ name: 'collection-detail', params: { id: newCollection.id } })
    if (props.isMobile) emit('close')
  } catch (error) {
    reportActionError("Couldn't create collection.", error)
  }
}

// Create new chat (from plus button)
async function createNewChat() {
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: activeProjectId.value })
    })
    if (!response.ok) throw new Error('Failed to create chat')
    const newChat = await response.json()
    router.push({ name: 'chat', params: { id: newChat.id } })
    if (props.isMobile) emit('close')
  } catch (error) {
    reportActionError("Couldn't create chat.", error)
  }
}

async function createNewFlow() {
  try {
    const response = await fetch('/api/flows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: activeProjectId.value })
    })
    if (!response.ok) throw new Error('Failed to create flow')
    const flow = await response.json()
    router.push({ name: 'flow', params: { id: String(flow.id) } })
    if (props.isMobile) emit('close')
  } catch (err) {
    reportActionError("Couldn't create flow.", err)
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
    moveTab(fromIndex, index, group, (group === 'pinned' ? pinnedTabs.value : openTabs.value).map(t => t.id))
  }
  handleTabReorderDragEnd()
}

function handleTabReorderDragEnd() {
  tabReorderDragSource.value = null
  tabReorderDropTarget.value = null
}

// ==================== Inline rename ====================

// Phones: every rename goes through one sheet (DESIGN.md §1.11); the row
// never turns into a text field.
const renameSheet = ref<{ tabId: string, tabType: string, entityId: string, name: string, label: string } | null>(null)
// Open state lives apart from the target: the sheet emits close before save.
const renameSheetOpen = ref(false)
const RENAME_LABELS: Record<string, string> = { chat: 'Rename chat', collection: 'Rename collection', flow: 'Rename flow', project: 'Rename project', tool: 'Rename tool window' }
function openRenameSheet(tabId: string, tabType: string, entityId: string, name: string) {
  renameSheet.value = { tabId, tabType, entityId, name, label: RENAME_LABELS[tabType] || 'Rename' }
  renameSheetOpen.value = true
}
function saveRenameFromSheet(name: string) {
  const target = renameSheet.value
  renameSheetOpen.value = false
  if (!target) return
  editingItem.value = { tabId: target.tabId, tabType: target.tabType, entityId: target.entityId }
  editingName.value = name
  saveRename()
}

function handleRenameFromContextMenu(tabType: 'collection' | 'chat' | 'flow' | 'project', entityId: string, currentName: string) {
  const tabId = `${tabType}:${entityId}`
  if (props.isMobile) { openRenameSheet(tabId, tabType, entityId, currentName); return }
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
  if (tab.type !== 'chat' && tab.type !== 'collection' && tab.type !== 'flow' && tab.type !== 'tool' && tab.type !== 'project') return
  if (props.isMobile) {
    openRenameSheet(tab.id, tab.type, tab.entityId, tab.type === 'tool' ? (tab.customName || '') : (tab.displayName || ''))
    return
  }
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
    if (tabType === 'collection') {
      await updateCollection(parseInt(entityId, 10), { name: newName })
    } else if (tabType === 'project') {
      await updateProject(entityId, { name: newName })
    } else if (tabType === 'chat') {
      const response = await fetch(`/api/chats/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
      if (!response.ok) throw new Error(await response.text())
    } else if (tabType === 'flow') {
      const response = await fetch(`/api/flows/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
      if (!response.ok) throw new Error(await response.text())
    }
    updateTabName(tabId, newName)
  } catch (err) {
    reportActionError("Couldn't rename item.", err)
    return
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

// Reads per list still in flight: a startup read and a reconnect read can
// overlap, and the list is loading until the last of them settles.
const readsInFlight = { savedViews: 0, tools: 0 }

async function loadSavedViews() {
  readsInFlight.savedViews++
  loadingState.value.savedViews.loading = true
  try {
    savedViews.value = await getSavedViews()
    loadingState.value.savedViews.error = false
  } catch (error) {
    console.error('Failed to load saved views:', error)
    loadingState.value.savedViews.error = true
  } finally {
    loadingState.value.savedViews.loading = --readsInFlight.savedViews > 0
    settleSidebarLoad()
  }
}

// Seed orphaned pins (provider removed from config, dropped from the live tool
// list) into the lookup maps using the persisted pin metadata, so they still
// show their provider identity and read as "not configured". Never overrides a
// live entry.
function mergePinFallbacks(toolsMap: Map<string, any>, availabilityMap: Map<string, string>, needsSetup: Set<string> = new Set()) {
  for (const pin of pinnedTools.value as any[]) {
    const fallback = needsSetup.has(pin.full_tool_id) ? 'needs_setup' : 'unconfigured'
    if (!toolsMap.has(pin.full_tool_id)) {
      toolsMap.set(pin.full_tool_id, {
        full_tool_id: pin.full_tool_id,
        provider_id: pin.provider_id,
        provider_name: pin.provider_name,
        task_types: pin.task_types || [],
        availability: fallback,
      })
    }
    if (!availabilityMap.has(pin.full_tool_id)) {
      availabilityMap.set(pin.full_tool_id, fallback)
    }
  }
}

async function loadPinnedTools() {
  readsInFlight.tools++
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
    loadingState.value.tools.loading = --readsInFlight.tools > 0
    settleSidebarLoad()
  }
}

async function loadToolAvailability() {
  try {
    const { providers, tools } = await fetchProvidersAndTools()
    const availabilityMap = new Map<string, string>()
    const toolsMap = new Map<string, any>()
    for (const tool of tools) {
      availabilityMap.set(tool.full_tool_id, tool.availability || 'available')
      toolsMap.set(tool.full_tool_id, tool)
    }
    // Tools a connected provider knows about but that can't run yet (missing
    // models/nodes — STP tool_status). Unavailable, but the pin should say why.
    const needsSetup = new Set<string>()
    for (const p of providers || []) {
      for (const tid of (p as any).needs_setup_tool_ids || []) needsSetup.add(`${p.provider_id}:${tid}`)
    }
    mergePinFallbacks(toolsMap, availabilityMap, needsSetup)
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
  const updatedIds = new Set(data.saved_views.map(v => v.id))
  savedViews.value = [...savedViews.value.filter(v => !updatedIds.has(v.id)), ...data.saved_views].sort((a, b) => a.display_order - b.display_order)
})

// Tool pin events
on('tool_pinned', () => loadPinnedTools())
on('tool_unpinned', (data) => {
  pinnedTools.value = pinnedTools.value.filter(t => t.full_tool_id !== data.full_tool_id)
  reconcileToolPins(pinnedTools.value)
})

// Chat events - update tab names, remove tabs on deletion
on('chat_updated', (data) => {
  const chat = data.chat
  if (!chat?.id) return
  if (chat.name) updateTabName(`chat:${chat.id}`, chat.name)
  // Moved to another project: the row follows the chat to its new context.
  if ('project_id' in chat) {
    const key = String(chat.id)
    const projectId = chat.project_id ?? null
    const meta = chatMetadata.value.get(key)
    if (meta && meta.project_id !== projectId) {
      chatMetadata.value.set(key, { ...meta, project_id: projectId })
      chatMetadata.value = new Map(chatMetadata.value)
    }
    setTabContext(`chat:${key}`, projectId)
    ensureProjectName(projectId)
    followOpenEntity('chat', key, projectId)
  }
})

on('chat_deleted', (data) => {
  const tabId = `chat:${data.chat_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]), visibleTabIds.value)
    if (next) navigateToTab(next)
    else router.push({ name: 'browse' })
  }
  removeTabByEntity('chat', String(data.chat_id))
  removeRecentEntity('chat', String(data.chat_id))
})

// Flow events - update tab names, remove tabs on deletion
on('flow_updated', (data) => {
  const flow = data.flow
  if (!flow?.id) return
  if (flow.name) updateTabName(`flow:${flow.id}`, flow.name)
  if ('project_id' in flow) {
    const projectId = flow.project_id ?? null
    if (flowMetadata.value.get(String(flow.id)) !== projectId) {
      flowMetadata.value.set(String(flow.id), projectId)
      flowMetadata.value = new Map(flowMetadata.value)
    }
    setTabContext(`flow:${flow.id}`, projectId)
    followOpenEntity('flow', String(flow.id), projectId)
  }
})

on('flow_deleted', (data) => {
  const tabId = `flow:${data.flow_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]), visibleTabIds.value)
    if (next) navigateToTab(next)
    else router.push({ name: 'flows' })
  }
  removeTabByEntity('flow', String(data.flow_id))
  removeRecentEntity('flow', String(data.flow_id))
})

// Collection events - open new collections as tabs, update names, remove on deletion
on('collection_created', (data) => {
  if (data.collection) {
    addTab('collection', String(data.collection.id), data.collection.name)
    applyCollectionUpdate(data.collection)
  }
})

on('collection_updated', (data) => {
  if (data.collection) {
    applyCollectionUpdate(data.collection)
  }
})

on('collection_items_changed', (data) => {
  if (data.collection) {
    applyCollectionUpdate(data.collection)
  }
})

on('collection_deleted', (data) => {
  const tabId = `collection:${data.collection_id}`
  const closingTab = allTabs.value.find(t => t.id === tabId)
  if (closingTab && isTabActive(closingTab)) {
    const next = findNextTab(new Set([tabId]), visibleTabIds.value)
    if (next) navigateToTab(next)
    else router.push({ name: 'browse' })
  }
  collectionMetadata.value.delete(String(data.collection_id))
  collectionMetadata.value = new Map(collectionMetadata.value)
  removeTabByEntity('collection', String(data.collection_id))
  removeRecentEntity('collection', String(data.collection_id))
})

// Chat generation tracking
on('project_updated', (data) => {
  const project = data.project
  if (project) rememberProject(project)
  if (!project?.id) return
  const id = String(project.id)
  const name = project.name || 'Untitled Project'
  projectNames.value.set(id, name)
  projectNames.value = new Map(projectNames.value)
  // Update tab displayName for project tabs and projectName on tool/chat/collection tabs
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

on('project_created', () => refreshProjects())
on('project_deleted', async (data) => {
  savedViews.value = savedViews.value.filter(v => v.project_id !== data.project_id)
  await handleProjectDeletedBroadcast(data.project_id, router, route)
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
    if (['browse', 'trash', 'saved-view', 'collections', 'chats', 'flows', 'all-tools', 'projects'].includes(name) || name?.startsWith('project-')) {
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
              addTab('tool', fullToolId, undefined, projectId, project.name || 'Untitled Project', instanceId)
            }
          }).catch(() => {})
        }
      } else {
        const tab = addTab('tool', fullToolId, toolDisplayName, undefined, undefined, instanceId)
        markTabActivated(tab.id)
      }
    } else if (name === 'chat' && params.id) {
      const chatId = String(params.id)
      const tab = addTab('chat', chatId)
      setTabContext(tab.id, route.meta.workingProjectId ?? null)
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
    } else if (name === 'collection-detail' && params.id) {
      const colId = String(params.id)
      const tab = addTab('collection', colId)
      setTabContext(tab.id, route.meta.workingProjectId ?? null)
      // Fetch collection data for name and metadata
      if (!tab.displayName || tab.displayName === colId || !getCollectionMetadata(colId)) {
        getCollection(parseInt(colId, 10)).then(col => {
          if (col) {
            updateTabName(tab.id, col.name || '')
            collectionMetadata.value.set(colId, {
              cover_media_id: null,
              item_count: col.asset_count || 0,
              section_count: col.sections?.length || 0,
              project_id: col.project_id ?? null,
              preview_items: (col.sections || [])
                .flatMap((section: any) => section.items || [])
                .slice(0, 4)
            })
            collectionMetadata.value = new Map(collectionMetadata.value)
            ensureProjectName(col.project_id ?? null)
          }
        }).catch(() => {})
      }
    } else if (name === 'edit-image' && params.assetId) {
      // The editor route carries only the Asset, so the thumbnail
      // and name come from the asset's head revision.
      const assetId = String(params.assetId)
      const tab = addEditorTab(assetId)
      setTabContext(tab.id, activeProjectId.value, true)
      // The shelf ranks by recency, so every visit counts as a touch.
      markTabActivated(tab.id)
      fetch(`/api/assets/${assetId}`).then(r => r.ok ? r.json() : null).then(data => {
        if (!data) return
        if (data.media?.id != null) updateEditorMedia(tab.id, String(data.media.id))
        if (data.asset?.title) updateTabName(tab.id, data.asset.title)
      }).catch(() => {})
    } else if (name === 'lineage' && params.mediaId) {
      const tab = addTab('lineage', String(params.mediaId), 'Lineage')
      setTabContext(tab.id, activeProjectId.value, true)
    } else if (name === 'flow' && params.id) {
      const flowId = String(params.id)
      const tab = addTab('flow', flowId)
      setTabContext(tab.id, route.meta.workingProjectId ?? null)
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
  collectionMetadata.value = new Map()
  chatMetadata.value = new Map()
  flowMetadata.value = new Map()
  projectNames.value = new Map()
  chatMetadataLoaded.clear()
  chatMetadataLoading.clear()
  refreshProjects()
  loadAllCollectionMetadata()
  loadAllChatMetadata()
  await fetchProvidersAndTools(true)
  await Promise.all([loadPinnedTools(), loadSavedViews()])
}

onMounted(() => {
  // Startup has usually just loaded the project list for this scope.
  refreshProjects({ maxAgeMs: 30_000 })
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

// Load chat/collection metadata whenever tabs change (covers initial load, new tabs, profile switch)
watch(allTabs, () => loadAllChatMetadata(), { immediate: true })
watch(allTabs, () => loadAllCollectionMetadata(), { immediate: true })
watch(allTabs, () => {
  for (const tab of allTabs.value) {
    if (tab.type === 'flow' && !flowMetadata.value.has(tab.entityId)) {
      flowMetadata.value.set(tab.entityId, tab.projectId)
      fetch(`/api/flows/${tab.entityId}`).then(r => r.ok ? r.json() : null).then(flow => {
        if (flow) { flowMetadata.value.set(tab.entityId, flow.project_id ?? null); flowMetadata.value = new Map(flowMetadata.value); setTabContext(tab.id, flow.project_id ?? null) }
      }).catch(() => {})
    }
  }
}, { immediate: true })


onUnmounted(() => {
  sidebarUnmounted = true
  sidebarRetry.stop()
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
