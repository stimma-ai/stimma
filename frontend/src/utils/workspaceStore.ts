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
// Batches sent, or due to be sent again, and not yet acknowledged; oldest first.
// One is always resent whole under its id, so a batch the server committed but
// whose answer was lost isn't applied a second time over a later edit.
interface Batch {
  id: string
  ops: Map<string, PendingOp>
}
let unacked: Batch[] = []
const namespaceListeners = new Map<string, Set<DocListener>>()
const keyListeners = new Map<string, Set<KeyListener>>()

let serverMode = false
let hydrated = false
let flushTimer: ReturnType<typeof setTimeout> | null = null
let flushing = false
let offline = false
let retryAt = 0
let boundProfile: string | null = null
// Bumped whenever the documents held stop being the ones a read was made for.
let epoch = 0
// Documents changed by events while a full read is in flight, one set per read;
// that read may predate them, so it must not undo them.
const activeReads = new Set<Set<string>>()

const docId = (namespace: string, key: string) => `${namespace}\u0000${key}`
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b)

/** What's unacknowledged for a document, oldest first. */
function pendingOps(id: string): PendingOp[] {
  const found: PendingOp[] = []
  for (const batch of unacked) {
    const op = batch.ops.get(id)
    if (op) found.push(op)
  }
  const queued = outbox.get(id)
  if (queued) found.push(queued)
  return found
}

function lastSent(id: string): PendingOp | undefined {
  for (let i = unacked.length - 1; i >= 0; i--) {
    const op = unacked[i].ops.get(id)
    if (op) return op
  }
  return undefined
}

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
  const sent = lastSent(id)
  // A merge needs a live document on the server: one we've read, or a
  // replacement queued or on its way ahead of this write.
  const canMerge = isObject(value) && isObject(current?.value) &&
    !pending?.deleted && !sent?.deleted &&
    ((current?.rev ?? 0) > 0 || !!pending?.hasValue || !!sent?.hasValue)

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
  flushTimer = null
  if (flushing) return
  let due = Infinity
  if (unacked.length) due = retryAt
  else for (const op of outbox.values()) due = Math.min(due, op.dueAt)
  if (due === Infinity) return
  flushTimer = setTimeout(flush, Math.max(0, due - Date.now()))
}

/** `newer` applied over `older`, as one operation. */
function coalesce(older: PendingOp, newer: PendingOp): PendingOp {
  if (newer.hasValue || newer.deleted || older.deleted) return newer
  if (older.hasValue) {
    const merged = isObject(older.value) ? { ...older.value } : older.value
    if (isObject(merged)) {
      Object.assign(merged, newer.set)
      for (const k of newer.unset ?? []) delete merged[k]
    }
    return { ...newer, set: undefined, unset: undefined, hasValue: true, value: merged }
  }
  const set = { ...older.set, ...newer.set }
  const unset = new Set([...(older.unset ?? []), ...(newer.unset ?? [])])
  for (const k of Object.keys(newer.set ?? {})) unset.delete(k)
  for (const k of newer.unset ?? []) delete set[k]
  return { ...newer, set, unset }
}

const REFUSED = new Set([409, 413, 422])

async function postBatch(profile: string | null, batch: Batch) {
  const { data } = await axios.post(
    `${getApiBase()}/workspace/docs`,
    { origin: clientId, batch_id: batch.id, ops: [...batch.ops.values()].map(serializeOp) },
    { profileId: profile } as object,
  )
  return data
}

