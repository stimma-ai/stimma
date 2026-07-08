import { ref, computed, readonly, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { makeProfileKey, makeGlobalKey, makeToolProfileKey, makeToolDbKey } from '../utils/storageKeys'
import { listBlobKeys, getBlob, putBlob, deleteBlob } from '../utils/blobStorage'
import { getCurrentProfileId, getCurrentDbGuid } from './useProfile'
import { useProvidersApi } from './useProvidersApi'
import { isSettingsLoaded } from '../appConfig'
import { recordEntityVisit, updateRecentEntityName, type RecentEntityType } from './useRecentEntities'

export type WorkspaceTabType = 'tool' | 'chat' | 'board' | 'editor' | 'lineage' | 'project' | 'flow'

export interface WorkspaceTab {
  id: string              // 'tool:{fullToolId}[:project:{p}]:i:{K}', 'chat:{id}', 'board:{id}', 'editor:{editorId}'
  type: WorkspaceTabType
  entityId: string        // fullToolId, chatId, boardId, or editorId (unique instance)
  pinned: boolean
  displayOrder: number
  displayName: string     // cached name for rendering without extra API calls
  editorMediaId?: string  // Only for editor tabs: the current mediaId being edited
  projectId?: number      // For project-scoped tool tabs: the project this instance belongs to
  projectName?: string    // Cached project name for display
  instanceId?: string     // Tool tabs: instance discriminator; every tool tab is an instance
  customName?: string     // Tool tabs: user-given name (window title); displayName stays the tool name
  lastActivatedAt?: number // Tool tabs: last time this tab was navigated to (instance resolution)
  feedScope?: string      // Tool tabs: tool-side token of the job-feed generatorInstanceId
}

/**
 * Scoped tool id for storage keys: the string handed to makeToolProfileKey /
 * makeToolDbKey. Mirrors ToolView's scopedToolId(): project suffix first,
 * then the instance suffix.
 */
export function toolInstanceScopedId(fullToolId: string, projectId?: number | null, instanceId?: string | null): string {
  const proj = projectId ? `__project_${projectId}` : ''
  const inst = instanceId ? `__i_${instanceId}` : ''
  return `${fullToolId}${proj}${inst}`
}

/**
 * Tool-side token of a tool instance's generatorInstanceId (job feed key).
 * Matches ToolView's toolIdForStorage (colons → underscores + suffixes).
 */
export function toolInstanceFeedScope(fullToolId: string, projectId?: number | null, instanceId?: string | null): string {
  return toolInstanceScopedId(fullToolId, projectId, instanceId).replace(/:/g, '_')
}

/**
 * Router location for a tool instance. The one way to build tool routes so
 * project_id and instance never get dropped.
 */
export function toolInstanceRoute(fullToolId: string, projectId?: number | null, instanceId?: string | null, extraQuery?: Record<string, string>) {
  return {
    name: 'tool' as const,
    params: { fullToolId },
    query: {
      ...(projectId ? { project_id: String(projectId) } : {}),
      ...(instanceId ? { instance: String(instanceId) } : {}),
      ...(extraQuery || {})
    }
  }
}

/** Router location for an existing tool tab. */
export function toolTabRoute(tab: WorkspaceTab, extraQuery?: Record<string, string>) {
  return toolInstanceRoute(tab.entityId, tab.projectId, tab.instanceId, extraQuery)
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

// Tool instance counter — persisted and strictly monotonic. Never derived
// downward from live tabs: a closed instance's storage keys survive until the
// next startup sweep, so reusing its id would resurrect leftover state.
// GLOBAL (not per-profile): the startup sweep can't attribute db-guid-scoped
// keys to a profile, so ids must be unique across profiles or one profile's
// live id would shield another profile's orphans forever.
function getInstanceCounterKey(): string {
  return makeGlobalKey('workspace_tabs', 'tool_instance_counter')
}

function nextToolInstanceId(): string {
  let counter = 0
  try {
    counter = parseInt(localStorage.getItem(getInstanceCounterKey()) || '0', 10) || 0
  } catch {}
  // Defensive: never mint below an id already referenced by a live tab
  for (const tab of tabs.value) {
    if (tab.type === 'tool' && tab.instanceId) {
      const num = parseInt(tab.instanceId, 10)
      if (!isNaN(num) && num >= counter) counter = num + 1
    }
  }
  try {
    localStorage.setItem(getInstanceCounterKey(), String(counter + 1))
  } catch {}
  return String(counter)
}

// Db-guid-scoped key suffixes that are per-instance (used by the migration;
// profile-scoped parts are handled inline below, and the startup sweep in
// utils/storageCleanup.ts matches the __i_{K} token instead of a part list).
const INSTANCE_DB_KEY_PARTS = ['video_images', 'remix'] as const

/**
 * One-time migration: pre-instance tool tabs (no instanceId) become instances.
 * Storage keys move from the (tool, project)-scoped names to instance-scoped
 * names; `_global`/`_ui` (previously shared per bare tool) are copied into
 * each instance of that tool. feedScope keeps the legacy token so the job
 * feed history stays attached.
 */
function migrateToolTabsToInstances() {
  if (!getCurrentProfileId()) return
  const legacyToolTabs = tabs.value.filter(t => t.type === 'tool' && !t.instanceId)
  if (legacyToolTabs.length === 0) return

  const copyKey = (storage: Storage, oldKey: string, newKey: string) => {
    try {
      const val = storage.getItem(oldKey)
      if (val !== null && storage.getItem(newKey) === null) storage.setItem(newKey, val)
    } catch {}
  }

  const legacyGlobalKeysToDelete = new Set<string>()
  const hasDbGuid = !!getCurrentDbGuid()
  const blobPairs: Array<{ bareToolId: string; newScoped: string }> = []

  for (const tab of legacyToolTabs) {
    const instanceId = nextToolInstanceId()
    const oldScoped = toolInstanceScopedId(tab.entityId, tab.projectId)
    const newScoped = toolInstanceScopedId(tab.entityId, tab.projectId, instanceId)

    for (const part of ['state', 'active_preset', 'collapsed_groups', 'ai_prompt_expanded']) {
      copyKey(localStorage, makeToolProfileKey(oldScoped, part), makeToolProfileKey(newScoped, part))
      try { localStorage.removeItem(makeToolProfileKey(oldScoped, part)) } catch {}
    }
    // _global/_ui were keyed by bare tool id (shared across the tool's global
    // and project-scoped tabs) — copy into this instance, delete afterwards.
    for (const part of ['global', 'ui']) {
      const oldKey = makeToolProfileKey(tab.entityId, part)
      copyKey(localStorage, oldKey, makeToolProfileKey(newScoped, part))
      legacyGlobalKeysToDelete.add(oldKey)
    }
    if (hasDbGuid) {
      for (const part of INSTANCE_DB_KEY_PARTS) {
        copyKey(localStorage, makeToolDbKey(oldScoped, part), makeToolDbKey(newScoped, part))
        try { localStorage.removeItem(makeToolDbKey(oldScoped, part)) } catch {}
      }
      blobPairs.push({ bareToolId: tab.entityId, newScoped })
    }

    tab.instanceId = instanceId
    tab.feedScope = toolInstanceFeedScope(tab.entityId, tab.projectId) // legacy token: keeps feed history
    tab.id = makeTabId('tool', tab.entityId, tab.projectId, instanceId)
    // Stamp so the duplicate prune below never mistakes a migrated original
    // for spurious-mint trash.
    tab.lastActivatedAt = Date.now()
  }

  for (const key of legacyGlobalKeysToDelete) {
    try { localStorage.removeItem(key) } catch {}
  }
  tabs.value = [...tabs.value]

  // Persist the migrated blob SYNCHRONOUSLY, bypassing the isReloadingProfile
  // gate on the watcher-driven save: the legacy keys were just moved, so a
  // crash before the tabs blob lands would leave a blob without instanceIds
  // and orphaned __i_ keys (which the startup sweep would then purge).
  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(tabs.value))
  } catch (err) {
    console.error('[useWorkspaceTabs] Failed to persist migrated tabs:', err)
  }

  // Mask/paint blobs live in IndexedDB under BARE tool ids (they predate even
  // project scoping); copy them into each migrated instance, best-effort.
  void migrateInstanceBlobs(blobPairs)
}

