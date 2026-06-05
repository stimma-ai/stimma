/**
 * LoRA Pool composable.
 *
 * Manages a per-tool pool of LoRAs that persists in localStorage.
 * Keyed by STP provider:tool ID (e.g. "comfyui:flux-klein-9b").
 *
 * Storage key: stimma_{profileId}_lorapool_{toolId}
 *
 * Data model: LoRAs are organized into named groups + an ungrouped bucket.
 * Legacy format (flat LoraPoolItem[]) is auto-migrated on load.
 */
import { ref } from 'vue'
import { makeProfileKey } from '../utils/storageKeys'

export interface LoraPoolItem {
  lora: string       // Path for backend (unique key) — also the opaque server id for cloud LoRAs
  weight: number     // 0-10, default 1.0
  enabled: boolean   // Toggle state
  /**
   * Display name override. Set when the `lora` key isn't human-readable
   * (e.g. cloud LoRAs use an opaque UUID as the key, but we want to show
   * the original filename in the pool UI).
   */
  name?: string
}

export interface LoraGroup {
  id: string           // unique ID
  label: string        // user-editable title
  items: LoraPoolItem[]
}

export interface LoraPool {
  groups: LoraGroup[]
  ungrouped: LoraPoolItem[]
}

export interface LoraOption {
  name: string
  path: string
}

function getPoolKey(toolId: string): string {
  return makeProfileKey('lorapool', toolId)
}

