/**
 * Everything the app holds about one contact sheet on screen: its content,
 * the user's review (answers and comments, stored on the server by component
 * id), what is new since they last looked, and the tile selection.
 *
 * The sheet's HTML is the agent's. The review is the user's, and outlives any
 * rewrite of the HTML because it is keyed by component id.
 */
import axios from 'axios'
import { computed, inject, onBeforeUnmount, provide, ref, shallowRef, watch, type ComputedRef, type InjectionKey, type Ref } from 'vue'
import { getApiBase } from '../../apiConfig'
import { useWebSocket } from '../../composables/useWebSocket'
import { addToast } from '../../composables/useToasts'
import { makeProfileKey } from '../../utils/storageKeys'
import { syncedStorage } from '../../utils/workspaceStore'
import { mediaIdOfRef, sheetMediaList, type SheetContent, type SheetMediaEntry, type SheetMember } from './sheetHtml'

export interface SheetComment {
  id: number
  anchor: string
  value: string
  author: { kind: string; name: string | null }
  created_at: string | null
  sent: boolean
}

export interface SheetAnswer {
  value: unknown
  sent: boolean
  /** The agent has seen some value for this answer, so clearing it is news. */
  wasSent: boolean
}

export interface CommentTarget {
  id: string
  label: string
  x: number
  y: number
  up?: boolean
  mediaId?: number | null
}

export interface SheetSlideshowRequest {
  list: SheetMediaEntry[]
  index: number
  sheet: SheetContext
}

/** Provided by ChatView: open the app's slideshow over a sheet's media. */
export const SHEET_SLIDESHOW: InjectionKey<(request: SheetSlideshowRequest) => void> = Symbol('sheetSlideshow')

export interface SheetContext {
  content: Ref<SheetContent | null>
  root: Ref<HTMLElement | null>
  assetId: ComputedRef<number | null>
  chatId: ComputedRef<number | null>
  readonly: ComputedRef<boolean>
  mediaList: ComputedRef<SheetMediaEntry[]>
  member(mediaId: number | null | undefined): SheetMember | null
  refOf(componentId: string): string | null
  // new since you looked
  newIds: ComputedRef<Set<string>>
  newCount: ComputedRef<number>
  markSeen(mediaIds?: number[]): void
  flashIds: Ref<string[]>
  // selection
  selected: Ref<Set<string>>
  toggleSelect(id: string): void
  clearSelection(): void
  // review
  answers: Ref<Record<string, SheetAnswer>>
  comments: Ref<SheetComment[]>
  commentsFor(anchor: string): SheetComment[]
  setAnswer(anchor: string, value: unknown): void
  addComment(anchor: string, text: string): Promise<void>
  deleteComment(id: number): Promise<void>
  pendingCount: ComputedRef<number>
  pendingAnswerCount: ComputedRef<number>
  pendingCommentCount: ComputedRef<number>
  send(): Promise<void>
  sending: Ref<boolean>
  commentFor: Ref<CommentTarget | null>
  openSlideshow(componentId: string): void
}

const SHEET_CONTEXT: InjectionKey<SheetContext> = Symbol('contactSheet')

export function useSheetContext(): SheetContext {
  const context = inject(SHEET_CONTEXT)
  if (!context) throw new Error('contact sheet components must render inside ContactSheetViewer')
  return context
}

function seenKey(assetId: number) {
  return makeProfileKey('contact-sheet', assetId, 'seen')
}

function readSeen(assetId: number): Set<number> | null {
  try {
    const raw = syncedStorage.getItem(seenKey(assetId))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return new Set<number>(Array.isArray(parsed?.media) ? parsed.media : [])
  } catch {
    return null
  }
}

function writeSeen(assetId: number, seen: Set<number>) {
  try {
    syncedStorage.setItem(seenKey(assetId), JSON.stringify({ media: [...seen].slice(-4000) }))
  } catch { /* ignore */ }
}

