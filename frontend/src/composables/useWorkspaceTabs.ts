import { ref, computed, readonly, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { makeProfileKey } from '../utils/storageKeys'
import { useProvidersApi } from './useProvidersApi'
import { isSettingsLoaded } from '../appConfig'
import { recordEntityVisit, updateRecentEntityName, type RecentEntityType } from './useRecentEntities'

export type WorkspaceTabType = 'tool' | 'chat' | 'board' | 'editor' | 'lineage' | 'project' | 'flow'

export interface WorkspaceTab {
  id: string              // 'tool:{fullToolId}', 'chat:{id}', 'board:{id}', 'editor:{editorId}'
  type: WorkspaceTabType
  entityId: string        // fullToolId, chatId, boardId, or editorId (unique instance)
  pinned: boolean
  displayOrder: number
  displayName: string     // cached name for rendering without extra API calls
  editorMediaId?: string  // Only for editor tabs: the current mediaId being edited
  projectId?: number      // For project-scoped tool tabs: the project this instance belongs to
  projectName?: string    // Cached project name for display
}

function getStorageKey(): string {
  return makeProfileKey('workspace_tabs')
}

function getLastLibraryRouteKey(): string {
  return makeProfileKey('workspace_tabs', 'last_library_route')
}

// Singleton state
const tabs = ref<WorkspaceTab[]>([])
let nextDisplayOrder = 0

// Recently closed tabs stack (in-memory only, not persisted)
const recentlyClosed: WorkspaceTab[] = []
const MAX_RECENTLY_CLOSED = 20

// Editor instance counter - initialized from existing tabs
let editorIdCounter = 0

function initEditorIdCounter() {
  // Migrate old-format editor tabs (entityId was mediaId, no editorMediaId)
  for (const tab of tabs.value) {
    if (tab.type === 'editor' && !tab.editorMediaId) {
      // Old format: entityId is the mediaId. Migrate to new format.
      const oldMediaId = tab.entityId
      const newEditorId = String(editorIdCounter++)
      tab.editorMediaId = oldMediaId
      tab.entityId = newEditorId
      tab.id = `editor:${newEditorId}`
    }
  }
  // Set counter past any existing editor IDs
  for (const tab of tabs.value) {
    if (tab.type === 'editor') {
      const num = parseInt(tab.entityId, 10)
      if (!isNaN(num) && num >= editorIdCounter) {
        editorIdCounter = num + 1
      }
    }
  }
}

// Flag to prevent saving during profile/settings reload
let isReloadingProfile = false

// Flag to prevent saving until settings are loaded (appModifier set)
let settingsReady = false

// --- Persistence ---

function loadFromStorage() {
  try {
    const stored = localStorage.getItem(getStorageKey())
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed)) {
        tabs.value = parsed
        // Restore nextDisplayOrder
        nextDisplayOrder = parsed.reduce((max: number, t: WorkspaceTab) => Math.max(max, t.displayOrder), 0) + 1
        initEditorIdCounter()
        return
      }
    }
    // Only clear tabs if we actually have a valid key (settings loaded)
    if (settingsReady) {
      tabs.value = []
      nextDisplayOrder = 0
    }
  } catch (err) {
    console.error('[useWorkspaceTabs] Failed to load from storage:', err)
    if (settingsReady) {
      tabs.value = []
      nextDisplayOrder = 0
    }
  }
}

function saveToStorage() {
  if (isReloadingProfile || !settingsReady) return
  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(tabs.value))
  } catch (err) {
    console.error('[useWorkspaceTabs] Failed to save to storage:', err)
  }
}

// Try initial load (may work if settings already loaded, e.g. cached)
if (isSettingsLoaded()) {
  settingsReady = true
  loadFromStorage()
}

// Watch for changes and sync to localStorage
watch(tabs, saveToStorage, { deep: true })

// Reload when settings become available (appModifier is now set, key is correct)
if (typeof window !== 'undefined') {
  window.addEventListener('settings-loaded', () => {
    settingsReady = true
    isReloadingProfile = true
    try {
      loadFromStorage()
    } finally {
      isReloadingProfile = false
    }
  })

  window.addEventListener('profile-changed', () => {
    isReloadingProfile = true
    try {
      loadFromStorage()
    } finally {
      isReloadingProfile = false
    }
  })

}

// --- Helpers ---