function generateGroupId(): string {
  return `g_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// Singleton state - shared across all component instances
const pools = ref<Record<string, LoraPool>>({})
const loadedToolIds = ref<Set<string>>(new Set())
// Version counter to force reactive updates when pools are mutated
const poolVersion = ref(0)

function bumpVersion() {
  poolVersion.value++
}

/**
 * Migrate legacy flat array format to grouped format.
 */
function migrateFromLegacy(data: any): LoraPool {
  if (Array.isArray(data)) {
    // Legacy format: LoraPoolItem[]
    const items = data.map(item => ({
      lora: item.lora || '',
      weight: typeof item.weight === 'number' ? item.weight : 1.0,
      enabled: item.enabled !== false
    }))
    return { groups: [], ungrouped: items }
  }
  // Already new format
  return data as LoraPool
}

/**
 * Validate and normalize a LoraPool structure.
 */
function normalizePool(data: any): LoraPool {
  if (!data || typeof data !== 'object') return { groups: [], ungrouped: [] }

  const pool = migrateFromLegacy(data)

  // Normalize groups
  pool.groups = (pool.groups || []).map(g => ({
    id: g.id || generateGroupId(),
    label: g.label || '',
    items: (g.items || []).map(normalizeItem)
  }))

  // Normalize ungrouped
  pool.ungrouped = (pool.ungrouped || []).map(normalizeItem)

  return pool
}

function normalizeItem(item: any): LoraPoolItem {
  return {
    lora: item.lora || '',
    weight: typeof item.weight === 'number' ? item.weight : 1.0,
    enabled: item.enabled !== false,
    ...(typeof item.name === 'string' && item.name ? { name: item.name } : {}),
  }
}

/**
 * Load pool from localStorage for a given model family.
 */
function loadPool(toolId: string): void {
  if (!toolId) return

  try {
    const key = getPoolKey(toolId)
    const saved = localStorage.getItem(key)
    if (saved) {
      const parsed = JSON.parse(saved)
      pools.value[toolId] = normalizePool(parsed)
    } else {
      pools.value[toolId] = { groups: [], ungrouped: [] }
    }
    loadedToolIds.value.add(toolId)
  } catch (err) {
    console.error(`Failed to load LoRA pool for ${toolId}:`, err)
    pools.value[toolId] = { groups: [], ungrouped: [] }
    loadedToolIds.value.add(toolId)
  }
}

/**
 * Save pool to localStorage for a given model family.
 */
function savePool(toolId: string): void {
  if (!toolId) return

  try {
    const key = getPoolKey(toolId)
    const pool = pools.value[toolId] || { groups: [], ungrouped: [] }
    localStorage.setItem(key, JSON.stringify(pool))
  } catch (err) {
    console.error(`Failed to save LoRA pool for ${toolId}:`, err)
  }
}

function ensureLoaded(toolId: string | null | undefined): LoraPool {
  // Read version to create reactive dependency
  void poolVersion.value
  if (!toolId) return { groups: [], ungrouped: [] }
  if (!loadedToolIds.value.has(toolId)) {
    loadPool(toolId)
  }
  return pools.value[toolId] || { groups: [], ungrouped: [] }
}

/**
 * Get the pool for a given model family.
 */
function getPool(toolId: string | null | undefined): LoraPool {
  return ensureLoaded(toolId)
}

/**
 * Get all LoRA items as a flat array (all groups + ungrouped).
 * Preserves order: groups first (in order), then ungrouped.
 */
function getAllItems(toolId: string | null | undefined): LoraPoolItem[] {
  const pool = ensureLoaded(toolId)
  const items: LoraPoolItem[] = []
  for (const group of pool.groups) {
    items.push(...group.items)
  }
  items.push(...pool.ungrouped)
  return items
}

/**
 * Set the entire pool for a model family.
 */
function setPool(toolId: string, pool: LoraPool): void {
  if (!toolId) return
  pools.value[toolId] = pool
  savePool(toolId)
  bumpVersion()
}

/**
 * Set pool from a flat items array (for controlled mode compatibility).
 * All items go to ungrouped, groups are preserved.
 */
function setPoolFlat(toolId: string, items: LoraPoolItem[]): void {
  if (!toolId) return
  // In flat mode, just put everything in ungrouped and clear groups
  pools.value[toolId] = { groups: [], ungrouped: items }
  savePool(toolId)
  bumpVersion()
}

/**
 * Find which container (group or ungrouped) a LoRA is in.
 * Returns { groupId, index } or { groupId: null, index } for ungrouped.
 */
function findLora(pool: LoraPool, loraPath: string): { groupId: string | null; index: number } | null {
  for (const group of pool.groups) {
    const idx = group.items.findIndex(item => item.lora === loraPath)
    if (idx !== -1) return { groupId: group.id, index: idx }
  }
  const idx = pool.ungrouped.findIndex(item => item.lora === loraPath)
  if (idx !== -1) return { groupId: null, index: idx }
  return null
}

/**
 * Get the items array that contains a LoRA (mutable reference).
 */
function getContainerItems(pool: LoraPool, groupId: string | null): LoraPoolItem[] {
  if (groupId === null) return pool.ungrouped
  const group = pool.groups.find(g => g.id === groupId)
  return group ? group.items : pool.ungrouped
}

/**
 * Add a LoRA to the pool (into ungrouped).
 */
function addToPool(toolId: string, lora: LoraOption, weight = 1.0, enabled = true): void {
  if (!toolId || !lora.path) return

  const pool = ensureLoaded(toolId)
  // Don't add if already in pool
  if (findLora(pool, lora.path)) return

  pool.ungrouped.push({
    lora: lora.path,
    weight,
    enabled,
    // Preserve the human-friendly name (LoraOption.name) on the pool item
    // so the UI can show e.g. "klein_snofs_v1_4.safetensors" instead of
    // the opaque cloud id we use as the key.
    ...(lora.name ? { name: lora.name } : {}),
  })
  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Remove a LoRA from the pool (from any group or ungrouped).
 */
function removeFromPool(toolId: string, loraPath: string): void {
  if (!toolId || !loraPath) return

  const pool = ensureLoaded(toolId)
  const location = findLora(pool, loraPath)
  if (!location) return

  const items = getContainerItems(pool, location.groupId)
  items.splice(location.index, 1)

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Toggle the enabled state of a LoRA.
 */
function toggleEnabled(toolId: string, loraPath: string): void {
  if (!toolId || !loraPath) return

  const pool = ensureLoaded(toolId)
  const location = findLora(pool, loraPath)
  if (!location) return

  const items = getContainerItems(pool, location.groupId)
  items[location.index] = { ...items[location.index], enabled: !items[location.index].enabled }

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Update the weight of a LoRA.
 */
function updateWeight(toolId: string, loraPath: string, weight: number): void {
  if (!toolId || !loraPath) return

  const pool = ensureLoaded(toolId)
  const location = findLora(pool, loraPath)
  if (!location) return

  const clampedWeight = Math.max(0, Math.min(10, weight))
  const roundedWeight = Math.round(clampedWeight * 100) / 100

  const items = getContainerItems(pool, location.groupId)
  items[location.index] = { ...items[location.index], weight: roundedWeight }

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Reorder a LoRA within its current container.
 */
function reorderInContainer(toolId: string, groupId: string | null, fromIndex: number, toIndex: number): void {
  if (!toolId) return

  const pool = ensureLoaded(toolId)
  const items = getContainerItems(pool, groupId)
  if (fromIndex < 0 || fromIndex >= items.length || toIndex < 0 || toIndex >= items.length) return

  const [item] = items.splice(fromIndex, 1)
  items.splice(toIndex, 0, item)

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Move a LoRA from one container to another.
 */
function moveToContainer(
  toolId: string,
  loraPath: string,
  targetGroupId: string | null,
  targetIndex?: number
): void {
  if (!toolId || !loraPath) return

  const pool = ensureLoaded(toolId)
  const location = findLora(pool, loraPath)
  if (!location) return

  // Remove from source
  const sourceItems = getContainerItems(pool, location.groupId)
  const [item] = sourceItems.splice(location.index, 1)

  // Add to target
  const targetItems = getContainerItems(pool, targetGroupId)
  if (targetIndex !== undefined && targetIndex >= 0 && targetIndex <= targetItems.length) {
    targetItems.splice(targetIndex, 0, item)
  } else {
    targetItems.push(item)
  }

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

// ── Group CRUD ──────────────────────────────────────────────

/**
 * Create a new empty group.
 */
function createGroup(toolId: string, label = ''): string {
  if (!toolId) return ''

  const pool = ensureLoaded(toolId)
  const id = generateGroupId()
  pool.groups.push({ id, label, items: [] })

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  return id
}

/**
 * Rename a group.
 */
function renameGroup(toolId: string, groupId: string, label: string): void {
  if (!toolId || !groupId) return

  const pool = ensureLoaded(toolId)
  const group = pool.groups.find(g => g.id === groupId)
  if (!group) return

  group.label = label
  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Explode a group: move all its items to ungrouped and remove the group.
 */
function explodeGroup(toolId: string, groupId: string): void {
  if (!toolId || !groupId) return

  const pool = ensureLoaded(toolId)
  const groupIndex = pool.groups.findIndex(g => g.id === groupId)
  if (groupIndex === -1) return

  const group = pool.groups[groupIndex]
  pool.ungrouped.push(...group.items)
  pool.groups.splice(groupIndex, 1)

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Remove a group (same as explode — items go to ungrouped).
 */
function removeGroup(toolId: string, groupId: string): void {
  return explodeGroup(toolId, groupId)
}

/**
 * Reorder groups.
 */
function reorderGroups(toolId: string, fromIndex: number, toIndex: number): void {
  if (!toolId) return

  const pool = ensureLoaded(toolId)
  if (fromIndex < 0 || fromIndex >= pool.groups.length || toIndex < 0 || toIndex >= pool.groups.length) return

  const [group] = pool.groups.splice(fromIndex, 1)
  pool.groups.splice(toIndex, 0, group)

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

// ── Bulk operations ─────────────────────────────────────────

/**
 * Solo-enable: enable only the given LoRA, disable all others across all groups.
 */
function soloEnable(toolId: string, loraPath: string): void {
  if (!toolId || !loraPath) return

  const pool = ensureLoaded(toolId)

  for (const group of pool.groups) {
    group.items = group.items.map(item => ({
      ...item,
      enabled: item.lora === loraPath
    }))
  }
  pool.ungrouped = pool.ungrouped.map(item => ({
    ...item,
    enabled: item.lora === loraPath
  }))

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Merge incoming LoRAs into the pool (for "Send to Generate" / loading image config).
 * - Disable all existing LoRAs not in the incoming set
 * - Add missing LoRAs to ungrouped
 * - Update weights of existing LoRAs
 * - Enable all incoming LoRAs
 */
function mergeIntoPool(
  toolId: string,
  incomingLoras: Array<{ lora: string; weight: number; enabled?: boolean }>
): void {
  if (!toolId) return

  const pool = ensureLoaded(toolId)
  const incomingPaths = new Set((incomingLoras || []).map(l => l.lora).filter(Boolean))

  // Helper to update items in a container
  function updateItems(items: LoraPoolItem[]): LoraPoolItem[] {
    return items.map(item => {
      if (incomingPaths.has(item.lora)) {
        const incoming = incomingLoras.find(l => l.lora === item.lora)!
        return { ...item, weight: incoming.weight, enabled: true }
      }
      return { ...item, enabled: false }
    })
  }

  // Update all groups
  for (const group of pool.groups) {
    group.items = updateItems(group.items)
  }
  pool.ungrouped = updateItems(pool.ungrouped)

  // Add new LoRAs that aren't in any container
  for (const incoming of (incomingLoras || [])) {
    if (!incoming.lora) continue
    if (!findLora(pool, incoming.lora)) {
      pool.ungrouped.push({
        lora: incoming.lora,
        weight: incoming.weight,
        enabled: true
      })
    }
  }

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Get enabled LoRAs formatted for backend submission.
 */
function getEnabledLoras(toolId: string | null | undefined): Array<{ lora: string; weight: number }> {
  if (!toolId) return []

  const items = getAllItems(toolId)
  return items
    .filter(item => item.enabled && item.lora)
    .map(item => ({
      lora: item.lora,
      weight: item.weight
    }))
}

/**
 * Remove all disabled (unselected) items from the pool.
 */
function removeDisabled(toolId: string): void {
  if (!toolId) return
  const pool = ensureLoaded(toolId)

  pool.ungrouped = pool.ungrouped.filter(i => i.enabled)
  pool.groups = pool.groups
    .map(g => ({ ...g, items: g.items.filter(i => i.enabled) }))
    .filter(g => g.items.length > 0)

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

/**
 * Clear the pool for a model family.
 */
function clearPool(toolId: string): void {
  if (!toolId) return

  pools.value[toolId] = { groups: [], ungrouped: [] }
  savePool(toolId)
  bumpVersion()
}

/**
 * Reload pools when profile changes.
 */
function handleProfileChanged(): void {
  loadedToolIds.value.clear()
  pools.value = {}
}

// Listen for profile and account changes
if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', handleProfileChanged)
}

/**
 * Sync a flat items array into the pool, preserving group structure.
 * Updates existing items in-place (weight, enabled), adds new ones to ungrouped,
 * removes items not in the incoming array.
 */
function syncItemsToPool(toolId: string, items: LoraPoolItem[]): void {
  if (!toolId) return

  const pool = ensureLoaded(toolId)
  const incomingMap = new Map(items.map(i => [i.lora, i]))
  const seen = new Set<string>()

  // Update existing items in groups
  for (const group of pool.groups) {
    group.items = group.items
      .filter(item => incomingMap.has(item.lora))
      .map(item => {
        const incoming = incomingMap.get(item.lora)!
        seen.add(item.lora)
        return { ...item, weight: incoming.weight, enabled: incoming.enabled }
      })
  }

  // Update existing items in ungrouped
  pool.ungrouped = pool.ungrouped
    .filter(item => incomingMap.has(item.lora))
    .map(item => {
      const incoming = incomingMap.get(item.lora)!
      seen.add(item.lora)
      return { ...item, weight: incoming.weight, enabled: incoming.enabled }
    })

  // Add new items to ungrouped
  for (const item of items) {
    if (!seen.has(item.lora)) {
      pool.ungrouped.push({ ...item })
    }
  }

  pools.value[toolId] = { ...pool }
  savePool(toolId)
  bumpVersion()
}

// ── Legacy compatibility ────────────────────────────────────

/**
 * Legacy: get pool as flat array (for backward compat with controlled mode).
 */
function getPoolFlat(toolId: string | null | undefined): LoraPoolItem[] {
  return getAllItems(toolId)
}

/**
 * Legacy: reorder in the flat list (maps to reorder within ungrouped).
 * @deprecated Use reorderInContainer instead.
 */
function reorderPool(toolId: string, fromIndex: number, toIndex: number): void {
  reorderInContainer(toolId, null, fromIndex, toIndex)
}

/**
 * LoRA Pool composable.
 * Returns the same singleton state for all callers.
 */
export function useLoraPool() {
  return {
    pools,
    getPool,
    getPoolFlat,
    getAllItems,
    setPool,
    setPoolFlat,
    addToPool,
    removeFromPool,
    toggleEnabled,
    updateWeight,
    reorderPool,
    reorderInContainer,
    moveToContainer,
    mergeIntoPool,
    syncItemsToPool,
    getEnabledLoras,
    clearPool,
    removeDisabled,
    loadPool,
    findLora,
    // Group operations
    createGroup,
    renameGroup,
    explodeGroup,
    removeGroup,
    reorderGroups,
    soloEnable,
  }
}
