/**
 * The chat dock: chats shown small, along the bottom edge.
 *
 * A docked chat is an ordinary chat in a second size. Docking has nothing to
 * do with the sidebar's open tabs; a chat can be in either, both or neither.
 * Each docked chat is either a row (minimized) or an open window, and at most
 * MAX_OPEN windows are open at once: opening another folds the oldest open
 * one down to a row.
 *
 * What's docked, in what order and how, belongs to the workspace (it follows
 * the person to other clients), stored in its own document beside the tabs.
 * What each docked chat is doing right now (busy, needs you, progress) is
 * reported by its mounted ChatView and lives only in memory.
 */
import { computed, reactive, ref } from 'vue'
import router from '../router'
import { makeProfileKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'

import { foldOpenWindows, MAX_OPEN, sanitizeDock, type DockEntry, type DockWin } from '../utils/chatDockState'

export { MAX_OPEN }
export type { DockEntry, DockWin }

export interface DockPresence {
  name: string
  busy: boolean
  needsYou: boolean
  status: string
  /** 0..1 while a batch runs, else null. */
  progress: number | null
  /** Media to show on the row: what the last turn made, else what was sent. */
  peekMediaIds: number[]
  mcp: boolean
}

const entries = ref<DockEntry[]>([])
const presence = reactive(new Map<number, DockPresence>())
/** Windows that just folded to a row, so the row can flash once. */
const foldedAt = reactive(new Map<number, number>())
/** The open windows the dock is showing right now (set by ChatDock from its layout). */
export const visibleOpen = ref<Set<number>>(new Set())
const pendingInitial = new Map<number, { text: string; mediaIds: number[] }>()
/** A selection bar is up at the bottom of the screen: the phone's dock button rises above it. */
export const selectionBarUp = ref(false)
let loadedKey: string | null = null
let unsubscribe: (() => void) | null = null

const storageKey = () => makeProfileKey('chat_dock')

function read(): DockEntry[] {
  try { return sanitizeDock(JSON.parse(syncedStorage.getItem(storageKey()) || '{}')) } catch { return [] }
}

// Load lazily and again whenever the profile (and so the key) changes.
function ensureLoaded() {
  const key = storageKey()
  if (loadedKey === key) return
  loadedKey = key
  unsubscribe?.()
  entries.value = read()
  unsubscribe = syncedStorage.subscribe(key, (value) => {
    try { entries.value = sanitizeDock(JSON.parse(value || '{}')) } catch { /* keep what we have */ }
  })
}

// Another profile has its own dock.
if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', () => {
    loadedKey = null
    presence.clear()
    ensureLoaded()
  })
}

function save() {
  syncedStorage.setItem(storageKey(), JSON.stringify({ entries: entries.value }))
}

/** The chat shown full size right now; its dock window steps aside. */
export function chatOnScreen(): number | null {
  const route = router.currentRoute.value
  if (route.name !== 'chat') return null
  const id = Number(route.params.id)
  return Number.isFinite(id) ? id : null
}

function find(chatId: number) {
  return entries.value.find(e => e.chatId === chatId)
}

function update(chatId: number, patch: Partial<DockEntry>) {
  entries.value = entries.value.map(e => e.chatId === chatId ? { ...e, ...patch } : e)
}

// At most MAX_OPEN open windows (not counting one stepped aside for the full
// view); the oldest open ones fold to rows, and flash once as they do.
function foldExtras(keep: number) {
  const { entries: next, folded } = foldOpenWindows(entries.value, keep, chatOnScreen())
  entries.value = next
  for (const id of folded) foldedAt.set(id, Date.now())
}

export function useChatDock() {
  ensureLoaded()

  /** Newest first. */
  const docked = computed(() => [...entries.value].sort((a, b) => b.at - a.at))

  function dock(chatId: number, options: { open?: boolean; initial?: { text: string; mediaIds: number[] } | null } = {}) {
    const existing = find(chatId)
    if (existing) {
      if (options.open) open(chatId)
      return
    }
    if (options.initial) pendingInitial.set(chatId, options.initial)
    entries.value = [...entries.value, { chatId, win: options.open ? 'open' : 'row', at: Date.now() }]
    if (options.open) foldExtras(chatId)
    save()
  }

  /** `front` brings it to the corner (opened from "+N more"). */
  function open(chatId: number, options: { front?: boolean } = {}) {
    if (!find(chatId)) return dock(chatId, { open: true })
    update(chatId, options.front ? { win: 'open', at: Date.now() } : { win: 'open' })
    foldExtras(chatId)
    save()
  }

  function minimize(chatId: number) {
    if (!find(chatId)) return
    update(chatId, { win: 'row' })
    save()
  }

  function toggle(chatId: number) {
    find(chatId)?.win === 'open' ? minimize(chatId) : open(chatId)
  }

  function undock(chatId: number) {
    if (!find(chatId)) return
    entries.value = entries.value.filter(e => e.chatId !== chatId)
    presence.delete(chatId)
    save()
  }

  // The first message is this client's to send: it never goes into the
  // shared dock document, so another client can't send it too.
  function consumeInitial(chatId: number) {
    const initial = pendingInitial.get(chatId) ?? null
    pendingInitial.delete(chatId)
    return initial
  }

  function isDocked(chatId: number | null | undefined) {
    return chatId != null && !!find(Number(chatId))
  }

  /** An open window actually on screen (laid out by the dock, not folded, not stepped aside). */
  function isOpenInDock(chatId: number) {
    return visibleOpen.value.has(chatId)
  }

  function reportPresence(chatId: number, p: DockPresence) {
    presence.set(chatId, p)
  }

  return {
    entries, docked, presence, foldedAt,
    dock, open, minimize, toggle, undock, consumeInitial,
    isDocked, isOpenInDock, reportPresence,
  }
}

// Opening a chat full size from the dock at an artifact or shared file: the
// small window has no stage, so it hands the full view what to show.
export type StageIntent =
  | { kind: 'asset'; assetId: number; revisionId?: number | null }
  | { kind: 'file'; file: any }
  | { kind: 'settings' }
const stageIntents = new Map<number, StageIntent>()
export function setStageIntent(chatId: number, intent: StageIntent) {
  stageIntents.set(chatId, intent)
}
export function takeStageIntent(chatId: number): StageIntent | null {
  const intent = stageIntents.get(chatId) ?? null
  stageIntents.delete(chatId)
  return intent
}

/** Test hook: reset module state. */
export function _resetChatDockForTests() {
  entries.value = []
  presence.clear()
  foldedAt.clear()
  loadedKey = null
  unsubscribe?.()
  unsubscribe = null
}
