import { makeProfileKey, makeStorageKey } from './storageKeys'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

const DB_NAME = 'stimma-editor'
const STORE_NAME = 'projects'

let initialized = false

function pendingKey(): string {
  return makeProfileKey('image-editor', 'pending-privacy-scrub')
}

type AssetDeletionIntent = {
  assetId: number
  projectKeys: string[]
}

type MediaDeletionIntent = {
  mediaId: number
  projectKey: string
}

function intentKey(): string {
  return makeProfileKey('image-editor', 'pending-asset-deletions')
}

function pendingIntents(): AssetDeletionIntent[] {
  try {
    const value = JSON.parse(localStorage.getItem(intentKey()) || '[]')
    return Array.isArray(value)
      ? value.filter(
          (intent): intent is AssetDeletionIntent =>
            Number.isFinite(intent?.assetId)
            && Array.isArray(intent?.projectKeys)
            && intent.projectKeys.every((key: unknown) => typeof key === 'string'),
        )
      : []
  } catch {
    return []
  }
}

function writeIntents(intents: AssetDeletionIntent[]): void {
  if (intents.length) localStorage.setItem(intentKey(), JSON.stringify(intents))
  else localStorage.removeItem(intentKey())
}

function mediaIntentKey(): string {
  return makeProfileKey('image-editor', 'pending-media-deletions')
}

function pendingMediaIntents(): MediaDeletionIntent[] {
  try {
    const value = JSON.parse(localStorage.getItem(mediaIntentKey()) || '[]')
    return Array.isArray(value)
      ? value.filter(
          (intent): intent is MediaDeletionIntent =>
            Number.isFinite(intent?.mediaId) && typeof intent?.projectKey === 'string',
        )
      : []
  } catch {
    return []
  }
}

function writeMediaIntents(intents: MediaDeletionIntent[]): void {
  if (intents.length) localStorage.setItem(mediaIntentKey(), JSON.stringify(intents))
  else localStorage.removeItem(mediaIntentKey())
}

function pendingProjectKeys(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(pendingKey()) || '[]')
    return Array.isArray(value)
      ? value.filter((key): key is string => typeof key === 'string')
      : []
  } catch {
    return []
  }
}

function writePending(keys: string[]): void {
  const unique = [...new Set(keys)]
  if (unique.length) localStorage.setItem(pendingKey(), JSON.stringify(unique))
  else localStorage.removeItem(pendingKey())
}

function projectKey(mediaId: number): string {
  return makeStorageKey('image-editor', 'project', mediaId)
}

async function deleteProjectKeys(keys: string[]): Promise<void> {
  const exactKeys = [...new Set(keys)]
  if (!exactKeys.length || typeof indexedDB === 'undefined') return

  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onerror = () => reject(request.error)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => {
      const db = request.result
      const transaction = db.transaction(STORE_NAME, 'readwrite')
      const store = transaction.objectStore(STORE_NAME)
      for (const key of exactKeys) store.delete(key)
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
      transaction.onerror = () => {
        db.close()
        reject(transaction.error)
      }
    }
  })
}

export async function scrubDeletedAssetProjects(mediaIds: number[]): Promise<void> {
  const requested = [...new Set(mediaIds.map(Number).filter(Number.isFinite))]
  if (!requested.length) return
  const exactKeys = requested.map(projectKey)
  writePending([...pendingProjectKeys(), ...exactKeys])
  try {
    await deleteProjectKeys(exactKeys)
    const completed = new Set(exactKeys)
    writePending(pendingProjectKeys().filter((key) => !completed.has(key)))
    const lastEditedKey = makeProfileKey('image-editor', 'last-edited')
    const lastEdited = Number(localStorage.getItem(lastEditedKey))
    if (requested.includes(lastEdited)) localStorage.removeItem(lastEditedKey)
  } catch (error) {
    console.warn('[ImageEditor] Deferred deleted Asset autosave scrub:', error)
  }
}

export function prepareAssetProjectDeletion(
  assetId: number,
  mediaIds: number[],
): void {
  const projectKeys = [...new Set(mediaIds.map(Number).filter(Number.isFinite))]
    .map(projectKey)
  if (!projectKeys.length) return
  const remaining = pendingIntents().filter((intent) => intent.assetId !== assetId)
  writeIntents([...remaining, { assetId, projectKeys }])
}