export function provideContactSheet(options: {
  mediaId: Ref<number | null>
  chatId: Ref<number | string | null | undefined>
  readonly?: Ref<boolean>
}): SheetContext {
  const content = shallowRef<SheetContent | null>(null)
  const root = shallowRef<HTMLElement | null>(null)
  const assetId = computed(() => content.value?.asset_id ?? null)
  const chatId = computed(() => {
    const value = Number(options.chatId.value)
    return Number.isFinite(value) && value > 0 ? value : null
  })
  const readonly = computed(() => assetId.value == null || !!options.readonly?.value)
  const mediaList = computed(() => (root.value ? sheetMediaList(root.value) : []))

  const refsById = computed(() => {
    const out: Record<string, string> = {}
    root.value?.querySelectorAll('stimma-media').forEach(el => { if (el.id) out[el.id] = el.getAttribute('ref') || '' })
    return out
  })

  function member(mediaId: number | null | undefined) {
    if (mediaId == null) return null
    return content.value?.members?.[String(mediaId)] ?? null
  }

  // -- new since you looked --------------------------------------------------
  const seen = ref<Set<number> | null>(null)
  const flashIds = ref<string[]>([])
  watch(assetId, id => {
    if (id == null) { seen.value = null; return }
    const stored = readSeen(id)
    if (stored) { seen.value = stored; return }
    // First time this viewer opens the sheet: everything on it is the baseline.
    const baseline = new Set(mediaList.value.map(entry => entry.mediaId))
    seen.value = baseline
    writeSeen(id, baseline)
  }, { immediate: true })
  const newIds = computed(() => {
    const out = new Set<string>()
    if (!seen.value) return out
    for (const [id, ref] of Object.entries(refsById.value)) {
      const mediaId = mediaIdOfRef(ref)
      if (mediaId != null && !seen.value.has(mediaId)) out.add(id)
    }
    return out
  })
  const newCount = computed(() => {
    if (!seen.value) return 0
    return mediaList.value.filter(entry => !seen.value!.has(entry.mediaId)).length
  })
  function markSeen(mediaIds?: number[]) {
    if (assetId.value == null || !seen.value) return
    const next = new Set(seen.value)
    for (const id of mediaIds ?? mediaList.value.map(entry => entry.mediaId)) next.add(id)
    seen.value = next
    writeSeen(assetId.value, next)
  }

  // -- selection -------------------------------------------------------------
  const selected = ref<Set<string>>(new Set())
  function toggleSelect(id: string) {
    const next = new Set(selected.value)
    next.has(id) ? next.delete(id) : next.add(id)
    selected.value = next
  }
  function clearSelection() { selected.value = new Set() }

  // -- review ----------------------------------------------------------------
  const answers = ref<Record<string, SheetAnswer>>({})
  const comments = ref<SheetComment[]>([])
  const commentFor = ref<CommentTarget | null>(null)
  const sending = ref(false)
  const api = () => `${getApiBase()}/contact-sheets/${assetId.value}`

  async function loadReview() {
    if (assetId.value == null) {
      answers.value = {}
      comments.value = []
      return
    }
    try {
      const { data } = await axios.get(`${api()}/review`)
      const next: Record<string, SheetAnswer> = {}
      for (const [anchor, row] of Object.entries<any>(data.answers || {})) next[anchor] = { value: row.value, sent: row.sent, wasSent: !!row.was_sent }
      answers.value = next
      comments.value = (data.comments || []).map((row: any) => ({ ...row, value: String(row.value ?? '') }))
    } catch (error) {
      console.error('Failed to load the contact sheet review:', error)
    }
  }
  watch(assetId, loadReview, { immediate: true })

  const { on, off } = useWebSocket()
  const onReviewChanged = (data: { asset_id?: number }) => {
    if (data?.asset_id != null && data.asset_id === assetId.value) loadReview()
  }
  on('contact_sheet_review_changed', onReviewChanged)
  onBeforeUnmount(() => off('contact_sheet_review_changed', onReviewChanged))

  function commentsFor(anchor: string) {
    return comments.value.filter(c => c.anchor === anchor)
  }

  // Unsaved answers by anchor, and saves in flight. Send waits for both.
  const answerTimers = new Map<string, { timer: ReturnType<typeof setTimeout>; save: () => Promise<void> }>()
  const savesInFlight = new Set<Promise<void>>()
  function startSave(save: () => Promise<void>) {
    const running = save()
    savesInFlight.add(running)
    running.finally(() => savesInFlight.delete(running))
    return running
  }
  function setAnswer(anchor: string, value: unknown) {
    if (readonly.value) return
    const previous = answers.value[anchor]
    answers.value = { ...answers.value, [anchor]: { value, sent: false, wasSent: !!previous?.wasSent || !!previous?.sent } }
    const pending = answerTimers.get(anchor)
    if (pending) clearTimeout(pending.timer)
    const save = async () => {
      answerTimers.delete(anchor)
      await axios.put(`${api()}/review/answers/${encodeURIComponent(anchor)}`, { value })
    }
    // Free text settles before it's saved; everything else saves at once.
    const delay = typeof value === 'string' ? 400 : 0
    answerTimers.set(anchor, {
      save,
      timer: setTimeout(() => {
        startSave(save).catch(error => {
          console.error('Failed to save a review answer:', error)
          addToast("Couldn't save your answer. Try again.", 'error')
        })
      }, delay),
    })
  }
  /** Save everything still waiting; rejects if any save fails. */
  async function flushAnswers() {
    for (const { timer, save } of [...answerTimers.values()]) {
      clearTimeout(timer)
      startSave(save)
    }
    const results = await Promise.allSettled([...savesInFlight])
    if (results.some(result => result.status === 'rejected')) throw new Error('an answer did not save')
  }

  async function addComment(anchor: string, text: string) {
    if (readonly.value || !text.trim()) return
    try {
      const { data } = await axios.post(`${api()}/review/comments`, { anchor, text })
      comments.value = [...comments.value, { ...data, value: String(data.value ?? '') }]
    } catch (error) {
      console.error('Failed to save a comment:', error)
      addToast("Couldn't save your comment. Try again.", 'error')
    }
  }

  async function deleteComment(id: number) {
    try {
      await axios.delete(`${api()}/review/comments/${id}`)
      comments.value = comments.value.filter(c => c.id !== id)
      await loadReview()
    } catch (error) {
      console.error('Failed to delete a comment:', error)
      addToast("Couldn't delete the comment. Try again.", 'error')
    }
  }

  const isEmpty = (value: unknown) => value == null || value === false || value === '' || value === 0
    || (Array.isArray(value) && value.length === 0)
  // An unsent answer is news if it says something, or if it takes back one
  // the agent already has.
  const pendingAnswerCount = computed(() =>
    Object.values(answers.value).filter(a => !a.sent && (!isEmpty(a.value) || a.wasSent)).length)
  const pendingCommentCount = computed(() => comments.value.filter(c => !c.sent).length)
  const pendingCount = computed(() => pendingAnswerCount.value + pendingCommentCount.value)

  async function send() {
    if (readonly.value || chatId.value == null || sending.value) return
    sending.value = true
    try {
      try {
        await flushAnswers()
      } catch (error) {
        console.error('Failed to save the review before sending:', error)
        addToast("Couldn't save your review, so it wasn't sent. Try again.", 'error')
        return
      }
      const { data } = await axios.post(`${api()}/review/send`, { chat_id: chatId.value })
      if (!data?.sent) addToast('Nothing new to send.', 'info')
      await loadReview()
    } catch (error) {
      console.error('Failed to send the review:', error)
      addToast("Couldn't send your review. Try again.", 'error')
    } finally {
      sending.value = false
    }
  }

  const openSheetSlideshow = inject(SHEET_SLIDESHOW, null)
  const context: SheetContext = {
    content, root, assetId, chatId, readonly, mediaList, member,
    refOf: id => refsById.value[id] ?? null,
    newIds, newCount, markSeen, flashIds,
    selected, toggleSelect, clearSelection,
    answers, comments, commentsFor, setAnswer, addComment, deleteComment,
    pendingCount, pendingAnswerCount, pendingCommentCount, send, sending,
    commentFor,
    openSlideshow(componentId: string) {
      if (!openSheetSlideshow) return
      const mediaId = mediaIdOfRef(refsById.value[componentId])
      const list = mediaList.value
      const index = Math.max(0, list.findIndex(entry => entry.mediaId === mediaId))
      openSheetSlideshow({ list, index, sheet: context })
    },
  }
  provide(SHEET_CONTEXT, context)
  return context
}