async function migrateInstanceBlobs(pairs: Array<{ bareToolId: string; newScoped: string }>) {
  const migratedBare = new Set<string>()
  for (const { bareToolId, newScoped } of pairs) {
    try {
      const oldMaskKey = makeToolDbKey(bareToolId, 'mask')
      const mask = await getBlob(oldMaskKey)
      if (mask !== null) await putBlob(makeToolDbKey(newScoped, 'mask'), mask)

      const paintKeys = await listBlobKeys(makeToolDbKey(bareToolId, 'paint'))
      for (const oldKey of paintKeys) {
        // Suffix after '..._paint' is '_{slotIndex}'
        const suffix = oldKey.slice(makeToolDbKey(bareToolId, 'paint').length)
        if (!/^_\d+$/.test(suffix)) continue
        const paint = await getBlob(oldKey)
        if (paint !== null) await putBlob(makeToolDbKey(newScoped, 'paint') + suffix, paint)
      }
      migratedBare.add(bareToolId)
    } catch { /* best-effort */ }
  }
  // Delete bare-key originals only after every instance of that tool got its copy.
  for (const bareToolId of migratedBare) {
    try {
      await deleteBlob(makeToolDbKey(bareToolId, 'mask'))
      const paintKeys = await listBlobKeys(makeToolDbKey(bareToolId, 'paint'))
      for (const key of paintKeys) {
        if (/^_\d+$/.test(key.slice(makeToolDbKey(bareToolId, 'paint').length))) {
          await deleteBlob(key)
        }
      }
    } catch { /* best-effort */ }
  }
}

