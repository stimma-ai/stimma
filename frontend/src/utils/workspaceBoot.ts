/**
 * Bringing this client onto the shared workspace: the first read of a profile,
 * and carrying over what it kept locally before the server held it.
 *
 * Migration rules:
 *   - One claim per profile, decided by the server. The first desktop with a
 *     workspace wins; a later one is archived there instead of merged.
 *   - Phones never claim. Their state is whatever they happened to visit, and
 *     keeping them out means launch order can't matter.
 *   - Only what stateRegistry marks as migrated leaves this client, and only for
 *     this server's profile. Local copies are left alone, so downgrading works.
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { desktop } from '../desktop'
import { getCurrentProfileId } from '../composables/useProfile'
import { useWebSocket } from '../composables/useWebSocket'
import { getBlob as getLocalBlob, listBlobKeys as listLocalBlobs } from './blobStorage'
import { makeInstallKey, makeProfileKey } from './storageKeys'
import { instanceOfKey, isMigratedBlobKey, isMigratedKey } from './stateRegistry'
import {
  TAB_NAMESPACE,
  beginHydration,
  detachProfile,
  docKeyFor,
  encodeStoredValue,
  handleWorkspaceEvent,
  installSnapshot,
  isWorkspaceHydrated,
  readSnapshot,
  rehydrate,
  storeBlobDoc,
  useLocalStorageOnly,
  WORKSPACE_CLIENT_ID,
} from './workspaceStore'

const READ_ATTEMPTS = 3
const READ_RETRY_MS = 500
const CLAIMED = 'claimed'

let capable = false
let listening = false
let activation = 0
let prepareLocalTabs: () => void = () => {}

let resolveReady: () => void = () => {}
let ready: Promise<void> = Promise.resolve()

/**
 * Resolves once a read of the workspace in progress has finished. The first read
 * starts with the settings response; tool routes wait for that via whenTabsReady.
 */
export function whenWorkspaceReady(): Promise<void> {
  return ready
}

function startReading() {
  const previous = resolveReady
  ready = new Promise(resolve => {
    resolveReady = () => {
      previous()
      resolve()
    }
  })
}

/** The tab module upgrades old local tabs before they're read for migration. */
export function registerLocalTabPreparation(prepare: () => void): void {
  prepareLocalTabs = prepare
}

function installationId(): string {
  const key = makeInstallKey('workspace_client_id')
  let id = localStorage.getItem(key)
  if (!id) {
    id = WORKSPACE_CLIENT_ID
    localStorage.setItem(key, id)
  }
  return id
}

function isPhone(): boolean {
  return desktop.kind === 'ios' || desktop.kind === 'android'
}

interface Upload {
  docs: Array<{ namespace: string; key: string; value: unknown }>
  instances: Set<string>
}

/** What this client holds for the current profile, by the registry's rules. */
export function collectLocalWorkspace(): Upload | null {
  prepareLocalTabs()
  let tabs: any[] = []
  try {
    const parsed = JSON.parse(localStorage.getItem(makeProfileKey('workspace_tabs')) || '[]')
    if (Array.isArray(parsed)) tabs = parsed
  } catch { /* A broken tab list is an empty one. */ }
  tabs = tabs.filter(tab => tab?.id && (tab.type !== 'editor' || String(tab.entityId).startsWith('asset:')))
  // No tabs means nothing here worth claiming for. Preferences alone stay put
  // rather than locking out a client that has a real workspace.
  if (tabs.length === 0) return null

  const instances = new Set<string>(tabs.filter(tab => tab.instanceId).map(tab => String(tab.instanceId)))
  const docs: Upload['docs'] = tabs.map(tab => ({ namespace: TAB_NAMESPACE, key: tab.id, value: tab }))
  for (let i = 0; i < localStorage.length; i++) {
    const fullKey = localStorage.key(i)
    if (!fullKey) continue
    const key = docKeyFor(fullKey)
    if (key === null || !isMigratedKey(key)) continue
    const instance = instanceOfKey(key)
    if (instance && !instances.has(instance)) continue
    const raw = localStorage.getItem(fullKey)
    if (raw !== null) docs.push({ namespace: 'kv', key, value: encodeStoredValue(raw) })
  }
  return { docs, instances }
}