async function flush(force = false): Promise<void> {
  flushTimer = null
  if (flushing || !serverMode) return
  if (!unacked.length) {
    const now = Date.now()
    const ops = new Map<string, PendingOp>()
    for (const [id, op] of outbox) {
      if (force || op.dueAt <= now) {
        ops.set(id, op)
        outbox.delete(id)
      }
    }
    if (ops.size === 0) {
      scheduleFlush()
      return
    }
    unacked.push({ id: randomId(), ops })
    // A saved copy holds these as never sent; from now on it must know their id.
    if (hasSavedOutbox(boundProfile)) persistOutbox(true)
  } else if (!force && retryAt > Date.now()) {
    scheduleFlush()
    return
  }
  flushing = true
  const profile = boundProfile
  // Leaving the profile takes `unacked` with it (detachProfile sends it on): this
  // batch is then no longer part of what the window holds, whatever becomes of it.
  const batch = unacked[0]
  const owned = () => unacked[0] === batch
  let reread = false
  try {
    const data = await postBatch(profile, batch)
    if (!owned()) {
      if (profile) answeredAfterLeaving(profile, batch.id)
    } else {
      unacked.shift()
      // A read in flight may predate this write, which no longer overlays it.
      for (const touched of activeReads) for (const id of batch.ops.keys()) touched.add(id)
      // A document created here now exists on the server, so later writes can
      // merge. Other revisions come only from reads and events: the response to
      // this write can overtake another client's earlier event, which must still apply.
      for (const [id, op] of batch.ops) {
        const doc = docs.get(id)
        if (doc && op.hasValue && doc.rev === 0) doc.rev = 1
      }
      // Already applied once, before an answer that never arrived; anything since
      // may have replaced it, and only a read shows what.
      reread = !!data?.duplicate
      if (profile) forgetSaved(profile, batch.id)
      retryAt = 0
      setOffline(false)
    }
  } catch (error: any) {
    const status = error?.response?.status
    if (!owned()) {
      // detachProfile has it.
    } else if (REFUSED.has(status)) {
      // The server refuses this batch and always will; retrying would wedge
      // every later write behind it.
      console.error('[workspace] write refused', status, [...batch.ops.keys()])
      unacked.shift()
    } else {
      setOffline(true)
      retryAt = Date.now() + RETRY_MS
    }
  } finally {
    flushing = false
  }
  persistOutbox()
  if (reread) void rehydrate()
  else scheduleFlush()
}

function setOffline(next: boolean) {
  offline = next
}

// While the server can't be reached, unsent changes also survive a restart.
function outboxStorageKey(profile: string | null): string {
  return `${basePrefix()}_${profile}_${OUTBOX_PART}`
}

// Stored as a list of entries: a batch that may have reached the server keeps
// its id ({ batch, ops }); a bare op was never sent.
function persistOutbox(force = false) {
  if (!boundProfile) return
  const key = outboxStorageKey(boundProfile)
  try {
    if (outbox.size === 0 && unacked.length === 0) {
      if (localStorage.getItem(key) !== null) localStorage.removeItem(key)
    } else if (offline || force) {
      const entries = [...unacked.map(serializeBatch), ...[...outbox.values()].map(serializeOp)]
      localStorage.setItem(key, JSON.stringify(entries))
    }
  } catch { /* Storage full: the unsent changes stay in memory. */ }
}

function serializeBatch(batch: Batch) {
  return { batch: batch.id, ops: [...batch.ops.values()].map(serializeOp) }
}

function hasSavedOutbox(profile: string | null): boolean {
  try {
    return !!profile && localStorage.getItem(outboxStorageKey(profile)) !== null
  } catch {
    return false
  }
}

// A profile whose left-behind write landed after this window began reading it
// again: that read may predate the write (whose event this window ignores as its own).
let rereadFor: string | null = null

/** The server answered for a batch sent after the window left its profile. */
function answeredAfterLeaving(profile: string, batchId: string) {
  forgetSaved(profile, batchId)
  if (profile !== getCurrentProfileId()) return
  if (hydrated && boundProfile === profile) void rehydrate()
  else rereadFor = profile
}

/** A batch the server has answered for no longer needs its saved copy. */
function forgetSaved(profile: string, batchId: string) {
  const key = outboxStorageKey(profile)
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '[]')
    if (!Array.isArray(saved)) return
    const rest = saved.filter(entry => entry?.batch !== batchId)
    if (rest.length === saved.length) return
    if (rest.length) localStorage.setItem(key, JSON.stringify(rest))
    else localStorage.removeItem(key)
  } catch { /* Unreadable: the next visit resends, and the server ignores repeats. */ }
}

/** A saved op as pending, applied to what's held; null if it no longer applies. */
function restoreOp(op: any): PendingOp | null {
  if (!op || typeof op.namespace !== 'string' || typeof op.key !== 'string') return null
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
    if (!isObject(current?.value)) return null
    const merged = { ...current!.value, ...pending.set }
    for (const k of pending.unset) delete merged[k]
    docs.set(id, { value: merged, rev: current!.rev })
  }
  return pending
}