/**
 * Self-heal duplicate tool tabs created by the (fixed) pre-load pin-reconcile
 * race. A tab a user actually opened is always navigated to, which stamps
 * lastActivatedAt; renames set customName. Within each (tool, project) group,
 * never-activated unnamed instance tabs are spurious beyond the first —
 * keep the oldest (lowest displayOrder), drop the rest.
 */
function pruneNeverActivatedDuplicates() {
  const groups = new Map<string, WorkspaceTab[]>()
  for (const tab of tabs.value) {
    if (tab.type !== 'tool' || !tab.instanceId || tab.customName || tab.lastActivatedAt) continue
    const key = `${tab.entityId}::${tab.projectId ?? ''}`
    const list = groups.get(key) || []
    list.push(tab)
    groups.set(key, list)
  }
  const drop = new Set<string>()
  for (const list of groups.values()) {
    if (list.length <= 1) continue
    list.sort((a, b) => a.displayOrder - b.displayOrder)
    for (const tab of list.slice(1)) drop.add(tab.id)
  }
  if (drop.size > 0) {
    tabs.value = tabs.value.filter(t => !drop.has(t.id))
    console.log(`[useWorkspaceTabs] pruned ${drop.size} duplicate never-activated tool tabs`)
  }
}

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

// Resolves once tabs have been loaded from storage FOR A REAL PROFILE. The
// router's tool-instance guard awaits this so it never resolves (and mints)
// instances against an empty or wrong-profile tab list. reconcileToolPins
// checks the flag for the same reason: creating a uniquely-id'd instance tab
// against a not-yet-loaded list produces a permanent duplicate.
let tabsLoadedForProfile = false
let markTabsLoaded: () => void = () => {}
const tabsLoaded: Promise<void> = new Promise(resolve => { markTabsLoaded = resolve })

function noteTabsLoaded() {
  if (getCurrentProfileId()) {
    tabsLoadedForProfile = true
    markTabsLoaded()
  }
}

/** Await initial tab load (used by the router guard). */
export function whenTabsReady(): Promise<void> {
  return tabsLoaded
}

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
        migrateToolTabsToInstances()
        pruneNeverActivatedDuplicates()
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
  noteTabsLoaded()
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
      noteTabsLoaded()
    }
  })

  window.addEventListener('profile-changed', () => {
    isReloadingProfile = true
    try {
      loadFromStorage()
    } finally {
      isReloadingProfile = false
      noteTabsLoaded()
    }
  })

}

// --- Helpers ---

export function makeTabId(type: WorkspaceTabType, entityId: string, projectId?: number, instanceId?: string): string {
  if (type === 'tool') {
    const proj = projectId ? `:project:${projectId}` : ''
    const inst = instanceId ? `:i:${instanceId}` : ''
    return `${type}:${entityId}${proj}${inst}`
  }
  return `${type}:${entityId}`
}

/**
 * Tab id for the tool route currently in `route` — the one builder for
 * "which tab is active" checks (App.vue, WorkspaceTabsContextMenu). Returns
 * null when the route isn't a tool route.
 */