/** Masks and paint layers go separately, after the claim that decides them. */
async function uploadLocalBlobs(instances: Set<string> | null): Promise<void> {
  const marker = makeProfileKey('workspace_blobs_migrated')
  if (localStorage.getItem(marker) !== null) return
  try {
    let live = instances
    if (!live) live = collectLocalWorkspace()?.instances ?? new Set()
    const uploaded = new Set<string>()
    for (const fullKey of await listLocalBlobs()) {
      const key = docKeyFor(fullKey)
      if (key === null || !isMigratedBlobKey(key)) continue
      const instance = instanceOfKey(key)
      if (!instance || !live.has(instance) || uploaded.has(key)) continue
      const value = await getLocalBlob(fullKey)
      if (value !== null) await storeBlobDoc(key, JSON.stringify(value), { ifAbsent: true })
      uploaded.add(key)
    }
    localStorage.setItem(marker, '1')
  } catch (error) {
    // Retried on the next launch; the claim doesn't depend on this.
    console.warn('[workspace] mask and paint upload incomplete:', error)
  }
}

async function migrateIfNeeded(): Promise<{ instances: Set<string> | null }> {
  const marker = makeProfileKey('workspace_migrated')
  const state = localStorage.getItem(marker)
  if (state !== null || isPhone()) return { instances: null }
  const upload = collectLocalWorkspace()
  if (!upload) return { instances: null }
  const { data } = await axios.post(`${getApiBase()}/workspace/migrate`, {
    client_id: installationId(),
    docs: upload.docs,
    meta: { kind: desktop.kind ?? 'browser' },
  })
  localStorage.setItem(marker, data.applied ? CLAIMED : 'archived')
  console.log('[workspace] local workspace', data.applied ? 'migrated' : 'archived', data.stats ?? '')
  return { instances: upload.instances }
}

async function readWithRetry() {
  let lastError: unknown
  for (let attempt = 0; attempt < READ_ATTEMPTS; attempt++) {
    try {
      return await readSnapshot()
    } catch (error: any) {
      lastError = error
      if (error?.response?.status === 403) break // Locked: unlocking re-activates.
      await new Promise(resolve => setTimeout(resolve, READ_RETRY_MS))
    }
  }
  throw lastError
}

function listenOnce() {
  if (listening) return
  listening = true
  const { on } = useWebSocket()
  on('workspace_docs_changed', handleWorkspaceEvent)
  on('workspace_reset', (data: any) => {
    if (data?.origin !== localStorage.getItem(makeInstallKey('workspace_client_id'))) void rehydrate()
  })
  on('websocket_reconnected', () => {
    if (!capable) return undefined
    return isWorkspaceHydrated() ? rehydrate() : activate()
  })
  // After profile-will-change, whose listeners save what's pending to the profile
  // being left. This runs first among profile-changed listeners, registered at boot.
  window.addEventListener('profile-changed', () => {
    if (!capable) return
    detachProfile()
    void activate()
  })
}

async function activate(): Promise<void> {
  const token = ++activation
  const profile = getCurrentProfileId()
  startReading()
  beginHydration()
  try {
    if (!profile) return
    const { instances } = await migrateIfNeeded()
    if (token !== activation) return
    const snapshot = await readWithRetry()
    if (token !== activation) return
    installSnapshot(snapshot, profile, true)
    if (localStorage.getItem(makeProfileKey('workspace_migrated')) === CLAIMED) void uploadLocalBlobs(instances)
  } catch (error) {
    // The next connection, or unlocking the profile, tries again.
    console.warn('[workspace] not available yet:', error)
  } finally {
    if (token === activation) resolveReady()
  }
}

/**
 * Called with the settings response, before anything reads the workspace. A
 * server that doesn't advertise a workspace leaves this client on local storage.
 */
export async function activateWorkspace(settings: { workspace_sync?: number }): Promise<void> {
  capable = !!settings.workspace_sync
  if (!capable) {
    useLocalStorageOnly()
    resolveReady()
    return
  }
  listenOnce()
  await activate()
}
