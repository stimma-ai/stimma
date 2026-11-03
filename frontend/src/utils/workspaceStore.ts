/**
 * The shared workspace, as this client sees it.
 *
 * Every client of a profile reads and writes one set of documents on the server
 * (see backend/workspace_service.py). This module holds them in memory so reads
 * stay synchronous, sends changes in the background, and applies other clients'
 * changes as they arrive.
 *
 * A server too old to have a workspace leaves the store in local mode, where
 * `syncedStorage` is plain localStorage, under the same keys as always.
 *
 * Conflict rules, for one person moving between clients:
 *   - Object documents merge per top-level key; the last write to reach the
 *     server wins that key. A key changed here and not yet acknowledged is kept
 *     over anything arriving.
 *   - Writing what the document already holds sends nothing, so a client that
 *     merely applied a change never writes it back.
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { getAppModifier, getSandbox } from '../appConfig'
import { getCurrentDbGuid, getCurrentProfileId } from '../composables/useProfile'

export const TAB_NAMESPACE = 'tab'
const KV_NAMESPACE = 'kv'
const BLOB_NAMESPACE = 'blob'

const DEFAULT_DELAY_MS = 250
const RETRY_MS = 3000
const OUTBOX_PART = 'workspace_outbox'

export interface RemoteChange {
  /** Top-level keys that changed; null when the whole document did. */
  changedKeys: string[] | null
  deleted: boolean
  /** True on a full re-read (profile switch, reconnect), not a live edit. */
  rehydrated: boolean
  /** What this client held before the change; undefined if it held nothing. */
  previous?: unknown
}

type DocListener = (key: string, value: unknown, change: RemoteChange) => void
type KeyListener = (value: string | null, change: RemoteChange) => void

interface Doc {
  value: unknown
  rev: number
}

interface PendingOp {
  namespace: string
  key: string
  dueAt: number
  value?: unknown
  hasValue?: boolean
  set?: Record<string, unknown>
  unset?: Set<string>
  deleted?: boolean
}