function restoreOutbox(profile: string) {
  const key = outboxStorageKey(profile)
  let entries: any[] = []
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '[]')
    if (Array.isArray(saved)) entries = saved
  } catch { /* unreadable: nothing to restore */ }
  for (const entry of entries) {
    if (typeof entry?.batch === 'string' && Array.isArray(entry.ops)) {
      if (unacked.some(batch => batch.id === entry.batch)) continue
      const ops = new Map<string, PendingOp>()
      for (const op of entry.ops) {
        const pending = restoreOp(op)
        if (pending) ops.set(docId(pending.namespace, pending.key), pending)
      }
      if (ops.size) unacked.push({ id: entry.batch, ops })
      continue
    }
    const pending = restoreOp(entry)
    if (!pending) continue
    // Several saved ops for one document are one change, in order.
    const id = docId(pending.namespace, pending.key)
    const earlier = outbox.get(id)
    outbox.set(id, earlier ? coalesce(earlier, pending) : pending)
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
  for (const op of pendingOps(id)) {
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
  const readFor = epoch
  try {
    const { data } = await axios.get(
      `${getApiBase()}/workspace/docs/${encodeURIComponent(namespace)}/${encodeURI(key)}`,
      { profileId: boundProfile } as object,
    )
    // The window moved on (another profile, or a fresh read) while this was out.
    if (readFor !== epoch) return
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
  for (const touched of activeReads) touched.add(id)
  const current = docs.get(id)
  if (current && rev <= current.rev) return

  if (change.refetch) {
    void refetch(namespace, key)
    return
  }
  const dirty = pendingOps(id).length > 0

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
  for (const op of pendingOps(id)) {
    if (op.hasValue) {
      // Our whole-document write is on top of anything arriving.
      docs.set(id, { value: current.value, rev })
      return
    }
    for (const k of Object.keys(op.set ?? {})) outgoing.add(k)
    for (const k of op.unset ?? []) outgoing.add(k)
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
export function installSnapshot(snapshot: Snapshot, profile: string, first: boolean, skip: Set<string> | null = null): void {
  const previous = first ? new Map<string, Doc>() : new Map(docs)
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
      if (seen.has(id) || skip?.has(id) || pendingOps(id).length) continue
      const [namespace, key] = id.split('\u0000')
      docs.delete(id)
      removed.push([namespace, key])
    }
  }
  if (first) restoreOutbox(profile)
  notifyHydrated()
  if (first && rereadFor === profile) {
    rereadFor = null
    void rehydrate()
  }

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
  const readFor = epoch
  const touched = new Set<string>()
  activeReads.add(touched)
  try {
    const snapshot = await readSnapshot()
    if (readFor !== epoch || profile !== getCurrentProfileId() || !profile) return
    installSnapshot(snapshot, profile, false, touched)
  } catch {
    // The next reconnect reads again.
  } finally {
    activeReads.delete(touched)
  }
  void flush(true)
}

/** This server has a workspace, not yet read: reads are empty, writes dropped. */
export function beginHydration(): void {
  epoch++
  serverMode = true
  hydrated = false
  docs.clear()
  closedTabs = []
}

/** This server has no workspace: everything is local storage. */
export function useLocalStorageOnly(): void {
  epoch++
  serverMode = false
  hydrated = false
  boundProfile = null
  docs.clear()
  outbox.clear()
  unacked = []
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
  const batches = [...unacked]
  if (outbox.size) batches.push({ id: randomId(), ops: new Map(outbox) })
  outbox.clear()
  unacked = []
  retryAt = 0
  epoch++
  activeReads.clear()
  hydrated = false
  boundProfile = null
  if (!profile) return
  // Saved first, so a page reload right after the switch loses nothing; each
  // copy goes once the server answers for it. Everything saved before is in
  // `batches` already (restored when the profile was read).
  try {
    if (batches.length) localStorage.setItem(outboxStorageKey(profile), JSON.stringify(batches.map(serializeBatch)))
    else localStorage.removeItem(outboxStorageKey(profile))
  } catch { /* Storage full: sending is all that's left. */ }
  if (batches.length) void sendInOrder(profile, batches)
}

// The first may still be on its way from flush; under the same id the server
// applies it once, whichever copy arrives first. Coming back to the profile
// restores what's still saved, and resends it ahead of anything new.
async function sendInOrder(profile: string, batches: Batch[]) {
  for (const batch of batches) {
    try {
      await postBatch(profile, batch)
    } catch (error: any) {
      // Anything else stays saved for the next visit, with what follows it.
      if (!REFUSED.has(error?.response?.status)) return
    }
    answeredAfterLeaving(profile, batch.id)
  }
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
