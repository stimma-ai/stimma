import { computed, effectScope, reactive, unref, watch, type Ref } from 'vue'
import { makeStorageKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'

interface ChatDraft {
  text: string
  attachments: any[]
}

// Drafts belong to conversations, not mounted views. Keep the reactive object
// stable so sidebar drops and embedded/standalone composers share one draft.
const drafts = new Map<string, ChatDraft>()
const DRAFT_SYNC_DELAY_MS = 1000
let applyingRemote = false

export function getChatDraft(chatId: string | number): ChatDraft {
  const key = makeStorageKey('chat', chatId, 'draft')
  let draft = drafts.get(key)
  if (draft) return draft
  let saved: Partial<ChatDraft> = {}
  try {
    saved = JSON.parse(syncedStorage.getItem(key) || '{}') || {}
  } catch { /* An unreadable draft must not prevent opening a chat. */ }
  draft = reactive({
    text: typeof saved.text === 'string' ? saved.text : '',
    attachments: Array.isArray(saved.attachments) ? saved.attachments.filter(a => a && typeof a === 'object') : [],
  })
  drafts.set(key, draft)
  const state = draft
  // A draft follows you to other clients, and sending clears it everywhere.
  syncedStorage.subscribe(key, (value) => {
    let next: Partial<ChatDraft> = {}
    try { next = JSON.parse(value || '{}') || {} } catch { return }
    applyingRemote = true
    state.text = typeof next.text === 'string' ? next.text : ''
    state.attachments = Array.isArray(next.attachments) ? next.attachments : []
    applyingRemote = false
  })
  // Detached from the first view's lifecycle; drops may arrive with no view.
  effectScope(true).run(() => watch(state, () => {
    try {
      applyingRemote || (!state.text && !state.attachments.length
        ? syncedStorage.removeItem(key)
        : syncedStorage.setItem(key, JSON.stringify(state), { delayMs: DRAFT_SYNC_DELAY_MS }))
    } catch { /* Keep the in-memory draft even if browser storage is full. */ }
  }, { deep: true, flush: 'sync' }))
  return state
}

export function useChatDraft(chatId: Ref<string | number | null>) {
  const empty = reactive<ChatDraft>({ text: '', attachments: [] })
  const draft = computed(() => {
    const id = unref(chatId)
    return id == null ? empty : getChatDraft(id)
  })
  const text = computed({ get: () => draft.value.text, set: value => { draft.value.text = value } })
  const attachments = computed({ get: () => draft.value.attachments, set: value => { draft.value.attachments = value } })
  return { draft, text, attachments }
}