function randomId(): string {
  // crypto.randomUUID is secure-context-only; dev servers can be plain http.
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`
}

const clientId = randomId()
const docs = new Map<string, Doc>()
let closedTabs: unknown[] = []
const outbox = new Map<string, PendingOp>()
let inflight = new Map<string, PendingOp>()
const namespaceListeners = new Map<string, Set<DocListener>>()
const keyListeners = new Map<string, Set<KeyListener>>()

let serverMode = false
let hydrated = false
let flushTimer: ReturnType<typeof setTimeout> | null = null
let flushing = false
let offline = false
let boundProfile: string | null = null
// Documents changed by events while a full read is in flight; that read may
// predate them, so it must not undo them.
let touchedDuringRead: Set<string> | null = null

const docId = (namespace: string, key: string) => `${namespace}\u0000${key}`
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b)

// --- Reading ---

export function isServerMode(): boolean {
  return serverMode
}

export function isWorkspaceHydrated(): boolean {
  return hydrated
}

export function getDoc<T = unknown>(namespace: string, key: string): T | undefined {
  return docs.get(docId(namespace, key))?.value as T | undefined
}

export function listDocs<T = unknown>(namespace: string): Array<{ key: string; value: T }> {
  const prefix = `${namespace}\u0000`
  const found: Array<{ key: string; value: T }> = []
  for (const [id, doc] of docs) {
    if (id.startsWith(prefix)) found.push({ key: id.slice(prefix.length), value: doc.value as T })
  }
  return found
}

export function getClosedTabs<T = unknown>(): T[] {
  return closedTabs as T[]
}

// --- Writing ---

/** Replace a document, sending only the top-level keys that differ. */
export function writeDoc(namespace: string, key: string, value: unknown, delayMs = DEFAULT_DELAY_MS): void {
  if (!hydrated) return
  const id = docId(namespace, key)
  const current = docs.get(id)
  if (current && same(current.value, value)) return

  const dueAt = Date.now() + delayMs
  const pending = outbox.get(id)
  // A merge needs a live document on the server: one we've read, or a
  // replacement queued or on its way ahead of this write.
  const canMerge = isObject(value) && isObject(current?.value) &&
    !pending?.deleted && !inflight.get(id)?.deleted &&
    ((current?.rev ?? 0) > 0 || !!pending?.hasValue || !!inflight.get(id)?.hasValue)

  if (pending?.hasValue || !canMerge) {
    outbox.set(id, { namespace, key, hasValue: true, value, dueAt })
  } else {
    const op: PendingOp = pending && !pending.deleted ? pending : { namespace, key, dueAt, set: {}, unset: new Set() }
    const before = current!.value as Record<string, unknown>
    const after = value as Record<string, unknown>
    for (const k of new Set([...Object.keys(before), ...Object.keys(after)])) {
      if (!(k in after)) {
        delete op.set![k]
        op.unset!.add(k)
      } else if (!same(before[k], after[k])) {
        op.unset!.delete(k)
        op.set![k] = after[k]
      }
    }
    op.dueAt = dueAt
    // Only the key order differed: nothing to say.
    if (pending || Object.keys(op.set!).length || op.unset!.size) outbox.set(id, op)
  }
  docs.set(id, { value, rev: current?.rev ?? 0 })
  scheduleFlush()
}

export function deleteDoc(namespace: string, key: string, delayMs = DEFAULT_DELAY_MS): void {
  if (!hydrated) return
  const id = docId(namespace, key)
  if (!docs.has(id) && !outbox.has(id)) return
  docs.delete(id)
  outbox.set(id, { namespace, key, deleted: true, dueAt: Date.now() + delayMs })
  scheduleFlush()
}

/**
 * Take `value` as what this client holds without sending it. For after applying
 * another client's change: settling it can rewrite values (constraints,
 * normalization), and writing those back would have two clients correcting each
 * other. The next real edit sends only what it changes.
 */
export function adoptDoc(namespace: string, key: string, value: unknown): void {
  const id = docId(namespace, key)
  const current = docs.get(id)
  if (!current || !hydrated) return
  docs.set(id, { value, rev: current.rev })
}

function serializeOp(op: PendingOp) {
  const base = { namespace: op.namespace, key: op.key }
  if (op.deleted) return { ...base, deleted: true }
  if (op.hasValue) return { ...base, value: op.value }
  return { ...base, set: op.set, unset: [...(op.unset ?? [])] }
}

function scheduleFlush() {
  if (flushTimer) clearTimeout(flushTimer)
  if (flushing || outbox.size === 0) return
  let due = Infinity
  for (const op of outbox.values()) due = Math.min(due, op.dueAt)
  flushTimer = setTimeout(flush, Math.max(0, due - Date.now()))
}

function requeue(ops: Map<string, PendingOp>) {
  // A newer write to the same document stays newer.
  for (const [id, op] of ops) {
    const newer = outbox.get(id)
    if (!newer) {
      outbox.set(id, op)
    } else if (!newer.hasValue && !newer.deleted && !op.deleted) {
      if (op.hasValue) {
        const merged = isObject(op.value) ? { ...op.value } : op.value
        if (isObject(merged)) {
          Object.assign(merged, newer.set)
          for (const k of newer.unset ?? []) delete merged[k]
        }
        outbox.set(id, { ...newer, set: undefined, unset: undefined, hasValue: true, value: merged })
      } else {
        const set = { ...op.set, ...newer.set }
        const unset = new Set([...(op.unset ?? []), ...(newer.unset ?? [])])
        for (const k of Object.keys(newer.set ?? {})) unset.delete(k)
        for (const k of newer.unset ?? []) delete set[k]
        outbox.set(id, { ...newer, set, unset })
      }
    }
  }
}

async function flush(force = false): Promise<void> {
  flushTimer = null
  if (flushing || outbox.size === 0 || !serverMode) return
  const now = Date.now()
  for (const [id, op] of outbox) {
    if (force || op.dueAt <= now) {
      inflight.set(id, op)
      outbox.delete(id)
    }
  }
  if (inflight.size === 0) {
    scheduleFlush()
    return
  }
  flushing = true
  const profile = boundProfile
  // Leaving the profile replaces `inflight`: this batch is then no longer part of
  // what the window holds, whatever becomes of it.
  const batch = inflight
  const ops = [...batch.values()].map(serializeOp)
  try {
    await axios.post(
      `${getApiBase()}/workspace/docs`,
      { origin: clientId, ops },
      { profileId: profile } as object,
    )
    // A document created here now exists on the server, so later writes can merge.
    // Other revisions come only from reads and events: the response to this write
    // can overtake another client's earlier event, which must still apply.
    if (batch === inflight) {
      for (const [id, op] of batch) {
        const doc = docs.get(id)
        if (doc && op.hasValue && doc.rev === 0) doc.rev = 1
      }
    }
    batch.clear()
    setOffline(false)
  } catch (error: any) {
    const status = error?.response?.status
    if (status === 413 || status === 422 || status === 409) {
      // The server refuses this batch and always will; retrying would wedge
      // every later write behind it.
      console.error('[workspace] write refused', status, [...batch.keys()])
      batch.clear()
    } else if (batch !== inflight) {
      saveUnsent(profile, ops)
    } else {
      requeue(batch)
      batch.clear()
      setOffline(true)
      for (const op of outbox.values()) op.dueAt = Math.max(op.dueAt, Date.now() + RETRY_MS)
    }
  } finally {
    flushing = false
  }
  persistOutbox()
  scheduleFlush()
}

function setOffline(next: boolean) {
  offline = next
}

// While the server can't be reached, unsent changes also survive a restart.
function outboxStorageKey(profile: string | null): string {
  return `${basePrefix()}_${profile}_${OUTBOX_PART}`
}

function persistOutbox(force = false) {
  if (!boundProfile) return
  const key = outboxStorageKey(boundProfile)
  try {
    if (outbox.size === 0 && inflight.size === 0) {
      if (localStorage.getItem(key) !== null) localStorage.removeItem(key)
    } else if (offline || force) {
      const ops = [...inflight.values(), ...outbox.values()].map(serializeOp)
      localStorage.setItem(key, JSON.stringify(ops))
    }
  } catch { /* Storage full: the unsent changes stay in memory. */ }
}

/** Keep changes that belong to a profile this window has left, for its next visit. */
function saveUnsent(profile: string | null, ops: unknown[]) {
  if (!profile) return
  const key = outboxStorageKey(profile)
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '[]')
    localStorage.setItem(key, JSON.stringify([...saved, ...ops]))
  } catch { /* Storage full: nothing more can be done for them. */ }
}

function restoreOutbox(profile: string) {
  const key = outboxStorageKey(profile)
  let ops: any[] = []
  try {
    ops = JSON.parse(localStorage.getItem(key) || '[]')
  } catch { /* unreadable: nothing to restore */ }
  for (const op of ops) {
    if (!op || typeof op.namespace !== 'string' || typeof op.key !== 'string') continue
    const id = docId(op.namespace, op.key)
    const pending: PendingOp = { namespace: op.namespace, key: op.key, dueAt: 0 }
    const current = docs.get(id)
    if (op.deleted) {
      pending.deleted = true
      docs.delete(id)
    } else if ('value' in op) {
      pending.hasValue = true
      pending.value = op.value
      docs.set(id, { value: op.value, rev: current?.rev ?? 0 })
    } else {
      pending.set = op.set ?? {}
      pending.unset = new Set(op.unset ?? [])
      if (!isObject(current?.value)) continue
      const merged = { ...current!.value, ...pending.set }
      for (const k of pending.unset) delete merged[k]
      docs.set(id, { value: merged, rev: current!.rev })
    }
    outbox.set(id, pending)
  }
}

/** Send everything now, e.g. before a profile switch or the page going away. */
export function flushWorkspace(): void {
  void flush(true)
  persistOutbox(true)
}

// --- Other clients' changes ---

export function onNamespaceChange(namespace: string, listener: DocListener): () => void {
  let set = namespaceListeners.get(namespace)
  if (!set) namespaceListeners.set(namespace, (set = new Set()))
  set.add(listener)
  return () => set!.delete(listener)
}

function notify(namespace: string, key: string, value: unknown, change: RemoteChange) {
  for (const listener of namespaceListeners.get(namespace) ?? []) {
    try { listener(key, value, change) } catch (error) { console.error('[workspace] listener failed', error) }
  }
  if (namespace !== KV_NAMESPACE) return
  for (const listener of keyListeners.get(key) ?? []) {
    try { listener(decodeValue(value), change) } catch (error) { console.error('[workspace] listener failed', error) }
  }
}

// Anything holding a value across a profile switch re-reads when this fires.
function notifyHydrated() {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('workspace-loaded'))
}

function overlayPending(id: string, value: unknown): unknown {
  // What this client has yet to get acknowledged stays on top, oldest first.
  let next = value
  for (const op of [inflight.get(id), outbox.get(id)]) {
    if (!op) continue
    if (op.deleted) return undefined
    if (op.hasValue) {
      next = op.value
    } else if (isObject(next)) {
      next = { ...next, ...op.set }
      for (const k of op.unset ?? []) delete (next as Record<string, unknown>)[k]
    }
  }
  return next
}

async function refetch(namespace: string, key: string) {
  try {
    const { data } = await axios.get(
      `${getApiBase()}/workspace/docs/${encodeURIComponent(namespace)}/${encodeURI(key)}`,
    )
    const id = docId(namespace, key)
    const current = docs.get(id)
    if (current && data.rev <= current.rev) return
    const next = overlayPending(id, data.value)
    docs.set(id, { value: next, rev: data.rev })
    notify(namespace, key, next, { changedKeys: null, deleted: false, rehydrated: false, previous: current?.value })
  } catch { /* The next reconnect re-reads everything. */ }
}

function applyRemoteChange(change: any) {
  const { namespace, key, rev } = change
  const id = docId(namespace, key)
  touchedDuringRead?.add(id)
  const current = docs.get(id)
  if (current && rev <= current.rev) return

  if (change.refetch) {
    void refetch(namespace, key)
    return
  }
  const dirty = !!outbox.get(id) || !!inflight.get(id)

  if (change.deleted) {
    if (dirty) return
    if (!current) return
    if (namespace === TAB_NAMESPACE) closedTabs = [current.value, ...closedTabs].slice(0, 20)
    docs.delete(id)
    notify(namespace, key, undefined, { changedKeys: null, deleted: true, rehydrated: false, previous: current.value })
    return
  }

  if ('value' in change) {
    const next = overlayPending(id, change.value)
    docs.set(id, { value: next, rev })
    if (namespace === TAB_NAMESPACE) closedTabs = closedTabs.filter((tab: any) => tab?.id !== key)
    notify(namespace, key, next, { changedKeys: null, deleted: false, rehydrated: false, previous: current?.value })
    return
  }

  if (!current || !isObject(current.value)) {
    // A field update for a document we don't hold (or hold in another shape).
    void refetch(namespace, key)
    return
  }
  const outgoing = new Set<string>()
  for (const op of [inflight.get(id), outbox.get(id)]) {
    if (op?.hasValue) {
      // Our whole-document write is on top of anything arriving.
      docs.set(id, { value: current.value, rev })
      return
    }
    for (const k of Object.keys(op?.set ?? {})) outgoing.add(k)
    for (const k of op?.unset ?? []) outgoing.add(k)
  }
  const next = { ...current.value }
  const changedKeys: string[] = []
  for (const [k, v] of Object.entries(change.set ?? {})) {
    if (outgoing.has(k)) continue
    next[k] = v
    changedKeys.push(k)
  }
  for (const k of change.unset ?? []) {
    if (outgoing.has(k)) continue
    delete next[k]
    changedKeys.push(k)
  }
  docs.set(id, { value: next, rev })
  if (changedKeys.length) notify(namespace, key, next, { changedKeys, deleted: false, rehydrated: false, previous: current.value })
}

/** Called for `workspace_docs_changed` events. */
export function handleWorkspaceEvent(data: any): void {
  if (!serverMode || !hydrated || data?.origin === clientId) return
  for (const change of data?.changes ?? []) applyRemoteChange(change)
}

// --- Loading ---

interface Snapshot {
  docs: Array<{ namespace: string; key: string; value: unknown; rev: number }>
  closed_tabs?: unknown[]
  migration?: { claimed?: boolean }
}

export async function readSnapshot(): Promise<Snapshot> {
  const { data } = await axios.get(`${getApiBase()}/workspace`)
  return data
}

/** Install a full read. Fires listeners for whatever it changed. */
export function installSnapshot(snapshot: Snapshot, profile: string, first: boolean): void {
  const previous = first ? new Map<string, Doc>() : new Map(docs)
  const skip = touchedDuringRead
  touchedDuringRead = null
  if (first) {
    docs.clear()
    outbox.clear()
  }
  boundProfile = profile
  serverMode = true
  hydrated = true
  closedTabs = snapshot.closed_tabs ?? []

  const seen = new Set<string>()
  const updates: Array<[string, string, unknown, unknown]> = []
  for (const doc of snapshot.docs) {
    const id = docId(doc.namespace, doc.key)
    seen.add(id)
    if (skip?.has(id)) continue
    const old = previous.get(id)
    if (old && old.rev > doc.rev) continue
    const value = overlayPending(id, doc.value)
    if (value === undefined) continue
    docs.set(id, { value, rev: doc.rev })
    if (!first && (!old || !same(old.value, value))) updates.push([doc.namespace, doc.key, value, old?.value])
  }
  const removed: Array<[string, string]> = []
  if (!first) {
    for (const [id] of previous) {
      if (seen.has(id) || skip?.has(id) || outbox.has(id) || inflight.has(id)) continue
      const [namespace, key] = id.split('\u0000')
      docs.delete(id)
      removed.push([namespace, key])
    }
  }
  if (first) restoreOutbox(profile)
  notifyHydrated()

  for (const [namespace, key] of removed) {
    notify(namespace, key, undefined, { changedKeys: null, deleted: true, rehydrated: true })
  }
  for (const [namespace, key, value, previous] of updates) {
    notify(namespace, key, value, { changedKeys: null, deleted: false, rehydrated: true, previous })
  }
  scheduleFlush()
}

/** Re-read after a reconnect or another client's import. */
export async function rehydrate(): Promise<void> {
  if (!serverMode || !hydrated) return
  const profile = boundProfile
  touchedDuringRead = new Set()
  try {
    const snapshot = await readSnapshot()
    if (profile !== getCurrentProfileId() || !profile) return
    installSnapshot(snapshot, profile, false)
  } catch {
    touchedDuringRead = null
  }
  void flush(true)
}

/** This server has a workspace, not yet read: reads are empty, writes dropped. */
export function beginHydration(): void {
  serverMode = true
  hydrated = false
  docs.clear()
  closedTabs = []
}

/** This server has no workspace: everything is local storage. */
export function useLocalStorageOnly(): void {
  serverMode = false
  hydrated = false
  boundProfile = null
  docs.clear()
  outbox.clear()
  inflight.clear()
  closedTabs = []
}

/**
 * The window has changed profile. What's unsent goes to the one it left, and
 * stops being part of what this window holds. If it can't get there it waits for
 * the next visit.
 */
export function detachProfile(): void {
  const profile = boundProfile
  if (flushTimer) clearTimeout(flushTimer)
  flushTimer = null
  const ops = [...outbox.values()].map(serializeOp)
  outbox.clear()
  inflight = new Map()
  hydrated = false
  boundProfile = null
  // Everything saved for it is in hand now, and is put back only if it fails.
  if (profile) localStorage.removeItem(outboxStorageKey(profile))
  if (!profile || !ops.length) return
  void axios.post(`${getApiBase()}/workspace/docs`, { origin: clientId, ops }, { profileId: profile } as object)
    .catch(() => saveUnsent(profile, ops))
}

// --- Keys ---

function basePrefix(): string {
  const modifier = getAppModifier()
  return modifier ? `stimma_${modifier}_${getSandbox()}` : 'stimma'
}

/**
 * The document name for a storage key: the key without what scoped it to a
 * server, channel and profile, since the server's copy can't belong to anything
 * else. Keys it doesn't recognize are not this profile's, and stay local.
 */
export function docKeyFor(fullKey: string, profile: string | null = getCurrentProfileId()): string | null {
  const base = basePrefix()
  const dbGuid = getCurrentDbGuid()
  for (const token of [profile, dbGuid, 'global']) {
    if (!token) continue
    const prefix = `${base}_${token}_`
    if (fullKey.startsWith(prefix)) return fullKey.slice(prefix.length)
  }
  return null
}

function encodeValue(raw: string): unknown {
  if (raw.startsWith('{')) {
    try { return JSON.parse(raw) } catch { /* keep the string */ }
  }
  return raw
}

function decodeValue(value: unknown): string | null {
  if (value === undefined || value === null) return null
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export { encodeValue as encodeStoredValue }

/**
 * The storage interface for anything that belongs to the shared workspace.
 * Takes the same keys as localStorage (from makeProfileKey and friends) and
 * stands in for it at those call sites.
 */
export const syncedStorage = {
  getItem(fullKey: string): string | null {
    const key = serverMode ? docKeyFor(fullKey) : null
    if (key === null) return localStorage.getItem(fullKey)
    return decodeValue(getDoc(KV_NAMESPACE, key))
  },

  setItem(fullKey: string, value: string, options?: { delayMs?: number }): void {
    const key = serverMode ? docKeyFor(fullKey) : null
    if (key === null) {
      localStorage.setItem(fullKey, value)
      return
    }
    writeDoc(KV_NAMESPACE, key, encodeValue(value), options?.delayMs)
  },

  removeItem(fullKey: string): void {
    const key = serverMode ? docKeyFor(fullKey) : null
    if (key === null) {
      localStorage.removeItem(fullKey)
      return
    }
    deleteDoc(KV_NAMESPACE, key)
  },

  /** Every stored key starting with `fullPrefix`, as full keys. */
  keysWithPrefix(fullPrefix: string): string[] {
    const stem = serverMode ? docKeyFor(fullPrefix) : null
    if (stem === null) {
      const found: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (key?.startsWith(fullPrefix)) found.push(key)
      }
      return found
    }
    return listDocs(KV_NAMESPACE)
      .filter(({ key }) => key.startsWith(stem))
      .map(({ key }) => fullPrefix + key.slice(stem.length))
  },

  /** Remove every stored key containing `marker`, in whichever store is live. */
  removeKeysContaining(marker: string): void {
    if (serverMode) {
      for (const { key } of listDocs(KV_NAMESPACE)) {
        if (key.includes(marker)) deleteDoc(KV_NAMESPACE, key)
      }
      return
    }
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (key?.includes(marker)) localStorage.removeItem(key)
    }
  },

  /**
   * Hear about other clients' changes to one key. Fires on this client's own
   * re-reads too (`rehydrated`), never for writes made here. No-op in local mode,
   * where nothing else writes.
   */
  subscribe(fullKey: string, listener: KeyListener): () => void {
    // The doc name is resolved per event: settings may arrive after subscribing.
    const wrapped: DocListener = (key, value, change) => {
      if (key === docKeyFor(fullKey)) listener(decodeValue(value), change)
    }
    return onNamespaceChange(KV_NAMESPACE, wrapped)
  },

  /** See adoptDoc. */
  adopt(fullKey: string, value: string): void {
    const key = serverMode ? docKeyFor(fullKey) : null
    if (key !== null) adoptDoc(KV_NAMESPACE, key, encodeValue(value))
  },
}

// --- Stored files, for values too large for documents ---

export function blobDocKey(fullKey: string): string | null {
  return serverMode ? docKeyFor(fullKey) : null
}

export function listBlobDocs(fullPrefix?: string): string[] {
  const stem = fullPrefix ? blobDocKey(fullPrefix) : ''
  if (stem === null) return []
  return listDocs(BLOB_NAMESPACE)
    .filter(({ key }) => key.startsWith(stem))
    .map(({ key }) => (fullPrefix ?? '') + key.slice(stem.length))
}

export async function fetchBlobDoc(key: string): Promise<string | null> {
  try {
    const { data } = await axios.get(`${getApiBase()}/workspace/blobs/${encodeURI(key)}`, { responseType: 'text', transformResponse: x => x })
    return data
  } catch (error: any) {
    if (error?.response?.status === 404) return null
    throw error
  }
}

export async function storeBlobDoc(key: string, body: string, options?: { ifAbsent?: boolean }): Promise<void> {
  const { data } = await axios.put(`${getApiBase()}/workspace/blobs/${encodeURI(key)}`, body, {
    params: { origin: clientId, if_absent: options?.ifAbsent ?? false },
    headers: { 'Content-Type': 'application/octet-stream' },
  })
  // Keep the listing current without waiting for the event we'll ignore.
  for (const change of data?.changes ?? []) {
    docs.set(docId(change.namespace, change.key), { value: {}, rev: change.rev })
  }
}

export function removeBlobDoc(key: string): void {
  deleteDoc(BLOB_NAMESPACE, key, 0)
}

export const WORKSPACE_CLIENT_ID = clientId

// The page going away is the last chance to send what's waiting.
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flushWorkspace)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushWorkspace()
  })
}