export function toolRouteTabId(route: { name?: unknown; params: Record<string, any>; query: Record<string, any> }): string | null {
  if (route.name !== 'tool' || !route.params.fullToolId) return null
  const proj = route.query.project_id ? Number(route.query.project_id) : undefined
  const inst = route.query.instance ? String(route.query.instance) : undefined
  return makeTabId('tool', String(route.params.fullToolId), Number.isFinite(proj) ? proj : undefined, inst)
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
  function addTab(type: WorkspaceTabType, entityId: string, displayName?: string, projectId?: number, projectName?: string, instanceId?: string): WorkspaceTab {
    // Every entity open flows through here (the sidebar's route watcher), so
    // this is the one place cross-entity recents get recorded.
    recordEntityVisit(type as RecentEntityType, entityId, displayName)
    const id = makeTabId(type, entityId, projectId, instanceId)
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
      ...(projectId ? { projectId, projectName: projectName || '' } : {}),
      ...(type === 'tool' && instanceId
        ? { instanceId, feedScope: toolInstanceFeedScope(entityId, projectId, instanceId) }
        : {})
    }
    tabs.value = [...tabs.value, tab]
    return tab
  }

  /**
   * Resolve which instance a GENERIC tool reference should land on (All Tools
   * card, deep link, tool-level send-to/remix/hop): the most recently
   * activated open UNNAMED instance matching (tool, project) exactly, else a
   * freshly minted id. Renaming an instance claims it as a station — generic
   * references never land in (or apply config onto) a named instance; those
   * are only reached by name (sidebar row, ⌘K/menu instance rows).
   * `forceNew` always mints (the explicit "open fresh" gesture).
   */
  function resolveToolInstance(fullToolId: string, projectId?: number | null, opts?: { forceNew?: boolean }): { instanceId: string, existing: boolean } {
    if (!opts?.forceNew) {
      const matching = tabs.value.filter(t =>
        t.type === 'tool' &&
        t.entityId === fullToolId &&
        (t.projectId ?? null) === (projectId ?? null) &&
        t.instanceId &&
        !t.customName
      )
      if (matching.length > 0) {
        const best = matching.reduce((a, b) =>
          (b.lastActivatedAt ?? 0) > (a.lastActivatedAt ?? 0) ||
          ((b.lastActivatedAt ?? 0) === (a.lastActivatedAt ?? 0) && b.displayOrder > a.displayOrder) ? b : a)
        return { instanceId: best.instanceId!, existing: true }
      }
    }
    return { instanceId: nextToolInstanceId(), existing: false }
  }

  /**
   * Find an open tool-instance tab.
   */
  function getToolInstanceTab(fullToolId: string, projectId: number | null | undefined, instanceId: string): WorkspaceTab | undefined {
    return tabs.value.find(t => t.id === makeTabId('tool', fullToolId, projectId ?? undefined, instanceId))
  }

  /**
   * Stamp a tab as just-activated (drives most-recent instance resolution).
   */
  function markTabActivated(tabId: string) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (tab) {
      tab.lastActivatedAt = Date.now()
      tabs.value = [...tabs.value]
    }
  }

  /**
   * Set or clear a tool tab's user-given name. Purely local (a window title):
   * displayName keeps the tool name.
   */
  function updateTabCustomName(tabId: string, name: string | null) {
    const tab = tabs.value.find(t => t.id === tabId)
    if (!tab || tab.type !== 'tool') return
    const trimmed = (name || '').trim()
    if (trimmed) tab.customName = trimmed
    else delete tab.customName
    tabs.value = [...tabs.value]
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

    // Backend pins are tool-level; only call the API when this is the first
    // pinned instance of the tool.
    if (tab.type === 'tool' && !tabs.value.some(t => t.type === 'tool' && t.pinned && t.entityId === tab.entityId)) {
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

    // Backend pins are tool-level; only unpin the API when no other pinned
    // instance of this tool remains.
    if (tab.type === 'tool' && !tabs.value.some(t => t.type === 'tool' && t.pinned && t.entityId === tab.entityId && t.id !== tab.id)) {
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
      // Backend pin order is tool-level: dedupe multiple pinned instances of
      // the same tool, keeping first occurrence in display order.
      const pinnedToolIds = [...new Set(reordered.filter(t => t.type === 'tool').map(t => t.entityId))]
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
    // NEVER create tabs before the profile's tabs have loaded: instance ids
    // are unique, so a tab minted against an incomplete list is a permanent
    // duplicate once the real list arrives. Pins reconcile again after load
    // (profile-changed handler / pin events).
    if (!tabsLoadedForProfile) return

    const apiPinnedIds = new Set(pinnedToolsFromApi.map(t => t.full_tool_id))

    // Backend pins are tool-level; ensure each API-pinned tool has at least
    // one pinned instance tab (any project scope counts).
    for (const tool of pinnedToolsFromApi) {
      const matching = tabs.value.filter(t => t.type === 'tool' && t.entityId === tool.full_tool_id)
      if (matching.length > 0) {
        for (const t of matching) {
          if (t.displayName !== tool.name) t.displayName = tool.name
        }
        if (!matching.some(t => t.pinned)) {
          const best = matching.reduce((a, b) => (b.lastActivatedAt ?? 0) > (a.lastActivatedAt ?? 0) ? b : a)
          best.pinned = true
        }
      } else {
        const instanceId = nextToolInstanceId()
        tabs.value.push({
          id: makeTabId('tool', tool.full_tool_id, undefined, instanceId),
          type: 'tool',
          entityId: tool.full_tool_id,
          pinned: true,
          displayOrder: nextDisplayOrder++,
          displayName: tool.name,
          instanceId,
          feedScope: toolInstanceFeedScope(tool.full_tool_id, undefined, instanceId),
          lastActivatedAt: Date.now()
        })
      }
    }

    // Unpin tool tabs whose tool is no longer pinned in API
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
    resolveToolInstance,
    getToolInstanceTab,
    markTabActivated,
    updateTabCustomName,
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
