/**
 * Masks and paint layers: too large for documents, and part of a tool tab's
 * state, so they're stored as files on the server. Same interface as
 * blobStorage, which remains the store on an older server and for values that
 * never leave this client (one-time handoffs between tools).
 */
import * as local from './blobStorage'
import { isMigratedBlobKey } from './stateRegistry'
import {
  blobDocKey,
  fetchBlobDoc,
  listBlobDocs,
  onNamespaceChange,
  removeBlobDoc,
  storeBlobDoc,
} from './workspaceStore'

function serverKey(fullKey: string): string | null {
  const key = blobDocKey(fullKey)
  return key !== null && isMigratedBlobKey(key) ? key : null
}

export async function getBlob<T = unknown>(fullKey: string): Promise<T | null> {
  const key = serverKey(fullKey)
  if (key === null) return local.getBlob<T>(fullKey)
  const body = await fetchBlobDoc(key)
  return body === null ? null : (JSON.parse(body) as T)
}

export async function putBlob(fullKey: string, value: unknown): Promise<void> {
  const key = serverKey(fullKey)
  if (key === null) return local.putBlob(fullKey, value)
  await storeBlobDoc(key, JSON.stringify(value))
}

export async function deleteBlob(fullKey: string): Promise<void> {
  const key = serverKey(fullKey)
  if (key === null) return local.deleteBlob(fullKey)
  removeBlobDoc(key)
}

export async function listBlobKeys(fullPrefix: string): Promise<string[]> {
  return blobDocKey(fullPrefix) === null ? local.listBlobKeys(fullPrefix) : listBlobDocs(fullPrefix)
}

/** Hear about another client storing or removing this value. */
export function onBlobChange(fullKey: string, listener: () => void): () => void {
  return onNamespaceChange('blob', key => {
    if (key === serverKey(fullKey)) listener()
  })
}