function makeTabId(type: WorkspaceTabType, entityId: string, projectId?: number): string {
  if (projectId && type === 'tool') return `${type}:${entityId}:project:${projectId}`
  return `${type}:${entityId}`
}

// --- Composable ---

export function useWorkspaceTabs() {
  /**
   * Get the last library route (for navigating when closing last tab).
   */
  function getLastLibraryRoute(): string {
    return localStorage.getItem(getLastLibraryRouteKey()) || '/browse'
  }

  function setLastLibraryRoute(path: string) {
    try {
      localStorage.setItem(getLastLibraryRouteKey(), path)
    } catch {}
  }

  /**
   * Allocate a new unique editor instance ID.
   */
  function nextEditorId(): string {
    return String(editorIdCounter++)
  }

  /**
   * Add a tab (idempotent by type+entityId+projectId). Returns the tab.
   */
  function addTab(type: WorkspaceTabType, entityId: string, displayName?: string, projectId?: number, projectName?: string): WorkspaceTab {
    // Every entity open flows through here (the sidebar's route watcher), so
    // this is the one place cross-entity recents get recorded.
    recordEntityVisit(type as RecentEntityType, entityId, displayName)
    const id = makeTabId(type, entityId, projectId)
    const existing = tabs.value.find(t => t.id === id)
    if (existing) {
      // Update displayName if provided and different
      if (displayName !== undefined && displayName !== existing.displayName) {
        existing.displayName = displayName
      }
      if (projectName && projectName !== existing.projectName) {
        existing.projectName = projectName
      }
      return existing
    }

    const tab: WorkspaceTab = {
      id,
      type,
      entityId,
      pinned: false,
      displayOrder: nextDisplayOrder++,
      displayName: displayName !== undefined ? displayName : entityId,
      ...(projectId ? { projectId, projectName: projectName || '' } : {})
    }
    tabs.value = [...tabs.value, tab]
    return tab
  }

  /**
   * Add an editor tab with a unique instance ID. Returns the tab.
   */
  function addEditorTab(editorId: string, mediaId?: string): WorkspaceTab {
    const id = makeTabId('editor', editorId)
    const existing = tabs.value.find(t => t.id === id)
    if (existing) {
      if (mediaId && existing.editorMediaId !== mediaId) {
        existing.editorMediaId = mediaId
        tabs.value = [...tabs.value]
      }
      return existing
    }

    const tab: WorkspaceTab = {
      id,
      type: 'editor',
      entityId: editorId,
      pinned: false,
      displayOrder: nextDisplayOrder++,
      displayName: 'Edit Image',
      editorMediaId: mediaId
    }
    tabs.value = [...tabs.value, tab]
    return tab
  }

  /**
   * Update the mediaId for an editor tab (e.g. when dropping a new image onto it).
   */
  function updateEditorMedia(tabId: string, mediaId: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (!tab || tab.type !== 'editor') return
    tab.editorMediaId = mediaId
    tabs.value = [...tabs.value]
  }

  /**
   * Update the thumbnail media for a lineage tab when focus changes.
   */
  function updateLineageFocus(mediaId: string, focusedMediaId: string) {
    const id = makeTabId('lineage', mediaId)
    const tab = tabs.value.find(t => t.id === id)
    if (!tab || tab.type !== 'lineage') return
    if (tab.editorMediaId === focusedMediaId) return
    tab.editorMediaId = focusedMediaId
    tabs.value = [...tabs.value]
  }

  /**
   * Find the best tab to navigate to after closing a tab (or set of tabs).
   * Returns the most recently added remaining tab, or null if no tabs remain.
   * `excludeIds` is the set of tab ids being removed.
   */
  function findNextTab(excludeIds: Set<string>): WorkspaceTab | null {
    const remaining = tabs.value.filter(t => !excludeIds.has(t.id))
    if (remaining.length === 0) return null
    // Return the most recently added tab (highest displayOrder)
    return remaining.reduce((best, t) => t.displayOrder > best.displayOrder ? t : best, remaining[0])
  }

  /**
   * Remove a tab by id. Pushes to recently-closed stack for reopen support.
   */
  function removeTab(tabId: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (tab) {
      recentlyClosed.push({ ...tab })
      if (recentlyClosed.length > MAX_RECENTLY_CLOSED) recentlyClosed.shift()
    }
    tabs.value = tabs.value.filter(t => t.id !== tabId)
  }

  /**
   * Remove a tab by entity type and id.
   */
  function removeTabByEntity(type: WorkspaceTabType, entityId: string) {
    const id = makeTabId(type, entityId)
    const tab = tabs.value.find(t => t.id === id)
    if (tab) {
      recentlyClosed.push({ ...tab })
      if (recentlyClosed.length > MAX_RECENTLY_CLOSED) recentlyClosed.shift()
    }
    tabs.value = tabs.value.filter(t => t.id !== id)
  }

  /**
   * Pop the most recently closed tab and re-add it. Returns the tab or null.
   */
  function reopenLastClosed(): WorkspaceTab | null {
    const closed = recentlyClosed.pop()
    if (!closed) return null
    // Don't re-add if a tab with the same id already exists
    if (tabs.value.some(t => t.id === closed.id)) return closed
    closed.displayOrder = nextDisplayOrder++
    closed.pinned = false
    tabs.value = [...tabs.value, closed]
    return closed
  }

  /**
   * Get the next tab in display order after the given tab id (cycles).
   */
  function getNextTab(activeTabId: string): WorkspaceTab | null {
    const sorted = allTabs.value
    if (sorted.length === 0) return null
    const idx = sorted.findIndex(t => t.id === activeTabId)
    if (idx === -1) return sorted[0]
    return sorted[(idx + 1) % sorted.length]
  }

  /**
   * Get the previous tab in display order before the given tab id (cycles).
   */
  function getPrevTab(activeTabId: string): WorkspaceTab | null {
    const sorted = allTabs.value
    if (sorted.length === 0) return null
    const idx = sorted.findIndex(t => t.id === activeTabId)
    if (idx === -1) return sorted[sorted.length - 1]
    return sorted[(idx - 1 + sorted.length) % sorted.length]
  }

  /**
   * Pin a tab. For tool tabs, also calls the backend pin API.
   */
  async function pinTab(tabId: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (!tab || tab.pinned) return

    if (tab.type === 'tool') {
      const { pinProviderTool } = useProvidersApi()
      try {
        await pinProviderTool(tab.entityId)
      } catch (err) {
        console.error('[useWorkspaceTabs] Failed to pin tool:', err)
        return
      }
    }

    tab.pinned = true
    // Trigger reactivity
    tabs.value = [...tabs.value]
  }

  /**
   * Unpin a tab. For tool tabs, also calls the backend unpin API.
   */
  async function unpinTab(tabId: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (!tab || !tab.pinned) return

    if (tab.type === 'tool') {
      const { unpinProviderTool } = useProvidersApi()
      try {
        await unpinProviderTool(tab.entityId)
      } catch (err) {
        console.error('[useWorkspaceTabs] Failed to unpin tool:', err)
        return
      }
    }

    tab.pinned = false
    // Trigger reactivity
    tabs.value = [...tabs.value]
  }

  /**
   * Update a tab's display name (e.g., from WebSocket rename events).
   */
  function updateTabName(tabId: string, name: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (tab && tab.displayName !== name) {
      tab.displayName = name
      tabs.value = [...tabs.value]
      updateRecentEntityName(tab.type as RecentEntityType, tab.entityId, name)
    }
  }

  /**
   * Close all unpinned tabs.
   */
  function closeAllUnpinned() {
    tabs.value = tabs.value.filter(t => t.pinned)
  }

  /**
   * Close all tabs except the specified one.
   */
  function closeOthers(tabId: string) {
    tabs.value = tabs.value.filter(t => t.id === tabId || t.pinned)
  }

  /**
   * Check if a tab exists for the given type and entityId.
   */
  function hasTab(type: WorkspaceTabType, entityId: string): boolean {
    return tabs.value.some(t => t.id === makeTabId(type, entityId))
  }

  /**
   * Get a specific tab by type and entityId.
   */
  function getTab(type: WorkspaceTabType, entityId: string): WorkspaceTab | undefined {
    return tabs.value.find(t => t.id === makeTabId(type, entityId))
  }

  /**
   * Reorder tabs within a group (pinned or unpinned).
   */
  function moveTab(fromIndex: number, toIndex: number, group: 'pinned' | 'open') {
    const groupTabs = group === 'pinned' ? pinnedTabs.value : openTabs.value

    // Allow toIndex to be equal to groupTabs.length (drop after last item)
    if (fromIndex < 0 || fromIndex >= groupTabs.length) return
    if (toIndex < 0 || toIndex > groupTabs.length) return
    if (fromIndex === toIndex) return

    // Reorder within the group. `reordered` is in DISPLAY order (the same order
    // the user sees the tabs), regardless of how displayOrder is sorted.
    const reordered = [...groupTabs]
    const [moved] = reordered.splice(fromIndex, 1)

    // Adjust toIndex if we removed an item before the drop position
    let adjustedToIndex = toIndex
    if (fromIndex < toIndex) {
      adjustedToIndex = toIndex - 1
    }

    reordered.splice(adjustedToIndex, 0, moved)

    // Reassign displayOrder to all tabs. Pinned tabs come first (lower values),
    // then open tabs. CRITICAL: pinnedTabs sorts displayOrder ASCENDING while
    // openTabs sorts DESCENDING, so the writeback direction must match the
    // group's sort or the displayed order gets inverted on every drag.
    const orderedPinned = group === 'pinned' ? reordered : pinnedTabs.value
    const orderedOpen = group === 'open' ? reordered : openTabs.value

    let order = 0
    const assign = (tab: WorkspaceTab) => {
      const t = tabs.value.find(tt => tt.id === tab.id)
      if (t) t.displayOrder = order++
    }

    // Pinned: ascending sort, so assign top-to-bottom (top = lowest displayOrder).
    orderedPinned.forEach(assign)
    // Open: descending sort, so assign bottom-to-top (top = highest displayOrder).
    for (let i = orderedOpen.length - 1; i >= 0; i--) {
      assign(orderedOpen[i])
    }

    // Force reactivity by creating a completely new array reference
    tabs.value = tabs.value.slice()

    // If reordering pinned tools, also update backend
    if (group === 'pinned') {
      const pinnedToolIds = reordered.filter(t => t.type === 'tool').map(t => t.entityId)
      if (pinnedToolIds.length > 0) {
        const { reorderPinnedTools } = useProvidersApi()
        reorderPinnedTools(pinnedToolIds).catch(err => {
          console.error('[useWorkspaceTabs] Failed to reorder pinned tools:', err)
        })
      }
    }
  }

  /**
   * Reconcile tool pins with backend API.
   * Called on init and when tool_pinned/tool_unpinned events fire.
   */
  async function reconcileToolPins(pinnedToolsFromApi: any[]) {
    const apiPinnedIds = new Set(pinnedToolsFromApi.map(t => t.full_tool_id))

    // Add pinned tabs for tools that are pinned in API but not in tabs
    for (const tool of pinnedToolsFromApi) {
      const id = makeTabId('tool', tool.full_tool_id)
      const existing = tabs.value.find(t => t.id === id)
      if (existing) {
        if (!existing.pinned) existing.pinned = true
        if (existing.displayName !== tool.name) existing.displayName = tool.name
      } else {
        tabs.value.push({
          id,
          type: 'tool',
          entityId: tool.full_tool_id,
          pinned: true,
          displayOrder: nextDisplayOrder++,
          displayName: tool.name
        })
      }
    }

    // Unpin tool tabs that are no longer pinned in API
    for (const tab of tabs.value) {
      if (tab.type === 'tool' && tab.pinned && !apiPinnedIds.has(tab.entityId)) {
        tab.pinned = false
      }
    }

    tabs.value = [...tabs.value]
  }

  // --- Computed ---

  const pinnedTabs = computed(() => {
    return tabs.value
      .filter(t => t.pinned)
      .sort((a, b) => a.displayOrder - b.displayOrder)
  })

  const openTabs = computed(() => {
    return tabs.value
      .filter(t => !t.pinned)
      .sort((a, b) => b.displayOrder - a.displayOrder)
  })

  const allTabs = computed(() => {
    return tabs.value.sort((a, b) => a.displayOrder - b.displayOrder)
  })

  return {
    tabs: readonly(tabs),
    pinnedTabs,
    openTabs,
    allTabs,
    addTab,
    addEditorTab,
    updateEditorMedia,
    updateLineageFocus,
    nextEditorId,
    findNextTab,
    removeTab,
    removeTabByEntity,
    pinTab,
    unpinTab,
    updateTabName,
    closeAllUnpinned,
    closeOthers,
    hasTab,
    getTab,
    moveTab,
    reopenLastClosed,
    getNextTab,
    getPrevTab,
    reconcileToolPins,
    getLastLibraryRoute,
    setLastLibraryRoute,
    makeTabId
  }
}