export async function confirmAssetProjectDeletion(assetId: number): Promise<void> {
  const intents = pendingIntents()
  const intent = intents.find((candidate) => candidate.assetId === assetId)
  if (!intent) return
  writePending([...pendingProjectKeys(), ...intent.projectKeys])
  try {
    await deleteProjectKeys(intent.projectKeys)
    const completed = new Set(intent.projectKeys)
    writePending(pendingProjectKeys().filter((key) => !completed.has(key)))
    writeIntents(intents.filter((candidate) => candidate.assetId !== assetId))
  } catch (error) {
    console.warn('[ImageEditor] Confirmed Asset cleanup remains queued:', error)
  }
}

export function prepareMediaProjectDeletion(mediaIds: number[]): void {
  const requested = [...new Set(mediaIds.map(Number).filter(Number.isFinite))]
  const requestedSet = new Set(requested)
  const remaining = pendingMediaIntents().filter(
    (intent) => !requestedSet.has(intent.mediaId),
  )
  writeMediaIntents([
    ...remaining,
    ...requested.map((mediaId) => ({ mediaId, projectKey: projectKey(mediaId) })),
  ])
}

async function confirmMediaProjectDeletion(mediaIds: number[]): Promise<void> {
  const completedIds = new Set(mediaIds.map(Number).filter(Number.isFinite))
  const intents = pendingMediaIntents()
  const completed = intents.filter((intent) => completedIds.has(intent.mediaId))
  if (completed.length) {
    const keys = completed.map((intent) => intent.projectKey)
    writePending([...pendingProjectKeys(), ...keys])
    try {
      await deleteProjectKeys(keys)
      const completedKeys = new Set(keys)
      writePending(pendingProjectKeys().filter((key) => !completedKeys.has(key)))
    } catch (error) {
      console.warn('[ImageEditor] Confirmed Media cleanup remains queued:', error)
    }
  }
  writeMediaIntents(
    intents.filter((intent) => !completedIds.has(intent.mediaId)),
  )
}

async function reconcileAssetDeletionIntents(): Promise<void> {
  for (const intent of pendingIntents()) {
    try {
      await axios.get(`${getApiBase()}/assets/${intent.assetId}`)
      writeIntents(
        pendingIntents().filter(
          (candidate) => candidate.assetId !== intent.assetId,
        ),
      )
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        await confirmAssetProjectDeletion(intent.assetId)
      }
      // Network/auth failures keep the exact-key intent for a later startup.
    }
  }
}

async function reconcileMediaDeletionIntents(): Promise<void> {
  for (const intent of pendingMediaIntents()) {
    try {
      const response = await axios.get(
        `${getApiBase()}/deletion-status/media/${intent.mediaId}`,
      )
      if (response.data?.status === 'deleted') {
        await confirmMediaProjectDeletion([intent.mediaId])
      } else if (response.data?.status === 'live') {
        writeMediaIntents(
          pendingMediaIntents().filter(
            (candidate) => candidate.mediaId !== intent.mediaId,
          ),
        )
      }
    } catch {
      // Network/auth failures keep the exact-key intent for a later startup.
    }
  }
}

async function retryPendingProjectScrubs(): Promise<void> {
  const exactKeys = pendingProjectKeys()
  if (!exactKeys.length) return
  try {
    await deleteProjectKeys(exactKeys)
    writePending([])
  } catch (error) {
    console.warn('[ImageEditor] Pending autosave privacy scrub still deferred:', error)
  }
}

export function initEditorProjectPrivacyCleanup(
  wsOn: (event: string, handler: (data: Record<string, unknown>) => void) => unknown,
): void {
  if (initialized) return
  initialized = true

  const scrub = (data: Record<string, unknown>) => {
    const mediaIds = Array.isArray(data.media_ids)
      ? data.media_ids.map(Number)
      : []
    void scrubDeletedAssetProjects(mediaIds)
  }
  const confirmMedia = (data: Record<string, unknown>) => {
    const mediaIds = Array.isArray(data.media_ids)
      ? data.media_ids.map(Number)
      : []
    void confirmMediaProjectDeletion(mediaIds)
    void scrubDeletedAssetProjects(mediaIds)
  }

  wsOn('asset_identity_deleted', scrub)
  wsOn('asset_identities_deleted', scrub)
  wsOn('media_permanently_deleted', confirmMedia)
  wsOn('websocket_reconnected', () => {
    void retryPendingProjectScrubs()
    void reconcileAssetDeletionIntents()
    void reconcileMediaDeletionIntents()
  })
  void retryPendingProjectScrubs()
  void reconcileAssetDeletionIntents()
  void reconcileMediaDeletionIntents()
}
