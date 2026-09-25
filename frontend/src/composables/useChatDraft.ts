import { computed, effectScope, reactive, unref, watch, type Ref } from 'vue'
import { makeStorageKey } from '../utils/storageKeys'

interface ChatDraft {
  text: string
  attachments: any[]
}

// Drafts belong to conversations, not mounted views. Keep the reactive object
// stable so sidebar drops and embedded/standalone composers share one draft.
const drafts = new Map<string, ChatDraft>()

export function getChatDraft(chatId: string | number): ChatDraft {
  const key = makeStorageKey('chat', chatId, 'draft')
  let draft = drafts.get(key)
  if (draft) return draft
  let saved: Partial<ChatDraft> = {}
  try {
    saved = JSON.parse(localStorage.getItem(key) || '{}') || {}
  } catch { /* An unreadable draft must not prevent opening a chat. */ }
  draft = reactive({
    text: typeof saved.text === 'string' ? saved.text : '',
    attachments: Array.isArray(saved.attachments) ? saved.attachments.filter(a => a && typeof a === 'object') : [],
  })
  drafts.set(key, draft)
  const state = draft
  // Detached from the first view's lifecycle; drops may arrive with no view.
  effectScope(true).run(() => watch(state, () => {
    try {
      if (!state.text && !state.attachments.length) localStorage.removeItem(key)
      else localStorage.setItem(key, JSON.stringify(state))
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
